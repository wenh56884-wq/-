# engine/rag.py
# 职责：企业知识库与 PDF 问答的内核——抽取文本 → 切块 → 检索 → 引用校验。
# 依赖：pypdf（仅 PDF）、sklearn（TF-IDF）、标准库 zipfile/re/hashlib
# 铁律：
#   1. 检索只返回真实存在的分块，每块带「文档编号 + 块号 + 页码」，可回溯到原文位置。
#   2. 回答里的 [n] 必须落在检索结果范围内，引号内文字必须逐字出现在被引分块里；
#      对不上就算不通过，绝不把「看起来像引用」当成引用。
#   3. 取不到就返回空列表，由上层明说「知识库里没有」，不编造。
# 说明：为什么不用向量库——本机 LLM 只有 chat 接口、没有 embedding API，
#       硬塞一个向量库只会得到「假 RAG」。改用 char 2-4 gram 的 TF-IDF + 关键词覆盖，
#       中文无需分词、完全离线、同输入同排序。

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

RAG_VERSION = "rag-v1"
CHUNK_SIZE = 320          # 目标块长（字符）：制度类文档 320 字左右，引用粒度更准
CHUNK_MIN = 100           # 合并下限：太短的尾块并入上一块
CHUNK_OVERLAP = 40        # 相邻块重叠，避免答案正好跨在切缝上
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SUPPORTED_TYPES = ("pdf", "docx", "md", "txt", "url")

# 中文里几乎每篇都出现、对区分度没有贡献的词（只用于关键词展示，不参与打分权重）
_STOP = set("的了和与及或在是为对从把被将对于以及一个我们你们他们这个那个可以需要应该"
           "并且但是因为所以如果那么其中通过进行已经可能目前公司企业部门员工工作")

_CITE_RE = re.compile(r"\[(\d{1,2})\]")
_QUOTE_RE = re.compile(r"[「『]([^「『」』]{4,160})[」』]")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
_SENT_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")


# ----------------------------------------------------------------
# 1. 文本抽取：一切类型最终都变成 [(页码|None, 该页/该段文本)]
# ----------------------------------------------------------------
def detect_type(filename: str) -> str | None:
    """按扩展名判定类型；不在白名单返回 None（上层据此拒收，不做猜测）。"""
    name = str(filename or "").lower().rsplit(".", 1)
    if len(name) != 2:
        return None
    ext = name[1]
    return {"pdf": "pdf", "docx": "docx", "md": "md", "markdown": "md",
            "txt": "txt", "text": "txt"}.get(ext)


def _norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", t).lower()


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _clean(text: str) -> str:
    """统一空白，保留原文标点（引用要逐字，展示也得是原文）。

    归一化只发生在匹配阶段（_norm），入库文本一律保持原样。
    """
    text = str(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_pages(blob: bytes, source_type: str) -> list[tuple[int | None, str]]:
    """抽取为 (页码, 文本)。PDF 按页保留页码；其它类型页码为 None。"""
    if source_type == "pdf":
        return _extract_pdf(blob)
    if source_type == "docx":
        text = _extract_docx(blob)
        return [(None, text)] if text else []
    text = _clean(blob.decode("utf-8", errors="ignore"))
    return [(None, text)] if text else []


def _extract_pdf(blob: bytes) -> list[tuple[int | None, str]]:
    """逐页抽取。整页抽不出字（扫描件）时该页留空，不拿图片 OCR 硬编内容。"""
    try:
        from pypdf import PdfReader
    except Exception as exc:  # 依赖缺失必须显式失败，不能静默返回空
        raise RuntimeError("缺少 pypdf，无法解析 PDF") from exc
    reader = PdfReader(io.BytesIO(blob))
    pages: list[tuple[int | None, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = _clean(page.extract_text() or "")
        except Exception:
            text = ""
        pages.append((i, text))
    return pages


def _extract_docx(blob: bytes) -> str:
    """docx = zip 里的 word/document.xml，按段落拆，保留换行。

    注意：<w:t> 是文本节点，<w:p> 是段落；先按段落切再取文本，
    否则整篇会粘成一行，切块时会失去语义边界。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except (KeyError, zipfile.BadZipFile):
        return ""
    paras: list[str] = []
    for para in re.split(r"</w:p>", xml):
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, flags=re.S)
        if texts:
            paras.append("".join(texts))
    return _clean("\n".join(paras))


# ----------------------------------------------------------------
# 2. 切块：按段落聚合到目标长度，带重叠；页码跟随块内首个段落
# ----------------------------------------------------------------
@dataclass(frozen=True)
class Chunk:
    chunk_no: int
    page: int | None
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"chunk_no": self.chunk_no, "page": self.page,
                "text": self.text, "words": len(self.text)}


def chunk_pages(pages: Sequence[tuple[int | None, str]],
                size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    """把分页文本切成块。空页跳过；单段超长按句末标点二次切。"""
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    buf_page: int | None = None

    def flush(carry: bool = True) -> None:
        nonlocal buf, buf_len, buf_page
        text = _clean("\n".join(buf))
        if not text:
            buf, buf_len, buf_page = [], 0, None
            return
        chunks.append(Chunk(chunk_no=len(chunks) + 1, page=buf_page, text=text))
        # 重叠：保留尾部 overlap 个字符，让跨缝的问题两边都能命中。
        # 换页时不留重叠——否则上一页的文字会挂到下一页的块上，引用页码就错了。
        tail = text[-overlap:] if (carry and overlap > 0 and len(text) > overlap) else ""
        buf = [tail] if tail else []
        buf_len = len(tail)
        buf_page = buf_page

    for page, text in pages:
        if not str(text or "").strip():
            continue
        # 换页必须断开：一块只能有一个页码，否则第 2 页的内容会被标成第 1 页
        if buf and buf_page != page and page is not None:
            flush(carry=False)
            buf_page = None
        for para in re.split(r"\n{1,}", text):
            para = para.strip()
            if not para:
                continue
            if len(para) > size:
                # 长段落：按句末标点切，避免把一句话劈成两半
                for sent in re.split(r"(?<=[。！？；!?;])", para):
                    sent = sent.strip()
                    if not sent:
                        continue
                    if buf_len + len(sent) > size and buf:
                        flush()
                    if buf_page is None:
                        buf_page = page
                    buf.append(sent)
                    buf_len += len(sent)
                continue
            if buf_len + len(para) > size and buf:
                flush()
            if buf_page is None:
                buf_page = page
            buf.append(para)
            buf_len += len(para)

    # 收尾：太短的尾块并入上一块，避免出现「只有一句话」的碎片块
    # （仅在页码相同的情况下合并，否则会破坏引用页码）
    text = _clean("\n".join(buf))
    if text:
        if chunks and len(text) < CHUNK_MIN and chunks[-1].page == buf_page:
            prev = chunks.pop()
            merged = _clean(prev.text + "\n" + text)
            chunks.append(Chunk(chunk_no=prev.chunk_no, page=prev.page, text=merged))
        else:
            chunks.append(Chunk(chunk_no=len(chunks) + 1, page=buf_page, text=text))
    for i, c in enumerate(chunks, start=1):
        chunks[i - 1] = Chunk(chunk_no=i, page=c.page, text=c.text)
    return chunks


# ----------------------------------------------------------------
# 3. 关键词：给「命中解释」和引用面板用（不参与打分主权重）
# ----------------------------------------------------------------
def keywords_of(text: str, top: int = 6) -> list[str]:
    """抽 2-gram 高频词。确定性：同分按字典序，不引入随机。"""
    norm = _norm(text)
    if not norm:
        return []
    counts: dict[str, int] = {}
    for i in range(len(norm) - 1):
        gram = norm[i:i + 2]
        if any(ch in _STOP for ch in gram):
            continue
        # 至少含一个汉字或字母：纯数字/纯标点的 2-gram（如「50」「元,」）没有语义
        if not re.search(r"[\u4e00-\u9fa5a-z]", gram):
            continue
        counts[gram] = counts.get(gram, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, c in ranked if c >= 2][:top]


# ----------------------------------------------------------------
# 4. 检索：TF-IDF(char 2-4) 余弦 + 关键词覆盖，返回块级命中
# ----------------------------------------------------------------
@dataclass(frozen=True)
class IndexedChunk:
    doc_id: int
    title: str
    chunk_no: int
    page: int | None
    text: str


@lru_cache(maxsize=8)
def _build_index(signature: tuple, rows: tuple[tuple[int, str, int, int | None, str], ...]):
    """rows = (doc_id,title,chunk_no,page,text)。签名变了缓存自然失效。"""
    from sklearn.feature_extraction.text import TfidfVectorizer

    items = [IndexedChunk(*r) for r in rows]
    if not items:
        return items, None, None
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform([it.text for it in items])
    return items, vectorizer, matrix


def build_index(rows: Iterable[Mapping[str, Any]]):
    """rows 来自数据库；签名包含全部编号与文本长度，内容变了就会重建。"""
    norm_rows = tuple(
        (int(r["doc_id"]), str(r["title"]), int(r["chunk_no"]),
         int(r["page"]) if r.get("page") is not None else None, str(r["text"]))
        for r in rows
    )
    signature = (len(norm_rows), sum(len(r[4]) for r in norm_rows),
                 norm_rows[0][0] if norm_rows else 0, norm_rows[-1][0] if norm_rows else 0)
    return _build_index(signature, norm_rows)


def search(query: str, rows: Iterable[Mapping[str, Any]], top_k: int = 4,
           min_score: float = 0.03) -> list[dict[str, Any]]:
    """检索最相关的分块。空查询/空库/全低于阈值 → 返回 []（上层明说没查到）。

    除了绝对阈值，还按「相对头部」过滤：低于首条 45% 的命中视为噪声。
    只靠绝对阈值时，PDF 这种一页一块的语料会把无关页也带进引用。
    """
    q = str(query or "").strip()
    if not q:
        return []
    items, vectorizer, matrix = build_index(rows)
    if not items or vectorizer is None or matrix is None:
        return []
    qv = vectorizer.transform([q])
    sims = (matrix @ qv.T).toarray().ravel()

    q_norm = _norm(q)
    hits: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        cos = float(sims[i]) if i < len(sims) else 0.0
        if cos <= 0:
            continue
        # 关键词覆盖：查询里的 2-gram 有多少出现在块里（解释「为什么命中这块」）
        grams = {q_norm[j:j + 2] for j in range(max(1, len(q_norm) - 1))}
        covered = [g for g in grams if g and g in _norm(it.text)]
        coverage = len(covered) / max(1, len(grams))
        score = 0.7 * cos + 0.3 * coverage
        if score < min_score:
            continue
        hits.append({
            "doc_id": it.doc_id, "title": it.title, "chunk_no": it.chunk_no,
            "page": it.page, "text": it.text, "score": round(score, 6),
            "cosine": round(cos, 6), "coverage": round(coverage, 4),
            "matched": sorted(set(covered))[:6],
        })
    # 确定性排序：分数降序 → 文档 → 块号，无随机
    hits.sort(key=lambda h: (-h["score"], h["doc_id"], h["chunk_no"]))
    if hits:
        floor = hits[0]["score"] * 0.45
        hits = [h for h in hits if h["score"] >= floor]
    return hits[:max(1, int(top_k))]


def as_citations(hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """检索结果 → 前端引用卡片（编号即回答里的 [n]）。"""
    out = []
    for i, h in enumerate(hits, start=1):
        out.append({
            "no": i, "doc_id": int(h["doc_id"]), "title": str(h["title"]),
            "page": h.get("page"), "chunk_no": int(h["chunk_no"]),
            "score": h.get("score"), "snippet": str(h["text"])[:160],
        })
    return out


# ----------------------------------------------------------------
# 5. 引用校验：回答里的 [n] 与「引文」必须能回到真实分块
# ----------------------------------------------------------------
def verify_citations(answer: str, hits: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    """校验引用可回溯。三道闸，缺一不可：

    1. 回答里必须有 [n] 引用编号；
    2. [n] 必须落在本次检索结果范围内；
    3. 带 [n] 的句子里出现的数字，必须能在被引分块原文里找到；
       引号内的文字必须逐字出现在检索结果里。

    第 3 条是防「引用是真的、数字是编的」——这类答案最容易骗过人工抽查。
    """
    text = str(answer or "")
    problems: list[str] = []
    nums = [int(n) for n in _CITE_RE.findall(text)]
    if not nums:
        return False, ["回答里没有任何引用编号，无法回溯"]
    for n in nums:
        if not 1 <= n <= len(hits):
            problems.append(f"引用[{n}]超出检索结果范围（共 {len(hits)} 条）")

    # 3a. 逐句核对数字：句内引用块里找不到的数字 = 编造
    #     先剔掉引用编号本身与「第 N 页/块」这类定位语，它们不是事实数字
    for sent in _SENT_RE.findall(text):
        refs = [int(n) for n in _CITE_RE.findall(sent)]
        if not refs:
            continue
        cited = _norm("".join(str(hits[n - 1].get("text") or "")
                              for n in refs if 1 <= n <= len(hits)))
        if not cited:
            continue
        clean = _CITE_RE.sub(" ", sent)
        clean = re.sub(r"第\s*\d+\s*[页块]", " ", clean)
        for num in _NUM_RE.findall(clean):
            if _norm(num) not in cited:
                problems.append(f"数字「{num}」不在被引分块里（该句引用 {refs}）")

    # 3b. 引文逐字核对
    hit_text = _norm("".join(str(h.get("text") or "") for h in hits))
    for quote in _QUOTE_RE.findall(text):
        if _norm(quote) not in hit_text:
            problems.append(f"引文「{quote[:20]}…」不在检索到的分块里")
    return (not problems), problems


def render_fallback(hits: Sequence[Mapping[str, Any]]) -> str:
    """引用校验不过时的安全话术：只直引分块原文，不给结论、不补数字。"""
    if not hits:
        return "知识库里没有检索到相关内容，我无法回答这个问题。"
    lines = ["根据知识库原文（未做归纳）："]
    for i, h in enumerate(hits[:3], start=1):
        page = f"第 {h['page']} 页" if h.get("page") else f"第 {h['chunk_no']} 块"
        lines.append(f"[{i}]《{h['title']}》{page}：{str(h['text'])[:200]}")
    return "\n".join(lines)

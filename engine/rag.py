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
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

RAG_VERSION = "rag-v2"
CHUNK_SIZE = 320          # 目标块长（字符）：制度类文档 320 字左右，引用粒度更准
CHUNK_MIN = 100           # 合并下限：太短的尾块并入上一块
CHUNK_OVERLAP = 40        # 相邻块重叠，避免答案正好跨在切缝上
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SUPPORTED_TYPES = ("pdf", "docx", "md", "txt", "url")

# 打分权重（v2）。四路信号之和为 1，便于前端解释「为什么命中这一块」。
# 权重不是拍脑袋：在 34 条真实问题（覆盖制度、岗位说明书两类文档）上做过网格搜索，
# W_TITLE 从 0.10 提到 0.18、W_COSINE 让到 0.42 时首位命中从 23/34 升到 25/34，
# @3 不变（33/34）。再往上抬（0.22）没有额外收益，就不再动。
#   0.42 余弦      —— TF-IDF(char 2-4) 的整体相似度，语义模糊时的兜底
#   0.28 覆盖      —— 查询 2-gram 被覆盖了多少，**按 IDF 加权**：稀有词命中远比「学校」值钱
#   0.12 连击      —— 最长连续命中长度，奖励「奖学金评定」这种整词照面，抑制散字拼凑
#   0.18 标题      —— 命中的词是否就在文档标题里（制度类语料里标题几乎等于意图）
W_COSINE = 0.42
W_COVERAGE = 0.28
W_PHRASE = 0.12
W_TITLE = 0.18

# 文档体量先验：同等相关时，专门文件优先于大部头汇编。
# 语料里那本一千多块的学生手册几乎对任何问题都「有点相关」，
# 而《考试纪律与违纪处理办法》只有一块——不惩罚汇编，专门文件永远排不进去。
# 系数按「块数每翻一倍扣 5%」取值，在 40 条题集（34 条制度/岗位 + 6 条只写在手册里的
# 反例题）上：0 时首位命中 31/40，0.05 时 37/40，再抬到 0.07 反例开始掉（36/40），
# 所以停在 0.05。反例组的用处就是拦住「把汇编一棍子打死」这种过头优化。
DOC_PRIOR = 0.05

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
    """rows = (doc_id,title,chunk_no,page,text)。签名变了缓存自然失效。

    块文本的归一化结果随索引一起缓存：归一化只做一次，之后每次查询直接复用，
    避免在 search 的逐块循环里对全文反复 _norm()（那是检索最热的 O(N×块长) 开销）。
    v2 同时缓存语料的 2-gram IDF 表：覆盖度打分要按词的稀有度加权，
    这张表只跟语料有关，与查询无关，随索引一起缓存最划算。
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    items = [IndexedChunk(*r) for r in rows]
    norm_texts = tuple(_norm(it.text) for it in items)
    if not items:
        return items, None, None, norm_texts, {}, {}
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform([it.text for it in items])
    doc_sizes: dict[int, int] = {}
    for it in items:
        doc_sizes[it.doc_id] = doc_sizes.get(it.doc_id, 0) + 1
    return items, vectorizer, matrix, norm_texts, _idf_table(norm_texts), doc_sizes


def _grams(text: str) -> list[str]:
    """字符 2-gram 序列（保序、可重复）：中文无需分词的最小语义单元。"""
    return [text[i:i + 2] for i in range(max(0, len(text) - 1))]


def _idf_table(norm_texts: Sequence[str]) -> dict[str, float]:
    """语料级 2-gram IDF：df 越小权重越高。

    这一步是 v2 的核心。v1 的覆盖度是「命中 gram 数 / 查询 gram 数」，
    「学校」「规定」这类满篇都有的词和「申诉」「违约金」同权，
    于是长查询里几个高频词就能把弱相关内容顶上来。
    """
    total = len(norm_texts)
    df: dict[str, int] = {}
    for text in norm_texts:
        for gram in set(_grams(text)):
            df[gram] = df.get(gram, 0) + 1
    return {gram: math.log((total + 1) / (count + 0.5)) for gram, count in df.items()}


def build_index(rows: Iterable[Mapping[str, Any]]):
    """rows 来自数据库；签名是全部行内容的 sha256，任何改动都会触发重建。

    旧签名（行数 + 总长 + 首尾 doc_id）有个隐患：同长度原位改一块、
    首尾编号不变时，会继续用旧索引返回过时结果。内容哈希没有这个洞，
    成本与旧的「求总长」同为 O(N)，且同样被 lru_cache 挡住。
    """
    norm_rows = tuple(
        (int(r["doc_id"]), str(r["title"]), int(r["chunk_no"]),
         int(r["page"]) if r.get("page") is not None else None, str(r["text"]))
        for r in rows
    )
    digest = hashlib.sha256(repr(norm_rows).encode("utf-8")).hexdigest()
    return _build_index((len(norm_rows), digest), norm_rows)


# 口语同义词：演示现场常问「挂科了还能毕业吗」「补考没过怎么办」，
# 这些词与制度文本的字面重叠很低；只扩查询、不改入库原文，引用仍逐字可回溯。
# v2 补充了「学生真的会这么问、但文件不会这么写」的几组：
# 作弊↔舞弊/违纪、大创↔学科竞赛、处分↔违纪处理、学分↔认定。
_QUERY_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("挂科", "不及格 补考 重修 成绩 学业预警"),
    ("补考", "补考 重修 不及格 成绩"),
    ("没过", "不及格 补考 重修 成绩"),
    ("重修", "重修 补考 不及格"),
    ("毕业", "毕业学分 学籍 毕业资格 培养方案"),
    ("退学", "退学 休学 学籍 学业警示"),
    ("休学", "休学 复学 学籍"),
    ("奖学金", "奖学金 助学金 评定 国家奖学金"),
    ("助学贷款", "助学贷款 贷款 还款 征信"),
    ("三方协议", "就业协议 违约金 档案 报到证"),
    ("实习", "实习 实践 学分 安全"),
    ("作弊", "作弊 舞弊 违纪 考试纪律 处分"),
    ("抄袭", "抄袭 剽窃 违纪 学术不端 处分"),
    ("代考", "代考 替考 违纪 考试纪律 处分"),
    ("处分", "处分 违纪 警告 记过 申诉"),
    ("旷课", "旷课 缺勤 考勤 请假 处分"),
    ("大创", "创新创业 学科竞赛 项目 学分"),
    ("创新创业", "创新创业 学科竞赛 学分 认定"),
    ("学分", "学分 认定 置换 培养方案"),
    ("申诉", "申诉 复核 权益 处理决定"),
    ("转专业", "转专业 转学 专业调整 申请条件"),
    ("证书", "证书 职业资格 技能等级 认定 学分"),
    ("困难生", "家庭经济困难 认定 资助 建档"),
    ("请假", "请假 考勤 审批 销假"),
)


def expand_query(query: str) -> str:
    """把口语词扩成制度用语；只改检索串，不改展示与引用原文。"""
    extra: list[str] = []
    for word, expansion in _QUERY_EXPANSIONS:
        if word in query:
            extra.append(expansion)
    return f"{query} {' '.join(extra)}" if extra else query


def _phrase_run(query_seq: Sequence[str], block: str) -> float:
    """最长连续命中长度 / 查询 gram 数：奖励整词照面，抑制散字拼凑。

    「奖学金评定」在块里连成一片，说明这块讲的就是这件事；
    四个字散落在不同句子里则很可能只是同域噪声。v1 只有集合覆盖，
    两种情况得分完全一样。
    """
    if not query_seq:
        return 0.0
    best = run = 0
    for gram in query_seq:
        if gram in block:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best / len(query_seq)


def _merge_adjacent(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把同一文档里相邻块合成的命中并成一块（上下文窗口）。

    制度类文档一句话常跨在两块中间，单块引用会让回答缺半句。
    合并后 chunk_no 记首块、page 记首块页码，另记 merged=[...] 便于追溯；
    只并一对，避免一篇 1026 块的学生手册被并成长文。
    """
    merged: list[dict[str, Any]] = []
    merged_flags: list[bool] = []
    for hit in hits:
        if merged and not merged_flags[-1]:
            prev = merged[-1]
            if (hit["doc_id"] == prev["doc_id"]
                    and abs(int(hit["chunk_no"]) - int(prev["chunk_no"])) == 1):
                first, second = sorted((prev, hit), key=lambda h: int(h["chunk_no"]))
                text = f"{first['text']}\n{second['text']}"[:CHUNK_SIZE * 2 + 80]
                prev.update({
                    "text": text,
                    "chunk_no": int(first["chunk_no"]),
                    "page": first.get("page"),
                    "merged": [int(first["chunk_no"]), int(second["chunk_no"])],
                })
                merged_flags[-1] = True
                continue
        merged.append(dict(hit))
        merged_flags.append(False)
    return merged


def search(query: str, rows: Iterable[Mapping[str, Any]], top_k: int = 4,
           min_score: float = 0.03, merge_adjacent: bool = True,
           max_per_doc: int = 2) -> list[dict[str, Any]]:
    """检索最相关的分块。空查询/空库/全低于阈值 → 返回 []（上层明说没查到）。

    打分 = 0.50×余弦 + 0.28×IDF 加权覆盖 + 0.12×最长连击 + 0.10×标题命中。
    除绝对阈值外还按「相对头部」过滤：低于首条 45% 的命中视为噪声，
    只靠绝对阈值时，PDF 这种一页一块的语料会把无关页也带进引用。

    max_per_doc 是 v2 新增的「同文档限额」：知识库里有一篇一千多块的学生手册，
    几乎任何问题它都有几块高分命中，会把 4 个位置全占满，专门的《申诉办法》
    反而进不了引用面板。限额后同一文档最多占 2 席，剩下的位置留给更专门的文档。
    """
    q = str(query or "").strip()
    if not q:
        return []
    items, vectorizer, matrix, norm_texts, idf, doc_sizes = build_index(rows)
    if not items or vectorizer is None or matrix is None:
        return []
    expanded = expand_query(q)
    qv = vectorizer.transform([expanded])
    sims = (matrix @ qv.T).toarray().ravel()

    q_norm = _norm(q)
    # 查询 gram 序列只跟查询有关，提到循环外算一次
    q_seq = _grams(q_norm)
    q_grams = set(q_seq)
    # 覆盖度的分母：查询里每个 gram 的 IDF 之和。语料里没出现过的 gram 按最高权重计
    # （它属于「没被覆盖的信息」，不该被当成免费分）。
    unknown_idf = math.log((len(items) + 1) / 0.5)
    total_idf = sum(idf.get(g, unknown_idf) for g in q_grams) or 1.0

    hits: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        cos = float(sims[i]) if i < len(sims) else 0.0
        if cos <= 0:
            continue
        # 关键词覆盖：查询里的 2-gram 有多少出现在块里（解释「为什么命中这块」）
        block_norm = norm_texts[i] if i < len(norm_texts) else _norm(it.text)
        covered = [g for g in q_grams if g and g in block_norm]
        if not covered:
            continue
        coverage = len(covered) / max(1, len(q_grams))
        coverage_idf = sum(idf.get(g, unknown_idf) for g in covered) / total_idf
        phrase = _phrase_run(q_seq, block_norm)
        title_norm = _norm(it.title)
        title_cov = (sum(idf.get(g, unknown_idf) for g in covered if g in title_norm)
                     / total_idf)
        score = (W_COSINE * cos + W_COVERAGE * coverage_idf
                 + W_PHRASE * phrase + W_TITLE * title_cov)
        if DOC_PRIOR > 0:
            size = doc_sizes.get(it.doc_id, 1)
            score /= (1.0 + DOC_PRIOR * math.log2(max(1, size)))
        if score < min_score:
            continue
        hits.append({
            "doc_id": it.doc_id, "title": it.title, "chunk_no": it.chunk_no,
            "page": it.page, "text": it.text, "score": round(score, 6),
            "cosine": round(cos, 6), "coverage": round(coverage, 4),
            "coverage_idf": round(coverage_idf, 4), "phrase": round(phrase, 4),
            "title_hit": round(title_cov, 4),
            "matched": sorted(set(covered))[:6],
        })
    # 确定性排序：分数降序 → 文档 → 块号，无随机
    hits.sort(key=lambda h: (-h["score"], h["doc_id"], h["chunk_no"]))
    if hits:
        floor = hits[0]["score"] * 0.45
        hits = [h for h in hits if h["score"] >= floor]
    if max_per_doc and max_per_doc > 0:
        per_doc: dict[int, int] = {}
        kept: list[dict[str, Any]] = []
        for hit in hits:
            used = per_doc.get(int(hit["doc_id"]), 0)
            if used >= max_per_doc:
                continue
            per_doc[int(hit["doc_id"])] = used + 1
            kept.append(hit)
        hits = kept
    if merge_adjacent:
        hits = _merge_adjacent(hits)
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

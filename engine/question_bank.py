# engine/question_bank.py
# 职责：面试题库的 RAG 检索器——行业族归并 + 标签硬过滤 + TF-IDF 语义排序。
# 铁律：
#   1. 出题只从题库里取，取不到返回空列表，由上层回落模板（缺失不冒充）。
#   2. 每条题必须带 source_url，没有出处的题目不入库、不可检索。
#   3. 检索结果可解释：每条返回 matched_by（命中了哪些标签）+ score。
#   4. 全程确定性：同样输入必得同样排序（score 降序 → 题目编号升序）。
# 为什么不用向量库：DeepSeek 不提供 embedding 接口，装 sentence-transformers 要
# 额外下模型；题库本身是强结构化的（行业族+题型+岗位族），标签硬过滤已经砍掉
# 绝大部分候选，剩下的用 sklearn TF-IDF(char 2-3 gram) 排序足够，且完全离线、
# 可复现、无需新增依赖。

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

QB_VERSION = "qb-v1"

BANK_DIR = Path(__file__).resolve().parent.parent / "data" / "question_bank"

# 检索只认这六种题型（与 engine/interview.py::QUESTION_TYPES 对齐）
QTYPES: tuple[str, ...] = ("motivation", "major", "project", "scenario", "stress", "counter")

# ----------------------------------------------------------------
# 行业族：把岗位库里的 80+ 个行业名归并成可维护的族
# 规则是「关键词命中即归属」，按 _INDUSTRY_RULES 的顺序取第一个命中的族。
# 宁可归到 general，也不硬塞进不相关的族（错配比缺失更糟）。
# ----------------------------------------------------------------
FAMILY_LABELS: dict[str, str] = {
    "general": "通用（跨行业）",
    "it_software": "计算机软件 / 互联网 / IT 服务",
    "finance_bank": "金融 / 银行 / 证券 / 保险",
    "accounting": "财务 / 会计 / 审计 / 税务",
    "sales_marketing": "销售 / 市场 / 营销 / 商务",
    "hr_admin": "人力资源 / 行政 / 人事",
    "manufacturing": "机械 / 制造 / 电气 / 自动化 / 电子半导体",
    "healthcare": "医疗 / 护理 / 医药 / 医疗器械",
    "logistics": "物流 / 运输 / 仓储 / 供应链",
    "education": "教育 / 培训 / 院校 / 教研",
    "property": "物业 / 房地产 / 商业中心",
    "media_design": "新媒体 / 内容 / 影视 / 设计",
    "hospitality": "酒店 / 旅游 / 餐饮 / 服务",
    "telecom": "通信 / 电信 / 网络优化",
    "agriculture": "农 / 林 / 牧 / 渔",
    "legal": "法律 / 法务 / 合规",
    "public_sector": "政府 / 公共事业",
}

_INDUSTRY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("it_software", (
        "计算机软件", "互联网", "计算机服务", "外包服务", "计算机硬件",
        "信息安全", "大数据", "企业服务", "智能硬件", "电子商务",
    )),
    ("finance_bank", (
        "金融", "银行", "保险", "证券", "信托", "担保", "拍卖", "典当", "基金",
    )),
    ("accounting", (
        "会计", "审计", "财会", "财务", "税务",
    )),
    ("hr_admin", (
        "人力资源", "中介服务", "行政", "人事",
    )),
    ("sales_marketing", (
        "贸易", "进出口", "批发", "零售", "广告", "公关", "市场推广", "会展",
        "奢侈品", "办公用品", "快速消费品", "服装", "纺织",
    )),
    ("healthcare", (
        "医疗", "护理", "卫生", "制药", "生物工程", "器械", "美容", "保健",
    )),
    ("logistics", (
        "物流", "运输", "仓储", "供应链", "货代", "快递", "配送", "交通",
    )),
    ("education", (
        "教育", "培训", "院校", "学术", "科研", "学校",
    )),
    ("property", (
        "物业", "房地产", "商业中心", "置业", "不动产",
    )),
    ("media_design", (
        "影视", "媒体", "文化传播", "广播", "设计", "装潢", "出版",
    )),
    ("hospitality", (
        "酒店", "旅游", "餐饮", "娱乐", "休闲",
    )),
    ("telecom", (
        "通信", "电信", "增值服务",
    )),
    ("agriculture", (
        "农业", "林业", "牧业", "渔业", "农林", "种植", "养殖",
    )),
    ("legal", (
        "法律", "法务", "合规", "律师",
    )),
    ("public_sector", (
        "政府", "公共事业", "事业单位",
    )),
    ("manufacturing", (
        "机械", "设备", "重工", "电子技术", "半导体", "集成电路", "芯片",
        "仪器仪表", "自动化", "通用设备", "专用设备", "原材料", "电气",
        "电力", "水利", "汽车", "新能源", "航天", "航空", "冶炼", "采掘",
        "石油", "化工", "矿产", "印刷", "包装", "建材", "建筑", "家具",
        "家电", "检测", "认证", "环保", "加工",
    )),
)


def normalize_industry(industry: str | None) -> str:
    """岗位行业名 → 行业族。认不出就返回 general（不硬猜）。"""
    s = str(industry or "").strip()
    if not s:
        return "general"
    for family, keywords in _INDUSTRY_RULES:
        for kw in keywords:
            if kw in s:
                return family
    return "general"


def family_label(family: str) -> str:
    return FAMILY_LABELS.get(family, family)


# ----------------------------------------------------------------
# 空行业岗位的族推断：岗位名 / 技能 / 描述里的关键词
# 背景：岗位库里有约 600 条「行业为空」的岗位（U3D、测试、Java 等），
# 只按行业字段会全部落到 general，导致题库覆盖被低估。
# 规则按顺序取第一个命中；认不出仍然回 general（不硬猜）。
# ----------------------------------------------------------------
_TITLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("it_software", (
        "开发", "测试", "算法", "前端", "后端", "全栈", "运维",
        "java", "python", "c++", "c#", ".net", "php", "golang",
        "大数据", "数据分析", "数据工程", "人工智能", "机器学习",
        "u3d", "unity", "ue4", "ue5", "嵌入式", "软件", "android", "ios",
    )),
    ("media_design", (
        "新媒体", "内容运营", "内容编辑", "编辑", "视频", "剪辑",
        "设计", "美工", "ui", "视觉", "摄影", "文案", "直播", "主播", "编导",
    )),
    ("healthcare", (
        "护士", "临床", "医生", "药师", "医药", "护理", "医学",
    )),
    ("finance_bank", (
        "银行", "证券", "保险", "柜员", "风控", "投资", "理财", "金融",
    )),
    ("accounting", (
        "会计", "财务", "出纳", "审计", "税务",
    )),
    ("education", (
        "教师", "讲师", "教研", "助教", "课程顾问", "培训师", "校长", "辅导员", "教务",
    )),
    ("hr_admin", (
        "人力", "招聘", "行政", "人事",
    )),
    ("sales_marketing", (
        "销售", "市场", "营销", "商务", "客户经理", "渠道", "招商",
    )),
    ("logistics", (
        "物流", "仓储", "供应链", "运输", "调度", "货代", "快递", "配送",
    )),
    ("property", (
        "物业", "房地产", "置业", "管家", "商业中心",
    )),
    ("hospitality", (
        "酒店", "前厅", "客房", "餐饮", "旅游", "导游", "前台", "礼宾",
    )),
    ("telecom", (
        "通信", "网络优化", "无线", "传输", "基站", "5g", "承载网",
    )),
    ("agriculture", (
        "农业", "育种", "种植", "养殖", "兽医", "农林", "牧业", "渔业",
    )),
    ("legal", (
        "法务", "律师", "合规", "法律",
    )),
    ("public_sector", (
        "公务员", "事业单位", "政府", "公共事业",
    )),
    ("manufacturing", (
        "机械", "电气", "自动化", "结构", "工艺", "质量", "生产",
        "设备", "硬件", "电子", "半导体", "芯片", "汽车", "化工",
        "材料", "焊接", "模具",
    )),
)


def infer_family(job: Mapping[str, Any] | None) -> str:
    """岗位所属行业族：行业字段优先；行业为空/认不出时按标题+技能+描述推断。"""
    job = job or {}
    family = normalize_industry(job.get("industry"))
    if family != "general":
        return family
    parts = [str(job.get("title") or ""), str(job.get("description") or "")]
    tags = job.get("skill_tags") or []
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    elif tags:
        parts.append(str(tags))
    text = _norm(" ".join(parts))
    if not text:
        return "general"
    for fam, keywords in _TITLE_RULES:
        if any(_norm(k) in text for k in keywords):
            return fam
    return "general"


# ----------------------------------------------------------------
# 语料加载
# ----------------------------------------------------------------
@dataclass(frozen=True)
class BankItem:
    id: str
    family: str
    qtype: str
    question: str
    keywords: tuple[str, ...]
    answer_hint: str
    difficulty: int
    source_name: str
    source_url: str
    job_family: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "family": self.family, "family_label": family_label(self.family),
            "qtype": self.qtype, "question": self.question, "keywords": list(self.keywords),
            "answer_hint": self.answer_hint, "difficulty": self.difficulty,
            "job_family": self.job_family,
            "source_name": self.source_name, "source_url": self.source_url,
        }


def _norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", t.lower())


def _require(item: Mapping[str, Any], key: str, where: str) -> str:
    val = str(item.get(key) or "").strip()
    if not val:
        raise ValueError(f"题库条目 {where} 缺少必填字段 {key}")
    return val


def load_bank(bank_dir: Path | str = BANK_DIR) -> list[BankItem]:
    """读 data/question_bank/*.json，逐条校验后返回。

    校验是硬门禁：缺 question / source_url / source_name / qtype 直接抛错，
    绝不让「没有出处的题」进入检索池。
    """
    root = Path(bank_dir)
    items: list[BankItem] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        family = str(raw.get("family") or path.stem)
        for idx, it in enumerate(raw.get("items") or []):
            where = f"{path.name}[{idx}]"
            code = _require(it, "id", where)
            if code in seen:
                raise ValueError(f"题目编号重复：{code}（{where}）")
            seen.add(code)
            qtype = _require(it, "qtype", where)
            if qtype not in QTYPES:
                raise ValueError(f"{where} 的 qtype={qtype!r} 不在允许集合 {QTYPES}")
            items.append(BankItem(
                id=code,
                family=str(it.get("family") or family),
                qtype=qtype,
                question=_require(it, "question", where),
                keywords=tuple(str(k) for k in (it.get("keywords") or []) if str(k).strip()),
                answer_hint=str(it.get("answer_hint") or "").strip(),
                difficulty=int(it.get("difficulty") or 1),
                source_name=_require(it, "source_name", where),
                source_url=_require(it, "source_url", where),
                job_family=(str(it["job_family"]) if it.get("job_family") else None),
            ))
    return items


# ----------------------------------------------------------------
# 检索
# ----------------------------------------------------------------
@dataclass
class Hit:
    item: BankItem
    score: float
    matched_by: list[str] = field(default_factory=list)
    pool: str = "family"          # family=行业专项  general=通用兜底

    def as_dict(self) -> dict[str, Any]:
        d = self.item.as_dict()
        d.update({"score": round(self.score, 4), "matched_by": self.matched_by, "pool": self.pool})
        return d


@lru_cache(maxsize=1)
def _bank_index(bank_dir: str) -> tuple[list[BankItem], dict[str, Any]]:
    """进程级缓存：语料 + 按题型分组的索引。语料更新后调用 clear_cache()。"""
    items = load_bank(bank_dir)
    by_qtype: dict[str, list[BankItem]] = {q: [] for q in QTYPES}
    for it in items:
        by_qtype.setdefault(it.qtype, []).append(it)
    # 预建 TF-IDF 矩阵（按题型分块，避免跨题型噪声）
    vectors: dict[str, Any] = {}
    vectorizer: dict[str, Any] = {}
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        for qtype, pool in by_qtype.items():
            if not pool:
                continue
            corpus = [f"{it.question} {' '.join(it.keywords)}" for it in pool]
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
            matrix = vec.fit_transform(corpus)
            vectorizer[qtype] = vec
            vectors[qtype] = matrix
    except Exception:  # sklearn 不可用时退化为关键词重叠打分，绝不因此不可用
        vectorizer, vectors = {}, {}
    return items, {"by_qtype": by_qtype, "vectorizer": vectorizer, "vectors": vectors}


def clear_cache() -> None:
    """语料热更新后清缓存（/qb/reload 调用）。"""
    _bank_index.cache_clear()


def _keyword_overlap(text: str, item: BankItem) -> list[str]:
    """命中项：岗位文本里出现的考点词 / 岗位族词。用于 matched_by 可解释性。"""
    norm_text = _norm(text)
    hits = [k for k in item.keywords if _norm(k) and _norm(k) in norm_text]
    if _job_family_hit(text, item):
        hits.append(f"岗位族:{item.job_family}")
    return hits


def _kw_coverage(text: str, item: BankItem) -> float:
    """考点覆盖率：岗位文本命中了该题考点的多少比例（0~1）。"""
    if not item.keywords:
        return 0.0
    norm_text = _norm(text)
    hit = sum(1 for k in item.keywords if _norm(k) and _norm(k) in norm_text)
    return hit / len(item.keywords)


def _job_family_hit(text: str, item: BankItem) -> bool:
    """岗位族是否命中。

    题目的岗位族常写成「柜员/客户服务」这种多值形式，而岗位名是「银行柜员」，
    整串匹配会漏掉，所以按 / 、, 空格切成片段，任一片段被包含即算命中。
    """
    if not item.job_family:
        return False
    norm_text = _norm(text)
    parts = [p for p in re.split(r"[\/、,，\s]+", str(item.job_family)) if p]
    return any(_norm(p) and _norm(p) in norm_text for p in parts)


def _tfidf_rank(query: str, qtype: str, pool: Sequence[BankItem], index: Mapping[str, Any]) -> dict[str, float]:
    """返回 {题目编号: 相似度}。sklearn 不可用或查询为空时返回空字典。"""
    vec = index["vectorizer"].get(qtype)
    matrix = index["vectors"].get(qtype)
    if vec is None or matrix is None or not str(query or "").strip():
        return {}
    try:
        qv = vec.transform([query])
        sims = (matrix @ qv.T).toarray().ravel()
    except Exception:
        return {}
    return {pool[i].id: float(sims[i]) for i in range(len(pool))}


def retrieve(job_industry: str | None,
             query_text: str,
             qtype: str,
             k: int = 2,
             bank_dir: Path | str = BANK_DIR) -> list[dict[str, Any]]:
    """行业字段入口：先归并行业族，再走 _retrieve_family。"""
    return _retrieve_family(normalize_industry(job_industry), query_text, qtype, k, bank_dir)


def _retrieve_family(family: str,
                     query_text: str,
                     qtype: str,
                     k: int = 2,
                     bank_dir: Path | str = BANK_DIR) -> list[dict[str, Any]]:
    """按「行业族 + 题型」硬过滤，再用三路信号打分排序取前 k 条。

    打分（0~1，纯排序用，不是概率）：
      0.55 × TF-IDF 相对相似度（同题型池内归一化，中文用 char 2-3 gram）
      0.30 × 岗位族精确命中（题目标注「后端开发」且岗位名也含该词）
      0.15 × 考点覆盖率（岗位名称/技能标签/JD 命中了该题多少个考点词）
    TF-IDF 对短查询的绝对值很小（0.01 量级），所以必须再叠岗位族与考点信号，
    否则排序几乎等同于随机。权重固定、无随机数，同样输入必得同样顺序。

    - 先取行业专项题（family == 该岗位所属族），不足 k 时用 general 补齐。
    - 两段都取不到 → 返回 []（上层回落模板，不编题）。
    """
    if qtype not in QTYPES:
        return []
    items, index = _bank_index(str(bank_dir))
    pool_all: list[BankItem] = index["by_qtype"].get(qtype, [])

    def pick(target_family: str, tag: str) -> list[Hit]:
        pool = [it for it in pool_all if it.family == target_family]
        if not pool:
            return []
        sims = _tfidf_rank(query_text, qtype, pool, index)
        peak = max(sims.values()) if sims else 0.0
        hits: list[Hit] = []
        for it in pool:
            sim_rel = (sims.get(it.id, 0.0) / peak) if peak > 0 else 0.0
            fam = 1.0 if _job_family_hit(query_text, it) else 0.0
            cov = _kw_coverage(query_text, it)
            score = 0.55 * sim_rel + 0.30 * fam + 0.15 * cov
            hits.append(Hit(item=it, score=score,
                            matched_by=_keyword_overlap(query_text, it), pool=tag))
        # 确定性排序：分数降序 → 命中项多者优先 → 题号升序
        hits.sort(key=lambda h: (-round(h.score, 6), -len(h.matched_by), h.item.id))
        return hits

    out = pick(family, "family") if family != "general" else []
    out = out[:k]
    if len(out) < k:
        seen = {h.item.id for h in out}
        out += [h for h in pick("general", "general") if h.item.id not in seen][: k - len(out)]
    return [h.as_dict() for h in out]


def retrieve_for_job(job: Mapping[str, Any] | None, qtype: str, k: int = 2,
                     bank_dir: Path | str = BANK_DIR,
                     query_text: str | None = None) -> list[dict[str, Any]]:
    """从岗位字典直接检索（供 build_outline 用）。

    query_text 显式传入时以它为准：答疑链路会把简历里的课程/技能并进查询串，
    让同一岗位对不同学生抽出更贴身的题（简历感知排序）。
    """
    job = job or {}
    query = query_text if query_text else " ".join(str(x) for x in (
        job.get("title") or "", job.get("industry") or "",
        " ".join(str(s) for s in (job.get("skill_tags") or [])),
    ) if x)
    return _retrieve_family(infer_family(job), query, qtype, k=k, bank_dir=bank_dir)


# ----------------------------------------------------------------
# 统计（给 /qb/stats 与评测脚本用）
# ----------------------------------------------------------------
def stats(bank_dir: Path | str = BANK_DIR) -> dict[str, Any]:
    """覆盖矩阵：每个行业族 × 每种题型各有多少题。"""
    items, _ = _bank_index(str(bank_dir))
    matrix: dict[str, dict[str, int]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for it in items:
        matrix.setdefault(it.family, {q: 0 for q in QTYPES})[it.qtype] += 1
        s = sources.setdefault(it.source_name, {"name": it.source_name, "url": it.source_url, "count": 0})
        s["count"] += 1
    families = {f: {"label": family_label(f), "total": sum(v.values()), "by_qtype": v}
                for f, v in sorted(matrix.items())}
    return {
        "version": QB_VERSION,
        "total": len(items),
        "families": families,
        "qtypes": list(QTYPES),
        "sources": sorted(sources.values(), key=lambda s: (-s["count"], s["name"])),
    }

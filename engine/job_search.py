# engine/job_search.py
# 职责：岗位关键词检索的确定性底座——分词、相关性分级、命中高亮、筛选器、同义词提示
# 依赖：仅标准库 + rules/direction_keywords.json（同义词来源）
# 说明：
#   1) **搜索与推荐是两套逻辑，互不污染**：
#      推荐 = 按个人画像个性化排序（engine/recommend.py）
#      搜索 = 按关键词相关性排序（本文件），不带任何个人画像因素。
#      为什么不混：搜「Java」时相关性最高的 Java 岗若被个人因素压到后面，搜索体验就是反常的。
#   2) **没命中就给同义词提示，绝不硬凑**：
#      搜「前端」无结果时返回 suggestions，而不是拿一堆不相关岗位充数。
#   3) 全部纯函数，不打库、不调模型；取数在 agents/tools.py。
#   4) 中文分词不引第三方库：用「整词 + 二元组」切分，与 recommend.py 的口径一致。

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

JOB_SEARCH_VERSION = "job-search-v1"

_DICT_PATH = Path(__file__).resolve().parents[1] / "rules" / "direction_keywords.json"

# ----------------------------------------------------------------
# 相关性权重：标题 > 技能标签 > 公司 > JD 全文
# 为什么标题权重最高：用户搜「Java」想看的是「Java 开发工程师」，不是
# 「某个岗位的 JD 里顺便提到了 Java」。
# ----------------------------------------------------------------
W_TITLE = 10.0
W_SKILL = 6.0
W_COMPANY = 2.0
W_DESC = 1.0

# 相关性分档（用于前端显示「高度相关 / 相关 / 弱相关」）
LEVEL_HIGH = "high"
LEVEL_MID = "medium"
LEVEL_LOW = "low"

# 命中字段的中文名（前端展示「命中：岗位名称、技能标签」）
FIELD_LABELS = {
    "title": "岗位名称",
    "skill": "技能标签",
    "company": "公司名称",
    "desc": "职位描述",
}

_ENG_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+\-#.]{1,}")
_ZH_CLEAN_RE = re.compile(r"[^一-鿿]")
# 关键词切分：按空白、常见标点切开（用户可能输入「Java 开发」或「Java,开发」）
_SPLIT_RE = re.compile(r"[\s,，、;；/|]+")


# ================================================================
# 一、分词（与 recommend.py 同一口径：英文串 + 中文整词 + 中文二元组）
# ================================================================
def norm_token(token: str) -> str:
    return str(token or "").strip().lower()


def tokens_of(text: str) -> set[str]:
    """切成可比对的特征词：英文/数字串（≥2 字符）+ 中文整词与二元组。"""
    low = norm_token(text)
    out: set[str] = set()
    for match in _ENG_TOKEN_RE.finditer(low):
        out.add(match.group(0))
    zh = _ZH_CLEAN_RE.sub("", low)
    if zh:
        out.add(zh)
        for i in range(len(zh) - 1):
            out.add(zh[i:i + 2])
    return out


def parse_keywords(query: str) -> list[str]:
    """把用户输入拆成关键词列表，去空、去重、保序。

    「Java 开发」→ ["java", "开发"]；「Java开发」保持一个词（用户没打空格时
    不该替他切，「Java开发」和「Java 开发」语义不同）。
    """
    if not query:
        return []
    parts = [p.strip() for p in _SPLIT_RE.split(str(query))]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        low = p.lower()
        if not low or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


# ================================================================
# 二、单字段命中与打分
# ================================================================
def _contains_any(haystack: str, needles: Sequence[str]) -> list[str]:
    """返回 haystack 里命中的关键词（子串判定，大小写不敏感）。

    英文关键词要求**词边界**：搜 "java" 不该命中 "javascript"。
    中文没有词边界概念，直接子串判（搜「前端」命中「前端开发」是对的）。
    """
    low = norm_token(haystack)
    if not low:
        return []
    hits: list[str] = []
    for n in needles:
        if not n:
            continue
        if n.isascii():
            # 词边界：两侧不能是字母/数字/#/+/.（避免 java 命中 javascript、c 命中 c#）
            pattern = r"(?<![a-z0-9#+._-])" + re.escape(n) + r"(?![a-z0-9#+._-])"
            if re.search(pattern, low):
                hits.append(n)
        elif n in low:
            hits.append(n)
    return hits


def score_one(
    job: Mapping[str, Any],
    keywords: Sequence[str],
) -> dict[str, Any]:
    """给单个岗位算相关性分，并记录命中在哪些字段。

    打分不是简单的「命中次数累加」：同一关键词在同一字段只算一次，
    否则一段反复提 Java 的 JD 会靠堆词刷分。
    """
    title = str(job.get("title") or "")
    company = str(job.get("company") or "")
    desc = str(job.get("description") or "")
    tags = job.get("skill_tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    tag_text = " ".join(str(t) for t in tags)

    hit_title = _contains_any(title, keywords)
    hit_skill = _contains_any(tag_text, keywords)
    hit_company = _contains_any(company, keywords)
    hit_desc = _contains_any(desc, keywords)

    score = (
        W_TITLE * len(hit_title)
        + W_SKILL * len(hit_skill)
        + W_COMPANY * len(hit_company)
        + W_DESC * len(hit_desc)
    )

    # 命中的关键词去重并保序（按用户输入顺序）
    matched: list[str] = []
    for kw in keywords:
        if kw in hit_title or kw in hit_skill or kw in hit_company or kw in hit_desc:
            matched.append(kw)

    fields: list[str] = []
    for key, hits in (("title", hit_title), ("skill", hit_skill),
                      ("company", hit_company), ("desc", hit_desc)):
        if hits:
            fields.append(key)

    return {
        "score": round(score, 2),
        "matched_keywords": matched,
        "matched_fields": fields,
        "hit_title": hit_title,
        "hit_skill": hit_skill,
    }


def level_of(score: float) -> str:
    """按分数分档：标题命中即 high，只有 JD 命中算 low。"""
    if score >= W_TITLE:
        return LEVEL_HIGH
    if score >= W_SKILL:
        return LEVEL_MID
    return LEVEL_LOW


# ================================================================
# 三、筛选器（与关键词是「与」关系：先筛后搜，或先搜后筛，结果一致）
# ================================================================
def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def match_filters(job: Mapping[str, Any], filters: Mapping[str, Any] | None) -> bool:
    """岗位是否满足全部筛选条件。**缺失值不放行也不拦死**，按「该岗位没声明」处理。

    具体口径：
    - city：精确等于任一选中城市
    - education：岗位要求学历在选中集合内；岗位写「学历不限」时任何学历都放行
    - salary_min_gte：岗位薪资下限 >= 门槛；岗位没写薪资时**不通过**（用户要的是"≥8K"，
      没标薪资的岗位无法保证满足）
    - exp_max_lte：岗位经验上限 <= 门槛（即「应届也能投」）；岗位没写经验时不通过
    """
    if not filters:
        return True

    cities = filters.get("cities") or []
    if cities:
        if str(job.get("city") or "") not in {str(c) for c in cities}:
            return False

    educations = filters.get("educations") or []
    if educations:
        edu = str(job.get("education") or "")
        wanted = {str(e) for e in educations}
        # 「学历不限」的岗位对任何学历都开放
        if edu and edu not in wanted and "学历不限" not in edu and edu != "学历不限":
            return False

    salary_min = _num(filters.get("salary_min_gte"))
    if salary_min is not None:
        job_min = _num(job.get("salary_min"))
        if job_min is None or job_min < salary_min:
            return False

    exp_max = _num(filters.get("exp_max_lte"))
    if exp_max is not None:
        job_exp_max = _num(job.get("exp_max"))
        if job_exp_max is None or job_exp_max > exp_max:
            return False

    return True


# ================================================================
# 四、主检索入口
# ================================================================
def diversify(
    items: Sequence[Mapping[str, Any]],
    max_per_company: int = 2,
) -> list[dict[str, Any]]:
    """同公司限流：单家公司最多占 max_per_company 条，保持原有相关性顺序不变。

    为什么需要：招聘站数据里一家公司常一次挂十几条同类岗位（如中电环保有 5 条
    「Java 开发工程师」分属不同城市），全排在前面会让首页看起来只有一家公司。
    实现是稳定的：只跳过超额项，被跳过的项仍留在后面（不是丢弃），
    所以「结果总数」不变，只是顺序更可浏览。
    """
    if max_per_company <= 0:
        return [dict(i) for i in items]
    head: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in items:
        key = str(item.get("company") or "")
        count = seen.get(key, 0)
        if key and count >= max_per_company:
            tail.append(dict(item))
            continue
        seen[key] = count + 1
        head.append(dict(item))
    return head + tail


def _filter_notes(job: Mapping[str, Any], filters: Mapping[str, Any] | None) -> list[str]:
    """给命中筛选器的岗位补一句「为什么它在结果里」的说明。

    最典型的坑：用户筛「硕士」，结果里混进「学历不限」的岗位 —— 这不是筛选失效，
    而是「不限」本来就该对所有人开放。但界面上不解释一句，用户只会觉得筛得不准。
    """
    notes: list[str] = []
    if not filters:
        return notes
    educations = filters.get("educations") or []
    if educations:
        edu = str(job.get("education") or "")
        if "学历不限" in edu:
            notes.append("该岗位不限学历")
    if filters.get("exp_max_lte") is not None:
        if _num(job.get("exp_max")) == 0 and _num(job.get("exp_min")) == 0:
            notes.append("该岗位不限经验")
    return notes


def search_jobs(
    jobs: Iterable[Mapping[str, Any]],
    query: str = "",
    *,
    filters: Mapping[str, Any] | None = None,
    limit: int = 20,
    offset: int = 0,
    max_per_company: int = 2,
) -> dict[str, Any]:
    """在候选岗位里按关键词 + 筛选器检索。

    返回 {total, items, keywords, page} —— items 已按相关性降序（同分按 id 升序，保证稳定）。
    空 query 时只做筛选（浏览模式），按 id 升序返回，不做相关性排序。
    """
    keywords = parse_keywords(query)
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    rows = [dict(j) for j in jobs if match_filters(j, filters)]

    if not keywords:
        total = len(rows)
        rows.sort(key=lambda j: int(j.get("id") or 0))
        page = diversify(rows, max_per_company)[offset:offset + limit]
        for r in page:
            r["relevance_score"] = None
            r["relevance_level"] = None
            r["matched_keywords"] = []
            r["matched_fields"] = []
            r["filter_notes"] = _filter_notes(r, filters)
        return {
            "total": total,
            "items": page,
            "keywords": [],
            "page": {"offset": offset, "limit": limit, "returned": len(page)},
            "engine_version": JOB_SEARCH_VERSION,
        }

    scored: list[dict[str, Any]] = []
    for row in rows:
        detail = score_one(row, keywords)
        if detail["score"] <= 0:
            continue
        merged = dict(row)
        merged["relevance_score"] = detail["score"]
        merged["relevance_level"] = level_of(detail["score"])
        merged["matched_keywords"] = detail["matched_keywords"]
        merged["matched_fields"] = detail["matched_fields"]
        merged["filter_notes"] = _filter_notes(merged, filters)
        scored.append(merged)

    scored.sort(key=lambda j: (-float(j.get("relevance_score") or 0), int(j.get("id") or 0)))
    total = len(scored)
    page = diversify(scored, max_per_company)[offset:offset + limit]

    return {
        "total": total,
        "items": page,
        "keywords": keywords,
        "page": {"offset": offset, "limit": limit, "returned": len(page)},
        "engine_version": JOB_SEARCH_VERSION,
    }


# ================================================================
# 五、同义词提示（没结果时不硬凑，给「是不是想找」）
# ================================================================
def load_directions(path: Path | None = None) -> list[dict[str, Any]]:
    """读方向词典；文件缺失时返回空列表（搜索功能不该因词典挂掉）。"""
    target = path or _DICT_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for item in data.get("directions") or []:
        name = str(item.get("name") or "").strip()
        kws = [str(k).strip() for k in item.get("keywords") or [] if str(k).strip()]
        if name and kws:
            out.append({"name": name, "keywords": kws})
    return out


def suggest_keywords(
    query: str,
    directions: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """没命中时给建议：找出与 query 相关的方向，返回该方向下更可能命中的词。

    匹配方式：query 命中方向名或其任一关键词 → 该方向的所有关键词都作为候选，
    排除 query 自身。例如搜「前端」→ 建议 vue / react / h5 / web。
    再例如搜「程序员」→ 方向名里没有，但「开发工程师」在「后端」方向里，故不命中这里，
    交给前端提示「换个词试试」。
    """
    words = parse_keywords(query)
    if not words:
        return []
    table = list(directions) if directions is not None else load_directions()
    out: list[dict[str, Any]] = []
    for d in table:
        name = str(d.get("name") or "")
        kws = [str(k) for k in d.get("keywords") or []]
        probe = " ".join([name] + kws).lower()
        if not any(w in probe for w in words):
            continue
        picks = [k for k in kws if k.lower() not in set(words)]
        if not picks:
            continue
        out.append({"direction": name, "keywords": picks[:6]})
    return out[:3]


# ================================================================
# 六、分面（前端筛选器下拉选项 + 各值岗位数）
# ================================================================
def build_facets(jobs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """统计筛选项与数量，供前端渲染下拉框（不含空值）。"""
    cities: dict[str, int] = {}
    educations: dict[str, int] = {}
    for job in jobs:
        city = str(job.get("city") or "").strip()
        if city:
            cities[city] = cities.get(city, 0) + 1
        edu = str(job.get("education") or "").strip()
        if edu:
            educations[edu] = educations.get(edu, 0) + 1

    def _sorted(d: dict[str, int]) -> list[dict[str, Any]]:
        return [{"value": k, "count": v}
                for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "cities": _sorted(cities),
        "educations": _sorted(educations),
        "engine_version": JOB_SEARCH_VERSION,
    }

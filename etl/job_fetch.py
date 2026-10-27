# etl/job_fetch.py
# 职责：从公开招聘站点抓「企业岗位」，解析成 recruit_job 一行。
#
# 铁律（与 recruit_fetch 完全一致）：
#   1. 只写抓到的东西。薪资/学历/人数抽不到就 None，不填 0、不填「不限」冒充。
#      —— 注意：「学历不限」是**原始原文**，学生看到的是「该岗不卡学历」，这是真信息；
#         而「我们没抽到学历要求」必须留 None，两者绝不能混为一谈。
#   2. 每条记录都带 apply_url（原文链接）+ published_at（发布日期），可逐条点开核对。
#   3. 单条解析失败不抛异常、不中断整轮。
#
# 数据源：
#   liepin-cq  猎聘·重庆   —— 静态 HTML 含完整岗位卡片（标题/薪资/地点/经验/学历/公司/行业）
#                            详情页亦为静态，含 JD 正文、招录人数、行业要求。
#
# 为什么选猎聘而不是 BOSS 直聘 / 智联：
#   BOSS 与智联的列表页是 JS 渲染，静态 HTML 里 0 个岗位链接（已实测）；
#   猎聘的岗位卡片写死在 HTML 里，是有骨架的静态站，可以稳定解析、也不给站点造成压力。

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from etl.recruit_fetch import _TIMEOUT, _opener, _UA, html_to_text, parse_list  # noqa: F401

# ---------------------------------------------------------------- 数据源定义

JOB_SOURCES: dict[str, dict[str, Any]] = {
    "liepin-cq": {
        "name": "猎聘·重庆职位",
        "list_url": "https://www.liepin.com/city-cq/",
        "city": "重庆",
        "region_scope": "重庆",
        # 列表页里混着「查看更多岗位」这类导航链接和城市/职能入口，用这个卡掉
        "card_class": "jobcard2-detail-box",
    },
}

# ---------------------------------------------------------------- 单元格解析

# 岗位卡有两个兄弟 <a>：jobcard2-detail-box（标题/薪资/地点/标签）和
# jobcard2-company-box（单位/行业/规模）。所以必须先按块切，再在块内分别解析
# —— 只按 detail-box 切会永远拿不到单位名。
#
# 不能用「<div class=seo-jobcard2-common>...</div></div>」这种懒匹配：
# 块内还有 company-meta 的 </div>，会提前截断，导致行业/规模丢失。
# 改为按位置切：块起点 = 下一个 seo-jobcard2-common 的位置。
_BLOCK_START = re.compile(r"<div[^>]*class=['\"]seo-jobcard2-common['\"][^>]*>", re.I)
_CARD_RE = re.compile(
    r"<a[^>]*class=['\"]jobcard2-detail-box['\"][^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
    re.S | re.I,
)


def _txt(html: str) -> str:
    """取标签内文字并压平空白。"""
    s = re.sub(r"<[^>]+>", "", html)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&ensp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def _span(card: str, cls: str) -> str | None:
    """取 class 命中的第一个 span 的文字。"""
    m = re.search(
        rf"<span[^>]*class=['\"][^'\"]*{re.escape(cls)}[^'\"]*['\"][^>]*>(.*?)</span>",
        card,
        re.S | re.I,
    )
    return _txt(m.group(1)) if m else None


# ---------------------------------------------------------------- 字段抽取


def parse_salary(text: str | None) -> tuple[float | None, float | None]:
    """把「5-7k」「30-55k·15薪」「8千-1.2万」解析成 (月薪下限, 上限)，单位元。

    抽不出返回 (None, None)。**绝不默认 0** —— 0 元月薪比「未知」更误导人。
    """
    if not text:
        return None, None
    s = text.replace(" ", "").replace(",", "")
    # 先归一单位：k/千 → 1000，w/万 → 10000
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*([kK千万])", s)
    if not m:
        # 单值形态：「面议」之类一律不要；「8k以上」这类也留 None
        m1 = re.search(r"(\d+(?:\.\d+)?)\s*([kK千万])", s)
        if not m1:
            return None, None
        unit = 10000.0 if m1.group(2) in "万w" else 1000.0
        v = float(m1.group(1)) * unit
        return v, None
    lo, hi = float(m.group(1)), float(m.group(2))
    unit = 10000.0 if m.group(3) in "万w" else 1000.0
    return lo * unit, hi * unit


def _split_city(location: str | None) -> tuple[str | None, str | None]:
    """「重庆-南岸区南坪(商圈)」→ (重庆, 南岸区)。

    只认「城市-区县」形态；没有短横线的（如「重庆」）只回城市。
    商圈括号里的补充信息丢掉 —— 城市/区县两列装不下，也不该硬塞。
    """
    if not location:
        return None, None
    s = re.sub(r"[（(].*?[）)]", "", location).strip()
    if "-" not in s:
        return (s or None), None
    city, rest = s.split("-", 1)
    city = city.strip() or None
    # 区县：取到「街道/商圈」之前，形如 南岸区 / 渝北区 / 万州区
    m = re.match(r"([^-\s]{2,12}?(?:区|县|市|镇))", rest.strip())
    district = m.group(1) if m else None
    return city, district


def _education_from_label(label: str | None) -> str | None:
    """标签里的学历原文（「本科」「学历不限」「硕士」）。

    注意：只有标签里**真的写了**才返回；没写就 None。
    """
    if not label:
        return None
    if "不限" in label:
        return "不限"
    for kw in ("博士", "硕士", "本科", "大专", "中专", "高中", "初中"):
        if kw in label:
            return kw
    return None


def _experience_from_label(label: str | None) -> str | None:
    if not label:
        return None
    if "不限" in label or "应届" in label or "在校" in label or "学生" in label:
        return label.strip()
    if re.search(r"\d+\s*[-~]\s*\d+\s*年", label) or "年以上" in label:
        return label.strip()
    return None


def parse_cards(html: str) -> list[dict[str, Any]]:
    """解析列表页岗位卡片。返回原始字段（尚未补详情页）。

    先切 seo-jobcard2-common 整块，再块内找 detail-box 与 company-box，
    因为单位名不在 detail-box 里面。
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    starts = [m.start() for m in _BLOCK_START.finditer(html)]
    blocks = [html[s: (starts[i + 1] if i + 1 < len(starts) else len(html))]
              for i, s in enumerate(starts)]
    if not blocks:
        # 结构变了（站点改版）时退一步：只按 detail-box 抓，单位留空，
        # 好过整轮 0 条。缺失就是缺失，不编一个假单位名。
        blocks = [m.group(0) for m in _CARD_RE.finditer(html)]

    for block in blocks:
        m = _CARD_RE.search(block)
        if not m:
            continue
        href, card = m.group(1), m.group(2)
        url = href if href.startswith("http") else f"https://www.liepin.com{href}"
        if url in seen:
            continue
        seen.add(url)

        title = _span(card, "jobcard2-title")
        if not title or len(title) < 2:
            continue
        location = _span(card, "jobcard2-location")
        salary_raw = _span(card, "jobcard2-salary")

        # 经验/学历标签是「无 class 的 span」顺序出现，先全部取出再逐一归位
        labels = [_txt(x) for x in re.findall(r"<span[^>]*>(.*?)</span>", card, re.S)]
        labels = [x for x in labels if x and x not in (title, location, salary_raw)]
        exp = edu = None
        for lb in labels:
            if exp is None and _experience_from_label(lb):
                exp = _experience_from_label(lb)
            elif edu is None and _education_from_label(lb):
                edu = _education_from_label(lb)

        # 单位 / 行业 / 规模来自同块的 company-box
        company = _span(block, "jobcard2-company-title")
        meta = re.search(
            r"class=['\"]jobcard2-company-meta['\"][^>]*>(.*?)</div>", block, re.S | re.I
        )
        industry = None
        company_size = None
        if meta:
            parts = [_txt(x) for x in re.findall(r"<span[^>]*>(.*?)</span>", meta.group(1), re.S)]
            parts = [p for p in parts if p]
            if parts:
                industry = parts[0]
            if len(parts) > 1:
                company_size = parts[1]

        sal_lo, sal_hi = parse_salary(salary_raw)
        city, district = _split_city(location)
        job_id = _job_id(url)

        out.append({
            "title": title,
            "company": company,
            "industry": industry,
            "city": city,
            "district": district,
            "salary_min": sal_lo,
            "salary_max": sal_hi,
            "education": edu,
            "experience": exp,
            "company_size": company_size,
            "apply_url": url,
            "job_id": job_id,
        })
    return out


def _job_id(url: str) -> str | None:
    m = re.search(r"/job/(\d+)\.shtml", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------- 详情页

_HEADCOUNT_D = re.compile(r"招(\d{1,5})人")
_UPDATE_D = re.compile(r"(\d{1,2})月(\d{1,2})日更新")


def parse_detail(text: str) -> dict[str, Any]:
    """从详情页纯文本里抽 JD / 人数 / 更新日期。抽不到一律 None。"""
    out: dict[str, Any] = {"description": None, "headcount": None, "published_at": None,
                           "industry_req": None}
    if not text:
        return out

    m = _HEADCOUNT_D.search(text)
    if m:
        out["headcount"] = int(m.group(1))

    m = _UPDATE_D.search(text)
    if m:
        # 只给「10月26日更新」没有年份 —— 招聘页的更新日永远是当年或去年，
        # 但不猜：这里只记录 月/日，年份留给调用方（见 _guess_year）
        out["_md"] = (int(m.group(1)), int(m.group(2)))

    # JD：从「职位介绍」到「公司简介 / 猎聘温馨提示」之间
    if "职位介绍" in text:
        body = text.split("职位介绍", 1)[1]
        for stop in ("公司简介", "猎聘温馨提示", "其他信息", "查看全部"):
            if stop in body:
                body = body.split(stop, 1)[0]
        body = body.strip(" →>-")
        if len(body) >= 20:
            out["description"] = body[:8000]

    if "行业要求：" in text:
        seg = text.split("行业要求：", 1)[1]
        seg = re.split(r"[\s]{2,}|公司简介|其他信息", seg, maxsplit=1)[0].strip()
        if seg and len(seg) <= 60:
            out["industry_req"] = seg

    return out


def _guess_year(month: int, today: date | None = None) -> int:
    """「10月26日更新」→ 年份。

    招聘页不给年份。规则：月 > 当前月 → 去年；否则今年。
    这不是编数据，而是把「相对日期」还原成日历日；错误最多差一年，
    且页面上同时保留了 detail_url，学生可点开看原文。
    """
    t = today or date.today()
    return t.year - 1 if month > t.month else t.year


# ---------------------------------------------------------------- 技能标签

# 只做「原文出现即标」的关键词映射，不做任何推断。
# 目的是让岗位能进搜索引擎的 skill 维度（相关性权重 6），不是为了画像写标签。
_SKILL_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", ("python",)),
    ("Java", ("java",)),
    ("JavaScript", ("javascript", "js开发", "前端开发")),
    ("C++", ("c++",)),
    ("C#", ("c#", ".net")),
    ("Go", ("golang", "go语言")),
    ("SQL", ("sql", "mysql", "oracle", "postgresql")),
    ("Hadoop", ("hadoop", "hdfs")),
    ("Spark", ("spark",)),
    ("Hive", ("hive",)),
    ("Flink", ("flink",)),
    ("数据仓库", ("数据仓库", "数仓")),
    ("数据分析", ("数据分析", "数据挖掘", "bi分析")),
    ("机器学习", ("机器学习", "深度学习", "算法模型")),
    ("Linux", ("linux",)),
    ("Docker", ("docker", "k8s", "kubernetes", "容器化")),
    ("Vue", ("vue",)),
    ("React", ("react",)),
    ("产品设计", ("产品设计", "需求分析", "axure")),
    ("项目管理", ("项目管理", "pmp")),
    ("会计", ("会计", "财务核算", "报表编制")),
    ("法律", ("法律", "法务", "合规")),
    ("英语", ("英语", "cet-4", "cet-6", "四六级")),
)


def extract_skills(*texts: str | None) -> list[str] | None:
    """从标题+JD+行业里抽技能标签；一个都没有则返回 None（不返回 []）。"""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    hits: list[str] = []
    for label, kws in _SKILL_WORDS:
        # ASCII 词要卡边界，否则 java 会命中 javascript
        for kw in kws:
            if _kw_hit(blob, kw):
                hits.append(label)
                break
    return hits or None


def _kw_hit(blob: str, kw: str) -> bool:
    """ASCII 关键词走词边界；中文关键词直接包含即可。"""
    if re.fullmatch(r"[a-z0-9+#.]+", kw):
        # c++ / c# / .net 里的 + # . 是边界的一部分，手工处理
        if kw in ("c++", "c#", ".net"):
            return kw in blob
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", blob) is not None
    return kw in blob


# ---------------------------------------------------------------- 组装

def make_source_key(source: str, url: str, title: str) -> str:
    basis = f"{source}|{url or title}"
    return hashlib.md5(basis.encode("utf-8")).hexdigest()[:32]


def build_job(source_id: str, card: dict[str, Any],
              detail_text: str | None = None) -> dict[str, Any]:
    """把列表卡片 + 详情页正文组装成 recruit_job 一行。"""
    cfg = JOB_SOURCES[source_id]
    det = parse_detail(detail_text or "")

    published = None
    if det.get("_md"):
        mo, dy = det["_md"]
        try:
            published = date(_guess_year(mo), mo, dy).isoformat()
        except ValueError:
            published = None

    desc = det["description"]
    skills = extract_skills(card.get("title"), desc, card.get("industry"))

    return {
        "source": source_id,
        "source_key": make_source_key(source_id, card["apply_url"], card["title"]),
        "title": card["title"][:200],
        "company": (card.get("company") or "未标注单位")[:200],        "industry": card.get("industry"),
        "city": card.get("city") or cfg["city"],
        "district": card.get("district"),
        "salary_min": card.get("salary_min"),
        "salary_max": card.get("salary_max"),
        "education": card.get("education"),
        "experience": card.get("experience"),
        "headcount": det["headcount"],
        "skill_tags": skills,
        "description": desc,
        "apply_url": card["apply_url"][:500],
        "published_at": published,
        "deadline": None,           # 猎聘不给报名截止日 —— 不猜
        # 有有效期吗？没有。招聘岗默认 open，下架由 last_seen_at 判断（见 sync 脚本）
        "status": "open",
    }


# ---------------------------------------------------------------- 对外抓取


def fetch_jobs(source_id: str, *, with_detail: bool = True,
               limit: int = 40) -> list[dict[str, Any]]:
    """抓一个来源的岗位列表；with_detail=True 时逐条进详情页补 JD。"""
    cfg = JOB_SOURCES[source_id]
    html = _get(cfg["list_url"])
    if html is None:
        return []

    cards = parse_cards(html)[:limit]
    out: list[dict[str, Any]] = []
    for card in cards:
        text = None
        if with_detail:
            det = _get(card["apply_url"])
            if det:
                text = " ".join(html_to_text(det))
        out.append(build_job(source_id, card, text))
    return out


def _get(url: str) -> str | None:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with _opener().open(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")

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
# 数据源（用户指定，全部为全国岗位）：
#   boss_zhipin  BOSS 直聘   —— 全国 geek/jobs + 重庆城市页。实测三路均被反爬拦截：
#                               静态 HTML 无卡片、JSON 接口回 code=37 安全挑战、
#                               无头浏览器渲染后停在 ?_security_check 安全页。
#                               抓取器保留「JSON 接口 → 端点 HTML → SSR 卡片」回退链，
#                               全失败时**如实返回空列表**，绝不用模型记忆凑数（铁律查无如实报）。
#   mohrss      中国招聘网   —— 人社部 job.mohrss.gov.cn。政府静态页，岗位数据以 JSON 内嵌
#                               在列表页 <input id="findjoblist" value="..."> 里，直接解码
#                               抽取，无需渲染/DOM 解析。
#
# 创新点：mohrss「HTML 内嵌 JSON 直采」—— 政府站把结构化岗位数据藏在 input value 里，
#         解码即得，绕开 DOM 解析；异构双源统一卡片形状 + 技能标签对齐 + 多端点回退链，
#         全失败如实返回空列表 + 不伪造数据。

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from typing import Any

from etl.recruit_fetch import fetch_html, html_to_text

# ---------------------------------------------------------------- 数据源定义

JOB_SOURCES: dict[str, dict[str, Any]] = {
    "boss_zhipin": {
        "name": "BOSS直聘·全国岗位",
        "type": "boss",
        "city": None,
        "region_scope": "全国",
        # 两个端点：全国 geek/jobs + 重庆城市页（用户指定）
        "endpoints": [
            "https://www.zhipin.com/web/geek/jobs?_security_check=1_1794815786926",
            "https://www.zhipin.com/chongqing/?ka=header-home",
        ],
        # BOSS 搜索列表 JSON 接口（需安全令牌，作回退链首环）
        "api_url": "https://www.zhipin.com/wapi/zpgeek/search/joblist.json",
    },
    "mohrss": {
        "name": "中国招聘网（人社部）",
        "type": "mohrss",
        # 岗位列表端点：岗位数据内嵌在页面 <input id="findjoblist"> 的 JSON 里
        "list_url": "http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist?pageNo=1&orderType=score",
        "city": None,
        "region_scope": "全国",
        "pages": 6,  # 实测列表共 6 页
    },
}

# ---------------------------------------------------------------- 单元格解析


def _txt(html: str) -> str:
    """取标签内文字并压平空白。"""
    s = re.sub(r"<[^>]+>", "", html)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&ensp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def _first_text(block: str, pattern: str) -> str | None:
    m = re.search(pattern, block, re.S | re.I)
    return _txt(m.group(1)) if m else None


# ---------------------------------------------------------------- 字段抽取


def parse_salary(text: str | None) -> tuple[float | None, float | None]:
    """把「5-7k」「30-55k·15薪」「8千-1.2万」解析成 (月薪下限, 上限)，单位元。

    抽不出返回 (None, None)。**绝不默认 0** —— 0 元月薪比「未知」更误导人。
    """
    if not text:
        return None, None
    s = text.replace(" ", "").replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*([kK千万])", s)
    if not m:
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


# ---------------------------------------------------------------- 详情页解析

_HEADCOUNT_D = re.compile(r"(?:招聘|招录|招)\s*(\d{1,5})\s*(?:名|人)")
_FULL_DATE_D = re.compile(r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})")
_MD_D = re.compile(r"(\d{1,2})月(\d{1,2})日")

# 详情页里「公司简介 / 平台温馨提示」等样板，不属于岗位 JD，截断在第一个命中处
_JD_BOILERPLATE = ("公司简介", "公司介绍", "猎聘温馨提示", "温馨提示", "平台提示")


def _truncate_jd(body: str) -> str:
    """把 JD 截到「公司简介/温馨提示」等样板之前，避免把公司介绍算进岗位描述。"""
    cut = len(body)
    for mk in _JD_BOILERPLATE:
        idx = body.find(mk)
        if 0 <= idx < cut:
            cut = idx
    return body[:cut].strip()


def parse_detail(text: str) -> dict[str, Any]:
    """从详情页纯文本里抽 JD / 人数 / 发布日期。抽不到一律 None。

    通用版（BOSS / mohrss 通用）：不依赖特定站点的「职位介绍」标记，
    直接取正文、按正则抽人数与日期，并在「公司简介/温馨提示」处截断 JD。
    """
    out: dict[str, Any] = {"description": None, "headcount": None,
                           "published_at": None, "industry_req": None, "_md": None}
    if not text:
        return out

    m = _HEADCOUNT_D.search(text)
    if m:
        out["headcount"] = int(m.group(1))

    m = _FULL_DATE_D.search(text)
    if m:
        y, mo, d = m.groups()
        try:
            out["published_at"] = date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            pass
    else:
        m = _MD_D.search(text)
        if m:
            # 只给「10月26日」没有年份 —— 不猜，记录月/日，年份留给调用方（见 _guess_year）
            out["_md"] = (int(m.group(1)), int(m.group(2)))

    body = _truncate_jd(text.strip())
    if len(body) >= 20:
        out["description"] = body[:8000]
    return out


def _guess_year(month: int, today: date | None = None) -> int:
    """「10月26日更新」→ 年份。

    招聘页不给年份。规则：月 > 当前月 → 去年；否则今年。
    这不是编数据，而是把「相对日期」还原成日历日；错误最多差一年，
    且页面上同时保留了 apply_url，学生可点开看原文。
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
    """把列表卡片 + 详情页正文组装成 recruit_job 一行。

    卡片里若已预置 source_key / skill_tags / headcount（mohrss 内嵌 JSON 直采时已算好），
    则直接沿用，避免重复计算或覆盖。
    """
    cfg = JOB_SOURCES[source_id]
    det = parse_detail(detail_text or "")

    published = det.get("published_at")
    if not published and det.get("_md"):
        mo, dy = det["_md"]
        try:
            published = date(_guess_year(mo), mo, dy).isoformat()
        except ValueError:
            published = None

    desc = det["description"]
    # 技能标签：卡片已抽（mohrss）就沿用，否则从标题/JD/行业现抽（BOSS）
    skills = card.get("skill_tags") or extract_skills(card.get("title"), desc,
                                                      card.get("industry"))
    # 招聘人数：卡片预置优先，否则从详情正文抽
    headcount = card.get("headcount") or det.get("headcount")
    source_key = card.get("source_key") or make_source_key(
        source_id, card["apply_url"], card["title"])

    return {
        "source": source_id,
        "source_key": source_key,
        "title": card["title"][:200],
        "company": (card.get("company") or "未标注单位")[:200],
        "industry": card.get("industry"),
        "city": card.get("city") or cfg["city"],
        "district": card.get("district"),
        "salary_min": card.get("salary_min"),
        "salary_max": card.get("salary_max"),
        "education": card.get("education"),
        "experience": card.get("experience"),
        "headcount": headcount,
        "skill_tags": skills,
        "description": desc,
        "apply_url": card["apply_url"][:500],
        "published_at": published,
        "deadline": None,           # 招聘岗不给报名截止日 —— 不猜
        # 招聘岗默认 open，下架由 last_seen_at 判断（见 sync 脚本）
        "status": "open",
    }


# ---------------------------------------------------------------- BOSS 直聘（SSR/JSON 直采）

# BOSS 列表页是 JS 渲染，静态 HTML 无卡片。但页面做了 SSR：首屏岗位数据以 JSON 内嵌
# 在 HTML 里（__NEXT_DATA__ / __INITIAL_STATE__ / jobList 等）。直采这段 JSON，绕开渲染。
_ASSIGN_RE = re.compile(r'(?:window\.)?(__INITIAL_STATE__|g_initialProps|PAGE_DATA)\s*=\s*')
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)


def _raw_decode_from(s: str, start: int) -> tuple[Any, int]:
    """从 start 起找到第一个 [ 或 {，用 raw_decode 解析（能正确处理字符串里的 ; 与括号）。"""
    i = start
    while i < len(s) and s[i] not in "[{":
        i += 1
    if i >= len(s):
        return None, start
    try:
        return json.JSONDecoder().raw_decode(s[i:])
    except (ValueError, TypeError):
        return None, start


def _extract_json_blob(html: str) -> Any | None:
    """从 HTML 里挖出内嵌的岗位 JSON。依次尝试常见载体，全失败返回 None。"""
    m = _NEXT_DATA_RE.search(html)
    if m:
        obj = _try_load(m.group(1))
        if obj is not None:
            return obj
    for m in _ASSIGN_RE.finditer(html):
        obj, _ = _raw_decode_from(html, m.end())
        if obj is not None:
            return obj
    # 直接找 "jobList":[...] 之类
    for key in ("jobList", "geekJobList", "jobCardList", "jobListData"):
        idx = html.find(f'"{key}"')
        if idx < 0:
            continue
        obj, _ = _raw_decode_from(html, html.find("[", idx))
        if isinstance(obj, list) and obj:
            return obj
    return None


def _try_load(s: str) -> Any | None:
    s = s.strip()
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        i = 0
        while i < len(s) and s[i] not in "[{":
            i += 1
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[i:])
            return obj
        except (ValueError, TypeError):
            return None


_JOB_NAME_KEYS = ("jobName", "jobTitle", "geekJobName", "name")


def _find_job_list(data: Any) -> list[dict[str, Any]]:
    """在嵌套 JSON 里找第一个「元素都带岗位名键」的列表。"""
    stack: list[Any] = [data]
    seen = 0
    while stack and seen < 80:
        node = stack.pop()
        seen += 1
        if isinstance(node, list):
            if node and all(isinstance(x, dict) for x in node) and any(
                any(k in x for k in _JOB_NAME_KEYS) for x in node
            ):
                return node
            for x in node:
                if isinstance(x, (list, dict)):
                    stack.append(x)
        elif isinstance(node, dict):
            for v in node.values():
                if isinstance(v, (list, dict)):
                    stack.append(v)
    return []


def _coerce_boss_card(raw: dict[str, Any]) -> dict[str, Any]:
    """把 BOSS 原始字段归一成通用卡片形状（字段名可能随版本变化，多取几个候选键）。"""
    title = raw.get("jobName") or raw.get("jobTitle") or raw.get("geekJobName") or raw.get("name")
    company = (raw.get("companyName") or raw.get("company") or raw.get("brandName")
               or raw.get("companyBrandName"))
    industry = (raw.get("industry") or raw.get("industryLabel") or raw.get("companyIndustry"))
    salary_raw = raw.get("salaryDesc") or raw.get("salary")
    city = raw.get("city") or raw.get("cityName")
    district = (raw.get("district") or raw.get("areaDistrict") or raw.get("cityDistrict"))
    location = f"{city}-{district}" if (city and district) else city
    edu_raw = raw.get("jobEducation") or raw.get("education") or raw.get("degree")
    exp_raw = (raw.get("jobExperience") or raw.get("experience")
               or raw.get("jobExperienceLabel"))
    sal_lo, sal_hi = parse_salary(salary_raw)
    city_s, district_s = _split_city(location)
    enc = raw.get("encryptJobId") or raw.get("jobId") or ""
    apply_url = raw.get("jobUrl") or raw.get("detailUrl") or raw.get("url")
    if not apply_url and enc:
        apply_url = f"https://www.zhipin.com/job_detail/{enc}.html"
    return {
        "title": title, "company": company, "industry": industry,
        "city": city_s, "district": district_s,
        "salary_min": sal_lo, "salary_max": sal_hi,
        "education": _education_from_label(edu_raw),
        "experience": _experience_from_label(exp_raw),
        "headcount": None,
        "apply_url": apply_url, "job_id": enc or None,
    }


def _coerce_boss_cards(raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一 + 按 apply_url/(标题,单位) 去重。"""
    out: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for r in raws:
        c = _coerce_boss_card(r)
        if not c.get("title"):
            continue
        key = c.get("apply_url") or (c["title"], c.get("company"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _boss_from_api(cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """回退链首环：BOSS 搜索 JSON 接口。需安全令牌，常被反爬拦截 —— 失败即返回 []。"""
    url = f"{cfg['api_url']}?query=&city=100010000&page=1&pageSize=30"
    html = fetch_html(url)
    if not html:
        return []
    try:
        data = json.loads(html)
    except (ValueError, TypeError):
        return []
    zp = data.get("zpData") if isinstance(data, dict) else data
    raws: list[dict[str, Any]] = []
    if isinstance(zp, dict):
        raws = zp.get("jobList") or []
    elif isinstance(zp, list):
        raws = zp
    if not raws:
        raws = _find_job_list(data) if isinstance(data, (dict, list)) else []
    return _coerce_boss_cards(raws)[:limit]


_BOSS_CARD_BLOCK = re.compile(
    r'<li[^>]*class="[^"]*job-card-wrapper[^"]*"[^>]*>(.*?)</li>', re.S | re.I
)


def _boss_from_html_cards(html: str, limit: int) -> list[dict[str, Any]]:
    """末环：SSR 渲染出的岗位卡片 HTML（结构随版本变，抽不到就空）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _BOSS_CARD_BLOCK.findall(html):
        title = _first_text(block, r'class="[^"]*job-name[^"]*"[^>]*>(.*?)<')
        if not title:
            continue
        salary_raw = _first_text(block, r'class="[^"]*salary[^"]*"[^>]*>(.*?)<')
        company = _first_text(block, r'class="[^"]*company-name[^"]*"[^>]*>(.*?)<')
        href_m = re.search(r'href="(/job_detail/[^"]+)"', block)
        apply_url = "https://www.zhipin.com" + href_m.group(1) if href_m else None
        sal_lo, sal_hi = parse_salary(salary_raw)
        key = apply_url or title
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title, "company": company, "industry": None,
            "city": None, "district": None,
            "salary_min": sal_lo, "salary_max": sal_hi,
            "education": None, "experience": None,
            "headcount": None, "apply_url": apply_url, "job_id": None,
        })
    return out[:limit]


def _boss_from_html(html: str, limit: int) -> list[dict[str, Any]]:
    """回退链中环：从 HTML 内嵌 JSON 挖岗位；挖不到再退到 SSR 卡片 HTML。"""
    data = _extract_json_blob(html)
    if data is not None:
        cards = _coerce_boss_cards(_find_job_list(data))
        if cards:
            return cards[:limit]
    return _boss_from_html_cards(html, limit)


def _fetch_boss_jobs(cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """BOSS 多端点回退链：JSON 接口 → 各端点 HTML(SSR/JSON) → SSR 卡片。全失败如实报空。"""
    cards = _boss_from_api(cfg, limit)
    if cards:
        return cards
    for url in cfg["endpoints"]:
        html = fetch_html(url)
        if not html:
            continue
        cards = _boss_from_html(html, limit)
        if cards:
            return cards
    return []


def _find_field(data: Any, keys: tuple[str, ...]) -> Any | None:
    """在嵌套 JSON 里递归找第一个命中的字段值。"""
    stack: list[Any] = [data]
    seen = 0
    while stack and seen < 80:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            for k in keys:
                if k in node and node[k]:
                    return node[k]
            for v in node.values():
                if isinstance(v, (list, dict)):
                    stack.append(v)
        elif isinstance(node, list):
            for x in node:
                if isinstance(x, (list, dict)):
                    stack.append(x)
    return None


def _boss_detail_text(url: str) -> str:
    """BOSS 详情页：优先从 SSR/JSON 取 jobDescription，取不到退到纯文本。"""
    html = fetch_html(url)
    if not html:
        return ""
    data = _extract_json_blob(html)
    if isinstance(data, (dict, list)):
        desc = _find_field(data, ("jobDescription", "jobDesc", "description", "desc"))
        if desc:
            return str(desc)
    return " ".join(html_to_text(html))


# ---------------------------------------------------------------- 中国招聘网（mohrss）
#
# 创新点：mohrss 列表页把整页岗位数据以 JSON 内嵌在
# <input id="findjoblist" name="findjoblist" value='[{...}]'> 的 value 属性里
# （HTML 实体编码 &#034; = "）。直接解码这段 JSON，无需渲染、无需 DOM 解析。
# 字段是政府数据字典编码（aab004=招聘单位、aca112=岗位名称、aab302=城市、
# dxs=学历、md5=来源键等），按实测映射到通用卡片形状。

_MOHRSS_FINDJOB_RE = re.compile(
    r'<input[^>]*id="findjoblist"[^>]*value="([^"]*)"', re.I | re.S
)
# 薪资常内嵌在岗位名里：「综合月薪：2500元」「月薪2500-4000元」
_MOHRSS_SALARY_D = re.compile(r"(?:月薪|薪资)[：:]?\s*(\d+(?:\.\d+)?)\s*[-~至]?\s*(\d+(?:\.\d+)?)?\s*元?")
_MOHRSS_HEADCOUNT_D = re.compile(r"(\d{1,3})\s*名")


def _mohrss_decode_records(page_html: str) -> list[dict[str, Any]]:
    """从列表页 HTML 里解码内嵌 JSON，返回岗位原始记录列表；无则 []。"""
    m = _MOHRSS_FINDJOB_RE.search(page_html)
    if not m:
        return []
    try:
        return json.loads(html.unescape(m.group(1)))
    except (ValueError, TypeError):
        return []


def _mohrss_salary(title: str) -> tuple[float | None, float | None]:
    """从岗位名里抽内嵌薪资（「综合月薪：2500元」→ (2500, None)）。抽不到 (None, None)。"""
    m = _MOHRSS_SALARY_D.search(title or "")
    if not m:
        return None, None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else None
    return lo, hi


def _mohrss_card(rec: dict[str, Any], page_url: str) -> dict[str, Any] | None:
    """把一条 mohrss 原始记录映射成通用卡片形状；无岗位名则 None。"""
    title = (rec.get("aca112") or "").strip()
    if not title:
        return None
    company = (rec.get("aab004") or "").strip() or None
    city = (rec.get("aab302") or rec.get("acb202") or "").strip() or None
    education = (rec.get("dxs") or "").strip() or None
    keywords = (rec.get("keyWords") or "").strip()
    sal_lo, sal_hi = _mohrss_salary(title)
    m_hc = _MOHRSS_HEADCOUNT_D.search(title)
    skills = extract_skills(title, keywords)
    md5 = rec.get("md5")
    source_key = md5 if md5 else make_source_key("mohrss", page_url, title)
    return {
        "title": title, "company": company, "industry": None,
        "city": city, "district": None,
        "salary_min": sal_lo, "salary_max": sal_hi,
        "education": education, "experience": None,
        "headcount": int(m_hc.group(1)) if m_hc else None,
        "skill_tags": skills,
        "apply_url": page_url,
        "source_key": source_key, "job_id": str(rec.get("aab001") or ""),
    }


def _fetch_mohrss_jobs(cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """中国招聘网：逐页解码内嵌 JSON → 卡片，按 source_key/标题去重，截到 limit。"""
    base = cfg["list_url"]
    pages = int(cfg.get("pages", 1))
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 列表端点用 pageNo 分页；orderType=score 按热度
    for page in range(1, pages + 1):
        if len(cards) >= limit:
            break
        url = re.sub(r"pageNo=\d+", f"pageNo={page}", base)
        html = fetch_html(url)
        if not html:
            continue
        for rec in _mohrss_decode_records(html):
            if len(cards) >= limit:
                break
            c = _mohrss_card(rec, url)
            if not c:
                continue
            key = c["source_key"] or (c["title"], c.get("company"))
            if key in seen:
                continue
            seen.add(key)
            cards.append(c)
    return cards


# ---------------------------------------------------------------- 对外抓取


def _fetch_list(cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """按源类型分发到各自的列表抓取器。"""
    if cfg["type"] == "boss":
        return _fetch_boss_jobs(cfg, limit)
    if cfg["type"] == "mohrss":
        return _fetch_mohrss_jobs(cfg, limit)
    return []


def _fetch_detail(url: str | None, source_type: str) -> str:
    if not url:
        return ""
    if source_type == "boss":
        return _boss_detail_text(url)
    # mohrss 无可靠单岗详情页（岗位仅内嵌在列表页 JSON 里），description 如实留空
    return ""


def fetch_jobs(source_id: str, *, with_detail: bool = True,
               limit: int = 40) -> list[dict[str, Any]]:
    """抓一个来源的岗位列表；with_detail=True 时逐条进详情页补 JD。"""
    cfg = JOB_SOURCES[source_id]
    cards = _fetch_list(cfg, limit)
    out: list[dict[str, Any]] = []
    for card in cards:
        text = None
        if with_detail:
            text = _fetch_detail(card.get("apply_url"), cfg["type"])
        out.append(build_job(source_id, card, text))
    return out

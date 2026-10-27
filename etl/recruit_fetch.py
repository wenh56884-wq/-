# etl/recruit_fetch.py
# 职责：从官方公开页面抓「招考公告」，解析成结构化记录（考公 / 考编 / 考研）。
#
# 铁律（和 competition 一致）：
#   1. 只写抓到的东西。字段抓不到就返回 None，绝不填「不限」冒充「没有要求」。
#   2. 每条都带 detail_url + publish_date，学生/老师可点开原文核对。
#   3. 解析失败不抛异常、不中断整轮：单条坏了跳过，用 fetch_* 的返回报告体现。
#
# 三个数据源（全部为政府/官方公开页面）：
#   考编  institution  → 重庆市人力资源和社会保障局「事业单位公开招聘」
#   考公  civil        → 重庆市人力资源和社会保障局「人事考试」+ 国家公务员局
#   考研  postgraduate → 中国研究生招生信息网（研招网）「网报公告」
#
# 注意：这些页面的「具体岗位表」通常在附件（xls/pdf）里，正文只给通用条件。
# 因此 education_req / major_req 等字段可能为 None —— 这是诚实的缺失，不是 bug。

from __future__ import annotations

import hashlib
import re
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Iterator
from urllib.parse import urljoin

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
_TIMEOUT = 20

# ---------------------------------------------------------------- 数据源定义

SOURCES: dict[str, dict[str, Any]] = {
    "cq-sydw": {
        "exam_type": "institution",
        "name": "重庆市事业单位公开招聘",
        "list_url": "https://rlsbj.cq.gov.cn/zwxx_182/sydw/sydwgkzp{y}/",
        "region": "重庆",
        "org": "重庆市人力资源和社会保障局",
        "title_filter": ("招聘", "招考", "考核", "公告", "简章"),
    },
    "cq-rsks": {
        "exam_type": "civil",
        "name": "重庆市人事考试·公务员招录",
        "list_url": "https://rlsbj.cq.gov.cn/ywzl/rsks/",
        "region": "重庆",
        "org": "重庆市人事考试中心",
        # 这个栏目同时挂着建造师/消防工程师等「职业资格考试」，
        # 考公只认公务员/选调/遴选，其余一律不要。
        # 注意：「事业单位遴选」属考编，不归考公，用 title_deny 排掉。
        "title_filter": ("公务员", "选调", "遴选"),
        "title_deny": ("事业单位", "事业编"),
    },
    "yz-chsi": {
        "exam_type": "postgraduate",
        "name": "重庆市教育考试院·研究生考试",
        # 研招网(yz.chsi.com.cn)是纯 JS 渲染，静态 HTML 无内容，无法抓取；
        # 改用重庆市教育考试院（静态页，含本省考研报名公告与要求）。
        "list_url": "https://www.cqksy.cn/site/index.html",
        "region": "重庆",
        "org": "重庆市教育考试院",
        # 只要「XXX招生考试 XXX公告/须知/提醒」形态，排除「艺体招生考试专栏」这类栏目入口
        "title_filter": ("研究生", "硕士", "推免", "调剂"),
        "title_deny": ("专栏", "专题", "栏目", "首页", "更多"),
    },
}


# ---------------------------------------------------------------- 网络层


def _opener() -> urllib.request.OpenerDirector:
    """部分政府站点证书链不完整，这里显式放宽校验（只读公开页面，不传敏感数据）。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_html(url: str) -> str | None:
    """取页面 HTML；失败返回 None（不抛异常，由调用方决定是否记录日志）。"""
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


def html_to_text(html: str) -> list[str]:
    """把 HTML 压成一行一句的纯文本（去脚本/样式/标签）。"""
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "\n", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [ln.strip() for ln in s.split("\n")]
    return [ln for ln in lines if ln]


# ---------------------------------------------------------------- 列表页解析


def parse_list(html: str, base_url: str) -> list[dict[str, str]]:
    """从栏目列表页抽 (标题, 绝对链接, 日期)。

    标题优先取 <a title="完整标题">：政府站列表常把可见文字截成「...」，
    完整标题放在 title 属性里；没有该属性才退回可见文字。

    只保留链接像「文章详情页」的条目（路径里带 t2026xxxx 或 .html），
    避免把导航栏、栏目入口当公告抓回来。
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<a([^>]*?)href="([^"]+)"([^>]*?)>\s*([^<]{0,200}?)\s*</a>', re.I | re.S
    )
    for pre, href, post, visible in pattern.findall(html):
        visible = re.sub(r"\s+", " ", visible).strip()
        attrs = f"{pre} {post}"
        m_title = re.search(r'title="([^"]{6,200})"', attrs, re.I)
        title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else visible
        if not title or len(title) < 8:
            continue
        low = href.lower()
        if not (low.endswith(".html") or ".html?" in low):
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        pub = _date_from_url(full) or _date_from_title(title)
        out.append({"title": title, "url": full, "publish_date": pub or ""})
    return out


def _date_from_url(url: str) -> str | None:
    """从链接里取发布日期。支持两种常见形态：
    1. 政府站：/t20261020_16262763.html   → 2026-10-20
    2. 考试院：/web/article/2026-09/30/content_7131.html → 2026-09-30
    """
    # 形态 1：t + 8 位数字
    m = re.search(r"/t(\d{4})(\d{2})(\d{2})_", url)
    if m:
        y, mo, d = m.groups()
        try:
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            return None
    # 形态 2：/YYYY-MM/DD/
    m = re.search(r"/(\d{4})-(\d{2})/(\d{2})/", url)
    if m:
        y, mo, d = m.groups()
        try:
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            return None
    return None


def _date_from_title(title: str) -> str | None:
    m = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", title)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- 正文要求抽取
#
# 政府公告的正文是**分段**的（「（二）年龄计算」「（三）毕业（学位）证书及专业」），
# 而且关键数字常被 HTML 拆到相邻行（「周岁以下」和「38」不在一行）。
# 所以不能逐行匹配：先把全文拼成一整块连续文本（保留标点、去掉多余空白），
# 再按小节标题定位 → 取该小节到下一个编号标题之间的文字 → 在里面找要求原文。
#
# 原则仍然是：抽不出干净的原文就留 None。宁可「不知道」，也不写错的「要求」。

_SECTION_HEADS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("age_req", ("年龄计算", "年龄要求", "年龄条件")),
    ("education_req", ("学历要求", "学历条件", "学历（学位）")),
    ("degree_req", ("学位要求", "毕业（学位）证书", "毕业（学位）")),
    ("major_req", ("专业要求", "专业条件", "专业资格审查", "所学专业")),
    ("political_req", ("政治面貌", "基本条件", "报考条件", "招聘条件")),
    ("exp_req", ("工作经历", "基层工作经历", "工作年限")),
    ("cert_req", ("资格证书", "职业（执业）资格", "执业资格")),
    ("other_req", ("户籍", "回避", "其他条件")),
)

# 小节标题的形态：（一）（二） / 1. 2. / 一、二、
# 注意：不能加 ^ 锚点 —— _flatten 已把换行去掉，锚点会永远不命中。
_HEAD_MARK = re.compile(r"(?:[（(][一二三四五六七八九十]{1,3}[）)]|[一二三四五六七八九十]{1,3}、|\d{1,2}[．.、])")


def _flatten(lines: list[str]) -> str:
    """把分行正文拼成连续文本。

    中文换行直接粘（不留空格），只有「前一行结尾是英文/数字、下一行开头也是英文」
    时才补空格 —— 否则 2026 会被拆成「202 6」，年龄这类含数字的要求就脏了。
    """
    out = ""
    for ln in lines:
        if not ln:
            continue
        if out and re.search(r"[A-Za-z]$", out) and re.match(r"[A-Za-z]", ln):
            out += " "
        out += ln
    return out


def _sections(flat: str) -> dict[str, str]:
    """按编号标题切小节，返回 {小节标题: 小节正文}。"""
    # 在编号标题前插分隔符，便于切分
    marks = [m.start() for m in _HEAD_MARK.finditer(flat)]
    blocks: dict[str, str] = {}
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(flat)
        chunk = flat[start:end].strip()
        if not chunk:
            continue
        # 标题 = 前 20 字，够做关键词匹配
        blocks[chunk[:20]] = chunk
    return blocks


def _strip_heading(sent: str, keywords: tuple[str, ...]) -> str:
    """去掉句首粘连的小节标题，如「年龄计算本公告所要求…」→「本公告所要求…」。

    做法：关键词出现位置之前如果只是很短的一段（通常就是标题 2~8 字），就砍掉。
    """
    for kw in keywords:
        idx = sent.find(kw)
        if 0 <= idx <= 8:
            rest = sent[idx + len(kw):].lstrip(" ：:，,、")
            if len(rest) >= 8:
                return rest
    return sent


def _pick(blocks: dict[str, str], keywords: tuple[str, ...]) -> str | None:
    """在小节里找命中关键词的那一段，截出与关键词同句的**描述性**原文。

    两道清洗，避免把「（三）毕业（学位）证书及专业」这种纯标题当要求：
      1. 去掉开头的编号与标题短语（标题短语以冒号/句号结束或长度 <12 且无动词）；
      2. 结果必须至少 10 个字，且不能是「报考条件」这种只有名词的短标题。
    """
    for head, body in blocks.items():
        if not any(k in head or k in body[:60] for k in keywords):
            continue
        for sent in re.split(r"[。；]", body):
            sent = sent.strip()
            if not sent or not any(k in sent for k in keywords):
                continue
            sent = _HEAD_MARK.sub("", sent).strip(" ：:，,、")
            # 把「XXX及专业考生凭已取得…」里的标题部分切掉：找第一个「：」或「，」
            if "：" in sent:
                sent = sent.split("：", 1)[1].strip()
            elif ":" in sent:
                sent = sent.split(":", 1)[1].strip()
            sent = _strip_heading(sent, keywords)
            if len(sent) < 10:
                continue
            return sent[:200]
    return None


_SIGNUP_RE = re.compile(
    r"报名(?:时间|期限)[^0-9]{0,20}"
    # 起：2026年10月9日（后面常跟 9:00 之类，用 [^0-9]* 吃掉）
    r"(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})[日号]?"
    r"[^至到\-~—]{0,20}?"
    r"(?:至|到|-|~|—)"
    r"[^0-9]{0,20}"
    # 止：可带年（2026年10月15日），也可只给月日（10月15日）
    r"(?:(\d{4})[年\-/.])?(\d{1,2})[月\-/.](\d{1,2})"
)
_EXAM_RE = re.compile(
    r"笔试(?:时间|日期)[^0-9]{0,12}(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})"
)
_HEADCOUNT_RE = re.compile(r"(?:招聘|招录|计划)[^0-9，。；]{0,12}(\d{1,5})\s*(?:名|人)")


def _safe_date(y: str | None, m: str | None, d: str | None) -> date | None:
    if not (y and m and d):
        return None
    try:
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def extract_requirements(text: str) -> dict[str, Any]:
    """从公告正文抽取各类「要求」字段与时间线；抽不到的一律 None。"""
    out: dict[str, Any] = {name: None for name, _kw in _SECTION_HEADS}
    out.update({
        "headcount": None, "signup_start": None, "signup_end": None, "exam_date": None,
    })
    if not text:
        return out

    flat = _flatten(text.split("\n"))
    blocks = _sections(flat)
    for name, keywords in _SECTION_HEADS:
        out[name] = _pick(blocks, keywords)

    m = _SIGNUP_RE.search(flat)
    if m:
        # 6 组 = 起(年/月/日) + 止(年?/月/日)；年份缺省沿用起始年
        y1, mo1, d1, y2, mo2, d2 = m.groups()
        start = _safe_date(y1, mo1, d1)
        end = _safe_date(y2 or y1, mo2, d2)
        out["signup_start"] = start.isoformat() if start else None
        out["signup_end"] = end.isoformat() if end else None

    m = _EXAM_RE.search(flat)
    if m:
        d = _safe_date(*m.groups())
        out["exam_date"] = d.isoformat() if d else None

    m = _HEADCOUNT_RE.search(flat)
    if m:
        try:
            out["headcount"] = int(m.group(1))
        except ValueError:
            out["headcount"] = None

    return out


# ---------------------------------------------------------------- 记录组装


def make_source_key(source: str, url: str, title: str) -> str:
    """同一来源内稳定的幂等键：优先 url，退化到标题。"""
    basis = f"{source}|{url or title}"
    return hashlib.md5(basis.encode("utf-8")).hexdigest()[:32]


def build_notice(
    source_id: str,
    item: dict[str, str],
    detail_text: str | None = None,
) -> dict[str, Any]:
    """把列表项（+ 可选的正文）组装成 exam_notice 一行。"""
    cfg = SOURCES[source_id]
    req = extract_requirements(detail_text or "")
    publish = _parse_iso(item.get("publish_date"))

    # 状态：有截止日就按截止日判，没有就 unknown（不猜「在招」）
    status = "unknown"
    end = req.get("signup_end")
    if end:
        try:
            status = "open" if date.fromisoformat(end) >= date.today() else "closed"
        except ValueError:
            status = "unknown"

    return {
        "exam_type": cfg["exam_type"],
        "source": source_id,
        "source_key": make_source_key(source_id, item["url"], item["title"]),
        "title": item["title"][:300],
        "org_name": cfg["org"],
        "region": cfg["region"],
        "education_req": req["education_req"],
        "degree_req": req["degree_req"],
        "major_req": req["major_req"],
        "age_req": req["age_req"],
        "political_req": req["political_req"],
        "exp_req": req["exp_req"],
        "cert_req": req["cert_req"],
        "other_req": req["other_req"],
        "headcount": req["headcount"],
        "publish_date": publish,
        "signup_start": req["signup_start"],
        "signup_end": req["signup_end"],
        "exam_date": req["exam_date"],
        "detail_url": item["url"][:500],
        "status": status,
        # 正文原文（截断到 2 万字）：具体岗位表在附件里时，正文仍是可核对的依据
        "raw_text": (detail_text or "")[:20000] or None,
    }


def _parse_iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- 对外抓取


def fetch_notices(source_id: str, *, with_detail: bool = True,
                  limit: int = 60) -> list[dict[str, Any]]:
    """抓一个来源的公告列表，逐个进详情页补「要求」字段。

    with_detail=False 时只取列表（快，用于自检/离线）。
    返回已组装好的 dict 列表；抓不到列表时返回 []。
    """
    cfg = SOURCES[source_id]
    list_url = cfg["list_url"].format(y=date.today().year)
    html = fetch_html(list_url)
    if html is None and "{y}" in cfg["list_url"]:
        # 当年栏目可能还没建，退回上一年
        html = fetch_html(cfg["list_url"].format(y=date.today().year - 1))
        if html is not None:
            list_url = cfg["list_url"].format(y=date.today().year - 1)
    if html is None:
        return []

    items = parse_list(html, list_url)
    # 只保留看起来是该类别的公告：先过通用招考词，再过源级 title_filter
    items = [it for it in items if _looks_like_notice(it["title"])]
    only = cfg.get("title_filter")
    if only:
        items = [it for it in items if any(k in it["title"] for k in only)]
    deny = cfg.get("title_deny")
    if deny:
        items = [it for it in items if not any(k in it["title"] for k in deny)]
    items = items[:limit]

    out: list[dict[str, Any]] = []
    for it in items:
        text = None
        if with_detail:
            detail = fetch_html(it["url"])
            if detail:
                text = "\n".join(html_to_text(detail))
        out.append(build_notice(source_id, it, text))
    return out


_NOTICE_KW = ("招聘", "招考", "考试", "公告", "选调", "遴选", "报名", "简章", "办法")
_NOTICE_DENY = (
    "常见问题", "问题解答", "收费标准", "联系我们", "网站地图", "政策法规",
    # 栏目入口/聚合页，不是具体公告
    "专栏", "专题", "栏目", "更多", "首页",
)


def _looks_like_notice(title: str) -> bool:
    if any(d in title for d in _NOTICE_DENY):
        return False
    return any(k in title for k in _NOTICE_KW)


def iter_sources() -> Iterator[tuple[str, dict[str, Any]]]:
    for sid, cfg in SOURCES.items():
        yield sid, cfg

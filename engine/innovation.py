# engine/innovation.py
# 职责：创新全景聚合层——把已有引擎与既有表里的事实，按「结果 → 测推练补 → 可信来源」
#       三层聚合成一页只读视图。不新增任何计算口径，不写库，不产生新数据。
# 铁律：
#   1. 缺失一律 available=False + value=None，禁止用 0 冒充「没有数据」。
#   2. 抓取时间与核实日期分开：kind="fetched" 用 latest_fetched_at，kind="verified"
#      用 latest_verified_at，两者不互相顶替（抓取不等于核实）。
#   3. 匹配分是「匹配度」，不是「录用概率」，文案里不得出现后者。
#   4. 教师端只返回任教范围内的聚合计数，不返回学生姓名、简历原文、面试原文。
#   5. 任何一项取数失败都降级为 available=False，不让整页 500。

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

import pymysql

from app.config import get_settings

logger = logging.getLogger(__name__)

ENGINE_VERSION = "innovation-v1"

_MISSING_NOTE = "尚未采集"
_STUDENT = "student"
_TEACHER = "teacher"


# --------------------------------------------------------------------------- #
# 基础连接与清洗
# --------------------------------------------------------------------------- #
def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """只读查询；失败返回空列表并把原因写日志，由调用方降级为 available=False。"""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception:
        logger.warning("innovation 查询失败：%s", sql.split("\n")[0][:120], exc_info=True)
        return []


def _one(sql: str, params: Sequence[Any] = ()) -> dict[str, Any]:
    rows = _query(sql, params)
    return rows[0] if rows else {}


def _day(value: Any) -> str | None:
    """统一成 YYYY-MM-DD；None / 非法值一律 None（不猜、不补今天）。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _kpi(key: str, label: str, value: Any, unit: str | None, source: str,
         as_of: Any, engine: str = ENGINE_VERSION, note: str | None = None) -> dict[str, Any]:
    """一张事实卡。value 为 None 即视为未采集，不写 0。"""
    available = value is not None
    return {
        "key": key,
        "label": label,
        "value": value if available else None,
        "unit": unit,
        "available": available,
        "note": note,
        "source_table": source,
        "engine_version": engine,
        "as_of": _day(as_of),
    }


def _step(key: str, label: str, summary: str | None, source: str,
          as_of: Any = None) -> dict[str, Any]:
    ok = bool(summary)
    return {
        "key": key,
        "label": label,
        "summary": summary if ok else None,
        "available": ok,
        "source_table": source,
        "as_of": _day(as_of),
    }


# --------------------------------------------------------------------------- #
# 作用域：学生 = 本人 + 本人班级；教师 = 任教班级全体（只出聚合）
# --------------------------------------------------------------------------- #
def _student_row(tenant_id: int, student_id: int) -> dict[str, Any]:
    return _one(
        "SELECT `编号` AS id, `学号` AS student_no, `姓名` AS name, `班级` AS class_name, "
        "       `专业` AS major, `年级` AS grade "
        "FROM `学生` WHERE `租户编号` = %s AND `编号` = %s",
        (tenant_id, student_id),
    )


def _latest_term(student_id: int) -> str | None:
    row = _one("SELECT MAX(`学期`) AS term FROM `成绩` WHERE `学生编号` = %s", (student_id,))
    return str(row["term"]) if row.get("term") else None


def _teacher_classes(tenant_id: int, teacher_id: int) -> list[str]:
    rows = _query(
        "SELECT `班级` AS class_name FROM `教师任教班级` "
        "WHERE `租户编号` = %s AND `教师编号` = %s ORDER BY `班级`",
        (tenant_id, teacher_id),
    )
    return [str(r["class_name"]) for r in rows if r.get("class_name")]


def _placeholders(items: Sequence[Any]) -> str:
    return ", ".join(["%s"] * len(items)) if items else "NULL"


# --------------------------------------------------------------------------- #
# 屏 1：结果层的事实卡
# --------------------------------------------------------------------------- #
def _kpis_market(tenant_id: int) -> list[dict[str, Any]]:
    """公共数据面（与角色无关）：在库岗位、招考公告、考证目录、面试题库。"""
    job = _one("SELECT COUNT(*) AS n, MAX(`发布时间`) AS ts FROM `岗位`")
    exam = _one("SELECT COUNT(*) AS n, MAX(`最近发现时间`) AS ts FROM `招考公告` WHERE `租户编号` = %s",
                (tenant_id,))
    cert = _one("SELECT COUNT(*) AS n, MAX(`核实日期`) AS ts FROM `考证目录`")
    bank = _one("SELECT COUNT(*) AS n, MAX(`采集时间`) AS ts FROM `面试题库` WHERE `校验状态` = 'verified'")

    return [
        _kpi("job_supply", "在库岗位", int(job["n"]) if job.get("n") else None, "条",
             "岗位", job.get("ts"), "job-v1",
             note="快照数据，发布时间不代表仍在招聘"),
        _kpi("exam_notices", "招考公告", int(exam["n"]) if exam.get("n") else None, "条",
             "招考公告", exam.get("ts"), "exam-v1", note="抓取时间，非人工核实日期"),
        _kpi("cert_catalog", "考证目录", int(cert["n"]) if cert.get("n") else None, "项",
             "考证目录", cert.get("ts"), "cert-v1", note="已人工核实"),
        _kpi("question_bank", "已校验面试题", int(bank["n"]) if bank.get("n") else None, "道",
             "面试题库", bank.get("ts"), "qb-v1"),
    ]


def _kpis_practice(tenant_id: int, class_names: Sequence[str] | None) -> list[dict[str, Any]]:
    """练习面：面试场次、简历份数、真实录用数据（后者库内不存在）。

    class_names=None 表示全租户（无可用范围时的兜底）；给了班级就只聚合任教班级，
    与「教师只看任教范围」的口径一致。
    """
    where = "`租户编号` = %s"
    params: list[Any] = [tenant_id]
    if class_names:
        where += (f" AND `学生编号` IN (SELECT `编号` FROM `学生` "
                  f"WHERE `租户编号` = %s AND `班级` IN ({_placeholders(class_names)}))")
        params += [tenant_id, *class_names]

    ses = _one(f"SELECT COUNT(*) AS n, MAX(`完成时间`) AS ts FROM `面试会话` "
               f"WHERE {where} AND `状态` = 'finished'", tuple(params))
    res = _one(f"SELECT COUNT(*) AS n, MAX(`更新时间`) AS ts FROM `简历` WHERE {where}", tuple(params))

    return [
        _kpi("interview_finished", "已完成模拟面试", int(ses["n"]) if ses.get("n") else None, "场",
             "面试会话", ses.get("ts"), "interview-v1",
             note=None if ses.get("n") else "尚无完成记录"),
        _kpi("resume_count", "在库简历", int(res["n"]) if res.get("n") else None, "份",
             "简历", res.get("ts"), "resume-v1"),
        # 库内没有投递/邀约/录用表，任何「就业率/转化率」都无从计算，只能诚实标未采集
        _kpi("real_interview", "真实投递与录用", None, None, "—", None, ENGINE_VERSION,
             note="库内无投递/录用表，就业转化类指标一律不展示"),
    ]


def _kpis_student(tenant_id: int, student: Mapping[str, Any], term: str | None) -> list[dict[str, Any]]:
    sid = int(student.get("id") or 0)
    g = _one("SELECT COUNT(*) AS n, MAX(`分数`) AS top FROM `成绩` WHERE `学生编号` = %s", (sid,))
    view = _one("SELECT COUNT(*) AS n, MAX(`创建时间`) AS ts FROM `岗位浏览日志` "
                "WHERE `租户编号` = %s AND `学生编号` = %s", (tenant_id, sid))
    assess = _one("SELECT COUNT(*) AS n, MAX(`创建时间`) AS ts FROM `测评结果` "
                  "WHERE `租户编号` = %s AND `学生编号` = %s", (tenant_id, sid))
    intent = _one("SELECT `意向` AS v, `更新时间` AS ts FROM `职业意向` "
                  "WHERE `租户编号` = %s AND `学生编号` = %s ORDER BY `更新时间` DESC LIMIT 1",
                  (tenant_id, sid))

    return [
        _kpi("my_grades", "本人成绩记录", int(g["n"]) if g.get("n") else None, "条",
             "成绩", None, "grades-v1", note=f"最新学期 {term}" if term else None),
        _kpi("my_job_views", "本人岗位浏览", int(view["n"]) if view.get("n") else None, "次",
             "岗位浏览日志", view.get("ts"), "behavior-v1"),
        _kpi("my_assessment", "软技能测评", int(assess["n"]) if assess.get("n") else None, "次",
             "测评结果", assess.get("ts"), "assessment-v1",
             note=None if assess.get("n") else "未测评，推荐缺软技能与潜力两维"),
        _kpi("my_intent", "职业意向", intent.get("v") or None, None,
             "职业意向", intent.get("ts"), "career-v1"),
        # 库内没有投递/邀约/录用表：学生端也显式给出「尚未采集」卡，
        # 而不是让这张卡凭空消失——缺席也是一种必须可见的事实
        _kpi("real_interview", "真实投递与录用", None, None, "—", None, ENGINE_VERSION,
             note="库内无投递/录用表，就业转化类指标一律不展示"),
    ]


def _intent_distribution(tenant_id: int, class_names: Sequence[str]) -> dict[str, int]:
    if not class_names:
        return {}
    rows = _query(
        "SELECT i.`意向` AS v, COUNT(*) AS n FROM `职业意向` i "
        "JOIN `学生` s ON s.`编号` = i.`学生编号` AND s.`租户编号` = i.`租户编号` "
        f"WHERE i.`租户编号` = %s AND s.`班级` IN ({_placeholders(class_names)}) "
        "GROUP BY i.`意向` ORDER BY n DESC",
        tuple([tenant_id, *class_names]),
    )
    return {str(r["v"]): int(r["n"]) for r in rows if r.get("v")}


# --------------------------------------------------------------------------- #
# 屏 2：测—推—练—补
# --------------------------------------------------------------------------- #
def _loop_student(tenant_id: int, student: Mapping[str, Any], instance: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    sid = int(student.get("id") or 0)
    assess = _one("SELECT `总分` AS score, `满分` AS full, `创建时间` AS ts, `引擎版本` AS v "
                  "FROM `测评结果` WHERE `租户编号` = %s AND `学生编号` = %s "
                  "ORDER BY `创建时间` DESC LIMIT 1", (tenant_id, sid))
    ses = _one("SELECT COUNT(*) AS n, MAX(`总分`) AS top, MAX(`完成时间`) AS ts FROM `面试会话` "
               "WHERE `租户编号` = %s AND `学生编号` = %s AND `状态` = 'finished'", (tenant_id, sid))

    measure = (f"已测评：{_num(assess.get('score')) or 0:.0f}/{_num(assess.get('full')) or 0:.0f} 分"
               if assess.get("ts") else None)
    push = None
    if instance:
        push = (f"引擎对在库岗位逐条打分，当前最高匹配度 "
                f"{_num(instance.get('final_score')) or 0:.1f}（{instance.get('job_title')}）；"
                f"匹配度不是录用概率")
    practice = (f"已完成 {int(ses['n'])} 场模拟面试，单场最高 {_num(ses.get('top')) or 0:.1f} 分"
                if ses.get("ts") else None)
    gaps = [g for g in (instance or {}).get("gap_items") or [] if g]
    fill = (f"待补缺口 {len(gaps)} 项，首项：{gaps[0]}" if gaps else None)

    return [
        _step("measure", "测：软技能与能力底数", measure, "测评结果", assess.get("ts")),
        _step("push", "推：岗位匹配与解释", push, "岗位 / 课程成绩"),
        _step("practice", "练：模拟面试与复盘", practice, "面试会话", ses.get("ts")),
        _step("fill", "补：缺口回到课程", fill, "课程 / 岗位技能标签"),
    ]


def _loop_teacher(tenant_id: int, class_names: Sequence[str]) -> list[dict[str, Any]]:
    if not class_names:
        return [
            _step("measure", "测：软技能与能力底数", None, "测评结果"),
            _step("push", "推：岗位匹配与解释", None, "职业意向"),
            _step("practice", "练：模拟面试与复盘", None, "面试会话"),
            _step("fill", "补：缺口回到课程", None, "课程 / 岗位技能标签"),
        ]
    ph = _placeholders(class_names)
    assess = _one(
        "SELECT COUNT(DISTINCT r.`学生编号`) AS n, MAX(r.`创建时间`) AS ts FROM `测评结果` r "
        "JOIN `学生` s ON s.`编号` = r.`学生编号` AND s.`租户编号` = r.`租户编号` "
        f"WHERE r.`租户编号` = %s AND s.`班级` IN ({ph})",
        tuple([tenant_id, *class_names]))
    ses = _one(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT r.`学生编号`) AS people, MAX(r.`完成时间`) AS ts "
        "FROM `面试会话` r JOIN `学生` s ON s.`编号` = r.`学生编号` AND s.`租户编号` = r.`租户编号` "
        f"WHERE r.`租户编号` = %s AND s.`班级` IN ({ph}) AND r.`状态` = 'finished'",
        tuple([tenant_id, *class_names]))
    dist = _intent_distribution(tenant_id, class_names)

    measure = (f"任教班级已有 {int(assess['n'])} 人完成软技能测评"
               if assess.get("n") else None)
    push = ("；".join(f"{k} {v} 人" for k, v in list(dist.items())[:4]) or None) if dist else None
    practice = (f"任教班级累计 {int(ses['n'])} 场模拟面试，覆盖 {int(ses['people'])} 人"
                if ses.get("n") else None)

    return [
        _step("measure", "测：软技能与能力底数", measure, "测评结果", assess.get("ts")),
        _step("push", "推：班级意向分布", push, "职业意向"),
        _step("practice", "练：模拟面试与复盘", practice, "面试会话", ses.get("ts")),
        # 缺口按班聚合尚无引擎输出，显式标未采集，不用 0 或估算值填
        _step("fill", "补：缺口回到课程", None, "课程 / 岗位技能标签"),
    ]


# --------------------------------------------------------------------------- #
# 本人实例：岗位技能 — 课程成绩 — 分位
# --------------------------------------------------------------------------- #
def _percentile_evidence(tenant_id: int, student: Mapping[str, Any], term: str | None,
                         job_tags: Sequence[str]) -> list[dict[str, Any]]:
    """该岗位技能对应的课程成绩 + 班内分位。分位按同班同课程排名现算，不落库。"""
    class_name = str(student.get("class_name") or "")
    sid = int(student.get("id") or 0)
    if not class_name or not term:
        return []
    rows = _query(
        "SELECT c.`课程名称` AS course, sc.`学生编号` AS sid, sc.`分数` AS score "
        "FROM `成绩` sc JOIN `课程` c ON c.`编号` = sc.`课程编号` "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
        "WHERE s.`租户编号` = %s AND s.`班级` = %s AND sc.`学期` = %s",
        (tenant_id, class_name, term),
    )
    if not rows:
        return []

    from engine.kg import skills_for_course

    wanted = {str(t).strip() for t in job_tags if str(t).strip()}
    by_course: dict[str, list[float]] = {}
    mine: dict[str, float] = {}
    for r in rows:
        course = str(r.get("course") or "")
        score = _num(r.get("score"))
        if not course or score is None:
            continue
        by_course.setdefault(course, []).append(score)
        if int(r.get("sid") or 0) == sid:
            mine[course] = score
    if not mine:
        return []

    if wanted:
        picked = [c for c in mine if wanted & set(skills_for_course(c))]
    else:
        picked = []
    if not picked:  # 岗位技能没映射到课程时，退化为本人得分最高的 5 门，仍标注真实分位
        picked = sorted(mine, key=lambda c: (-mine[c], c))[:5]

    out: list[dict[str, Any]] = []
    for course in sorted(picked, key=lambda c: (-mine[c], c))[:8]:
        peers = by_course.get(course) or []
        score = mine[course]
        pct = round(100.0 * sum(1 for s in peers if s <= score) / len(peers), 1) if peers else None
        # 分位样本量必须显式给出：3 人班里的「前 100%」没有说服力，不能只给读数不给分母
        out.append({"course": course, "score": round(score, 1),
                    "percentile": pct, "sample_size": len(peers)})
    return out


_OPEN_EDUCATIONS = ("大专", "专科", "不限")


def _usable_tags(tags: Iterable[Any]) -> list[str]:
    """丢掉只有标点的脏标签（真实数据里出现过 "[" 这种），保留有实义字符的。"""
    out: list[str] = []
    for tag in tags:
        text = str(tag or "").strip()
        if text and any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            out.append(text)
    return out


def _instance(tenant_id: int, student: Mapping[str, Any], term: str | None) -> dict[str, Any] | None:
    """本人实例：取「技能有实证交集且学历门槛可投」的岗位里匹配度最高的一条。

    候选池三级收敛（不伪造匹配、不改打分口径）：
      ① 方向相关 ∩ 技能交集 ∩ 学历可投（大专/专科/不限）
      ② 退化为 方向相关 ∩ 技能交集
      ③ 再退化为 方向相关岗位
    打分与排序全部交给 engine.recommend，本层只做候选集筛选。
    """
    student_no = str(student.get("student_no") or "")
    if not student_no or not term:
        return None
    try:
        from engine.recommend import _tokens, load_jobs, load_student, recommend

        profile = load_student(tenant_id, student_no, term)
        if not profile.get("major") and profile.get("gpa") is None:
            return None
        jobs = load_jobs(profile.get("directions") or [])
        if not jobs:
            return None

        mine: set[str] = set()
        for name in profile.get("skills") or []:
            mine |= _tokens(str(name))

        def overlap(job: Mapping[str, Any]) -> int:
            tags: set[str] = set()
            for tag in _usable_tags(job.get("skill_tags") or []):
                tags |= _tokens(tag)
            return len(mine & tags)

        with_evidence = [j for j in jobs if overlap(j) > 0]
        open_first = [j for j in with_evidence
                      if str(j.get("education") or "").strip() in _OPEN_EDUCATIONS]
        pool = open_first or with_evidence or jobs
        top = recommend(profile, pool, top_n=1)["items"][0]
        chosen = next((j for j in pool
                       if int(j.get("id") or 0) == int(top.get("job_id") or 0)), {})
        job_tags = _usable_tags(chosen.get("skill_tags") or [])
    except Exception:
        logger.warning("innovation 实例打分失败，降级为 None", exc_info=True)
        return None

    return {
        "job_title": top.get("title"),
        "final_score": top.get("final_score"),
        "hit_items": list(top.get("hit_items") or []),
        "gap_items": list(top.get("gap_items") or []),
        "evidence": _percentile_evidence(tenant_id, student, term, job_tags),
    }



# --------------------------------------------------------------------------- #
# 屏 3：可信事实与区域产业
# --------------------------------------------------------------------------- #
def _sources(tenant_id: int) -> list[dict[str, Any]]:
    """事实来源清单：核实日期与抓取日期分字段，不互相顶替。"""
    exam = _one("SELECT COUNT(*) AS n, MAX(`最近发现时间`) AS fetched, MAX(`发布日期`) AS published "
                "FROM `招考公告` WHERE `租户编号` = %s", (tenant_id,))
    positions = _one("SELECT COUNT(*) AS n, MAX(`最近发现时间`) AS fetched FROM `国考职位` "
                     "WHERE `租户编号` = %s", (tenant_id,))
    cert = _one("SELECT COUNT(*) AS n, MAX(`核实日期`) AS verified FROM `考证目录`")
    bank = _one("SELECT COUNT(*) AS n, MAX(`采集时间`) AS fetched FROM `面试题库` "
                "WHERE `校验状态` = 'verified'")
    job = _one("SELECT COUNT(*) AS n, MAX(`发布时间`) AS published FROM `岗位`")

    def item(name: str, kind: str, records: Any, when: Any, link: str | None) -> dict[str, Any]:
        ts = _day(when)
        return {
            "name": name,
            "kind": kind,
            "records": int(records) if records else None,
            "latest_verified_at": ts if kind == "verified" else None,
            "latest_fetched_at": ts if kind == "fetched" else None,
            "link": link,
        }

    return [
        item("招考公告（考公/考编/考研）", "fetched", exam.get("n"), exam.get("fetched"),
             "https://www.mohrss.gov.cn/"),
        item("国考职位表", "fetched", positions.get("n"), positions.get("fetched"),
             "http://bm.scs.gov.cn/"),
        item("考证目录", "verified", cert.get("n"), cert.get("verified"), None),
        item("面试题库（已校验）", "fetched", bank.get("n"), bank.get("fetched"), None),
        item("在库岗位（快照）", "fetched", job.get("n"), job.get("published"), None),
    ]


# 全国地图省级白名单：与 web/public/geo/china.json 的 features[].properties.name 逐字一致。
# geo 文件另有一个 name="" 的占位 feature（共 35 项），不是省，必须排除。
PROVINCE_NAMES = frozenset({
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省",
    "黑龙江省", "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省",
    "山东省", "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省",
    "重庆市", "四川省", "贵州省", "云南省", "西藏自治区", "陕西省", "甘肃省",
    "青海省", "宁夏回族自治区", "新疆维吾尔自治区", "台湾省", "香港特别行政区",
    "澳门特别行政区",
})

# 城市 → 省内置映射：只收录库内真实出现、且能明确归属的城市；不猜、不近似。
# 按省分组便于逐条审计；键是岗位表的「城市」原文，值必须落在 PROVINCE_NAMES 内。
_CITY_GROUPS: dict[str, tuple[str, ...]] = {
    "北京市": ("北京",),
    "天津市": ("天津",),
    "河北省": ("石家庄", "保定", "廊坊", "沧州", "雄安新区"),
    "山西省": ("太原", "晋中"),
    "内蒙古自治区": ("呼和浩特", "乌海"),
    "辽宁省": ("沈阳", "大连", "葫芦岛"),
    "吉林省": ("长春", "吉林"),
    "黑龙江省": ("哈尔滨", "大庆"),
    "上海市": ("上海",),
    "江苏省": ("南京", "苏州", "无锡", "常州", "昆山", "张家港", "太仓", "常熟",
               "南通", "徐州", "泰州", "扬州", "镇江", "盐城", "连云港", "宿迁", "淮安"),
    "浙江省": ("杭州", "宁波", "温州", "台州", "嘉兴", "绍兴", "湖州", "舟山",
               "金华", "义乌", "丽水", "衢州"),
    "安徽省": ("合肥", "芜湖", "马鞍山", "蚌埠", "滁州", "铜陵", "六安", "安庆",
               "宣城", "阜阳", "淮南"),
    "福建省": ("福州", "厦门", "泉州", "莆田"),
    "江西省": ("南昌", "赣州", "九江", "宜春", "吉安", "上饶", "抚州", "萍乡"),
    "山东省": ("青岛", "济南", "烟台", "东营", "临沂", "聊城", "潍坊", "济宁", "菏泽"),
    "河南省": ("郑州", "洛阳", "平顶山", "新乡", "许昌", "南阳", "开封", "焦作", "驻马店"),
    "湖北省": ("武汉", "宜昌", "襄阳", "荆门", "天门", "湖北省", "潜江", "荆州",
               "黄冈", "随州"),
    "湖南省": ("长沙", "株洲", "郴州", "益阳", "娄底", "常德", "衡阳", "邵阳", "永州"),
    "广东省": ("广州", "深圳", "东莞", "佛山", "珠海", "中山", "江门", "惠州", "汕头",
               "清远", "肇庆", "云浮", "茂名", "韶关", "河源"),
    "广西壮族自治区": ("南宁", "钦州", "柳州", "梧州", "河池", "北海"),
    "海南省": ("海口",),
    "重庆市": ("重庆",),
    "四川省": ("成都", "绵阳", "眉山", "德阳", "乐山", "宜宾", "广安", "内江", "南充"),
    "贵州省": ("贵阳", "铜仁", "黔西南"),
    "云南省": ("昆明", "曲靖", "西双版纳", "丽江", "玉溪", "保山", "文山", "大理", "红河州"),
    "西藏自治区": ("林芝",),
    "陕西省": ("西安", "宝鸡", "咸阳"),
    "甘肃省": ("兰州", "武威"),
    "青海省": ("西宁",),
    "宁夏回族自治区": ("银川",),
    "新疆维吾尔自治区": ("乌鲁木齐", "和田", "昌吉回族自治州"),
}
_CITY_TO_PROVINCE: dict[str, str] = {
    city: province for province, cities in _CITY_GROUPS.items() for city in cities
}


def _province_supply() -> dict[str, Any]:
    """按省聚合在库岗位数：只认内置映射，映射不到的城市不猜、只计个数。"""
    rows = _query("SELECT `城市` AS city, COUNT(*) AS n FROM `岗位` GROUP BY `城市`")
    province_counts: dict[str, int] = {}
    unmapped_cities = 0
    for row in rows:
        city = str(row.get("city") or "")
        n = int(row.get("n") or 0)
        province = _CITY_TO_PROVINCE.get(city)
        if province not in PROVINCE_NAMES or n <= 0:
            unmapped_cities += 1
            continue
        province_counts[province] = province_counts.get(province, 0) + n
    return {"province_counts": province_counts, "unmapped_cities": unmapped_cities}


def _supply(limit_cities: int = 12, limit_industries: int = 8) -> dict[str, Any]:
    """城市 × 行业岗位供给矩阵。只数在库岗位条数，不推算需求或成功率。

    先取 top 城市/行业名单，再把名单下推进 GROUP BY 的 IN 条件——
    不能先 LIMIT 截断再后置过滤，否则小格子会被静默截掉、矩阵缺格。
    """
    province = _province_supply()
    cities = _query("SELECT `城市` AS v, COUNT(*) AS n FROM `岗位` "
                    "WHERE `城市` IS NOT NULL AND TRIM(`城市`) <> '' "
                    "GROUP BY `城市` ORDER BY n DESC, v LIMIT %s", (limit_cities,))
    industries = _query("SELECT `行业` AS v, COUNT(*) AS n FROM `岗位` "
                        "WHERE `行业` IS NOT NULL AND TRIM(`行业`) <> '' "
                        "GROUP BY `行业` ORDER BY n DESC, v LIMIT %s", (limit_industries,))
    keep_c = [str(r["v"]) for r in cities]
    keep_i = [str(r["v"]) for r in industries]
    # 城市查询已经查出了 COUNT(*) AS n，原样留用；不新增查询、不改分组与排序口径
    city_counts = {
        str(r["v"]): int(r["n"]) for r in cities
        if r.get("v") and r.get("n") is not None and int(r["n"]) > 0
    }
    if not keep_c or not keep_i:
        return {"cells": [], "cities": keep_c, "industries": keep_i,
                "city_counts": city_counts,
                "province_counts": province["province_counts"],
                "unmapped_cities": province["unmapped_cities"]}
    rows = _query(
        "SELECT `城市` AS city, `行业` AS industry, COUNT(*) AS count FROM `岗位` "
        f"WHERE `城市` IN ({_placeholders(keep_c)}) AND `行业` IN ({_placeholders(keep_i)}) "
        "GROUP BY `城市`, `行业`",
        tuple([*keep_c, *keep_i]),
    )
    cells = [
        {"city": str(r["city"]), "industry": str(r["industry"]), "count": int(r["count"])}
        for r in rows
        if str(r["city"]) in keep_c and str(r["industry"]) in keep_i and int(r["count"]) > 0
    ]
    return {"cells": cells, "cities": keep_c, "industries": keep_i,
            "city_counts": city_counts,
            "province_counts": province["province_counts"],
            "unmapped_cities": province["unmapped_cities"]}


def _interest(tenant_id: int, student_ids: Sequence[int] | None,
              class_names: Sequence[str]) -> list[dict[str, Any]]:
    """浏览/关注热度：分母是「浏览记录」，与岗位供给的分母不同，不合并成转化率。"""
    base = ("SELECT j.`岗位名称` AS job, COUNT(*) AS views FROM `岗位浏览日志` l "
            "JOIN `岗位` j ON j.`编号` = l.`岗位编号` "
            "WHERE l.`租户编号` = %s AND l.`动作` = 'view'")
    params: list[Any] = [tenant_id]
    if student_ids is not None:
        base += f" AND l.`学生编号` IN ({_placeholders(student_ids)})"
        params += list(student_ids)
    elif class_names:
        base += (f" AND l.`学生编号` IN (SELECT `编号` FROM `学生` "
                 f"WHERE `租户编号` = %s AND `班级` IN ({_placeholders(class_names)}))")
        params += [tenant_id, *class_names]
    base += " GROUP BY j.`岗位名称` ORDER BY views DESC, job LIMIT 10"
    return [{"job": str(r["job"]), "views": int(r["views"])} for r in _query(base, tuple(params))]


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def build_overview(*, role: str, tenant_id: int, student_id: int | None = None,
                   teacher_id: int | None = None) -> dict[str, Any]:
    """返回创新全景的唯一只读契约。前端 web/src/views/InnovationHub.vue 逐字依赖其形状。

    学生：本人事实卡 + 本人实例（含课程分位）；教师：任教范围内聚合，不出个人证据。
    越权（学生却缺 student_id / 教师却缺 teacher_id）直接抛 PermissionError，由路由转 403。
    """
    if role == _STUDENT:
        if not student_id:
            raise PermissionError("学生端缺少本人身份，无法聚合")
        student = _student_row(tenant_id, student_id)
        if not student:
            raise PermissionError("学生不在当前租户内")
        term = _latest_term(student_id)
        instance = _instance(tenant_id, student, term)
        return {
            "role": _STUDENT,
            "as_of": date.today().isoformat(),
            "engine_version": ENGINE_VERSION,
            "scope": {"tenant_id": tenant_id, "class_id": student.get("class_name")},
            "screens": {
                "result": {"kpis": _kpis_market(tenant_id) + _kpis_student(tenant_id, student, term)},
                "loop": {"steps": _loop_student(tenant_id, student, instance), "instance": instance},
                "trust": {
                    "sources": _sources(tenant_id),
                    "supply": _supply(),
                    "interest": _interest(tenant_id, [student_id], []),
                },
            },
        }

    if role == _TEACHER:
        if not teacher_id:
            raise PermissionError("教师端缺少本人身份，无法确定任教范围")
        classes = _teacher_classes(tenant_id, teacher_id)
        if not classes:
            raise PermissionError("当前教师没有任教班级，取不到可展示范围")
        return {
            "role": _TEACHER,
            "as_of": date.today().isoformat(),
            "engine_version": ENGINE_VERSION,
            "scope": {"tenant_id": tenant_id,
                      "class_id": classes[0] if len(classes) == 1 else None,
                      "class_count": len(classes)},
            "screens": {
                "result": {"kpis": _kpis_market(tenant_id) + _kpis_practice(tenant_id, classes)},
                "loop": {"steps": _loop_teacher(tenant_id, classes), "instance": None},
                "trust": {
                    "sources": _sources(tenant_id),
                    "supply": _supply(),
                    "interest": _interest(tenant_id, None, classes),
                },
            },
        }

    raise PermissionError(f"未知角色：{role}")

# agents/career/context.py
# 职责：职业规划模块的取数/落库层（student_extra / career_plan / plan_rule / week_snapshot / notice）
# 依赖：pymysql / app.config / rules/*.json
# 说明：本模块只做「查库 + 组装 facts + 原样落库」，**不做任何判定**；
#       所有判定一律交给 engine.career_rules，模型永远不碰数值。

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pymysql

from app.config import get_settings
from engine.career_guide import grade_label

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"

# 目标类型 → 模板文件名
TEMPLATE_FILES: dict[str, str] = {
    "考公": "kaogong.json",
    "考编": "kaobian.json",
    "考研": "kaoyan.json",
    "就业": "jiuye.json",
}


# ----------------------------------------------------------------
# 连接
# ----------------------------------------------------------------
def connect() -> pymysql.connections.Connection:
    """建立 MySQL 连接（口令只从 .env 读，禁止硬编码）。"""
    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def _json_load(raw: Any, default: Any) -> Any:
    """把 JSON 列（字符串或已解析）统一解成 Python 对象。"""
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except ValueError:
            return default
    return default


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _iso(value: Any) -> Any:
    """date/datetime → ISO 字符串，其余原样返回。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


# ----------------------------------------------------------------
# 规则库（模板是数据不是代码，管理员改 JSON 不动代码）
# ----------------------------------------------------------------
def load_template(goal: str) -> dict[str, Any]:
    """按目标类型读模板；找不到返回空 dict（由调用方按 unknown 处理）。"""
    name = TEMPLATE_FILES.get(str(goal or "").strip())
    if not name:
        return {}
    path = RULES_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def available_templates() -> list[str]:
    """列出可用模板的键（考公/考研/就业），供健康检查与前端下拉。"""
    return [k for k, v in TEMPLATE_FILES.items() if (RULES_DIR / v).exists()]


def _grade_label(enroll_year: Any, today: date | None = None) -> str | None:
    """由入学年份推算年级标签（大一大二大三大四/已毕业）。

    保留本函数名是为了兼容既有调用与测试；实际算法统一在
    engine.career_guide.grade_label，避免教师端/学生端两处口径漂移。
    """
    return grade_label(enroll_year, today)


# ----------------------------------------------------------------
# 学生事实（硬门槛比对输入；缺失一律 None，绝不补默认值）
# ----------------------------------------------------------------
def fetch_student_facts(tenant_id: int, student_id: int) -> dict[str, Any]:
    """取硬门槛比对所需的全部事实。

    关键：**没有数据就是 None**，不许写成 0 或空串。
    这是「缺失不冒充」在 career 模块的落地（与指标口径字典 §3.2 同一口径）。
    """
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT `编号` AS id, `学号` AS student_no, `姓名` AS name, `专业` AS major,
                   `学院` AS college, `班级` AS class_name, `年级` AS grade,
                   `入学年份` AS enroll_year
            FROM `学生`
            WHERE `编号` = %s AND `租户编号` = %s
            """,
            (student_id, tenant_id),
        )
        base = cur.fetchone() or {}

        # 四六级 / 政治面貌：没有记录 = 未采集（None），不是"未通过"
        cur.execute(
            """
            SELECT `四级分数` AS cet4_score, `六级分数` AS cet6_score,
                   `政治面貌` AS political_status, `意向城市` AS target_city,
                   `每周学时` AS weekly_hours
            FROM `学生扩展信息`
            WHERE `学生编号` = %s AND `租户编号` = %s
            """,
            (student_id, tenant_id),
        )
        extra = cur.fetchone() or {}

        # 绩点/挂科从业务表现算（不跨库读 DuckDB，避免 career 模块依赖派生表）
        cur.execute(
            """
            SELECT ROUND(AVG(`分数`), 2) AS gpa,
                   SUM(CASE WHEN `分数` < 60 THEN 1 ELSE 0 END) AS fail_count,
                   COUNT(*) AS course_cnt
            FROM `成绩`
            WHERE `学生编号` = %s
            """,
            (student_id,),
        )
        score_row = cur.fetchone() or {}

        # 证书/竞赛/项目数来自 学生活动（P2-3 灌的行为表）
        cur.execute(
            """
            SELECT `活动类型` AS activity_type, COUNT(*) AS cnt
            FROM `学生活动`
            WHERE `学生编号` = %s AND `租户编号` = %s
            GROUP BY `活动类型`
            """,
            (student_id, tenant_id),
        )
        act = {str(r["activity_type"]): int(r["cnt"]) for r in (cur.fetchall() or [])}

        fail_cnt = score_row.get("fail_count")
        return {
            "student_id": base.get("id"),
            "student_no": base.get("student_no"),
            "name": base.get("name"),
            "major": base.get("major"),
            "college": base.get("college"),
            "class_name": base.get("class_name"),
            # grade 是入学年份（如 "2025"），这里换成真正的年级标签
            "enroll_year": base.get("enroll_year"),
            "grade": _grade_label(base.get("enroll_year") or base.get("grade")),
            # 学历层次：本校为本科院校，统一按「本科」；专科/研究生需另建字段
            "degree": "本科",
            "cet4_score": extra.get("cet4_score"),
            "cet6_score": extra.get("cet6_score"),
            "political_status": extra.get("political_status"),
            "target_city": extra.get("target_city"),
            "weekly_hours": float(extra["weekly_hours"]) if extra.get("weekly_hours") is not None else None,
            "gpa": float(score_row["gpa"]) if score_row.get("gpa") is not None else None,
            "fail_count": int(fail_cnt) if fail_cnt is not None else None,
            "cert_count": act.get("cert", 0),
            "contest_count": act.get("contest", 0),
            "project_cnt": act.get("project", 0),
            "has_score": bool(score_row.get("course_cnt")),
        }
    finally:
        conn.close()


def save_student_extra(
    tenant_id: int,
    student_id: int,
    *,
    cet4_score: int | None = None,
    cet6_score: int | None = None,
    political_status: str | None = None,
    target_city: str | None = None,
    weekly_hours: float | None = None,
) -> None:
    """写入/更新学生补充信息（只更新传入的非 None 字段）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO `学生扩展信息`
                    (`租户编号`, `学生编号`, `四级分数`, `六级分数`,
                     `政治面貌`, `意向城市`, `每周学时`)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `四级分数`  = COALESCE(VALUES(`四级分数`), `四级分数`),
                    `六级分数`  = COALESCE(VALUES(`六级分数`), `六级分数`),
                    `政治面貌`  = COALESCE(VALUES(`政治面貌`), `政治面貌`),
                    `意向城市`  = COALESCE(VALUES(`意向城市`), `意向城市`),
                    `每周学时`  = COALESCE(VALUES(`每周学时`), `每周学时`)
                """,
                (
                    tenant_id, student_id, cet4_score, cet6_score,
                    political_status, target_city, weekly_hours,
                ),
            )
            conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------
# 职业目标（career_intent，大一先选，大二/大三可调整）
# ----------------------------------------------------------------
def fetch_intent(tenant_id: int, student_id: int) -> str | None:
    """读取学生选择的职业目标；未选择或库不可用返回 None。"""
    try:
        conn = connect()
    except (pymysql.MySQLError, OSError):
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `意向` AS intent FROM `职业意向` "
                "WHERE `租户编号` = %s AND `学生编号` = %s LIMIT 1",
                (tenant_id, student_id),
            )
            row = cur.fetchone()
        return str(row["intent"]) if row and row.get("intent") else None
    except (pymysql.MySQLError, OSError):
        return None
    finally:
        conn.close()


def save_intent(tenant_id: int, student_id: int, intent: str) -> int:
    """写入/更新职业目标（同一学生一行，重复提交覆盖）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO `职业意向` (`租户编号`, `学生编号`, `意向`)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE `意向` = VALUES(`意向`)
                """,
                (tenant_id, student_id, intent),
            )
            conn.commit()
            # MySQL 对「值未变化」的 ON DUPLICATE KEY UPDATE 可能返回 0，
            # 但接口语义是“已保存”，故不把 rowcount 当成功与否。
            return 1
    finally:
        conn.close()


# ----------------------------------------------------------------
# 画像（career_plan，同一学生只有一条 is_active=1）
# ----------------------------------------------------------------
def fetch_active_plan(tenant_id: int, student_id: int) -> dict[str, Any] | None:
    """取该生当前生效的职业规划画像。无记录返回 None。"""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT `编号` AS id, `规划原文` AS raw_text, `目标类型` AS goal_type,
                   `规划内容` AS plan_json, `差距内容` AS gaps_json,
                   `待补问题` AS pending_questions, `提示词版本` AS prompt_version,
                   `模型名称` AS model_name, `创建时间` AS created_at
            FROM `职业规划`
            WHERE `学生编号` = %s AND `租户编号` = %s AND `是否生效` = 1
            ORDER BY `编号` DESC
            LIMIT 1
            """,
            (student_id, tenant_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        out = dict(row)
        out["plan"] = _json_load(out.pop("plan_json", None), {})
        out["gaps"] = _json_load(out.pop("gaps_json", None), [])
        out["pending_questions"] = _json_load(out.pop("pending_questions", None), [])
        out["created_at"] = _iso(out.get("created_at"))
        return out
    finally:
        conn.close()


def save_plan(
    tenant_id: int,
    student_id: int,
    *,
    raw_text: str,
    goal_type: str,
    plan: Mapping[str, Any],
    gaps: Sequence[str],
    pending_questions: Sequence[str],
    prompt_version: str = "career-v1",
    model_name: str | None = None,
) -> int:
    """落库一份画像：先把旧的 是否生效 置 0，再插新的（保留历史可追溯）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE `职业规划` SET `是否生效` = 0 "
                "WHERE `学生编号` = %s AND `租户编号` = %s",
                (student_id, tenant_id),
            )
            cur.execute(
                """
                INSERT INTO `职业规划`
                    (`租户编号`, `学生编号`, `规划原文`, `目标类型`, `规划内容`,
                     `差距内容`, `待补问题`, `提示词版本`, `模型名称`, `是否生效`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    tenant_id, student_id, raw_text, goal_type,
                    _json_dump(plan), _json_dump(list(gaps)),
                    _json_dump(list(pending_questions)), prompt_version, model_name,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
    finally:
        conn.close()


# ----------------------------------------------------------------
# 规培规则（plan_rule）
# ----------------------------------------------------------------
def fetch_active_rule(tenant_id: int, student_id: int) -> dict[str, Any] | None:
    """取该生当前生效的规培规则。"""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.`编号` AS id, r.`规划编号` AS plan_id, r.`主模板` AS main_template,
                   r.`次模板` AS sub_template, r.`主权重` AS main_weight,
                   r.`门槛状态` AS gates_json, r.`阶段计划` AS phases_json,
                   r.`监控指标` AS metrics_json, r.`节点日历` AS calendar_json,
                   r.`硬基线` AS hard_baseline, r.`可调项` AS adjustable,
                   r.`引擎版本` AS engine_version, r.`创建时间` AS created_at
            FROM `规划规则` r
            JOIN `职业规划` p ON p.`编号` = r.`规划编号`
            WHERE r.`学生编号` = %s AND r.`租户编号` = %s AND p.`是否生效` = 1
            ORDER BY r.`编号` DESC
            LIMIT 1
            """,
            (student_id, tenant_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        out = dict(row)
        # gates/phases/metrics/calendar 在表里是 *_json 列；hard_baseline/adjustable
        # 是 JSON 类型的同名列（没有 _json 后缀），必须按各自列名解析，不能一起 pop。
        for key in ("gates", "phases", "metrics", "calendar"):
            out[key] = _json_load(out.pop(f"{key}_json", None), [])
        for key in ("hard_baseline", "adjustable"):
            out[key] = _json_load(out.get(key), [])
        out["created_at"] = _iso(out.get("created_at"))
        return out
    finally:
        conn.close()


def save_rule(
    tenant_id: int,
    student_id: int,
    plan_id: int,
    *,
    main_template: str,
    sub_template: str | None,
    main_weight: float,
    gates: Sequence[Mapping[str, Any]],
    phases: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    calendar: Sequence[Mapping[str, Any]],
    hard_baseline: Sequence[str],
    adjustable: Sequence[str],
    engine_version: str = "career-v1",
) -> int:
    """落库规培规则（同一 plan 只保留最新一条，旧的删掉避免歧义）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM `规划规则` WHERE `规划编号` = %s AND `租户编号` = %s",
                (plan_id, tenant_id),
            )
            cur.execute(
                """
                INSERT INTO `规划规则`
                    (`租户编号`, `学生编号`, `规划编号`, `主模板`, `次模板`, `主权重`,
                     `门槛状态`, `阶段计划`, `监控指标`, `节点日历`,
                     `硬基线`, `可调项`, `引擎版本`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id, student_id, plan_id, main_template, sub_template, float(main_weight),
                    _json_dump(list(gates)), _json_dump(list(phases)),
                    _json_dump(list(metrics)), _json_dump(list(calendar)),
                    _json_dump(list(hard_baseline)), _json_dump(list(adjustable)),
                    engine_version,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
    finally:
        conn.close()


# ----------------------------------------------------------------
# 周快照（"连续两周落后"的唯一依据）
# ----------------------------------------------------------------
def fetch_week_history(
    tenant_id: int,
    student_id: int,
    limit: int = 4,
) -> list[list[dict[str, Any]]]:
    """取最近 N 周判定结果，**按由近到远**（history[0] = 上周）。

    engine.escalate_risks 就按这个顺序吃输入。
    """
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT `ISO年` AS iso_year, `ISO周` AS iso_week, `判定结果` AS judge_json
            FROM `周快照`
            WHERE `学生编号` = %s AND `租户编号` = %s
            ORDER BY `ISO年` DESC, `ISO周` DESC
            LIMIT %s
            """,
            (student_id, tenant_id, limit),
        )
        rows = cur.fetchall() or []
        history: list[list[dict[str, Any]]] = []
        for row in rows:
            judge = _json_load(row.get("judge_json"), {})
            items = judge.get("items") if isinstance(judge, Mapping) else None
            if isinstance(items, list):
                history.append(items)
        return history
    finally:
        conn.close()


def save_week_snapshot(
    tenant_id: int,
    student_id: int,
    plan_id: int,
    *,
    iso_year: int,
    iso_week: int,
    judge: Mapping[str, Any],
    escalation: Sequence[Mapping[str, Any]],
    notice_push: Sequence[Mapping[str, Any]],
    summary: str,
    advice: Sequence[Mapping[str, Any]],
    self_report: Mapping[str, Any] | None = None,
    system_metrics: Mapping[str, Any] | None = None,
    engine_version: str = "career-v1",
) -> int:
    """写入/更新本周快照（同一 (学生, 年, 周) 唯一）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO `周快照`
                    (`租户编号`, `学生编号`, `规划编号`, `ISO年`, `ISO周`,
                     `自报内容`, `系统指标`, `判定结果`, `升级预警`,
                     `通知推送`, `摘要`, `建议内容`, `引擎版本`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `判定结果`   = VALUES(`判定结果`),
                    `升级预警`   = VALUES(`升级预警`),
                    `通知推送`   = VALUES(`通知推送`),
                    `摘要`       = VALUES(`摘要`),
                    `建议内容`   = VALUES(`建议内容`),
                    `自报内容`   = VALUES(`自报内容`),
                    `系统指标`   = VALUES(`系统指标`)
                """,
                (
                    tenant_id, student_id, plan_id, int(iso_year), int(iso_week),
                    _json_dump(self_report or {}), _json_dump(system_metrics or {}),
                    _json_dump(dict(judge)), _json_dump(list(escalation)),
                    _json_dump(list(notice_push)), (summary or "")[:400],
                    _json_dump(list(advice)), engine_version,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
    finally:
        conn.close()


# ----------------------------------------------------------------
# 同侪基准（报考分析的「位次」依据，全部由真实成绩实算）
# ----------------------------------------------------------------
def fetch_peer_benchmark(
    tenant_id: int,
    student_id: int,
    min_courses: int = 5,
) -> dict[str, Any]:
    """算该生在同专业同届（同入学年份）中的均分位次。

    口径：
      - 样本 = 同学院同专业 + 同入学年份、且至少有 min_courses 门成绩的学生；
      - 只要求学生本人的成绩参与排名，同侪成绩只做分母，不泄露任何他人分数；
      - 样本不足 5 人 → pct 返回 None（不拿小样本冒充位次）。
    返回 {total, rank, pct, median, max, min, peer_with_score}
    """
    empty = {"total": 0, "rank": None, "pct": None, "median": None, "max": None, "min": None}
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT `专业` AS major, `年级` AS grade FROM `学生` WHERE `编号` = %s AND `租户编号` = %s",
            (student_id, tenant_id),
        )
        me = cur.fetchone()
        if not me or not me.get("major"):
            return empty

        cur.execute(
            """
            SELECT s.`编号` AS sid, ROUND(AVG(g.`分数`), 2) AS gpa, COUNT(*) AS n
            FROM `学生` s
            JOIN `成绩` g ON g.`学生编号` = s.`编号`
            WHERE s.`租户编号` = %s AND s.`专业` = %s AND s.`年级` = %s
            GROUP BY s.`编号`
            HAVING n >= %s
            ORDER BY gpa DESC
            """,
            (tenant_id, me["major"], me.get("grade"), int(min_courses)),
        )
        rows = cur.fetchall() or []
        if len(rows) < 5:
            return {**empty, "total": len(rows), "peer_with_score": len(rows)}

        scores = [float(r["gpa"]) for r in rows]
        rank = next((i + 1 for i, r in enumerate(rows) if int(r["sid"]) == int(student_id)), None)
        total = len(rows)
        mid = total // 2
        median = scores[mid] if total % 2 else round((scores[mid - 1] + scores[mid]) / 2, 2)
        return {
            "total": total,
            "rank": rank,
            "pct": _round(rank / total, 3) if rank else None,
            "median": median,
            "max": scores[0],
            "min": scores[-1],
            "peer_with_score": total,
            "major": me["major"],
            "grade": me.get("grade"),
        }
    finally:
        conn.close()


def _round(value: float, digits: int = 3) -> float:
    return round(float(value) + 1e-12, digits)


# ----------------------------------------------------------------
# 真实考试机会（招考公告，按考试类型取）
# ----------------------------------------------------------------
def fetch_exam_opportunities(
    tenant_id: int,
    exam_type: str,
    limit: int = 10,
) -> dict[str, Any]:
    """取该路径的真实招考公告 + 分项要求抽取覆盖率。

    stats 里的抽取率必须如实上报：重庆事业单位的岗位分项要求多写在附件岗位表，
    正文抓不到，前端要据此提示「以原文链接为准」，不能假装门槛都判过了。
    """
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT `编号` AS id, `标题` AS title, `招录单位` AS unit, `地区` AS region,
                   `招录人数` AS headcount, `报名截止` AS deadline, `考试日期` AS exam_date,
                   `原文链接` AS url, `状态` AS status, `发布日期` AS published,
                   `学历要求` AS edu_req, `专业要求` AS major_req, `政治面貌要求` AS pol_req,
                   `年龄要求` AS age_req
            FROM `招考公告`
            WHERE `租户编号` = %s AND `考试类型` = %s
            ORDER BY `报名截止` IS NULL, `报名截止` ASC, `发布日期` DESC
            """,
            (tenant_id, exam_type),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    def _filled(key: str) -> int:
        return sum(1 for r in rows if str(r.get(key) or "").strip())

    headcounts = [int(r["headcount"]) for r in rows if r.get("headcount") is not None]
    regions = sorted({str(r["region"]) for r in rows if r.get("region")})
    today = date.today()

    items: list[dict[str, Any]] = []
    for r in rows[:limit]:
        deadline = r.get("deadline")
        days_left = (deadline - today).days if isinstance(deadline, date) else None
        items.append(
            {
                "id": r.get("id"),
                "标题": r.get("title"),
                "招录单位": r.get("unit"),
                "地区": r.get("region"),
                "招录人数": r.get("headcount"),
                "报名截止": _iso(deadline),
                "考试日期": _iso(r.get("exam_date")),
                "原文链接": r.get("url"),
                "状态": r.get("status"),
                "距截止天数": days_left,
                # 只把真正抽到的要求带出去，空的留 None（前端显示「公告未单独说明」）
                "学历要求": (str(r.get("edu_req") or "").strip() or None),
                "专业要求": (str(r.get("major_req") or "").strip() or None),
                "政治面貌要求": (str(r.get("pol_req") or "").strip() or None),
                "年龄要求": (str(r.get("age_req") or "").strip() or None),
            }
        )

    total = len(rows)
    open_count = sum(
        1 for r in rows
        if isinstance(r.get("deadline"), date) and (r["deadline"] - today).days >= 0
    )
    published = [r["published"] for r in rows if isinstance(r.get("published"), date)]
    stats = {
        "total": total,
        "open_count": open_count,
        "with_education": _filled("edu_req"),
        "with_major": _filled("major_req"),
        "with_political": _filled("pol_req"),
        "with_age": _filled("age_req"),
        "latest_published": max(published).isoformat() if published else None,
        "regions": regions,
        "scope_note": (
            f"公告库当前只覆盖 {'、'.join(regions)}"
            + ("，其他省份的招考信息需另行查询官网。" if len(regions) == 1 else "。")
            if regions else "公告库暂无地区信息。"
        ),
    }
    return {
        "exam_type": exam_type,
        "total": total,
        "headcount": sum(headcounts) if headcounts else None,
        "items": items,
        "stats": stats,
    }


# ----------------------------------------------------------------
# 真实课程机会（国考职位——国家公务员局《招考简章》逐职位明细，仅考公）
# ----------------------------------------------------------------
# 政治面貌 / 学历 的匹配都用「关键词初筛 + 确定性 SQL 片段」，不猜、不补全：
#   - 政治面貌未采集 → 按保守口径只统计「不限/未标注」岗位（群众不能冒充党/团员）。
#   - 学历初筛只把「以硕士/研究生/博士为最低学历」的岗位排除在本科考生之外。
#   - 专业只按学生专业原文做子串匹配，「不限/未标注」单独统计，绝不拿相近专业凑数。
_GUOKAO_EDU_OK = (
    # 字面 % 在 pymysql「query % args」里须写成 %%，避免被当格式符
    "(`学历` IS NULL OR TRIM(`学历`) = '' OR `学历` LIKE '%%本科%%'"
    " OR `学历` LIKE '%%专科%%' OR `学历` LIKE '%%大专%%' OR `学历` LIKE '%%中专%%'"
    " OR `学历` LIKE '%%高中%%'"
    # 未提及任何更高学历的，也视为能接受本科（如“本科学历”这类纯要求）
    " OR (`学历` NOT LIKE '%%硕士%%' AND `学历` NOT LIKE '%%研究生%%' AND `学历` NOT LIKE '%%博士%%'))"
)
# 岗位「不限政治面貌」的可接受形态
_GUOKAO_POL_UNRESTRICTED = "(`政治面貌` IS NULL OR TRIM(`政治面貌`) = '' OR `政治面貌` IN ('不限','无','不要求'))"


def _guoka_pol_ok_sql(political: Any) -> str:
    """按学生政治面貌生成确定性的可报考 SQL 片段（纯文本→SQL，无 DB 副作用）。"""
    p = str(political or "").strip()
    if "党员" in p or "预备" in p:   # 中共党员 / 中共预备党员
        return (
            f"({_GUOKAO_POL_UNRESTRICTED}"
            # 不干抢「仅限共青团员」「民主党派」的岗位
            " OR NOT ((`政治面貌` LIKE '%%共青团员%%' AND `政治面貌` NOT LIKE '%%中共党员%%')"
            " OR (`政治面貌` LIKE '%%民主党派%%' AND `政治面貌` NOT LIKE '%%中共党员%%')))"
        )
    if "共青团员" in p:              # 共青团员
        return (
            f"({_GUOKAO_POL_UNRESTRICTED}"
            # 不抢「仅限中共党员」「民主党派」的岗位
            " OR NOT ((`政治面貌` LIKE '%%中共党员%%' AND `政治面貌` NOT LIKE '%%共青团员%%')"
            " OR `政治面貌` LIKE '%%民主党派%%'))"
        )
    # 群众 / 未采集 → 保守口径：只统计不限政治面貌的岗位
    return _GUOKAO_POL_UNRESTRICTED


def fetch_guokao_positions(
    tenant_id: int,
    facts: Mapping[str, Any],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """按学生学历/政治面貌/专业/城市对官方《招考简章》职位表做初筛聚合。

    返回确定性摘要：匹配职位数 / 计划招录人数 / 不限专业数 / 总职位数 / 样例，
    并明确标注「初筛、以官方职位详情为准」。数字全部来自 SQL COUNT/SUM，
    引擎只负责把结果组织成上下文，**不自己改这些数**（铁律 1）。
    """
    major = str(facts.get("major") or "").strip()
    degree = str(facts.get("degree") or "本科").strip()
    political = facts.get("political_status")
    city = str(facts.get("target_city") or "").strip()

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(`年度`) AS y FROM `国考职位` WHERE `租户编号` = %s",
            (tenant_id,),
        )
        row = cur.fetchone() or {}
        year = row.get("y")
        if not year:
            return {"available": False,
                    "reason": "国考职位表为空（尚未年度同步），无法给可报职位参考。"}
        year = int(year)

        pol = _guoka_pol_ok_sql(political)

        major_match = ""
        major_params: list[Any] = []
        if major:
            major_match = "(`专业` IS NULL OR TRIM(`专业`)='' OR `专业` LIKE '%%不限%%' OR `专业` LIKE %s)"
            major_params.append(f"%{major}%")
        else:
            # 学生未标注专业 → 只统计不设专业限制的岗位（保守，不冒充）
            major_match = "(`专业` IS NULL OR TRIM(`专业`)='' OR `专业` LIKE '%%不限%%')"

        city_param: Any = f"%{city}%" if city else None

        def _aggregate(where_sql: str, params: list[Any]) -> tuple[int, int | None]:
            cur.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(`招考人数`),0) AS p "
                f"FROM `国考职位` WHERE {where_sql}",
                params,
            )
            r = cur.fetchone() or {}
            return int(r["n"]), int(r["p"])

        # 组装匹配条件：每个子句前显式留空格，防止「= 2027AND」这种粘连被 MySQL 当函数名。
        where = (
            "`租户编号` = %s AND `年度` = %s "
            f"AND {_GUOKAO_EDU_OK} AND {pol} AND {major_match}"
        )
        matched_params: list[Any] = [tenant_id, year, *major_params]
        if city:
            where += " AND `工作地点` LIKE %s"
            matched_params.append(city_param)
        matched_n, matched_p = _aggregate(where, matched_params)

        # 「不设专业限制」子集：单独统计，供学生判断这条专业路径能报多少无门槛岗位
        unrestricted_where = (
            "`租户编号` = %s AND `年度` = %s "
            f"AND {_GUOKAO_EDU_OK} AND {pol} "
            "AND (`专业` IS NULL OR TRIM(`专业`)='' OR `专业` LIKE '%%不限%%')"
        )
        unrestricted_params: list[Any] = [tenant_id, year]
        if city:
            unrestricted_where += " AND `工作地点` LIKE %s"
            unrestricted_params.append(city_param)
        unrestricted_n, unrestricted_p = _aggregate(
            unrestricted_where, unrestricted_params)

        total_n, total_p = _aggregate(
            "`租户编号` = %s AND `年度` = %s", [tenant_id, year])

        cur.execute(
            "SELECT `公告链接` AS u FROM `国考职位` "
            "WHERE `租户编号` = %s AND `年度` = %s LIMIT 1",
            (tenant_id, year),
        )
        src = (cur.fetchone() or {}).get("u") or str(exam_positions_topic_url())

        cur.execute(
            "SELECT `编号` AS id, `部门名称` AS dept, `用人司局` AS bureau, "
            "`招考职位` AS position, `职位代码` AS code, `招考人数` AS headcount, "
            "`学历` AS edu, `政治面貌` AS pol, `工作地点` AS place, "
            "`专业` AS major, `简章分类` AS cat "
            "FROM `国考职位` WHERE " + where +
            " ORDER BY `招考人数` DESC, `编号` ASC LIMIT %s",
            [tenant_id, year, *major_params, *([city_param] if city else []), limit],
        )
        examples = []
        for ex in (cur.fetchall() or []):
            ec = str(ex.get("edu") or "").strip()
            ep = str(ex.get("pol") or "").strip()
            examples.append({
                "id": ex.get("id"),
                "dept": ex.get("dept"),
                "bureau": ex.get("bureau"),
                "position": ex.get("position"),
                "code": ex.get("code"),
                "headcount": ex.get("headcount"),
                "work_place": ex.get("place"),
                "education": ec or None,
                "political": ep or None,
                "major": str(ex.get("major") or "").strip() or None,
                "category": ex.get("cat"),
            })

        return {
            "available": True,
            "year": year,
            "degree": degree,
            "major": major or None,
            "political_status": political if political else None,
            "target_city": city or None,
            "matched_positions": matched_n,
            "matched_headcount": matched_p,
            "unrestricted_positions": unrestricted_n,
            "unrestricted_headcount": unrestricted_p,
            "total_positions": total_n,
            "total_headcount": total_p,
            "source_url": src,
            "source_label": "国家公务员局·中央机关及其直属机构考试录用公务员专题",
            "examples": examples,
        }
    except pymysql.MySQLError as exc:
        # 表不存在/连接失败：如实返回 not available，不吞掉也不编造
        return {"available": False, "reason": f"职位表查询失败：{str(exc)[:120]}"}
    finally:
        conn.close()


def exam_positions_topic_url() -> str:
    """官方国考专题 URL 兜底（无行取公告链接时用，取已登记年度里最新的）。"""
    from etl import exam_positions

    try:
        if exam_positions.OFFICIAL_TOPIC:
            latest = max(exam_positions.OFFICIAL_TOPIC)
            return str(exam_positions.OFFICIAL_TOPIC.get(latest) or "")
    except Exception:
        return ""
    return ""


# ----------------------------------------------------------------
# 通知（候选池；截止过滤一律交给引擎，这里绝不过滤）
# ----------------------------------------------------------------
def fetch_notices(tenant_id: int, limit: int = 60) -> list[dict[str, Any]]:
    """取候选通知。**不做日期过滤**——截止过滤必须走 engine.filter_notices。"""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT `编号` AS id, `标题` AS title, `发布单位` AS publisher,
                   `截止日期` AS deadline, `摘要` AS summary, `链接` AS url,
                   `分类` AS category
            FROM `学校通知`
            WHERE `租户编号` = %s
            ORDER BY `截止日期` IS NULL, `截止日期` ASC
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        rows = cur.fetchall() or []
        return [
            {
                "id": r.get("id"),
                "标题": r.get("title"),
                "发布单位": r.get("publisher"),
                "截止时间": _iso(r.get("deadline")),
                "摘要": r.get("summary"),
                "url": r.get("url"),
                "类别": r.get("category"),
            }
            for r in rows
        ]
    finally:
        conn.close()


def save_notice_match(
    tenant_id: int,
    student_id: int,
    matches: Sequence[Mapping[str, Any]],
) -> int:
    """落库通知匹配结果（只存 high/medium，low 不落库以免污染）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM `通知匹配` WHERE `学生编号` = %s AND `租户编号` = %s",
                (student_id, tenant_id),
            )
            n = 0
            for m in matches:
                rel = str(m.get("相关性") or "").lower()
                if rel not in {"high", "medium"}:
                    continue
                nid = m.get("id") or m.get("notice_id")
                if nid is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO `通知匹配` (`租户编号`, `通知编号`, `学生编号`, `相关度`, `理由`)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id, int(nid), student_id, rel,
                        str(m.get("推送理由") or "")[:120],
                    ),
                )
                n += 1
            conn.commit()
            return n
    finally:
        conn.close()

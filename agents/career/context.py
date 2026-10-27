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

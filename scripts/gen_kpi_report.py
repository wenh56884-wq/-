# scripts/gen_kpi_report.py
# 职责：生成 docs\KPI.md —— 计划书第七章考核指标中“现有数据可算”的部分
# 依赖：pymysql / duckdb / app.config / engine.warning / engine.metrics
# 说明：全部实测（真实库查询 + 真实预警引擎计算）；缺数据源的指标明确标 N/A，不编数

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pymysql

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from engine import metrics, warning  # noqa: E402

DEFAULT_TERM = "2025-2026-2"
DEFAULT_TENANT = 1
DEFAULT_LIMIT = 5000
HIDDEN_RISK = _ROOT / "data" / "hidden_risk.csv"


def _connect(settings) -> pymysql.connections.Connection:
    """MySQL 连接（字典游标）。"""
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def _detail(raw: Any) -> dict[str, Any]:
    """audit_log.detail 可能是 JSON 字符串或 dict；解析失败返回空 dict。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _load_hidden_risk(path: Path) -> dict[str, int]:
    """读取 seed_mock 产出的真实风险标签。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row["student_no"]): int(row["true_risk"])
            for row in csv.DictReader(handle)
            if row.get("student_no")
        }


def _warning_metrics(settings, tenant_id: int, term: str) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, Any]]:
    """跑一遍真实预警引擎，返回 (全预警/危机两套指标, 等级分布, 样本信息)。"""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `学号` AS student_no FROM `学生` "
                "WHERE `租户编号` = %s AND `学号` <> ''",
                (tenant_id,),
            )
            tenant_students = {str(row["student_no"]) for row in cur.fetchall()}
            cur.execute(
                "SELECT DISTINCT `班级` AS class_name FROM `学生` "
                "WHERE `租户编号` = %s AND `班级` <> '' ORDER BY `班级`",
                (tenant_id,),
            )
            classes = [str(row["class_name"]) for row in cur.fetchall()]
    finally:
        conn.close()

    y_pred: dict[str, str] = {}
    for class_name in classes:
        for row in warning.compute_class(tenant_id, class_name, term):
            y_pred[str(row["student_no"])] = str(row["level"])

    hidden = _load_hidden_risk(HIDDEN_RISK)
    y_true = {sno: risk for sno, risk in hidden.items() if sno in tenant_students}
    evaluated_true = {sno: risk for sno, risk in y_true.items() if sno in y_pred}
    bundle = {
        "all": metrics.classification_metrics(y_true, y_pred),
        "all_evaluated": metrics.classification_metrics(evaluated_true, y_pred),
        "crisis": metrics.classification_metrics(
            y_true, y_pred, positive_levels=("red", "orange")
        ),
        "crisis_evaluated": metrics.classification_metrics(
            evaluated_true, y_pred, positive_levels=("red", "orange")
        ),
    }
    info = {
        "classes": len(classes),
        "tenant_students": len(tenant_students),
        "hidden_risk_rows": len(hidden),
        "hidden_risk_in_tenant": len(y_true),
        "predicted_rows": len(y_pred),
        "missing_prediction": len(y_true) - len(evaluated_true),
    }
    return bundle, metrics.level_distribution(y_pred.values()), info


def _audit_rows(settings, action: str, limit: int) -> list[dict[str, Any]]:
    """取最近 N 条某类审计的 (target, detail)。"""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `对象`, `详情` FROM `审计日志` WHERE `动作` = %s "
                "ORDER BY `编号` DESC LIMIT %s",
                (action, int(limit)),
            )
            return [
                {"target": str(row.get("target") or ""),
                 "detail": _detail(row.get("detail"))}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def _latency_metrics(settings, limit: int) -> dict[str, Any]:
    """按审计行统计接口延迟；额外拆出推荐/对话/教师端。"""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `动作`, `详情` FROM `审计日志` "
                "WHERE `动作` LIKE 'GET /%%' OR `动作` LIKE 'POST /%%' OR `动作` LIKE 'PUT /%%' "
                "ORDER BY `编号` DESC LIMIT %s",
                (int(limit),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    groups: dict[str, list[float]] = {"all": [], "recommendations": [], "chat": [], "teacher": []}
    for row in rows:
        detail = _detail(row.get("detail"))
        duration = detail.get("duration_ms")
        if duration is None:
            continue
        value = float(duration)
        action = str(row.get("action") or "")
        groups["all"].append(value)
        if action == "GET /student/recommendations":
            groups["recommendations"].append(value)
        elif action == "POST /chat":
            groups["chat"].append(value)
        elif action.startswith(("GET /teacher", "PUT /teacher")):
            groups["teacher"].append(value)
    return {name: metrics.summarize_latency(values) for name, values in groups.items()}


def _recommend_metrics(settings) -> dict[str, Any]:
    """读 DuckDB recommend_log；被其它进程占用时重试 3 次，仍失败则标 unavailable。"""
    last_error = ""
    for attempt in range(3):
        try:
            with duckdb.connect(str(settings.duckdb_path_obj), read_only=True) as conn:
                rows = conn.execute(
                    'SELECT "学号", "最终得分", "协同得分", "命中项", "缺口项" '
                    'FROM "推荐日志"'
                ).fetchall()
            columns = ("student_no", "final_score", "cf_score", "hit_items", "gap_items")
            data = [dict(zip(columns, row)) for row in rows]
            out = metrics.summarize_recommend(data)
            out["available"] = True
            return out
        except Exception as exc:  # pragma: no cover - 依赖运行环境
            last_error = str(exc)[:200]
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    return {"available": False, "error": last_error}


def _usage_metrics(settings, tenant_id: int) -> dict[str, Any]:
    """从 audit_log 近似统计周活跃学生与教师覆盖（口径见文档）。"""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT `操作者编号`) AS n FROM `审计日志` "
                "WHERE `操作者类型` = 'student' AND `操作者编号` > 0 "
                "AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
            )
            active_students = int(cur.fetchone()["n"] or 0)
            cur.execute(
                "SELECT COUNT(DISTINCT a.`操作者编号`) AS n FROM `审计日志` a "
                "JOIN `教师` t ON t.`编号` = a.`操作者编号` "
                "WHERE a.`操作者类型` = 'teacher' AND t.`租户编号` = %s",
                (tenant_id,),
            )
            active_teachers = int(cur.fetchone()["n"] or 0)
            cur.execute("SELECT COUNT(*) AS n FROM `学生` WHERE `租户编号` = %s", (tenant_id,))
            total_students = int(cur.fetchone()["n"] or 0)
            cur.execute("SELECT COUNT(*) AS n FROM `教师` WHERE `租户编号` = %s", (tenant_id,))
            total_teachers = int(cur.fetchone()["n"] or 0)
    finally:
        conn.close()
    return {
        "active_students_7d": active_students,
        "total_students": total_students,
        "weekly_active_rate": round(active_students / total_students, 4) if total_students else None,
        "active_teachers": active_teachers,
        "total_teachers": total_teachers,
        "teacher_coverage": round(active_teachers / total_teachers, 4) if total_teachers else None,
    }


def _pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.2f}%"


def _num(value: Any, digits: int = 2, suffix: str = "") -> str:
    return "N/A" if value is None else f"{float(value):.{digits}f}{suffix}"


def _status(value: Any, target: float, op: str = ">=") -> str:
    if value is None:
        return "N/A"
    ok = value >= target if op == ">=" else value <= target
    return "PASS" if ok else "FAIL"


def render_report(
    *,
    term: str,
    tenant_id: int,
    warning_metrics: dict[str, dict[str, Any]],
    levels: dict[str, int],
    info: dict[str, Any],
    critic_all: dict[str, Any],
    critic_current: dict[str, Any],
    chat_current: dict[str, Any],
    latency: dict[str, Any],
    recommend: dict[str, Any],
    usage: dict[str, Any],
) -> str:
    """把指标渲染成 Markdown 报告。"""
    lines = [
        "# 启航系统 · 考核指标报告（KPI.md）",
        "",
        f"> 生成脚本：`python scripts\\gen_kpi_report.py --term {term} --tenant-id {tenant_id}`  ",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> 数据口径：租户 {tenant_id}，学期 `{term}`；全部为实测值，缺数据源的指标标 N/A。",
        "",
        "## 1. 预警准确性（对照 hidden_risk.csv）",
        "",
        "口径：`全预警` = 红/橙/黄均算阳性；`危机` = 只把红/橙算阳性（计划书所说“学业危机”）；"
        "`unknown`（数据不足）不算阳性；无成绩/未评估按未预警处理。"
        "KPI 采用“危机·可评估”口径，其余口径用于说明数据覆盖与宽严差异。",
        "",
        "| 口径 | 样本 | 命中覆盖 | TP | FP | TN | FN | 准确率 | 精确率 | 召回率 | F1 |",
        "| - | - | - | - | - | - | - | - | - | - | - |",
    ]
    warning_rows = (
        ("全预警 · 全量（缺失按未预警）", "all"),
        ("全预警 · 可评估（有预警输出）", "all_evaluated"),
        ("危机 · 全量（缺失按未预警）", "crisis"),
        ("危机 · 可评估（有预警输出）", "crisis_evaluated"),
    )
    for label, key in warning_rows:
        item = warning_metrics[key]
        lines.append(
            f"| {label} | {item['sample']} | {_pct(item['coverage'])} | "
            f"{item['tp']} | {item['fp']} | {item['tn']} | {item['fn']} | "
            f"{_pct(item['accuracy'])} | {_pct(item['precision'])} | "
            f"{_pct(item['recall'])} | {_num(item['f1'], 4)} |"
        )
    lines += [
        "",
        f"样本信息：租户学生 {info['tenant_students']} 人 / 班级 {info['classes']} 个；"
        f"hidden_risk {info['hidden_risk_rows']} 行，其中 {info['hidden_risk_in_tenant']} 行属于本租户；"
        f"预警引擎实际输出 {info['predicted_rows']} 人，缺成绩/未评估 {info['missing_prediction']} 人。",
        "",
        "预警等级分布（引擎输出）：" + "、".join(f"{k} {v}" for k, v in levels.items()) + "。",
        "",
        "## 2. Critic 与对话审计",
        "",
        "口径：全量 `audit_log` 含历史测试与注入幻觉演示；KPI 采用当前 `graph-v2` 且剔除 "
        "`draft_mode=injected` 的口径。一次通过率只看 `attempt=1`。",
        "",
        "| 口径 | 审核次数 | 通过率 | 一次通过率 | 数值不一致/模糊率 |",
        "| - | - | - | - | - |",
        f"| 全量 audit_log | {critic_all['total']} | {_pct(critic_all['pass_rate'])} | "
        f"{_pct(critic_all['first_pass_rate'])} | {_pct(critic_all['hallucination_rate'])} |",
        f"| 当前 graph-v2（剔除 injected） | {critic_current['total']} | "
        f"{_pct(critic_current['pass_rate'])} | {_pct(critic_current['first_pass_rate'])} | "
        f"{_pct(critic_current['hallucination_rate'])} |",
        "",
        f"当前 graph-v2 对话降级率：{_pct(chat_current['degraded_rate'])}；"
        f"平均尝试次数：{_num(chat_current['avg_attempts'])}。",
        "",
        "## 3. 接口延迟（audit_log.duration_ms）",
        "",
        "| 范围 | 样本 | 平均 | P50 | P95 | 最大 |",
        "| - | - | - | - | - | - |",
    ]
    labels = {"all": "全部 API", "recommendations": "推荐接口", "chat": "对话接口", "teacher": "教师端接口"}
    for key, label in labels.items():
        item = latency[key]
        lines.append(
            f"| {label} | {item['count']} | {_num(item['avg_ms'])} ms | "
            f"{_num(item['p50_ms'])} ms | {_num(item['p95_ms'])} ms | {_num(item['max_ms'])} ms |"
        )
    lines += [
        "",
        "## 4. 推荐日志（DuckDB recommend_log）",
        "",
    ]
    if recommend.get("available"):
        lines += [
            "| 指标 | 数值 |",
            "| - | - |",
            f"| 推荐日志条数 | {recommend['total']} |",
            f"| 覆盖学生数 | {recommend['students']} |",
            f"| 平均最终得分 | {_num(recommend['avg_final_score'], 4)} |",
            f"| 协同过滤覆盖率 | {_pct(recommend['cf_coverage'])} |",
            f"| 平均命中项数 | {_num(recommend['avg_hit_items'])} |",
            f"| 平均缺口项数 | {_num(recommend['avg_gap_items'])} |",
        ]
    else:
        lines.append(f"读取失败：`{recommend.get('error', 'unknown')}`（通常是 DuckDB 被其它进程占用）。")

    weekly_status = (
        "N/A（演示环境样本不足）"
        if usage["active_students_7d"] < 30
        else _status(usage["weekly_active_rate"], 0.60)
    )
    teacher_status = (
        "N/A（教师样本不足）"
        if usage["total_teachers"] < 3
        else _status(usage["teacher_coverage"], 0.80)
    )
    lines += [
        "",
        "## 5. 计划书第七章指标对照",
        "",
        "| 计划书指标 | 目标 | 当前值 | 状态 / 数据说明 |",
        "| - | - | - | - |",
        f"| 学业预警准确率 | ≥85% | {_pct(warning_metrics['crisis_evaluated']['accuracy'])} | "
        f"{_status(warning_metrics['crisis_evaluated']['accuracy'], 0.85)}"
        f"（危机口径·可评估 {warning_metrics['crisis_evaluated']['sample']} 人；"
        f"全预警口径 {_pct(warning_metrics['all_evaluated']['accuracy'])}，"
        f"危机口径覆盖 {_pct(warning_metrics['crisis']['coverage'])}） |",
        "| 平均预警提前量 | ≥4 周 | N/A | 缺预警历史快照，无法计算 |",
        "| 推荐岗位投递转化率 | ≥40% | N/A | 缺投递/申请日志表 |",
        "| 简历初筛通过率提升 | ≥20% | N/A | 缺就业系统回填数据 |",
        f"| 推荐理由一次审核通过率 | ≥98% | {_pct(critic_current['first_pass_rate'])} | "
        f"{_status(critic_current['first_pass_rate'], 0.98)}（graph-v2，剔除 injected） |",
        f"| 数值幻觉率 | ≤1% | {_pct(critic_current['hallucination_rate'])} | "
        f"{_status(critic_current['hallucination_rate'], 0.01, '<=')}（graph-v2 草稿级口径） |",
        f"| 学生周活跃率 | ≥60% | {_pct(usage['weekly_active_rate'])}"
        f"（{usage['active_students_7d']}/{usage['total_students']}） | "
        f"{weekly_status}（最近 7 天 API 活跃，近似） |",
        f"| 教师功能覆盖率 | ≥80% | {_pct(usage['teacher_coverage'])}"
        f"（{usage['active_teachers']}/{usage['total_teachers']}） | "
        f"{teacher_status}（有调用的教师/教师总数；缺教师-班级绑定） |",
        f"| 推荐接口 P95 | ≤3 秒 | {_num(latency['recommendations']['p95_ms'])} ms | "
        f"{_status(latency['recommendations']['p95_ms'], 3000, '<=')}（audit_log） |",
        "| 用户综合满意度 | ≥85 分 | N/A | 缺问卷/调研数据 |",
        "",
        "> 周活跃/教师覆盖是演示库的审计近似值，不是试点真实使用数据；正式口径需要登录与页面埋点。",
        "",
        "## 6. 指标缺口",
        "",
        "- 预警评估覆盖不足：本学期只有部分学生有成绩/考勤；缺数据的样本无法参与预警评估，"
        "需补数据或改用覆盖完整的学期重算。",
        "- 平均预警提前量：需要按周/月的 `warning_snapshot` 历史表；当前预警是即时计算。",
        "- 投递转化率、简历初筛通过率：需要 `job_apply_log` 或就业系统回填；当前只有 `job_view_log` 与 `recommend_log`。",
        "- 满意度：需要教师/学生问卷；当前无调研数据。",
        "- 周活跃/教师覆盖：当前用 `audit_log` 近似，正式口径需埋点表（登录、页面访问、功能使用）。",
        "- 教师-班级绑定：当前教师可见范围是租户级；覆盖率要按计划书口径计算，需先补 `teacher_class`。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """入口：采集指标、写 docs/KPI.md、打印摘要。"""
    parser = argparse.ArgumentParser(description="生成计划书考核指标报告")
    parser.add_argument("--term", default=DEFAULT_TERM)
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="审计日志取样条数（默认最近 5000 条）")
    parser.add_argument("--out", default=str(_ROOT / "docs" / "KPI.md"))
    args = parser.parse_args(argv)

    settings = get_settings()
    warning_metrics, levels, info = _warning_metrics(
        settings, args.tenant_id, args.term
    )

    chat_rows = _audit_rows(settings, "agent.chat", args.limit)
    critic_rows = _audit_rows(settings, "critic.verify", args.limit)
    current_traces = {
        row["target"]
        for row in chat_rows
        if row["detail"].get("graph_version") == "graph-v2"
        and row["detail"].get("draft_mode") != "injected"
    }
    critic_all = metrics.summarize_critic([row["detail"] for row in critic_rows])
    critic_current = metrics.summarize_critic(
        [row["detail"] for row in critic_rows if row["target"] in current_traces]
    )
    chat_current = metrics.summarize_chat(
        [row["detail"] for row in chat_rows if row["target"] in current_traces]
    )

    latency = _latency_metrics(settings, args.limit)
    recommend = _recommend_metrics(settings)
    usage = _usage_metrics(settings, args.tenant_id)

    report = render_report(
        term=args.term,
        tenant_id=args.tenant_id,
        warning_metrics=warning_metrics,
        levels=levels,
        info=info,
        critic_all=critic_all,
        critic_current=critic_current,
        chat_current=chat_current,
        latency=latency,
        recommend=recommend,
        usage=usage,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(f"已生成：{out}")
    print(
        f"预警准确率（危机·可评估）={_pct(warning_metrics['crisis_evaluated']['accuracy'])}，"
        f"Critic 一次通过率（graph-v2）={_pct(critic_current['first_pass_rate'])}，"
        f"推荐 P95={_num(latency['recommendations']['p95_ms'])} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

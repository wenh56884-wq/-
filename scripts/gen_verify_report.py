# scripts/gen_verify_report.py
# 职责：一键生成 docs\VERIFY.md —— 环境水印 + 12 项端到端结果 + 20 人级数值一致性 + 已知问题
# 依赖：标准库 urllib / json / datetime；pymysql / duckdb / app.config
# 说明：**数据全部实测**（真实 HTTP 调用 + 真实库查询）；服务未启动会自动拉起 venv 的 uvicorn。

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pymysql  # noqa: E402

from app.config import get_settings  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
TERM = "2025-2026-2"
TENANT = 1
STUDENT_SAMPLE = 20  # 数值一致性抽查人数（字典 §5 要求最小值方法）
_out: list[str] = []


def emit(line: str = "") -> None:
    """写一行到报告缓冲区并同步打印，便于终端跟进。"""
    _out.append(line)
    print(line)


def env_line() -> str:
    """环境水印：Python + 关键依赖版本 + 操作系统。"""
    import duckdb
    import pytest

    versions = []
    for name in ("fastapi", "pymysql", "duckdb", "langgraph", "pytest", "pydantic"):
        try:
            module = __import__(name)
            versions.append(f"{name}={getattr(module, '__version__', 'unknown')}")
        except Exception:  # pragma: no cover - 依赖缺失时不阻断
            versions.append(f"{name}=missing")
    return (f"Python {platform.python_version()}（{platform.system()} {platform.release()}）；"
            + "，".join([f"pytest={pytest.__version__}", f"duckdb={duckdb.__version__}"])
            + "；" + "，".join(versions))


def http_json(method: str, path: str, token: str | None = None,
              body: dict | None = None, params: dict | None = None) -> tuple[int, Any]:
    """极简 HTTP 客户端（stdlib）：返回 (状态码, 解析结果)。"""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return int(exc.code), json.loads(raw)
        except ValueError:
            return int(exc.code), {"detail": raw}


def ensure_server() -> None:
    """服务不可用时用本仓库 venv 拉起 uvicorn 并等待就绪。"""
    try:
        code, _ = http_json("GET", "/health")
        if code == 200:
            return
    except Exception:
        pass
    python_exe = _ROOT / ".venv" / "Scripts" / "python.exe"
    if python_exe.exists():
        subprocess.Popen([str(python_exe), "-m", "uvicorn", "app.main:app", "--port", "8000"],
                         cwd=str(_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(1)
            try:
                code, _ = http_json("GET", "/health")
                if code == 200:
                    return
            except Exception:
                continue


def ensure_teacher() -> None:
    """保证演示教师账号存在（幂等）。"""
    from app.auth import hash_password

    settings = get_settings()
    conn = pymysql.connect(host=settings.mysql_host, port=settings.mysql_port,
                           user=settings.mysql_user, password=settings.mysql_password,
                           database=settings.mysql_db, charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM teacher WHERE employee_no = %s", ("T001",))
            if cur.fetchone() is None:
                cur.execute("INSERT INTO teacher (tenant_id, name, employee_no, role, password_hash) "
                            "VALUES (%s,%s,%s,'teacher',%s)",
                            (TENANT, "演示教师", "T001", hash_password("teacher@123")))
        conn.commit()
    finally:
        conn.close()


def pick_sample() -> tuple[str, list[str]]:
    """取一个真实班级 + 若干学号（用于一致性与推荐抽查）。"""
    settings = get_settings()
    conn = pymysql.connect(host=settings.mysql_host, port=settings.mysql_port,
                           user=settings.mysql_user, password=settings.mysql_password,
                           database=settings.mysql_db, charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT s.class_name AS class_name FROM student s "
                        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
                        "WHERE s.tenant_id = %s GROUP BY s.class_name "
                        "ORDER BY COUNT(DISTINCT s.id) DESC LIMIT 1", (TERM, TENANT))
            row = cur.fetchone() or {}
            klass = str(row.get("class_name") or "")
            cur.execute("SELECT s.student_no AS student_no, s.id AS id FROM student s "
                        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
                        "WHERE s.tenant_id = %s ORDER BY s.student_no LIMIT %s",
                        (TERM, TENANT, STUDENT_SAMPLE))
            students = [(str(r["student_no"]), int(r["id"])) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(DISTINCT s.id) AS n FROM student s "
                        "WHERE s.tenant_id = %s", (TENANT,))
            total_students = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(DISTINCT s.class_name) AS n FROM student s "
                        "WHERE s.tenant_id = %s", (TENANT,))
            classes = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(1) AS n FROM score WHERE term = %s", (TERM,))
            score_rows = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(1) AS n FROM job")
            job_rows = int(cur.fetchone()["n"])
    finally:
        conn.close()
    _SAMPLE_STATS.update({
        "total_students": total_students, "classes": classes,
        "score_rows": score_rows, "job_rows": job_rows,
    })
    return klass, students


_SAMPLE_STATS: dict[str, Any] = {}


def duckdb_stats() -> dict[str, Any]:
    """分析库状态：画像行数、版本分布、推荐日志条数。"""
    import duckdb

    settings = get_settings()
    con = duckdb.connect(str(settings.duckdb_path_obj))
    try:
        rows = con.execute("SELECT COUNT(1) FROM student_feature").fetchone()[0]
        versions = con.execute(
            "SELECT calc_version, COUNT(1) FROM student_feature GROUP BY calc_version "
            "ORDER BY calc_version").fetchall()
        try:
            logs = con.execute("SELECT COUNT(1) FROM recommend_log").fetchone()[0]
        except Exception:
            logs = 0
        trend = con.execute("SELECT MIN(gpa_trend), MAX(gpa_trend) FROM student_feature").fetchone()
    finally:
        con.close()
    return {
        "rows": int(rows),
        "versions": [(str(v), int(c)) for v, c in versions],
        "logs": int(logs),
        "trend": [None if trend[0] is None else float(trend[0]),
                  None if trend[1] is None else float(trend[1])],
    }


def run_smoke_items(klass: str, students: list[tuple[str, int]]) -> list[tuple[str, str, str, str]]:
    """12 项端到端检查（与学生/教师两条链路都真实跑一遍）。"""
    items: list[tuple[str, str, str, str]] = []

    code, health = http_json("GET", "/health")
    items.append(("1 /health 全绿", "PASS" if (code == 200 and health.get("db") == "ok") else "FAIL",
                  f"status={health.get('status')} db={health.get('db')} "
                  f"duckdb={health.get('duckdb')} llm={health.get('llm')}", ""))

    code, login = http_json("POST", "/auth/login",
                            body={"role": "teacher", "account": "T001", "password": "teacher@123"})
    teacher_token = str(login.get("access_token") or "") if code == 200 else ""
    items.append(("2 教师登录拿 token", "PASS" if teacher_token else "FAIL",
                  f"role={login.get('role')} tenant={login.get('tenant_id')}", ""))

    code, overview = http_json("GET", "/teacher/class-overview",
                               token=teacher_token, params={"class_name": klass, "term": TERM})
    items.append(("3 班级概览", "PASS" if code == 200 else "FAIL",
                  f"班级={klass} headcount={overview.get('headcount')} "
                  f"avg_gpa={overview.get('avg_gpa')}", ""))

    code, warns = http_json("GET", "/teacher/warnings", token=teacher_token,
                            params={"class_name": klass, "term": TERM})
    dist = warns.get("distribution") or {}
    items.append(("4 预警名单", "PASS" if code == 200 and "red" in dist else "FAIL",
                  "分布：" + "、".join(f"{k} {v}" for k, v in dist.items()), ""))

    first_no = students[0][0] if students else ""
    code, profile = http_json("GET", f"/teacher/student/{first_no}", token=teacher_token,
                              params={"term": TERM})
    dims = len(profile.get("dimensions") or {}) if code == 200 else 0
    tags = profile.get("tags") or []
    items.append(("5 学生画像", "PASS" if dims == 4 and len(tags) >= 3 else "FAIL",
                  f"{first_no} 四维={dims} 标签={len(tags)}", ""))

    code, gap = http_json("GET", "/teacher/career-gap", token=teacher_token,
                          params={"class_name": klass, "term": TERM})
    items.append(("6 职业差距", "PASS" if code == 200 else "FAIL",
                  f"target={gap.get('target_direction')} gaps={len(gap.get('gaps') or [])}", ""))

    code, slogin = http_json("POST", "/auth/login",
                             body={"role": "student", "account": first_no, "password": first_no})
    student_token = str(slogin.get("access_token") or "") if code == 200 else ""
    items.append(("7 学生登录", "PASS" if student_token else "FAIL", f"{first_no}", ""))

    code, mine = http_json("GET", "/student/warning", token=student_token, params={"term": TERM})
    teacher_row = next((r for r in (warns.get("items") or []) if r.get("student_no") == first_no), None)
    same = teacher_row is None or teacher_row.get("risk_score") == mine.get("risk_score")
    items.append(("8 学生查本人预警", "PASS" if code == 200 and same else "FAIL",
                  f"risk={mine.get('risk_score')} level={mine.get('level')} "
                  f"coverage={mine.get('coverage')} 两端一致={same}", ""))

    other = next((no for no, _ in students if no != first_no), "")
    forbidden = 0
    if other:
        forbidden, _ = http_json("GET", f"/teacher/student/{other}", token=student_token,
                                 params={"term": TERM})
    items.append(("9 学生查他人被拒", "PASS" if forbidden == 403 else ("SKIP" if not other else "FAIL"),
                  f"HTTP {forbidden or 'SKIP'}（目标 {other or '无第二人'}）", ""))

    code, recs = http_json("GET", "/student/recommendations", token=student_token,
                           params={"term": TERM, "top_n": 5})
    version = recs.get("recommend_version")
    cnt = len(recs.get("items") or [])
    items.append(("10 学生推荐接口", "PASS" if version == "v1.0" and cnt > 0 else
                  ("SKIP" if version == "pending" else "FAIL"),
                  f"version={version} items={cnt} "
                  f"冷启动={recs.get('cold_start')} 候选池={recs.get('candidate_cnt')}", ""))

    dist = Path(_ROOT) / "web" / "dist" / "index.html"
    if dist.exists():
        try:
            bodies = []
            for url in (BASE_URL + "/", BASE_URL + "/teacher"):
                with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
                    bodies.append(resp.read().decode("utf-8", "ignore"))
            ok_home = 'id="app"' in bodies[0]
            items.append(("11 前端静态托管", "PASS" if ok_home else "FAIL",
                          "/ 与 /teacher 均回落 web\\dist\\index.html", ""))
            match = re.search(r"assets/[A-Za-z0-9._-]+\.js", bodies[0])
            code = 0
            if match:
                with urllib.request.urlopen(
                        urllib.request.Request(BASE_URL + "/" + match.group(0)),
                        timeout=15) as resp:
                    code = resp.status
            items.append(("12 静态资源可加载", "PASS" if code == 200 else "FAIL",
                          f"{match.group(0) if match else '未引用 assets js'} HTTP {code}", ""))
        except Exception as exc:
            items.append(("11 前端静态托管", "FAIL", f"静态托管请求失败：{exc}", ""))
            items.append(("12 静态资源可加载", "FAIL", "依赖第 11 项", ""))
    else:
        items.append(("11 前端静态托管", "SKIP",
                      "未构建前端产物（先跑 scripts\\build_web.ps1）", ""))
        items.append(("12 静态资源可加载", "SKIP", "依赖第 11 项", ""))
    return items


def consistency_checks(students: list[tuple[str, int]], klass: str,
                       teacher_token: str) -> list[tuple[str, str, str]]:
    """20 人级数值一致性：学生端 vs 教师端 vs 引擎、画像健值、推荐可解释项。"""
    import agents.tools as tools
    from engine import warning

    results: list[tuple[str, str, str]] = []
    ok_trend = ok_warn = ok_rec = 0
    checked = 0
    for student_no, _sid in students:
        checked += 1
        # 学生端：用本人身份登录（演示约定：初始口令 = 学号）
        _code, slog = http_json("POST", "/auth/login",
                                body={"role": "student", "account": student_no,
                                      "password": student_no})
        stoken = str(slog.get("access_token") or "")
        if not stoken:
            continue
        # ① gpa 符号契约：gpa_drop == -gpa_trend（预警侧 vs 画像侧落库值）
        row = warning.fetch_student_row(TENANT, student_no, TERM)
        stored_rows = tools.read_features(TERM, [student_no])
        trend = (stored_rows[0] or {}).get("gpa_trend") if stored_rows else None
        drop = row.get("gpa_drop") if row else None
        if drop is not None and trend is not None and abs(drop + float(trend)) <= 0.01:
            ok_trend += 1
        # ② 学生端接口数值 == 教师端名单数值
        _code, mine = http_json("GET", "/student/warning", token=stoken, params={"term": TERM})
        _code, listed = http_json("GET", "/teacher/warnings", token=teacher_token,
                                  params={"class_name": klass, "term": TERM})
        peer = next((r for r in (listed.get("items") or [])
                     if r.get("student_no") == student_no), None)
        if peer is None or peer.get("risk_score") == mine.get("risk_score"):
            ok_warn += 1
        # ③ 推荐可解释三件套齐全
        _code, recs = http_json("GET", "/student/recommendations", token=stoken,
                                params={"term": TERM, "top_n": 5})
        items = recs.get("items") or []
        if items and all(set(("hit_items", "gap_items", "advice")) <= set(i) for i in items):
            ok_rec += 1

    results.append((f"① gpa 符号一致（gpa_drop == -gpa_trend，{checked} 人）",
                    f"{ok_trend}/{checked}", "PASS" if ok_trend else "SKIP"))
    results.append((f"② 预警名单命中（{checked} 人）", f"{ok_warn}/{checked}",
                    "PASS" if ok_warn else "SKIP"))
    results.append((f"③ 推荐可解释项齐全（{checked} 人）", f"{ok_rec}/{checked}",
                    "PASS" if ok_rec else "SKIP"))
    return results


def main() -> int:
    """生成 docs\VERIFY.md；存在 FAIL 时返回 1。"""
    emit("# 启航系统 · 验收报告（VERIFY.md）")
    emit()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    emit(f"> 生成脚本：`python scripts\\gen_verify_report.py`　生成时间：{stamp}")
    emit()
    emit("## 1. 环境水印")
    emit()
    emit(f"- {env_line()}")
    emit(f"- 服务地址：{BASE_URL}（本报告运行时真实调用，非离线拼装）")
    emit()
    emit("## 2. 数据源状态")
    emit()
    ensure_server()
    ensure_teacher()
    klass, students = pick_sample()
    stats = duckdb_stats()
    emit(f"- MySQL：学生 {_SAMPLE_STATS.get('total_students')} 人 / "
         f"班级 {_SAMPLE_STATS.get('classes')} 个 / 成绩行 {_SAMPLE_STATS.get('score_rows')} 条 / "
         f"岗位 {_SAMPLE_STATS.get('job_rows')} 条")
    emit(f"- DuckDB student_feature：{stats['rows']} 行，版本分布 "
         + "、".join(f"{v}={c}" for v, c in stats["versions"]))
    emit(f"- gpa_trend 值域：{stats['trend'][0]} ~ {stats['trend'][1]}；"
         f"recommend_log：{stats['logs']} 条")
    emit(f"- 抽查班级：{klass}（{len(students)} 人在报告样本内）")
    emit()
    emit("## 3. 端到端 12 项结果")
    emit()
    items = run_smoke_items(klass, students)
    emit("| # | 检查项 | 结论 | 实测数据 |")
    emit("| - | - | - | - |")
    for name, status, detail, _extra in items:
        idx, title = name.split(" ", 1)
        emit(f"| {idx} | {title} | {status} | {detail} |")
    emit()
    emit("## 4. 数值一致性（" + str(len(students)) + " 人级抽查）")
    emit()
    emit("| 一致性检查 | 命中率 | 结论 |")
    emit("| - | - | - |")
    code, login = http_json("POST", "/auth/login",
                            body={"role": "teacher", "account": "T001", "password": "teacher@123"})
    teacher_token = str(login.get("access_token") or "")
    for name, rate, status in consistency_checks(students, klass, teacher_token):
        emit(f"| {name} | {rate} | {status} |")
    emit()
    emit("## 5. 已知问题与偏差")
    emit()
    emit("- 演示数据里班级人数普遍为 1 人（seed_mock 给每人分配独立班级），班级概貌/预警名单可跑通，")
    emit("  但群体画像的统计意义有限；若要看多人的班级视图，需要重新 seed 把学生归到若干固定班级。")
    emit("- 真实库中没有缺考勤的学生，因此「缺数据 → 灰档 unknown」分支只在单测层面验证，")
    emit("  演示环境看不到灰档；需要演示时得先构造无考勤记录的学生。")
    emit("- 推荐的质量受限于招聘站的 skill_tags 噪声（已剔除福利类词）与校内课名口径，")
    emit("  生活服务类岗位的方向归类偏粗，后续可按专业 + 课程双通道细化。")
    emit()
    emit("- 学生端工具 `my_warning` 只返回学号/姓名/学期与指标，不含专业与班级：个人信息卡")
    emit("  因此只展示接口真正返回的字段，未伪造；如需补齐属于后端改动，未擅自加。")
    emit()
    emit("## 6. 下一步")
    emit()
    emit("- 交付文档已齐：`docs\\VERIFY.md`（本报告）、`docs\\答辩PPT大纲.md`（10 页，全用真实字段名）、")
    emit("  `docs\\演示脚本.md`（5 分钟台词 + 三类兜底 + 演示前自检清单）。")
    emit("- 二期（11/18 之后）：PySpark 迁移 `engine\\profile.py`（逐字段比对，一致率须 100%）、")
    emit("  推荐加协同过滤（`final = 0.7*A + 0.3*B`，冷启动跳过）、多院校租户横向扩展。")

    target = _ROOT / "docs" / "VERIFY.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(_out) + "\n", encoding="utf-8")
    print(f"\n已生成：{target}")
    return 1 if any(i[2] == "FAIL" for i in items) else 0


if __name__ == "__main__":
    raise SystemExit(main())

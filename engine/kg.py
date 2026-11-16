# engine/kg.py
# 职责：知识图谱「专业—课程—岗位—技能」——NetworkX 构建与查询。
# 数据来源（全部真实库表，不编造）：
#   专业/课程  ← `学生`.`专业` + `课程`（课程挂专业）
#   岗位      ← `岗位`（2931 条历史库 + 方向由方向词典判定）
#   技能      ← 方向名 ∪ 岗位技能标签高频词 ∪ 课程培养技能（映射表见 COURSE_SKILL_MAP）
# 边：
#   专业-开设->课程 / 课程-培养->技能 / 岗位-要求->技能 / 专业-对口->岗位（经方向中转判定）
# 铁律：抽不到就不连边（缺失不冒充）；explain_path 只讲图中真实存在的链。

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import networkx as nx

KG_VERSION = "kg-v1"
KG_EXPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "kg" / "knowledge_graph.json"

# 高频技能标签门槛：岗位标签出现 ≥ 此次数才建技能节点（控图规模，保真实）
_MIN_TAG_FREQ = 8


def _norm(text: str) -> str:
    """NFKC + 去空白 + 小写（技能等价判定共用）。"""
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", t).lower()

# 课程名关键词 → 培养技能（确定性映射；未命中不连边，绝不编一条假技能）
COURSE_SKILL_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 人工智能 / 数据科学核心课：先覆盖工科演示专业，技能词只取图谱里真实存在的标签
    ("人工智能", ("人工智能", "算法")),
    ("模式识别", ("算法", "机器学习")),
    ("计算机视觉", ("算法", "机器学习")),
    ("智能系统", ("算法", "人工智能")),
    ("机器学习", ("机器学习", "算法")),
    ("深度学习", ("机器学习", "算法")),
    ("自然语言处理", ("算法", "机器学习")),
    ("算法", ("算法", "编程基础")),
    ("数据挖掘", ("数据挖掘", "数据分析")),
    ("数据可视化", ("数据可视化", "Excel")),
    ("java", ("Java", "编程基础")),
    ("web应用", ("HTML", "JavaScript", "前端")),
    ("软件测试", ("软件测试",)),
    ("会计", ("会计核算", "财务报表")),
    ("审计", ("审计",)),
    ("税", ("税务处理",)),
    ("财务", ("财务管理",)),
    ("成本", ("成本管理",)),
    ("资产评估", ("资产评估",)),
    ("统计", ("统计分析", "Excel")),
    ("数据库", ("SQL", "数据库设计")),
    ("数据结构", ("编程基础",)),
    ("python", ("Python",)),
    ("大数据", ("Hive", "数据仓库")),
    ("数据分析", ("数据分析", "Excel")),
    ("计量", ("计量分析",)),
    ("经济", ("经济分析",)),
    ("金融", ("金融分析",)),
    ("投资", ("投资分析",)),
    ("保险", ("保险实务",)),
    ("国际经济与贸易", ("外贸实务",)),
    ("贸易", ("外贸实务",)),
    ("营销", ("市场营销",)),
    ("电子商务", ("电商运营",)),
    ("物流", ("物流管理",)),
    ("供应链", ("供应链管理",)),
    ("管理", ("管理学",)),
    ("人力资源", ("人力资源",)),
    ("新媒体", ("新媒体运营",)),
    ("网络与新媒体", ("新媒体运营",)),
    ("会展", ("会展策划",)),
    ("物业", ("物业运营",)),
    ("工程管理", ("项目管理",)),
    ("土地资源", ("不动产管理",)),
    ("健康服务", ("健康服务管理",)),
    ("播音", ("内容表达",)),
    ("数字媒体", ("数字内容制作",)),
    ("法律", ("法律合规",)),
    ("法学", ("法律合规",)),
    ("经济法", ("法律合规",)),
    ("商法", ("法律合规",)),
    ("谈判", ("商务谈判",)),
    ("礼仪", ("商务礼仪",)),
    ("英语", ("英语",)),
)


def skills_for_course(name: str) -> tuple[str, ...]:
    """课程名 → 培养技能（纯函数，按映射表逐条匹配，去重保序）。

    只返回映射表里明确写出的技能；未命中返回空元组，由建图环节跳过这条边。
    """
    normalized = str(name or "").strip().lower()
    if not normalized:
        return ()
    found: list[str] = []
    for key, skills in COURSE_SKILL_MAP:
        if key in normalized:
            for skill in skills:
                if skill not in found:
                    found.append(skill)
    return tuple(found)


def _query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """与 engine.recommend 相同的取数模式：失败返回空（缺失不冒充）。"""
    try:
        from app.config import get_settings
        import pymysql
        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db,
                               charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                               connect_timeout=5)
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def _direction_of(text: str) -> str | None:
    """复用 recommend 的方向判定，保持口径一致。"""
    try:
        from engine.recommend import direction_of
        d = direction_of(text)
        return d or None
    except Exception:
        return None


# ----------------------------------------------------------------
# 构图
# ----------------------------------------------------------------
def build_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.graph["version"] = KG_VERSION

    # 1) 专业 —开设-> 课程
    courses = _query("SELECT `课程名称` AS name, `专业` AS major FROM `课程`")
    majors: set[str] = set()
    for c in courses:
        major = str(c.get("major") or "").strip()
        name = str(c.get("name") or "").strip()
        if not major or not name:
            continue
        majors.add(major)
        g.add_node(f"major:{major}", kind="major", label=major)
        g.add_node(f"course:{name}", kind="course", label=name)
        g.add_edge(f"major:{major}", f"course:{name}", kind="开设")

    # 2) 课程 —培养-> 技能（映射表；未命中不连）
    for c in courses:
        for sk in skills_for_course(str(c.get("name") or "")):
            g.add_node(f"skill:{sk}", kind="skill", label=sk)
            g.add_edge(f"course:{c['name']}", f"skill:{sk}", kind="培养")

    # 3) 岗位：方向判定 + 技能标签
    jobs = _query(
        "SELECT `编号` AS id, `岗位名称` AS title, `企业` AS company, `城市` AS city,"
        " `学历` AS education, `技能标签` AS skill_tags, `最低薪资` AS salary_min,"
        " `最高薪资` AS salary_max FROM `岗位`")
    tag_freq: Counter[str] = Counter()
    parsed: list[dict[str, Any]] = []
    for j in jobs:
        try:
            from engine.recommend import clean_skill_tags
            tags = clean_skill_tags(j.get("skill_tags"))
        except Exception:
            tags = []
        parsed.append({**j, "tags": tags})
        tag_freq.update(tags)

    frequent = {t for t, n in tag_freq.items() if n >= _MIN_TAG_FREQ}

    for j in parsed:
        jid = f"job:{j['id']}"
        direction = _direction_of(" ".join([str(j.get("title") or "")] + j.get("tags", [])))
        g.add_node(jid, kind="job", label=str(j.get("title") or f"岗位{j['id']}"),
                   company=j.get("company"), city=j.get("city"), direction=direction,
                   education=j.get("education"), salary_min=j.get("salary_min"),
                   salary_max=j.get("salary_max"), tags=j.get("tags", []))
        # 岗位 —要求-> 技能（方向名 + 高频标签）
        if direction:
            g.add_node(f"skill:{direction}", kind="skill", label=direction)
            g.add_edge(jid, f"skill:{direction}", kind="要求")
        for t in j["tags"]:
            if t in frequent:
                g.add_node(f"skill:{t}", kind="skill", label=t)
                g.add_edge(jid, f"skill:{t}", kind="要求")

    # 4) 专业 —对口-> 岗位（方向中转：专业属方向 D，岗位方向为 D）
    dir_majors = _direction_majors()
    for mn in [n for n in g.nodes if g.nodes[n]["kind"] == "major"]:
        major_label = g.nodes[mn]["label"]
        dirs = {d for d, ms in dir_majors.items() if major_label in ms}
        if not dirs:
            continue
        for jn in [n for n in g.nodes if g.nodes[n]["kind"] == "job"]:
            if g.nodes[jn].get("direction") in dirs:
                g.add_edge(mn, jn, kind="对口")
    return g


def _direction_majors() -> dict[str, tuple[str, ...]]:
    try:
        from engine.recommend import DIR_MAJORS
        return dict(DIR_MAJORS)
    except Exception:
        return {}


# ----------------------------------------------------------------
# 查询（三个规定动作 + 统计 + explain_path）
# ----------------------------------------------------------------
def graph_stats(g: nx.DiGraph) -> dict[str, Any]:
    by_kind = Counter(g.nodes[n]["kind"] for n in g.nodes)
    by_edge = Counter(d.get("kind") for _, _, d in g.edges(data=True))
    return {"version": KG_VERSION, "nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "nodes_by_kind": dict(by_kind), "edges_by_kind": dict(by_edge)}


def query_jobs_by_skill(g: nx.DiGraph, skill: str, limit: int = 20) -> dict[str, Any]:
    """技能 → 要求该技能的岗位（图中真实边，无则空）。"""
    sn = f"skill:{skill}"
    if sn not in g.nodes:
        return {"skill": skill, "total": 0, "items": []}
    jobs = []
    for _, jn, d in g.out_edges(sn, data=True):
        pass
    for jn in g.predecessors(sn):
        if g.nodes[jn]["kind"] != "job":
            continue
        n = g.nodes[jn]
        jobs.append({"id": int(jn.split(":", 1)[1]), "title": n["label"], "company": n.get("company"),
                     "city": n.get("city"), "direction": n.get("direction"),
                     "salary_min": n.get("salary_min"), "salary_max": n.get("salary_max")})
    jobs.sort(key=lambda x: (-(x.get("salary_max") or 0), x["id"]))
    return {"skill": skill, "total": len(jobs), "items": jobs[:max(1, limit)]}


def query_skills_by_major(g: nx.DiGraph, major: str) -> dict[str, Any]:
    """专业 →（开的课程）→（培养的）技能。链路里每一步都是真实边。"""
    mn = f"major:{major}"
    if mn not in g.nodes:
        return {"major": major, "total": 0, "courses": [], "skills": []}
    courses: list[str] = []
    skills: dict[str, list[str]] = {}
    for _, cn, d in g.out_edges(mn, data=True):
        if d.get("kind") != "开设":
            continue
        cname = g.nodes[cn]["label"]
        courses.append(cname)
        for _, skn, d2 in g.out_edges(cn, data=True):
            if d2.get("kind") == "培养":
                skills.setdefault(g.nodes[skn]["label"], []).append(cname)
    skill_items = [{"skill": k, "via_courses": v[:3]} for k, v in
                   sorted(skills.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return {"major": major, "total": len(skill_items), "course_cnt": len(courses),
            "courses": courses, "skills": skill_items}


def _skill_match(a: str, b: str) -> bool:
    """技能等价判定：全等或互为子串（财务管理 ↔ 财务；Hive ↔ hive）。"""
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def explain_path(g: nx.DiGraph, major: str, job_id: int) -> dict[str, Any]:
    """你学过X课程→掌握Y技能→匹配岗位Z。同时给缺口：岗位要求但课程链未覆盖的技能。"""
    jn = f"job:{int(job_id)}"
    if jn not in g.nodes:
        return {"found": False, "reason": "岗位不在图谱中"}
    job = g.nodes[jn]
    sm = query_skills_by_major(g, major)
    owned = {s["skill"] for s in sm.get("skills", [])}
    required = [g.nodes[n]["label"] for n in g.successors(jn)
                if g.nodes[n]["kind"] == "skill"]
    covered = [s for s in required if any(_skill_match(s, o) for o in owned)]
    missing = [s for s in required if not any(_skill_match(s, o) for o in owned)]
    # 链条：专业→课程→技能→岗位（技能取「岗位要求 ∩ 课程培养」）
    chain: list[dict[str, Any]] = []
    for s in covered:
        hit = next((x for x in sm["skills"] if _skill_match(x["skill"], s)), None)
        chain.append({"skill": s, "owned_as": hit["skill"] if hit else s,
                      "courses": (hit or {}).get("via_courses", []), "job": job["label"]})
    return {"found": True, "version": KG_VERSION,
            "major": major, "job_id": int(job_id), "job": job["label"],
            "direction": job.get("direction"),
            "required": required, "covered": covered, "missing": missing,
            "chain": chain[:6],
            "summary": (f"岗位要求 {len(required)} 项技能，课程链覆盖 {len(covered)} 项"
                        + (f"，缺 {len(missing)} 项：{'、'.join(missing[:4])}" if missing else "，无缺口"))}


# ----------------------------------------------------------------
# 导出（落盘 JSON，供答辩/离线分析/前端兜底）
# ----------------------------------------------------------------
def export_json(g: nx.DiGraph, path: Path | None = None) -> Path:
    path = path or KG_EXPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = [{"id": n, **{k: v for k, v in g.nodes[n].items() if k != "tags"}} for n in g.nodes]
    edges = [{"source": u, "target": v, "kind": d.get("kind")} for u, v, d in g.edges(data=True)]
    payload = {"stats": graph_stats(g), "nodes": nodes, "edges": edges}
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    return path

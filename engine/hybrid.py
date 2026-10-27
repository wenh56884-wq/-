# engine/hybrid.py
# 职责：混合推荐 = 0.7×召回A(内容) + 0.3×召回B(协同过滤)，B 缺失退化为 A 归一化。
# 召回B（协同过滤，确定性）：
#   邻居 = 同专业 + 成绩段 ±5 分的其他学生；
#   信号 = 邻居在候选岗位上的行为（favorite=3, view=1）；
#   相似度 = 余弦(我的行为向量, 邻居行为向量)；
#   cf_score(j) = Σ sim×w / Σ sim（加权预测），无邻居/无行为 → None（冷启动跳过）。
# 理由三段式：①知识匹配（A 口径）②同伴证据（B）③行动建议（差距+KG 课程链）。
# 铁律：不引入随机数；A 打分复用 engine.recommend.score_job（口径不漂移）。

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from engine import kg as kg_engine
from engine import recommend

HYBRID_ENGINE_VERSION = "hybrid-v1"
GPA_BAND = 5.0          # 成绩段 ±5 分
MAX_NEIGHBORS = 200     # 邻居上限（按行为量取最活跃，控制计算量）
CF_TOP_K = 20           # user-based CF 的最近邻数
_W_ACTION = {"favorite": 3.0, "view": 1.0}


def _weights() -> tuple[float, float]:
    """混合权重：默认 0.7 内容 / 0.3 协同（计划书口径），可用环境变量微调。

    为什么可配：评测显示协同在当前 mock 行为数据上区分度更强（见 scripts/eval_hybrid.py
    的权重敏感性表），真实偏好数据上 0.7/0.3 更稳；默认值仍按计划书执行。
    """
    import os
    try:
        wc = float(str(os.getenv("HYBRID_W_CONTENT", "0.7")).strip())
        wf = float(str(os.getenv("HYBRID_W_CF", "0.3")).strip())
    except ValueError:
        return 0.7, 0.3
    if wc < 0 or wf < 0 or wc + wf <= 0:
        return 0.7, 0.3
    total = wc + wf
    return round(wc / total, 4), round(wf / total, 4)


_KG_CACHE: dict[str, Any] = {"graph": None}


def _kg_graph():
    """进程级缓存：图谱构图要全表扫描，不能每个学生都重建。"""
    if _KG_CACHE["graph"] is None:
        try:
            _KG_CACHE["graph"] = kg_engine.build_graph()
        except Exception:
            return None
    return _KG_CACHE["graph"]


def _behavior_vectors(tenant_id: int, term: str, neighbor_ids: Sequence[int],
                      job_ids: Sequence[int]) -> dict[int, dict[int, float]]:
    """邻居 → 候选岗位 → 行为权重（一次 SQL 聚合，不在 Python 里拼万行）。"""
    if not neighbor_ids or not job_ids:
        return {}
    id_list = ",".join(str(int(i)) for i in neighbor_ids[: MAX_NEIGHBORS * 3])
    job_list = ",".join(str(int(j)) for j in job_ids)
    rows = recommend._query(
        "SELECT `学生编号` AS sid, `岗位编号` AS jid,"
        " SUM(CASE WHEN `动作`='favorite' THEN 3 ELSE 1 END) AS w"
        " FROM `岗位浏览日志`"
        f" WHERE `学生编号` IN ({id_list}) AND `岗位编号` IN ({job_list})"
        " GROUP BY `学生编号`, `岗位编号`",
        (),
    )
    vec: dict[int, dict[int, float]] = {}
    for r in rows:
        vec.setdefault(int(r["sid"]), {})[int(r["jid"])] = float(r["w"] or 0.0)
    return vec


def _my_vector(tenant_id: int, student_id: int, job_ids: Sequence[int]) -> dict[int, float]:
    rows = recommend._query(
        "SELECT `岗位编号` AS jid, SUM(CASE WHEN `动作`='favorite' THEN 3 ELSE 1 END) AS w"
        " FROM `岗位浏览日志` WHERE `学生编号`=%s AND `岗位编号` IN ("
        + ",".join(str(int(j)) for j in job_ids) + ") GROUP BY `岗位编号`",
        (int(student_id),),
    )
    return {int(r["jid"]): float(r["w"] or 0.0) for r in rows}


def _neighbor_ids(tenant_id: int, term: str, major: str, gpa: float | None,
                  student_id: int) -> list[int]:
    """同专业 + 成绩段 ±5 分的其他学生（按行为量取最活跃 MAX_NEIGHBORS 个）。"""
    if gpa is None or not major:
        return []
    rows = recommend._query(
        "SELECT s.`编号` AS sid, AVG(sc.`分数`) AS gpa,"
        " (SELECT COUNT(*) FROM `岗位浏览日志` b WHERE b.`学生编号` = s.`编号`) AS acts"
        " FROM `学生` s JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s"
        " WHERE s.`租户编号` = %s AND s.`专业` = %s AND s.`编号` <> %s"
        " GROUP BY s.`编号`"
        " HAVING AVG(sc.`分数`) BETWEEN %s AND %s"
        " ORDER BY acts DESC, s.`编号`"
        " LIMIT %s",
        (term, tenant_id, major, int(student_id),
         float(gpa) - GPA_BAND, float(gpa) + GPA_BAND, MAX_NEIGHBORS),
    )
    return [int(r["sid"]) for r in rows]


def _cosine(a: Mapping[int, float], b: Mapping[int, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def cf_scores(my_vec: Mapping[int, float], neigh_vecs: Mapping[int, Mapping[int, float]],
              job_ids: Sequence[int], top_k: int = 20) -> dict[int, float]:
    """协同过滤预测值 b(j) ∈ (0,1]：

        b(j) = Σ_{v∈TopK} sim_v · min(1, ln(1+w_v(j)) / ln(1+5))  /  Σ_{v∈TopK} sim_v

    语义 = 「与你最相似的 K 位同学里，有多大比例（按相似度加权）关注过这个岗位」。
    TopK 是必须的：同专业同成绩段的邻居可能上百个，全部加权会把相似度稀释成噪声，
    标准 user-based CF 只取最近邻。
    """
    sims = [(sid, _cosine(my_vec, vec)) for sid, vec in neigh_vecs.items()]
    sims = sorted([(sid, s) for sid, s in sims if s > 0], key=lambda kv: (-kv[1], kv[0]))[:top_k]
    if not sims:
        return {}
    sim_sum = sum(s for _, s in sims)
    num: dict[int, float] = {}
    for sid, sim in sims:
        vec = neigh_vecs[sid]
        for jid in job_ids:
            w = vec.get(int(jid))
            if w and w > 0:
                strength = min(1.0, math.log1p(w) / math.log1p(5.0))
                num[int(jid)] = num.get(int(jid), 0.0) + sim * strength
    if sim_sum <= 0 or not num:
        return {}
    return {j: round(v / sim_sum, 6) for j, v in num.items()}


def fuse_scores(scored: list[dict[str, Any]], cf: Mapping[int, float],
                peer_cnt: Mapping[int, int], a_max: float,
                w_content: float = 0.7, w_cf: float = 0.3) -> list[dict[str, Any]]:
    """纯函数：把 A 分与 B 分融合成 final_score 并确定性排序（原地改 + 返回）。

        final = w_c · (A / A_max) + w_f · B，B 缺失按 0 计（不用均值兜底）。

    为什么缺失计 0 而不是 a_norm：A 并行内并列满分（a_norm=1）的岗位会白白压过
    有真实同伴证据的岗位，出现「有 B 反而降权」的倒挂。
    排序键：final 降序 → 薪资上限降序 → job_id 升序（无随机，同输入同结果）。
    """
    peak = a_max if a_max > 0 else 1.0
    for s in scored:
        s["content_score"] = s["final_score"]        # A 原分（日志留存）
        a_norm = float(s["final_score"]) / peak
        b = cf.get(int(s["job_id"]))
        if b is None:
            s["cf_score"] = None
            s["peer_count"] = None
            s["final_score"] = round(w_content * a_norm, 4)
        else:
            s["cf_score"] = round(float(b), 4)
            s["peer_count"] = int(peer_cnt.get(int(s["job_id"]), 0))
            s["final_score"] = round(w_content * a_norm + w_cf * float(b), 4)
    scored.sort(key=lambda x: (-x["final_score"], -(x["salary_max"] or 0.0), x["job_id"]))
    return scored


def hybrid_recommend(tenant_id: int, student_no: str, term: str,
                     top_n: int = recommend.DEFAULT_TOP_N,
                     *, write_log: bool = True,
                     student_id: int | None = None) -> dict[str, Any]:
    """端到端混合推荐：复用 A 的取数与打分，叠加 CF 与 KG 解释。"""
    student = recommend.load_student(tenant_id, student_no, term)
    if not student.get("major") and student.get("gpa") is None:
        return {"student_no": student_no, "term": term,
                "engine_version": HYBRID_ENGINE_VERSION,
                "cold_start": True, "candidate_cnt": 0, "items": [],
                "note": "该生在本学期无成绩记录，无法推荐"}

    jobs = recommend.load_jobs(student["directions"])
    scored = [recommend.score_job(student, j) for j in jobs]
    scored.sort(key=lambda x: (-x["final_score"], -(x["salary_max"] or 0.0), x["job_id"]))
    a_max = max((s["final_score"] for s in scored), default=0.0)

    # ---- 召回B：协同过滤 ----
    sid = student_id
    if sid is None:
        rows = recommend._query("SELECT `编号` FROM `学生` WHERE `租户编号`=%s AND `学号`=%s",
                                (tenant_id, student_no))
        sid = int(rows[0]["编号"]) if rows else None
    cand_ids = [s["job_id"] for s in scored]
    my_vec: dict[int, float] = {}
    neigh_vecs: dict[int, dict[int, float]] = {}
    if sid:
        my_vec = _my_vector(tenant_id, sid, cand_ids)
        nids = _neighbor_ids(tenant_id, term, str(student.get("major") or ""),
                             student.get("gpa"), sid)
        if nids:
            neigh_vecs = _behavior_vectors(tenant_id, term, nids, cand_ids)
    cf = cf_scores(my_vec, neigh_vecs, cand_ids)
    # 同伴证据：每个候选岗位被多少位邻居行为覆盖（理由第②段用，真实计数）
    peer_cnt: dict[int, int] = {}
    for vec in neigh_vecs.values():
        for jid in vec:
            if vec[jid]:
                peer_cnt[jid] = peer_cnt.get(jid, 0) + 1

    # ---- 混合排序 ----
    w_content, w_cf = _weights()
    fuse_scores(scored, cf, peer_cnt, a_max, w_content, w_cf)
    items = scored[: max(1, int(top_n))]

    # ---- KG 解释链（缺库不致命）----
    _kg = _kg_graph()
    for it in items:
        it["kg_explain"] = None
        if _kg is None:
            continue
        # 只在专业与岗位方向对口（≥0.6）时给课程链：否则「覆盖 0 项」是噪声不是解释
        try:
            matched, _ = recommend.major_match_of(student.get("major"), it.get("direction") or "")
            if matched < 0.6:
                continue
            exp = kg_engine.explain_path(_kg, str(student.get("major") or ""), it["job_id"])
            if exp.get("found"):
                it["kg_explain"] = {"summary": exp["summary"],
                                    "chain": exp["chain"][:3],
                                    "missing": exp["missing"][:5]}
        except Exception:
            continue

    result = {
        "student_no": str(student_no), "term": str(term),
        "engine_version": HYBRID_ENGINE_VERSION,
        "cold_start": bool(items and items[0].get("cold_start")),
        "candidate_cnt": len(scored),
        "cf_active": bool(cf),
        "neighbor_cnt": len(neigh_vecs),
        "weights": {"content": w_content, "cf": w_cf},
        "items": items,
    }
    if write_log:
        result["logged"] = _write_hybrid_log(result)
    return result


def _write_hybrid_log(result: Mapping[str, Any]) -> int:
    """写 recommend_log：content_score=A 归一化前分数，cf_score=召回B，final_score=混合分。"""
    written = 0
    try:
        import time

        from engine.store import DuckDBStore
        store = DuckDBStore()
    except Exception:
        return 0
    base_id = int(time.time() * 1000) * 1000
    for idx, item in enumerate(result.get("items") or []):
        try:
            written += int(store.write_recommend_log({
                "id": base_id + idx,
                "student_no": str(result.get("student_no") or ""),
                "job_id": int(item.get("job_id") or 0),
                "content_score": float(item.get("content_score") or 0.0),
                "cf_score": item.get("cf_score"),
                "final_score": float(item.get("final_score") or 0.0),
                "hit_items": list(item.get("hit_items") or []),
                "gap_items": list(item.get("gap_items") or []),
                "advice": str(item.get("advice") or ""),
                "engine_version": HYBRID_ENGINE_VERSION,
            }) or 0)
        except Exception:
            continue
    return written

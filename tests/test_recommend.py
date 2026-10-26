# tests/test_recommend.py
# 职责：校验规则版岗位推荐（四维打分 / 冷启动 / 确定性 / 缺口归因）
# 依赖：pytest / engine.recommend（纯函数，全程离线）
# 说明：只测打分逻辑，不连 MySQL / DuckDB；DB 分支用 monkeypatch 注入

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from engine import recommend as rec  # noqa: E402
from engine.recommend import (  # noqa: E402
    RECOMMEND_ENGINE_VERSION,
    gpa_gate_of,
    interest_fit_of,
    major_match_of,
    min_gpa_of,
    recommend,
    score_job,
    skill_cover_of,
)

JOB_BACKEND = {
    "id": 101, "title": "Java 后端开发工程师", "company": "示例科技", "city": "杭州",
    "salary_min": 12000, "salary_max": 20000, "education": "本科", "exp_min": 1,
    "skill_tags": ["Java", "MySQL", "数据结构"], "direction": "后端",
}
JOB_ACCOUNTING = {
    "id": 202, "title": "会计", "company": "示例财务", "city": "上海",
    "salary_min": 6000, "salary_max": 9000, "education": "大专", "exp_min": 0,
    "skill_tags": ["会计", "税法"], "direction": "财务",
}
JOB_NO_SKILLS = {
    "id": 303, "title": "管培生", "company": "示例集团", "city": "北京",
    "salary_min": 8000, "salary_max": 12000, "education": "本科", "exp_min": 0,
    "skill_tags": [], "direction": "产品",
}

STUDENT_CS = {
    "student_no": "S001", "term": "2025-2026-2", "major": "软件工程", "gpa": 88.0,
    "skills": ["Java程序设计", "MySQL数据库应用", "数据结构"],
    "directions": ["后端", "算法"],
}


# ----------------------------------------------------------------
# 1) 完全匹配 → 0.9 以上
# ----------------------------------------------------------------
def test_full_match_scores_above_0_9():
    """对口专业 + 过门槛 + 技能全覆盖 + 兴趣命中 → final_score >= 0.9。"""
    scored = score_job(STUDENT_CS, JOB_BACKEND)
    assert scored["dims"]["major_match"] == 1.0
    assert scored["dims"]["gpa_gate"] == 1.0
    assert scored["dims"]["skill_cover"] == 1.0
    assert scored["dims"]["interest_fit"] == 1.0
    assert scored["final_score"] >= 0.9, scored
    assert any("专业完全匹配" in h for h in scored["hit_items"])
    assert scored["gap_items"] == []


# ----------------------------------------------------------------
# 2) 专业不符 → 分数显著低
# ----------------------------------------------------------------
def test_major_mismatch_scores_much_lower():
    """会计专业碰后端岗：专业项 0 分，总分应显著低于对口岗位。"""
    accountant = {**STUDENT_CS, "student_no": "S002", "major": "会计学", "directions": ["财务"]}
    good = score_job(STUDENT_CS, JOB_BACKEND)
    bad = score_job(accountant, JOB_BACKEND)
    assert bad["dims"]["major_match"] == 0.0
    assert bad["final_score"] < good["final_score"] - 0.3
    # 换成对口财务岗，分数应回来
    fit = score_job(accountant, JOB_ACCOUNTING)
    assert fit["final_score"] > bad["final_score"]
    assert fit["dims"]["major_match"] == 1.0


# ----------------------------------------------------------------
# 3) 技能缺口被写进 gap_items
# ----------------------------------------------------------------
def test_skill_gap_is_reported():
    """缺少 MySQL/数据结构 → gap_items 指明缺什么，并给出对应课程建议。"""
    thin_student = {**STUDENT_CS, "skills": ["Java程序设计"]}
    scored = score_job(thin_student, JOB_BACKEND)
    assert scored["dims"]["skill_cover"] == pytest.approx(1 / 3, abs=1e-4)
    joined = " ".join(scored["gap_items"])
    assert "MySQL" in joined and "数据结构" in joined
    assert "岗位要求" in joined


def test_skill_cover_matching_is_substring_based():
    """'java' 应命中 'Java开发经验'（包含匹配，大小写不敏感）。"""
    cover, hits, gaps = skill_cover_of(["Java程序设计"], ["Java开发经验", "Redis"])
    assert cover == pytest.approx(0.5, abs=1e-4)
    assert hits == ["Java开发经验"] and gaps == ["Redis"]


# ----------------------------------------------------------------
# 4) 冷启动：无技能无兴趣 → 只算两项
# ----------------------------------------------------------------
def test_cold_start_only_uses_major_and_gpa():
    """没有任何技能/兴趣数据时：cold_start=True，分数按 major+gpa 两项重归权重。"""
    cold_student = {**STUDENT_CS, "skills": [], "directions": []}
    scored = score_job(cold_student, JOB_NO_SKILLS)
    assert scored["cold_start"] is True
    # 0.35*1.0 + 0.25*1.0，权重和 0.60 → 1.0
    assert scored["final_score"] == pytest.approx(1.0, abs=1e-4)
    assert scored["dims"]["skill_cover"] == 0.0 and scored["dims"]["interest_fit"] == 0.0

    result = recommend(cold_student, [JOB_NO_SKILLS])
    assert result["cold_start"] is True
    assert result["engine_version"] == RECOMMEND_ENGINE_VERSION


def test_stride_sample_edge_cases():
    """候选池抽样边界：配额 0 返回空（相关岗位已占满配额的场景，曾经除零崩溃）。"""
    jobs = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert rec._stride_sample(jobs, 0) == []
    assert rec._stride_sample([], 5) == []
    assert rec._stride_sample(jobs, 3) == jobs
    assert rec._stride_sample(jobs, 2) == [{"id": 1}, {"id": 3}]  # 步长 2 稳定抽样


def test_missing_gpa_reports_gap_not_zero():
    """成绩缺失 → gpa_gate 记 0 且写缺口话术，不得按满额算。"""
    score, hit, gap, _delta = gpa_gate_of(None, 66.0)
    assert score == 0.0 and hit == "" and "缺失" in gap


# ----------------------------------------------------------------
# 5) 同输入结果一致（无随机数）
# ----------------------------------------------------------------
def test_write_recommend_log_keeps_structured_items(monkeypatch):
    """落库前不得先 json.dumps：store 会统一序列化，先 dumps 会变成双重转义字符串。"""
    captured: dict = {}

    class FakeStore:
        def write_recommend_log(self, log):
            captured.update(log)
            return 1

    monkeypatch.setattr("engine.store.DuckDBStore", FakeStore)
    written = rec.write_recommend_log(
        {
            "student_no": "S001",
            "items": [
                {
                    "job_id": 101,
                    "final_score": 0.92,
                    "hit_items": ["专业完全匹配"],
                    "gap_items": [],
                    "advice": "建议选修课程",
                }
            ],
        }
    )
    assert written == 1
    assert captured["hit_items"] == ["专业完全匹配"]
    assert captured["gap_items"] == []
    assert captured["job_id"] == 101


def test_deterministic_and_sorted_by_score_then_id():
    """同输入两次排序结果完全一致；同分时按 job_id 升序（确定性二次键）。"""
    jobs = [JOB_ACCOUNTING, JOB_BACKEND, JOB_NO_SKILLS]
    first = recommend(STUDENT_CS, jobs, top_n=10)
    second = recommend(STUDENT_CS, jobs, top_n=10)
    assert first == second
    scores = [x["final_score"] for x in first["items"]]
    assert scores == sorted(scores, reverse=True)
    assert first["items"][0]["job_id"] == 101  # 后端岗分数最高

    few = recommend(STUDENT_CS, jobs, top_n=2)
    assert len(few["items"]) == 2
    assert few["candidate_cnt"] == 3


# ----------------------------------------------------------------
# 6) 门槛与专业/兴趣基础映射
# ----------------------------------------------------------------
def test_min_gpa_formula_is_documented():
    """min_gpa = 60 + 学历溢价 + 经验溢价（上限 90）。"""
    assert min_gpa_of({"education": "学历不限", "exp_min": 0}) == 60.0
    assert min_gpa_of({"education": "本科", "exp_min": 0}) == 66.0
    assert min_gpa_of({"education": "本科", "exp_min": 2}) == 69.0
    # 经验溢价封顶 6 年（+9 分）：博士 12 + 9 = 21 → 81，仍不超过 GPA_MAX_GATE
    assert min_gpa_of({"education": "博士", "exp_min": 20}) == 81.0
    assert min_gpa_of({"education": "博士", "exp_min": 20}) <= rec.GPA_MAX_GATE


def test_graded_matches_and_related_dirs():
    """专业：对口 1.0 / 相近 0.6 / 不符 0；兴趣：命中 1.0 / 相关 0.5 / 无关 0。"""
    assert major_match_of("软件工程", "后端") == (1.0, "专业完全匹配")
    score, _reason = major_match_of("电子信息工程", "后端")
    assert score == 0.6
    assert major_match_of("会计学", "后端")[0] == 0.0

    assert interest_fit_of(["后端"], "后端")[0] == 1.0
    assert interest_fit_of(["算法"], "后端")[0] == 0.5
    assert interest_fit_of(["金融"], "后端")[0] == 0.0
    assert interest_fit_of([], "后端")[0] == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

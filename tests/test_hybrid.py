# tests/test_hybrid.py
# 混合推荐单测：纯函数部分（余弦、CF 预测、融合排序、权重），不依赖 MySQL。

from __future__ import annotations

import math

import pytest

from engine.hybrid import _cosine, _weights, cf_scores, fuse_scores

pytestmark = pytest.mark.hybrid


def test_cosine_identical_vectors_is_one():
    v = {1: 3.0, 2: 1.0}
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero():
    assert _cosine({1: 3.0}, {2: 3.0}) == 0.0


def test_cosine_only_counts_common_jobs_for_dot():
    # 点积只在共同岗位上有贡献；额外维度只影响模长（标准余弦语义）
    a = {1: 1.0, 2: 1.0}
    b = {1: 1.0, 2: 1.0, 99: 100.0}
    assert 0 < _cosine(a, b) < 0.05
    # 邻居多看 100 个无关岗位不会把相似度归零（仍有正信号）
    assert _cosine(a, b) > 0


def test_cf_scores_empty_without_neighbors():
    assert cf_scores({1: 1.0}, {}, [1, 2]) == {}


def test_cf_scores_empty_when_no_similarity():
    assert cf_scores({1: 1.0}, {9: {2: 3.0}}, [1, 2]) == {}


def test_cf_scores_bounded_0_1():
    my = {1: 1.0}
    neigh = {2: {1: 1.0}, 3: {1: 5.0, 2: 2.0}}
    out = cf_scores(my, neigh, [1, 2])
    assert all(0 < v <= 1.0 for v in out.values())


def test_cf_scores_top_k_limits_neighbors():
    # 邻居同质时，取前 5 个与取全部 50 个结果相同（top-K 不是简单扩大分母）
    my = {1: 1.0}
    neigh = {i: {1: 1.0} for i in range(50)}
    out5 = cf_scores(my, neigh, [1], top_k=5)
    out50 = cf_scores(my, neigh, [1], top_k=50)
    strength = math.log1p(1) / math.log1p(5)   # w=1（只看过一次）的饱和强度
    assert out5[1] == pytest.approx(strength, abs=1e-6)
    assert out5[1] == pytest.approx(out50[1], abs=1e-6)


def test_cf_scores_log_saturation():
    my = {1: 1.0}
    low = cf_scores(my, {2: {1: 1.0}}, [1])[1]
    high = cf_scores(my, {2: {1: 100.0}}, [1])[1]
    assert high >= low and high <= 1.0


def _rows():
    return [
        {"job_id": 1, "final_score": 0.5, "salary_max": 10000.0},
        {"job_id": 2, "final_score": 0.5, "salary_max": 9000.0},
        {"job_id": 3, "final_score": 0.35, "salary_max": 8000.0},
    ]


def test_fuse_missing_cf_counts_zero():
    out = fuse_scores(_rows(), {3: 1.0}, {3: 171}, a_max=0.5)
    by_id = {r["job_id"]: r for r in out}
    assert by_id[1]["cf_score"] is None and by_id[1]["final_score"] == 0.7
    assert by_id[3]["cf_score"] == 1.0 and by_id[3]["final_score"] == 0.79


def test_fuse_strong_peer_evidence_outranks_plain_content():
    out = fuse_scores(_rows(), {3: 1.0}, {3: 171}, a_max=0.5)
    assert out[0]["job_id"] == 3  # 同伴证据把 A 较低但同学都在看的岗位顶上来


def test_fuse_keeps_content_score_for_log():
    out = fuse_scores(_rows(), {}, {}, a_max=0.5)
    assert [r["content_score"] for r in out] == [0.5, 0.5, 0.35]


def test_fuse_is_deterministic_and_tiebreaks_by_salary_then_id():
    a = fuse_scores(_rows(), {}, {}, a_max=0.5)
    b = fuse_scores(_rows(), {}, {}, a_max=0.5)
    assert [r["job_id"] for r in a] == [r["job_id"] for r in b] == [1, 2, 3]


def test_fuse_handles_zero_amax():
    out = fuse_scores([{"job_id": 1, "final_score": 0.0, "salary_max": None}],
                      {}, {}, a_max=0.0)
    assert math.isclose(out[0]["final_score"], 0.0)


def test_weights_default_and_env(monkeypatch):
    monkeypatch.delenv("HYBRID_W_CONTENT", raising=False)
    monkeypatch.delenv("HYBRID_W_CF", raising=False)
    assert _weights() == (0.7, 0.3)
    monkeypatch.setenv("HYBRID_W_CONTENT", "0.5")
    monkeypatch.setenv("HYBRID_W_CF", "0.5")
    assert _weights() == (0.5, 0.5)
    monkeypatch.setenv("HYBRID_W_CONTENT", "garbage")
    assert _weights() == (0.7, 0.3)


def test_weights_normalize():
    import os
    os.environ["HYBRID_W_CONTENT"] = "1"
    os.environ["HYBRID_W_CF"] = "3"
    try:
        wc, wf = _weights()
        assert wc == pytest.approx(0.25) and wf == pytest.approx(0.75)
    finally:
        os.environ.pop("HYBRID_W_CONTENT", None)
        os.environ.pop("HYBRID_W_CF", None)

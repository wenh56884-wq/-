# tests/test_interview_router_contract.py
# 职责：面试路由的两条数据契约——MySQL JSON 列解析、答题/收卷证据集同口径
# 说明：只测纯函数，不连 MySQL、不调 LLM

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.routers.interview import _evidence, _json_list  # noqa: E402


def test_json_list_parses_mysql_json_string():
    """pymysql 把 JSON 列返回成 str；必须解析成列表，不能逐字符拆。"""
    assert _json_list('["数据结构", "数据库"]') == ["数据结构", "数据库"]


def test_json_list_empty_and_bad_values_do_not_fabricate():
    assert _json_list("[]") == []
    assert _json_list(None) == []
    assert _json_list("not-json") == []


def test_json_list_passes_python_list_through():
    assert _json_list(["Java", "Redis"]) == ["Java", "Redis"]


def test_evidence_answer_and_finish_share_same_shape():
    """答题与收卷都用这一个函数；顺序固定：原文/自评 → 岗位技能 → 经历描述。"""
    resume = {"简历原文": "简历原文", "self": "自评",
              "experiences": [{"desc": "做过秒杀"}, {"desc": ""}]}
    assert _evidence(resume, {"skill_tags": ["Java", "Redis"]}) == [
        "简历原文", "Java", "Redis", "做过秒杀"]


def test_evidence_falls_back_to_self_or_db_self_eval():
    assert _evidence({"self": "自评", "experiences": []}, None) == ["自评"]
    # _load_resume() 返回的是中文列名，问卷自填简历没有原文时用「自我评价」
    assert _evidence({"自我评价": "库里的自评", "experiences": []}, None) == ["库里的自评"]

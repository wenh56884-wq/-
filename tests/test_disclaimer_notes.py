# tests/test_disclaimer_notes.py
# 职责：守住两条产品免责声明——教师预警复核、简历/面试建议仅供参考。
# 说明：只断言固定文案与输出挂载，不触碰任何业务数值。

from agents.graph import WARNING_REVIEW_NOTE, accept_node, fallback_node


def test_warning_list_accept_includes_review_note():
    state = {
        "draft": "AI2301 预警名单：46 人。",
        "tool_name": "warning_list",
        "verdict": {"passed": True},
    }
    answer = accept_node(state)["answer"]
    assert WARNING_REVIEW_NOTE in answer


def test_warning_list_fallback_includes_review_note():
    state = {
        "tool_name": "warning_list",
        "tool_result": {"items": [{"student_no": "AI20230001"}]},
    }
    result = fallback_node(state)
    assert result["degraded"] is True
    assert WARNING_REVIEW_NOTE in result["answer"]

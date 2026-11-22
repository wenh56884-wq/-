# tests/test_student_agent.py
# 职责：锁死学生端 Agent 的意图路由与参数抠取契约。
# 依赖：pytest / agents.student_agent；不访问数据库与网络。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import student_agent  # noqa: E402


def test_personal_routes() -> None:
    assert student_agent.personal_tool("我这学期成绩怎么样") == "my_grades"
    assert student_agent.personal_tool("国考职位表里有哪些岗位") == "exam_positions"
    # 职位明细问法（考公词 + 职位词复合）：不能被报考分析聚合口径吃掉
    assert student_agent.personal_tool("今年考公能考哪些职位") == "exam_positions"
    # 推荐问法（岗位词但无考公词）：仍走默认岗位推荐，不被职位表截胡
    assert student_agent.personal_tool("有哪些岗位适合我") is None
    assert student_agent.personal_tool("面试会问什么") == "question_bank_lookup"
    assert student_agent.personal_tool("实习管理办法有哪些") is None


def test_compound_civil_position_question_is_exam_positions() -> None:
    # 概览问法：概览 + 职位 → exam_positions 且**不得**抠出垃圾关键词（否则 LIKE 空结果）
    assert student_agent.personal_tool("今年考公能考哪些职位") == "exam_positions"
    args = student_agent.tool_args("exam_positions", "今年考公能考哪些职位")
    assert "keyword" not in args
    assert args.get("year") is None   # 「今年」语义由工具按库内最新年度兜底


def test_edu_threshold_followup_routes_to_exam_positions() -> None:
    """用户实测翻车句：「里面有哪些是本科就可以考的吗」——不含职位/岗位字面，
    但问的是职位表按学历过滤；学历过滤要从追问里抠出来，且不产生垃圾关键词。"""
    q = "里面有哪些是本科就可以考的吗"
    assert student_agent.personal_tool(q) == "exam_positions"
    args = student_agent.tool_args("exam_positions", q)
    assert args.get("education") == "本科"
    assert "keyword" not in args


def test_position_requirement_question_routes_to_exam_positions() -> None:
    """用户实测翻车句：「我知道我具体岗位和要求」——岗位 + 要求 → 职位表明细，
    清洗后不得把「知道我」这类残词当关键词。"""
    q = "我知道我具体岗位和要求"
    assert student_agent.personal_tool(q) == "exam_positions"
    args = student_agent.tool_args("exam_positions", q)
    assert "keyword" not in args


def test_edu_threshold_rule_does_not_steal_non_civil_exams() -> None:
    """学历 + 考 的组合不能抢走非国考范畴的考试问法。"""
    assert student_agent.personal_tool("本科可以直接考研吗") != "exam_positions"
    assert student_agent.personal_tool("本科能考教师资格证吗") != "exam_positions"
    assert student_agent.personal_tool("四级可以考吗") != "exam_positions"


def test_exam_position_args_include_year_and_clean_keyword() -> None:
    # 显式年度入参
    args = student_agent.tool_args("exam_positions", "2027年国考职位")
    assert args["year"] == 2027
    assert "keyword" not in args
    # 具体检索词（不复述职位表）
    args = student_agent.tool_args("exam_positions", "我想看税务局相关的岗位")
    assert args["keyword"] == "税务局"
    # 复合过滤：地点 + 学历 + 专业
    args = student_agent.tool_args("exam_positions",
                                    "重庆的本科公务员岗位有哪些")
    assert args["place"] == "重庆"
    assert args["education"] == "本科"


def test_default_routes() -> None:
    assert student_agent.default_tool("有哪些岗位适合我") == "my_recommendations"
    assert student_agent.default_tool("我需要学什么技能") == "kg_skill_jobs"
    assert student_agent.default_tool("今天天气") == "my_warning"


def test_exam_position_args() -> None:
    args = student_agent.tool_args("exam_positions", "查一下重庆国考职位表里计算机类的岗位")
    assert args["place"] == "重庆"
    assert args["keyword"] == "计算机类"


def test_exam_notice_args() -> None:
    args = student_agent.tool_args("exam_notices", "考公公告里有哪些岗位")
    assert args["exam_type"] == "civil"


def test_describe() -> None:
    info = student_agent.describe()
    assert info["agent_version"] == "student-agent-v1"
    assert "my_grades" in info["personal_tools"]

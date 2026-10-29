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
    assert student_agent.personal_tool("面试会问什么") == "question_bank_lookup"
    assert student_agent.personal_tool("实习管理办法有哪些") is None


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

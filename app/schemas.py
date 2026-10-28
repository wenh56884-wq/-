# app/schemas.py
# 职责：Pydantic 请求/响应模型（对外契约）
# 依赖：pydantic.BaseModel
# 说明：所有字段中文释义写在 Field(description) 里，直接给前端与 Critic 看

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    """登录入参：role + 账号 + 口令（tenant_id 可选，用于同账号多租户场景）。"""

    role: str = Field(description="teacher / student")
    account: str = Field(description="教师传工号 employee_no，学生传学号 student_no")
    password: str = Field(description="明文口令，仅在内网 HTTPS 传输")
    tenant_id: int | None = Field(default=None, description="可选：限定登录的租户")


class LoginOut(BaseModel):
    """登录出参：token + 身份摘要（不含任何口令信息）。"""

    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: int
    actor_id: int
    student_no: str | None = None
    expires_in: int = Field(description="token 有效秒数")


class ChatTurn(BaseModel):
    """一轮历史对话（前端回传，仅作语境，不参与鉴权）。"""

    role: str = Field(pattern="^(user|assistant)$", description="user / assistant")
    text: str = Field(max_length=1000, description="该轮正文")


class ChatIn(BaseModel):
    """对话入参：query 必填，term 缺省时由引擎回落最新学期。"""

    query: str = Field(min_length=1, description="用户提问")
    term: str | None = None
    session_id: int | None = Field(default=None, description="续聊会话编号；不传则新开会话")
    history: list[ChatTurn] = Field(default_factory=list, max_length=8,
                                    description="最近几轮对话，用于追问语境（无会话时使用）")


class ChatOut(BaseModel):
    """对话出参：answer + trace_id（Critic 依赖 trace_id 回查原始工具结果）。"""

    answer: str
    trace_id: str
    term: str | None = None
    degraded: bool = Field(default=False, description="True 表示走了降级话术，不保证含数值")
    session_id: int | None = Field(default=None, description="本轮所属会话，续聊时回传")
    tool: str = Field(default="", description="本轮命中的能力：kb_search / web_search / ...")
    citations: list[dict] = Field(default_factory=list,
                                  description="引用清单：知识库给页码，联网给 URL")
    suggested_followups: list[str] = Field(default_factory=list,
                                           description="引导式追问：答完后建议继续问的问题")


class FeedbackIn(BaseModel):
    """对话反馈入参：一次点赞/点踩 + 可选备注，落审计供质量统计。"""

    trace_id: str = Field(min_length=1, max_length=32, description="要反馈的那轮回答的追踪号")
    rating: Literal["up", "down"] = Field(description="up=有帮助，down=没帮助")
    comment: str | None = Field(default=None, max_length=500, description="可选文字备注")


class HealthOut(BaseModel):
    """健康检查：db / duckdb 真实连通，llm 只检查 key 是否配置。"""

    status: str
    db: str
    duckdb: str
    llm: str


class ErrorOut(BaseModel):
    """统一错误结构：只给中文 message，不外泄堆栈。"""

    detail: str

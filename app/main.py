# app/main.py
# 职责：FastAPI 应用工厂、路由注册、统一异常与请求级审计中间件
# 依赖：app.auth / app.routers.* / app.schemas / app.audit / engine.store
# 说明：容器化模式下 `uvicorn app.main:app`；本地演示 `python app\main.py`

from __future__ import annotations

import time
import uuid
from typing import Any

import pymysql
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import (
    ROLE_STUDENT,
    ROLE_TEACHER,
    authenticate,
    create_access_token,
    get_current_ctx,
    get_current_ctx_payload,
)
from app.config import get_settings
from app.routers import student as student_router
from app.routers import teacher as teacher_router
from app.schemas import ChatIn, ChatOut, HealthOut, LoginIn, LoginOut

APP_TITLE = "启航 · 学业预警与职业发展助手 API"
APP_VERSION = "1.0.0"


def _check_mysql() -> str:
    """真实连通检测：能连上并查到任意一行即 ok。"""
    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return "ok"
    finally:
        conn.close()


def _check_duckdb() -> str:
    """真实连通检测：读一次分析库（health_check）。"""
    try:
        from engine.store import DuckDBStore

        return "ok" if DuckDBStore().health_check() else "down"
    except Exception:
        return "down"


def _run_chat(ctx: ToolContext, payload: dict[str, Any], body: ChatIn) -> tuple[str, bool]:
    """调 LangGraph 对话入口；图未就绪或异常时降级成无数值话术（degraded=True）。"""
    term = body.term
    try:
        from agents.graph import run_chat  # 延迟导入：P7 接入后即生效
    except Exception:
        return ("智能体编排尚未启用，暂无法回答该问题。"
                "你可以先查看「预警列表」与「个人画像」中的结构化数据。", True)
    try:
        result = run_chat(ctx, body.query, term=term, claims=payload)
    except NotImplementedError:
        return ("智能体编排尚未启用，暂无法回答该问题。"
                "你可以先查看「预警列表」与「个人画像」中的结构化数据。", True)
    except Exception:
        return "智能体处理失败，已降级为安全话术（不提供任何未经核对的数值）。", True
    answer = str((result or {}).get("answer") or "").strip()
    degraded = bool((result or {}).get("degraded"))
    if not answer:
        return "未得到可用答复，已降级为安全话术。", True
    return answer, degraded


def create_app() -> FastAPI:
    """构造 FastAPI 应用（工厂函数，便于测试与托管）。"""
    app = FastAPI(title=APP_TITLE, version=APP_VERSION,
                  responses={401: {"model": None}, 403: {"model": None}})

    # 开发期允许 Vue dev server 直连；演示托管模式下此策略无害（同源请求）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(teacher_router.router)
    app.include_router(student_router.router)

    @app.middleware("http")
    async def audit_middleware(request: Request, call_next):
        """请求级审计：无论成功失败都写 audit_log（含耗时）。"""
        started = time.perf_counter()
        actor_type, actor_id = "anonymous", 0
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            try:
                from app.auth import decode_token

                claims = decode_token(header.split(" ", 1)[1].strip())
                actor_type = str(claims.get("role") or "anonymous")
                actor_id = int(claims.get("student_id")
                               or claims.get("teacher_id") or 0)
            except Exception:  # token 无效：按匿名留痕，由依赖层决定 401
                actor_type, actor_id = "invalid-token", 0
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            audit_event(
                actor_type=actor_type, actor_id=actor_id,
                action=f"{request.method} {request.url.path}",
                target=request.url.query or "",
                detail={"status": status_code},
                duration_ms=(time.perf_counter() - started) * 1000,
            )

    @app.exception_handler(PermissionError)
    async def _permission_handler(request: Request, exc: PermissionError):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN,
                            content={"detail": str(exc)})

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _server_handler(request: Request, exc: Exception):
        # 统一 500：中文提示，不外泄任何堆栈或内部信息
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            content={"detail": "服务内部错误，请联系运维查看日志"})

    @app.get("/health", response_model=HealthOut, tags=["系统"])
    def health() -> HealthOut:
        """真实检测 MySQL 与 DuckDB 连通；llm 只检查 key 是否配置。"""
        try:
            db = _check_mysql()
        except Exception:
            db = "down"
        settings = get_settings()
        return HealthOut(
            status="ok" if (db == "ok" and _check_duckdb() == "ok") else "degraded",
            db=db,
            duckdb=_check_duckdb(),
            llm="configured" if settings.deepseek_api_key else "missing",
        )

    @app.post("/auth/login", response_model=LoginOut, tags=["系统"])
    def login(body: LoginIn) -> LoginOut:
        """登录：teacher 用工号、student 用学号；失败统一 401『账号或口令错误』。"""
        role = str(body.role or "").strip()
        if role not in (ROLE_TEACHER, ROLE_STUDENT):
            raise HTTPException(status_code=422,
                                detail="role 只能是 teacher 或 student")
        identity = authenticate(role, body.account, body.password, body.tenant_id)
        if identity is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="账号或口令错误")
        token, expires_in = create_access_token(identity)
        audit_event(actor_type=role, actor_id=identity["actor_id"],
                    action="auth.login", target=str(body.account), detail={"ok": True})
        return LoginOut(
            access_token=token, token_type="bearer", role=role,
            tenant_id=identity["tenant_id"], actor_id=identity["actor_id"],
            student_no=identity.get("student_no"), expires_in=expires_in,
        )

    @app.post("/chat", response_model=ChatOut, tags=["系统"])
    def chat(body: ChatIn,
             claims: dict[str, Any] = Depends(get_current_ctx_payload)) -> ChatOut:
        """对话：调 LangGraph；返回 answer + trace_id，便于 Critic 回查工具结果。"""
        ctx = ToolContext(
            actor_type=str(claims.get("role") or ""),
            tenant_id=int(claims.get("tenant_id") or 0),
            student_id=int(claims["student_id"]) if claims.get("student_id") else None,
            teacher_id=int(claims["teacher_id"]) if claims.get("teacher_id") else None,
        )
        trace_id = uuid.uuid4().hex[:12]
        answer, degraded = _run_chat(ctx, claims, body)
        audit_event(actor_type=ctx.actor_type,
                    actor_id=ctx.student_id or ctx.teacher_id or 0,
                    action="api.chat", target=trace_id,
                    detail={"query": body.query[:120], "term": body.term,
                            "degraded": degraded})
        return ChatOut(answer=answer, trace_id=trace_id, term=body.term,
                       degraded=degraded)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.app_port, reload=False)

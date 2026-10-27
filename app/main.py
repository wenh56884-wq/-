# app/main.py
# 职责：FastAPI 应用工厂、路由注册、统一异常与请求级审计中间件
# 依赖：app.auth / app.routers.* / app.schemas / app.audit / engine.store
# 说明：容器化模式下 `uvicorn app.main:app`；本地演示 `python app\main.py`

from __future__ import annotations

import time
import uuid

import pymysql
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarsHTTPException

from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import (
    ROLE_STUDENT,
    ROLE_TEACHER,
    authenticate,
    create_access_token,
    get_current_ctx,
)
from app.config import get_settings
from app.routers import career as career_router
from app.routers import chat as chat_router
from app.routers import exam as exam_router
from app.routers import forecast as forecast_router
from app.routers import grades as grades_router
from app.routers import interview as interview_router
from app.routers import job as job_router
from app.routers import kb as kb_router
from app.routers import kg as kg_router
from app.routers import question_bank as qb_router
from app.routers import student as student_router
from app.routers import teacher as teacher_router
from app.routers import workflow as workflow_router
from app.schemas import ChatIn, ChatOut, HealthOut, LoginIn, LoginOut

APP_TITLE = "启航 · 学业预警与职业发展助手 API"
APP_VERSION = "1.0.0"


def _check_mysql() -> str:
    """真实连通检测：能连上并查到任意一行即 ok。"""
    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", connect_timeout=5)
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


def _run_chat(ctx: ToolContext, body: ChatIn) -> dict:
    """跑一次对话，返回完整结果（answer / degraded / session_id / citations）。

    优先走 chat_service（会落库、带多轮记忆）；落库层不可用时退回纯图调用，
    回答照常给，只是这一轮不留痕——不因为存储问题让用户拿不到答案。
    """
    try:
        from app import chat_service

        return chat_service.handle(ctx, body.query, body.term, body.session_id, body.history)
    except Exception:
        pass
    try:
        from agents.graph import run_chat  # 延迟导入：P7 接入后即生效
    except Exception:
        return {"answer": "智能体编排尚未启用，暂无法回答该问题。"
                          "你可以先查看「预警列表」与「个人画像」中的结构化数据。",
                "degraded": True, "session_id": None, "tool_name": "", "citations": []}
    try:
        return run_chat(ctx, body.query, term=body.term,
                        history=[{"role": turn.role, "text": turn.text}
                                 for turn in (body.history or [])])
    except Exception:
        return {"answer": "智能体处理失败，已降级为安全话术（不提供任何未经核对的数值）。",
                "degraded": True, "session_id": None, "tool_name": "", "citations": []}


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
    app.include_router(career_router.router)
    app.include_router(forecast_router.router)
    app.include_router(grades_router.router)
    app.include_router(exam_router.router)
    app.include_router(job_router.router)
    app.include_router(interview_router.router)
    app.include_router(kg_router.router)
    app.include_router(qb_router.router)
    app.include_router(kb_router.router)
    app.include_router(chat_router.router)
    app.include_router(workflow_router.router)

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
        duckdb_state = _check_duckdb()
        return HealthOut(
            status="ok" if (db == "ok" and duckdb_state == "ok") else "degraded",
            db=db,
            duckdb=duckdb_state,
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
             ctx: ToolContext = Depends(get_current_ctx)) -> ChatOut:
        """对话：调 LangGraph；返回 answer + trace_id，便于 Critic 回查工具结果。

        身份只从 get_current_ctx 取（已校验角色与租户），不再手工解析 claims。
        """
        trace_id = uuid.uuid4().hex[:12]
        result = _run_chat(ctx, body)
        answer = str(result.get("answer") or "").strip()
        degraded = bool(result.get("degraded"))
        if not answer:
            answer, degraded = "未得到可用答复，已降级为安全话术。", True
        audit_event(actor_type=ctx.actor_type,
                    actor_id=ctx.student_id or ctx.teacher_id or 0,
                    action="api.chat", target=trace_id,
                    detail={"query": body.query[:120], "term": body.term,
                            "session_id": result.get("session_id"),
                            "tool": result.get("tool_name"),
                            "citations": len(result.get("citations") or []),
                            "degraded": degraded})
        return ChatOut(answer=answer, trace_id=trace_id, term=body.term,
                       degraded=degraded, session_id=result.get("session_id"),
                       tool=str(result.get("tool_name") or ""),
                       citations=list(result.get("citations") or []))

    # --- 静态托管（P10-3）：构建产物存在才挂，已注册路由与 /api 不受影响 ---
    dist = get_settings().frontend_dist_obj
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

        @app.exception_handler(StarsHTTPException)
        async def _spa_fallback(request: Request, exc: StarsHTTPException):
            """未命中的前端路由（如 /teacher）回落到 index.html，交给 Vue Router 接管。"""
            if exc.status_code == 404 and not request.url.path.startswith("/api"):
                return FileResponse(dist / "index.html")
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app


app = create_app()

# 后台定时同步：官方一发布新竞赛通知就自动入库，学生端随即看到未读推送
try:
    from app.competition_sync import start_background_sync

    start_background_sync()
except Exception:  # 同步模块异常不能拖垮接口服务
    pass

# 后台周更：招考公告（考公 / 考编 / 考研）每周抓一次并增量入库
# 间隔由 RECRUIT_SYNC_HOURS 控制（默认 168 小时 = 一周；0 关闭）
try:
    from app.recruit_sync import start_background_sync as start_recruit_sync

    start_recruit_sync()
except Exception:
    pass


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.app_port, reload=False)

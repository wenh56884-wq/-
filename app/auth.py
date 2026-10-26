# app/auth.py
# 职责：JWT 编解码 + 身份注入——student_id / teacher_id 只能从 token 解析，禁止从 body / query 读
# 依赖：app.config / passlib / python-jose / pymysql / agents.tools.ToolContext
# 说明：口令校验兼容两种形态：bcrypt（新账号）与 scripts\seed_mock.py 的演示 sha256（存量数据）

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pymysql
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from agents.tools import ToolContext
from app.config import Settings, get_settings

ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ALGORITHM = "HS256"
_DEV_SECRET = "qihang-dev-secret-change-me"

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="未认证或 token 已失效",
    headers={"WWW-Authenticate": "Bearer"},
)
_FORBIDDEN_TEACHER = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="学生账号无权访问教师端接口",
)
_FORBIDDEN_STUDENT = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="教师账号无权访问学生端接口，学生端只服务于本人",
)


def _secret(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return s.jwt_secret or _DEV_SECRET


# ----------------------------------------------------------------
# 口令
# ----------------------------------------------------------------
def hash_password(plain: str) -> str:
    """生成 bcrypt 口令摘要（新账号一律走这里）。"""
    return _pwd.hash(str(plain)[:72])


def _legacy_hash(account: str) -> str:
    """seed_mock 的演示摘要：sha256('qihang_<账号>') 取前 32 位。"""
    return hashlib.sha256(f"qihang_{account}".encode()).hexdigest()[:32]


def verify_password(plain: str, password_hash: str, account: str = "") -> bool:
    """校验口令：bcrypt 摘要走 passlib；存量演示摘要走「口令=账号」约定。

    为什么不许任意口令登录：seed_mock 的摘要只由账号派生，若直接比对摘要，
    任何口令都会通过。故这里要求 plain == account（演示约定：学号/工号即初始口令）。
    """
    if not password_hash:
        return False
    if password_hash.startswith("$2"):
        try:
            return bool(_pwd.verify(str(plain)[:72], password_hash))
        except ValueError:
            return False
    return bool(account) and str(plain) == str(account) \
        and _legacy_hash(str(account)) == password_hash


# ----------------------------------------------------------------
# 登录：查库校验，返回可用于签 token 的身份
# ----------------------------------------------------------------
def _connect(settings: Settings | None = None) -> pymysql.connections.Connection:
    s = settings or get_settings()
    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def authenticate(role: str, account: str, password: str,
                 tenant_id: int | None = None) -> dict[str, Any] | None:
    """按角色查对应的账号表；库不可用时返回 None（登录失败，不外泄原因）。"""
    if role == ROLE_TEACHER:
        sql = ("SELECT t.id AS id, t.tenant_id AS tenant_id, t.name AS name, "
               "       t.employee_no AS employee_no, t.password_hash AS password_hash "
               "FROM teacher t WHERE t.employee_no = %s")
    elif role == ROLE_STUDENT:
        sql = ("SELECT s.id AS id, s.tenant_id AS tenant_id, s.name AS name, "
               "       s.student_no AS employee_no, s.password_hash AS password_hash "
               "FROM student s WHERE s.student_no = %s")
    else:
        return None
    params: list[Any] = [account]
    if tenant_id:
        alias = "t" if role == ROLE_TEACHER else "s"
        sql += f" AND {alias}.tenant_id = %s"
        params.append(tenant_id)
    sql += " LIMIT 1"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError):
        return None
    finally:
        conn.close()

    if not rows:
        return None
    row = rows[0]
    if tenant_id and int(row["tenant_id"]) != int(tenant_id):
        return None
    if not verify_password(password, str(row["password_hash"] or ""), str(row["employee_no"])):
        return None
    return {
        "role": role,
        "tenant_id": int(row["tenant_id"]),
        "actor_id": int(row["id"]),
        "account": str(row["employee_no"]),
        "name": str(row["name"] or ""),
        "student_no": str(row["employee_no"]) if role == ROLE_STUDENT else None,
    }


# ----------------------------------------------------------------
# Token
# ----------------------------------------------------------------
def create_access_token(identity: Mapping[str, Any],
                        settings: Settings | None = None) -> tuple[str, int]:
    """签发访问令牌，返回 (token, expires_in 秒)。sub 用角色+账号，便于日志追踪。"""
    s = settings or get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=max(1, s.jwt_expire_minutes))
    payload = {
        "sub": f"{identity.get('role')}:{identity.get('account')}",
        "role": str(identity.get("role")),
        "tenant_id": int(identity.get("tenant_id") or 0),
        "student_id": identity.get("actor_id") if identity.get("role") == ROLE_STUDENT else None,
        "teacher_id": identity.get("actor_id") if identity.get("role") == ROLE_TEACHER else None,
        "student_no": identity.get("student_no"),
        "jti": uuid.uuid4().hex,
        "exp": expire,
    }
    token = jwt.encode(payload, _secret(s), algorithm=ALGORITHM)
    return token, max(1, s.jwt_expire_minutes) * 60


def decode_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """解析 token；无效或过期抛 JWTError（上层转 401）。"""
    return jwt.decode(token, _secret(settings), algorithms=[ALGORITHM])


def ctx_from_token(payload: Mapping[str, Any]) -> ToolContext:
    """token claims → ToolContext（工具层再也不接受任何外部传入的 id）。"""
    role = str(payload.get("role") or "")
    return ToolContext(
        actor_type=role,
        tenant_id=int(payload.get("tenant_id") or 0),
        student_id=int(payload["student_id"]) if payload.get("student_id") else None,
        teacher_id=int(payload["teacher_id"]) if payload.get("teacher_id") else None,
    )


def anonymous_ctx() -> ToolContext:
    """未携带 token 时的占位身份：只用于审计，不参与任何取数。"""
    return ToolContext(actor_type="anonymous", tenant_id=0)


# ----------------------------------------------------------------
# FastAPI 依赖
# ----------------------------------------------------------------
def get_current_ctx(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> ToolContext:
    """从 Authorization: Bearer 解析身份；缺失/无效一律 401（中文提示，不外泄堆栈）。"""
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise _UNAUTHORIZED
    ctx = ctx_from_token(payload)
    if ctx.actor_type not in (ROLE_TEACHER, ROLE_STUDENT) or not ctx.tenant_id:
        raise _UNAUTHORIZED
    return ctx


def get_current_ctx_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    """同 get_current_ctx，但返回原始 claims（供 /chat 取 student_no 等展示信息）。"""
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED
    try:
        return decode_token(credentials.credentials)
    except JWTError:
        raise _UNAUTHORIZED


def require_teacher(ctx: ToolContext = Depends(get_current_ctx)) -> ToolContext:
    if ctx.actor_type != ROLE_TEACHER:
        raise _FORBIDDEN_TEACHER
    return ctx


def require_student(ctx: ToolContext = Depends(get_current_ctx)) -> ToolContext:
    if ctx.actor_type != ROLE_STUDENT:
        raise _FORBIDDEN_STUDENT
    if not ctx.student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="token 内缺少 student_id，无法确定本人身份")
    return ctx

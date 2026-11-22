# app/routers/pet.py
# 职责：AI 宠物陪伴层的 HTTP 接口——人格化对话、状态读写、专注模式、主动说话触发。
# 铁律落地：身份只来自 get_current_ctx；状态按身份隔离（铁律 3）且持久化到 MySQL
#          （跨会话保留）；心情/记忆/调度数值由 engine.pet 确定性算出（铁律 1）。
# 边界：只做陪伴对话，不查任何业务数据，杜绝越权与数值编造。

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from agents import llm
from agents.tools import ToolContext
from app.auth import get_current_ctx
from app.config import get_settings
from app.logging_config import get_logger
from engine import pet as pet_engine
from engine import pet_store

router = APIRouter(prefix="/pet", tags=["pet"])
logger = get_logger("qihang.pet")

# PetRuntime 已下沉到 engine.pet，路由层直接复用其数据类。
PetRuntime = pet_engine.PetRuntime
Personality = pet_engine.Personality
MoodState = pet_engine.MoodState
ShortMemory = pet_engine.ShortMemory
ProactiveScheduler = pet_engine.ProactiveScheduler
MOOD_HAPPY = pet_engine.MOOD_HAPPY
DEFAULT_PERSONALITY = pet_engine.DEFAULT_PERSONALITY
DEFAULT_SHORT_MEMORY_TURNS = pet_engine.DEFAULT_SHORT_MEMORY_TURNS
build_state = pet_engine.build_state
template_reply = pet_engine.template_reply


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _try_db():
    """尝试取连接；MySQL 不可用时返回 None（降级为纯内存，不阻断陪伴）。"""
    try:
        return _conn()
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet db unavailable, running in memory mode: %s", exc)
        return None


@contextmanager
def _db():
    conn = _try_db()
    try:
        yield conn
    finally:
        if conn is not None:
            conn.close()


def init_db() -> None:
    """建宠物表（幂等）。应用启动时调用一次。"""
    conn = _try_db()
    if conn is None:
        return
    try:
        pet_store.ensure_schema(conn)
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet db init skipped: %s", exc)
    finally:
        conn.close()


# 身份 -> 运行时缓存。内存缓存以避免每请求查库；写操作同步落库。
_PETS: dict[int, PetRuntime] = {}


def _identity(ctx: ToolContext) -> int:
    if ctx.actor_type == "teacher":
        return int(ctx.teacher_id or 0)
    return int(ctx.student_id or 0)


def _tenant(ctx: ToolContext) -> int:
    return int(ctx.tenant_id or 0)


def _actor_type(ctx: ToolContext) -> str:
    return "teacher" if ctx.actor_type == "teacher" else "student"


def _load_personality(conn, identity: int) -> Personality:
    """加载人格；无连接/无记录/出错则返回默认。"""
    if conn is None:
        return DEFAULT_PERSONALITY
    try:
        data = pet_store.load_personality(conn, identity)
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet personality load failed: %s", exc)
        return DEFAULT_PERSONALITY
    if data is None:
        return DEFAULT_PERSONALITY
    encourage = data.get("encourage") or list(DEFAULT_PERSONALITY.encourage_pool)
    return Personality(
        name=data["name"], species=data["species"],
        tone=data["tone"], greeting=data["greeting"],
        encourage_pool=tuple(encourage),
    )


def _load_or_default(conn, identity: int) -> PetRuntime:
    """从 MySQL 恢复运行时；无连接/无记录/出错则建默认。记忆一并加载。"""
    data = None
    if conn is not None:
        try:
            data = pet_store.load_runtime(conn, identity)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet runtime load failed, fallback to default: %s", exc)
    personality = _load_personality(conn, identity)
    if data is None:
        return PetRuntime(
            personality=personality,
            mood=MoodState(),
            memory=ShortMemory(),
            scheduler=ProactiveScheduler(),
        )
    rt = PetRuntime(
        personality=personality,
        mood=MoodState(mood=data["mood"], intensity=data["intensity"],
                       last_interact_at=data["last_interact_at"]),
        memory=ShortMemory(max_turns=DEFAULT_SHORT_MEMORY_TURNS),
        scheduler=ProactiveScheduler(interval_sec=data["interval_sec"],
                                     focus_mode=data["focus_mode"],
                                     last_spoke_at=data["last_spoke_at"]),
    )
    if conn is not None:
        try:
            turns = pet_store.load_memory(conn, identity, DEFAULT_SHORT_MEMORY_TURNS)
            rt.memory.turns = list(turns)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet memory load failed: %s", exc)
    return rt


def _runtime(ctx: ToolContext, conn) -> PetRuntime:
    key = _identity(ctx)
    rt = _PETS.get(key)
    if rt is None:
        rt = _load_or_default(conn, key)
        _PETS[key] = rt
    return rt


def _add_memory(conn, identity: int, tenant: int, role: str, text: str, now: float) -> None:
    """写一条记忆；无连接或失败时静默跳过（内存已更新）。"""
    if conn is None:
        return
    try:
        pet_store.add_memory(conn, identity, tenant, role, text, now)
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet memory add failed identity=%s: %s", identity, exc)


def _persist(conn, ctx: ToolContext, rt: PetRuntime, *, save_memory: bool = True) -> None:
    """把运行时状态落库；无连接或失败时跳过（内存仍可用，下次再写）。"""
    if conn is None:
        return
    key = _identity(ctx)
    tenant = _tenant(ctx)
    if save_memory:
        try:
            pet_store.trim_memory(conn, key, rt.memory.max_turns * 2)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet memory trim failed identity=%s: %s", key, exc)
    try:
        pet_store.save_runtime(conn, key, tenant, rt)
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet runtime save failed identity=%s: %s", key, exc)


# ---------------- 请求体 ----------------


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class FocusIn(BaseModel):
    on: bool


class PersonalityIn(BaseModel):
    """人格更新：名字必填，语气/问候语可选（缺省保留原值），鼓励池可选。"""
    name: str = Field(min_length=1, max_length=40)
    tone: str | None = Field(default=None, max_length=80)
    greeting: str | None = Field(default=None, max_length=200)
    encourage: list[str] | None = Field(default=None)


class MemoryUpdateIn(BaseModel):
    """长期记忆编辑：内容必填（与提取规则一致，1-60 字）。"""
    content: str = Field(min_length=1, max_length=60)


MAX_ENCOURAGE_POOL = 10
MAX_ENCOURAGE_LEN = 40
MAX_MEMORY_LEN = 60  # 与 _EXTRACT_SYS 的提取上限一致


# ---------------- prompt 构造 ----------------

# 半角标点 -> 全角标点（确定性后处理，与 LLM 无关）
_PUNCT_MAP = str.maketrans({"?": "？", "!": "！", ",": "，", ":": "：", ";": "；"})
# 连续波浪号收敛为单个全角波浪号，避免「～～~」这种不统一写法
_WAVE_RE = re.compile(r"[~～]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def normalize_reply(text: str) -> str:
    """确定性标点归一：半角转全角、波浪号收敛、压多余空白。不改动任何语义。"""
    t = (text or "").strip()
    t = _WAVE_RE.sub("～", t)
    t = t.translate(_PUNCT_MAP)
    t = _MULTI_SPACE_RE.sub(" ", t)
    return t.strip()


def _system_prompt(p: pet_engine.Personality) -> str:
    """宠物人格 system prompt：纯陪伴、禁止数值、不查业务。"""
    return (
        f"你是{p.name}，一只{p.species}，语气{p.tone}。\n"
        "陪伴规则：\n"
        "1. 纯陪伴聊天，回复中不罗列具体数值（如风险分、分数、排名、百分比）。\n"
        "2. 可引用系统提供的用户学业状态（预警等级）给出针对性鼓励：状态好就夸，"
        "有预警就鼓励一起赶上来，数据不足就加油；但不得编造其他业务数据或数值。\n"
        "3. 回复简短温暖，像朋友一样，不超过 60 字。\n"
        "4. 不确定就说不知道，绝不编造。\n"
        "5. 用户说压力大/紧张时，先共情再鼓励。\n"
        "6. 标点一律用中文全角标点，禁止波浪号、emoji、颜文字。\n"
        "7. 开头句式每次都要变化，禁止每次都用同一句问候（如固定「嘿，你好呀」）。\n"
        "8. 必须回应用户刚说的内容，不要自说自话、不要答非所问。"
    )


_EXTRACT_SYS: str = (
    "你是记忆助手。从对话中提取关于“用户”的长期事实（目标、偏好、约束、重要事件），"
    "供宠物以后陪伴时引用。规则：只提取用户的事实，不含宠物的；"
    "绝不包含任何数值、成绩、排名、分数；没有值得记的就返回空行；"
    "每行一条，最多 5 行，每行不超过 60 字。"
)


def _recall_memories(conn, identity: int, limit: int = 5) -> list[str]:
    """召回长期记忆的内容摘要（确定性：按重要度+时间排序取 limit）。"""
    return [m["content"] for m in _list_memories_full(conn, identity, limit)]


def _list_memories_full(conn, identity: int, limit: int = 50) -> list[dict[str, Any]]:
    """加载长期记忆完整条目（含 id，供查看/编辑/删除）。"""
    if conn is None:
        return []
    try:
        return pet_store.load_long_memories(conn, identity, limit)
    except (pymysql.MySQLError, OSError) as exc:
        logger.warning("pet long memory load failed identity=%s: %s", identity, exc)
        return []


def _extract_memories(conn, ctx: ToolContext, user_turns: list[str]) -> int:
    """从近期用户对话用 LLM 提取长期事实并落库（表达性提取，失败不阻断）。

    铁律 1：提取的是事实文本、不生成数值；存储条数/上限由引擎确定。
    """
    if conn is None or not user_turns:
        return 0
    prompt = "\n".join(f"用户说：{t}" for t in user_turns)
    facts = llm.generate_reply(
        _actor_type(ctx), system_prompt=_EXTRACT_SYS, user_prompt=prompt, tag="pet.extract",
    )
    if not facts:
        return 0
    added = 0
    now = time.time()
    key = _identity(ctx)
    tenant = _tenant(ctx)
    for line in facts.splitlines():
        fact = line.strip().lstrip("-•* ").strip()
        if len(fact) < 4 or len(fact) > 60:
            continue
        try:
            pet_store.add_long_memory(conn, key, tenant, fact, "fact", 3, now)
            added += 1
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet long memory add failed: %s", exc)
            break
    if added:
        try:
            pet_store.trim_long_memories(conn, key, pet_engine.LONG_MEMORY_MAX)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet long memory trim failed: %s", exc)
    return added


def _extract_memories_bg(ctx: ToolContext, user_turns: list[str]) -> None:
    """响应返回后再做长期记忆提取：不让第二次 LLM 调用堵住宠物回复。

    后台任务运行在原请求的连接关闭之后，所以这里必须自己开一条连接。
    """
    if not user_turns:
        return
    conn = _try_db()
    if conn is None:
        return
    try:
        _extract_memories(conn, ctx, user_turns)
    finally:
        conn.close()


_LEVEL_CN = {
    "green": "正常", "normal": "正常",
    "yellow": "关注", "orange": "预警", "red": "严重",
    "unknown": "数据不足",
}


def _academic_snapshot(ctx: ToolContext) -> dict[str, Any] | None:
    """取用户真实学业状态（预警等级），供宠物针对性鼓励。

    铁律落地：等级由 engine.warning 确定性算出；身份走 ctx（工具层解析学号+租户隔离）。
    失败/无数据时返回 None，宠物退化为纯陪伴。仅在真实 DB 模式（conn 非空）下调用。
    """
    if ctx.actor_type != "student":
        return None
    try:
        from agents import tools
        w = tools.my_warning(ctx, ctx.term)
        level = str(w.get("level") or "unknown")
        return {
            "name": str(w.get("name") or ""),
            "level": level,
            "level_cn": _LEVEL_CN.get(level, "数据不足"),
        }
    except Exception as exc:
        logger.warning("pet academic snapshot failed identity=%s: %s",
                       _identity(ctx), exc)
        return None


def _build_user_prompt(history: list[pet_engine.Turn], current: str,
                       p: pet_engine.Personality,
                       memories: list[str] | None = None,
                       academic: dict[str, Any] | None = None) -> str:
    """把短期记忆、长期记忆与学业状态拼进单轮 user prompt。"""
    if not history:
        base = current
    else:
        lines = ["【近期对话】"]
        for t in history[-6:]:  # 只带最近 6 轮，控制 token
            who = "用户" if t.role == "user" else p.name
            lines.append(f"{who}：{t.text}")
        lines.append("【你刚说】")
        lines.append(current)
        base = "\n".join(lines)
    blocks = []
    if academic:
        blocks.append(
            "【用户学业状态】\n"
            f"姓名：{academic.get('name', '')}\n"
            f"预警等级：{academic.get('level_cn', '数据不足')}"
        )
    if memories:
        blocks.append("【用户长期记忆】\n" + "\n".join(f"- {m}" for m in memories))
    if blocks:
        return "\n\n".join(blocks) + "\n\n" + base
    return base


# ---------------- 对话 ----------------


@router.post("/chat")
def chat_with_pet(
    body: ChatIn,
    background_tasks: BackgroundTasks,
    ctx: ToolContext = Depends(get_current_ctx),
) -> dict[str, Any]:
    """被动应答：用户和宠物说话。LLM 生成文本，失败回退模板（degraded 确定性）。"""
    with _db() as conn:
        rt = _runtime(ctx, conn)
        key = _identity(ctx)
        tenant = _tenant(ctx)
        now = time.time()
        rt.mood.decay(now)
        rt.mood.apply_interaction(MOOD_HAPPY)
        rt.memory.add("user", body.text, now)
        _add_memory(conn, key, tenant, "user", body.text, now)

        history = rt.memory.recent()
        memories = _recall_memories(conn, key, 5)
        academic = _academic_snapshot(ctx) if conn is not None else None
        reply = llm.generate_reply(
            _actor_type(ctx),
            system_prompt=_system_prompt(rt.personality),
            user_prompt=_build_user_prompt(history, body.text, rt.personality, memories, academic),
            tag="pet.chat",
        )
        degraded = reply is None
        if degraded:
            reply = template_reply(rt.personality, body.text)
        reply = normalize_reply(reply)

        now2 = time.time()
        rt.memory.add("pet", reply, now2)
        _add_memory(conn, key, tenant, "pet", reply, now2)
        _persist(conn, ctx, rt)
        # 长期记忆提取（第二次 LLM 调用）放到响应之后，别堵住宠物回复
        user_turns = [t.text for t in rt.memory.recent()[-4:] if t.role == "user"]
        background_tasks.add_task(_extract_memories_bg, ctx, user_turns)
        state = build_state(rt.mood, rt.scheduler, rt.memory, now=now2)
    return {"reply": reply, "mood": state.mood, "degraded": degraded}


# ---------------- 状态 / 专注 / 主动说话 ----------------


@router.get("/state")
def get_state(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    with _db() as conn:
        rt = _runtime(ctx, conn)
        now = time.time()
        rt.mood.decay(now)
        state = build_state(rt.mood, rt.scheduler, rt.memory, now=now)
    return {
        "mood": state.mood,
        "intensity": state.intensity,
        "focus_mode": state.focus_mode,
        "next_speak_at": state.next_speak_at,
        "memory_size": state.memory_size,
        "name": rt.personality.name,
    }


@router.post("/focus")
def set_focus(body: FocusIn, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """切换专注模式：开启后宠物不再主动说话，只保留被动应答。"""
    with _db() as conn:
        rt = _runtime(ctx, conn)
        rt.scheduler.focus_mode = body.on
        _persist(conn, ctx, rt, save_memory=False)
    return {"focus_mode": rt.scheduler.focus_mode}


@router.post("/proactive")
def maybe_proactive(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """主动说话触发器：到点返回一句主动话，未到点静默。"""
    with _db() as conn:
        rt = _runtime(ctx, conn)
        now = time.time()
        rt.mood.decay(now)
        if not rt.scheduler.should_speak(now):
            return {"spoke": False, "next_speak_at": rt.scheduler.next_speak_at(now)}

        rt.scheduler.on_spoke(now)
        rt.mood.apply_interaction(MOOD_HAPPY)
        prompt = (
            f"你叫{rt.personality.name}。用户现在可能在忙或发呆，"
            "主动发起一句简短问候或陪伴话，不超过 30 字，不要提问，不要数值。"
            "开头句式每次都要变化，不要重复之前的问候；"
            "标点一律用中文全角标点，禁止波浪号、emoji、颜文字。"
        )
        text = llm.generate_reply(
            _actor_type(ctx),
            system_prompt=_system_prompt(rt.personality),
            user_prompt=prompt,
            tag="pet.proactive",
        )
        if not text:
            text = rt.personality.encourage_pool[int(now) % len(rt.personality.encourage_pool)]
        text = normalize_reply(text)
        rt.memory.add("pet", text, now)
        _add_memory(conn, _identity(ctx), _tenant(ctx), "pet", text, now)
        _persist(conn, ctx, rt)
        state = build_state(rt.mood, rt.scheduler, rt.memory, now=now)
    return {
        "spoke": True,
        "text": text,
        "mood": state.mood,
        "next_speak_at": rt.scheduler.next_speak_at(now),
    }


@router.get("/personality")
def get_personality(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    with _db() as conn:
        rt = _runtime(ctx, conn)
    return {
        "name": rt.personality.name,
        "species": rt.personality.species,
        "tone": rt.personality.tone,
        "greeting": rt.personality.greeting,
        "encourage": list(rt.personality.encourage_pool),
    }


@router.get("/memories")
def list_memories(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """宠物记住的长期事实（供用户查看/管理）。确定性排序，无 LLM。"""
    with _db() as conn:
        key = _identity(ctx)
        items = _list_memories_full(conn, key, 50)
    return {"total": len(items), "items": items}


@router.put("/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryUpdateIn,
                  ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """编辑一条长期记忆的文本；只允许改本人（身份编号）的记忆。"""
    text = re.sub(r"\s+", " ", str(body.content or "")).strip()
    if not text or len(text) > MAX_MEMORY_LEN:
        raise HTTPException(status_code=422, detail="记忆内容需为 1-60 字")
    with _db() as conn:
        key = _identity(ctx)
        if conn is None:
            raise HTTPException(status_code=404, detail="记忆不存在")
        try:
            ok = pet_store.update_long_memory(conn, key, memory_id, text)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet memory update failed identity=%s id=%s: %s", key, memory_id, exc)
            raise HTTPException(status_code=500, detail="记忆编辑失败") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"updated": True, "id": memory_id, "content": text}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """删除一条长期记忆；只允许删本人（身份编号）的记忆。"""
    with _db() as conn:
        key = _identity(ctx)
        if conn is None:
            raise HTTPException(status_code=404, detail="记忆不存在")
        try:
            ok = pet_store.delete_long_memory(conn, key, memory_id)
        except (pymysql.MySQLError, OSError) as exc:
            logger.warning("pet memory delete failed identity=%s id=%s: %s", key, memory_id, exc)
            raise HTTPException(status_code=500, detail="记忆删除失败") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"deleted": True, "id": memory_id}


@router.put("/personality")
def update_personality(body: PersonalityIn, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """更新宠物人格：名字必填，语气/问候语/鼓励池可选（缺省保留原值）。"""
    with _db() as conn:
        rt = _runtime(ctx, conn)
        current = rt.personality
        new_name = body.name.strip() or current.name
        new_tone = (body.tone or "").strip() or current.tone
        new_greeting = (body.greeting or "").strip() or current.greeting
        if body.encourage is None:
            new_encourage = current.encourage_pool
        else:
            cleaned = [e.strip()[:MAX_ENCOURAGE_LEN] for e in (body.encourage or []) if e and e.strip()]
            if not cleaned:
                # 全空则回退默认，避免宠物无鼓励语时模板兜底越界
                cleaned = list(current.encourage_pool)
            new_encourage = tuple(cleaned[:MAX_ENCOURAGE_POOL])
        rt.personality = Personality(
            name=new_name, species=current.species,
            tone=new_tone, greeting=new_greeting,
            encourage_pool=new_encourage,
        )
        # 人格落库 + 同步运行时快照（人格名字）
        if conn is not None:
            try:
                pet_store.save_personality(conn, _identity(ctx), _tenant(ctx), rt.personality)
            except (pymysql.MySQLError, OSError) as exc:
                logger.warning("pet personality save failed identity=%s: %s", _identity(ctx), exc)
        _persist(conn, ctx, rt, save_memory=False)
    return {
        "name": rt.personality.name,
        "species": rt.personality.species,
        "tone": rt.personality.tone,
        "greeting": rt.personality.greeting,
        "encourage": list(rt.personality.encourage_pool),
    }

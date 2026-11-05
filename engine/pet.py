# engine/pet.py
# 职责：AI 宠物陪伴层的确定性数值引擎——心情衰减、记忆窗口、主动说话调度、人格配置。
# 铁律 1 落地：本模块只做确定性计算并返回结构化数值；LLM 仅负责把结果组织成自然语言，
#              任何分数/间隔/窗口大小均由这里算出，不经过模型。
# 边界：纯函数 / 数据类优先，无副作用，便于单测与将来迁移。

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

# ---------------- 心情枚举 ----------------
# 这里只保留 PetAvatar 动画能表达的状态，避免后端发明前端画不出来的心情。
MOOD_IDLE: Final = "idle"
MOOD_HAPPY: Final = "happy"
MOOD_THINKING: Final = "thinking"
MOOD_SLEEPY: Final = "sleepy"

VALID_MOODS: Final = frozenset({MOOD_IDLE, MOOD_HAPPY, MOOD_THINKING, MOOD_SLEEPY})

# ---------------- 确定性常量（数值真相源） ----------------
# 心情强度每秒衰减，避免宠物永远亢奋。
MOOD_DECAY_PER_SEC: Final = 0.015
# 一次友好互动提升的心情强度上限。
MOOD_INTERACT_GAIN: Final = 0.35
# 多久不互动后宠物开始变困（秒）；演示用较短值，正式可调。
SLEEPY_THRESHOLD_SEC: Final = 600
# 主动说话默认间隔（秒）：8 分钟一次，陪伴感与打扰的平衡点。
DEFAULT_PROACTIVE_INTERVAL_SEC: Final = 480
# 短期记忆默认保留轮数（一轮 = 一问一答）。
DEFAULT_SHORT_MEMORY_TURNS: Final = 12
# 长期记忆最多保留条数（超出按重要度 + 时间淘汰）。
LONG_MEMORY_MAX: Final = 20

# ---------------- 工具 ----------------


def clamp(value: float, lo: float, hi: float) -> float:
    """把 value 钳到 [lo, hi]。"""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ---------------- 人格配置 ----------------


@dataclass(frozen=True)
class Personality:
    """宠物人格：名字、语气、鼓励语、开场白。纯表达，不含任何数值。"""

    name: str = "小航"
    species: str = "启航小助手"
    tone: str = "活泼、鼓励、像学长一样陪伴"
    greeting: str = "嗨，我是小航，今天想聊点什么呀？"
    encourage_pool: tuple[str, ...] = (
        "加油哦，我相信你！",
        "慢慢来，每一步都算数。",
        "你做得很好，继续保持。",
    )


DEFAULT_PERSONALITY: Final = Personality()


# ---------------- 心情 ----------------


@dataclass
class MoodState:
    """心情状态：当前心情 + 强度（0~1）。强度随时间衰减，互动可拉升。"""

    mood: str = MOOD_IDLE
    intensity: float = 0.5
    last_interact_at: float = field(default_factory=lambda: time.time())

    def decay(self, now: float) -> None:
        """按时间衰减强度；太久不互动则进入困倦。"""
        elapsed = max(0.0, now - self.last_interact_at)
        if elapsed >= SLEEPY_THRESHOLD_SEC:
            self.mood = MOOD_SLEEPY
        self.intensity = clamp(self.intensity - MOOD_DECAY_PER_SEC * elapsed, 0.05, 1.0)

    def apply_interaction(self, mood: str = MOOD_HAPPY) -> None:
        """记录一次互动：刷新时间基准、拉升强度、切到对应心情。"""
        if mood not in VALID_MOODS:
            mood = MOOD_HAPPY
        self.mood = mood
        self.intensity = clamp(self.intensity + MOOD_INTERACT_GAIN, 0.05, 1.0)
        self.last_interact_at = time.time()

    def animation_mood(self) -> str:
        """映射到 PetAvatar 的 mood prop。强度太低时退化为 idle。"""
        if self.mood == MOOD_SLEEPY:
            return MOOD_SLEEPY
        if self.mood == MOOD_HAPPY and self.intensity > 0.6:
            return MOOD_HAPPY
        if self.intensity < 0.3:
            return MOOD_SLEEPY
        return MOOD_IDLE


# ---------------- 短期记忆 ----------------


@dataclass
class Turn:
    """一轮对话：role=user/pet，text 为内容，ts 为时间戳。"""

    role: str
    text: str
    ts: float


@dataclass
class ShortMemory:
    """短期记忆：保留最近 N 轮，超出窗口自动裁掉。窗口大小由引擎确定。"""

    max_turns: int = DEFAULT_SHORT_MEMORY_TURNS
    turns: list[Turn] = field(default_factory=list)

    def add(self, role: str, text: str, now: float) -> None:
        """追加一轮并裁剪到窗口内。"""
        if role not in ("user", "pet"):
            raise ValueError(f"invalid role: {role!r}")
        self.turns.append(Turn(role=role, text=text, ts=now))
        if len(self.turns) > self.max_turns:
            # 丢掉最旧的一半，避免频繁整体搬家
            del self.turns[: len(self.turns) - self.max_turns]

    def recent(self, limit: int | None = None) -> list[Turn]:
        """返回最近 limit 轮（默认全部已保留轮）。"""
        if limit is None or limit >= len(self.turns):
            return list(self.turns)
        return list(self.turns[-limit:])

    def clear(self) -> None:
        self.turns.clear()


# ---------------- 主动说话调度 ----------------


@dataclass
class ProactiveScheduler:
    """主动说话调度器（确定性）。专注模式开启时永不主动说话。"""

    interval_sec: int = DEFAULT_PROACTIVE_INTERVAL_SEC
    focus_mode: bool = False
    last_spoke_at: float = field(default_factory=lambda: -DEFAULT_PROACTIVE_INTERVAL_SEC)

    def should_speak(self, now: float) -> bool:
        """到点且未专注就该主动说话一次。"""
        if self.focus_mode:
            return False
        return (now - self.last_spoke_at) >= self.interval_sec

    def on_spoke(self, now: float) -> None:
        """标记刚说过话，重置计时。"""
        self.last_spoke_at = now

    def toggle_focus(self) -> bool:
        """切换专注模式并返回新值。"""
        self.focus_mode = not self.focus_mode
        return self.focus_mode

    def next_speak_at(self, now: float) -> float:
        """下次可主动说话的时刻（用于前端展示倒计时）。"""
        if self.focus_mode:
            return float("inf")
        return self.last_spoke_at + self.interval_sec


# ---------------- 状态聚合 ----------------


@dataclass
class PetState:
    """聚合后的宠物状态，供后端序列化与前端驱动。"""

    mood: str
    intensity: float
    focus_mode: bool
    next_speak_at: float
    memory_size: int


def build_state(mood: MoodState, scheduler: ProactiveScheduler,
                memory: ShortMemory, now: float | None = None) -> PetState:
    """由各组件聚合出当前状态。now 缺省取当前时间。"""
    now = now if now is not None else time.time()
    return PetState(
        mood=mood.animation_mood(),
        intensity=round(mood.intensity, 3),
        focus_mode=scheduler.focus_mode,
        next_speak_at=scheduler.next_speak_at(now),
        memory_size=len(memory.turns),
    )


# ---------------- 模板兜底（LLM 不可用时） ----------------


def template_reply(personality: Personality, user_text: str) -> str:
    """LLM 不可用时的模板回复：仍然可读，不报错给孩子。"""
    echo = user_text.strip()[:20] if user_text else "你今天的状态"
    pick = int(time.time()) % len(personality.encourage_pool)
    return f"我听到啦——关于「{echo}」。{personality.encourage_pool[pick]}"


# ---------------- 运行时容器 ----------------


@dataclass
class PetRuntime:
    """宠物运行时：聚合引擎组件，按身份隔离。持久化由 engine.pet_store 负责。"""

    personality: Personality
    mood: MoodState
    memory: ShortMemory
    scheduler: ProactiveScheduler

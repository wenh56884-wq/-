# engine/agent_memory.py
# 职责：智能体长期记忆的持久化与向量检索（按租户 + 角色 + 主体严格隔离）。
# 依赖：scikit-learn HashingVectorizer / 标准库 json、math、pathlib（连接由调用方传入）。
# 说明：当前 LLM 只有 chat 接口、没有 embedding API，因此用 char 2-3 gram hashing
#       生成确定性稀疏向量；将来接入真 embedding 只需替换 embed() 与 VECTOR_DIM。

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

MEMORY_VERSION = "memory-v1"
VECTOR_DIM = 4096     # 512 维时中文 n-gram 哈希碰撞会让无关记忆误召回，提到 4096
DEDUP_SIMILARITY = 0.92
MIN_RECALL_SCORE = 0.05
MAX_CONTENT_CHARS = 500
_KINDS = ("fact", "preference", "goal", "constraint")

# 中文口语虚词不参与向量：不去掉的话「我的成绩怎么样」会和「我…的…」类记忆误撞。
# 只收多字短语 + 少量高频单字；专有名词（计算机/公务员/重庆）保持原样。
_STOP_PHRASES: tuple[str, ...] = (
    "我的", "我是", "我想", "我打算", "我希望", "帮我", "请问", "怎么", "怎么样",
    "什么", "哪些", "这个", "那个", "一下", "可以", "能不能", "有没有", "以及",
    "还有", "然后", "同时", "优先", "的", "了", "吗", "呢", "啊", "吧", "我", "你",
    "他", "她", "它", "在", "是", "和", "与", "及", "或", "想", "有",
)


def normalize_text(text: str) -> str:
    """记忆向量用的归一化：去空白与口语虚词，保留专业/方向/地名等实词。"""
    value = re.sub(r"\s+", "", str(text or ""))
    for phrase in sorted(_STOP_PHRASES, key=len, reverse=True):
        value = value.replace(phrase, "")
    return value or re.sub(r"\s+", "", str(text or ""))


@lru_cache(maxsize=1)
def _vectorizer():
    """固定维度的字符 n-gram hashing：无词表、跨进程稳定、完全离线。"""
    from sklearn.feature_extraction.text import HashingVectorizer

    return HashingVectorizer(
        n_features=VECTOR_DIM,
        analyzer="char",
        ngram_range=(2, 3),
        alternate_sign=False,
        norm="l2",
        dtype="float32",
    )


def embed(text: str) -> dict[str, list[float] | list[int]]:
    """文本 → 稀疏向量 {"i": 下标, "v": 权重}；空文本返回空向量。"""
    vec = _vectorizer().transform([normalize_text(text)]).tocoo()
    return {
        "i": [int(idx) for idx in vec.col],
        "v": [round(float(value), 6) for value in vec.data],
    }


def _dot(left: dict[str, Any], right: dict[str, Any]) -> float:
    """两个 l2 归一化稀疏向量的点积 = 余弦相似度。"""
    right_map = dict(zip(right.get("i") or [], right.get("v") or []))
    return float(sum(value * right_map.get(idx, 0.0)
                     for idx, value in zip(left.get("i") or [], left.get("v") or [])))


def _parse_vector(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def _split_sql(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def ensure_schema(conn) -> None:
    """建 `智能体记忆` 表（幂等）。"""
    sql_path = Path(__file__).resolve().parents[1] / "db" / "agent_memory.sql"
    with conn.cursor() as cur:
        for stmt in _split_sql(sql_path.read_text(encoding="utf-8")):
            cur.execute(stmt)


def _owner(ctx: Any) -> tuple[int, str, int]:
    """取记忆归属；缺少主体 id 直接拒绝（不写无主记忆）。"""
    actor_id = int((ctx.teacher_id if ctx.actor_type == "teacher"
                    else ctx.student_id) or 0)
    if not actor_id:
        raise ValueError("缺少主体编号，不能读写长期记忆")
    return int(ctx.tenant_id), str(ctx.actor_type), actor_id


def _clean_content(content: str) -> str:
    return re.sub(r"\s+", " ", str(content or "")).strip()[:MAX_CONTENT_CHARS]


def add(conn, ctx: Any, content: str, kind: str = "fact", importance: int = 3,
        session_id: int | None = None) -> tuple[int, bool]:
    """写一条记忆；与已有记忆高度相似时更新而不是重复插入。返回 (编号, 是否新建)。"""
    tenant, role, actor_id = _owner(ctx)
    text = _clean_content(content)
    if len(text) < 4:
        raise ValueError("记忆内容太短（至少 4 个字）")
    memory_kind = kind if kind in _KINDS else "fact"
    weight = max(1, min(int(importance or 3), 5))
    vector = embed(text)
    text_chars = set(normalize_text(text))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT `编号`, `内容`, `向量`, `重要度` FROM `智能体记忆` "
            "WHERE `租户编号`=%s AND `角色`=%s AND `主体编号`=%s AND `状态`='active' "
            "ORDER BY `编号` DESC LIMIT 2000",
            (tenant, role, actor_id),
        )
        best_id, best_score = 0, 0.0
        for row in cur.fetchall():
            old = _parse_vector(row.get("向量"))
            if not old:
                continue
            # 先看实词字符是否有交集，挡住哈希碰撞造成的「伪相似」
            if not (text_chars & set(normalize_text(row.get("内容") or ""))):
                continue
            score = _dot(vector, old)
            if score > best_score:
                best_id, best_score = int(row["编号"]), score
        if best_id and best_score >= DEDUP_SIMILARITY:
            cur.execute(
                "UPDATE `智能体记忆` SET `内容`=%s, `记忆类型`=%s, "
                "`重要度`=GREATEST(`重要度`, %s), `向量`=%s, `最近使用时间`=NOW() "
                "WHERE `编号`=%s AND `租户编号`=%s",
                (text, memory_kind, weight, json.dumps(vector, ensure_ascii=False),
                 best_id, tenant),
            )
            return best_id, False
        cur.execute(
            "INSERT INTO `智能体记忆` (`租户编号`,`角色`,`主体编号`,`记忆类型`,"
            "`内容`,`向量`,`来源会话`,`重要度`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant, role, actor_id, memory_kind, text,
             json.dumps(vector, ensure_ascii=False), session_id, weight),
        )
        return int(cur.lastrowid), True


def search(conn, ctx: Any, query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """按余弦相似度召回本人记忆；空查询/无记忆返回空列表。"""
    text = str(query or "").strip()
    if not text:
        return []
    tenant, role, actor_id = _owner(ctx)
    query_vec = embed(text)
    if not query_vec["i"]:
        return []
    query_chars = set(normalize_text(text))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `编号`, `记忆类型`, `内容`, `向量`, `重要度`, `使用次数` "
            "FROM `智能体记忆` WHERE `租户编号`=%s AND `角色`=%s AND `主体编号`=%s "
            "AND `状态`='active' ORDER BY `编号` DESC LIMIT 2000",
            (tenant, role, actor_id),
        )
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for row in cur.fetchall():
            vector = _parse_vector(row.get("向量"))
            if not vector:
                continue
            # 实词字符无交集直接跳过：哈希碰撞会让无关记忆拿到虚高分
            if not (query_chars & set(normalize_text(row.get("内容") or ""))):
                continue
            score = _dot(query_vec, vector)
            if score < MIN_RECALL_SCORE:
                continue
            scored.append((score, int(row.get("重要度") or 3), dict(row)))
        scored.sort(key=lambda item: (-item[0], -item[1], -int(item[2]["编号"])))
        top = scored[:max(1, min(int(top_k or 4), 10))]
        if top:
            ids = [int(item[2]["编号"]) for item in top]
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"UPDATE `智能体记忆` SET `使用次数`=`使用次数`+1, `最近使用时间`=NOW() "
                f"WHERE `租户编号`=%s AND `编号` IN ({placeholders})",
                [tenant, *ids],
            )
    return [
        {
            "id": int(row["编号"]),
            "kind": str(row.get("记忆类型") or "fact"),
            "content": str(row.get("内容") or ""),
            "importance": int(row.get("重要度") or 3),
            "score": round(score, 4),
        }
        for score, _importance, row in top
    ]


def list_memories(conn, ctx: Any, limit: int = 50) -> list[dict[str, Any]]:
    """列出本人记忆（按重要度、更新时间倒序）。"""
    tenant, role, actor_id = _owner(ctx)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `编号`, `记忆类型`, `内容`, `重要度`, `使用次数`, `创建时间` "
            "FROM `智能体记忆` WHERE `租户编号`=%s AND `角色`=%s AND `主体编号`=%s "
            "AND `状态`='active' ORDER BY `重要度` DESC, `编号` DESC LIMIT %s",
            (tenant, role, actor_id, max(1, min(int(limit or 50), 200))),
        )
        rows = list(cur.fetchall())
    return [dict(row) for row in rows]


def archive(conn, ctx: Any, memory_id: int) -> bool:
    """软删除本人一条记忆；返回是否真的改到了行。"""
    tenant, role, actor_id = _owner(ctx)
    with conn.cursor() as cur:
        changed = cur.execute(
            "UPDATE `智能体记忆` SET `状态`='archived' "
            "WHERE `编号`=%s AND `租户编号`=%s AND `角色`=%s AND `主体编号`=%s",
            (int(memory_id), tenant, role, actor_id),
        )
    return bool(changed)


def format_for_prompt(memories: list[dict[str, Any]]) -> str:
    """把召回记忆拼成提示词片段；明确标注「数字不得直接引用」。"""
    if not memories:
        return ""
    lines = ["【长期记忆（仅作背景；其中的数字不得直接引用，需要数字必须重新查工具）】"]
    for item in memories:
        lines.append(f"- [{item.get('kind')}] {item.get('content')}")
    return "\n".join(lines)

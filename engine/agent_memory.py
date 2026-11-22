# engine/agent_memory.py
# 职责：智能体长期记忆的持久化与向量检索（按租户 + 角色 + 主体严格隔离）。
# 依赖：scikit-learn HashingVectorizer / 标准库 json、math、pathlib（连接由调用方传入）。
# 说明：当前 LLM 只有 chat 接口、没有 embedding API，因此用 char 2-3 gram hashing
#       生成确定性稀疏向量；将来接入真 embedding 只需替换 embed() 与 VECTOR_DIM。

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

MEMORY_VERSION = "memory-v2"
VECTOR_DIM = 4096     # 512 维时中文 n-gram 哈希碰撞会让无关记忆误召回，提到 4096
DEDUP_SIMILARITY = 0.92
MIN_RECALL_SCORE = 0.05
MAX_CONTENT_CHARS = 500
# v2：召回分做 IDF 加权。哈希向量没有词表，也就没有全局 IDF，
# 但「这一批记忆里的 document frequency」是现成的——同一批最多 2000 条，
# 遍历一遍 feature 只多几十毫秒，却能把「我的」「想考」这类人人都有的特征压下去。
MEMORY_IDF = True
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


@lru_cache(maxsize=2048)
def _embed_cached(norm_text: str) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """归一化文本 → (下标, 权重)。同一句话在一次会话里通常要算好几遍
    （召回一次、去重一次、审计一次），缓存成不可变 tuple，命中时再复制成 list。
    """
    vec = _vectorizer().transform([norm_text]).tocoo()
    return tuple(int(i) for i in vec.col), tuple(round(float(v), 6) for v in vec.data)


def embed(text: str) -> dict[str, list[float] | list[int]]:
    """文本 → 稀疏向量 {"i": 下标, "v": 权重}；空文本返回空向量。"""
    idx, val = _embed_cached(normalize_text(text))
    return {"i": list(idx), "v": list(val)}


def _dot(left: dict[str, Any], right: dict[str, Any]) -> float:
    """两个 l2 归一化稀疏向量的点积 = 余弦相似度。"""
    right_map = dict(zip(right.get("i") or [], right.get("v") or []))
    return float(sum(value * right_map.get(idx, 0.0)
                     for idx, value in zip(left.get("i") or [], left.get("v") or [])))


def _idf_weight(vectors: Sequence[Mapping[str, Any]]) -> dict[int, float]:
    """这一批记忆的特征 IDF：log((N+1)/(df+0.5))，df 为出现该特征的记忆条数。

    哈希维度是固定的，但「哪些维度在这批记忆里稀有」是可统计的。
    稀有特征（「重庆」「公务员」）权重高，人人都有的特征（「我的」「想考」）
    权重趋近 0——这正好补上哈希向量没有 IDF 的短板。
    """
    total = len(vectors)
    df: dict[int, int] = {}
    for vec in vectors:
        for idx in set(vec.get("i") or []):
            df[int(idx)] = df.get(int(idx), 0) + 1
    return {idx: math.log((total + 1) / (count + 0.5)) for idx, count in df.items()}


def _query_coverage(query_vec: Mapping[str, Any], memory_vec: Mapping[str, Any],
                    idf: Mapping[int, float], unknown: float) -> float:
    """查询特征有多少被这条记忆覆盖（IDF 加权），**只看查询侧特征**。

    为什么不用对称余弦：查询往往十几个字、记忆是整句，长度差一个量级，
    余弦天然偏低，「考公 重庆 岗位」这种短问法会被判成不相关。
    覆盖率是个非对称指标——分母只算查询里的特征，短查询也能如实反映命中度。
    """
    q_idx = {int(i) for i in (query_vec.get("i") or [])}
    if not q_idx:
        return 0.0
    m_idx = {int(i) for i in (memory_vec.get("i") or [])}
    total = sum(idf.get(i, unknown) for i in q_idx) or 1.0
    hit = sum(idf.get(i, unknown) for i in q_idx & m_idx)
    return hit / total


def _importance_factor(importance: int) -> float:
    """重要度加权：3 分不动，5 分 ×1.04，1 分 ×0.96。

    只做微调不做主导——同等相关时让用户标过「重要」的那条排前面，
    但绝不能靠重要度把不相关内容顶上来。
    """
    return 1.0 + 0.02 * (max(1, min(int(importance or 3), 5)) - 3)


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
        rows = list(cur.fetchall())
        # 去重保持对称余弦：阈值 0.92 的语义是「几乎是同一句话」，
        # 换成覆盖率会让「包含关系」的句子被误合并（长短句覆盖率高但并非同义）
        best_id, best_score = 0, 0.0
        for row in rows:
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
    """召回本人记忆：0.65×余弦 + 0.35×查询覆盖率，再乘重要度微调。

    改的是召回口径，不改存储：向量仍由 HashingVectorizer 离线生成，
    旧数据不用重建——新分数是「怎么用这堆向量」的事。
    """
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
        rows = list(cur.fetchall())
        stored = [_parse_vector(row.get("向量")) for row in rows]
        vectors = [v for v in stored if v]
        idf = _idf_weight(vectors + [query_vec]) if MEMORY_IDF else {}
        unknown = (max(idf.values()) if idf else 1.0)
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for row, vector in zip(rows, stored):
            if not vector:
                continue
            # 实词字符无交集直接跳过：哈希碰撞会让无关记忆拿到虚高分
            if not (query_chars & set(normalize_text(row.get("内容") or ""))):
                continue
            cosine = _dot(query_vec, vector)
            coverage = _query_coverage(query_vec, vector, idf, unknown)
            base = 0.65 * cosine + 0.35 * coverage
            importance = int(row.get("重要度") or 3)
            score = base * _importance_factor(importance)
            if score < MIN_RECALL_SCORE:
                continue
            scored.append((score, importance, dict(row)))
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

# engine/pet_store.py
# 职责：AI 宠物运行时与对话记忆的 MySQL 持久化——序列化/反序列化，纯确定性数据存取。
# 铁律落地：铁律 1（不涉及 LLM，纯数据存取）；铁律 3（按身份编号隔离，租户编号冗余存储）。
# 依赖：pymysql（连接由调用方传入）；engine.pet 的数据类（Turn / PetRuntime）；
#       engine.agent_memory 的向量器（长期记忆去重，完全离线、无 LLM）。

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from engine import agent_memory
from engine.pet import Turn

_SQL_PATH = Path(__file__).resolve().parents[1] / "db" / "pet_memory.sql"


def _split_sql(text: str) -> list[str]:
    """拆分 SQL 文件：去注释行、按 ; 切分。"""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def ensure_schema(conn) -> None:
    """建宠物表（幂等）；为旧表补 鼓励池JSON / 向量 列（迁移）。"""
    with conn.cursor() as cur:
        for stmt in _split_sql(_SQL_PATH.read_text(encoding="utf-8")):
            cur.execute(stmt)
    # 迁移：旧环境 宠物人格 表无 鼓励池JSON 列，补上
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM `宠物人格` LIKE '鼓励池JSON'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE `宠物人格` ADD COLUMN "
                "`鼓励池JSON` JSON NULL DEFAULT NULL COMMENT '鼓励语池（最多 10 条）'"
            )
    # 迁移：旧环境 宠物长期记忆 表无 向量 列，补上（长期记忆去重用）
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM `宠物长期记忆` LIKE '向量'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE `宠物长期记忆` ADD COLUMN "
                "`向量` JSON NULL COMMENT '内容稀疏向量（agent_memory.embed 格式，去重与编辑后重算）'"
            )
    conn.commit()


def _parse_vector(raw: Any) -> dict[str, Any] | None:
    """向量列 JSON → 稀疏向量；空/坏数据返回 None。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def _cosine(left: dict[str, Any], right: dict[str, Any]) -> float:
    """两个 l2 归一化稀疏向量的点积 = 余弦相似度（与 agent_memory._dot 同式）。"""
    right_map = dict(zip(right.get("i") or [], right.get("v") or []))
    return float(sum(value * right_map.get(idx, 0.0)
                     for idx, value in zip(left.get("i") or [], left.get("v") or [])))


def _clean_long_text(content: str) -> str:
    """长期记忆入库文本：压空白；空串拒绝由调用方处理。"""
    return re.sub(r"\s+", " ", str(content or "")).strip()


# ---------------- 运行时 ----------------


def load_runtime(conn, identity: int) -> dict[str, Any] | None:
    """加载运行时状态；不存在返回 None。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `心情`, `强度`, `上次互动时间`, `专注模式`, `上次说话时间`, "
            "`主动间隔秒`, `人格名字` FROM `宠物运行时` WHERE `身份编号` = %s",
            (identity,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "mood": row["心情"],
        "intensity": float(row["强度"]),
        "last_interact_at": float(row["上次互动时间"]),
        "focus_mode": bool(row["专注模式"]),
        "last_spoke_at": float(row["上次说话时间"]),
        "interval_sec": int(row["主动间隔秒"]),
        "name": row["人格名字"],
    }


def save_runtime(conn, identity: int, tenant_id: int, rt) -> None:
    """写入/更新运行时状态（INSERT ... ON DUPLICATE KEY UPDATE）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO `宠物运行时` "
            "(`身份编号`, `租户编号`, `心情`, `强度`, `上次互动时间`, `专注模式`, "
            "`上次说话时间`, `主动间隔秒`, `人格名字`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "`租户编号`=VALUES(`租户编号`), `心情`=VALUES(`心情`), `强度`=VALUES(`强度`), "
            "`上次互动时间`=VALUES(`上次互动时间`), `专注模式`=VALUES(`专注模式`), "
            "`上次说话时间`=VALUES(`上次说话时间`), `主动间隔秒`=VALUES(`主动间隔秒`), "
            "`人格名字`=VALUES(`人格名字`)",
            (
                identity, tenant_id,
                rt.mood.mood, float(rt.mood.intensity), float(rt.mood.last_interact_at),
                1 if rt.scheduler.focus_mode else 0,
                float(rt.scheduler.last_spoke_at), int(rt.scheduler.interval_sec),
                rt.personality.name,
            ),
        )
    conn.commit()


# ---------------- 记忆 ----------------


def load_memory(conn, identity: int, limit: int) -> list[Turn]:
    """加载最近 limit 轮（按时间正序返回，供 ShortMemory 重建）。"""
    with conn.cursor() as cur:
        # 倒序取 limit，再在内存里正序还原
        cur.execute(
            "SELECT `角色`, `文本`, `创建时间` FROM `宠物记忆` "
            "WHERE `身份编号` = %s ORDER BY `创建时间` DESC LIMIT %s",
            (identity, limit),
        )
        rows = list(cur.fetchall())
    rows.reverse()
    return [Turn(role=r["角色"], text=r["文本"], ts=float(r["创建时间"])) for r in rows]


def add_memory(conn, identity: int, tenant_id: int, role: str, text: str, now: float) -> None:
    """追加一轮记忆。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO `宠物记忆` (`身份编号`, `租户编号`, `角色`, `文本`, `创建时间`) "
            "VALUES (%s, %s, %s, %s, %s)",
            (identity, tenant_id, role, text, now),
        )
    conn.commit()


def trim_memory(conn, identity: int, keep: int) -> int:
    """裁剪记忆，保留最近 keep 轮。返回删除行数。

    MySQL 不允许 DELETE 直接对同表用子查询，故用派生表包一层。
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM `宠物记忆` WHERE `身份编号` = %s AND `编号` NOT IN "
            "(SELECT `编号` FROM (SELECT `编号` FROM `宠物记忆` WHERE `身份编号` = %s "
            "ORDER BY `创建时间` DESC LIMIT %s) AS keep_ids)",
            (identity, identity, keep),
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted


# ---------------- 人格 ----------------


def load_personality(conn, identity: int) -> dict[str, Any] | None:
    """加载人格配置；不存在返回 None。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `名字`, `物种`, `语气`, `问候语`, `鼓励池JSON` FROM `宠物人格` WHERE `身份编号` = %s",
            (identity,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "name": row["名字"],
        "species": row["物种"],
        "tone": row["语气"],
        "greeting": row["问候语"],
        "encourage": json.loads(row["鼓励池JSON"]) if row["鼓励池JSON"] else [],
    }


def save_personality(conn, identity: int, tenant_id: int, p) -> None:
    """写入/更新人格配置（INSERT ... ON DUPLICATE KEY UPDATE）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO `宠物人格` "
            "(`身份编号`, `租户编号`, `名字`, `物种`, `语气`, `问候语`, `鼓励池JSON`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
            "`租户编号`=VALUES(`租户编号`), `名字`=VALUES(`名字`), `物种`=VALUES(`物种`), "
            "`语气`=VALUES(`语气`), `问候语`=VALUES(`问候语`), `鼓励池JSON`=VALUES(`鼓励池JSON`)",
            (identity, tenant_id, p.name, p.species, p.tone, p.greeting,
             json.dumps(list(p.encourage_pool), ensure_ascii=False)),
        )
    conn.commit()


# ---------------- 长期记忆 ----------------


def load_long_memories(conn, identity: int, limit: int = 5) -> list[dict[str, Any]]:
    """加载长期记忆（按重要度倒序 + 时间倒序，取 limit 条）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `编号`, `内容`, `类型`, `重要度`, `创建时间` FROM `宠物长期记忆` "
            "WHERE `身份编号` = %s ORDER BY `重要度` DESC, `创建时间` DESC LIMIT %s",
            (identity, limit),
        )
        rows = list(cur.fetchall())
    return [{"id": int(r["编号"]), "content": r["内容"], "kind": r["类型"],
             "importance": int(r["重要度"])} for r in rows]


def add_long_memory(conn, identity: int, tenant_id: int, content: str,
                    kind: str = "fact", importance: int = 3, now: float = 0.0) -> int:
    """追加一条长期记忆；与已有记忆高度相似时更新原行而不是重复插入。

    去重完全离线：agent_memory.embed 稀疏向量 + 余弦相似度（阈值同主智能体），
    另用实词字符交集前置挡哈希碰撞造成的「伪相似」。返回命中的记忆编号。
    """
    text = _clean_long_text(content)
    if not text:
        return 0
    vector = agent_memory.embed(text)
    vector_json = json.dumps(vector, ensure_ascii=False)
    text_chars = set(agent_memory.normalize_text(text))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT `编号`, `内容`, `向量` FROM `宠物长期记忆` WHERE `身份编号` = %s",
            (identity,),
        )
        best_id, best_score = 0, 0.0
        for row in cur.fetchall():
            old = _parse_vector(row.get("向量"))
            if not old:
                continue
            if not (text_chars & set(agent_memory.normalize_text(row.get("内容") or ""))):
                continue
            score = _cosine(vector, old)
            if score > best_score:
                best_id, best_score = int(row["编号"]), score
        if best_id and best_score >= agent_memory.DEDUP_SIMILARITY:
            cur.execute(
                "UPDATE `宠物长期记忆` SET `内容` = %s, `向量` = %s, "
                "`重要度` = GREATEST(`重要度`, %s) WHERE `编号` = %s AND `身份编号` = %s",
                (text, vector_json, max(1, min(int(importance or 3), 5)), best_id, identity),
            )
            conn.commit()
            return best_id
        cur.execute(
            "INSERT INTO `宠物长期记忆` "
            "(`身份编号`, `租户编号`, `内容`, `类型`, `重要度`, `创建时间`, `向量`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (identity, tenant_id, text, kind, max(1, min(int(importance or 3), 5)), now, vector_json),
        )
        new_id = cur.lastrowid
    conn.commit()
    return int(new_id)


def update_long_memory(conn, identity: int, memory_id: int, content: str) -> bool:
    """编辑一条长期记忆的文本（重算向量）；只能改本人（身份编号）的行。"""
    text = _clean_long_text(content)
    if not text:
        return False
    vector_json = json.dumps(agent_memory.embed(text), ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE `宠物长期记忆` SET `内容` = %s, `向量` = %s "
            "WHERE `编号` = %s AND `身份编号` = %s",
            (text, vector_json, memory_id, identity),
        )
        changed = cur.rowcount
    conn.commit()
    return changed > 0


def delete_long_memory(conn, identity: int, memory_id: int) -> bool:
    """删除一条长期记忆；只能删本人（身份编号）的行。"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM `宠物长期记忆` WHERE `编号` = %s AND `身份编号` = %s",
            (memory_id, identity),
        )
        changed = cur.rowcount
    conn.commit()
    return changed > 0


def trim_long_memories(conn, identity: int, keep: int) -> int:
    """保留重要度最高 + 最新 keep 条。返回删除行数。"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM `宠物长期记忆` WHERE `身份编号` = %s AND `编号` NOT IN "
            "(SELECT `编号` FROM (SELECT `编号` FROM `宠物长期记忆` WHERE `身份编号` = %s "
            "ORDER BY `重要度` DESC, `创建时间` DESC LIMIT %s) AS keep_ids)",
            (identity, identity, keep),
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted

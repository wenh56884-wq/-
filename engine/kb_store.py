# engine/kb_store.py
# 职责：知识库的取数口径——路由与对话工具共用同一套 SQL，避免两处检索结果不一致。
# 说明：只做「取块 + 检索」，不建连接（连接由调用方按自己的事务语义管理）。

from __future__ import annotations

from typing import Any

from engine import rag

_CHUNK_SQL = (
    "SELECT c.`编号` AS chunk_id, c.`文档编号` AS doc_id, d.`标题` AS title,"
    " c.`块号` AS chunk_no, c.`页码` AS page, c.`文本` AS text"
    " FROM `知识库分块` c JOIN `知识库文档` d ON d.`编号`=c.`文档编号`"
    " WHERE d.`租户编号`=%s AND d.`状态`='ready'"
)


def fetch_chunks(conn, tenant_id: int, doc_id: int | None = None) -> list[dict[str, Any]]:
    """取本租户全部可检索分块（可按文档过滤）。"""
    sql = _CHUNK_SQL
    params: list[Any] = [int(tenant_id)]
    if doc_id:
        sql += " AND d.`编号`=%s"
        params.append(int(doc_id))
    sql += " ORDER BY c.`文档编号`, c.`块号`"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return list(cur.fetchall())


def search(conn, tenant_id: int, query: str, top_k: int = 4,
           doc_id: int | None = None) -> list[dict[str, Any]]:
    """检索：返回块级命中（含页码），空列表表示知识库里确实没有。"""
    return rag.search(query, fetch_chunks(conn, tenant_id, doc_id), top_k=top_k)

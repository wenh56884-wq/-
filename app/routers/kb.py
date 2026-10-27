# app/routers/kb.py
# 职责：企业知识库 + PDF 文档问答的接口——上传入库、列表、删除、检索、分块查看。
# 鉴权：登录用户都可读；上传/删除限教师（学生只能查，不能改知识库内容）。
# 铁律：
#   1. 入库前先抽文本；抽不出字（如扫描件 PDF）直接拒收并说明原因，不入一个空文档。
#   2. 同租户同内容哈希只入库一次，重复上传返回已存在的那份，不产生重复引用。
#   3. 检索只返回真实分块，附带文档名/页码/块号，回答侧引用必须能回到这里。

from __future__ import annotations

import json
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.audit import audit_event
from app.auth import get_current_ctx, require_teacher
from app.config import get_settings
from engine import kb_store, rag
from agents.tools import ToolContext

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _rows(cur, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return list(cur.fetchall())


def _one(cur, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    cur.execute(sql, params)
    return cur.fetchone()


def _owner(ctx: ToolContext) -> tuple[str, int | None]:
    if ctx.actor_type == "teacher":
        return "teacher", ctx.teacher_id
    return "student", ctx.student_id


def _chunk_rows(ctx: ToolContext, doc_id: int | None = None) -> list[dict[str, Any]]:
    """取本租户的检索底表（块 + 文档标题）。doc_id 给了就只取那份文档。"""
    conn = _conn()
    try:
        return kb_store.fetch_chunks(conn, ctx.tenant_id, doc_id)
    finally:
        conn.close()


def search_knowledge(ctx: ToolContext, query: str, top_k: int = 4,
                     doc_id: int | None = None) -> list[dict[str, Any]]:
    """供对话工具与接口共用：返回带页码的块级命中（空列表 = 没查到）。"""
    conn = _conn()
    try:
        return kb_store.search(conn, ctx.tenant_id, query, top_k=top_k, doc_id=doc_id)
    finally:
        conn.close()


class TextIn(BaseModel):
    """粘贴文本入库（md/txt），或登记一条 URL 来源的正文。"""

    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    source_type: str = Field(default="txt", pattern="^(md|txt|url)$")
    source_url: str | None = None


def _persist(ctx: ToolContext, title: str, filename: str | None, source_type: str,
             source_url: str | None, blob: bytes, pages: list[tuple[int | None, str]]) -> dict[str, Any]:
    """把抽取好的页文本切块入库；重复内容直接返回既有文档。"""
    chunks = rag.chunk_pages(pages)
    if not chunks:
        raise HTTPException(422, "文档里没有可抽取的文字（可能是扫描件或空文件），请先转成可复制文本")
    digest = rag.sha256(blob)
    role, actor = _owner(ctx)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            exist = _one(cur, "SELECT `编号`,`标题`,`分块数` FROM `知识库文档`"
                              " WHERE `租户编号`=%s AND `内容哈希`=%s", (ctx.tenant_id, digest))
            if exist:
                return {"doc_id": int(exist["编号"]), "title": exist["标题"],
                        "chunks": int(exist["分块数"]), "duplicated": True}
            cur.execute(
                "INSERT INTO `知识库文档`(`租户编号`,`标题`,`文件名`,`来源类型`,`来源地址`,`内容哈希`,"
                "`字节数`,`页数`,`分块数`,`状态`,`上传人角色`,`上传人编号`)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready',%s,%s)",
                (ctx.tenant_id, title[:200], filename, source_type, source_url, digest,
                 len(blob), len(pages), len(chunks), role, actor))
            doc_id = int(cur.lastrowid)
            cur.executemany(
                "INSERT INTO `知识库分块`(`文档编号`,`块号`,`页码`,`文本`,`字数`,`关键词`)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                [(doc_id, c.chunk_no, c.page, c.text, len(c.text),
                  json.dumps(rag.keywords_of(c.text), ensure_ascii=False)) for c in chunks])
        conn.commit()
        audit_event(actor_type=role, actor_id=actor or 0, action="kb.ingest",
                    target=str(doc_id), detail={"title": title[:60], "chunks": len(chunks),
                                                "type": source_type})
        return {"doc_id": doc_id, "title": title, "chunks": len(chunks), "duplicated": False}
    finally:
        conn.close()


@router.post("/docs")
async def upload_doc(file: UploadFile = File(...), title: str | None = None,
                     ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """上传 PDF / DOCX / MD / TXT 入库。文件名类型不在白名单 → 415。"""
    name = file.filename or ""
    source_type = rag.detect_type(name)
    if source_type is None:
        raise HTTPException(415, "只支持 PDF / DOCX / MD / TXT")
    blob = await file.read()
    if not blob:
        raise HTTPException(422, "文件是空的")
    if len(blob) > rag.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件超过 {rag.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    try:
        pages = rag.extract_pages(blob, source_type)
    except Exception as exc:
        raise HTTPException(422, f"解析失败：{exc}") from exc
    doc_title = (title or name.rsplit(".", 1)[0]).strip()[:200] or "未命名文档"
    return _persist(ctx, doc_title, name, source_type, None, blob, pages)


@router.post("/docs/text")
def upload_text(inp: TextIn, ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """粘贴正文入库（制度、SOP、FAQ 都走这条），也用于登记网页正文。"""
    blob = inp.text.encode("utf-8")
    if len(blob) > rag.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文本过长")
    pages = rag.extract_pages(blob, inp.source_type)
    return _persist(ctx, inp.title, None, inp.source_type, inp.source_url, blob, pages)


@router.get("/docs")
def list_docs(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            rows = _rows(cur, "SELECT `编号` AS id,`标题` AS title,`文件名` AS filename,"
                              "`来源类型` AS source_type,`页数` AS pages,`分块数` AS chunks,"
                              "`字节数` AS bytes,`状态` AS status,`创建时间` AS created_at"
                              " FROM `知识库文档` WHERE `租户编号`=%s ORDER BY `编号` DESC",
                         (ctx.tenant_id,))
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """删文档连带删分块：删完立刻检索不到，不留孤儿引用。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            doc = _one(cur, "SELECT `编号` FROM `知识库文档` WHERE `编号`=%s AND `租户编号`=%s",
                       (doc_id, ctx.tenant_id))
            if not doc:
                raise HTTPException(404, "文档不存在")
            cur.execute("DELETE FROM `知识库分块` WHERE `文档编号`=%s", (doc_id,))
            cur.execute("DELETE FROM `知识库文档` WHERE `编号`=%s", (doc_id,))
        conn.commit()
        audit_event(actor_type="teacher", actor_id=ctx.teacher_id or 0, action="kb.delete",
                    target=str(doc_id))
        return {"deleted": doc_id}
    finally:
        conn.close()


@router.get("/docs/{doc_id}/chunks")
def doc_chunks(doc_id: int, limit: int = 50, offset: int = 0,
               ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            doc = _one(cur, "SELECT `编号`,`标题` FROM `知识库文档`"
                            " WHERE `编号`=%s AND `租户编号`=%s", (doc_id, ctx.tenant_id))
            if not doc:
                raise HTTPException(404, "文档不存在")
            rows = _rows(cur, "SELECT `块号` AS chunk_no,`页码` AS page,`文本` AS text,`字数` AS words"
                              " FROM `知识库分块` WHERE `文档编号`=%s"
                              " ORDER BY `块号` LIMIT %s OFFSET %s",
                         (doc_id, max(1, min(limit, 200)), max(0, offset)))
        return {"title": doc["标题"], "items": rows}
    finally:
        conn.close()


@router.get("/search")
def search(q: str, top_k: int = 4, doc_id: int | None = None,
           ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """检索（调试与前端引用面板共用）。命中为空时明确返回 0，不拼凑结果。"""
    hits = search_knowledge(ctx, q, top_k=max(1, min(top_k, 12)), doc_id=doc_id)
    return {"query": q, "total": len(hits), "citations": rag.as_citations(hits), "hits": hits}


@router.get("/stats")
def stats(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            doc = _one(cur, "SELECT COUNT(*) AS docs, COALESCE(SUM(`分块数`),0) AS chunks,"
                            " COALESCE(SUM(`页数`),0) AS pages, COALESCE(SUM(`字节数`),0) AS bytes"
                            " FROM `知识库文档` WHERE `租户编号`=%s AND `状态`='ready'",
                       (ctx.tenant_id,)) or {}
            by_type = _rows(cur, "SELECT `来源类型` AS type, COUNT(*) AS cnt FROM `知识库文档`"
                                 " WHERE `租户编号`=%s GROUP BY `来源类型` ORDER BY cnt DESC",
                            (ctx.tenant_id,))
        return {"engine_version": rag.RAG_VERSION, "docs": int(doc.get("docs") or 0),
                "chunks": int(doc.get("chunks") or 0), "pages": int(doc.get("pages") or 0),
                "bytes": int(doc.get("bytes") or 0),
                "by_type": {r["type"]: int(r["cnt"]) for r in by_type}}
    finally:
        conn.close()

"""engine/competition.py
职责：把「该参加哪些比赛」做成确定性规则——不调大模型、不用随机数、同输入必同输出。

数据来源：重庆财经学院教务处公布的《学科竞赛计划项目》名单 + 栏目页最新通知（官方原文入库）。
匹配规则（全部可解释，输出里带 match_reason）：
  1. 去向：考公 / 就业，按学生自己的目标选；「通用」类降权参与，「文体」类不参与。
  2. 标签：比赛自带标签与「岗位方向 + 岗位标题 + 待补技能」做包含匹配，命中即加权。
  3. 权重：学校认定类别 A > B > C > D（A 类为学校重点资助赛事）。
  4. 排序：得分降序 → 类别 → id，保证稳定。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

import pymysql

from app.config import Settings, get_settings

COMPETITION_ENGINE_VERSION = "competition-v1"

# 学校认定类别权重（A 类为学校重点，D 类为一般）
CATEGORY_WEIGHT: dict[str, float] = {"A": 1.0, "B": 0.8, "C": 0.7, "D": 0.5}
# 去向权重：主目标 > 通用 > 非目标
TRACK_WEIGHT: dict[str, float] = {"main": 1.0, "通用": 0.6, "other": 0.0}
# 标签命中加分
TAG_HIT_SCORE = 0.6


def _connect(settings: Settings | None = None) -> pymysql.connections.Connection:
    s = settings or get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=5)


def _query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError):
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError):
        return []
    finally:
        conn.close()


def _execute(sql: str, params: Sequence[Any] = ()) -> int:
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError):
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
        conn.commit()
        return 1
    except (pymysql.MySQLError, OSError):
        return 0
    finally:
        conn.close()


def _tags(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(t) for t in raw]
    try:
        data = json.loads(str(raw or "[]"))
    except (ValueError, TypeError):
        return []
    return [str(t) for t in data] if isinstance(data, list) else []


def _keywords(direction: str, job_title: str, gap_skills: Sequence[str]) -> list[str]:
    """参与匹配的关键词：方向名 + 岗位标题里的方向词 + 待补技能。"""
    words: list[str] = []
    if direction:
        words.append(str(direction))
    for text in [str(job_title or "")] + [str(s) for s in gap_skills or []]:
        for token in str(text).replace("、", " ").replace("/", " ").split():
            token = token.strip()
            if len(token) >= 2:
                words.append(token)
    # 去重复、保序
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return seen


def _hit_tags(tags: Sequence[str], keywords: Sequence[str]) -> list[str]:
    """标签命中：标签里含关键词，或关键词里含标签（双向包含，短词也认）。"""
    hits: list[str] = []
    for tag in tags:
        for word in keywords:
            if tag and word and (tag in word or word in tag):
                hits.append(tag)
                break
    return hits


def score_competition(row: Mapping[str, Any], track: str,
                      keywords: Sequence[str]) -> dict[str, Any] | None:
    """单条竞赛打分；非目标去向（文体等）返回 None 表示不推荐。"""
    name = str(row.get("name") or "")
    category = str(row.get("category") or "").upper()
    row_track = str(row.get("track") or "")
    tags = _tags(row.get("tags_json"))

    if row_track == "文体":
        return None
    if row_track == track:
        track_score = TRACK_WEIGHT["main"]
        track_desc = f"面向{track}"
    elif row_track == "通用":
        track_score = TRACK_WEIGHT["通用"]
        track_desc = f"通用类赛事，{track}同样用得上"
    else:
        return None  # 另一条去向的专项赛不混入，避免答非所问

    hits = _hit_tags(tags, keywords)
    name_hit = any(word and word in name for word in keywords)
    tag_score = TAG_HIT_SCORE if hits else (0.3 if name_hit else 0.0)
    total = round(track_score + tag_score + CATEGORY_WEIGHT.get(category, 0.5), 4)

    if hits:
        reason = f"{track_desc}；匹配你的{'、'.join(hits[:2])}方向"
    elif name_hit:
        reason = f"{track_desc}；赛事内容与目标岗位相关"
    else:
        reason = f"{track_desc}；{category} 类校级重点赛事"

    return {
        "competition_id": int(row.get("id") or 0),
        "name": name,
        "category": category,
        "org_unit": str(row.get("org_unit") or ""),
        "track": row_track,
        "tags": tags,
        "reward": str(row.get("reward") or ""),
        "source_title": str(row.get("source_title") or ""),
        "source_url": str(row.get("source_url") or ""),
        "published_at": str(row.get("published_at") or ""),
        "score": total,
        "match_reason": reason,
    }


def recommend_competitions(track: str = "就业", direction: str = "",
                           job_title: str = "", gap_skills: Sequence[str] = (),
                           limit: int = 8) -> dict[str, Any]:
    """按去向 + 岗位方向推荐比赛：纯规则、确定性排序。"""
    track = "考公" if str(track or "").strip() == "考公" else "就业"
    keywords = _keywords(direction, job_title, gap_skills)
    rows = _query(
        "SELECT `编号` AS id, `竞赛名称` AS name, `类别` AS category, "
        "       `组织单位` AS org_unit, `去向` AS track, `标签` AS tags_json, "
        "       `奖励方案` AS reward, `来源标题` AS source_title, "
        "       `来源链接` AS source_url, `发布日期` AS published_at "
        "FROM `竞赛` ORDER BY `编号`",
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        item = score_competition(row, track, keywords)
        if item:
            scored.append(item)
    scored.sort(key=lambda x: (-x["score"], x["category"], x["competition_id"]))
    items = scored[: max(1, int(limit))]
    return {
        "engine_version": COMPETITION_ENGINE_VERSION,
        "track": track,
        "direction": str(direction or ""),
        "candidate_cnt": len(scored),
        "items": items,
        "note": "数据来自重庆财经学院教务处公布的学科竞赛计划项目名单，每条附官方通知链接可核对",
    }


def unread_notices(student_no: str, tenant_id: int, limit: int = 20) -> dict[str, Any]:
    """未读推送：id 大于水位的通知即未读（含考证提醒，id 带 10^9 偏移）。

    水位用自增 id 而非时间，避免同一秒内发布的新通知被漏掉。
    """
    from engine import cert_guide as cert_engine

    rows = _query(
        "SELECT `已读通知编号` AS last_notice_id, `最后已读时间` AS last_read_at "
        "FROM `学生通知已读` WHERE `租户编号` = %s AND `学号` = %s",
        (int(tenant_id), str(student_no)),
    )
    watermark = int((rows[0] or {}).get("last_notice_id") or 0) if rows else 0
    notices = _query(
        "SELECT `编号` AS id, `标题` AS title, `发布日期` AS published_at, "
        "       `链接` AS url, `来源` AS source, `抓取时间` AS fetched_at "
        "FROM `竞赛通知` "
        "WHERE `编号` > %s ORDER BY `发布日期` DESC, `编号` DESC LIMIT %s",
        (watermark, int(limit)),
    )
    total = _query(
        "SELECT COUNT(*) AS n FROM `竞赛通知` WHERE `编号` > %s", (watermark,))
    comp_unread = int((total[0] or {}).get("n") or 0) if total else len(notices)
    for notice in notices:
        fetched = notice.get("fetched_at")
        notice["fetched_at"] = fetched.strftime("%Y-%m-%d %H:%M:%S") if isinstance(
            fetched, datetime) else (str(fetched) if fetched else "")
    merged = cert_engine.merge_notices(notices, watermark, limit=limit)
    return {
        "student_no": str(student_no),
        "last_notice_id": watermark,
        "last_read_at": str((rows[0] or {}).get("last_read_at") or "") if rows else "",
        "unread_cnt": comp_unread + int(merged.get("cert_unread_cnt") or 0),
        "items": merged.get("items") or [],
    }


def mark_read(student_no: str, tenant_id: int) -> dict[str, Any]:
    """把水位推到当前最大通知 id（含考证提醒）：之后的新通知才会再次提醒。

    考证提醒的 id 按阶段递增（报名中 → 临近考试），推到当前活跃提醒的最大 id，
    下一阶段 id 更大，到点仍会再提醒。
    """
    from engine import cert_guide as cert_engine

    rows = _query("SELECT COALESCE(MAX(`编号`), 0) AS max_id FROM `竞赛通知`")
    max_id = int((rows[0] or {}).get("max_id") or 0) if rows else 0
    cert_max = cert_engine.watermark_max()
    watermark = max(max_id, cert_max)
    _execute(
        "INSERT INTO `学生通知已读` (`学号`, `租户编号`, `已读通知编号`, `最后已读时间`) "
        "VALUES (%s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE "
        "`已读通知编号` = VALUES(`已读通知编号`), `最后已读时间` = NOW()",
        (str(student_no), int(tenant_id), watermark),
    )
    return {"student_no": str(student_no), "last_notice_id": watermark, "marked": True}

"""engine/cert_guide.py
职责：大学生考证推荐——确定性规则引擎，不调大模型、不用随机数，同输入必同输出。

数据来源：db/cert_tables.sql 种子（官方公告逐条核实入库，每条带来源链接与核实日期）。
能力边界（对外承诺）：
  1. 目录 + 状态：每本证书算出「报名中 / 未开始 / 已截止 / 常年可报」，日期来自官方公告；
  2. 个性化推荐：按去向 + 专业 + 年级 + 已持有证书打分，理由全部可解释（match_reasons）；
  3. 差距分析：只说事实——前提条件里学生还不满足的项、同方向常见的下一本证书；
     不编造学生已有证书，数据里没有就明说「档案里未登记证书」；
  4. 通知提醒：报名中 / 临近考试（≤14 天）的证书生成提醒条目，复用竞赛通知的已读水位。

铁律：日期未公布的批次一律标「预计」并在文案里说明依据，不把猜测说成官方日期。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Sequence

import pymysql

from app.config import get_settings

CERT_ENGINE_VERSION = "cert-v1"

# 考证提醒并入竞赛通知的已读水位：id = OFFSET + 编号*100 + 阶段（0=报名中,1=临近考试）。
# 偏移量要远大于竞赛通知的自增上限（竞赛通知仅数十条）。
CERT_ID_OFFSET = 1_000_000_000
REMIND_EXAM_DAYS = 14          # 考试前多少天开始提醒「准考证打印」
PHASE_UPCOMING = 0   # 即将开放报名（时间最早，id 最小）
PHASE_ENROLL = 1     # 报名中
PHASE_EXAM = 2       # 临近考试

LEVEL_WEIGHT: dict[str, float] = {"必备": 1.0, "推荐": 0.8, "加分": 0.6}
STATUS_WEIGHT: dict[str, float] = {"报名中": 0.8, "未开始": 0.5, "常年可报": 0.4, "已截止": 0.1}

# 年级适配：标签里出现「大一可考」等，学生年级不在其中则降权（软硬门槛都写在标签里）
GRADE_TAG = {"大一": "大一可考", "大二": "大二可考", "大三": "大三可考", "大四": "大四可考"}


def _connect() -> pymysql.connections.Connection:
    s = get_settings()
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


def _json_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(t) for t in raw]
    try:
        data = json.loads(str(raw or "[]"))
    except (ValueError, TypeError):
        return []
    return [str(t) for t in data] if isinstance(data, list) else []


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------
# 状态计算：报名窗口 + 考试临近，全部由日期字段推出，不人工标注
# ------------------------------------------------------------------
def cert_status(row: Mapping[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    start, deadline = _as_date(row.get("reg_start")), _as_date(row.get("reg_deadline"))
    exam = _as_date(row.get("exam_start"))
    if start is None or deadline is None:
        status, days = "常年可报", None
        note = "常年开放报名（按测试站/考点批次），越早安排越从容"
    elif start <= today <= deadline:
        status = "报名中"
        days = (deadline - today).days
        note = (f"报名进行中，{deadline.strftime('%m月%d日')} 截止"
                + (f"（剩 {days} 天）" if days is not None and days <= 15 else ""))
    elif today < start:
        status = "未开始"
        days = (start - today).days
        note = f"报名预计 {start.strftime('%Y年%m月%d日')} 开通（还有 {days} 天），可先备考"
    else:
        status = "已截止"
        days = None
        note = "本批报名已截止" + (f"；{str(row.get('next_batch') or '')}" if row.get("next_batch") else "")
    exam_days = (exam - today).days if exam else None
    return {
        "status": status,
        "reg_start": start.isoformat() if start else "",
        "reg_deadline": deadline.isoformat() if deadline else "",
        "days_to_deadline": days,
        "exam_start": exam.isoformat() if exam else "",
        "days_to_exam": exam_days,
        "status_note": note,
    }


# ------------------------------------------------------------------
# 目录与个性化推荐
# ------------------------------------------------------------------
def _owned_cert_names(student_id: int) -> list[str]:
    """学生档案里已登记的证书名（学生活动 cert 行）。查不到/没登记就返回空。"""
    if not student_id:
        return []
    rows = _query(
        "SELECT `名称` AS name FROM `学生活动` "
        "WHERE `租户编号`=%s AND `学生编号`=%s AND `活动类型`='cert'",
        (1, int(student_id)))
    return [str(r.get("name") or "") for r in rows if r.get("name")]


def _owned_flags(owned: Sequence[str]) -> dict[str, bool]:
    """按证书类别判定学生已持有：类别关键词 ↔ 档案证书名 双向包含。"""
    keys = {
        "cet4": ["四级", "cet4", "cet-4"],
        "cet6": ["六级", "cet6", "cet-6"],
        "ncre": ["计算机等级", "ncre", "计算机二级", "计算机三级"],
        "ruankao": ["软考", "软件设计师", "程序员", "计算机技术与软件"],
        "ntce": ["教师资格", "ntce"],
        "psc": ["普通话"],
        "bigdata_1x": ["大数据应用开发", "1+x", "1x"],
        "huawei": ["华为", "hcia", "hcip"],
    }
    lowered = [str(o).lower() for o in owned if o]
    return {k: any(w in o or o in w for w in words for o in lowered)
            for k, words in keys.items()}


# 目录简称 → 持有类别（同一本证书不重复推荐）
ROW_KEY = {"计算机二级": "ncre", "英语四级": "cet4", "英语六级": "cet6",
           "软考": "ruankao", "教资": "ntce", "普通话": "psc",
           "1+X大数据": "bigdata_1x", "华为HCIA": "huawei"}


def recommend(student_id: int, major: str = "", grade: str = "",
              intent: str = "", today: date | None = None,
              limit: int = 6) -> dict[str, Any]:
    """个性化考证推荐：确定性打分 + 可解释理由 + 差什么。"""
    today = today or date.today()
    rows = _query(
        "SELECT `编号` AS id, `考证名称` AS name, `简称` AS short_name, `负责机构` AS org, "
        "`级别科目` AS level_subject, `适合去向` AS tracks_json, `适合标签` AS tags_json, "
        "`前提条件` AS prerequisites, `收获` AS benefits, `报名方式` AS how_to_apply, "
        "`报名官网` AS apply_url, `费用说明` AS fee, `报名开始` AS reg_start, "
        "`报名截止` AS reg_deadline, `考试日期` AS exam_text, `考试开始` AS exam_start, "
        "`日期备注` AS date_note, `批次说明` AS cycle, `含金量` AS level, "
        "`来源标题` AS source_title, `来源链接` AS source_url, `核实日期` AS verified_at "
        "FROM `考证目录` ORDER BY `排序`, `编号`")
    if not rows:
        return {"engine_version": CERT_ENGINE_VERSION, "items": [], "note": "考证目录暂不可用"}

    owned = _owned_cert_names(student_id)
    owned_flags = _owned_flags(owned)
    intent = str(intent or "").strip()
    major = str(major or "")
    grade = str(grade or "")

    scored: list[dict[str, Any]] = []
    for row in rows:
        st = cert_status(row, today)
        tracks = _json_list(row.get("tracks_json"))
        tags = _json_list(row.get("tags_json"))
        row_short = str(row.get("short_name") or "")

        # 已持有的证书不再推荐（事实判断，不猜）：档案里有同类别证书即跳过
        if owned_flags.get(ROW_KEY.get(row_short, ""), False):
            continue

        reasons: list[str] = []
        score = LEVEL_WEIGHT.get(str(row.get("level") or ""), 0.5) + STATUS_WEIGHT.get(
            st["status"], 0.0)

        reasons.append(st["status_note"])

        if intent and intent in tracks:
            score += 0.5
            reasons.append(f"与你的目标「{intent}」直接相关")
        elif "通用" in tracks:
            score += 0.3
            reasons.append("全专业通用，不依赖具体去向")
        if major and any(t and (t in major or major in t) for t in tags
                         if t not in ("全专业",)):
            score += 0.4
            reasons.append(f"贴合你的专业（{major}）")

        grade_tag = GRADE_TAG.get(grade)
        if grade_tag:
            if grade_tag in tags or "无门槛" in tags:
                score += 0.3
                reasons.append(f"{grade}在校生即可报考")
            elif any(t.endswith("可考") for t in tags) and grade_tag not in tags:
                score -= 0.5
                reasons.append(f"通常建议更晚的年级再考（适合：{'、'.join(t for t in tags if t.endswith('可考'))}）")

        # 差什么：前提条件 + 持有事实
        gaps: list[str] = []
        if row_short == "英语六级" and not owned_flags.get("cet4"):
            gaps.append("六级报考前提是四级 ≥ 425 分——档案里没看到你的四级成绩，先冲四级")
        if row_short == "英语四级" and not owned_flags.get("cet4") and grade in ("大一", "大二"):
            gaps.append("档案里未登记四级成绩，四级是学位与招聘的常见硬门槛，优先级最高")
        if row_short == "普通话" and not owned_flags.get("psc") and intent in ("考公", "就业"):
            gaps.append("档案里未登记普通话等级；考教师资格认定必用（二乙以上）")
        if not gaps:
            gaps.append(f"报名前提：{str(row.get('prerequisites') or '')[:80]}")

        if st["status"] == "报名中" and st["days_to_deadline"] is not None:
            reasons.append(f"当前正在报名，{st['days_to_deadline']} 天后截止，错过等下一批")
        if st["days_to_exam"] is not None and 0 <= st["days_to_exam"] <= REMIND_EXAM_DAYS:
            reasons.append(f"{st['days_to_exam']} 天后开考，已报名的记得打印准考证")

        scored.append({
            "cert_id": int(row.get("id") or 0),
            "name": str(row.get("name") or ""),
            "short_name": row_short,
            "org": str(row.get("org") or ""),
            "level_subject": str(row.get("level_subject") or ""),
            "level": str(row.get("level") or ""),
            "tracks": tracks,
            "tags": tags,
            "benefits": str(row.get("benefits") or ""),
            "prerequisites": str(row.get("prerequisites") or ""),
            "how_to_apply": str(row.get("how_to_apply") or ""),
            "apply_url": str(row.get("apply_url") or ""),
            "fee": str(row.get("fee") or ""),
            "exam_text": str(row.get("exam_text") or ""),
            "date_note": str(row.get("date_note") or ""),
            "cycle": str(row.get("cycle") or ""),
            "source_title": str(row.get("source_title") or ""),
            "source_url": str(row.get("source_url") or ""),
            "verified_at": str(row.get("verified_at") or ""),
            "score": round(score, 4),
            "match_reasons": reasons,
            "gaps": gaps,
            "owned": [o for o in owned if o],
            **st,
        })

    scored.sort(key=lambda x: (-x["score"], x["cert_id"]))
    items = scored[: max(1, int(limit))]
    note = "日期均来自官方公告（附来源链接可核对）；标「预计」的是官方尚未公布的批次，按历年规律推算"
    if owned:
        note = f"已按档案里的证书（{'、'.join(owned[:5])}）去重；" + note
    else:
        note = "档案里暂未登记证书，差距按报名前提与常见路径判断；" + note
    return {
        "engine_version": CERT_ENGINE_VERSION,
        "today": today.isoformat(),
        "intent": intent,
        "major": major,
        "grade": grade,
        "candidate_cnt": len(scored),
        "items": items,
        "note": note,
    }


def catalog(today: date | None = None, limit: int = 20) -> dict[str, Any]:
    """考证目录（不个性化）：全部证书 + 实时状态，页面用。"""
    today = today or date.today()
    result = recommend(student_id=0, today=today, limit=limit)
    result.pop("note", None)
    result["note"] = "目录含实时报名状态；日期均来自官方公告（附来源链接与核实日期），标「预计」为按历年规律推算"
    return result


# ------------------------------------------------------------------
# 通知提醒：并入竞赛通知的未读推送（水位复用，id 带 10^9 偏移）
# ------------------------------------------------------------------
def active_reminders(today: date | None = None) -> list[dict[str, Any]]:
    """当前应提醒的证书条目：即将开放报名≤14天（阶段0）+ 报名中（阶段1）
    + 临近考试≤14天（阶段2）。

    与竞赛通知共用「编号 > 水位」的未读判定：id = OFFSET + 编号*100 + 阶段。
    学生点已读后本阶段不再提醒；进入下一阶段（如从报名中到临近考试）id 更大，会再次提醒。
    """
    today = today or date.today()
    rows = _query(
        "SELECT `编号` AS id, `考证名称` AS name, `报名官网` AS apply_url, "
        "`报名开始` AS reg_start, `报名截止` AS reg_deadline, `考试开始` AS exam_start, "
        "`考试日期` AS exam_text, `核实日期` AS verified_at "
        "FROM `考证目录` ORDER BY `编号`")
    items: list[dict[str, Any]] = []
    for row in rows:
        st = cert_status(row, today)
        cert_id = int(row.get("id") or 0)
        base = st["status"] in ("报名中", "已截止")
        if (not base and st["reg_start"]
                and st["days_to_deadline"] is not None
                and st["days_to_deadline"] <= REMIND_EXAM_DAYS):
            # 未开始且距报名开通 ≤14 天：先告诉学生「多久开始」
            items.append({
                "id": CERT_ID_OFFSET + cert_id * 100 + PHASE_UPCOMING,
                "kind": "cert",
                "cert_id": cert_id,
                "phase": PHASE_UPCOMING,
                "title": f"【考证提醒】{row.get('name')} 报名将于 {st['days_to_deadline']} 天后开通（{st['reg_start']}）",
                "content": f"可先备考，届时在报名官网提交：{row.get('apply_url')}",
                "url": str(row.get("apply_url") or ""),
                "published_at": str(row.get("verified_at") or ""),
                "source": "cert",
            })
        elif st["status"] == "报名中":
            deadline = st.get("reg_deadline") or ""
            items.append({
                "id": CERT_ID_OFFSET + cert_id * 100 + PHASE_ENROLL,
                "kind": "cert",
                "cert_id": cert_id,
                "phase": PHASE_ENROLL,
                "title": f"【考证提醒】{row.get('name')} 正在报名，{deadline[5:7]}月{deadline[8:10]}日截止"
                if len(deadline) >= 10 else f"【考证提醒】{row.get('name')} 正在报名",
                "content": f"报名入口：{row.get('apply_url')}；考试：{row.get('exam_text')}",
                "url": str(row.get("apply_url") or ""),
                "published_at": str(row.get("verified_at") or ""),
                "source": "cert",
            })
        elif st["days_to_exam"] is not None and 0 <= st["days_to_exam"] <= REMIND_EXAM_DAYS:
            items.append({
                "id": CERT_ID_OFFSET + cert_id * 100 + PHASE_EXAM,
                "kind": "cert",
                "cert_id": cert_id,
                "phase": PHASE_EXAM,
                "title": f"【考证提醒】{row.get('name')} 将于 {st['days_to_exam']} 天后开考（{row.get('exam_text')}）",
                "content": f"记得在报名官网打印准考证：{row.get('apply_url')}",
                "url": str(row.get("apply_url") or ""),
                "published_at": str(row.get("verified_at") or ""),
                "source": "cert",
            })
    return items


def watermark_max(today: date | None = None) -> int:
    """当前活跃考证提醒的最大 id（mark_read 推水位时用）。

    没有活跃提醒时返回 0（不能返回占位值——竞赛通知与考证提醒共用一个水位，
    推到偏移量会把所有竞赛通知误标已读；考证提醒 id 恒大于竞赛通知 id，
    之后新提醒出现仍会大于水位、正常提醒）。
    """
    ids = [int(item.get("id") or 0) for item in active_reminders(today)]
    return max(ids) if ids else 0


def merge_notices(competition_items: list[dict[str, Any]], watermark: int,
                  today: date | None = None, limit: int = 20) -> dict[str, Any]:
    """把考证提醒并进竞赛通知列表（按 id 排序，统一走水位判定）。

    返回 items（展示用，按 limit 截断）与 cert_unread_cnt（未读考证提醒总数，
    供调用方把未读角标算对——考证提醒不占竞赛通知的计数）。
    """
    cert_items = [item for item in active_reminders(today)
                  if int(item.get("id") or 0) > int(watermark or 0)]
    merged = list(competition_items or []) + cert_items
    merged.sort(key=lambda x: -int(x.get("id") or 0))
    return {"items": merged[: max(0, int(limit))], "cert_unread_cnt": len(cert_items)}

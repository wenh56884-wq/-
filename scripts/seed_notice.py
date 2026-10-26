# scripts/seed_notice.py
# 职责：给 notice 表灌「考试/招聘公告」，让职业规划的公告推送（P13-4）有数据可跑
# 依赖：pymysql / app.config / engine.career_rules（只用于 raw_hash 去重口径）
# 说明：
#   1) 截止日期按「相对今天的天数」生成，所以任何时候跑都能同时产生
#      open（未截止）与 expired（已截止）两类，便于验证引擎的日期过滤。
#   2) 所有标题/发布单位都是公开赛制里的通用表述，**不伪造具体岗位与附件链接**；
#      url 留空，避免演示时点进去是死链。真实数据由 etl 层抓取后覆盖。
#   3) 幂等：以 raw_hash 去重，重复运行不产生重复行。
# 用法：.venv\Scripts\python.exe scripts\seed_notice.py [--tenant 1]

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402

# ----------------------------------------------------------------
# 种子公告：days 是「截止日距今天数」，负数代表已截止（用来验证过滤）
# ----------------------------------------------------------------
NOTICES: list[dict[str, Any]] = [
    {
        "title": "2027年度中央机关及其直属机构考试录用公务员公告",
        "publisher": "国家公务员局",
        "days": 18,
        "category": "考公",
        "summary": "国考公告发布，含报考条件、职位表查询方式、报名与笔试时间安排。"
                   "应届毕业生可报定向职位，报名前须核对专业目录与学历要求。",
    },
    {
        "title": "重庆市2027年度考试录用公务员报名入口开放",
        "publisher": "重庆市人力资源和社会保障局",
        "days": 41,
        "category": "考公",
        "summary": "重庆市考报名开始，市直单位与区县岗位同步开放。"
                   "部分岗位限应届、限党员，报名时须上传学信网学籍验证报告。",
    },
    {
        "title": "重庆市某区县事业单位公开招聘工作人员公告（综合类）",
        "publisher": "重庆市某区县人力社保局",
        "days": 9,
        "category": "考公",
        "summary": "综合类岗位招聘，笔试科目为《综合基础知识》，不限专业岗位占三成，"
                   "面向应届与社会人员，服务期满可参与遴选。",
    },
    {
        "title": "2027年全国硕士研究生招生考试网上报名公告",
        "publisher": "教育部教育考试院",
        "days": 25,
        "category": "考研",
        "summary": "研招网报名时间、报考点选择规则、学历学籍校验要求。"
                   "往届生须选择户籍或工作所在地报考点，并准备社保或居住证明。",
    },
    {
        "title": "2027年硕士研究生招生考试报名信息网上确认须知",
        "publisher": "重庆市教育考试院",
        "days": 52,
        "category": "考研",
        "summary": "网上确认上传材料清单：身份证、学生证或在读证明、"
                   "学历学籍在线验证报告；逾期未确认视为放弃报名。",
    },
    {
        "title": "2026年12月全国大学英语四、六级考试报名通知",
        "publisher": "重庆市教育考试院",
        "days": 6,
        "category": "证书",
        "summary": "四六级笔试报名与缴费时间，口试为选考项。"
                   "报名系统按学籍库校验，未注册学籍的学生无法报考。",
    },
    {
        "title": "全国计算机等级考试（NCRE）第77次考试报名公告",
        "publisher": "重庆市教育考试院",
        "days": 14,
        "category": "证书",
        "summary": "二级 MS Office、Python 程序设计等科目开放报名，"
                   "证书长期有效，可作为简历技能佐证。",
    },
    {
        "title": "2026年秋季校园招聘双选会（信息技术类专场）",
        "publisher": "重庆市高校毕业生就业指导中心",
        "days": 11,
        "category": "就业",
        "summary": "面向 2027 届毕业生的信息技术类专场双选会，参会单位以软件开发、"
                   "数据分析、运维岗为主，现场可直接投递并初面。",
    },
    {
        "title": "2027届毕业生就业协议书（三方）线上签约操作指引",
        "publisher": "重庆市高校毕业生就业指导中心",
        "days": 68,
        "category": "就业",
        "summary": "三方协议线上签约流程、解约与改签规则。"
                   "签约前须确认单位性质，机关事业单位与国企的报到证办理方式不同。",
    },
    {
        "title": "全国大学生数学建模竞赛校内选拔报名通知",
        "publisher": "教务处",
        "days": 21,
        "category": "竞赛",
        "summary": "校内选拔面向大二及以上学生，三人一组，"
                   "通过选拔可代表学校参加省级与国家赛，获奖计入综合素质测评。",
    },
    {
        "title": "中国国际大学生创新大赛（原互联网+）校内项目征集",
        "publisher": "创新创业学院",
        "days": 33,
        "category": "竞赛",
        "summary": "征集创新创业项目，需提交商业计划书与路演 PPT，"
                   "校级立项后可申请孵化场地与经费支持。",
    },
    {
        "title": "2026年下半年中小学教师资格考试（笔试）报名公告",
        "publisher": "重庆市教育考试院",
        "days": -12,
        "category": "证书",
        "summary": "教师资格证笔试报名已结束，本批次考试将于近期举行。",
    },
    {
        "title": "2026年国家公务员补充录用公告（上一年度）",
        "publisher": "国家公务员局",
        "days": -60,
        "category": "考公",
        "summary": "上一年度调剂补充录用已截止，仅作历史记录保留。",
    },
]


def raw_hash(title: str, publisher: str | None) -> str:
    """与 notice.raw_hash 唯一键口径一致：标题+发布单位 的 md5。"""
    return hashlib.md5(f"{title}|{publisher or ''}".encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, default=1)
    args = ap.parse_args()

    s = get_settings()
    conn = pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    today = date.today()
    inserted = skipped = 0
    try:
        with conn.cursor() as cur:
            for n in NOTICES:
                h = raw_hash(n["title"], n["publisher"])
                cur.execute("SELECT id FROM notice WHERE raw_hash = %s", (h,))
                if cur.fetchone():
                    skipped += 1
                    continue
                deadline = today + timedelta(days=int(n["days"]))
                published = deadline - timedelta(days=20)
                cur.execute(
                    """
                    INSERT INTO notice
                        (tenant_id, title, publisher, deadline, summary, url,
                         category, raw_hash, published_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (args.tenant, n["title"], n["publisher"], deadline,
                     n["summary"], None, n["category"], h, published),
                )
                inserted += 1
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(deadline >= CURDATE()) AS open_cnt,
                       SUM(deadline <  CURDATE()) AS expired_cnt,
                       COUNT(*) AS total
                FROM notice WHERE tenant_id = %s
                """,
                (args.tenant,),
            )
            stat = cur.fetchone() or {}
    finally:
        conn.close()

    print(f"新增 {inserted} 条，跳过已存在 {skipped} 条")
    print(f"当前共 {stat.get('total')} 条：未截止 {int(stat.get('open_cnt') or 0)} 条，"
          f"已截止 {int(stat.get('expired_cnt') or 0)} 条")
    print("（已截止的那批不是多余数据——用它验证引擎的日期过滤确实生效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""为演示账号造三场可复现的模拟面试（分数递增，含专业考点）。

为什么需要：库里演示账号的历史场次答案多为「11」这类无效输入，分数 20 上下，
圆桌/护照/溯源都无从展示。这里用引擎真实评分函数造样本，分数不是硬编码的。

用法：.venv\\Scripts\\python.exe scripts/seed_demo_interview.py [--reset]
  --reset 先删除本脚本以前造的场次（按 岗位名称 前缀识别），可重复执行。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.interview import _conn, _load_resume, _rows
from engine.interview import (
    QUESTION_TYPES,
    aggregate,
    extract_quotes,
    fallback_comment,
    rubric_of,
    score_answer,
)
from agents import interviewer

STUDENT_NO = "AI20230001"
TENANT = 1
JOB_TITLE = "算法工程师（校招·演示样本）"
SKILLS = ["机器学习", "算法", "Python", "数据分析", "模型评估"]

# 六道题：题型 + 题干 + 考点（考点里刻意含「机器学习」「算法」，用于验证课程技能桥）
QUESTIONS = [
    ("motivation", "为什么选择算法 / 数据这个方向？你平时怎么学新技术？",
     ["兴趣", "项目", "学习方法", "实践", "源码"]),
    ("major", "解释一下过拟合的成因，以及你在项目里怎么避免它。",
     ["机器学习", "算法", "过拟合", "正则化", "交叉验证", "泛化"]),
    ("project", "围绕你简历里的项目：背景、你负责的部分、难点、方案和结果。",
     ["背景", "负责", "难点", "方案", "结果"]),
    ("scenario", "模型上线后效果持续下降，你会怎么排查？",
     ["监控", "数据漂移", "特征", "评估", "回滚", "复盘"]),
    ("stress", "你的模型准确率只有 60%，队友当场质疑，你怎么回应？",
     ["指标", "基线", "样本", "复盘"]),
    ("counter", "最后留给你提问：你想问面试官什么？",
     ["团队", "挑战", "衡量", "流程"]),
]

# 满分版答案（结构标记齐全、含数字）；低分场次按句子比例截断，保证句子完整
ANSWERS = [
    "我的兴趣来自大二的一个课程项目：用图像分类做校园垃圾识别。第一版准确率只有 61%，"
    "我调了数据增强和迁移学习，做到 87%，那次调参让我确认想做算法方向。"
    "我的学习方法有三条：首先看论文和官方文档，把原理弄明白；然后一定在自己的项目里实践一遍；"
    "最后写笔记讲给别人听，讲不清楚就说明没懂。项目里我踩过最大的坑是数据泄漏，"
    "后来每次划分训练集都会先检查一遍。",

    "过拟合本质是模型把训练集的噪声也学进去了，泛化能力变差，这是机器学习里最常见的问题，"
    "算法再强也躲不过。成因通常是模型容量过大、样本太少或特征里有泄漏。"
    "应对上我会做四件事：第一，加正则化，L2 抑制大权重；第二，用验证集选超参，"
    "不在测试集上调；第三，早停加数据增强；第四，精简特征，把业务上不该出现的特征剔掉。"
    "判断上我会对比训练集和验证集的损失曲线，训练损失一直降、验证损失回升就是典型过拟合。"
    "项目里我把验证集准确率从 79% 提到 86%，靠的就是正则化加数据增强。",

    "背景是学院的课程达成度分析系统，原来靠 Excel 人工汇总，一个专业要两天。"
    "我负责数据层和模型，把 12 个学期的成绩做成宽表。难点有两个：课程编号跨学期不一致，"
    "直接 join 会丢 30% 的数据；130 万行做多维聚合时接口要 8 秒。"
    "方案是先建课程维表做编号归一，再用预聚合把常用组合算成物化表。"
    "结果是分析从两天缩到 3 分钟，接口从 8 秒降到 400 毫秒。",

    "先看监控，确认是全线下降还是某个群体出问题。然后查数据，重点看输入特征的分布有没有变，"
    "看是不是某个上游特征变了；再看标签回流的真实效果。定位后分两种处理：如果特征漂移，用新数据做增量训练；"
    "如果是上游埋点改版，先回滚模型到上一版，再修数据管道。最后把原因写进复盘，"
    "加一条特征分布的日常监控。",

    "先承认结果不好，不辩解。然后给基线：60% 相比随机猜或多数类基线高多少，"
    "如果基线就是 58%，这个模型其实没学到东西。再看样本，是不是某几类样本太少或标注有问题。"
    "最后给下一步：补齐样本、换评估指标，一周后给新结果。被质疑不是坏事，"
    "能把问题说清楚比硬撑有用。",

    "我想问三个：团队现在最想解决的挑战是什么；这个岗位的衡量标准是准确率还是业务指标；"
    "需求从提出到上线大概走哪些流程，我进来后在哪一环能最快上手。",
]


def _trim(text: str, keep: float) -> str:
    """按句号截断到 keep 比例，保留完整句子。"""
    parts = [p for p in text.replace("\n", "").split("。") if p.strip()]
    n = max(1, round(len(parts) * keep))
    return "。".join(parts[:n]) + "。"


def _scores_of(answers: list[str], outlines: list[dict], evidence: list[str]) -> list[dict]:
    return [score_answer(a, o["rubric"], evidence) for a, o in zip(answers, outlines)]


def main(reset: bool) -> None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            stu = _rows(cur, "SELECT `编号` FROM `学生` WHERE `学号`=%s", (STUDENT_NO,))
            if not stu:
                print("找不到演示学生", STUDENT_NO)
                return
            sid_student = int(stu[0]["编号"])
            res = _rows(cur, "SELECT `编号` FROM `简历` WHERE `学生编号`=%s AND `状态`='active'"
                             " ORDER BY `版本号` DESC LIMIT 1", (sid_student,))
            if not res:
                print("该学生没有简历，无法造面试")
                return
            resume_id = int(res[0]["编号"])
            resume = _load_resume(cur, resume_id, TENANT)

            if reset:
                cur.execute("SELECT `编号` FROM `面试会话` WHERE `学生编号`=%s AND `岗位名称`=%s",
                            (sid_student, JOB_TITLE))
                old = [int(r["编号"]) for r in cur.fetchall()]
                if old:
                    marks = ",".join(["%s"] * len(old))
                    cur.execute(f"DELETE FROM `面试问答` WHERE `会话编号` IN ({marks})", tuple(old))
                    cur.execute(f"DELETE FROM `面试会话` WHERE `编号` IN ({marks})", tuple(old))
                    print(f"已清理旧样本 {len(old)} 场")

            evidence = [str(resume.get("简历原文") or resume.get("自我评价") or "")]
            evidence += SKILLS
            evidence += [str(e.get("desc") or "") for e in (resume.get("experiences") or []) if e.get("desc")]
            evidence = [e for e in evidence if e.strip()]

            outlines: list[dict] = []
            for idx, (qtype, question, kws) in enumerate(QUESTIONS, start=1):
                rub = rubric_of(qtype, SKILLS)
                rub["keywords"] = list(kws)
                outlines.append({"round": idx, "type": qtype, "question": question, "rubric": rub,
                                 "source": "demo-sample"})

            # 三场：keep 越小答案越短、漏的考点越多，分数自然越低
            plans = [(0.35, 2), (0.62, 1), (1.0, 0)]  # (保留比例, 天数前)
            now = datetime.now()
            for keep, days_ago in plans:
                answers = [_trim(a, keep) for a in ANSWERS]
                scores = _scores_of(answers, outlines, evidence)
                agg = aggregate(scores, outlines)
                when = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
                snapshot = json.dumps({"title": JOB_TITLE, "skill_tags": SKILLS,
                                       "education": "本科", "industry": "人工智能",
                                       "city": "重庆", "pool": "national"}, ensure_ascii=False)
                cur.execute(
                    "INSERT INTO `面试会话`(`租户编号`,`学生编号`,`简历编号`,`岗位编号`,`岗位名称`,"
                    "`岗位要求快照`,`状态`,`提纲`,`当前轮次`,`最大轮次`,`总分`,`报告`,`引擎版本`,"
                    "`创建时间`,`完成时间`) VALUES (%s,%s,%s,NULL,%s,%s,'finished',%s,%s,%s,%s,%s,"
                    "'interview-v2',%s,%s)",
                    (TENANT, sid_student, resume_id, JOB_TITLE, snapshot,
                     json.dumps(outlines, ensure_ascii=False), len(outlines), len(outlines),
                     agg["total"] if agg else None, None, when, when))
                session_id = cur.lastrowid
                for o, a, s in zip(outlines, answers, scores):
                    comment = fallback_comment(o["question"], s, a) if s else None
                    cur.execute(
                        "INSERT INTO `面试问答`(`会话编号`,`轮次`,`问题类型`,`问题`,`学生回答`,"
                        "`点评`,`评分`,`引用原文`,`点评版本`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (session_id, o["round"], o["type"], o["question"], a, comment,
                         s["score"] if s else None,
                         json.dumps(extract_quotes(comment or ""), ensure_ascii=False),
                         "comment-fallback-v1"))
                # 报告文字用引擎模板（不调模型，数字全部来自引擎）
                report = interviewer.render_report({
                    "total": agg["total"] if agg else None,
                    "answered": agg["answered"] if agg else 0,
                    "skipped": agg["skipped"] if agg else len(outlines),
                    "probes": 0,
                    "items": [{"round": o["round"], "label": QUESTION_TYPES[o["type"]]["label"],
                               "score": s["score"] if s else None,
                               "brief": a[:60]} for o, a, s in zip(outlines, answers, scores)],
                    "strengths": [QUESTION_TYPES[o["type"]]["label"]
                                  for o, s in zip(outlines, scores) if s and s["score"] >= 75],
                    "core_problems": [], "improvement_plan": [], "gaps": [],
                })
                cur.execute("UPDATE `面试会话` SET `报告`=%s WHERE `编号`=%s", (report, session_id))
                print(f"场次 {session_id}: keep={keep} 总分={agg['total'] if agg else None} 日期={when[:10]}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main("--reset" in sys.argv)

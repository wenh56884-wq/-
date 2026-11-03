# agents/student_agent.py
# 职责：学生端 Agent 的意图路由与参数抠取——只选工具、抠参数，不查库、不调 LLM。
# 依赖：标准库 re / typing；身份由 ToolContext.student_id 在后端注入，本模块不接收外部学号。
# 说明：纯函数，便于单测与迁移；图编排仍由 agents/graph.py 负责。

from __future__ import annotations

import re
from typing import Any

AGENT_VERSION = "student-agent-v1"

# 省级地名：学生问「重庆国考职位」时转成 place 过滤，避免把地名当关键词。
PLACE_WORDS: tuple[str, ...] = (
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "宁夏",
    "新疆", "西藏", "内蒙古", "广西",
)

# 学生端「本人数据」意图表：命中即选工具，**未命中返回 None** 继续走后面的分支。
# 只列明确指向本人数据的问法；「推荐 / 岗位」这类留给默认分支，
# 这样「实习管理办法」仍会正确落到知识库，而不是被塞进某个数据工具。
STUDENT_DATA_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # agent-entry-v2：招考/面试/题库放最前，具体词优先于宽泛词
    #（「招考公告」要在 my_notices 的「公告」之前被吃掉）
    ("question_bank_lookup", ("面试题", "题库", "会问什么", "都会问", "常问",
                              "面试问什么", "面试一般")),
    ("my_interviews", ("面试记录", "面试历史", "面试成绩", "我面过",
                       "模拟面试成绩", "面试了多少", "面过几场")),
    # 职位表要排在招考公告之前：「国考职位表」既含「国考」也含「职位表」，
    # 先匹配具体词，避免被 exam_notices 吃掉。
    ("exam_positions", ("国考职位", "国考岗位", "职位表", "招考职位", "公务员职位",
                        "国考招录")),
    ("exam_notices", ("招考", "公务员考试", "事业单位招聘", "国考", "省考", "报名截止")),
    # 预测要排在成绩之前：问「预测一下我下学期的绩点」时，
    # 「绩点」会先被成绩路由吃掉，答成历史成绩而不是预测。
    ("my_forecast", ("预测", "下学期", "走势", "未来", "会怎样", "会不会挂")),
    ("my_grades", ("成绩", "成绩单", "分数", "绩点", "均分", "考了多少")),
    # 软技能测评：「测评/软技能/能力画像」要排在成绩之后、报考分析之前，
    # 这些词不与成绩/报考分析重叠，命中即走本人画像而非知识库。
    ("my_assessment", ("测评", "软技能", "能力画像", "复合能力", "职业素养", "五维画像")),
    ("my_career_forecast", ("竞争力", "上岸", "胜算", "把握", "考公", "考研", "考编", "报考")),
    ("my_notices", ("通知", "消息", "公告")),
    ("competition_guide", ("竞赛", "比赛", "挑战杯")),
    ("my_career_guide", ("规划", "怎么准备", "怎么规划", "发展方向")),
    ("kg_major_skills", ("专业学什么", "能学到什么", "专业能学")),
)


def personal_tool(intent: str) -> str | None:
    """学生端数据意图路由：命中返回工具名，未命中返回 None。

    放在知识库分支之前调用，原因是知识库词表含「学分 / 实习 / 管理办法」等词，
    学生问「我的成绩怎么样」时会被误判成查制度文档。
    """
    for name, keywords in STUDENT_DATA_ROUTES:
        if any(k in intent for k in keywords):
            return name
    return None


def tool_args(tool_name: str, query: str) -> dict[str, Any]:
    """按工具从提问里抠参数；抠不到就留空——工具层对空参有明确语义（不猜）。"""
    args: dict[str, Any] = {}
    if tool_name == "exam_notices":
        # 先剥掉「招考」再匹配目标词：「招考公告」里含子串「考公」，不剥会误判成考公
        text = query.replace("招考", "")
        for word, code in (("考公", "civil"), ("公务员", "civil"), ("国考", "civil"),
                           ("省考", "civil"), ("考编", "institution"),
                           ("事业单位", "institution"), ("考研", "postgraduate"),
                           ("研究生", "postgraduate")):
            if word in text:
                args["exam_type"] = code
                break
        quoted = re.search(r"[\"“']([^\"”']{1,30})[\"”']", query)
        if quoted:
            args["keyword"] = quoted.group(1)
    elif tool_name == "exam_positions":
        quoted = re.search(r"[\"“']([^\"”']{1,30})[\"”']", query)
        if quoted:
            args["keyword"] = quoted.group(1)
        # 工作地点：命中省级地名就转成 place 过滤，并从关键词里剔掉
        text = query
        for place in PLACE_WORDS:
            if place in text:
                args["place"] = place
                text = text.replace(place, "")
                break
        for word, edu in (("博士", "博士"), ("硕士", "硕士研究生"),
                          ("研究生", "硕士研究生"), ("本科", "本科"),
                          ("大专", "大专"), ("专科", "大专")):
            if word in text:
                args["education"] = edu
                text = text.replace(word, "")
                break
        if "党员" in text:
            args["political"] = "中共党员"
            text = text.replace("党员", "")
        if not quoted:
            cleaned = re.sub(
                r"国考|招考|职位表|职位|岗位|有哪些|有什么|哪些|具体|信息|"
                r"帮我|查一下|看看|一下|里|的|吗|呢|？|\?|，|。|(?:19|20)\d{2}年?",
                "", text)
            cleaned = cleaned.strip(" 　")
            if cleaned.endswith("专业") and len(cleaned) > 2:
                cleaned = cleaned[:-2]        # 「计算机专业」按「计算机」检索，别把「专业」当专业名
            if len(cleaned) >= 2:
                args["keyword"] = cleaned[:20]
    elif tool_name == "question_bank_lookup":
        quoted = re.search(r"[\"“']([^\"”']{1,30})[\"”']", query)
        if quoted:
            args["query"] = quoted.group(1)
        else:
            # 去掉「面试会问什么」这类虚词后，剩余连续汉字当检索词
            cleaned = re.sub(r"面试|题库|一般|都会|会问|什么|哪些|有|的|吗|？|\?", "", query)
            cleaned = cleaned.strip(" 　，。")
            if len(cleaned) >= 2:
                args["query"] = cleaned[:20]
    return args


def default_tool(intent: str) -> str:
    """学生端兜底路由（知识库 / 联网 / 工作流都没命中时）。"""
    if any(k in intent for k in ("推荐", "岗位", "工作")):
        return "my_recommendations"
    if any(k in intent for k in ("技能", "需要学", "要学什么")):
        return "kg_skill_jobs"
    return "my_warning"


def describe() -> dict[str, Any]:
    """能力自检用：告诉前端/脚本学生端路由覆盖了哪些工具。"""
    return {
        "agent_version": AGENT_VERSION,
        "personal_tools": [name for name, _ in STUDENT_DATA_ROUTES],
        "default_tools": ["my_recommendations", "kg_skill_jobs", "my_warning"],
        "place_words": len(PLACE_WORDS),
    }

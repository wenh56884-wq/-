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
    # 岗位搜索（检索不是推荐）：明确带搜索动词的问法走岗位库检索
    ("search_jobs", ("搜岗位", "搜索岗位", "岗位搜索", "查岗位", "找岗位",
                     "岗位库", "搜一下岗位", "检索岗位")),
    # 预测要排在成绩之前：问「预测一下我下学期的绩点」时，
    # 「绩点」会先被成绩路由吃掉，答成历史成绩而不是预测。
    ("my_forecast", ("预测", "下学期", "走势", "未来", "会怎样", "会不会挂")),
    # 选课推荐要排在成绩之前：「选什么课补技能」问的是缺口选课，不是历史成绩。
    ("my_elective_advice", ("选课", "选修", "技能缺口", "补什么课", "选什么课",
                            "补技能", "选哪些课")),
    ("my_grades", ("成绩", "成绩单", "分数", "绩点", "均分", "考了多少")),
    # 软技能测评：「测评/软技能/能力画像」要排在成绩之后、报考分析之前，
    # 这些词不与成绩/报考分析重叠，命中即走本人画像而非知识库。
    ("my_assessment", ("测评", "软技能", "能力画像", "复合能力", "职业素养", "五维画像")),
    ("my_career_forecast", ("竞争力", "上岸", "胜算", "把握", "考公", "考研", "考编", "报考")),
    # 标记已读要排在通知查询之前：「通知都读完了」是操作不是查询
    ("mark_notices_read", ("全部已读", "标记已读", "都读过了", "通知已读", "一键已读",
                           "全部标记", "读完了", "都看过了")),
    ("my_notices", ("通知", "消息", "公告")),
    ("competition_guide", ("竞赛", "比赛", "挑战杯")),
    # 考证推荐要排在招考公告之前：「软考报名截止时间」含 exam_notices 的「报名截止」，
    # 具体证书词必须先被考证路由吃掉；「普通话/教资/四级」等词无其他归属。
    ("cert_guide", ("考证", "考什么证", "证书推荐", "该考什么证", "考什么证书",
                    "等级考试", "软考", "四六级", "四级", "六级", "cet",
                    "普通话考试", "普通话", "教师资格证", "教资", "计算机二级", "1+x", "hcia",
                    "证书怎么报名", "证书报名", "证书", "报名费", "含金量")),
    ("my_career_guide", ("规划", "怎么准备", "怎么规划", "发展方向", "职业目标", "我的目标")),
    ("kg_major_skills", ("专业学什么", "能学到什么", "专业能学")),
)

# 保存职业目标的明确操作词：必须与 考公/考研/考编/就业 之一同现才触发，
# 避免「我考公有多大把握」这类竞争力问法被当成保存操作。
SAVE_INTENT_MARKERS: tuple[str, ...] = (
    "目标设为", "目标定为", "目标是", "设定目标", "保存目标", "目标改成",
    "把目标定", "职业目标", "目标选", "决定考公", "决定考研", "决定考编", "决定就业",
)


def personal_tool(intent: str, raw: str | None = None) -> str | None:
    """学生端数据意图路由：命中返回工具名，未命中返回 None。

    放在知识库分支之前调用，原因是知识库词表含「学分 / 实习 / 管理办法」等词，
    学生问「我的成绩怎么样」时会被误判成查制度文档。

    raw：当前问句原文。复合规则只看当前问句——intent 可能拼着上一轮原话
    （graph._intent_text），上一轮问过「国考职位表」会让追问「那我的成绩怎么样」
    在合并文本上误中职位表复合词。
    """
    text = str(raw).strip() if raw else intent
    # 复合命中：「考公/国考词 + 职位/岗位词」问的是职位明细（逐条数据），
    # 而不是报考分析路线聚合，先于 STUDENT_DATA_ROUTES 返回 exam_positions。
    # 例：「今年考公能考哪些职位」含「考公」+「职位」。
    if any(a in text for a in ("国考", "考公", "公务员", "招录", "招考")) and any(
            b in text for b in ("职位", "岗位")):
        return "exam_positions"
    # 复合命中 2：学历门槛问法不含「职位/岗位」字面（「里面有哪些是本科就可以考的」），
    # 但问的仍是职位表按学历过滤（education 由 tool_args 抠出）。
    # 排除考研/教资等非国考职位表范畴的考试，别把「本科能直接考研吗」抢过来。
    if (any(v in text for v in ("能考", "可以考", "可考", "能报", "可以报", "可报",
                                "能报考", "要报"))
            and any(e in text for e in ("本科", "硕士", "大专", "专科", "学历"))
            and not any(x in text for x in ("考研", "教资", "教师资格", "四六级",
                                            "四级", "六级", "驾照", "计算机等级"))):
        return "exam_positions"
    # 复合命中 3：「具体岗位和要求」——岗位字面 + 要求/条件/门槛，问的是职位表字段
    #（学历/政治面貌/专业等）。「有哪些岗位适合我」没有要求类词，不受影响。
    if any(p in text for p in ("职位", "岗位")) and any(
            r in text for r in ("要求", "条件", "门槛")):
        return "exam_positions"
    # 复合命中 4：搜索动词 + 岗位词 → 岗位库检索（不是个性化推荐）。
    # 「推荐 / 适合我」仍归推荐；国考/招考职位表由上面的复合规则先接住。
    if (any(s in text for s in ("搜索", "搜一下", "搜一搜", "检索", "找找",
                                "找一下", "查一下", "搜搜"))
            and any(p in text for p in ("岗位", "职位", "工作"))
            and not any(x in text for x in ("推荐", "适合我", "国考", "考公",
                                            "招考", "公务员", "招录"))):
        return "search_jobs"
    # 复合命中 5：明确的目标保存操作词 + 四个方向之一 → 保存职业目标。
    # 只问竞争力/把握的问法不含操作词，仍走 my_career_forecast。
    if any(m in text for m in SAVE_INTENT_MARKERS) and any(
            g in text for g in ("考公", "考研", "考编", "就业")):
        return "save_career_intent"
    for name, keywords in STUDENT_DATA_ROUTES:
        if any(k in text for k in keywords):
            # 「证书」过宽：毕业证/简历里的技能证书/荣誉证书不是考证；「XX管理办法」
            # 这类制度问法归知识库——放行给后续路由
            if name == "cert_guide" and any(
                    b in text for b in ("毕业证", "简历", "技能证书", "荣誉证书",
                                        "发证书", "证书领取", "领证书",
                                        "管理办法", "规定", "制度", "细则", "实施办法")):
                continue
            return name
    # 当前问句没命中再退回合并意图（无关键词的追问「那结果呢」靠上一轮原话续上）。
    # 顺序很关键：先 raw 后 intent，新话题（「那我的成绩怎么样」）才不会被
    # 上一轮的「国考职位表」字面劫走。
    if raw and raw.strip() != intent:
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
        # 年度：「2026年 / 2027年度 / 2026 年度」显式入参；问「今年/明年」不注年度，
        # 由工具按库内最新年度（MAX(年度)）取数，语义上年份仍来自数据而非模型记忆。
        year_match = re.search(r"(20\d{2})\s*年", text)
        if year_match:
            args["year"] = int(year_match.group(1))
        # 年度词剥离后不参与关键词；年度缺失「今年"语义由工具 layer 兜底最新年度
        text = re.sub(r"20\d{2}\s*年|年度", "", text)
        if not quoted:
            # 泛词剥离表：「今年考公能考哪些职位」这类概览问法清洗后必须归空，
            # 否则残词（如「考公」「有」）被当成关键词 LIKE 查不到任何职位。
            # 知道/要求/条件/门槛/我：追问「我知道我具体岗位和要求」的残词，
            # 拿去 LIKE 只会查空；要求类语义已由复合路由命中、无需关键词。
            cleaned = re.sub(
                r"国考|考公|公务员考试|公务员|招考|招录|职位表|职位|岗位|"
                r"有哪些|有什么|哪些|具体|信息|"
                r"今年|明年|去年|现在|目前|最近|"
                r"能考|能报|想报|要报|可以报|可以考|可以|"
                r"知道|要求|条件|门槛|告诉|满足|符合|里面|其中|还有|就|面|我|"
                r"帮我|查一下|看看|查看|一下|我想|想看|想看|想|看|里|的|相关|有|吗|呢|？|\?|，|。|是",
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
    elif tool_name == "search_jobs":
        cleaned = re.sub(
            r"帮我|搜一下|搜一搜|搜搜|搜索|检索|找一下|找找|查一下|看看|"
            r"岗位|职位|工作|有哪些|有什么|一下|的|吗|呢|？|\?", "", query)
        cleaned = cleaned.strip(" 　，。")
        if len(cleaned) >= 2:
            args["query"] = cleaned[:20]
    elif tool_name == "save_career_intent":
        for word in ("考公", "考研", "考编", "就业"):
            if word in query:
                args["intent"] = word
                break
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

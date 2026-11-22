# agents/intents.py
# 职责：意图关键词的配置化加载——商业化交付时实施方按客户问法增词，不改代码
# 依赖：rules/agent_intents.json（可选覆盖文件）
# 说明：
#   1. 内置默认词表在本模块（_DEFAULTS），保证零配置也能跑；
#   2. rules/agent_intents.json 存在时按节合并（列表追加、词典更新），JSON 优先；
#   3. JSON 坏了不炸服务：打日志、退回内置默认；
#   4. 词表带 mtime 缓存：改文件即生效，无需重启。

from __future__ import annotations

import json
import threading
from pathlib import Path

INTENTS_VERSION = "intents-v1"

_PATH = Path(__file__).resolve().parents[1] / "rules" / "agent_intents.json"

# 内置默认：与配置文件同构。改动历史见 rules/agent_intents.json 的 notes。
_DEFAULTS: dict[str, dict] = {
    "tools": {
        "warning_thresholds": ["阈值", "门槛", "预警线", "判定标准"],
        "class_list": ["班级列表", "班级目录", "有哪些班", "哪些班级", "学院列表", "院系", "各班人数"],
        # 名册要排在预警名单之前：「班级名单」含「名单」，排后面会被预警路由吃掉
        "class_roster": ["名册", "学生列表", "班里有哪些人", "有哪些学生",
                         "班级名单", "全班名单", "全部学生名单"],
        "warning_list": ["预警", "风险名单", "风险学生", "名单", "挂科", "挂了"],
        # 校园行为洞察（班级）：必须排在 student_profile 之前——「班级画像」含「画像」，
        # 排后面会被个人画像路由抢走；点名到具体学生时由 _CLASS_LEVEL_TOOLS 让位。
        # 通用行为词（图书馆/考勤…）也收进来：教师问「全班考勤怎么样」是班级行为数据，
        # 与知识库制度词的冲突由 graph._teacher_campus_tool 的机构词守卫处理。
        "class_campus_insight": ["班级洞察", "班级行为", "班级画像", "全班行为",
                                 "班级活动", "低投入", "图书馆", "借阅", "到馆",
                                 "一卡通", "消费", "考勤", "出勤", "证书",
                                 "活动参与", "行为数据", "投入情况", "投入画像"],
        # 逐生校园行为洞察：点名到学生时班级级让位后由它接住（学号在 plan_teacher 抠）
        "student_campus_insight": ["借阅", "到馆", "一卡通", "消费", "考勤", "出勤",
                                   "图书馆", "证书", "活动参与", "行为画像",
                                   "投入画像", "低投入"],
        "student_profile": ["画像", "标签", "四维", "这个学生", "那位学生", "他的情况", "她的情况"],
        "career_gap": ["差距", "缺口", "能力结构", "岗位要求"],
        "teacher_career_search": ["生涯规划", "职业规划", "生涯档案", "规划查看",
                                   "按班级规划", "规划搜索", "全班规划", "班级规划"],
        # 招考公告（教师端原先漏配词表，问「招考公告」会掉到班级概貌）
        "exam_notices": ["招考公告", "招聘公告", "招聘信息", "事业单位公告", "报名截止"],
        # agent-entry-v3：国考职位表（逐职位明细，师生通用）。
        # 必须排在 search_jobs 之前：「国考职位表里有哪些税务岗位」含「岗位」，
        # 排后面会被岗位搜索的宽泛词抢走。
        "exam_positions": ["国考职位", "国考岗位", "职位表", "招考职位",
                           "公务员职位", "国考招录"],
        # 岗位搜索（检索不是推荐）：师生通用词，教师端原先漏配会掉到班级概貌。
        # 「岗位要求」的差距问法由前面的 career_gap 先接住，不会被「岗位」抢走。
        "search_jobs": ["搜岗位", "搜索岗位", "岗位搜索", "查岗位", "找岗位",
                        "岗位库", "搜一下岗位", "招聘搜索", "岗位"],
        # agent-entry-v1 新增：成绩 / 预测 / 知识图谱（数值仍由 engine 算）
        # 排名要排在成绩之前：「班级成绩排名」里的「成绩」会先被成绩单路由吃掉
        "class_grades_rank": ["排名", "名次", "排第几", "第几名", "班级排名", "专业排名",
                              "平均成绩", "全班平均", "班级平均", "总体平均"],
        "student_grades": ["成绩", "成绩单", "分数", "绩点", "均分", "考了多少"],
        "student_forecast": ["预测", "下学期", "下学期会", "走势", "未来"],
        "kg_major_skills": ["专业学什么", "能学到", "专业能学"],
        # 「会了 Python 能做什么」这种中间插词的问法也要接住，
        # 光写死「会了能做什么」一插词就不认，会掉到兜底的班级概貌
        "kg_skill_jobs": ["技能", "会什么", "会了能做什么", "能做什么"],
        "kg_path": ["达成路径", "还缺什么", "路径", "怎么达到"],
        # agent-entry-v3：国考职位表（逐职位明细，师生通用）
        "exam_positions": ["国考职位", "国考岗位", "职位表", "招考职位",
                           "公务员职位", "国考招录"],
    },
    # 学生端本人数据补充路由（graph.plan_node 在知识库分支之前检查）：
    # 校园行为洞察。「考勤/证书」与知识库制度词（考勤管理规定/资格证书管理办法）撞车，
    # 由 graph._student_campus_tool 的知识库词守卫让位——制度问法仍走 kb_search。
    # 「校园行为」覆盖板块本名「校园行为洞察」（不含「校园洞察」子串）。
    "student_tools": {
        "my_campus_insight": ["校园洞察", "校园行为", "行为画像", "图书馆", "借阅",
                              "到馆", "一卡通", "消费", "考勤", "出勤", "证书", "活动"],
    },
    # 名次信号词：判断教师问的是「第几名」还是「多少分」。
    # 是 tools.class_grades_rank 词表的子集，改那边时这里要同步。
    # 用途：点名到某个学生时，「他排第几」仍要交给班级排名（个人名次在里面），
    #       而「他的平均成绩」要放给成绩单——两者问法很像，靠这个区分。
    "rank_markers": ["排名", "名次", "排第几", "第几名", "班级排名", "专业排名"],
    "overview": ["概貌", "概览", "概况", "整体情况", "情况怎么样", "什么情况",
                 "考公", "考研", "考编", "就业意向", "去向", "意向分布"],
    "levels": {
        "红色": "red", "红牌": "red", "高危": "red",
        "橙色": "orange", "中危": "orange",
        "黄色": "yellow", "低危": "yellow",
    },
    "student_name_stop_words": ["班级", "学生", "画像", "标签", "情况", "老师",
                                "同学", "预警", "名单", "概貌", "差距", "岗位"],
    "chitchat": ["你好", "您好", "hi", "hello", "早", "嗨", "谢谢", "感谢", "再见", "拜拜",
                 "你是谁", "你能做什么", "能干什么", "会什么", "功能是", "怎么用", "如何使用"],
    "kb": ["知识库", "制度", "规定", "流程", "手册", "sop", "faq", "常见问题",
           "报销", "请假", "考勤", "合同", "发票", "入职", "离职", "培训文档",
           "文档里", "文件里", "pdf", "制度里", "政策文件"],
    "web": ["联网", "搜一下", "搜索一下", "上网查", "网上查", "网络搜索",
            "最新新闻", "实时行情", "今年政策", "最近政策", "公开招聘信息"],
    "workflow": ["工作流", "一键", "批量", "跑一遍", "走一遍", "自动执行", "自动跑"],
    "workflow_prefix": ["帮我跑一遍", "帮我跑一下", "帮我执行", "跑一遍", "跑一下", "走一遍",
                        "执行一下", "执行", "工作流", "一键", "批量", "自动执行", "自动跑",
                        "帮我", "一下"],
}

_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float | None = None


def _read_override() -> dict:
    if not _PATH.is_file():
        return {}
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # 配置坏了不能炸对话服务：退回内置默认
        return {}


def _merge(base: dict, override: dict) -> dict:
    """按节合并：列表追加去重（保持顺序），词典更新，标量覆盖。"""
    merged = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in base.items()}
    for key, value in override.items():
        if key == "notes" or key == "version":
            merged[key] = value
            continue
        if key not in merged:
            merged[key] = value          # 新增节：直接采纳
        elif isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = merged[key] + [v for v in value if v not in merged[key]]
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def load(force: bool = False) -> dict:
    """加载并缓存词表；文件 mtime 变了自动重载。"""
    global _cache, _cache_mtime
    mtime = _PATH.stat().st_mtime if _PATH.is_file() else None
    with _lock:
        if force or _cache is None or mtime != _cache_mtime:
            _cache = _merge(_DEFAULTS, _read_override())
            _cache_mtime = mtime
    return _cache


def section(name: str) -> dict | list:
    """取某一节（tools/student_tools/levels/chitchat/kb/web/workflow/overview…）。"""
    return load().get(name) or ({} if name in ("tools", "student_tools", "levels") else [])


def tool_keywords() -> list[tuple[str, tuple[str, ...]]]:
    """教师端工具路由表：按 JSON 里的书写顺序保持优先级。"""
    tools = section("tools")
    return [(name, tuple(kws)) for name, kws in tools.items()]


def student_tool_keywords() -> list[tuple[str, tuple[str, ...]]]:
    """学生端补充路由表（校园行为洞察等本人数据）：书写顺序即优先级。"""
    tools = section("student_tools")
    return [(name, tuple(kws)) for name, kws in tools.items()]


def reload() -> dict:
    """测试用：强制重载。"""
    return load(force=True)

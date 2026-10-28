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
        "warning_list": ["预警", "风险名单", "风险学生", "名单", "挂科", "挂了"],
        "student_profile": ["画像", "标签", "四维", "这个学生", "那位学生", "他的情况", "她的情况"],
        "career_gap": ["差距", "缺口", "能力结构", "岗位要求"],
    },
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
    """取某一节（tools/levels/chitchat/kb/web/workflow/overview…）。"""
    return load().get(name) or ({} if name in ("tools", "levels") else [])


def tool_keywords() -> list[tuple[str, tuple[str, ...]]]:
    """教师端工具路由表：按 JSON 里的书写顺序保持优先级。"""
    tools = section("tools")
    return [(name, tuple(kws)) for name, kws in tools.items()]


def reload() -> dict:
    """测试用：强制重载。"""
    return load(force=True)

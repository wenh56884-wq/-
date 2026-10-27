# engine/interview.py
# 职责：模拟面试官的确定性引擎——提纲生成 / 评分 / 差距清单 / 防虚构校验 / 简历解析与诊断。
# 铁律：引擎定数，模型说话。本模块全部是纯函数，不给 LLM 任何算分权。
# 缺失不冒充：未回答 → score=None；抽不到 → None，绝不填 0 或「不限」。

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

INTERVIEW_ENGINE_VERSION = "interview-v1"
RESUME_PARSE_VERSION = "resume-parse-v1"

# ----------------------------------------------------------------
# 提纲：题型与出题规则（确定性：按简历/岗位证据决定出什么题）
# ----------------------------------------------------------------
QUESTION_TYPES: dict[str, dict[str, Any]] = {
    "motivation": {"label": "动机匹配", "weight": 0.15},
    "major": {"label": "专业基础", "weight": 0.20},
    "project": {"label": "项目深挖", "weight": 0.25},
    "scenario": {"label": "情景模拟", "weight": 0.20},
    "stress": {"label": "抗压应对", "weight": 0.10},
    "counter": {"label": "反问环节", "weight": 0.10},
}

# 每种题型的机械模板（LLM 只做个性化润色，替换 {占位符} 后不得改变考点）
_TEMPLATES: dict[str, list[str]] = {
    "motivation": [
        "你为什么应聘{job_title}这个岗位？请结合你自己的经历说明。",
        "你对我们这个行业了解多少？未来三年的职业规划是什么？",
    ],
    "major": [
        "简历里提到你学过{course}，请讲讲它和{job_title}的关系。",
        "这个岗位要求{skill}，说说你通过什么课程或自学掌握了它？",
    ],
    "project": [
        "请具体讲一下「{proj}」：你承担的角色、遇到的最大困难、最终结果。",
        "「{proj}」里如果重来一次，你会在哪个环节做出不同决策？",
    ],
    "scenario": [
        "假如入职第一周，主管让你在{deadline}内完成{task}，但你需要的数据别人还没给，你会怎么做？",
        "如果团队里同事对你的方案提出强烈质疑，你会怎么处理？",
    ],
    "stress": [
        "坦白说，你的简历和其他候选人相比并不突出，你认为自己凭什么胜任这个岗位？",
        "如果你投了很多简历都没有回音，你会怎么调整？",
    ],
    "counter": [
        "最后留给你提问：你想问面试官什么问题？",
    ],
}

# 各题型的评分要点关键词（答到才得分；引擎逐词匹配，不靠模型感觉）
_RUBRIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "motivation": ("岗位", "规划", "行业", "原因", "因为", "希望", "目标"),
    "major": (),     # 动态：技能标签 / 课程名
    "project": ("角色", "负责", "困难", "结果", "实现", "解决", "完成", "成果"),
    "scenario": ("先", "然后", "确认", "沟通", "方案", "优先", "复盘", "反馈"),
    "stress": (),    # 只看结构与长度（抗压题无标准答案）
    "counter": (),   # 反问环节不打分，只记录
}

# 结构分标记（STAR / 分点叙述）
_STRUCT_MARKS: tuple[str, ...] = (
    "背景", "目标", "行动", "结果", "首先", "其次", "然后", "最后",
    "第一", "第二", "第三", "一是", "二是", "三是",
)

# 深度分档（字符数；中文按 1 计）
_DEPTH_BANDS: tuple[tuple[int, float], ...] = ((30, 0.0), (120, 0.6), (10**9, 1.0))

_MAX_ROUNDS = 6


def _norm(text: str) -> str:
    """规范化：全角→半角、去所有空白。防虚构比对与关键词匹配共用。"""
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", t.lower())


# ----------------------------------------------------------------
# 提纲生成
# ----------------------------------------------------------------
def build_outline(job: Mapping[str, Any] | None,
                  resume: Mapping[str, Any],
                  max_rounds: int = _MAX_ROUNDS) -> list[dict[str, Any]]:
    """按证据决定考什么题：有项目经历→项目深挖；岗位有技能→专业+情景。

    顺序固定：动机→专业→项目→情景→抗压→反问（真实面试的常规推进），
    不足 max_rounds 时按题型权重从低到高裁剪（反问环节永远保留）。
    """
    experiences = list(resume.get("experiences") or [])
    projects = list(experiences)  # 实习/项目/竞赛/社团都值得深挖（有经历就问得下去）
    courses = _list_of(resume.get("courses"))
    skills = _list_of(resume.get("skills"))
    job_title = str((job or {}).get("title") or "目标岗位")
    job_skills = _list_of((job or {}).get("skill_tags"))
    task = job_skills[0] if job_skills else "一项紧急任务"

    plan: list[str] = ["motivation", "major", "scenario", "stress", "counter"]
    if projects:
        plan.insert(2, "project")
    if not job_skills and not courses and "major" in plan:
        plan.remove("major")  # 无技能无课程 → 专业题没有抓手，不出（缺失不编题）
    plan = plan[:max(2, max_rounds)]

    outline: list[dict[str, Any]] = []
    used_proj: set[str] = set()
    for rnd, qtype in enumerate(plan, start=1):
        placeholders: dict[str, str] = {"job_title": job_title, "task": task,
                                        "deadline": "三天", "skill": job_skills[0] if job_skills else "核心技能"}
        if qtype == "major":
            anchor = (courses and courses[0]) or (skills and skills[0]) or None
            if anchor:
                placeholders["course"] = str(anchor)
                placeholders["skill"] = str(skills[0] if skills else anchor)
            else:
                placeholders["course"] = "核心课程"
        if qtype == "project":
            unused = [p for p in projects if p.get("name") not in used_proj] or projects
            proj = unused[0]
            used_proj.add(proj.get("name"))
            placeholders["proj"] = str(proj.get("name") or "项目经历")
        q = _TEMPLATES[qtype][0]
        for k, v in placeholders.items():
            q = q.replace("{" + k + "}", v)
        outline.append({"round": rnd, "type": qtype,
                        "question": q,
                        "rubric": rubric_of(qtype, job_skills)})
    return outline


def rubric_of(qtype: str, job_skills: Sequence[str]) -> dict[str, Any]:
    """评分要点（引擎逐词核对）：关键词 + 结构标记 + 深度档。"""
    kws = list(_RUBRIC_KEYWORDS.get(qtype, ()))
    if qtype == "major":
        kws = [str(s) for s in job_skills][:4] or ["课程", "掌握"]
    return {"keywords": kws, "struct_marks": list(_STRUCT_MARKS),
            "weight": QUESTION_TYPES[qtype]["weight"], "label": QUESTION_TYPES[qtype]["label"]}


# ----------------------------------------------------------------
# 单题评分（确定性：关键词覆盖 30 + 结构 25 + 深度 25 + 证据相关 20）
# ----------------------------------------------------------------
def score_answer(answer: str | None, rubric: Mapping[str, Any],
                 evidence_texts: Sequence[str]) -> dict[str, Any] | None:
    """纯函数评分。未回答（None/空）→ None（缺失不冒充 0）。"""
    if answer is None or not str(answer).strip():
        return None
    ans = str(answer)
    norm_ans = _norm(ans)
    detail: dict[str, Any] = {}

    # 1) 关键词覆盖（30）：命中数/关键词数；无关键词的题型按满分*0.6 给底分
    kws = [str(k) for k in (rubric.get("keywords") or [])]
    if kws:
        hits = [k for k in kws if _norm(k) in norm_ans]
        detail["keyword_hits"] = hits
        detail["keyword_missed"] = [k for k in kws if k not in hits]
        kw_score = 30.0 * len(hits) / len(kws)
    else:
        detail["keyword_hits"] = detail["keyword_missed"] = []
        kw_score = 18.0
    detail["keyword_score"] = round(kw_score, 2)

    # 2) 结构分（25）：分点/STAR 标记，命中 1 个 10、2 个 17、3+ 个 25
    marks = [m for m in rubric.get("struct_marks") or [] if m in ans]
    detail["struct_marks"] = marks
    struct_score = 25.0 if len(marks) >= 3 else (17.0 if len(marks) == 2 else (10.0 if len(marks) == 1 else 0.0))
    detail["struct_score"] = struct_score

    # 3) 深度分（25）：长度分档
    n = len(ans.strip())
    depth_ratio = next(r for th, r in _DEPTH_BANDS if n < th or th == 10**9)
    detail["depth_score"] = round(25.0 * depth_ratio, 2)
    detail["length"] = n

    # 4) 证据相关分（20）：回答与简历/JD 证据的 2-gram 重叠度（防空谈）
    detail["evidence_score"] = round(20.0 * _evidence_overlap(norm_ans, evidence_texts), 2)

    total = kw_score + struct_score + detail["depth_score"] + detail["evidence_score"]
    detail["score"] = round(min(100.0, total), 2)
    return detail


def _evidence_overlap(norm_ans: str, evidence_texts: Sequence[str]) -> float:
    """2-gram 重叠：回答里的 bigram 有多少出现在证据里（0~1）。"""
    evid = _norm("".join(str(t) for t in evidence_texts if t))
    if len(norm_ans) < 2 or not evid:
        return 0.0
    ans_grams = {norm_ans[i:i + 2] for i in range(len(norm_ans) - 1)}
    evid_grams = {evid[i:i + 2] for i in range(len(evid) - 1)}
    if not ans_grams:
        return 0.0
    return min(1.0, len(ans_grams & evid_grams) / max(1, min(len(ans_grams), 40)))


def aggregate(scores: Sequence[Mapping[str, Any] | None],
              outline: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """按题型权重加权汇总（只算已回答的题）；全未回答 → None。"""
    num = den = 0.0
    for item, out in zip(scores, outline):
        if item is None:
            continue
        w = float(QUESTION_TYPES[str(out["type"])]["weight"])
        num += float(item["score"]) * w
        den += w
    if den <= 0:
        return None
    return {"total": round(num / den, 2), "answered": sum(1 for s in scores if s is not None),
            "skipped": sum(1 for s in scores if s is None)}


# ----------------------------------------------------------------
# 差距清单（引擎对照岗位要求逐项核对，缺失就是缺失）
# ----------------------------------------------------------------
def gap_list(resume: Mapping[str, Any], job: Mapping[str, Any] | None,
             scores: Sequence[Mapping[str, Any] | None] | None = None,
             outline: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    job_skills = [str(s) for s in _list_of((job or {}).get("skill_tags"))]
    resume_skills = {_norm(s) for s in _list_of(resume.get("skills"))}
    resume_skills |= {_norm(str(c.get("name") or "")) for c in (resume.get("certs") or [])}

    missing = [s for s in job_skills if _norm(s) not in resume_skills
               and not any(_norm(s) in _norm(k) or _norm(k) in _norm(s) for k in resume_skills)]
    if job_skills and missing:
        gaps.append({"dimension": "技能", "gap": "岗位要求但简历未体现：" + "、".join(missing[:5]),
                     "action": "在技能证书栏补齐可佐证的材料，或先通过课程/自学补上再投递"})

    exp_types = {str(e.get("type") or "") for e in (resume.get("experiences") or [])}
    if "intern" not in exp_types:
        gaps.append({"dimension": "经历", "gap": "简历中没有实习经历",
                     "action": "争取一段与目标岗位相关的实习，哪怕是短期远程项目"})

    edu = _list_of(resume.get("educations"))
    job_edu = str((job or {}).get("education") or "")
    if not edu:
        gaps.append({"dimension": "信息", "gap": "简历缺教育经历（学校/专业/时间段）",
                     "action": "补全教育经历，否则简历初筛容易被刷" + (f"（岗位要求「{job_edu}」）" if job_edu and job_edu not in ("不限", "学历不限") else "")})

    if scores and outline:
        weak = [(out, item) for out, item in zip(outline, scores)
                if item and float(item["score"]) < 60]
        for out, item in weak[:2]:
            label = QUESTION_TYPES[str(out["type"])]["label"]
            gaps.append({"dimension": "面试表现", "gap": f"「{label}」题得分 {item['score']}",
                         "action": f"补强{label}类回答：用 STAR 结构（背景-目标-行动-结果）重新组织"})
    return gaps


# ----------------------------------------------------------------
# 防虚构：点评里的「引文」必须逐字存在于简历/回答原文
# ----------------------------------------------------------------
_QUOTE_RE = re.compile(r"[「『\"]([^「『」』\"]{1,120})[」』\"]")


def extract_quotes(comment: str) -> list[str]:
    return [m.group(1) for m in _QUOTE_RE.finditer(str(comment or ""))]


def verify_comment(comment: str, answer: str | None,
                   evidence_texts: Sequence[str]) -> tuple[bool, list[str]]:
    """点评中每条「引文」都必须能在原文（回答/简历）里逐字找到。
    返回 (是否通过, 找不到的引文列表)。没有引文也算不通过（防虚构要求可回溯）。"""
    quotes = extract_quotes(comment)
    if not quotes:
        return False, []
    sources = [_norm(t) for t in ([answer] + list(evidence_texts)) if t]
    bad = [q for q in quotes if _norm(q) not in "".join(sources)]
    return (not bad), bad


def fallback_comment(question: str, item: Mapping[str, Any] | None,
                     answer: str | None) -> str:
    """校验不过时的降级点评：只机械引用原文片段，不经过模型。
    注意：要点词不是引文，绝不包「」（防虚构校验会把它当引文比对）。"""
    if item is None or answer is None:
        return "本题未作答，无法点评。"
    hits = list(item.get("keyword_hits") or [])
    frag = answer[:40] + ("…" if len(answer) > 40 else "")
    parts = [f"你的回答提到「{frag}」"]
    if hits:
        parts.append("答到了 " + "、".join(hits[:3]) + " 这些要点")
    missed = list(item.get("keyword_missed") or [])
    if missed:
        parts.append("但漏掉了 " + "、".join(missed[:3]))
    parts.append(f"本题得分 {item['score']}。")
    return "；".join(parts)


# ----------------------------------------------------------------
# 简历解析（规则版，确定性；上传/粘贴通用）
# ----------------------------------------------------------------
_SECTION_HEADERS: tuple[tuple[str, str], ...] = (
    ("教育经历", "education"), ("教育背景", "education"), ("教育", "education"),
    ("技能证书", "skills"), ("专业技能", "skills"), ("技能", "skills"),
    ("证书", "skills"), ("语言能力", "skills"),
    ("实践经历", "experiences"), ("项目经历", "experiences"), ("实习经历", "experiences"),
    ("竞赛经历", "experiences"), ("校园经历", "experiences"), ("工作经历", "experiences"),
    ("项目", "experiences"), ("实习", "experiences"), ("竞赛", "experiences"), ("经历", "experiences"),
    ("自我评价", "self"), ("关于我", "self"), ("个人简介", "self"),
)
_CERT_MARKS = ("证书", "资格证", "CET", "四级", "六级", "雅思", "托福", "等级考试")
_TIME_RE = re.compile(r"\d{4}\s*[.\-/年]\s*\d{1,2}|\d{4}\s*[-—–至~]")


def _looks_like_header(line: str) -> str | None:
    """完整标题词优先（长键在前）：「教育经历」不能只剥「教育」把「经历」漏成内容。"""
    for key, sect in sorted(_SECTION_HEADERS, key=lambda kv: -len(kv[0])):
        if line == key or (line.startswith(key) and 0 < len(line) - len(key) <= 2
                           and line[len(key)] in "：: 、|"):
            return sect
    return None


def parse_resume(text: str) -> dict[str, Any]:
    """把简历全文切成三类结构化经历。规则解析，抽不到留空不编造。"""
    lines = [ln.strip() for ln in str(text or "").replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    out: dict[str, Any] = {"self": None, "educations": [], "skills": [],
                           "certs": [], "experiences": [], "raw_text": str(text or "")}
    sect = None
    for ln in lines:
        head = _looks_like_header(ln)
        if head:
            sect = head
            # 剥离被命中的标题词本身（取与 _looks_like_header 相同的最长键）
            key = next(k for k, s in sorted(_SECTION_HEADERS, key=lambda kv: -len(kv[0]))
                       if s == head and (ln == k or (ln.startswith(k) and 0 < len(ln) - len(k) <= 2
                                                     and ln[len(k)] in "：: 、|")))
            rest = ln[len(key):].lstrip("：: 、|")
            if rest:
                _emit(out, sect, rest)
            continue
        if sect:
            _emit(out, sect, ln)
        elif not out["self"] and 10 < len(ln) < 160 and not _TIME_RE.search(ln):
            out["self"] = ln  # 开头无标题的短段视作自我介绍（宁缺勿滥：只取第一段）
    return out


def _emit(out: dict[str, Any], sect: str, line: str) -> None:
    if sect == "self":
        out["self"] = ((out["self"] or "") + line).strip() or None
    elif sect == "education":
        school = re.split(r"[｜|,，，]", line)[0][:120]
        major = next((p.strip() for p in re.split(r"[｜|,，，]", line)[1:] if p.strip()), None)
        out["educations"].append({"school": school, "major": major,
                                  "dates": _TIME_RE.search(line).group(0) if _TIME_RE.search(line) else None})
    elif sect == "skills":
        if any(m in line for m in _CERT_MARKS):
            name = re.split(r"[｜|:：,，，]", line)[0][:120]
            m = re.search(r"\d{3}", line)
            out["certs"].append({"name": name, "level": m.group(0) if m else None})
        else:
            for token in re.split(r"[、,，/|;；]", line):
                token = token.strip()
                if 1 < len(token) <= 40:
                    out["skills"].append(token)
    elif sect == "experiences":
        name = re.split(r"[｜|:：]", line)[0][:200]
        out["experiences"].append({"name": name, "type": _exp_type(line),
                                   "desc": line, "dates": _TIME_RE.search(line).group(0) if _TIME_RE.search(line) else None})


def _exp_type(line: str) -> str:
    if "实习" in line:
        return "intern"
    if "竞赛" in line or "比赛" in line or "挑战杯" in line:
        return "contest"
    if "社团" in line or "志愿" in line:
        return "activity"
    return "project"


# ----------------------------------------------------------------
# 简历诊断（独立入口：不做面试也能出优化建议）
# ----------------------------------------------------------------
_ACTION_VERB_RE = re.compile(r"^(负责|主导|完成|实现|搭建|设计|优化|参与|组织|获得|开发|维护|撰写|分析|提升|降低|独立|协作)")


def diagnose(resume: Mapping[str, Any], job: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """逐条诊断：量化 / 动词开头 / 长度 / 与岗位关键词对齐 / 缺失栏。
    全部确定性规则；rewrite 为模板改写示例（模型可在此之上润色，但模板本身可直接用）。"""
    issues: list[dict[str, Any]] = []
    strengths: list[str] = []

    exps = list(resume.get("experiences") or [])
    for e in exps:
        desc = str(e.get("desc") or "")
        name = str(e.get("name") or "")
        if not re.search(r"\d", desc):
            issues.append({"where": name, "kind": "quantify",
                           "problem": "经历描述没有数字（规模/占比/结果）",
                           "rewrite": f"建议把「{desc[:30]}…」改写为带数字的结果，如：独立完成 X，覆盖 N 个用户/数据 M 条，效率提升 P%"})
        if not _ACTION_VERB_RE.match(desc) and len(desc) > 6:
            issues.append({"where": name, "kind": "verb",
                           "problem": "没有以动作动词开头，HR 扫简历时抓不到重点",
                           "rewrite": f"建议改为「负责/主导/实现 + 事情 + 结果」结构开头"})
        if len(desc) > 200:
            issues.append({"where": name, "kind": "length",
                           "problem": f"描述过长（{len(desc)} 字），建议压缩到 100 字以内",
                           "rewrite": "保留「做了什么 + 怎么做 + 量化结果」三句即可"})
        if len(desc) >= 30 and re.search(r"\d", desc) and _ACTION_VERB_RE.match(desc):
            strengths.append(name)
    if not exps:
        issues.append({"where": "实践经历", "kind": "missing",
                       "problem": "简历没有任何实践/项目/实习经历",
                       "rewrite": "哪怕是课程大作业、比赛、社团活动，也按「角色-做法-结果」补一段"})

    skills = _list_of(resume.get("skills"))
    certs = list(resume.get("certs") or [])
    if not skills and not certs:
        issues.append({"where": "技能证书", "kind": "missing",
                       "problem": "没有技能与证书栏",
                       "rewrite": "至少列出 3 项硬技能（工具/语言/框架）与已获证书"})

    job_kws = [str(s) for s in _list_of((job or {}).get("skill_tags"))]
    aligned = [k for k in job_kws if _norm(k) in _norm(str(resume.get("raw_text") or ""))]
    if job is not None and job_kws:
        issues.append({"where": "岗位对齐", "kind": "alignment",
                       "problem": f"岗位要求技能 {len(job_kws)} 项，简历原文覆盖 {len(aligned)} 项（{'、'.join(aligned[:4]) or '无'}）",
                       "rewrite": ("把相关关键词自然写进技能栏与经历描述，" if len(aligned) < len(job_kws)
                                   else "岗位关键词覆盖良好，") + "注意不要堆砌，每项都要有经历支撑"})

    if not resume.get("self"):
        issues.append({"where": "自我评价", "kind": "missing",
                       "problem": "缺自我评价",
                       "rewrite": "2-3 句：专业方向 + 一项最强证据（数字）+ 与目标岗位的连接"})

    return {"engine_version": RESUME_PARSE_VERSION,
            "score_hint": max(0, 100 - 10 * len(issues)) if issues else 100,
            "strengths": strengths, "issues": issues}


# ----------------------------------------------------------------
# 工具
# ----------------------------------------------------------------
def _list_of(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            import json as _json
            v = _json.loads(v)
        except Exception:
            v = [v]
    if isinstance(v, Mapping):
        return [str(x) for x in v.values()]
    if isinstance(v, Iterable):
        return [str(x) for x in v if str(x).strip()]
    return []

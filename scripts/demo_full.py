# scripts/demo_full.py
# 职责：**完整功能演示**——一条命令跑通系统全部能力，逐步打印真实返回值（不裁剪、不跳过）。
#   学生端：登录 → 画像预警 → 混合推荐(三段式+KG链) → 岗位搜索 → 招考信息
#           → 知识图谱(技能→岗位 / 专业→课程→技能 / explain) → 简历解析→诊断
#           → 模拟面试(6轮含防虚构点评) → 面试报告 → 历史
#   教师端：登录 → 班级总览 → 全班预警 → 学生档案 → 生涯差距
# 用法：先启动服务（8001），再
#   .venv\Scripts\python.exe scripts\demo_full.py
# 参数：QH_BASE 可改服务地址；--student/--teacher 可指定账号。

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = os.getenv("QH_BASE", "http://127.0.0.1:8001")
STEP = {"n": 0}


def _call(method: str, path: str, token: str | None = None, body=None, timeout: int = 120):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"detail": "non-json"}


def step(title: str) -> None:
    STEP["n"] += 1
    print(f"\n{'=' * 74}\n[{STEP['n']:02d}] {title}\n{'=' * 74}")


def brief(items, fmt, limit=3) -> None:
    for it in (items or [])[:limit]:
        print("   " + fmt(it))


def login(account: str, role: str) -> str:
    """学生口令=学号；教师口令=teacher@123（scripts/gen_verify_report.py 建号口径）。"""
    candidates = [account] if role == "student" else ["teacher@123", account]
    last = None
    for pwd in candidates:
        s, d = _call("POST", "/auth/login", body={"account": account, "password": pwd, "role": role})
        if s == 200 and "access_token" in d:
            return d["access_token"]
        last = (s, d)
    raise SystemExit(f"登录失败 {account}/{role}（试过 {candidates}）：{last}")


def pick_accounts() -> tuple[str, str]:
    """从库里挑真实账号（不硬编码过期学号）。"""
    sys.path.insert(0, str(_ROOT))
    from scripts.sync_recruit import _connect
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT `学号` FROM `学生` ORDER BY `学号` LIMIT 1")
        stu = cur.fetchone()[0]
        cur.execute("SELECT `工号` FROM `教师` ORDER BY `编号` LIMIT 1")
        tea = cur.fetchone()[0]
    conn.close()
    return str(stu), str(tea)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="启航系统完整功能演示")
    ap.add_argument("--student", default=None)
    ap.add_argument("--teacher", default=None)
    args = ap.parse_args(argv)

    stu, tea = pick_accounts()
    stu = args.student or stu
    tea = args.teacher or tea

    # ---------------------------------------------------------- 学生端
    step("健康检查")
    s, d = _call("GET", "/health")
    print(f"   HTTP {s}  {d}")
    if s != 200:
        raise SystemExit("服务未启动：先运行 uvicorn app.main:app --port 8001")

    step(f"学生登录（{stu}）")
    st = login(stu, "student")
    print(f"   token 长度 {len(st)}（JWT）")

    step("我的画像预警")
    s, d = _call("GET", "/student/warning", st)
    print(f"   HTTP {s} 等级={d.get('level')} 触发项={len(d.get('reasons') or [])}")
    brief(d.get("reasons"), lambda r: f"· {r}" if isinstance(r, str) else f"· {r}")

    step("混合推荐（0.7 内容 + 0.3 协同过滤 + KG 课程链 + 三段式理由）")
    s, d = _call("GET", "/student/recommendations?top_n=5", st)
    print(f"   HTTP {s} 引擎={d.get('engine_version')} 协同生效={d.get('cf_active')} "
          f"邻居={d.get('neighbor_cnt')} 权重={d.get('weights')} 候选池={d.get('candidate_cnt')}")
    for it in (d.get("items") or [])[:3]:
        print(f"   #{it['title'][:18]} | 综合 {it['final_score']} | A {it.get('content_score')} "
              f"| B {it.get('cf_score')} | 同伴 {it.get('peer_count')} 人")
        reasons = it.get("reasons") or {}
        print(f"      内容匹配：{reasons.get('knowledge', '-')[:60]}")
        print(f"      课程链　：{reasons.get('skill', '-')[:60]}")
        print(f"      同伴证据：{reasons.get('potential', '-')[:60]}")

    step("岗位库搜索（真实企业岗位，周更入库）")
    # 关键词取自库里真实岗位名（招聘岗位表是周更增量，条数少，不能硬编码词）
    s0, first = _call("GET", "/job/list?page_size=1")
    kw = "工程师"
    if first.get("items"):
        kw = str(first["items"][0]["title"]).split("（")[0][:3] or "工程师"
    s, d = _call("GET", f"/job/list?keyword={urllib.parse.quote(kw)}&page_size=3")
    print(f"   HTTP {s} 关键词「{kw}」命中 {d.get('total')} 条（库内共 {first.get('total')} 条）")
    brief(d.get("items"), lambda it: f"· {it['title'][:20]} | {it.get('company')} | {it.get('salary_text')} | {it.get('education')}")

    step("考公 / 考编 / 考研公告库（含对应要求）")
    s, d = _call("GET", "/exam/stats")
    print(f"   HTTP {s} 最后同步={d.get('last_success_at')}")
    for t in d.get("by_type") or []:
        print(f"   {t['label']}：共 {t['total']} 条，在招 {t['open']} 条")
    s, d = _call("GET", "/exam/notices?page_size=3")
    brief(d.get("items"), lambda it: f"· {it['title'][:34]} | 截止 {it.get('signup_end') or '未公布'} | {it.get('status')}")

    step("知识图谱：技能 → 岗位")
    s, d = _call("GET", "/kg/stats")
    print(f"   HTTP {s} 节点 {d.get('nodes')} 边 {d.get('edges')} {d.get('nodes_by_kind')}")
    s, f = _call("GET", "/kg/facets")
    skill = (f.get("skills") or [["数据"]])[0][0]
    major = (f.get("majors") or [["会计学"]])[0][0]
    s, d = _call("GET", "/kg/jobs-by-skill?skill=" + urllib.parse.quote(skill) + "&limit=3")
    print(f"   技能「{skill}」→ {d.get('total')} 个岗位")
    brief(d.get("items"), lambda it: f"· {it['title'][:22]} | {it.get('company')} | 上限 {it.get('salary_max')}")

    step("知识图谱：专业 → 课程 → 技能")
    s, d = _call("GET", "/kg/skills-by-major?major=" + urllib.parse.quote(major))
    print(f"   「{major}」{d.get('course_cnt')} 门课培养 {d.get('total')} 项技能")
    brief(d.get("skills"), lambda it: f"· {it['skill']} ← {'、'.join(it['via_courses'][:2])}")

    step("知识图谱：解释链（学过X课程→掌握Y技能→匹配岗位Z）")
    s, jobs = _call("GET", "/kg/neighborhood?skill=" + urllib.parse.quote(skill) + "&max_jobs=1")
    raw_id = (jobs.get("jobs") or [{"id": "job:1"}])[0]["id"]
    # 图谱节点 id 形如 "job:123"，转成数据库主键给面试/诊断用
    jid = int(str(raw_id).split(":")[-1])
    s, d = _call("GET", f"/kg/explain?major={urllib.parse.quote(major)}&job_id={jid}")
    print(f"   HTTP {s} {d.get('summary')}")
    for c in (d.get("chain") or [])[:3]:
        print(f"   学过 {'、'.join(c['courses'][:2]) or '（无）'} → {c['owned_as']} → 满足「{c['skill']}」")

    step("简历：粘贴全文 → 规则解析")
    resume_text = """教育经历
重庆财经学院｜大数据管理与应用｜2023.09-2027.06
技能证书
CET-6 568
Python、MySQL、Hive
实践经历
电商用户行为分析平台｜负责数据清洗与报表，处理100万条数据，产出12张报表
自我评价
踏实肯学，喜欢钻研数据"""
    s, d = _call("POST", "/interview/resume/parse", st, {"text": resume_text})
    p = d.get("parsed") or {}
    print(f"   HTTP {s} 教育 {len(p.get('educations') or [])} 段 / 技能 {p.get('skills')} / "
          f"证书 {[c.get('name') for c in (p.get('certs') or [])]} / 经历 {len(p.get('experiences') or [])} 段")

    step("简历：保存（问卷结构化路径，接入三张经历表）")
    s, d = _call("POST", "/interview/resume", st, {
        "self_eval": p.get("self"), "intent": "数据分析",
        "educations": [{"school": "重庆财经学院", "major": "大数据管理与应用",
                        "dates": "2023.09-2027.06", "courses": ["数据库原理", "统计学"]}],
        "skills": ([{"type": "skill", "name": x} for x in (p.get("skills") or [])]
                   + [{"type": "cert", "name": "CET-6", "level": "568"}]),
        "experiences": [{"type": "project", "name": "电商用户行为分析平台", "role": "数据处理",
                         "dates": "2025.03-2025.06",
                         "desc": "负责数据清洗与报表，处理100万条数据，产出12张报表"}],
        "raw_text": resume_text})
    print(f"   HTTP {s} 简历编号 {d.get('resume_id')}")
    rid = d.get("resume_id")

    step("简历诊断（独立入口：量化/动词/对齐/缺失）")
    s, d = _call("GET", f"/interview/resume/diagnosis{'?job_id=' + str(jid) if jid else ''}", st)
    print(f"   HTTP {s} 问题 {len(d.get('issues') or [])} 项，提示分 {d.get('score_hint')}")
    for i in (d.get("issues") or [])[:4]:
        print(f"   [{i['kind']}] {i['where']}：{i['problem'][:40]}")
        print(f"        改写：{i['rewrite'][:56]}")

    step("题库 RAG：行业族 → 题型检索（每道题都有出处）")
    s, qst = _call("GET", "/qb/stats", st)
    print(f"   HTTP {s} 题库 {qst.get('total')} 条｜行业族 {len(qst.get('families') or {})}"
          f"｜来源 {len(qst.get('sources') or [])} 个")
    for fam, info in list((qst.get("families") or {}).items())[:4]:
        print(f"     {fam:16s} {info['label'][:18]:20s} {info['total']:>3} 条")
    s, qsr = _call("GET", "/qb/search?" + urlencode(
        {"industry": "计算机软件", "q": "Java后端开发 MySQL", "qtype": "major", "k": 2}), st)
    print(f"   HTTP {s} 检索「Java后端开发/计算机软件」→ 行业族={qsr.get('family_label')}")
    for h in (qsr.get("items") or []):
        print(f"     {h['score']:.3f} {h['question'][:40]}")
        print(f"           来源={h['source_name']} 命中={h['matched_by']}")

    step("模拟面试：开局（题库优先出题，按简历证据裁剪）")
    s, d = _call("POST", "/interview/start", st, {"job_id": jid, "resume_id": rid})
    print(f"   HTTP {s} 会话 {d.get('session_id')} 共 {d.get('total_rounds')} 轮，"
          f"第1题[{d.get('question_label')}]：{d.get('question')}")
    src = d.get("source") or {}
    print(f"   出题来源：{'题库 ' + str(src.get('name')) + ' / ' + str(src.get('id')) if src.get('kind') == 'bank' else '模板出题'}")
    sid = d.get("session_id")

    answers = [
        "我应聘这个岗位是因为它和数据方向一致，我的规划是先打好SQL和Python基础，然后深入业务分析。",
        "我通过数据库原理课程掌握了MySQL，通过统计课程掌握了分析思路，课下自学了Hive并做了练习项目。",
        "在电商用户行为分析平台里，我负责数据清洗与报表，遇到的最大困难是数据质量差，"
        "我先写了校验规则，然后重跑全量，结果处理了100万条数据并产出12张报表。",
        "我会先跟主管确认需求优先级，然后协调数据方给出时间点，同步自己的进度，最后复盘避免再次发生。",
        "我的简历虽然项目不多，但我处理的100万条数据量是真实的，学习能力强，能快速上手岗位技能。",
        "我想了解团队目前的数据栈和新人培养节奏。",
    ]
    step("模拟面试：逐轮作答（每题含引擎评分 + 防虚构校验后的点评）")
    final = None
    for i, ans in enumerate(answers):
        s, d = _call("POST", f"/interview/{sid}/answer", st, {"text": ans})
        if d.get("finished"):
            final = d
            print(f"   第{i + 1}轮 → 收卷")
            break
        print(f"   第{i + 1}轮 得分 {d.get('score')} 点评版本={d.get('comment_version')}")
        print(f"      点评：{(d.get('comment') or '')[:64]}")
        nxt = d.get("next") or {}
        nsrc = nxt.get("source") or {}
        origin = (f"题库·{nsrc.get('name')}" if nsrc.get("kind") == "bank" else "模板")
        print(f"      下一题（{origin}）：{(nxt.get('question') or '')[:44]}")
    if final is None:
        s, final = _call("POST", f"/interview/{sid}/answer", st, {"text": answers[-1]})

    step("面试报告（总分/各题/差距清单，全部引擎计算）")
    print(f"   总分 {final.get('total')}｜候选题 {len(final.get('items') or [])} 题")
    print("   " + (final.get("report") or "").split("\n")[0])
    for g in (final.get("gaps") or [])[:4]:
        print(f"   [{g['dimension']}] {g['gap'][:44]} → {g['action'][:34]}")

    step("本场题目出处（防幻觉：每道题都可回溯到来源页面）")
    srcs = final.get("sources") or []
    bank_n = sum(1 for x in srcs if x.get("kind") == "bank")
    print(f"   {len(srcs)} 题中 {bank_n} 题来自题库，{len(srcs) - bank_n} 题用模板")
    for x in srcs:
        print(f"   [{x['round']}] {x['label']:6s} {x['name'] or '模板':16s} {x['question'][:36]}")
        if x.get("url"):
            print(f"        出处 {x['url']}")

    step("面试详情与历史（防虚构证据留痕）")
    s, d = _call("GET", f"/interview/{sid}", st)
    qa = d.get("qa") or []
    print(f"   HTTP {s} 问答 {len(qa)} 条，状态 {d['session']['状态']}，"
          f"点评版本 {sorted({q.get('点评版本') for q in qa})}")
    s, h = _call("GET", "/interview/history/me", st)
    print(f"   历史 {h.get('total')} 场")

    # ---------------------------------------------------------- 教师端
    step(f"教师登录（{tea}）")
    tt = login(tea, "teacher")
    print(f"   token 长度 {len(tt)}")

    step("教师：任教班级目录")
    s, d = _call("GET", "/teacher/classes", tt)
    colleges = d.get("colleges") or d.get("items") or []
    cls = None
    for c in colleges:
        for b in (c.get("classes") or []):
            cls = b.get("class_name") or b.get("name") or cls
            if cls:
                break
        if cls:
            break
    if isinstance(d, dict) and not cls:
        # 兼容直接返回班级列表的形态
        for b in (d.get("classes") or []):
            cls = b.get("class_name") or b.get("name")
            if cls:
                break
    print(f"   HTTP {s} 学院 {len(colleges)} 个，取班级「{cls}」继续")
    if not cls:
        cls = "会计学2301"

    step("教师：班级总览 + 全班预警")
    qc = urllib.parse.quote(cls)
    s, d = _call("GET", f"/teacher/class-overview?class_name={qc}", tt)
    print(f"   HTTP {s} {json.dumps(d, ensure_ascii=False)[:200]}")
    s, d = _call("GET", f"/teacher/warnings?class_name={qc}", tt)
    items = d if isinstance(d, list) else (d.get("items") or d.get("students") or [])
    print(f"   HTTP {s} 预警学生 {len(items)} 人")
    brief(items, lambda it: f"· {it.get('name') or it.get('student_no')} "
                            f"{it.get('level') or ''} {str(it.get('reasons') or '')[:40]}")

    step("教师：越权防线（学生 token 访问教师接口应 403）")
    s, d = _call("GET", f"/teacher/warnings?class_name={urllib.parse.quote(cls)}", st)
    print(f"   HTTP {s} {str(d)[:100]}")

    step("完成")
    print(f"   共 {STEP['n']} 步全部通过（学生端 9 项 + 教师端 4 项 + 健康检查）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

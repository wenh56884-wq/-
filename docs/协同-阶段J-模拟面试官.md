# 阶段J·模拟面试官——三端协同看板（2026-10-27 18:18）

> 本文档是三端（WorkBuddy / Claude Code / CodeBuddy）唯一的协同事实源。
> **谁要改别人的文件，先在这里登记，等 owner 确认；不登记就改 = 打架。**
> 每次开工/收工各更新一次「变更记录」。

## 0. 作战纪律（硬规则）

1. **文件归属制**：只改自己名下的文件（见 §2）；跨归属改动先在 §5 登记，由 owner 改。
2. **十分钟冷静期**：动手前看 mtime；若目标文件 10 分钟内被别人改过，停手，先问。
3. **禁止 `git add -A`**：只 stage 自己的文件；绝不把别人的 WIP 混进提交。
4. **测试排他**：默认只跑自己的测试文件；全量 `pytest tests\ -q` 必须先确认没有别的 pytest 在跑（`Get-CimInstance Win32_Process` 查），并在 §5 登记开始/结束。
5. **数据与端口**：共享 MySQL `qihang`、DuckDB、8000/8001 端口；同一时间只允许一个人重灌数据/重启服务；不要为了自己测试清空别人的表。
6. **接口变更先公告**：后端字段/路由一变，先在 §4 记一行，前端按表适配；禁止前端猜字段。
7. **不重构、不美化别人的文件**；不移动/改名别人的文件。
8. **收工三件套**：改了什么 / 怎么验证（完整输出）/ 已知问题，贴到 §5。

## 1. 角色与目标

| 角色 | 定位 | 本轮目标 |
|---|---|---|
| WorkBuddy | **主导方**：模拟面试官后端全链路 | engine / router / DB / eval / e2e 冒烟 |
| Claude Code | **智能体开发 + 协同主持**：Agent 层与测试门禁 | `agents/interviewer.py`、agent 测试、跨端验收 |
| CodeBuddy | **前端与联调** | 面试 Vue 页、路由/菜单、`npm run build`、浏览器联调 |

## 2. 文件归属（冻结区）

| Owner | 文件 |
|---|---|
| **WorkBuddy** | `engine/interview.py`、`app/routers/interview.py`、`app/main.py`、`scripts/init_db.py`、`db/interview_tables.sql`、`scripts/eval_interview.py`、`data/eval/interview_cases.json`、`tests/test_interview.py`、`scripts/demo_interview.py`、`scripts/_tmp_itv_*.py` |
| **Claude Code** | `agents/interviewer.py`、`tests/test_interviewer.py`、`docs/协同-阶段J-模拟面试官.md` |
| **CodeBuddy** | `web/src/views/InterviewRoom.vue`、`web/src/router/index.js`、`web/src/layout/ShellLayout.vue` |
| **共享只读** | `AGENTS.md`、`pytest.ini`、`requirements.txt`、`.env`、`engine/interview.py` 的公共函数签名 |

## 3. 当前状态（18:18）

### WorkBuddy
- ✅ 6 张表已建：`简历/简历教育经历/简历技能证书/简历实践经历/面试会话/面试问答`。
- ✅ 离线评测 20 条 **5/5 PASS**（18:05）：提纲 20/20、防虚构 20/20、合法引文 17/17、一致性 20/20、差距 16/16。
- ✅ `tests/test_interview.py` 20 条引擎测试通过（与我的 7 条同跑 27 passed）。
- ✅ P0-2 部分修复：`_load_resume()` 已用 SQL `AS` 英文别名对齐引擎键（18:12）。
- ❌ **P0-2 残留：`主修课程` 仍是 JSON 字符串**。pymysql 2.2.8 对 JSON 列（type 245）无转换器，返回 `str`；现写法 `for c in (e.get("courses") or [])` 会逐字符拆开，专业题变成「你学过[」。修法：`json.loads(e.get("courses") or "[]")`。
  **已在真实库复现**：`面试会话 #5` 的提纲第 2 题原文 =「简历里提到你学过[，请讲讲它和目标岗位的关系。」
- ❌ **P0-3 未修：`_finish()` 重算分数仍只传 `简历原文`**，比答题时少了 JD 技能标签 + 经历描述，报告逐题分可能与答题时返回/落库的 `面试问答.评分` 不一致。
  **已在真实库复现**：`面试会话 #5` 落库分数 54.57 / 30.50 / 36.25，报告里却是 54.07 / 25.5 / 35.75。
- ⚠️ `tests/test_interview.py` 在 import 时执行 `os.environ.setdefault("AGENT_LLM_DRAFT","0")`，会污染同一 pytest 进程里的其他测试模块；建议改成 `autouse` fixture + `monkeypatch.setenv`。
- ⚠️ `tests/test_interview.py` 使用未注册的 `pytest.mark.interview`，pytest 会告警；建议在 `pytest.ini` 注册 marker（共享文件，登记后再改）。

### Claude Code（本轮）
- ✅ `tests/test_interviewer.py` 7 条离线测试：未答不计分、合法引文一次过、编造引文重试→降级、重试 prompt 带驳回原因、LLM 不可用立即降级、环境开关、报告数字原样引用。
- ✅ 修 `agents/interviewer.py` 两个缺陷：重试不带 feedback（空转）、`generate_reply()` 返回 `None` 被 `str()` 成 `"None"`（白跑重试）。
- ✅ 解决测试串扰：我的测试在 `_fake_llm()` 里显式 `monkeypatch.setenv("AGENT_LLM_DRAFT","1")`，与 WorkBuddy 的模块级 `0` 共存。
- ✅ 与 WorkBuddy 的 20 条测试同跑：**27 passed**（仅剩 marker 告警）。

### CodeBuddy
- ✅ `web/src/views/InterviewRoom.vue` 已产出：简历三路径（粘贴/上传/问卷）、诊断、岗位选择、逐题问答、报告、历史。
- ✅ `web/src/layout/ShellLayout.vue` 已加「模拟面试」菜单（`/student/interview`）。
- ✅ **构建阻断已解除**：`web/src/router/index.js:33` 的逗号已于 18:14:45 补上；`npm run build` 于 18:15:12 产出新的 `web/dist/index.html`。
- ❌ **P1 显示字段漂移（后端 18:12 改英文别名后前端未跟上）**：
  - 第 69 行 `resume.educations.map(e => e['学校'] ...)` → 现在行里是 `school/major`，页面会显示 `undefined｜`；
  - 第 73 行 `e['名称']` → 现在行里是 `name`，经历标题会空白。
  - 修法：`e.school`、`e.major`、`e.name`（`resume.certs` 已经是 `{name, level}`，无需改）。
- ✅ API 契约与后端一致（已逐项核对：start 返回 `session_id/total_rounds/round/question...`；answer 返回 `score/comment/next` 或 `finished/report`；history 用中文键 `编号/状态/总分`）。

## 4. 接口契约（后端已注册 `/interview`；8000 端口 uvicorn 无 `--reload`，改后端需重启）

| 方法 | 路径 | 入参 | 返回要点 |
|---|---|---|---|
| POST | `/interview/resume/parse` | `{text}` | `parsed{self,educations,skills,certs,experiences}` |
| POST | `/interview/resume/upload` | multipart `.docx/.txt` | 同上，不入库 |
| POST | `/interview/resume` | `{self_eval,intent,educations[],skills[],experiences[],raw_text}` | `{resume_id}`，版本只增不删 |
| GET | `/interview/resume/me` | — | `{resume}`（中文列 + 引擎英文键） |
| GET | `/interview/jobs?keyword=&limit=` | — | `{total,items:[{id,title,company,city,education,skill_tags}]}` |
| GET | `/interview/resume/diagnosis?job_id=` | — | `{engine_version,score_hint,strengths,issues[]}` |
| POST | `/interview/start` | `{job_id?,resume_id?,max_rounds=6}` | `{session_id,total_rounds,round,question_type,question_label,question}` |
| POST | `/interview/{sid}/answer` | `{text}`（`null`=跳过） | 未结束：`{round_done,score,comment,comment_version,next}`；结束：`{finished,total,report,gaps,items}` |
| GET | `/interview/{sid}` | — | `{session,outline,qa}` |
| GET | `/interview/history/me` | — | `{total,items:[{编号,岗位名称,状态,总分,…}]}` |

鉴权：学生 JWT；身份由后端 `require_student` 注入，前端**不得**传 `student_id`（铁律 2）。

## 5. 变更记录 / 阻塞与交接

| 时间 | 谁 | 事项 | 状态 |
|---|---|---|---|
| 18:03 | Claude Code | 新增 7 条 agent 测试 + 修 2 个 agent 缺陷 | 完成 |
| 18:05 | WorkBuddy | eval 合法引文 17/18 → 17/17，5/5 PASS | 完成 |
| 18:12 | WorkBuddy | `_load_resume` 改 SQL 别名，P0-2 部分修复 | 完成 |
| 18:13 | CodeBuddy | 新增 `InterviewRoom.vue` + 路由 + 菜单 | 完成 |
| 18:14 | CodeBuddy | `npm run build` 失败：router 缺逗号 | 18:14:45 已修 |
| 18:15 | Claude Code | 发现 `AGENT_LLM_DRAFT` 测试串扰；已在自己的测试里隔离 | 完成 |
| 18:16 | Claude Code | 复核 `主修课程` JSON 仍被逐字符拆开（pymysql 无 JSON 转换器）；真实库会话 #5 提纲已出现「你学过[」 | **待修（WorkBuddy）** |
| 18:17 | Claude Code | 复核 `_finish()` evidence 仍未统一；真实库会话 #5 落库分与报告分全部不一致 | **待修（WorkBuddy）** |
| 18:15 | CodeBuddy | `npm run build` 成功，`web/dist` 已更新 | 完成 |
| 18:18 | Claude Code | 发现前端简历展示仍用中文键（`e['学校']/e['名称']`），与后端英文别名漂移 | **待修（CodeBuddy）** |

### 待办队列（按优先级）
1. **[WorkBuddy]** `_load_resume()` 的 `courses` 用 `json.loads`；`_finish()` 与答题路径共用 `_evidence()`（或直接复用 `面试问答.评分`）。
2. **[CodeBuddy]** `InterviewRoom.vue` 第 69/73 行改用 `e.school / e.major / e.name`；改完重新 build。
3. **[WorkBuddy]** `tests/test_interview.py` 的环境变量改为 autouse fixture；在 `pytest.ini` 注册 `interview` marker（共享文件，先登记）。
4. **[Claude Code]** 等 P0-2/P0-3 修完，补一条 router→engine 数据形状回归测试 + 点评数值校验（铁律 1）。
5. **[全员]** 全量 `pytest tests\ -q` 排他复跑一次；`scripts/demo_interview.py` 走通后再提交。

## 6. 验证门禁（每次交付必须贴完整输出）

```powershell
# 1) Agent + 引擎测试（两个文件必须同跑，验证无串扰）
.venv\Scripts\python.exe -m pytest tests/test_interview.py tests/test_interviewer.py -q

# 2) 离线评测（WorkBuddy）
.venv\Scripts\python.exe scripts/eval_interview.py

# 3) 前端构建（CodeBuddy；先把 router 逗号修掉）
cd web; npm run build

# 4) 全量回归（排他；先确认没有别的 pytest 进程）
.venv\Scripts\python.exe -m pytest tests\ -q
```

**当前门禁结果（18:18）**
- `pytest tests/test_interview.py tests/test_interviewer.py -q` → **27 passed, 1 warning**（warning = 未注册 marker）。
- `scripts/eval_interview.py` → **5/5 PASS**。
- `npm run build` → **PASS**（18:15:12 产出新 dist）。
- 全量回归 → 未跑（等 P0 修完、排他执行）。

## 7. 已知风险

- 8000 端口仍是 15:02 启动的旧进程（无 `--reload`），`/interview` 要重启才生效；8001 是 18:12 起的新服务，联调以 8001 为准。
- 面试相关表目前无真实数据；e2e 脚本会写库，跑之前先确认没有别人在重灌/演示。
- `scripts/demo_interview.py` 头部注释还写着 `_smoke_interview.py`，且 `sys.path.insert` 写死 `D:\qihang`；演示前统一改成 `Path(__file__).resolve().parent.parent`。

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
- ✅ **P0-2 已修（Claude Code 接管，18:22）**：新增 `_json_list()`，`主修课程` 先 `json.loads` 再取列表；空/坏 JSON → `[]`。真实库复核：`_load_resume()` 的 `courses=[]`，提纲不再出现「你学过[」。
- ✅ **P0-3 已修（Claude Code 接管，18:22）**：新增 `_evidence()`，答题与收卷共用同一证据集（简历原文/自评 + 岗位技能 + 经历描述）。真实库复核：`面试会话 #5` 重算分 54.57 / 30.5 / 36.25，与落库分逐题一致。
- ⚠️ `tests/test_interview.py` 在 import 时执行 `os.environ.setdefault("AGENT_LLM_DRAFT","0")`，会污染同一 pytest 进程里的其他测试模块；建议改成 `autouse` fixture + `monkeypatch.setenv`。
- ⚠️ `tests/test_interview.py` 使用未注册的 `pytest.mark.interview`，pytest 会告警；建议在 `pytest.ini` 注册 marker（共享文件，登记后再改）。

### Claude Code（本轮）
- ✅ `tests/test_interviewer.py` 7 条离线测试：未答不计分、合法引文一次过、编造引文重试→降级、重试 prompt 带驳回原因、LLM 不可用立即降级、环境开关、报告数字原样引用。
- ✅ 修 `agents/interviewer.py` 两个缺陷：重试不带 feedback（空转）、`generate_reply()` 返回 `None` 被 `str()` 成 `"None"`（白跑重试）。
- ✅ 解决测试串扰：我的测试在 `_fake_llm()` 里显式 `monkeypatch.setenv("AGENT_LLM_DRAFT","1")`，与 WorkBuddy 的模块级 `0` 共存。
- ✅ 与 WorkBuddy 的 20 条测试同跑：**27 passed**（marker 已由 WorkBuddy 注册）。
- ✅ **18:21 接管 P0 修复**（用户授权，单独提交）：`_json_list()` / `_evidence()` + 前端两处显示字段；新增 `tests/test_interview_router_contract.py` 5 条回归测试。**32 passed**。

### CodeBuddy
- ✅ `web/src/views/InterviewRoom.vue` 已产出：简历三路径（粘贴/上传/问卷）、诊断、岗位选择、逐题问答、报告、历史。
- ✅ `web/src/layout/ShellLayout.vue` 已加「模拟面试」菜单（`/student/interview`）。
- ✅ **构建阻断已解除**：`web/src/router/index.js:33` 的逗号已于 18:14:45 补上；`npm run build` 于 18:15:12 产出新的 `web/dist/index.html`。
- ✅ **P1 显示字段漂移已修（Claude Code 接管，18:22）**：`InterviewRoom.vue` 第 69/73 行改用 `e.school / e.major / e.name`；`npm run build` 通过。
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
| 18:18 | Claude Code | 发现前端简历展示仍用中文键（`e['学校']/e['名称']`），与后端英文别名漂移 | 18:22 已修 |
| 18:21 | Claude Code | **接管声明**：用户授权，冻结 `app/routers/interview.py`、`web/src/views/InterviewRoom.vue` 至 fix commit 完成；WorkBuddy/CodeBuddy 这两个文件暂停改动 | 完成 |
| 18:21 | WorkBuddy | 全量 pytest 结束；转做知识图谱，新增 `engine/kg.py`、`app/routers/kg.py`、`scripts/build_kg.py`、`data/kg/`（新 WIP，不属于面试提交） | 进行中 |
| 18:22 | Claude Code | 修 P0-2/P0-3 + 前端显示字段；新增 5 条路由契约测试；32 passed、eval 5/5、build PASS | 完成，待提交 |
| 18:35 | WorkBuddy | 二期 B/C 落地：`engine/kg.py`+`/kg` 路由+KgView；`engine/hybrid.py`（0.7/0.3）+工具层三段式理由+StudentHome 展示 | 完成 |
| 18:40 | WorkBuddy | `scripts/demo_full.py` 完整演示 21 步全通（含防虚构降级实录、越权 403） | 完成 |
| 18:44 | WorkBuddy | 全量 `pytest -m "not spark"` **342 passed**；spark 10 条本轮未跑（被并发会话 kill） | 完成 |
| 18:45 | WorkBuddy | **违规自述**：18:0x 用 `git add -A` 提交，把 Claude Code 的 `agents/interviewer.py`/`tests/test_interviewer.py`/本文件一并纳入 18d1bd3；之后各提交改为精确 add | 已纠 |
| 18:59 | WorkBuddy | spark 10 条**排他复跑通过**：`10 passed, 342 deselected in 467.97s`（JVM 冷启，全程无并发 pytest） | 完成 |
| 18:59 | WorkBuddy | 修 §4 待办 1/2：面试测试改 autouse fixture、demo 脚本去硬编码盘符 | 完成 |

### 待办队列（按优先级）
1. ~~**[WorkBuddy]** `tests/test_interview.py` 的环境变量改为 autouse fixture~~ → **已修（18:58）**：删掉模块级 `os.environ.setdefault`，改为 `@pytest.fixture(autouse=True)` + `monkeypatch.setenv` 逐条隔离；混跑 `test_interview + test_tools + test_api` 54 passed，确认无串扰。
2. ~~**[WorkBuddy]** `scripts/demo_interview.py` 头部仍写 `_smoke_interview.py`，且 `sys.path.insert(0, r"D:\qihang")` 写死盘符~~ → **已修（18:58）**：改为模块 docstring + `Path(__file__).resolve().parent.parent`；`BASE` 改读 `DEMO_BASE` 环境变量。
3. **[Claude Code]** 点评数值校验（铁律 1）：`verify_comment()` 目前只校验引文，不校验「引擎分被写成别的数字」；下一轮加数值白名单。
4. **[全员]** 全量 `pytest tests\ -q` 排他复跑一次（WorkBuddy 18:15 那轮已跑完，结论以排他复跑为准）。
5. **[全员]** 提交纪律：`git add -A` 已在 18:16 的提交里把三方改动混在一起；后续一律按路径 stage，知识图谱 WIP 不得混入面试提交。

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

**当前门禁结果（18:22，P0 修复后）**
- `pytest tests/test_interview.py tests/test_interviewer.py tests/test_interview_router_contract.py -q` → **32 passed**。
- `scripts/eval_interview.py` → **5/5 PASS**。
- `npm run build` → **PASS**（18:22:35 产出新 dist，9.98s）。
- 真实库只读复核：会话 #5 重算分 = 落库分（54.57 / 30.5 / 36.25）；`courses=[]`。
- 全量回归 → WorkBuddy 18:15 那轮已结束；修复后需排他复跑一次。

## 7. 已知风险

- 8000 端口仍是 15:02 启动的旧进程（无 `--reload`），`/interview` 要重启才生效；8001 临时服务已停止。演示/联调前用新进程启一次。
- 面试表已有 e2e 数据：6 份简历、5 场会话、21 条问答；e2e 脚本会继续写库，跑之前先确认没有别人在重灌/演示。
- `scripts/demo_interview.py` 头部注释与写死路径问题仍在（见待办 2），演示前修。
- WorkBuddy 的知识图谱 WIP（`engine/kg.py`、`app/routers/kg.py`、`scripts/build_kg.py`、`data/kg/`、`app/main.py`）不在本次面试 fix 提交范围内，提交时按路径排除。

## 8. 演示数据全覆盖（2026-10-27 18:35，Claude Code）

### 目标与结果
- **35 张 MySQL 表全部非空**（原空表：`预警阈值`、`班级预警阈值`、`学生通知已读`）。
- 新增 `scripts/seed_demo_coverage.py`（幂等，可重复运行）：
  - `预警阈值` 5 条（与 `engine/rules.py` 内置默认同值，页面可见、可改）；
  - `班级预警阈值` 1 条（AI2301 / attendance_rate / 权重 1.0，与默认同值，页面能看到 `source=class` 但不改变预警结果）；
  - `学生通知已读` 1 条（AI20230002，水位 8；演示学生 AI20230001 仍有 9 条未读）；
  - `学生扩展信息` 新增 9999 条（按学号哈希确定性生成四六级/政治面貌/意向城市/每周学时；已有 3701 不覆盖）；
  - 演示学生 `职业意向` 对齐为「考公」，与已提交的考公规划一致。
- 修复 `app/routers/exam.py`：列表查询 `tenant_id` → `` `租户编号` ``，招考页不再 500。
- 新增 `tests/test_api.py::test_exam_notices_list_returns_rows` 回归测试。

### 实测（TestClient / 真实库）
- 考试：在招 26 条（考公 5 / 考编 / 考研），列表、详情、筛选均 200。
- 岗位：`招聘岗位` 40 条、详情 200；`岗位` 池 2931 条、搜索/详情 200。
- 教师：AI2301 在册 580，均分 76.3，挂科率 0.45，预警分布 红 47 / 橙 45 / 黄 92 / 无 396；班级概览、预警名单、阈值、学生画像（含雷达四维 + GPA 趋势）、职业差距全部有数据。
- 学生（AI20230001 陈燕）：预警风险 10 / none；推荐 10 条；竞赛 8 条；未读通知 9 条；生涯规划「大四·考公」与已提交规划一致；简历 + 5 场面试历史。
- 知识图谱：3477 节点 / 21185 边；`/kg/stats`、`/kg/facets`、`/kg/neighborhood`、`/kg/jobs-by-skill`、`/kg/skills-by-major`、`/kg/explain` 全部 200。
- 前端 `npm run build` 通过（18:22）。

### 演示账号（当前库真实存在）
- 教师：`T001 / teacher@123`；班级 `AI2301`；学期 `2025-2026-2`。
- 学生：`AI20230001 / AI20230001`（学号即口令）。
- ⚠️ `docs/演示脚本.md` 里的 `AI2201 / AI2022001 陈鹏` 是旧数据集，当前库不存在；演示前需按上面账号改口播/操作。

### 已知非本次问题
- `tests/test_api.py::test_student_sees_only_self` 当前失败：WorkBuddy 正在做的混合推荐把 `recommend_version` 改为 `hybrid-v1`，测试仍断言 `v1.0`。属并行 WIP，待 WorkBuddy 收口时同步测试。
- 8000 旧进程（15:02 启动）不含 `/interview`、`/kg` 与考试修复，已重启为新进程。

## 9. Bento 前端改造（2026-10-27 18:50，Claude Code 主导）

### 设计系统（不引入 Tailwind，用项目内 CSS 等价实现）
- `web/src/styles/bento.css`：4 列网格 / `bento-span-2|3|4` / `bento-row-2` / 22px 圆角 / 20px 一致 gap / hover `-4px + scale(1.01)` / 阴影 `0 8px 30px rgba(0,0,0,.08)` / 260ms ease-out / 图标 group-hover `scale(1.1)` / 平板 2 列、手机 1 列 / `prefers-reduced-motion` 降级。
- `web/src/styles.css`：全站 `el-card` 20px 圆角 + Bento 阴影 + 悬停上浮；按钮/输入框 14px 圆角；主按钮 zinc-900；输入聚焦蓝环。
- 禁用：Tailwind 依赖（未安装）、嵌套 `el-card`、紫蓝渐变、直角、gap-1/2/10/12。

### 已完成（Phase 1）
- **登录页**：2×2 品牌渐变卡 + 2×2 登录卡 + 4 个 1×1 能力卡；演示账号更新为 `T001 / teacher@123`、`AI20230001 / AI20230001`。
- **教师看板**：全宽筛选卡 + 4 个指标瓦片 + 2×2 班级概貌（风险分段条/图例/快捷入口）+ 2×1 图表 + 2×1 高风险 Top5 + 全宽职业目标分布 + 全宽预警名单（新增归因摘要列）。
- **学生首页**：生涯规划 2×2 大卡 + 本人信息卡 + 快捷入口（面试/岗位/招考/图谱）+ 全宽岗位推荐；原业务逻辑与混合推荐字段不动。
- **岗位库**：4 个指标瓦片 + 全宽筛选卡 + 全宽行业分布 + 全宽列表；查询/分页/详情抽屉逻辑不变。
- **招考信息**：全部/考公/考编/考研 4 个可点选指标卡（全部=合计）+ 全宽筛选卡 + 全宽公告列表；筛选/分页/详情抽屉逻辑不变。
- **学生档案**：全宽筛选 + 职业目标条 + 学生名单 2×1 + 画像详情 2×1（雷达/成绩趋势）；顺带修 `loadDetail()` 在骨架未撤时初始化 ECharts 导致图表空白的 bug。
- **模拟面试**：两个 tab 内各一层 Bento 网格；录入 2×2、当前题 2×2、报告/历史全宽；新增常驻「怎么练」引导卡填充右侧。
- **知识图谱**：5 个统计卡按 2/1/1 + 2/2 跨列，邻接图 2×2，技能→岗位 / 专业→课程链各 2×1，解释链全宽。
- **全局 Bento 化**：其他页面的 `el-card` 立即获得 20px 圆角、Bento 阴影与悬停，不必逐页重写。
- 视觉截图（不入库）：`logs/screenshots/01-login.png` ~ `08-student-kg.png`（登录/教师看板/学生首页/岗位/招考/学生档案/面试/图谱）。
- 构建：`npm run build` 通过（15.89s）。

### Phase 2 分工（防打架）
- **全部页面完成（Claude Code）**：登录、教师看板、学生档案、学生首页、岗位库、招考信息、模拟面试、知识图谱；最终 `npm run build` 通过（9.50s）。
- **CodeBuddy 交叉验收**：独立复跑 `npm run build`、抽查 8 张截图、确认无横向溢出/无嵌套 el-card/主按钮非蓝色；发现问题按文件归属登记。
- 每页改造前先在看板登记；同一文件同一时间只允许一个 owner 改；改完 `npm run build` 并把截图/构建输出贴回本节。
- 规则：外层 `.bento-page`、内层 `.bento-grid`；大卡 `span-2 row-2`、中卡 `span-2`、小卡 1×1；统一 gap 20；不在 `bento-card` 里再套 `el-card`；主按钮不用 Element 蓝。

## 10. 题库 RAG 覆盖扩展（2026-10-27 19:20，Claude Code 配合 WorkBuddy）

### 用户目标
全国岗位面试题做成 RAG；模拟面试贴近真实场景。

### 现状（WorkBuddy 已完成，20:00 前）
- `engine/question_bank.py`：8 行业族 / 147 题 / 17 个公开来源；TF-IDF(char 2-3)+岗位族+考点三路排序；无出处不入库；题库优先、模板兜底。
- 题库表 `面试题库`/`面试题库导入日志`、加载/评测脚本、`/qb/*` API、前端出处展示。
- 测试 30 passed；评测：可回溯 100%、岗位覆盖 78.67%、检索命中 100%、题面一致 100%。

### Claude Code 接管范围（不碰 WorkBuddy 文件）
- `engine/question_bank.py`：新增行业族（物流/教育/新媒体设计/物业/酒店/通信/农业/法律/公共事业）+ **空行业按岗位名推断族**（当前 600 个岗位行业为空，多为开发/测试，全部落到 general）。
- `data/question_bank/`：新增上述行业族的可回溯语料（每题带 source_url/考点/答案要点）。
- 新增测试：行业推断 / 新族检索 / 空行业覆盖。
- **不改** `engine/interview.py`、`app/routers/interview.py`、`db/*`、`web/*`；这些由 WorkBuddy 继续。
- 下一步交接 WorkBuddy：`_bank_pick(job, qtype)` 增加 resume 参数做简历感知排序；答题后按得分/漏点决定是否追问（可用题库同族 probe 题）。

### 10.1 扩展结果（Claude Code，2026-10-27 19:25）
- 题库从 147 → **234 题**，行业族 8 → **17**（新增物流/教育/新媒体设计/物业/酒店/通信/农业/法律/公共事业 + IT 补题），来源 **28** 个。
- `engine/question_bank.py`：新增 9 个行业族规则 + `infer_family()`（行业为空时按岗位名/技能推断）；`retrieve_for_job` 已接入推断。WorkBuddy 的 `query_text` 简历感知检索保留。
- `engine/interview_probe.py`（新增）：真实追问决策模块——`should_probe()` 判断浅答/漏考点，`pick_probe()` 从同族题库取未用过的题，`probe_plan()` 返回可直接落库的追问（含 source_url）。8 条测试通过；环境开关 `INTERVIEW_PROBE`。
- `scripts/eval_question_bank.py`：职位覆盖率改用 `infer_family`（与线上海选口径一致）。
- `data/question_bank/`：新增 10 个语料文件（含 `it_extra.json`），每题带 source_url/考点/答案要点。
- MySQL `面试题库` 已导入 **234 条**；服务已重启，`/qb/stats` 线上返回 234/17/28。

### 10.2 评测（排他）
- 可回溯率 100%；覆盖矩阵 **96/96 = 100%**；职位覆盖 **99.87%**（1512/1514）；检索命中 ≥4 轮 100%（200 样本）；平均 **6.00/6** 轮来自题库；题面一致 100%；0 个岗位拿不到题。
- 仅剩 2 个 general 岗位（空标题/多元化集团）无专项族；不影响主流程。

### 10.3 交接 WorkBuddy（必须接，否则“真实场景”只完成一半）
1. **追问接线**：`app/routers/interview.py::interview_answer` 在 `item = score_answer(...)` 后调用
   `plan = interview_probe.probe_plan(job_snapshot, q["type"], item, answer, used_ids=[...])`；
   命中则把 `plan["question"]` 作为下一题返回（`问题类型='probe'`，来源写 `bank_id/source_url`），
   同一主问题最多追问 1 次（需在 `面试会话` 加 `追问次数` 或按 QA 行推断）。
2. **岗位池扩展**：`/interview/jobs` 与 `_load_job` 目前只读 `招聘岗位`（40 条）；全国 `岗位` 池 2931 条未进选择器。
   建议加 `source` 参数（recruit/pool）或 UNION，映射 `岗位名称/企业/城市/学历/技能标签/岗位描述`。
3. **`/qb/search`**：行业为空时也应走 `infer_family`（目前只按 industry 归并），否则调试接口看不到空行业命中。
4. 提交边界：题库核心文件仍是 WorkBuddy 的 WIP；本轮的 `data/question_bank/*`、`engine/interview_probe.py`、`tests/test_interview_probe.py`、`tests/test_question_bank_infer.py` 可一并收进题库提交。

## 11. 题库 RAG 收工登记（2026-10-27 19:40，WorkBuddy）

### 按 §10 分工，WorkBuddy 本轮实际改动（不含 Claude Code 名下文件）
| 文件 | 改动 |
|---|---|
| `db/question_bank.sql`（新） | `面试题库` + `面试题库导入日志` 两张表；题目编号唯一；`来源链接` NOT NULL |
| `engine/question_bank.py`（New，**与 Claude Code 共有**） | 我的部分：语料加载门禁（缺 source_url 直接抛错）、TF-IDF(char 2-3)+岗位族+考点三路打分、`stats()` 覆盖矩阵、`retrieve/retrieve_for_job`；Claude Code 的部分：行业族扩到 17、空行业按岗位名 `infer_family` |
| `engine/interview.py`（改） | `build_outline` 改「题库优先、模板兜底」，`source` 随提纲落库；新增 `rubric_from_bank` / `_bank_pick` / `_bank_query` / `_resume_affinity`；修 major 模板在「岗位无技能」时硬扯课程与岗位关系的荒谬问法 |
| `app/routers/interview.py`（改） | 新增 `_rubric_of_q`：**修掉评分时用 `rubric_of()` 重算、把题库考点覆盖掉的问题**；开局/作答/报告回传 `source`；报告新增 `sources` 逐题出处 |
| `app/routers/question_bank.py`（新） | `/qb/stats`、`/qb/sources`、`/qb/search`、`/qb/reload`（只读，不提供写接口，防止绕过语料塞无出处题） |
| `scripts/load_question_bank.py`（新） | 语料校验 → 入库 → 写导入日志；缺来源条目拒收并记原因 |
| `scripts/eval_question_bank.py`（新） | 5 项指标：可回溯率 / 覆盖矩阵 / 职位覆盖率 / 检索命中率 / 题面一致率 |
| `tests/test_question_bank.py`（新，35 条） | 语料门禁、行业归一化、检索兜底、排序确定性、考点不被覆盖、简历感知 |
| `web/src/views/InterviewRoom.vue`（改） | 每题显示「本题出自 XX（链接）」或「模板出题」；报告页新增逐题出处表 |
| `scripts/demo_full.py`（改） | 新增 [13] 题库检索、[17] 本场题目出处两步，演示 23 步 |

### 我**没**动 Claude Code 名下的内容
- `data/question_bank/` 新增的 9 个行业族语料、`infer_family`、`tests/test_question_bank_infer.py` 均未改动。
- `scripts/init_db.py` 里 `db/question_bank.sql` 的注册是 Claude Code 加的，我未改。

### 实测（本轮，语料 222 条 / 15 族 / 26 来源）
```
可回溯率 100.00%
覆盖矩阵 100.00% (84/84)
职位覆盖率 91.74% (1389/1514)
检索命中率（≥4轮来自题库）100.00% (样本 200)
平均题库轮次 5.99 / 6
题面一致率 100.00% (校验 360 条)
简历感知：400 个岗位中 177 场（44.3%）的专业题会因简历不同而不同
门禁：pytest -m "not spark" 408 passed
```

### 已修的一个 P0（与 §4 待办 3 同类）
`app/routers/interview.py` 原来在答题与收卷两处都用 `rubric_of(q["type"], job_skills)` **重算**评分要点，
提纲里存的题库考点被丢弃 → 专业题答对得分低、答偏得分高。已改为 `_rubric_of_q()` 优先取提纲内 rubric。

### 交接给 Claude Code
- `_bank_pick(job, qtype, resume)` 已支持简历感知（`_bank_query` + `_resume_affinity`，候选窗口 k=8、亲和度权重 0.35）。
- 未做：答题后按漏点追问（同族 probe 题）。若要做，建议在 `interviewer.run_turn` 之后加一次 `_probe_pick`，并把追问记为 `轮次=x.y`，避免破坏 `当前轮次` 整型语义。

## 11. 成绩单（2026-10-27 19:45，Claude Code）

### 目标
Web 端学生/教师都能看学生**每一学年、每一学期、每一门课的全部成绩**。

### 实现
- `engine/grades.py`：纯函数聚合——学年/学期/课程分组；同课多次记录逐条保留；课程汇总取最高分；学期/学年/总汇总给平均分、学分加权均分、学分、课程数、挂科数；缺失不补 0。
- `app/routers/grades.py`：
  - `GET /grades/me`（学生，学号只来自 JWT）；
  - `GET /grades/student/{student_no}`（教师，复用 `tools._fetch_student` 的租户 + 任教范围校验）；
  - 审计 `grades.view`，越权 403。
- `web/src/views/GradeReport.vue`：Bento 汇总卡 + 学期均分趋势 + 学年 tabs + 每学期全量成绩表（课程代码/名称/学分/成绩/第几次/重修/状态）。
- 入口：学生/教师侧栏「成绩单」、学生首页快捷入口、教师学生档案「查看成绩单」。
- 测试：`tests/test_grades.py` 3 条 + `tests/test_grades_api.py` 4 条；`npm run build` 通过（13.17s）。
- 截图：`logs/screenshots/09-teacher-grades.png`、`10-student-grades.png`。

### 口径
- 同一课程同一学期多次记录**逐条展示**（第几次按录入顺序）；
- 课程汇总取最高分；学期/学年加权均分按学分；
- 挂科按课程最高分判断（通过重修后不再计挂科）；缺失不出现在任何汇总里补 0。

## 12. 追问接入 + 全国岗位池 + 对话六项能力（2026-10-27 19:55，WorkBuddy）

> 本轮三件事：① 把 `engine/interview_probe.py` 追问引擎接进答题链路；② 岗位选择器从租户 40 条扩到全国 2931 条；③ `/chat` 从 7 个校园工具扩到六项能力（ChatBot / RAG 知识库 / PDF 问答 / 多轮记忆 / 联网+工具调用 / 工作流）。第 ③ 项是用户当轮改口后的最终口径，原提的「Agent 自动任务执行」「代码生成与分析」两项用户自己划掉了。

### 12.1 追问：为什么插一轮而不是记 `x.y`

原交接建议（§11 末尾）是把追问记成 `轮次=x.y`。**没有采纳**，因为收卷时 `zip(answers, outline)` 靠顺序对齐，小数轮次或空洞会让逐题得分串行错位。改为：

- `_insert_probe(outline, index, entry)` 插到本题之后，再把全表 `round` 重排成 `1..N` 连续整数；
- 追问预算 `_PROBE_MAX`（`INTERVIEW_PROBE_MAX`，默认 2）；`_used_bank_ids()` 用 `dict.fromkeys` 保序去重，同一考点不追问两次；
- `_build_probe_entry()` 取不到题库考点就返回 `None` 放弃追问——**不拿空 rubric 硬评**；
- 收卷 `items` 带 `is_probe`，`facts` 带 `probes`；报告 `sources` 里追问行有标记。

### 12.2 岗位池：双表并存，不猜池

| 池 | 表 | 规模 | 用途 |
|---|---|---|---|
| `national` | `岗位` | 2931 条 | 无租户维度、字段最全，选择器默认池 |
| `tenant` | `招聘岗位` | 租户在招池（演示库 40 条） | 含投递链接/状态，原有链路 |

两表 `编号` 各自独立会撞号，所以 `_load_job(cur, job_id, pool=None)` 必须显式传 `pool`（`None` = 先全国后租户的兼容路径），**不做「猜池」**。`GET /interview/jobs` 新增 `city/industry/pool/limit/offset` 并返回真实 `total`；新增 `GET /interview/jobs/facets` 给筛选下拉。`StartIn` 增 `job_pool`，`job_snapshot` 增 `industry/city/pool`（`industry` 必须保留，它是归族关键）。

### 12.3 六项能力：引擎定数，模型说话

新增模块（全部纯函数，可离线单测）：

| 文件 | 职责 |
|---|---|
| `engine/rag.py`（新，~420 行） | 类型白名单、按页抽取、切块、检索、**引用三道闸**、原文兜底 |
| `engine/kb_store.py`（新） | 路由与对话工具共用的取块口径，避免两处 SQL 漂移 |
| `engine/web_search.py`（新） | Serper → Bing 适配层，未配置如实降级 |
| `engine/workflow.py`（新） | 9 工具白名单、`validate/run/run_default`、`{{steps.x.y}}` 只取值 |
| `app/chat_service.py`（新） | 会话落库、`RECENT_TURNS=8`、`SUMMARY_TRIGGER=12`、`last_tool` 继承 |
| `db/rag_tables.sql`（新） | 6 张表：知识库文档/分块、对话会话/消息、工作流定义/运行 |

**引用三道闸**（`verify_citations`）：① 回答必须有 `[n]`；② `[n]` 必须在检索结果范围内；③ **带 `[n]` 的句子里出现的数字，必须能在被引分块原文里找到**，引号内文字必须逐字存在。第 ③ 条专治「引用是真的、数字是编的」。

**无命中反向约束**：知识库/联网都没命中时，回答里出现任何数字即判不通过，且必须说明「没有/未/查不到」——不许用模型记忆补一段看着合理的内容。

**不引向量库的理由**：本机 DeepSeek 只有 chat、无 embedding API，也没有 jieba/faiss/sentence-transformers。改用 sklearn TF-IDF(`char_wb`, 2-4 gram) + 2-gram 关键词覆盖，中文免分词、完全离线、同输入同排序。检索除绝对阈值 `min_score=0.03` 外，再按「低于首条 45% 视为噪声」过滤，解决 PDF 一页一块时无关页被带进引用。

### 12.4 本轮踩到的坑（都是真 bug，已修）

| 现象 | 根因 | 修法 |
|---|---|---|
| 第 2 页内容被标成第 1 页 | 跨页 overlap 把上页文字挂到下一页块 | `flush(carry=False)`；尾块合并仅在同页时做 |
| 引用编号合法但数字编造仍判通过 | 只校验了 `[n]` 范围 | 逐句数字核对；再把 `第 N 页/块` 剔掉避免误伤页码 |
| 引用里全角标点变半角 | `_clean` 里做了 NFKC | NFKC 只留在 `_norm()` 匹配阶段 |
| docx 整篇粘成一行 | 直接取 `<w:t>` 没切段 | 先按 `</w:p>` 切段再取 `<w:t>` |
| `/kb/docs` 列表 500 | COUNT 查询漏拼 `where` | `"SELECT COUNT(*) AS c" + base + where`，`params_count` 提前取 |
| 建表脚本 `created: []` | 首行 `--` 注释吃掉第一条 DDL | 先剔 `--` 行再按 `;` 切分 |
| 制度原文换行导致残句 | 按 `\n` 切句 | 先把 `\s*\n\s*` 折空再按句末标点切；截断**不补句号**（补了就不是原文子串，引用校验会驳回） |
| 改 `engine/` 后接口行为不变 | uvicorn 无 `--reload` | 每次改引擎必须 `Stop-Process` 再启 |

### 12.5 实测（本轮，演示库）

```
追问端到端：浅答「我会认真做。」→ 触发 probed，插入追问带上一轮原话锚点
  整场 4 轮开局 → 2 次追问 → 收卷 6 题
  轮次序列 [1,2,3,4,5,6] / is_probe [F,T,T,F,F,F] / probes=2 / sources=6，zip 对齐无错位

岗位池：GET /interview/jobs?pool=national → total=2931
        GET /interview/jobs/facets → 行业 81、城市 163

六项能力（scripts/demo_chat.py 九步）：
  [01] ChatBot / RAG(4 文档 5 块) / PDF / 记忆 / 工作流(2 个) = 可用
       联网搜索 = 未就绪（未配置密钥，如实说明）
  [03] 「报销的住宿标准是多少？」→ 能力=kb_search，引用 [1]《员工报销制度》第 1 块
  [04] 「那超标了怎么办」→ 沿用 kb_search，命中同一块「超标部分由个人自理」
  [05] PDF 问答 → 引用精确到「第 1 页」，无关第 2 页已被相对过滤掉
  [06] 联网 → 「当前没有配置联网搜索，我查不了实时信息。」（未编结果）
  [07] 「跑一遍求职体检」→ ✅ 本人学业预警 / ✅ 岗位推荐
  [08] 会话 4 条消息全部落库，assistant 带 [kb_search] 标记
  [09] 知识库自检：文档 4 / 分块 5 / 页数 5 / {'txt':2,'md':1,'pdf':1}

教师端工作流带参：POST /workflow/defs/2/run {class_name, term} → success
  三步 ✅ 班级概览(709ms) / ✅ 预警名单(414ms) / ✅ 能力差距(15788ms)，/workflow/runs 留痕

门禁：pytest -m "not spark" 454 passed, 10 deselected in 40.41s
      npm run build ✓ 12.92s（index 2,290.84 kB，仅 chunk 体积告警）
```

### 12.6 已知限制（不美化）

1. **联网搜索当前未就绪**：`/chat/capabilities` 明写 `[未就绪] 未配置密钥（SERPER_API_KEY / BING_SEARCH_KEY）`。代码路径已通（未配置时诚实降级、不编结果），但**真实搜索结果未验证**，需用户提供密钥后才能实测。
2. **PDF 样本是 ASCII 夹具**：`data/samples/reimbursement_policy.pdf` 由 `scripts/make_sample_pdf.py`（Helvetica 内置字体）生成，只验证「按页抽取 + 页码引用」通道，**不代表带嵌入字体的中文 PDF 抽取效果**。该文件已进 `.gitignore`（生成物，`seed_chat_demo.py` 缺文件时自动生成）。
3. 本轮未动 Claude Code 名下文件：`tests/test_question_bank_infer.py`、`data/question_bank/` 的新增语料、`infer_family` 均保持原样。

### 12.7 未提交遗留（供下一轮判断归属）

`scripts/start_qihang.bat`（mtime 18:54，早于本轮）有一行演示账号改动：大三 `AI20240001 刘杰 就业` → `AI20240004 孙鹏 考公`。**不是本轮改的，未纳入本次提交**，请 owner 认领。
`db/interview_tables.sql` 的索引名 `idx_redum` → `idx_reedu` 属纯笔误修正，已随本轮提交。

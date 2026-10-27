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

### 待办队列（按优先级）
1. **[WorkBuddy]** `tests/test_interview.py` 的环境变量改为 autouse fixture（模块级 `setdefault` 会污染同进程其他测试；我的测试已隔离，但其他模块仍可能中招）。
2. **[WorkBuddy]** `scripts/demo_interview.py` 头部仍写 `_smoke_interview.py`，且 `sys.path.insert(0, r"D:\qihang")` 写死盘符；演示前改成 `Path(__file__).resolve().parent.parent`。
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
- **全局 Bento 化**：其他页面的 `el-card` 立即获得 20px 圆角、Bento 阴影与悬停，不必逐页重写。
- 视觉截图（不入库）：`logs/screenshots/01-login.png`、`02-teacher-dashboard.png`、`03-student-home.png`。
- 构建：`npm run build` 通过（15.89s）。

### Phase 2 分工（防打架）
- `web/src/views/StudentHome.vue`：CodeBuddy 当前 WIP（混合推荐 +27 行）——**等它提交后**由 Claude Code 按 `bento.css` 重构；期间 CodeBuddy 不要再改这个文件。
- `TeacherStudents.vue` / `JobList.vue` / `ExamNotices.vue` / `InterviewRoom.vue` / `KgView.vue`：优先 CodeBuddy 用现有 `.bento-page / .bento-grid / .bento-card / .bento-span-*` 改造；Claude Code 负责验收与共享 CSS 调整。
- 规则：外层 `.bento-page`、内层 `.bento-grid`；大卡 `span-2 row-2`、中卡 `span-2`、小卡 1×1；统一 gap 20；不在 `bento-card` 里再套 `el-card`；主按钮不用 Element 蓝。

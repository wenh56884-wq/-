# AGENTS.md —— 启航项目宪法

> 本文件是施工 Agent（以及任何协作者）在本项目中的最高行为准则。
> 每一轮任务都必须逐条遵守下方「六条铁律」与「编码约定」，违反即停。

---

## 0. 项目背景

- **名称**：启航——基于大数据与多智能体协同的生涯与岗位匹配系统（高校教育信息化）
- **目标用户**：
  - 教师：学业预警、班级画像、职业差距分析
  - 学生：本人预警、岗位推荐
- **技术依据**：项目计划书（Spark / ClickHouse / MySQL / LangChain+LangGraph / FastAPI / 知识图谱 / 内容推荐）
- **交付时间**：2026 年 11 月 18 日演示

## 1. 运行环境（已实测，不要改）

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11，PowerShell |
| Python | 3.12，虚拟环境 `D:\qihang\.venv` |
| MySQL | 8.0.21，`127.0.0.1:3306`，库名 `qihang`，连接信息从 `.env` 读 |
| 分析层 | DuckDB（嵌入式文件 `D:/qihang/data/analytics.duckdb`），替代项目书里的 ClickHouse |
| LLM | DeepSeek：`langchain_openai.ChatOpenAI(base_url="https://api.deepseek.com", model="deepseek-chat")`，密钥从 `.env` 读 `DEEPSEEK_API_KEY` |
| 编排 | LangGraph |
| 服务 | FastAPI + uvicorn |
| 测试 | pytest |

## 2. 六条铁律（每轮都必须遵守）

### 铁律 1：计算确定性、表达生成性

所有**分数、排名、门次、比例、人数**等数值，必须由 `engine\` 下的 Python 确定性引擎
计算并返回结构化结果；任何调用大模型（DeepSeek / LangGraph 节点）的代码
**不得生成或修改数值**，只能原样引用引擎结果。

- 引擎输出 = 唯一数值真相源。
- 大模型只负责把结构化结果组织成自然语言。
- `agents\critic.py` 负责逐条回查输出中的数字，与引擎结果不一致即驳回（最多 2 次，
  超限降级为模板输出）。

### 铁律 2：身份只能来自后端登录态

`student_id` / `teacher_id` 由 FastAPI 从 JWT 登录态解析后注入，
**绝不允许**由对话文本、URL 参数、请求体或工具入参自由指定。

- 认证在 `app\auth.py` 完成，解析 JWT 后把身份写入请求上下文。
- `agents\tools.py` 中所有工具的 id 入参只接受后端注入值，不接受前端传参。
- 任何"按学号查询"的入口都必须先经过鉴权，再由后端取登录者身份。

### 铁律 3：多租户隔离

教师只能访问**自己租户内**班级学生的数据，隔离在**数据层**实现，
不靠前端隐藏入口。

- 租户隔离在 `engine\store.py` 的查询里通过 `tenant_id` 过滤实现。
- 即使伪造请求，数据层也不会返回越权行。
- 前端隐藏只是体验优化，不是安全边界。

### 铁律 4：小步交付

一次只完成用户指定的一件事；完成后**必须运行相关测试并贴出完整输出**。

- 不在一次任务里塞多个功能模块。
- 每一步交付都要有"改了什么 / 怎么验证 / 已知问题"三段汇报。
- 测试输出要完整粘贴，不截断、不粉饰。

### 铁律 5：不擅自扩大范围

只改用户指定目录内的文件；确需改其他文件，**先说明理由等用户确认**再动手。

- 任务边界以用户当轮指定为准。
- 跨目录改动必须先报备，获得明确同意后才执行。
- 不主动重构、不主动美化、不主动加功能。

### 铁律 6：不写密钥

一切密钥 / 口令只从 `.env` 或环境变量读取，
**禁止硬编码、禁止写进 git**。

- `.env` 已在 `.gitignore` 中，不入库。
- 代码里只能出现 `os.getenv` / `pydantic-settings` 读取。
- 示例值放 `.env.example`，标注 `REPLACE_ME`。

## 3. 智能体统一入口（agent-entry-v2，2026-10-29 修订）

智能体是系统的**统一对话入口**：用户用一句话就能调度系统全部能力，
智能体负责理解意图、编排工具、组织表达；数值仍由 engine 确定性计算
（铁律 1/2/3 原样适用，本节不改变任何铁律）。

### 工具注册表（全板块覆盖）

| 板块 | 学生端工具 | 教师端工具 | 数值来源 |
|---|---|---|---|
| 预警 | `my_warning` | `warning_list` / `class_overview` / `get_warning_thresholds` | engine.warning |
| 成绩 | `my_grades` | `student_grades` | engine.grades |
| 学业预测 | `my_forecast` | `student_forecast` | engine.forecast |
| 报考分析 | `my_career_forecast` | —（个人数据不出教师端） | engine.career_forecast |
| 岗位 | `my_recommendations` / `search_jobs` / `job_facets` | `search_jobs` / `job_facets` | engine.recommend / SQL 实查 |
| 图谱 | `kg_major_skills` / `kg_skill_jobs` / `kg_path` | 同左 | engine.kg |
| 招考 | `exam_notices` | `exam_notices` | `招考公告` 表实查 |
| 模拟面试 | `my_interviews` | —（只本人可见） | `面试会话` 表实查 |
| 题库 | `question_bank_lookup` | `question_bank_lookup` | engine.question_bank（硬校验池） |
| 规划/竞赛 | `my_career_guide` / `competition_guide` / `my_notices` | — | engine.career_guide / competition |
| 外部事实 | `kb_search` / `web_search` / `run_workflow` | 同左 | RAG / 联网 / 工作流白名单 |

注册位置：`agents/tools.py` 的 `TEACHER_TOOLS` / `STUDENT_TOOLS`（注册表）+
`agents/graph.py::tool_node`（分发）+ `agents/auto_plan.py`（AGENT_MODE=auto 的
LangChain 工具壳与 EXECUTABLE 集合）。**三处必须同步**，新增工具漏一处就会
静默失效——`tests/test_agent_entry.py` 守住这一点。

### 硬性要求（新增工具时逐条核对）

1. **只读优先**：新工具默认只读；有副作用的（如阈值写入）必须单独命名并审计。
2. **取数即隔离**：学生工具只用 `ctx.student_id`；教师查学生必须走
   `_fetch_student`（租户 + 任教范围校验）。学生端工具集**不得出现**查他人工具。
3. **查无如实报**：检索类工具查不到就返回空列表 + note，绝不用模型记忆凑数。
4. **草稿可直引**：每个工具的结果形状都要有 `_template_draft` 分支，
   保证 LLM 不可用时模板稿仍然可读。
5. **测试三件套**：注册表覆盖、分发可达、路由与参数抠取，各至少一条。

## 4. 编码约定

- 文件一律 **UTF-8** 编码。
- 路径统一用 `pathlib.Path`，**禁止**在代码里写死反斜杠路径字符串。
- 类型注解齐全（函数签名、返回值都要标注）。
- 函数保持**纯函数优先**（无副作用、可独立测试），便于将来迁移到 PySpark。
- 每个模块顶部用 **3 行注释**说明职责；不写无意义注释。
- 依赖统一放 `requirements.txt`（带版本锁），**禁止**在代码里 `pip install`。
- 不生成无意义的大段 hash 或二进制内容。

## 5. 交付汇报格式

每完成一件事，按以下三段汇报：

1. **改了什么**：文件清单 + 一句话说明。
2. **怎么验证**：命令 + 实际输出（完整粘贴）。
3. **已知问题 / 下一步建议**。

## 6. 目录职责速查

| 目录 | 职责 |
|---|---|
| `app\` | FastAPI 网关：认证、路由、身份强制注入 |
| `agents\` | LangGraph 多智能体层（DeepSeek 驱动，只做表达不碰数值） |
| `engine\` | 确定性引擎（预警、画像、推荐——唯一数值真相源） |
| `db\` | MySQL / DuckDB 建表脚本 |
| `etl\` | 数据脱敏与清洗 |
| `scripts\` | 初始化、造数、冒烟脚本 |
| `tests\` | pytest 用例 |
| `data\` | DuckDB 文件与生成数据（不入库） |
| `docs\` | 文档、验收报告、演示脚本 |
| `logs\` | 运行与 critic 日志（不入库） |

---

> 铁律优先级：1 > 2 > 3 > 4 > 5 > 6。
> 任何冲突以铁律为准，铁律之间冲突以前者为准。

# 【启航】基于大数据与多智能体协同的生涯与岗位匹配系统

> Windows 11 · Python 3.12 · MySQL 8.0.21 · DuckDB · LangGraph + DeepSeek
> 交付日期：2026-11-18

## 项目简介

启航是面向高校教育信息化的**生涯与岗位匹配系统**，用大数据与多智能体协同，
为教师与学生提供差异化的智能服务。

- **教师端**：学业预警、班级画像、职业差距分析——帮助教师及时发现学业风险学生、
  掌握班级整体状况、针对性指导职业发展。
- **学生端**：本人预警、岗位推荐——让学生了解自身学业风险与能力画像，
  获得基于画像的内容推荐岗位。

核心设计原则（详见 [`AGENTS.md`](AGENTS.md)）：**计算确定性、表达生成性**——
所有数值由 `engine\` 确定性引擎计算，大模型只负责把结果组织成自然语言；
身份与多租户隔离在数据层实现，不依赖前端。

## 快速开始

```powershell
Set-Location D:\qihang
& 'D:\data\python.exe' -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
copy .env.example .env      # 然后填 DEEPSEEK_API_KEY / MYSQL_PASSWORD / JWT_SECRET
python -m agents.llm        # 验证 DeepSeek 链路
```

## 目录结构

```
D:\qihang\
├── .env.example          # 环境变量模板（复制为 .env 后填写）
├── .gitignore            # 忽略 .venv / .env / data 产物 / logs
├── AGENTS.md             # 项目宪法（六条铁律，P0 生成）
├── requirements.txt      # 依赖锁版本（P1-1 生成）
├── app\                  # FastAPI 网关：认证、路由、student_id 强制注入
│   ├── main.py           # 入口 uvicorn app.main:app
│   ├── auth.py           # JWT 解析 → 身份注入
│   ├── audit.py          # 调用审计日志
│   ├── schemas.py        # Pydantic 请求/响应模型
│   ├── config.py         # pydantic-settings 读取 .env
│   ├── demo_streamlit.py # 演示页（双 Tab）
│   ├── routers\          # teacher.py / student.py
│   └── static\           # 演示页静态资源
├── agents\               # LangGraph 多智能体层（DeepSeek 驱动）
│   ├── llm.py            # ChatOpenAI(base_url=api.deepseek.com) 单例
│   ├── graph.py          # router → teacher/student → critic 状态机
│   ├── tools.py          # 工具层（入参只接受后端注入的 id）
│   ├── teacher_agent.py  # 教师端 Agent
│   ├── student_agent.py  # 学生端 Agent
│   └── critic.py         # 数值回查 + 驳回 + 降级模板
├── engine\               # 确定性引擎（大模型无权触碰数值）
│   ├── store.py          # 存储抽象：DuckDBStore / ClickHouseStore
│   ├── rules.py          # 预警规则与阈值（可按租户配置）
│   ├── warning.py        # 预警引擎 V1（红/橙/黄三级）
│   ├── profile.py        # 四维画像（学业/行为/兴趣/能力）
│   └── recommend.py      # 规则打分 + 协同过滤 + 三段式理由
├── db\                   # mysql_schema.sql / duckdb_schema.sql
├── etl\                  # mask.py 脱敏与清洗
├── scripts\              # init_db.py / seed_mock.py / smoke_test.ps1 / gen_verify_report.py
├── tests\                # pytest 用例
├── data\                 # analytics.duckdb 与生成数据（不入库）
├── docs\                 # 目录说明 / VERIFY.md / 演示脚本 / 答辩大纲
└── logs\                 # critic 日志与运行日志（不入库）
```

## 架构铁律

1. 数值全部由 `engine\` 下的 Python 确定性代码计算，**大模型只负责组织语言**；
2. 身份（student_id / teacher_id）**只能由后端从 JWT 注入**，绝不从对话或请求体里取；
3. `agents\critic.py` 逐条回查输出中的数字，与引擎结果不一致即驳回，最多 2 次，超限降级为模板；
4. 小步提交：每阶段跑通 + `git commit`，人工审 `git diff` 后再进下一阶段。

## 分阶段

| 阶段 | 内容 | 提示词 |
|---|---|---|
| 0 | 项目宪法 `AGENTS.md` | P0 |
| 1 | 骨架 + 依赖 + DeepSeek 连通 | P1-1 / P1-2 |
| 2 | MySQL 9 表 + DuckDB 2 表 + 500 人模拟数据 | P2 |
| 3 | 预警引擎 V1 | P3 |
| 4 | 四维画像引擎 | P4 |
| 5 | tools 工具层 + LangGraph 图 | P5 / P6 |
| 6 | FastAPI + JWT + 越权防护 | P7 |
| 7 | Critic 防幻觉 | P8 |
| 8 | 冒烟 10 项 + VERIFY.md | P9 / P10 |
| 9 | Streamlit 演示页 | P11 |
| 二期 | Spark / 协同过滤 / 知识图谱 | P12 |

## 验收指标

> 以下为演示交付前需达到的验收基线，随阶段推进逐项勾选。

| 编号 | 指标 | 验收标准 | 状态 |
|---|---|---|---|
| V1 | 学业预警 | 红橙黄三级分类，引擎输出与大模型陈述数值一致（critic 通过） | ☐ |
| V2 | 班级画像 | 四维画像（学业/行为/兴趣/能力）可按班级聚合展示 | ☐ |
| V3 | 职业差距分析 | 给出学生能力与目标岗位的差距项与数值 | ☐ |
| V4 | 岗位推荐 | 基于画像的内容推荐 + 三段式理由，Top-K 可配置 | ☐ |
| V5 | 身份安全 | student_id / teacher_id 仅来自 JWT，前端伪造无效 | ☐ |
| V6 | 多租户隔离 | 跨租户查询在数据层被拦截，返回空 | ☐ |
| V7 | 防幻觉 | critic 回查数值不一致即驳回，超 2 次降级为模板 | ☐ |
| V8 | 冒烟测试 | 10 项冒烟用例全部通过，VERIFY.md 出报告 | ☐ |
| V9 | 演示可用 | Streamlit 双 Tab（教师/学生）可现场跑通核心流程 | ☐ |
| V10 | 文档完备 | 目录说明、答辩大纲、演示脚本齐备 | ☐ |

## 更新记录

### 2026-10-26
- 新增 `AGENTS.md`：项目宪法，写入六条铁律、运行环境、编码约定与交付汇报格式。
- 补充 `README.md` 骨架：项目简介、验收指标表（V1–V10）。
- P1-1：补全 `__init__.py`（app/ app\routers/ agents/ engine/ etl/）。
- P1-1：创建 16 个空模块骨架（app\*.py agents\*.py engine\*.py），仅含职责注释 + TODO。
- P1-1：实现 `app\config.py`（pydantic-settings `Settings` 单例）。
- P1-1：写 `requirements.txt`（依赖锁版本）。
- P1-1：`docs\目录说明.md` 追加 P1-1 已落地文件清单。
- P1-2：实现 `agents\llm.py`——DeepSeek 客户端封装（工厂函数 + SYSTEM_RULES + smoke）。
- P2：落地 `db\mysql_schema.sql`（9 表 + 外键索引 + 种子租户）与 `db\duckdb_schema.sql`（3 表）。
- P2：实现 `engine\store.py`——Store 抽象接口 + DuckDBStore 实现 + ClickHouseStore 留空。
- P2：实现 `scripts\init_db.py`——幂等执行两份 schema，逐表打印结果。
- P2-续：实现 `scripts\seed_mock.py`——500 名学生模拟数据（校情自检 + 风险埋点 + hidden_risk.csv）。
- P2-续：修正 `db\mysql_schema.sql` / `db\duckdb_schema.sql` 的 `term` 列为 VARCHAR(20)。
- P2-ETL：实现 `etl\mask.py`（手机号/邮箱/微信号脱敏）、`etl\clean_jobs.py`（5 文件清洗统一 schema）、`scripts\load_jobs.py`（灌入 MySQL job + DuckDB job_feature）。

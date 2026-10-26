# 【启航】基于大数据与多智能体协同的生涯与岗位匹配系统

> Windows 11 · Python 3.12 · MySQL 8.0.21 · DuckDB · LangGraph + DeepSeek
> 交付日期：2026-11-18

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

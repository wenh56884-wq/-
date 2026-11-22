# 【启航】基于大数据与多智能体协同的生涯与岗位匹配系统

> Windows 11 · Python 3.12 · MySQL 8.0.21 · DuckDB · LangGraph + 星火 / DeepSeek
> 交付日期：2026-11-18

## 项目简介

启航是面向高校教育信息化的**生涯与岗位匹配系统**，用大数据与多智能体协同，
为教师与学生提供差异化的智能服务。

- **教师端**：学业预警、班级画像、职业差距分析、按学号直达学生档案——帮助教师及时发现
  学业风险学生、掌握班级整体状况、针对性指导职业发展。
- **学生端**：本人预警、岗位推荐、生涯规划——让学生了解自身学业风险与能力画像，
  获得基于画像的内容推荐岗位；**大一先选考公/考研/考编/就业，大二/大三直接给出规划与方向**。

核心设计原则（详见 [`AGENTS.md`](AGENTS.md)）：**计算确定性、表达生成性**——
所有数值由 `engine\` 确定性引擎计算，大模型只负责把结果组织成自然语言；
身份与多租户隔离在数据层实现，不依赖前端。

## 快速开始

环境前提：Windows 11 + Python 3.12 + MySQL 8.0（已启动、`qihang` 库已建）+ Node 18+（构建前端用）。

### 首次初始化

```powershell
Set-Location D:\qihang
& 'D:\data\python.exe' -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 可选：只有运行 Spark 对拍测试时安装
pip install -r requirements-spark.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
copy .env.example .env              # 填 SPARK_API_KEY / DEEPSEEK_API_KEY / MYSQL_PASSWORD / JWT_SECRET

python scripts\init_db.py           # 建 MySQL + DuckDB 全部表（幂等，可重复执行）
python scripts\seed_mock.py         # 灌四届学生约 1 万人（含 2026 级大一），确定性种子
python scripts\load_jobs.py         # 清洗 5 份招聘数据灌入岗位库（职业差距/推荐依赖它）
python scripts\seed_kb_academic.py  # 灌学业 / 职业规划类制度文档（知识库问答依赖它）
python -m agents.llm                # 验证实际启用的模型链路
```

`seed_intent_demo.py` / `seed_notice.py` / `seed_competition.py` 等属于可选补充数据，按演示需要再跑。

`JWT_SECRET` 必须是非占位符、至少 32 字符的随机值。缺失或过短时服务会拒绝启动，不再回退到默认密钥。

### 启动

```powershell
cd web; npm install; npm run build; cd ..     # 前端只需首次构建，产物在 web\dist
scripts\start_qihang.bat                      # 默认 8000，只绑 127.0.0.1
scripts\start_qihang.bat 8000 lan             # 绑 0.0.0.0，手机/平板可经局域网访问
```

启动脚本依次做：环境自检 → 前端产物检查 → 起 uvicorn → 等 `/health` 通过 → 开浏览器 → 打印演示账号。
构建过 `web\dist` 后由 FastAPI 单服务托管，前后端同端口（默认 <http://127.0.0.1:8000>）。

### 演示账号

| 角色 | 账号 | 口令 | 说明 |
|---|---|---|---|
| 教师 | `T001` | `123456h` | 任教 40 个班 |
| 学生（大四） | `AI20230001` | `123456h` | 2023 级 |
| 学生（大一） | `AI20260001` | `123456h` | 2026 级，**学号是 8 位数字段**，不是 `AI2026001` |

演示账号口令统一为 `123456h`；该口令只用于本地/答辩演示，正式部署请改回强口令或关闭演示入口。

公网临时演示用 `scripts\start_public_demo.bat` 启动，教师 T001 与四个年级演示学生共用口令 `123456h`；公网模式仍只允许白名单账号登录。

登录页「演示账号」区点一下即自动填入。要换别的学生，先查一个真实存在的学号：
`SELECT 学号, 姓名, 班级 FROM 学生 WHERE 年级 = '2026' LIMIT 5;`

> `scripts\seed_freshman.py` 已废弃：2026 级由 `seed_mock.py` 整届生成，运行它只会打印废弃提示。

### 常用命令

| 目的 | 命令 |
|---|---|
| 日常全量测试（不含 Spark） | `.venv\Scripts\python.exe -m pytest tests -q -m "not spark"` |
| 发布前全量测试（含 Spark） | `.venv\Scripts\python.exe -m pytest tests -q` |
| 仅 Spark 对拍 | `pip install -r requirements-spark.txt` 后运行 `pytest tests\test_spark_features.py -q` |
| 端到端冒烟（12 项） | `powershell -ExecutionPolicy Bypass -File scripts\smoke_test.ps1` |
| 考核指标报告 | `python scripts\gen_kpi_report.py --out etl\docs\KPI.md` |
| 交付核验报告 | `python scripts\gen_verify_report.py`（输出路径写死 `etl\docs\VERIFY.md`，目录不存在会自建） |
| 配置教师任教范围 | `python scripts\seed_teacher_scope.py --classes AI2301,RJ2301` |

## 目录结构

```
D:\qihang\
├── .env.example          # 环境变量模板（复制为 .env 后填写）
├── .gitignore            # 忽略 .venv / .env / data 产物 / logs / shots
├── AGENTS.md             # 项目宪法（六条铁律）
├── requirements.txt      # 核心依赖锁版本
├── requirements-spark.txt# 可选 Spark 对拍依赖（含 requirements.txt）
├── app\                  # FastAPI 网关：认证、路由、身份强制注入
│   ├── main.py           # 入口 uvicorn app.main:app；/auth/login、/chat
│   ├── auth.py           # JWT 编解码 + 口令校验（bcrypt / 演示 sha256 双兼容）
│   ├── audit.py          # 失败请求与业务动作审计（均带 tenant_id）
│   ├── logging_config.py # 控制台 + logs/qihang.log 滚动日志
│   ├── schemas.py        # Pydantic 模型
│   ├── config.py         # pydantic-settings 读取 .env
│   ├── workflow_approval.py  # 工作流人工审批（挂起 / 通过 / 驳回）
│   └── routers\          # teacher / student / career / chat / grades / job / kg /
│                         # forecast / exam / interview / question_bank / kb / workflow
├── web\                  # Vue 3 + Vite + ECharts（构建后由 FastAPI 单服务托管）
│   ├── src\views\        # 16 个页面：登录、教师端、学生端、岗位/招考、图谱、面试、
│   │                     # 预测、测评、工作流审批、AI 助手等
│   ├── src\layout\       # ShellLayout（侧栏 + 顶栏 + 助手抽屉）
│   ├── src\api\http.js   # axios + JWT 拦截器
│   └── dist\             # 构建产物（不入 git）
├── agents\               # LangGraph 多智能体层（星火优先、DeepSeek 兜底）
│   ├── llm.py            # 多提供方客户端（OpenAI 兼容接口）
│   ├── graph.py          # plan → tool → draft → critic 状态机
│   ├── tools.py          # 工具层（入参只接受后端注入的身份）
│   ├── teacher_agent.py  # 教师端意图路由与参数抠取（不产生数值）
│   ├── student_agent.py  # 学生端意图路由
│   ├── intents.py        # 意图词表热加载（rules\agent_intents.json）
│   ├── auto_plan.py      # 自主规划（AGENT_MODE=auto 时模型自己选工具，可切换）
│   ├── interviewer.py    # 模拟面试官（出题 / 追问 / 点评）
│   ├── critic.py         # 数值回查 + 驳回 + 降级模板
│   └── career\           # 职业规划 5 节点（解析/匹配/周监控/通知/陪伴）
├── engine\               # 确定性引擎（大模型无权触碰数值）
│   ├── warning.py        # 预警 V1（红/橙/黄 + 灰档 unknown）
│   ├── rules.py          # 预警规则与阈值（可按租户 / 按班配置）
│   ├── profile.py        # 四维画像（学业/行为/兴趣/能力）
│   ├── recommend.py      # 规则打分 + 三段式理由 + 协同过滤
│   ├── career_guide.py   # 年级分层生涯规划（大一选目标 / 大二大三给路径）
│   ├── career_rules.py   # 职业规划规则引擎（career-v1）
│   ├── career_forecast.py# 目标导向的学期路径预测
│   ├── forecast.py       # 学业预测
│   ├── interview.py      # 模拟面试引擎（出题池 / 评估 / 追问）
│   ├── kg.py / kb_store.py / question_bank.py   # 知识图谱 / 知识库 / 题库
│   ├── job_search.py     # 岗位检索
│   ├── metrics.py        # 指标统计
│   ├── rag.py / web_search.py / workflow.py     # 检索与工作流
│   └── store.py          # 存储抽象（DuckDBStore；ClickHouseStore 留空）
├── rules\                # 考公 / 考编 / 考研 / 就业模板 + 方向关键词 + 意图词表
├── db\                   # MySQL / DuckDB / 职业规划 / 工作流审批建表脚本
├── etl\                  # 数据接入：脱敏（mask）/ 清洗（clean_jobs）/ 抓取 / 校情参照
│   └── docs\             # 数据来源、口径、验收、演示与答辩文档
├── docs\                 # 产品协同、前端改版与跨角色交接文档
├── scripts\              # init_db / seed_* / load_jobs / smoke_test / gen_*_report / start_qihang
├── tests\                # pytest（690+ 用例；Spark 用例需可选依赖）
├── data\                 # analytics.duckdb 与生成数据（不入库）
└── logs\                 # critic 与运行日志（不入库）
```

## 架构铁律

1. 数值全部由 `engine\` 下的 Python 确定性代码计算，**大模型只负责组织语言**；
2. 身份（student_id / teacher_id）**只能由后端从 JWT 注入**，绝不从对话或请求体里取；
3. `agents\critic.py` 逐条回查输出中的数字，与引擎结果不一致即驳回，最多 2 次，超限降级为模板；
4. 小步提交：每阶段跑通 + `git commit`，人工审 `git diff` 后再进下一阶段。

## 数据与运行约定

- **岗位主目录**：推荐、智能体检索与 `/job/*` 统一使用 MySQL `岗位` 表。
- **招聘抓取暂存**：`招聘岗位` 表只作为外部招聘源暂存，面试岗位选择仍可单独使用，
  但不再作为前台第二套岗位目录。
- **数据库审计**：成功访问写 `logs/qihang.log`；失败请求和业务动作写 `审计日志`，
  每条记录都带 `tenant_id`。
- **请求追踪**：响应包含 `X-Request-ID`，可与文件日志和失败审计记录对应。
- **日志轮转**：`logs/qihang.log` 单文件 10 MB，保留 5 份；日志目录不入 Git。

## 分阶段

| 阶段 | 内容 | 提示词 |
|---|---|---|
| 0 | 项目宪法 `AGENTS.md` | P0 |
| 1 | 骨架 + 依赖 + DeepSeek 连通 | P1-1 / P1-2 |
| 2 | MySQL 9 表 + DuckDB 3 表 + 500 人（重财校情）+ 1.2 万真实岗位 ETL | P2-1 / P2-2a / P2-2b |
| 2.5 | 源表补齐：图书馆 / 一卡通 / 证书竞赛项目 / 岗位浏览（补 7 个缺失特征） | P2-3 |
| 3 | 预警引擎 V1 | P3-1 |
| 4 | 四维画像引擎 | P4-1 |
| 4.5 | 口径统一与技术债清理（见 `etl\docs\指标口径字典.md`） | P4-3 |
| 5 | tools 工具层 + LangGraph 图 | P5-1 / P5-2 |
| 6 | FastAPI + JWT + 越权防护 | P6-1 |
| 7 | Critic 防幻觉 | P7-1 |
| 8 | 冒烟 12 项 + VERIFY.md | P8-1 |
| 9 | Vue 3 + ECharts 前端 | P10-1 / P10-2 / P10-3 |
| 10 | 职业规划模块（career-v1，5 节点） | P13-0 ~ P13-5 |
| 二期 | Spark / 协同过滤 / 知识图谱 | P12 |

## 验收指标

> 状态依据最近一次实测（2026-11-03）：日常快速门禁 702 passed、10 deselected；
> Spark 对拍 10 passed。合并口径为 712 passed。
> `scripts\smoke_test.ps1` PASS 12 / FAIL 0。

| 编号 | 指标 | 验收标准 | 状态 | 依据 |
|---|---|---|---|---|
| V1 | 学业预警 | 红橙黄三级分类，引擎输出与大模型陈述数值一致（critic 通过） | ☑ | 冒烟 #4/#8 两端数值一致 |
| V2 | 班级画像 | 四维画像（学业/行为/兴趣/能力）可按班级聚合展示 | ☑ | 冒烟 #3/#5；教师看板班级四维 + 学生抽屉 |
| V3 | 职业差距分析 | 给出学生能力与目标岗位的差距项与数值 | ☑ | 冒烟 #6 `gaps=3`，接口 ~1.1s |
| V4 | 岗位推荐 | 基于画像的内容推荐 + 三段式理由，Top-K 可配置 | ☑ | 冒烟 #10 `count=5 version=hybrid-v1` |
| V5 | 身份安全 | student_id / teacher_id 仅来自 JWT，前端伪造无效 | ☑ | 冒烟 #9 学生查他人 403；`get_current_ctx` 单一入口 |
| V6 | 多租户隔离 | 跨租户查询在数据层被拦截，返回空 | ☑ | `_fetch_student` / `_require_class` 均带 tenant_id |
| V7 | 防幻觉 | critic 回查数值不一致即驳回，超 2 次降级为模板 | ☑ | `tests\test_critic.py` |
| V8 | 冒烟测试 | 12 项冒烟用例全部通过，VERIFY.md 出报告 | ☑ | 2026-10-28 实测 PASS 12 / FAIL 0 |
| V9 | 演示可用 | Vue 前端（构建后单服务托管）走通登录→教师看板→学生端全流程 | ☑ | 冒烟 #11/#12；登录→`/student` 实测 |
| V10 | 文档完备 | 目录说明、数据来源、口径、验收、演示、答辩与协同文档齐备 | ☑ | `docs\` 管协同，`etl\docs\` 管数据/验收 |

## 更新记录

### 2026-11-10
- **修复「本科能考哪些职位」类追问被兜底进 my_warning**（用户实测截图翻车）：
  ① `agents\student_agent.py` `personal_tool` 新增两条复合路由——「学历词 + 考/报」
  → `exam_positions`（排除考研/教资等非国考范畴）、「职位/岗位 + 要求/条件/门槛」
  → `exam_positions`；复合规则只看当前问句（新增 `raw` 参数），关键词路由先查
  当前问句、未命中再退合并意图，避免上一轮「国考职位表」字面劫走新话题追问；
  泛词剥离表补「知道/要求/条件/我/里面/其中/还有/就/面」，追问残词不再变成
  垃圾关键词 LIKE 查空。② `agents\graph.py` 新增学生端数据面追问延续：追问 +
  上一轮工具为 `exam_positions`/`exam_notices` 时沿用同一工具，只让学历/地点等
  结构化过滤生效（不带检索词）；`_looks_like_followup` 补「里面/其中/这些/上面/
  刚才」。③ `agents\graph.py` `draft_node` exam_positions 专用草稿分支修复
  `str(attempts) >= 3` 的 str/int 比较必炸 TypeError（一进该分支就「智能体处理
  失败」）。④ `agents\critic.py`（critic-v2）修复列表型草稿被误杀：行首列表序号
  （「1. 外交部…」）不再算数值论断；新增 rowref 论断（「第1、3条」行引用）按
  返回列表行数校验边界；白名单收进列表条数（「共 8 条」= len(列表)）。修复后
  职位表问答第一稿即通过，不再连吃两次驳回降级。测试：test_student_agent.py /
  test_agent_entry.py / test_critic.py 共新增 8 个回归用例。

### 2026-11-09
- **宠物话术与打扰修复**：① `app\routers\pet.py` 新增确定性
  `normalize_reply()`——LLM 输出的半角 `?!,;:` 转全角、连续波浪号收敛为单个
  `～`、压多余空白，chat 与 proactive 两处输出统一过一遍（铁律 1：后处理不经
  模型）；② system/proactive prompt 加「全角标点、禁波浪号 emoji、开头句式
  必须变化、必须回应用户刚说的内容」规则；③ 前端 `usePet.js` 加交互门控
  `markInteract()`——用户从未交互不主动说话、闲置超 10 分钟静默，页面刚打开
  不再突然冒话；④ 气泡 `white-space: normal` 允许换行，长句不再溢出。
- **修复 `pet_store.load_personality` KeyError**：SELECT 漏选 `鼓励池JSON`
  列导致读库必崩，补上该列。
- **国考职位数据源打通（调研）**：国考专题下载页
  `bm.scs.gov.cn/pp/gkweb/.../gkdownloads.html` 为 JS 渲染，真实清单来自
  `gkdownloads.js` 里的 API `GET dl.scs.gov.cn/api/res/{hb01Id}/1110`
  （2027 年度 `hb01Id=8a81f6eca0221f1401a0242759fc0000`）；返回 4 个文件的
  `resourceName/resResourceId/resourceComment`，下载地址
  `dl.scs.gov.cn/download/{id}`，验证码仅前端校验、服务端可直接下载。
  已实测拉到《招考简章 2027》zip（1.76MB）并解出 xls：5 sheet /
  约 1.94 万职位 / 27 列（部门代码/名称、用人司局、招考职位、专业、学历、
  学位、政治面貌、基层年限、工作地点等）。源数据归档 `data\gk2027\raw\`
  （不入库）。**已入库**：走既有管线
  `scripts\sync_guokao.py --year 2027 --file data\gk2027\raw\guokao2027.zip`
  （dry-run 核对后实跑，成功 19426 / 失败 0），`/exam/positions/facets`
  返回 2027 年度 19426 职位 / 35691 招录人数，4 类分部与官方 sheet 一致，
  关键词「税务」命中 11288 条——前端「招考信息·国考职位」与智能体
  `exam_positions` 工具即时可见。
- **国考职位自动同步（年度守护线程）**：新增 `app\guokao_sync.py`，与
  `recruit_sync` 同模式但独立开关——`GUOKAO_SYNC_HOURS`（默认 168 = 一周，
  0 关闭），`main.py` 启动时拉起 `guokao-sync` 线程；只同步
  `etl.exam_positions.DOWNLOAD_URLS` 里显式登记的年度（不猜 URL），
  下载→解析→`upsert_positions` 增量入库→写 `抓取运行日志`，失败只告警不抛异常。
  `scripts\sync_guokao.py` 的 `log_run` 增加 `trigger` 参数并配 `--trigger`，
  日志可区分 manual / schedule / api。`.env.example` 补 `GUOKAO_SYNC_HOURS`。
  实测：重启服务后线程自动跑出 `触发方式=schedule / 抓取 19426 / 更新 19426 /
  是否成功=1` 的运行日志。
- **修一处测试隔离事故**：`TestClient(create_app())` 会在 pytest 进程内触发启动
  块拉起真守护线程，该线程恰在 monkeypatch 生效期间跑了一轮，把打桩职位以默认
  租户 1 写进真库（多出 2 行、并让 facets 断言 19426 误报）。修法：
  `guokao_sync.start_background_sync()` 在测试进程内直接返回 False（已加用例
  锁定）；同时 `tests\test_exam_positions.py` 的总量断言改为与库内实数对账，
  不再写死 19426，避免官方补录后误报。新增 `tests\test_guokao_sync.py`
  （10 项：间隔开关、失败告警、真库入库/幂等、pytest 门禁）。
- **报考分析页新增「你能报的国考职位」卡片**：`CareerForecast.vue` 在
  「真实招考公告」折叠项上方新增 `guokao` 折叠项（仅考公且后端
  `opportunities.guokao_positions` 有效时渲染，考研/考编自动隐藏）。
  el-card 内用 el-tag 展示 可报职位数 / 计划招录人数 / 不限专业数 /
  全表规模，el-table 列出按学生学历/政治面貌/专业/意向城市初筛的职位样例
  （部门/职位/人数/地点/学历/政治面貌），底部挂官方专题链接
  （`source_url` / `source_label`）。「关键词初筛、以官方职位详情为准」的
  口径说明由后端 caveats 承担，前端不重复编数字。
  验证：`npm run build` ✓；Edge 实测 AI20230001（智能科学与技术，重庆）
  命中 2 个职位并完整渲染，切到考研卡片消失；期间发现并确认运行中的
  uvicorn 加载的是并行会话修复前的 `context.py`（`%%` 转义 bug 导致 422），
  重启后正常。
- **同步线程启动防抖**：`app\guokao_sync.py` 与 `app\recruit_sync.py` 的守护
  线程不再「启动即全量跑一轮」——先查 `抓取运行日志` 最近一次成功时间，
  距上次成功不足一个间隔（默认一周）就跳过本轮（日志记
  `... sync skipped: ... fresh`）。动机：开发期频繁重启服务，会对官方站点
  反复拉 2MB 全量、对招聘站逐条进详情页。国考按单一目标判断；招考按
  civil/institution/postgraduate/job 四个目标独立判断，某源持续失败时到点
  仍会整轮重跑，不会被成功源「捂住」。查询失败一律按「该跑」兜底，
  宁可多跑一次不漏跑。测试：`tests\test_recruit_sync.py`（新建 8 项）、
  `tests\test_guokao_sync.py` 补 4 项（含 DictCursor/tuple 游标双形态回归
  ——首轮实测抓到 `row[0]` 在 DictCursor 下抛 TypeError 导致防抖失效的
  bug，已修）。另修测试隔离：`test_guokao_sync` 的日志清理改用专用触发
  方式 `test` 打标（日志表无租户列），不再误删真实 schedule 运行历史
  （被误删的 5 条已按查库原始输出回插）。全量回归 792 passed。
- **借鉴 Nuxt UI 设计语言的数据组件打磨**：评估 github.com/nuxt/ui 后
  定论——它可用于纯 Vue 项目（Vite 插件形态）但硬依赖 Tailwind v4，
  preflight 会与 Element Plus 全套样式打架，16 个 view 全是 el-table/
  el-collapse/el-form，整体迁移是重写级工作量且推翻刚落地的 Medusa 基线，
  故不换栈，只把它的设计细节融进 `styles.css`（追加式，不动基线）：
  el-table 表头降权（12.5px/600/灰字/字距）+ 行悬停染靛蓝软底 +
  `font-variant-numeric: tabular-nums` 数字等宽对齐（含 el-descriptions/
  el-statistic）；el-tag 全圆角胶囊化 + 软底去边框；el-collapse 标题
  悬停主色反馈；el-overlay 弹层遮罩加 backdrop-blur 景深；全局链接
  颜色过渡 + 下划线偏移。验证：`npm run build` ✓；浏览器实测报考分析
  （卡片标签胶囊/表格表头/等宽数字）与岗位库（行业标签胶囊不破布局、
  统计卡数字对齐）均正常。截图 `logs/screenshots/nuxtui-polish-*.png`。
- **修模拟面试页两处布局空洞**（用户反馈「有点空」）：根因有二——
  ① `.kv` 是 flex 容器，「当前简历」的 v-for 经历项被当独立 flex 子项
  互相挤压成竖排单字列，把卡体撑到天高；② 「录入简历」「答题卡」带
  `bento-row-2` 跨两行，bento 行高 = 行内最高者，右侧长卡（长简历/
  长诊断/长点评）把整行拉爆，跨行卡体内全是空白。修法：经历项包进
  `.exp-list`（flex:1 块级容器）回归正常文档流；去掉两处 `bento-row-2`；
  长内容卡（当前简历/简历诊断/上一题点评）加 `cap-body` 体高 540px
  封顶内部滚动；「怎么练」无诊断时 span-4 占满整行、「历史场次」动态
  跨列（无点评时与答题卡/选岗卡并排，有点评时占满整行）——历史场次
  从页尾提到首屏，选岗时可直接参考过往场次。验证：dev server (5173)
  实测两个标签页布局紧凑无空洞、竖排文字修复；`npm run build` ✓。
  截图 `logs/screenshots/interview-before/after*.png`。
  遗留（后端，转 Claude）：简历文本含 `<w` 前缀乱码（docx 解析产物，
  v19 自填简历的教育/技能/经历多处可见），属 resume 解析层问题，
  前端展示层无法根治。
- **按校内参考站（xsc.cfec.edu.cn:82/dashboard）整体换肤**：该站是
  Vue SPA 且本机浏览器被代理拦（PowerShell 可直连），改为抓取其全部
  CSS 提取设计体系——深藏青侧栏 #161c2b、主蓝 #1951c3、选中项深蓝实底
  + 右缘 3px 浅蓝指示条 #a3beff、内容区 #ebf0f5、语义绿 #77d9a3/红
  #f57676。迁移分两步：① `data/_retheme_colors.py`（已删）把全前端
  21 个文件的靛蓝系精确映射到深蓝系（#5b5bd6→#1951c3 等 12 个 hex +
  rgba(91,91,214)→rgba(25,81,195)，字节级读写保换行符）；② 手工重做
  `ShellLayout.vue`：桌面侧栏与移动抽屉改 #161c2b 深底、导航项灰字
  #969eaf、悬停/选中 #1951c3 + inset 浅蓝指示条、品牌白字（白字只
  作用于深底作用域，浅色顶栏品牌保持墨色）、AI 问法面板深底卡片
  （边框 #272d3c、字 #c8d3e8、标签 #a3beff）。Medusa 的结构层
  （圆角/阴影/bento/焦点环）原样保留，只换色相。验证：`npm run build`
  ✓；工作台/报考分析实测侧栏、选中态、按钮/单选组/链接全蓝系统一，
  宠物与内容区不受影响。截图 `logs/screenshots/retheme-*.png`。
  语义色（teal 正常/warning/danger）与图表非主色轴未动。
- **修宠物遮挡登录入口**：2D 宠物固定左下角后，`.enter-btn`（登录页
  「开始使用」CTA，实测位于视口 (68,787)）被 `pet-img` 完全盖住，点击
  全被宠物吃掉，登录页无法进入。修法：`App.vue` 陪伴层在 `/login` 路由
  不渲染（`v-if="showPet"`）——未登录时 personality/state/memories 三个
  接口本来就 401，陪伴层在登录页既挡路又无意义。实测：登录页宠物消失、
  CTA 可点、登录后宠物照常在岗；`npm run build` ✓。此改动动了宠物提交
  （f562437）的「跨路由常驻」假设，如需登录页也保留宠物，需另行挪开
  CTA 或给宠物让位。
- **宠物形象最终定稿：2D 立绘静态化（取代 2026-11-05 的 3D 方案）**：
  Claude 定夺采用 `PetSprite` 2D 立绘（fisharchive.cc 鲸鱼，CC BY-NC-SA 4.0），
  **删除** `PetAvatar`（Three.js 漫游鲸鱼）与 three 依赖——此前的「3D 数字暖生 /
  RobotExpressive.glb / 漫步、跟随、可拖动」口径全部作废。定稿行为：宠物固定
  驻留视口左下角，不移动/不拖动/不漫游；待机侧视、说话正视换图，心情驱动
  呼吸，点击蹦跳回应；控制条在右下角；登录页不渲染（见上条）。主动说话为
  确定性调度（默认间隔 480s，专注模式永不主动）。验收（CodeBuddy，1440×900）：
  登录页无宠物且 CTA 可点；登录后宠物 (20,671) 左下、控制条 (1096,828) 右下、
  零重叠；点身体冒泡、对话真实 LLM 回复（/pet/chat 200）、专注开关双向切换、
  主动说话心跳正常（/pet/proactive 周期 200，间隔内正确沉默）。截图
  `logs/screenshots/pet-turnbubble-1440.png`、`pet-chat-reply-1440.png`。

### 2026-11-05
- **宠物模块验证通过**：`engine/pet.py`、`engine/pet_store.py`、`app/routers/pet.py`
  （路由挂载于 `app/main.py`，启动时幂等建表）与前端 `App.vue` 全局
  `PetAvatar`/`PetBubble`/`PetConsole` 全链路跑通：pet 相关 pytest 56 passed，
  前端构建通过，重启服务后 `/pet` 5 个接口端到端实测正常（chat 走真实 LLM、
  degraded=false）。
- **宠物形象定稿 3D 数字暖生**：`PetAvatar` 改用本地 `RobotExpressive.glb`
  （three.js 官方带动画角色，Idle/Dance/Sitting 随心情切换）；修复模型缩放
  单位换算错误（像素误作世界单位，机器人只渲染十几个像素不可见），登录 →
  跑腿面板 → 指令直达端到端复验通过。
- **长期记忆管理与向量去重**：新增 `PUT/DELETE /pet/memories/{id}`（只允许
  编辑/删除本人记忆）；`宠物长期记忆` 表加 `向量` 列（幂等迁移），入库时用
  `agent_memory.embed` 离线向量 + 余弦相似度去重（阈值同主智能体 0.92，另有
  实词字符交集前置防误撞，语义反转不会被合并）；设置弹窗里每条记忆可「改/删」。
  pet 相关 pytest 62 passed。
- **宠物 UI 冒烟脚本**：`scripts/verify_pet.py`（18 项接口自检，照
  verify_career.py 范式）与 `web/scripts/pet-ui-check.cjs`（9 项交互自检：
  登录 → 跑腿面板 → 指令直达 → 气泡），均为 0/1 退出码，可进演示前自检。
  控制条/气泡/跑腿面板视觉同步美化（毛玻璃聚焦态、弹性气泡入场、统一紫系）。
- **清理临时文件**：删除根目录与 `web` 下全部 `tmp*` / `_tmp*` 临时脚本、
  截图、日志、模型预览目录及 `.playwright-cli` 抓取产物，并从 git 暂存区同步移除。

### 2026-11-03
- **安全收口**：`JWT_SECRET` 缺失、为占位符或不足 32 字符时服务拒绝启动；
  `POST /kg/rebuild`、`POST /qb/reload` 改为仅教师可调用。
- **审计租户隔离**：`审计日志` 新增 `租户编号` 和
  `(租户编号, 动作, 创建时间)` 索引；`/chat/metrics` 按当前租户统计。
  已有数据库升级时先运行一次 `python scripts\init_db.py`。
- **审计性能与可观测性**：成功访问不再写数据库审计，改写入轮转文件日志；
  静态资源与健康检查成功响应不污染审计表；失败请求和业务动作继续落库。
  500、后台同步失败与审计写库失败现在会记录异常堆栈和 `X-Request-ID` 对应信息。
- **依赖统一**：直接依赖补 `networkx`、`python-multipart`；移除未使用的
  `streamlit`、`langgraph-checkpoint-sqlite`；Spark 依赖拆到
  `requirements-spark.txt`。
- **岗位数据源统一**：`/job/*`、学生岗位搜索和智能体岗位检索统一读取 `岗位` 主目录；
  `招聘岗位` 仅保留为外部抓取暂存/面试选岗池。
- **验证基线**：快速门禁 `702 passed, 10 deselected`（75.28s）；Spark 对拍
  `10 passed`（357.25s），合并口径 712 passed。

### 2026-10-29
- **教师端成绩单加「全班总体平均成绩 / 个人平均成绩 / 同专业班级排名 / 同专业个人排名」**：原先教师只能逐个学生查成绩单，看不到班级整体水平。新增 `engine\grades.py::build_rank`（纯函数，不连库）与接口 `GET /grades/class-rank`，前端 `GradeReport.vue` 教师端加三块：全班总体均分、同专业班级排名、班级个人均分与排名（点行即看该生成绩单）。口径按需求确认为**学分加权平均分**、**只统计教师任教范围内的班**、**按学期可切换**（默认最近学期）。
  - 一个绕不开的数据事实：班级与专业是**多对多**（如 `JR2301` 里同时有金融学、金融科技、保险学、信用管理 4 个专业的学生），所以班级排名按 **(专业, 班级)** 聚合分别计名次，而不是按整个班算一个名次；名次并列后跳号（并列第 2 之后是第 4），无成绩者不参与排名。
  - 班级均分定义为「该班各学生个人加权均分的算术平均」（学生等权），不选课多的学生主导；个人加权均分与成绩单**严格同口径**（同一门课取最高分 → 按学分加权），已用真实数据逐条比对，8/8 完全一致，不会出现两个页面数字打架。
  - 权限落在数据层：`_require_class` 校验任教范围，统计 SQL 带 `tenant_id` 且只用任教班级；响应里**只回当前班的学生明细**，同专业其他班的数据只用于算名次、不随响应下发。
  - 同步接入智能体：工具 `class_grades_rank`（仅教师端）、分发 `graph._dispatch`、auto_plan 声明、词表「排名 / 名次 / 平均成绩 / 全班平均」；词表刻意把排名排在成绩单之前，否则「班级成绩排名」里的「成绩」会被成绩单路由吃掉。新增 `tests\test_grades_rank.py`（11 项，主用例不连库）。
  - 词表冲突回归（固化在 `tests\test_agent_entry.py`，22 种问法）：给班级排名加「平均成绩」后，**「AI20230001 的平均成绩」会被班级统计抢走**——问的是这个人、统计的却是全班。修法是 `plan_teacher` 增加「提问点名到具体学生时，班级级统计让位给成绩单 / 画像 / 预测」，但**真在问名次时不让位**：个人名次只存在于班级排名里，成绩单没有名次字段，「XX 排第几」交给成绩单会答不出来，靠 intents 新增的 `rank_markers` 名次信号词区分。另修一处老问题：`kg_skill_jobs` 原本写死「会了能做什么」，中间插个词（「会了 Python 能做什么」）就不认，掉到兜底的班级概貌。
  - 上线自查（Edge 浏览器实测 + 问法压测）发现并修复：教师**点名班级但没点名到人**时，「成绩怎么样 / 的均分 / 平均绩点」会落到个人成绩单、再兜底成随机一个学生的成绩——问的是全班，看到的是一个人。修法是给 `plan_teacher` 加「班级信号」规则：提问里有班级名或说「这个班 / 我们班」且未点名到人时，成绩类问法一律归班级统计（10 种问法压测全对，含「点名到人归成绩单」「挂科归预警名单」的反例）。同时排名卡注明「任教范围内共 N 个班参与比较」，教师只带一个班时明确提示无法横向比较，不让用户对着只有 1 行的排名猜。
- **联网搜索真正打通（web-v1 · 博查适配）**：原先教师问「联网查最新的公开招聘信息」，回答是「没检索到任何公开招聘信息」——实际上从来没连过网。逐层定位出三个原因，都在代码里修掉：① 项目里**没有任何 `load_dotenv`**，`.env` 只被 pydantic 的 `get_settings` 读走、从不写回 `os.environ`，而 `engine/web_search.py` 是读 `os.getenv` 的，等于服务进程里永远读不到搜索密钥 → `app/main.py` 启动时加载一次；② 补上**博查**（api.bochaai.com，国内可直连）适配层，与 serper / bing 形成三级选择；③ 联网与知识库共用 RAG 提示词，那条提示词要求「查不到就说知识库里没有相关规定」，于是「网上没查到」被说成「知识库里没有」，用户以为查的是校内知识库 → 给 `web_search` 单独写提示词 `_WEB_SYSTEM`，并规定联网无结果时**跳过模型润色**直出模板。附带一处：检索词里的「联网查一下」这类动作词要洗掉——带着「联网」去搜会被召回一堆「什么是联网搜索」的页面，洗完后引用从招聘平台首页变成真实公告与政府官网（武汉青山区政府、盐城新闻网、本溪人社局）。密钥经 `.env` 的 `BOCHA_API_KEY` 配置（注意是 `sk-` 开头的搜索服务密钥，`ak-` 开头的是别的平台的访问密钥，博查不认）。新增测试：无密钥话术断言、provider 选中博查。
- **智能体成为统一入口（agent-entry-v1）**：原先智能体只有 9 个工具，成绩、学业预测、报考分析、知识图谱、竞赛、通知这些功能只能走页面接口，智能体根本调不到；学生端路由更只有两条（`推荐`→`my_recommendations`，其余一律 `my_warning`）。本轮把工具集扩到 **24 个**（教师 14 / 学生 16）：新增 `my_grades`、`student_grades`、`my_forecast`、`student_forecast`、`my_career_forecast`、`kg_major_skills`、`kg_skill_jobs`、`kg_path`，并把已实现却从未暴露给智能体的 `search_jobs`、`job_facets`、`competition_guide`、`my_notices`、`my_career_guide` 一并接入，学生端路由扩到 8 条。**铁律不变**：数值仍由 `engine/` 的确定性函数算出（成绩聚合走 `engine.grades`、预测走 `engine.forecast`、图谱走 `engine.kg`），智能体只做选工具、编排与表达；学生端工具集仍不含 `student_profile` / `warning_list` / `student_grades` 等查他人的工具。
  - 一个必须排在前面的顺序问题：学生端「本人数据」意图要**先于**知识库判断，否则「我的成绩」会被知识库词表里的「学分」抢走，答出一堆管理办法；同理「预测」要排在「成绩」之前，否则「预测一下我下学期的绩点」里的「绩点」会被成绩路由吃掉。
  - 工具分发从 11 个 `elif` 改成显式 `_dispatch` 表；`teacher_agent.plan_teacher` 给 `student_grades` / `student_forecast` 补了学号抠取（原来只有 `student_profile` 会抠，新工具会拿到空学号）。
  - 新增 `tests\test_agent_entry.py`（14 项）：路由正确性、学号是否真的传下去、新工具名能否被分发、学生端无越权工具、`my_grades` 只用 `ctx.student_id`。
- 知识库换成「学业职业规划」类（原来灌的是报销 / 请假 / 采购等企业制度，与项目主题不符、演示容易被问住）：新增 `scripts\seed_kb_academic.py`，走 `/kb/docs/text` 灌 6 份制度——学业预警帮扶、学籍与学分、实习实践、就业指导、职业资格证书认定、奖助学金评定，幂等可重复跑；加 `--purge-legacy` 会删掉早期的 4 份企业制度文档（不带则只增不删）。
- `rules\agent_intents.json` 的 `kb` 节补 23 个学业职业词（学籍 / 学分 / 培养方案 / 学位 / 重修 / 补考 / 实习 / 管理办法 / 实施细则 / 职业规划 / 资格证书 等），让「学业预警管理办法里红色预警怎么定」这类问法能路由到 `kb_search`；**刻意避开** `考公` / `考研` / `考编` / `就业意向`（已被 `overview` 占用）与 `预警` / `挂科` / `名单`（已被 `warning_list` 占用），否则教师查班级数据会被误判到知识库。
- Web 前端打磨：① 新增 `web\src\views\NotFound.vue` 404 兜底——顶层与 `/teacher`、`/student` 侧栏内各挂一份，后者**保留侧栏只换内容区**，输错地址不再整屏白屏；② 路由加 `meta.title` 并在 `afterEach` 写入 `document.title`，标签页标题随页面变化（与侧栏菜单 label 同源）；③ 加 `scrollBehavior`，切页回顶部、浏览器前进后退恢复原位置；④ 审批页「通过 / 驳回」加二次确认（通过会真实执行步骤且以提交者身份取数，两者都不可逆）；⑤ 路由全部改为按需加载，首屏 JS 由 2.33 MB 降到 1.06 MB（已验证 ECharts 不在首屏 chunk 内，改由访问图表页时才拉取）。
- 测试语料同步改为学业职业类：`tests\test_chat_capabilities.py` 的 `POLICY` 由「员工报销制度」换成「学业预警与帮扶管理办法」（数字断言 500/350 元 → 6 门 / 15 日），`tests\test_approval_autoplan.py` 的多跳用例假命中改为「学业预警办法 / 学籍学分规定」；`test_agent_commercial.py` 的 `入职`、`test_profile_raw.py` 与 `test_metric_consistency.py` 的「考勤」属学生出勤数据或词表合并机制用例，保留不改。

### 2026-10-28
- 新增三个智能体能力（**默认行为不变，均可开关**）：
  1. **审批工作流（人工审核）**：`工作流定义` 加 `是否需要审批`，新增 `工作流审批` 表，`工作流运行.状态` 扩充 `pending` / `rejected`。教师把流程设为需审批后，师生触发**只挂起不执行**，教师通过才真正跑，驳回则一步都不跑；审批通过时用**提交者**身份执行（学生提交的流程只会取到本人数据，不会变成审批人视角）。新增 `app\workflow_approval.py`、`app\routers\workflow.py` 的 `/approvals/pending` 与 `/runs/{id}/decide`（学生调用返回 403、重复审批返回 409），教师端新增「工作流审批」页，智能体触发需审批流程时返回 pending 话术而非谎报已执行。
  2. **多跳检索**：`agents\tools.py` 新增 `kb_search_deep`——模型判定第一跳不足以回答时改写检索词再补一跳（最多 2 跳），命中合并去重，引用编号与 `verify_citations` 口径不变；`AGENT_KB_MULTIHOP=0` 可退回单跳。补跳时**扩大召回**（`top_k` 翻倍至多 10），否则会把第一跳那几块再捞一遍、去重后等于白跳；返回新增 `new_hits` 字段标明多跳实际带回几块新原文，避免「跳了但没带回东西」被误当成收益。当前演示知识库已扩展到 32 份文档 / 43 个分块，多跳仍可按同一协议继续扩展语料。
  3. **自主规划（可切换）**：新增 `agents\auto_plan.py`，`AGENT_MODE=auto` 时由模型用 LangChain tool calling 自主选工具；**只替换「规划」这一步**，工具执行 / Critic 校验 / 降级模板全部照旧，学生端只暴露本人工具集（不给 `student_profile`、`warning_list`），模型不可用或选中越权工具则自动退回确定性路由。默认 `AGENT_MODE=graph` 不变。
- README 大修：快速开始补完整初始化链路（`init_db` → `seed_mock` → `load_jobs` → 构建前端 → `start_qihang.bat`，含 `lan` 局域网模式）、演示账号表与查学号方式、常用命令表（测试 / 冒烟 / KPI 报告 / 任教范围）；目录结构按实际模块重写（`engine\` 22 个模块、`app\routers\` 13 个路由、`web\src\views\` 11 个页面、`rules\` 6 份规则词表）；验收指标 V1–V10 按 2026-10-28 实测勾选并补「依据」列（冒烟 PASS 12 / FAIL 0，pytest 527 passed），V10 标注文档位置待迁回。
- 修复大一账号登录不进去：根因是文档写的 `AI2026001`（7 位）与库中真实学号 `AI20260001`（8 位）不一致，认证要求「口令=学号」且账号必须精确存在，输错即 401。快速开始补账号表并注明 8 位格式，`seed_freshman.py` 标注废弃；登录页演示账号改为可点击填充，并补「学生（大一）AI20260001」；同步更正 `etl\docs\演示脚本.md`、`etl\docs\VERIFY.md` 的过期账号与班级规模描述。
- 性能：修复教师端「学生档案」整页 14 秒才出数据——根因是 `read_features` 逐人读取画像，580 人的班级要开 580 次 DuckDB 连接（约 5.8 秒）。`engine\store.py` 新增 `read_student_features` 批量读取（一次连接 + IN 查询），`agents\tools.py` 的 `read_features` 改走批量；顺带把 `_job_demand` 的检索文本改为预构建、方向判定加单次调用内缓存（3 个维度不再各拼一遍、2 万条浏览记录不再重复匹配）。`/teacher/career-gap` 从 13.5~14.7s 降到约 1.1s，进程内 19969ms → 936ms，口径与返回结构不变（test_tools / test_profile / test_warning / test_api / test_metric_consistency 共 96 项通过）。
- 前端：修复侧栏菜单双高亮（`web\src\layout\ShellLayout.vue`）——`isActive` 的前缀匹配导致访问 `/teacher/students` 时「班级总览」与「学生档案」同时点亮，改为与 `currentItem` 相同的最长匹配口径；学生端 `/student` 同类问题一并修复。
- 前端：教师看板画像抽屉美化（`web\src\views\TeacherDashboard.vue`）——新增姓名头像摘要卡、标签圆角化、四维雷达图由预警红改为主题蓝并加网格底色；职业差距标题在无目标方向时不再显示占位符"—"，无有效数据时按原因给出三类空态文案，不再渲染全 0 空图。
- 协同：审查 WorkBuddy 提交 `a2dd0a0`（教师端智能体）——全量回归 527 passed；教师按姓名查画像/阈值问答/上学期口径端到端冒烟通过；发现两个待改进点：① 租户内重名学生（如 10 个"何雯"）会兜底到空学号，被误报为"不属于当前租户"，建议改为向教师追问学号/班级；② `student_profile` 对空学号抛的是越权拦截而非参数错误，话术误导。

### 2026-10-26
- 新增 `AGENTS.md`：项目宪法，写入六条铁律、运行环境、编码约定与交付汇报格式。
- 补充 `README.md` 骨架：项目简介、验收指标表（V1–V10）。
- P1-1：补全 `__init__.py`（app/ app\routers/ agents/ engine/ etl/）。
- P1-1：创建 16 个空模块骨架（app\*.py agents\*.py engine\*.py），仅含职责注释 + TODO。
- P1-1：实现 `app\config.py`（pydantic-settings `Settings` 单例）。
- P1-1：写 `requirements.txt`（依赖锁版本）。
- P1-1：`etl\docs\目录说明.md` 追加 P1-1 已落地文件清单。
- P1-2：实现 `agents\llm.py`——DeepSeek 客户端封装（工厂函数 + SYSTEM_RULES + smoke）。
- P2：落地 `db\mysql_schema.sql`（9 表 + 外键索引 + 种子租户）与 `db\duckdb_schema.sql`（3 表）。
- P2：实现 `engine\store.py`——Store 抽象接口 + DuckDBStore 实现 + ClickHouseStore 留空。
- P2：实现 `scripts\init_db.py`——幂等执行两份 schema，逐表打印结果。
- P2-续：实现 `scripts\seed_mock.py`——500 名学生模拟数据（校情自检 + 风险埋点 + hidden_risk.csv）。
- P2-续：修正 `db\mysql_schema.sql` / `db\duckdb_schema.sql` 的 `term` 列为 VARCHAR(20)。
- P2-ETL：实现 `etl\mask.py`（手机号/邮箱/微信号脱敏）、`etl\clean_jobs.py`（5 文件清洗统一 schema）、`scripts\load_jobs.py`（灌入 MySQL job + DuckDB job_feature）。

### 2026-10-26（巡检）
- P3–P13 已落地：预警 / 画像 / 推荐 / Critic / FastAPI / Vue 前端 / 职业规划模块（详见 `git log` 与 `etl\docs\VERIFY.md`）。
- 修复：`fetch_active_rule` 把 `hard_baseline`/`adjustable` 读成空列表；`recommend_log` 的 `hit_items`/`gap_items` 双重 JSON 编码。
- 加固：MySQL 连接统一加 5 秒超时；库不可用时登录返回 401、工具层返回空结果而不是 500；`/chat` 改用已校验的 `get_current_ctx`。
- 前端：403 不再清理登录态（只有 401 才跳登录），并保留错误原因展示。
- 文档/依赖：冒烟项数统一为 12 项；`requirements.txt` 全部锁版本。
- 新增学生生涯规划卡：大一先选考公/考研/考编/就业（`career_intent` 表），大二/大三直接给出确定性路径；教师端支持按学号直达学生档案。
- `scripts/init_db.py` 现在会同时执行 `mysql_schema.sql` 与 `career_tables.sql`，新环境一次建表完成。
- 新增 `scripts/seed_freshman.py`：幂等插入 4 个 2026 级大一演示账号（AI2026001 / RJ2026001 / KJ2026001 / JR2026001，初始口令=学号）。
- 教师端班级总览新增「职业目标分布」卡：考公 / 考研 / 考编 / 就业 / 未填写人数与占比。
- 新增 `scripts/seed_intent_demo.py`：按学号哈希为演示学生补目标分布（`--reset` 可重建），不影响 2026 级大一先选流程。
- 新增考核指标报告：`python scripts\gen_kpi_report.py` 生成 `docs\KPI.md`（预警准确率、Critic 通过率/幻觉率、接口 P95、推荐日志覆盖与计划书指标对照）。
- 新增 `teacher_class` 教师任教班级绑定与 `class_warning_threshold` 班级级阈值：教师只能访问自己绑定的班级；未绑定任何班级时教师端目录为空（不可见全校），用 `scripts/seed_teacher_scope.py` 配置。
- 教师端「班级总览」新增“预警阈值”弹窗，可按班覆盖挂科/均分下滑/出勤率/分级门槛。
- 新增 `scripts/seed_teacher_scope.py`：`--classes AI2201,RJ2201` 绑定任教范围，`--clear` 清空绑定（此后看不到任何班级）。
- 教师端登录入口链接：`/login?role=teacher` 直达教师身份；演示账号 T001（绑定 AI2301/AI2401/AI2501）、T908208（AI2601）、T921028（AI2501），口令统一为 `123456h`。

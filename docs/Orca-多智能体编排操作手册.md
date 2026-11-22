# Orca 多智能体编排操作手册（qihang 项目）

> 适用版本：Orca CLI 1.4.261（本机实测）
> 适用项目：`D:\qihang`（启航 · 生涯与岗位匹配系统），分支 `feat/career-guide-teacher-search`
> **终端类型：PowerShell 5.1（提示符 `PS D:\qihang>`）——全文命令均为 PowerShell 语法**
> 目标：让 Claude Code / Qwen / CodeBuddy 三个 Agent 在不同终端里并行干活，由 Orca 统一建任务、派发、收结果

> ⚠️ **先记住三件事，能避掉 90% 的报错：**
> 1. 设变量用 `$X = "值"`，**不是** `export X=值`（那是 bash）
> 2. 多行续行用反引号 `` ` ``，**不是** `\`
> 3. 丢弃错误输出用 `2>$null`，**不是** `2>/dev/null`
>
> 本机没装 `jq`，文中 JSON 一律用 PowerShell 原生 `ConvertFrom-Json` 解析。

---

## 0. 角色分工约定（qihang 现状）

| Agent | 终端标题（必须先改） | 负责范围 |
| --- | --- | --- |
| Claude Code | `Claude-重构` | 后端 `app/`、`agents/`、`db/`、`tests/` |
| Qwen | `Qwen-接口` | 路由与接口层联调、ETL 脚本 |
| CodeBuddy | `CB-前端` | `web/src/views/*`、`web/src/components/*` |
| 主控（本会话） | `Main-编排` | 壳层 4 件（`ShellLayout.vue` / `Login.vue` / `styles.css` / `bento.css`）、验收与合并 |

> 文件主权必须提前讲清：**同一个人在同一时间只改自己名下的文件**，否则并行改同一文件必冲突。这是 qihang 已经踩过的坑（`ShellLayout.vue` 曾被两方同时改写）。

---

## 1. 第一步：开启编排开关

1. 打开 Orca 桌面应用
2. 进入 `Settings → Experimental`
3. 打开 **Orchestration** 开关

未开启前，所有 `orca orchestration ...` 命令都不可用。

**验证方式：**

```powershell
orca orchestration --help
```

能列出 `task-create / dispatch / check / worker-start` 等子命令，说明开关已生效。

---

## 2. 第二步：确认运行时状态

```powershell
orca status --json
```

正常返回示例（关键看 `runtime.state`）：

```json
{
  "id": "local-status",
  "ok": true,
  "result": {
    "app": { "running": true, "pid": 24232 },
    "runtime": {
      "state": "ready",
      "reachable": true,
      "connectionState": "connected",
      "appVersion": "1.4.261"
    }
  }
}
```

**只想看状态一行字，不想读整段 JSON：**

```powershell
(orca status --json | ConvertFrom-Json).result.runtime
```

**两种典型异常：**

| 返回 | 含义 | 处理 |
| --- | --- | --- |
| `runtime.state: "not_running"` / `reachable: false` | Orca 应用没起，或运行时就绪中 | 启动 Orca 应用，等 5~10 秒再查 |
| `terminal list` 报 `runtime_unavailable` | 读不到 `orca-runtime.json` | 一定是应用没启动，先解决上一条 |

> 实测记录：Orca 应用未启动时报错原文为 `Could not read Orca runtime metadata at C:\Users\22124\AppData\Roaming\orca\orca-runtime.json. Start the Orca app first.`——**这不是配置问题，是 Orca 没开**。应用起来后同一命令返回 `runtime.state: "ready"`、`reachable: true`、`connectionState: "connected"`。

---

## 3. 第三步：查终端列表并确认 handle

```powershell
orca terminal list --json
```

输出里每个终端包含 `handle`、`title`、`worktreePath`、`preview` 等字段。

**只看本项目终端，表格形式（推荐，替代 jq）：**

```powershell
(orca terminal list --worktree path:D:/qihang --json).result.terminals |
  Format-Table handle, title, branch -AutoSize
```

用管道解析也行（先 `ConvertFrom-Json` 再筛）：

```powershell
orca terminal list --json | ConvertFrom-Json |
  ForEach-Object { $_.result.terminals } |
  Where-Object { $_.worktreePath -like '*qihang*' } |
  Format-Table handle, title, worktreePath -AutoSize
```

**过滤后为空时先别怀疑语法**，先看总数：

```powershell
(orca terminal list --json | ConvertFrom-Json).result.totalCount
```

`0` 表示 Orca 里此刻没有任何存活终端（终端被关掉就是这个结果），不是选择器写错了。`--worktree` 支持这些选择器：`path:<路径>`、`branch:<分支>`、`name:<名称>`、`active`（当前聚焦的那个）。

**实测样例（当时有 1 个终端存活）：**

```text
handle       : term_20d4a792-8b7d-42a0-842d-07a2bffbd350
title        : C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
worktreePath : D:/qihang
branch       : refs/heads/feat/career-guide-teacher-search
```

即：标题是 powershell 的默认完整路径，**不是 Agent 名**。

**关键提醒（务必执行）：**

> Orca **不记录终端里跑的是哪个 Agent**，只能靠 `title` 或输出预览来判断。
> 直接把三个终端都开着、标题全叫 "Terminal"，`dispatch --to` 派错你无从察觉。
> 必须先在终端里手动改名：`Claude-重构`、`Qwen-接口`、`CB-前端`，再回来 `terminal list` 确认。

**把 handle 记进 PowerShell 变量（注意：不是 `export`）：**

```powershell
$T_CLAUDE = "term_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
$T_QWEN   = "term_yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"
$T_CB     = "term_zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"
```

确认都设上了：

```powershell
$T_CLAUDE, $T_QWEN, $T_CB
```

> 变量只存在于**当前这个 PowerShell 窗口**。关窗或新开 Tab 就没了，要重新设；`orca` 是独立进程，引用变量时靠 PowerShell 在传参前展开（`--to $T_CLAUDE` 这样写没问题，加引号 `"--to $T_CLAUDE"` 则不会展开，别这么写）。
>
> handle 与终端会话绑定：**终端关掉重开，handle 就变了**，必须重新 list。

---

## 4. 第四步：创建任务

```powershell
orca orchestration task-create --task-title "重构：auth 逻辑抽到独立 service" --spec '把 app/auth.py 里的登录/鉴权逻辑抽到 app/services/auth_service.py，保持路由层只做参数校验与响应组装；补 tests/test_auth_service.py 覆盖登录成功、密码错误、token 过期三种分支；不要改数据库表结构。' --json
```

> `--spec` 用**单引号**包起来：PowerShell 单引号内不做任何变量展开，中文标点、括号、`$` 全部原样传参，最不容易出岔子。

**想同时拿到 taskId，一步到位：**

```powershell
$TASK_CLAUDE = (orca orchestration task-create --task-title "重构：auth 抽独立 service" --spec '把 app/auth.py 的登录/鉴权抽到 app/services/auth_service.py；补 tests/test_auth_service.py；不要改表结构；不要提交 git。' --json | ConvertFrom-Json).result.taskId
$TASK_CLAUDE
```

**spec 写作四要素**（写不清楚，Agent 一定跑偏）：

1. **改哪里**：具体文件/目录，不要只说“优化一下”
2. **做到什么程度**：验收标准，最好能量化（“补 3 个测试分支”“首屏距离顶栏 24px”）
3. **不要动什么**：边界（“不要改表结构”“不要提交 git”）
4. **怎么验证**：`pytest -q` / `npm run build` 之类

**qihang 三条示例任务：**

```powershell
# Claude：后端
orca orchestration task-create --task-title "后端：工作流审批并发安全" --spec '修 app/workflow_approval.py 的并发审批问题：approve 与 reject 同时到达时只有一方生效；补 tests/test_approval_autoplan.py 用例；跑 .\.venv\Scripts\python.exe -m pytest -q 全绿；不要提交 git。' --json
```

```powershell
# Qwen：接口联调
orca orchestration task-create --task-title "接口：招考信息分页与筛选" --spec '改 app/routers/competition_sync.py：给招考列表加分页（page/page_size）与地区/学历筛选；保持响应字段向后兼容；补接口测试；不要动 web/ 目录；不要提交 git。' --json
```

```powershell
# CodeBuddy：前端视图
orca orchestration task-create --task-title "前端：成绩单页卡片视觉统一" --spec '只改 web/src/views/GradeReport.vue：卡片内距统一 24px、圆角用 var(--bento-radius)、标题走 .bento-title；不要动 web/src/layout/ 与 web/src/styles/（归主控）；改完 npm run build 必须过；不要提交 git。' --json
```

---

## 5. 第五步：派发任务给指定终端

```powershell
orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --json
```

- `--inject`：把任务内容自动注入终端并回车执行
- `--dry-run`：**先预检一次**，确认要注入什么内容、目标终端对不对，再正式发
- `--return-preamble`：返回注入的前导文本，便于核对

**建议顺序（先预检、再注入）：**

```powershell
# 1) 预检：不真正注入
orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --dry-run --json
```

```powershell
# 2) 确认目标终端标题、注入内容都对，再正式发
orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --json
```

三个 Agent 各建一个任务、各派一次：

```powershell
orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --json
orca orchestration dispatch --task $TASK_QWEN   --to $T_QWEN   --inject --json
orca orchestration dispatch --task $TASK_CB     --to $T_CB     --inject --json
```

**派完核对：**

```powershell
orca orchestration task-list --json
orca orchestration dispatch-show --task $TASK_CLAUDE --json
```

---

## 6. 第六步：等待完成

```powershell
orca orchestration check --wait --types "worker_done,escalation" --timeout-ms 900000 --json
```

> `--types "worker_done,escalation"` **必须加引号**。PowerShell 里 `a,b` 不加引号会被拆成数组，变成两个独立参数传给 orca。

| 事件类型 | 含义 | 处理 |
| --- | --- | --- |
| `worker_done` | 该 Agent 自认为干完了 | 收工验收，不要直接信，先跑构建/测试 |
| `escalation` | 卡住或要你拍板 | 必须人工看内容再回复，别静默忽略 |

**长任务轮询建议：** 每个 `--wait` 最多 15 分钟（900000ms），超时是正常返回，不代表失败，再起一轮即可。

**流式输出要过滤 keepalive**（`--wait` 每 15 秒往 stderr 打一行 JSON keepalive，不滤会污染解析）：

```powershell
orca orchestration check --wait --types "worker_done,escalation" --timeout-ms 900000 --json 2>$null |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { -not $_.PSObject.Properties['_keepalive'] } |
  ConvertTo-Json -Depth 10
```

---

## 7. 验收与合并（qihang 专用）

每个 Agent 报 `worker_done` 之后，主控统一跑一遍（PowerShell 下 `cd` 与 `;` 串联，别用 `&&`）：

```powershell
cd D:\qihang; .\.venv\Scripts\python.exe -m pytest -q
```

```powershell
cd D:\qihang\web; npm run build
```

```powershell
cd D:\qihang; .\.venv\Scripts\python.exe D:\tmp\qh_probe.py
```

> PowerShell 5.1 **不支持 `&&`**，链式命令用 `;`（前一条失败也照跑）或 `if ($?) { ... }`。

三条全绿，才把该 worktree 的改动合并回主干；**失败就打回**，用 `orca orchestration send` 把失败输出原样发回给对应 Agent（参数是 `--subject` + `--body`，没有 `--message`）：

```powershell
orca orchestration send --to $T_CLAUDE --subject "pytest 失败打回" --body 'pytest 挂了 3 个：<粘贴失败摘要>，修完再报 done' --json
```

---

## 8. 快速速查表（PowerShell 版）

| 目的 | 命令 |
| --- | --- |
| 看运行时是否正常 | `orca status --json` |
| 建编排 Run（可选但推荐） | `orca orchestration run-create --objective "…" --json` |
| 只看关键状态 | `(orca status --json \| ConvertFrom-Json).result.runtime` |
| 列终端与 handle | `orca terminal list --json` |
| 按项目过滤终端 | `(orca terminal list --worktree path:D:/qihang --json).result.terminals \| Format-Table handle,title` |
| 设 handle 变量 | `$T_CLAUDE = "term_..."` |
| 建任务 | `orca orchestration task-create --task-title "…" --spec '…' --json` |
| 建任务并取 taskId | `$TASK_CLAUDE = (orca orchestration task-create … --json \| ConvertFrom-Json).result.taskId` |
| 查任务 | `orca orchestration task-list --json` |
| 预检派发 | `orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --dry-run --json` |
| 正式派发 | `orca orchestration dispatch --task $TASK_CLAUDE --to $T_CLAUDE --inject --json` |
| 看某任务派发上下文 | `orca orchestration dispatch-show --task $TASK_CLAUDE --json` |
| 等结果 | `orca orchestration check --wait --types "worker_done,escalation" --timeout-ms 900000 --json` |
| 给 Agent 追加消息 | `orca orchestration send --to $T_CLAUDE --subject "…" --body '…' --json` |
| 看收件箱 | `orca orchestration inbox --json` |
| 查后端是否在跑 | `curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8001/ --noproxy "*"` |

---

## 9. 常见报错速查（都是 shell 语法问题）

| 报错原文 | 原因 | 改法 |
| --- | --- | --- |
| `export : 无法将"export"项识别为 cmdlet…` | 在 PowerShell 用了 bash 的 `export` | 改 `$T_CLAUDE = "term_..."` |
| `& : 无法将"&&"项识别为…` 或语法错误 | PS 5.1 不支持 `&&` | 改 `;` 或 `if ($?) { … }` |
| 命令末尾多出一个 `\ ` 报错 / 把 `\` 当参数 | PS 续行符是反引号 `` ` `` | 一行写完，或用 `` ` `` 结尾且**行尾不留空格** |
| `jq : 无法将"jq"项识别…` | 本机没装 jq | 用 `ConvertFrom-Json` |
| `2>/dev/null` 被当成参数或报“重定向不正确” | PS 重定向语法不同 | 改 `2>$null` |
| `--types worker_done,escalation` 报参数个数不对 | 逗号被拆成数组 | 加引号 `--types "worker_done,escalation"` |
| `curl` 输出一大段 HTML/对象 | PS 里 `curl` 是 `Invoke-WebRequest` 别名 | 用 `curl.exe`，参数照旧 |
| `无法将值“System.Object[]”转换为类型“System.String”` | `ConvertFrom-Json` 取到的是数组却当对象用 | 先 `.result.terminals` 再 `ForEach-Object` |

---

## 10. 注意事项（单独列出）

### 10.1 Agent 身份不可自动识别
Orca 只认终端，不认终端里跑的是谁。**派发前必须先把终端标题改成可辨识的名字**（`Claude-重构` / `Qwen-接口` / `CB-前端`），否则 `dispatch --to` 派错终端时你无从察觉。改标题比事后排查便宜得多——**开终端时第一件事就是改名**。

### 10.2 handle 会失效
handle 与终端会话绑定。终端关闭、崩溃、重启后 handle 全部作废，必须重新 `terminal list` 取新的，别复用变量里的旧值。新开一个 PowerShell 窗口，`$T_CLAUDE` 也自动为空，要重设。

### 10.3 CodeBuddy 的兼容性要实测
CodeBuddy 的 CLI 是否在 Orca 可识别列表内需要确认（`dispatch` 返回里若有 `unsupported agent` 之类提示即为不识别）。
**`--inject` 不生效时的回退方案：** 把 `spec` 原文手动粘贴进 CodeBuddy 终端，其余流程（`task-create` / `check`）照常走。

### 10.4 Cursor 不进编排链路
Cursor 不参与 Orca 派发。等某个 worktree 的产出胜出后，再用 Cursor 打开做代码审查和收尾，避免它和多 Agent 抢同一份文件。

### 10.5 一个终端同一时间只跑一个任务
同一 handle 连续 dispatch 两个任务，第二个会覆盖/打断第一个。要并行就开新终端、改标题、取新 handle。

### 10.6 派发时必须写死“不要提交 git”
并行 Agent 各自提交会造成分支地狱。所有 spec 统一加一句：**“不要提交 git，改动留给主控合并”**，提交权只在主控手里。

### 10.7 文件主权先划分再派发
qihang 的既有分工：`web/src/layout/*` + `web/src/styles/*` 归主控，`web/src/views/*` 归 CodeBuddy，`app/` + `agents/` 归 Claude。派发 spec 里点明“不要动 xx 目录”，比事后解冲突便宜得多。

### 10.8 escalation 不能静默丢弃
`check` 返回 `escalation` 说明 Agent 卡住或在等你决策（例如要装依赖、要改表结构）。必须人工读完再回复，否则该任务会一直挂着。

### 10.9 `--wait` 超时是正常返回
15 分钟无事件不代表失败，只是这一轮没消息。继续下一轮 `check`，或先 `task-list` 看任务状态。

### 10.10 输出解析要滤 keepalive
`--wait` 每 15 秒往 **stderr** 打 keepalive，且 `_heartbeat` 是已废弃别名。用 `2>$null` + 过滤 `_keepalive` 才是干净的事件流（见第 6 节）。

### 10.11 新版还有受监督 Worker 路径
当前版本已提供 `worker-start / worker-show / worker-read / worker-stop` 一整套受监督 Worker 命令，适合需要读中间输出、控制权限提示的场景。`dispatch --inject` 是“注入即走”的轻量路线，两者按需选：**短任务用 dispatch，长任务/要看进度用 worker-start**。

### 10.12 Claude Code 额度较贵，只派高价值任务
Claude Code 的单位成本明显高于另两个 Agent，**不要拿它做并行试错**。分工建议：Claude 只接「架构性改动 + 需要跨文件推理」的活（如审批并发、状态机、数据一致性），Qwen 接接口/脚本这类线性任务，CodeBuddy 接前端视图与样式。同一份 spec 不要三家同时派一份比谁做得好——费用翻三倍，收益接近零。

### 10.13 派发前先确认服务在跑
qihang 的验收依赖 `http://127.0.0.1:8001`（后端托管 `web/dist`）。派发前先确认：

```powershell
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8001/ --noproxy "*"
```

返回 `000` 说明服务没起，Agent 报 `worker_done` 你也无法验收，只能干等。

### 10.14 任务挂在「Run」上，先建 Run 更顺
1.4.261 里 `task-create` / `dispatch` / `check` 都有可选 `--run <run_id>`，而 `check` 的默认行为是「返回**已绑定的 Run** 的最早未读批次」。所以顺序建议是：

```powershell
orca orchestration run-create --objective "qihang：审批并发 + 招考分页 + 成绩单视觉" --json
```

拿到 `runId` 后，后续 `task-create` / `dispatch` / `check` 都显式带 `--run <runId>`，一条编排线一个 Run，收信不会串。不建也能跑（会自动落在一个默认 Run），但事后追溯麻烦。

### 10.15 受监督 Worker 可以直接指定 Agent，绕开“标题识别”难题
`dispatch` 只能派到「已存在的终端」，所以必须靠标题认人。而 `worker-start` 是**由 Orca 拉起受监督 Worker**，可以直接声明 Agent：

```powershell
orca orchestration worker-start --task $TASK_CLAUDE --agent claude --worktree current --json
```

这条路径不依赖终端标题、还能 `worker-read` 读中间输出、`worker-stop` 收工，代价是得先确认你要的 agent 名在 Orca 的可识别列表里（`orca orchestration worker-start --help` 里 `--agent` 的取值）。**短任务仍是 dispatch 更省事。**

---

## 附录 A：Bash / Git-Bash 等价写法

如果你用 Git-Bash（提示符是 `$`，不是 `PS`），前文命令按下表替换：

| 用途 | PowerShell | Bash / Git-Bash |
| --- | --- | --- |
| 设变量 | `$T_CLAUDE = "term_xxx"` | `export T_CLAUDE="term_xxx"` |
| 展开变量 | `$T_CLAUDE` | `$T_CLAUDE`（同） |
| 切目录 | `cd D:\qihang` | `cd /d/qihang` |
| 串联命令 | `A; B` | `A && B` |
| 丢错误输出 | `2>$null` | `2>/dev/null` |
| 续行 | 反引号 `` ` `` | 反斜杠 `\` |
| 解析 JSON | `ConvertFrom-Json` | `jq -r '.result.taskId'` |
| 取 taskId | `(… --json \| ConvertFrom-Json).result.taskId` | `$(… --json \| jq -r '.result.taskId')` |
| HTTP 探测 | `curl.exe … --noproxy "*"` | `curl … --noproxy '*'` |
| Python 路径 | `.\.venv\Scripts\python.exe` | `./.venv/Scripts/python.exe` |

**怎么确认自己在哪个 shell：** 看提示符。`PS D:\qihang>` 是 PowerShell；`$ ` 或 `user@host:/d/qihang$` 是 Bash。

---

## 11. 一页流程

```text
[Orca 应用启动]
      │
      ▼
Settings → Experimental → 打开 Orchestration
      │
      ▼
orca status --json            → runtime.state = ready ?
      │ 否 → 起应用 / 等就绪
      ▼ 是
orca terminal list --json     → 改标题 → 记 handle（$T_CLAUDE / $T_QWEN / $T_CB）
      │
      ▼
task-create ×3                → 记 taskId（$TASK_xxx）
      │
      ▼
dispatch --inject --dry-run   → 预检
      │
      ▼
dispatch --inject             → 正式派发
      │
      ▼
check --wait --types "worker_done,escalation"
      │
      ├─ escalation → 人工决策 → send 回复
      └─ worker_done → pytest + npm build + 布局体检 → 合并 / 打回
```

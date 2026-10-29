# 协同 · 阶段 K：教师端智能体

> 面向实现者的落地文档。里面每个函数名、字段名、路径都在当前代码库核对过，可直接照抄。
>
> **现状**：`agents/teacher_agent.py` 只有 4 行注释（标注 P5 阶段 TODO），教师端 6 个确定性接口已全部就绪并带权限与留痕。本阶段要做的不是"造新能力"，而是给已有能力接上表达层。

## 0. 定位：一条四段流水线

一句话：**教师端智能体不生产任何数字，只把引擎算好的结论说成人话。**

```
引擎取数 tools.*  →  引擎判定 engine.*  →  模型表达 LLM  →  Critic 守门  →  降级兜底
   （已有）            （已有）            （本阶段新增）     （已有）        （已有）
```

前两段和最后一段**都不用写**，本阶段只补中间那一段 + 把它串起来。任何"让模型算个数/判个色/排个序"的写法都违反分工，会被 Critic 拦下。

四个节点：

| 节点 | 干什么 | 数据来源（已存在） |
|---|---|---|
| 1 班级学情周报 | 把班级概貌翻译成一段客观摘要 + 本周关注点 | `tools.class_overview` |
| 2 预警名单解读 | 把 `risk_score` 与 `reasons` 讲成人话 + 干预建议 + 优先级 | `tools.warning_list` |
| 3 教学干预建议 | 读班级能力与岗位需求差距，给教学调整建议 | `tools.career_gap` |
| 4 教师自由问答 | 教师用自然语言问本班问题，引擎取数后作答 | 上述三个 + `tools.student_profile` |

---

## 1. 可直接复用的资产（不要重写）

| 资产 | 位置 | 用法 |
|---|---|---|
| `get_teacher_llm()` | `agents/llm.py:50` | 教师端 LLM 单例（temperature=0.2，偏严谨），**已存在** |
| `generate_reply(...)` | `agents/llm.py:112` | 推荐入口。LLM 不可用时返回 `None`（内部 try/except 吞掉异常），**必须用它而不是直接 invoke** |
| `_invoke_stream(...)` | `agents/llm.py:86` | 流式，签名 `(actor_type, system_prompt, user_prompt, tag, on_token)` |
| `critic.verify(draft, tool_result)` | `agents/critic.py:180` | 返回 `Verdict(passed, mismatches, fuzzy, reason)` |
| `critic.render_fallback(tool_result)` | `agents/critic.py:209` | 降级话术，**不含任何阿拉伯数字**（末尾有 assert 兜底） |
| `critic.MAX_RETRY` | `agents/critic.py:16` | 重试上限 2，超限走降级 |
| `tools.class_overview(ctx, class_name, term)` | `agents/tools.py:682` | 班级概貌 |
| `tools.warning_list(ctx, class_name, term, level)` | `agents/tools.py:861` | 预警名单 |
| `tools.career_gap(ctx, class_name, term)` | `agents/tools.py:898` | 能力差距 |
| `tools.student_profile(ctx, student_no, term)` | `agents/tools.py:805` | 单人画像 |
| `tools.class_list(ctx)` | `agents/tools.py:444` | 班级目录（含教师可见范围过滤） |
| `_require_teacher` / `_require_class` / `_teacher_class_scope` | `agents/tools.py` | 权限三件套，**每个工具内部已调用，新节点不要再判一次** |
| `_guard(ctx, action, target, call)` | `app/routers/teacher.py:38` | 路由层异常翻译 + 留痕，新接口直接套 |
| `require_teacher` | `app/auth.py` | 路由依赖注入 |

---

## 2. 取数字段清单（照抄，别自己拼 SQL）

### `tools.class_overview` 返回

```
class_name, term, headcount, roster_count, avg_gpa, fail_students,
fail_courses, fail_rate, warning_distribution{LEVELS:int},
top_risk_students[{student_no,name,risk_score,level,coverage}]   # 已按 risk_score 降序取前 5
employment_intent{view_total, top_directions[{direction,views,rate}]}
career_intent{distribution,total,filled,unfilled,fill_rate}
engine_version, calc_version, tools_version
```

### `tools.warning_list` 返回

```
class_name, term, level, count, distribution{LEVELS:int},
items[{student_no, name, risk_score, level, reasons, coverage, missing}]
```
- `reasons` 是 `list[str]`，引擎产物，如 `["本学期挂科6门"]`
- `LEVELS` = `red / orange / yellow / none / unknown`
- `missing` 是未采集到的指标名列表——**"数据不足"档必须如实说，不能跳过**

### `tools.career_gap` 返回

```
class_name, term, target_direction,
class_ability{sample,cert_rate,contest_rate,project_rate,cert_avg,contest_avg,project_avg,gpa_avg},
job_demand{sample_jobs,keyword_rates,top_skills,education_top,salary_range,avg_exp_min},
gaps[{dimension, class_rate, demand_rate, shortfall, level}],
note, engine_version, calc_version, tools_version
```
- `gaps[].level` 已由引擎判好：`shortfall>=0.30→red，>=0.10→orange，否则 none`，缺数据为 `unknown`

### `tools.student_profile` 返回

```
student_no, name, college, major, class_name, grade, term, has_data, tags,
extreme_decline, dimensions{study,behavior,interest,ability},
gpa_trend_series[{term,gpa}],
stored{gpa,gpa_trend,fail_count,class_rank_pct,major_rank_pct,attendance_rate,
       library_visit_cnt,library_activity,cert_count,contest_count,project_cnt,course_pref}
```

---

## 3. 四个节点的落地设计

### 3.0 通用骨架（四个节点共用）

```python
# agents/teacher_agent.py
def _ask(system: str, user: str, *, tag: str) -> str | None:
    return llm_module.generate_reply("teacher", system_prompt=system,
                                     user_prompt=user, tag=tag)
```
`generate_reply` 返回 `None` 表示 LLM 不可用（Key 无效/限流/超时），**必须回退到 `render_fallback`，不能抛给前端**。

草稿 → 定稿流程（四个节点一致）：

```python
tool_result = tools.xxx(ctx, ...)          # 1. 引擎取数
brief = _brief(tool_result)                # 2. 压成给模型看的摘要（只挑要说的关键字段）
draft = _ask(SYSTEM, brief, tag="...")     # 3. 模型表达
if draft is None:
    return _fallback(tool_result)
verdict = critic.verify(draft, tool_result)
for _ in range(critic.MAX_RETRY):          # 4. Critic 守门 + 重试
    if verdict.passed:
        break
    draft = _ask(SYSTEM, brief + "\n" + verdict.feedback(), tag="...retry")
    if draft is None:
        break
    verdict = critic.verify(draft, tool_result)
if draft is None or not verdict.passed:
    draft, degraded = critic.render_fallback(tool_result), True   # 5. 降级兜底
```

给模型看的 `brief` 用 `json.dumps(..., ensure_ascii=False, indent=2)`，与 `career/nodes.py` 保持一致。

---

### 节点 1 · 班级学情周报

```python
def class_brief(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
```
- 取数：`tools.class_overview(ctx, class_name, term)`
- 模型任务：写 150 字以内摘要 + ≤3 条本周关注点
- **不许做**：不改任何数值、不重排 `top_risk_students`（引擎已按 `risk_score` 降序）、不替教师下结论（如"建议开除"）
- 关注点必须能对应 `brief` 里的具体字段（`fail_rate` / `warning_distribution` / `career_intent.unfilled`）

提示词模板：

```
你是高校班级学情周报撰写器。所有数值与等级**已由系统算好**，你只负责翻译成人话。

硬性约束（违反即视为失败）：
1. 不得任何形式的估算、四舍五入、单位换算，「约/大概/估计」与数字同时出现即判不通过；
2. 只依据给定摘要，不得补充摘要里没有的事实（学生姓名只许抄给定的）；
3. 摘要 150 字以内，本周关注点最多 3 条，每条 ≤40 字；
4. 关注点必须指向摘要里的具体字段；数据不足的项要如实说「数据不足」，不许略过；
5. 语气客观、不制造焦虑，不给学生贴人格标签；
6. 只输出 JSON，不要解释文字。

只输出 JSON：
{"摘要": "150 字以内", "本周关注点": ["≤40 字"], "数据不足项": ["原样抄字段名"]}
```

---

### 节点 2 · 预警名单解读（四个节点里最要注意成本）

```python
def warning_brief(ctx: ToolContext, class_name: str, term: str,
                  *, level: str | None = None, top_n: int = 10) -> dict[str, Any]:
```
- 取数：`tools.warning_list(ctx, class_name, term, level)`
- **排序与筛选由代码做**，不让模型碰：先按 `level` 权重（`red>orange>yellow`）再按 `risk_score` 降序，取前 `top_n`（默认 10）
- 全班 40 人若逐个送进提示词，一次调用就上千 token 且耗时陡增——**只解读真正需要干预的那批**
- 模型任务：对每人写「为什么会到这个等级」（基于 `reasons`）+ 一条可执行干预建议
- `missing` 非空的人，必须写「数据不足，结论暂不成立」，不许当成低风险

提示词模板：

```
你是高校学业预警解读助手。名单、风险分、归因、等级**已由系统算好**，你只负责解释与建议。

硬性约束（违反即视为失败）：
1. 不得修改、新增、删除任何风险分与等级，不得改名单顺序；
2. 只解释给定的 reasons，不得编造学生未发生过的事；
3. 每条归因 ≤30 字、每条建议 ≤40 字且必须可执行（谁来做、做什么、什么时候）；
4. coverage 不足或 missing 非空的人，归因里必须写明「数据不足」，且不得据此建议处分；
5. 语气客观、不制造焦虑，不贴人格标签；
6. 只输出 JSON，不要解释文字。

只输出 JSON：
{"解读": [{"学号": "原样抄", "姓名": "原样抄", "等级": "原样抄",
           "归因": "≤30 字", "干预建议": "≤40 字", "数据不足": true/false}]}
```

---

### 节点 3 · 教学干预建议

```python
def intervention_advice(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
```
- 取数：`tools.career_gap(ctx, class_name, term)`
- 模型任务：对每个 `shortfall` 非空的维度，给一条教学侧（课程或实践）调整建议
- **不许做**：不改 `shortfall` 数值、不臆造岗位具体要求（只引用 `job_demand.top_skills`）
- `gaps[].level == "unknown"` 的维度，建议里要写「数据不足，暂不判断」

---

### 节点 4 · 教师自由问答（**不要新建接口**）

`/chat` 现有链路已经可用，改动最小：

- `app/routers/chat.py` 用的是 `get_current_ctx`（不是 `require_student`），师生通用 ✓
- 已有 `_actor(ctx)` 按 `actor_type` 分流 ✓
- 前端 `ChatDrawer.vue` 已按 `currentRole()` 切换示例，教师端可见 ✓
- 已有流式 `/chat/stream` + 一次性 `/chat` 回退 ✓

所以本节点做的是：**在 `agents/graph.py` 的编排里加一条教师分支**，不是另起一套对话接口。

意图路由用**关键词规则**（确定性），不要交给模型选工具：

| 命中条件 | 调用 |
|---|---|
| 含 预警 / 风险 / 红档 / 橙档 / 挂科 / 谁最危险 | `tools.warning_list` |
| 含 概貌 / 均分 / 人数 / 挂科率 / 班级情况 | `tools.class_overview` |
| 含 差距 / 岗位需求 / 能力 / 就业方向 | `tools.career_gap` |
| 正则匹配到学号 `AI\d{8}` | `tools.student_profile` |
| 都不命中 | **不猜**，返回能力清单 + 示例问题 |

最后一条是关键：答不了就说答不了，这是「缺失不冒充」在问答场景的落地。拒答文案：

```
我能回答的是本班这四类问题：班级整体情况、预警名单与风险、某位学生的画像、班级能力与目标岗位的差距。
换一种问法试试，比如「这学期挂科最多的几个人是谁」「AI20230001 最近成绩怎么样」。
```

教师端提问里若带班级名，必须过 `_require_class`（该班不属于该教师可见范围 → 403，不得静默返回别的班数据）。

---

## 4. 接口契约

节点 1/2/3 的新接口放 `app/routers/teacher.py`（复用现成的 `_guard`），前缀用 **`/teacher/advisor`**：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/teacher/advisor/brief` | 班级学情周报，query: `class_name`, `term` |
| GET | `/teacher/advisor/warnings` | 预警名单解读，query: `class_name`, `term`, `level`, `top_n` |
| GET | `/teacher/advisor/intervene` | 教学干预建议，query: `class_name`, `term` |
| POST | `/chat`（**已存在**） | 教师自由问答，走现有对话链路 |

**路径前缀这个坑是真的踩过**：`/teacher` 下有 6 个 SPA 子路由（`''`、`students`、`grades`、`jobs`、`exams`、`kg`），`/student` 下同样有一批。API 一旦和 SPA 路径同名，FastAPI 会先匹配到 API，直接访问页面 URL 返回的是 401 JSON 而不是页面——学生端 `/student/forecast` 就因为这个改成了 `/forecast/me`。所以新接口**不能**叫 `/teacher/grades`、`/teacher/students` 这类名字，`/teacher/advisor/*` 不在 SPA 路由表内，安全。

响应体统一结构（与 career 节点一致）：

```jsonc
{
  "class_name": "...", "term": "2025-2026-2",
  "content": { },                 // 节点各自的 JSON 内容
  "degraded": false,              // true = 走了降级话术（前端要提示「未做数值核对」）
  "critic": { "passed": true, "mismatches": [], "fuzzy": [] },
  "engine_version": "...", "tools_version": "..."
}
```

`degraded=true` 时前端必须显示提示——这是"宁可少说也不给错数"对用户的交代。

---

## 5. 前端接入

- **节点 1/2/3**：`TeacherDashboard.vue` 里加卡片；或在 `ShellLayout.vue` 的 `MENUS.teacher` 加一个 `advisor` 入口（图标字典在 `ShellLayout.vue` 顶部，是 SVG path，加一个即可）
- **节点 4**：**不用改前端**，`ChatDrawer` 已在右下角悬浮且支持教师角色
- 若卡片要展示流式，接口需 SSE；否则一次性返回，前端加 loading 骨架

已知前端坑：`loadDetail()` 在骨架未撤时初始化 ECharts 会导致图表空白（阶段 J 修过一次），加载完成再 init。

---

## 6. 避坑清单（都是实测确认过的，不是推测）

1. **接口路径撞 SPA 路由** —— 见第 4 节。新接口别往 `/teacher/{grades,students,jobs,exams,kg}` 上挂。
2. **Critic 会把 `reasons` 里的数字一并收进白名单**（`critic.py:130` 的 `walk()` 专门处理了字符串叶子，见该函数内 135-140 行的注释）。所以直引 `reasons` 原文是安全的，但**自己算出来的数必被拦**。
3. **模糊词 + 数字 = 直接判不通过**：`约/大概/估计/大约/差不多/似乎/左右` 出现在数字前 8 个字内即 fail。提示词里要明确写「禁止估算」。
4. **降级模板不能含阿拉伯数字**（`render_fallback` 末尾有 `assert`），自写兜底文案时同样别带数字。
5. **LLM 不可用不是异常**：`generate_reply` 返回 `None` 是正常的降级路径，别当成 500 抛出去。
6. **口径一致性**：`gpa_drop = -gpa_trend`（预警侧正数=下降，画像侧负数=下降），由 `tests/test_metric_consistency.py` 强制断言。教师端文案说到趋势时必须与学生端同向，否则答辩现场会被问倒。
7. **权限不要重复判**：`tools.*` 内部已调 `_require_teacher` + `_require_class` + `_teacher_class_scope`，新节点直接用 `ctx` 调工具即可，不要再写一遍租户过滤（重复过滤容易写出不一致的口径）。
8. **成本与延迟**：`warning_list` 会跑全班的 `compute_class`（文档记录过 414ms/40 人），`career_gap` 更重（15.8s 那次是冷启动）。节点 2 务必限制 `top_n`，别把 40 人全塞进提示词。

---

## 7. 测试用例清单（新增 `tests/test_teacher_agent.py`）

纯函数部分（`_brief`、意图路由、排序筛选）不需要连数据库，直接断言：

1. 意图路由：每类关键词各 2 例 → 命中预期工具；无关问题 → 返回拒答且不含任何数字
2. 排序筛选：`warning_list` 假数据 → 结果按 `level` 权重再按 `risk_score` 降序，且长度 ≤ `top_n`
3. `_brief` 不丢字段：`unknown` 等级与 `missing` 非空必须保留到摘要里
4. Critic 拦截：构造含 `平均绩点 88.8` 的草稿（引擎结果里没有）→ `passed=False`，`mismatches` 非空
5. Critic 放过：逐字直引 `reasons` 原文（如「本学期挂科6门」）→ `passed=True`（验证第 6.2 条）
6. 降级：LLM 返回 `None` → 走 `render_fallback`，且断言文本不含阿拉伯数字
7. 越权：学生 token 调教师接口 → 403；教师访问非本班 → 403
8. 口径：教师端提到的 `gpa_trend` 与学生端反号（`test_metric_consistency` 已有同类断言，保持不破）

---

## 8. 验收清单

- [ ] `pytest tests/test_teacher_agent.py -q` 全绿
- [ ] 全量回归不破（当前基线 484 passed）
- [ ] `scripts\smoke_test.ps1` → PASS 12 / FAIL 0（新增接口若要入冒烟，另行加）
- [ ] 教师端（`T001 / teacher@123`）在 `AI2201` 上能看到三个节点的输出，数值与直接调接口一致
- [ ] 断掉 `DEEPSEEK_API_KEY` 后三个节点仍返回降级话术，且页面显示「未做数值核对」提示，不报 500
- [ ] 教师问「这学期谁下滑最快」能命中预警名单；问「食堂几点开门」返回第 3 节那条拒答文案
- [ ] 直接访问 `/teacher/advisor/brief`（浏览器地址栏）不会被 SPA 路由吃掉
- [ ] `npm run build` 通过

---

## 9. 明确不做（本阶段边界）

1. **不新建数据表**。教师端智能体的产出先用 `audit_event` 留痕；确实要存历史周报再单独提建表（career 那 7 张表是前车之鉴，别在没想清楚前扩表）。
2. **不做自动干预动作**（自动发通知、自动约谈）。本阶段只给建议，动作留给教师。
3. **不做跨班/跨年级聚合**。教师可见范围以 `_teacher_class_scope` 为准。
4. **不让学生端接口出现在教师链路里**（反之亦然），角色分流以 `ctx.actor_type` 为准。

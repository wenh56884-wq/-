# 启航系统 · 验收报告（VERIFY.md）

> 生成脚本：`python scripts\gen_verify_report.py`　生成时间：2026-10-27 15:05:02

## 1. 环境水印

- Python 3.12.10（Windows 11）；pytest=9.1.1，duckdb=1.5.5；fastapi=0.143.0，pymysql=2.2.8，duckdb=1.5.5，langgraph=unknown，pytest=9.1.1，pydantic=2.13.5
- 服务地址：http://127.0.0.1:8000（本报告运行时真实调用，非离线拼装）

## 2. 数据源状态

- MySQL：学生 10000 人 / 班级 40 个 / 成绩行 57954 条 / 岗位 2931 条
- DuckDB student_feature：10000 行，版本分布 v1.1=10000
- gpa_trend 值域：-39.91 ~ 27.19；recommend_log：43 条
- 抽查班级：AI2301（20 人在报告样本内）

## 3. 端到端 12 项结果

| # | 检查项 | 结论 | 实测数据 |
| - | - | - | - |
| 1 | /health 全绿 | PASS | status=ok db=ok duckdb=ok llm=configured |
| 2 | 教师登录拿 token | PASS | role=teacher tenant=1 |
| 3 | 班级概览 | PASS | 班级=AI2301 headcount=580 avg_gpa=76.3 |
| 4 | 预警名单 | PASS | 分布：red 47、orange 45、yellow 92、none 396、unknown 0 |
| 5 | 学生画像 | PASS | AI20230001 四维=4 标签=3 |
| 6 | 职业差距 | PASS | target=数据 gaps=3 |
| 7 | 学生登录 | PASS | AI20230001 |
| 8 | 学生查本人预警 | PASS | risk=10 level=none coverage=3 两端一致=True |
| 9 | 学生查他人被拒 | PASS | HTTP 403（目标 AI20230002） |
| 10 | 学生推荐接口 | PASS | version=v1.0 items=5 冷启动=False 候选池=736 |
| 11 | 前端静态托管 | PASS | / 与 /teacher 均回落 web\dist\index.html |
| 12 | 静态资源可加载 | PASS | assets/index-UhrxUEv9.js HTTP 200 |

## 4. 数值一致性（20 人级抽查）

| 一致性检查 | 命中率 | 结论 |
| - | - | - |
| ① gpa 符号一致（gpa_drop == -gpa_trend，20 人） | 20/20 | PASS |
| ② 预警名单命中（20 人） | 20/20 | PASS |
| ③ 推荐可解释项齐全（20 人） | 20/20 | PASS |

## 5. 已知问题与偏差

- 演示数据按「学院 + 年级 + 专业」分班，班级规模为数百人（如 AI2301 约 580 人），
  班级概貌/预警名单具备统计意义；
  大一（2026 级）由 `scripts\seed_mock.py` 整届生成（2498 人 / 16 个班），
  学号形如 `AI20260001`、初始口令与学号相同；`scripts\seed_freshman.py` 已废弃，
  不再需要单独补账号。
- 真实库中没有缺考勤的学生，因此「缺数据 → 灰档 unknown」分支只在单测层面验证，
  演示环境看不到灰档；需要演示时得先构造无考勤记录的学生。
- 推荐的质量受限于招聘站的 skill_tags 噪声（已剔除福利类词）与校内课名口径，
  生活服务类岗位的方向归类偏粗，后续可按专业 + 课程双通道细化。

- 学生端工具 `my_warning` 只返回学号/姓名/学期与指标，不含专业与班级：个人信息卡
  因此只展示接口真正返回的字段，未伪造；如需补齐属于后端改动，未擅自加。

## 6. 下一步

- 交付文档已齐：`docs\VERIFY.md`（本报告）、`docs\答辩PPT大纲.md`（10 页，全用真实字段名）、
  `docs\演示脚本.md`（5 分钟台词 + 三类兜底 + 演示前自检清单）。
- 二期（11/18 之后）：PySpark 迁移 `engine\profile.py`（逐字段比对，一致率须 100%）、
  推荐加协同过滤（`final = 0.7*A + 0.3*B`，冷启动跳过）、多院校租户横向扩展。

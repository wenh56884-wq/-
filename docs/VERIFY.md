# 启航系统 · 验收报告（VERIFY.md）

> 生成脚本：`python scripts\gen_verify_report.py`　生成时间：2026-10-26 21:06:28

## 1. 环境水印

- Python 3.12.10（Windows 11）；pytest=9.1.1，duckdb=1.5.5；fastapi=0.143.0，pymysql=2.2.8，duckdb=1.5.5，langgraph=unknown，pytest=9.1.1，pydantic=2.13.5
- 服务地址：http://127.0.0.1:8000（本报告运行时真实调用，非离线拼装）

## 2. 数据源状态

- MySQL：学生 500 人 / 班级 500 个 / 成绩行 2918 条 / 岗位 2931 条
- DuckDB student_feature：500 行，版本分布 v1.1=500
- gpa_trend 值域：-36.99 ~ 21.06；recommend_log：108 条
- 抽查班级：AI2201（20 人在报告样本内）

## 3. 端到端 10 项结果

| # | 检查项 | 结论 | 实测数据 |
| - | - | - | - |
| 1 | /health 全绿 | PASS | status=ok db=ok duckdb=ok llm=configured |
| 2 | 教师登录拿 token | PASS | role=teacher tenant=1 |
| 3 | 班级概览 | PASS | 班级=AI2201 headcount=1 avg_gpa=46.0 |
| 4 | 预警名单 | PASS | 分布：red 1、orange 0、yellow 0、none 0、unknown 0 |
| 5 | 学生画像 | PASS | AI2022001 四维=4 标签=4 |
| 6 | 职业差距 | PASS | target=数据 gaps=3 |
| 7 | 学生登录 | PASS | AI2022001 |
| 8 | 学生查本人预警 | PASS | risk=100 level=red coverage=3 两端一致=True |
| 9 | 学生查他人被拒 | PASS | HTTP 403（目标 AI2022002） |
| 10 | 学生推荐接口 | PASS | version=v1.0 items=5 冷启动=False 候选池=400 |

## 4. 数值一致性（20 人级抽查）

| 一致性检查 | 命中率 | 结论 |
| - | - | - |
| ① gpa 符号一致（gpa_drop == -gpa_trend，20 人） | 20/20 | PASS |
| ② 预警名单命中（20 人） | 20/20 | PASS |
| ③ 推荐可解释项齐全（20 人） | 20/20 | PASS |

## 5. 已知问题与偏差

- 演示数据里班级人数普遍为 1 人（seed_mock 给每人分配独立班级），班级概貌/预警名单可跑通，
  但群体画像的统计意义有限；若要看多人的班级视图，需要重新 seed 把学生归到若干固定班级。
- 真实库中没有缺考勤的学生，因此「缺数据 → 灰档 unknown」分支只在单测层面验证，
  演示环境看不到灰档；需要演示时得先构造无考勤记录的学生。
- 推荐的质量受限于招聘站的 skill_tags 噪声（已剔除福利类词）与校内课名口径，
  生活服务类岗位的方向归类偏粗，后续可按专业 + 课程双通道细化。

## 6. 下一步

- P10：Vue 前端（教师看板 / 学生端 / 静态托管）；P11：验收文档与汇报材料。
- 预留：warning_threshold 覆盖、租户多院校横向扩展、LLM 摘要润色（须过 Critic）。

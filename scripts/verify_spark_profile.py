# scripts/verify_spark_profile.py
# 二期②验收：pandas 版画像 vs Spark 版画像，逐字段一致率必须 100%。
#
# 用法：
#   .venv\Scripts\python.exe scripts\verify_spark_profile.py            # 全量 1 万学生
#   .venv\Scripts\python.exe scripts\verify_spark_profile.py --limit 500
#
# 两边吃的是**同一批** raw 行（scripts/build_profile_raw.assemble_rows 的真实
# 生产输入），pandas 走 engine/profile.build_features，Spark 走
# features/batch_features.spark_build_rows，逐字段对比 to_feature_row 的全部键。

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.profile import build_features, to_feature_row  # noqa: E402
from features.batch_features import spark_build_rows  # noqa: E402
from scripts.build_profile_raw import assemble_rows  # noqa: E402

# 与 engine/profile.to_feature_row 完全一致的输出键序
_FIELDS = (
    "student_no", "term", "gpa", "gpa_trend", "extreme_decline", "fail_count",
    "class_rank_pct", "major_rank_pct", "attendance_rate", "library_visit_cnt",
    "library_activity", "consumption_regularity", "course_pref",
    "job_view_cnt", "job_favorite_cnt", "cert_count", "contest_count",
    "project_cnt", "tags", "calc_version",
)


def _norm(v):
    """把两边类型归一成可比较形态（Spark map→dict、None 语义统一）。"""
    if isinstance(v, dict):
        return {str(k): round(float(x), 6) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return str(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="pandas vs Spark 画像口径一致性验收")
    ap.add_argument("--tenant", type=int, default=1)
    ap.add_argument("--term", default="2025-2026-2")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 行做快验；0=全量")
    args = ap.parse_args(argv)

    raw_rows = assemble_rows(args.tenant, args.term)
    if args.limit:
        raw_rows = raw_rows[: args.limit]
    print(f"raw 行数：{len(raw_rows)}（term={args.term}）")
    if not raw_rows:
        print("无数据可对比")
        return 1

    # pandas 基准（引擎原版）
    pandas_rows = []
    for raw in raw_rows:
        row = to_feature_row(build_features(raw))
        if not row["term"]:
            row["term"] = args.term
        pandas_rows.append(row)

    # Spark 版
    from scripts.spark_env import get_spark

    spark = get_spark("verify-spark-profile")
    try:
        spark_rows = spark_build_rows(spark, raw_rows)
    finally:
        spark.stop()

    if len(pandas_rows) != len(spark_rows):
        print(f"行数不一致：pandas {len(pandas_rows)} vs spark {len(spark_rows)}")
        return 1

    # Spark 经 explode/groupBy/join 会 shuffle，collect 顺序不可保证；
    # 对比必须按 student_no 对齐，绝不能按位置 zip。
    pmap = {r["student_no"]: r for r in pandas_rows}
    smap = {r["student_no"]: r for r in spark_rows}
    if set(pmap) != set(smap):
        only_p = sorted(set(pmap) - set(smap))[:5]
        only_s = sorted(set(smap) - set(pmap))[:5]
        print(f"学生集合不一致：仅pandas {only_p} 仅spark {only_s}")
        return 1
    idx = [(pmap[s], smap[s]) for s in sorted(pmap)]

    field_bad: dict[str, int] = {f: 0 for f in _FIELDS}
    examples: dict[str, str] = {}
    n = 0
    for pr, sr in idx:
        n += 1
        for f in _FIELDS:
            if _norm(pr.get(f)) != _norm(sr.get(f)):
                field_bad[f] += 1
                if f not in examples:
                    examples[f] = (
                        f"student={pr.get('student_no')} pandas={pr.get(f)!r} "
                        f"spark={sr.get(f)!r}")

    total = n * len(_FIELDS)
    bad = sum(field_bad.values())
    print()
    print(f"{'字段':<24} 不一致数")
    for f in _FIELDS:
        mark = "" if field_bad[f] == 0 else "  <-- 有差异"
        print(f"  {f:<24} {field_bad[f]:>5}{mark}")
    rate = (total - bad) / total * 100 if total else 0.0
    print()
    print(f"逐字段一致率：{rate:.4f}%  （{total - bad}/{total}）")
    if examples:
        print()
        print("首个差异示例：")
        for f, msg in examples.items():
            print(f"  [{f}] {msg}")
    if bad == 0:
        print("验收通过：两版口径 100% 一致")
        return 0
    print("验收不通过：存在口径漂移，必须修到 100%")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

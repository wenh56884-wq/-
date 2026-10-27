# features/batch_features.py
# 二期·特征工程 Spark 版：用 PySpark DataFrame API 复现 engine/profile.py 的口径。
#
# 口径来源（唯一事实）：
#   - engine/profile.py 的 build_features / make_tags / to_feature_row（CALC_VERSION v1.1）
#   - docs/指标口径字典.md
#
# 验收（手册阶段 J 第二次交付）：与 pandas 版逐字段一致率必须 100%。
#   对比脚本：scripts/verify_spark_profile.py
#
# 实现要点：
#   1. 舍入对齐：Python round() 是「银行家舍入」(half-even)，Spark 的 F.round 是
#      half-up——小数位恰为 5 时两者会差 1。所以全篇统一用 F.bround（half-even）。
#   2. 缺失即 NULL：Spark 的列运算天然满足 null 传播，凡「缺失不冒充」的子指标
#      一律不 coalesce 补 0，与引擎的 None 语义逐位对齐。
#   3. 维度得分 = Σ(子指标×权重) / Σ(非缺失项权重)，全部缺失 → NULL。
#   4. top_direction 需要跨两个 map 字段按方向求加权频次，explode + groupBy 实现；
#      平局按方向名升序打破，与引擎 sorted(key=(-freq, name)) 一致。

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from engine.profile import CALC_VERSION

# ----------------------------------------------------------------
# 常量（与 engine/profile.py 逐一对齐，改口径必须两边同步）
# ----------------------------------------------------------------
GPA_MIN, GPA_MAX = 0.0, 100.0
TREND_MIN, TREND_MAX = -40.0, 20.0
EXTREME_DECLINE_AT = -30.0
FAIL_CAP = 3.0
LIBRARY_CAP = 60.0
PREF_CAP = 6.0
JOB_VIEW_CAP = 50.0
JOB_FAV_CAP = 20.0
CERT_CAP = 3.0
CONTEST_CAP = 2.0
PROJECT_CAP = 2.0
JOB_VIEW_DIRECTION_WEIGHT = 0.5

STUDY_WEIGHTS: dict[str, float] = {
    "gpa": 0.40, "gpa_trend": 0.20, "fail_count": 0.20, "major_rank_pct": 0.20,
}
BEHAVIOR_WEIGHTS: dict[str, float] = {
    "attendance_rate": 0.50, "library_activity": 0.30, "consumption_regularity": 0.20,
}
INTEREST_WEIGHTS: dict[str, float] = {
    "course_pref": 0.40, "job_view_cnt": 0.30, "job_favorite_cnt": 0.30,
}
ABILITY_WEIGHTS: dict[str, float] = {
    "project_cnt": 0.40, "cert_count": 0.30, "contest_count": 0.30,
}

_HAS_DATA_KEYS: tuple[str, ...] = (
    "gpa", "gpa_trend", "fail_count", "class_rank_pct", "major_rank_pct",
    "attendance_rate", "library_activity", "library_visit_cnt",
    "consumption_regularity", "course_pref", "job_view_cnt",
    "job_view_pref", "job_favorite_cnt",
    "cert_count", "contest_count", "project_cnt",
)

# ----------------------------------------------------------------
# 输入 schema：raw 行（与 scripts/build_profile_raw.assemble_rows 对齐）
# ----------------------------------------------------------------
_RAW_SCHEMA = T.StructType([
    T.StructField("student_no", T.StringType(), True),
    T.StructField("term", T.StringType(), True),
    T.StructField("gpa", T.DoubleType(), True),
    T.StructField("gpa_trend", T.DoubleType(), True),
    T.StructField("fail_count", T.IntegerType(), True),
    T.StructField("class_rank_pct", T.DoubleType(), True),
    T.StructField("major_rank_pct", T.DoubleType(), True),
    T.StructField("attendance_rate", T.DoubleType(), True),
    T.StructField("library_activity", T.DoubleType(), True),
    T.StructField("library_visit_cnt", T.DoubleType(), True),
    T.StructField("consumption_regularity", T.DoubleType(), True),
    T.StructField("course_pref", T.MapType(T.StringType(), T.DoubleType()), True),
    T.StructField("job_view_cnt", T.IntegerType(), True),
    T.StructField("job_view_pref", T.MapType(T.StringType(), T.DoubleType()), True),
    T.StructField("job_favorite_cnt", T.IntegerType(), True),
    T.StructField("cert_count", T.IntegerType(), True),
    T.StructField("contest_count", T.IntegerType(), True),
    T.StructField("project_cnt", T.IntegerType(), True),
])


# ----------------------------------------------------------------
# 列级口径原语（逐行 map-only，对应 profile 的 _clamp01/_min_max/_saturate）
# ----------------------------------------------------------------
def _clamp01(col: F.Column) -> F.Column:
    # Spark 的 greatest/least 会跳过 NULL（greatest(0, null)==0），必须先用 when
    # 守住 null，否则「缺失」会被冒充成 0，违反引擎的缺失语义。
    return F.when(col.isNull(), F.lit(None)).otherwise(
        F.bround(F.greatest(F.lit(0.0), F.least(F.lit(1.0), col)), 4))


def _min_max(col: F.Column, low: float, high: float) -> F.Column:
    return _clamp01((col - F.lit(low)) / F.lit(high - low))


def _saturate(col: F.Column, cap: float) -> F.Column:
    return _clamp01(col / F.lit(cap))


def _weighted(norms: dict[str, F.Column], weights: dict[str, float]) -> F.Column:
    """Σ(值×权重)/Σ(非缺失权重)；全缺失 → NULL。"""
    num = F.lit(0.0)
    den = F.lit(0.0)
    for key, w in weights.items():
        col = norms[key]
        num = num + F.coalesce(col * F.lit(w), F.lit(0.0))
        den = den + F.when(col.isNull(), F.lit(0.0)).otherwise(F.lit(w))
    return F.when(den > 0, F.bround(num / den, 4)).otherwise(F.lit(None))


# ----------------------------------------------------------------
# top_direction：course_pref 权重 1 + job_view_pref 权重 0.5，平局按名称升序
# ----------------------------------------------------------------
def _top_direction(df: DataFrame) -> DataFrame:
    a = (df.where(F.size("course_pref") > 0)
         .select("student_no", F.lit(1.0).alias("w"),
                 F.explode("course_pref").alias("direction", "cnt")))
    b = (df.where(F.size("job_view_pref") > 0)
         .select("student_no", F.lit(JOB_VIEW_DIRECTION_WEIGHT).alias("w"),
                 F.explode("job_view_pref").alias("direction", "cnt")))
    both = a.unionByName(b).where(F.col("cnt") > 0)
    agg = (both.groupBy("student_no", "direction")
           .agg(F.bround(F.sum(F.col("w") * F.col("cnt")), 4).alias("freq")))
    win = Window.partitionBy("student_no").orderBy(
        F.col("freq").desc(), F.col("direction").asc())
    top = agg.withColumn("_rn", F.row_number().over(win)).where("_rn = 1")
    return df.join(top.select("student_no",
                              F.col("direction").alias("top_direction")),
                   on="student_no", how="left")


# ----------------------------------------------------------------
# 主入口：raw 行 → 落库行（与 to_feature_row 字段一一对应）
# ----------------------------------------------------------------
def spark_build_rows(spark, raw_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """与 engine.profile.batch_build 的逐行产物做逐字段对比。

    输入 raw 行的字段缺失用 None 表示（缺失不冒充）；course_pref / job_view_pref
    传 {方向: 次数} 字典。返回 list[dict]，键与 to_feature_row 完全一致。
    """
    if not raw_rows:
        return []

    def _f(x):
        """PySpark 4 严格校验：DoubleType 只收 float，int/Decimal 一律转。"""
        return None if x is None else float(x)

    def _i(x):
        return None if x is None else int(x)

    norm_rows = []
    for r in raw_rows:
        norm_rows.append({
            "student_no": str(r.get("student_no") or ""),
            "term": str(r.get("term") or ""),
            "gpa": _f(r.get("gpa")),
            "gpa_trend": _f(r.get("gpa_trend")),
            "fail_count": _i(r.get("fail_count")),
            "class_rank_pct": _f(r.get("class_rank_pct")),
            "major_rank_pct": _f(r.get("major_rank_pct")),
            "attendance_rate": _f(r.get("attendance_rate")),
            "library_activity": _f(r.get("library_activity")),
            "library_visit_cnt": _f(r.get("library_visit_cnt")),
            "consumption_regularity": _f(r.get("consumption_regularity")),
            "course_pref": (None if not r.get("course_pref")
                            else {str(k): float(v) for k, v in r["course_pref"].items()}),
            "job_view_cnt": _i(r.get("job_view_cnt")),
            "job_view_pref": (None if not r.get("job_view_pref")
                              else {str(k): float(v) for k, v in r["job_view_pref"].items()}),
            "job_favorite_cnt": _i(r.get("job_favorite_cnt")),
            "cert_count": _i(r.get("cert_count")),
            "contest_count": _i(r.get("contest_count")),
            "project_cnt": _i(r.get("project_cnt")),
        })
    df = spark.createDataFrame(norm_rows, schema=_RAW_SCHEMA)

    # --- 学业 ---
    fail_n = F.when(F.col("fail_count").isNull(), F.lit(None)).otherwise(
        _clamp01(F.lit(1.0) - F.least(F.lit(1.0),
                                      F.greatest(F.lit(0.0),
                                                 F.col("fail_count").cast("double"))
                                      / F.lit(FAIL_CAP))))
    rank_n = F.when(F.col("major_rank_pct").isNull(), F.lit(None)).otherwise(
        _clamp01(F.lit(1.0) - F.col("major_rank_pct")))
    study_norms = {
        "gpa": F.when(F.col("gpa").isNull(), F.lit(None)).otherwise(
            _min_max(F.col("gpa"), GPA_MIN, GPA_MAX)),
        "gpa_trend": F.when(F.col("gpa_trend").isNull(), F.lit(None)).otherwise(
            _min_max(F.col("gpa_trend"), TREND_MIN, TREND_MAX)),
        "fail_count": fail_n,
        "major_rank_pct": rank_n,
    }
    extreme = F.coalesce(F.col("gpa_trend") <= F.lit(EXTREME_DECLINE_AT), F.lit(False))

    # --- 行为 ---
    lib_n = (F.when(F.col("library_activity").isNotNull(),
                    _clamp01(F.col("library_activity")))
             .when(F.col("library_visit_cnt").isNotNull(),
                   _saturate(F.col("library_visit_cnt"), LIBRARY_CAP))
             .otherwise(F.lit(None)))
    behavior_norms = {
        "attendance_rate": F.when(F.col("attendance_rate").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("attendance_rate"))),
        "library_activity": lib_n,
        "consumption_regularity": F.when(F.col("consumption_regularity").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("consumption_regularity"))),
    }

    # --- 兴趣 ---
    pref_total = (F.when(F.size("course_pref") == 0, F.lit(None))
                  .otherwise(F.aggregate(F.map_values("course_pref"), F.lit(0.0),
                                         lambda acc, x: acc + x)))
    interest_norms = {
        "course_pref": _saturate(pref_total, PREF_CAP),
        "job_view_cnt": F.when(F.col("job_view_cnt").isNull(), F.lit(None)).otherwise(
            _saturate(F.col("job_view_cnt").cast("double"), JOB_VIEW_CAP)),
        "job_favorite_cnt": F.when(F.col("job_favorite_cnt").isNull(), F.lit(None)).otherwise(
            _saturate(F.col("job_favorite_cnt").cast("double"), JOB_FAV_CAP)),
    }

    # --- 能力 ---
    ability_norms = {
        "cert_count": F.when(F.col("cert_count").isNull(), F.lit(None)).otherwise(
            _saturate(F.col("cert_count").cast("double"), CERT_CAP)),
        "contest_count": F.when(F.col("contest_count").isNull(), F.lit(None)).otherwise(
            _saturate(F.col("contest_count").cast("double"), CONTEST_CAP)),
        "project_cnt": F.when(F.col("project_cnt").isNull(), F.lit(None)).otherwise(
            _saturate(F.col("project_cnt").cast("double"), PROJECT_CAP)),
    }

    # --- has_data（任一业务字段非空） ---
    has_data = F.lit(False)
    for k in _HAS_DATA_KEYS:
        has_data = has_data | F.col(k).isNotNull()

    df = (df
          .withColumn("study_score", _weighted(study_norms, STUDY_WEIGHTS))
          .withColumn("behavior_score", _weighted(behavior_norms, BEHAVIOR_WEIGHTS))
          .withColumn("interest_score", _weighted(interest_norms, INTEREST_WEIGHTS))
          .withColumn("ability_score", _weighted(ability_norms, ABILITY_WEIGHTS))
          .withColumn("has_data", has_data)
          .withColumn("extreme_decline", extreme)
          .withColumn("lib_out", lib_n)
          .withColumn("cp_out",
                      F.when(F.size("course_pref") == 0, F.lit(None)).otherwise(
                          F.map_from_entries(
                              F.transform(F.map_entries("course_pref"),
                                          lambda e: F.struct(
                                              e["key"].alias("k"),
                                              e["value"].cast("double").alias("v"))))))
          )

    df = _top_direction(df)

    # --- 标签（与 make_tags 逐条对齐） ---
    study_tag = (F.when(F.col("major_rank_pct").isNull(), F.lit("学业数据不足"))
                 .when(F.col("major_rank_pct") <= 0.20, F.lit("专业前20%"))
                 .when(F.col("major_rank_pct") <= 0.50, F.lit("专业前50%"))
                 .otherwise(F.lit("专业后50%")))
    dir_tag = (F.when(F.col("top_direction").isNull(), F.lit("方向未明"))
               .otherwise(F.concat(
                   F.lit("偏好"), F.col("top_direction"),
                   F.when(F.col("top_direction").rlike("(岗|方向|类)$"),
                          F.lit("")).otherwise(F.lit("岗")))))
    ability_tag = (F.when(F.col("project_cnt").isNotNull() & (F.col("project_cnt") == 0),
                          F.lit("缺乏项目经历"))
                   .when(F.col("cert_count").isNotNull() & (F.col("cert_count") == 0),
                         F.lit("无技能证书"))
                   .when(F.col("contest_count").isNotNull() & (F.col("contest_count") == 0),
                         F.lit("未参加学科竞赛"))
                   .when(F.col("project_cnt").isNotNull() | F.col("cert_count").isNotNull()
                         | F.col("contest_count").isNotNull(),
                         F.lit("能力履历完整"))
                   .otherwise(F.lit("能力数据不足")))
    tags = (F.when(~F.col("has_data"), F.array(F.lit("数据不足")))
            .otherwise(F.when(F.col("extreme_decline"),
                              F.array(study_tag, dir_tag, ability_tag,
                                      F.lit("学业急剧下滑")))
                       .otherwise(F.array(study_tag, dir_tag, ability_tag))))

    out = df.select(
        F.col("student_no"),
        F.col("term"),
        F.bround("gpa", 2).alias("gpa"),
        F.bround("gpa_trend", 2).alias("gpa_trend"),
        F.col("extreme_decline"),
        F.col("fail_count"),
        F.when(F.col("class_rank_pct").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("class_rank_pct"))).alias("class_rank_pct"),
        F.when(F.col("major_rank_pct").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("major_rank_pct"))).alias("major_rank_pct"),
        F.when(F.col("attendance_rate").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("attendance_rate"))).alias("attendance_rate"),
        F.col("library_visit_cnt").cast("int").alias("library_visit_cnt"),
        F.col("lib_out").alias("library_activity"),
        F.when(F.col("consumption_regularity").isNull(), F.lit(None)).otherwise(
            _clamp01(F.col("consumption_regularity"))).alias("consumption_regularity"),
        F.col("cp_out").alias("course_pref"),
        F.col("job_view_cnt"),
        F.col("job_favorite_cnt"),
        F.col("cert_count"),
        F.col("contest_count"),
        F.col("project_cnt"),
        tags.alias("tags"),
        F.lit(CALC_VERSION).alias("calc_version"),
    )
    result = [r.asDict(recursive=True) for r in out.collect()]
    return result

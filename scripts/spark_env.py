# scripts/spark_env.py
# 二期 Spark 环境统一入口：任何要用 PySpark 的脚本先 `from scripts.spark_env import get_spark`。
#
# 为什么不把 JAVA_HOME 设成系统全局：
#   本机 D:\bigdata\jdk 是 Java 8（大数据集群课程在用），Spark 4 必须 Java 17+。
#   这里把 JDK 17 装在项目内 tools\jdk-17.0.20.1+1，只在进程级注入，互不干扰。

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_JDK17 = _ROOT / "tools" / "jdk-17.0.20.1+1"
_PYTHON = sys.executable


def ensure_env() -> None:
    """进程级注入 Spark 所需环境变量（幂等，可重复调用）。"""
    if _JDK17.exists():
        os.environ["JAVA_HOME"] = str(_JDK17)
    else:
        raise FileNotFoundError(
            f"未找到 JDK 17：{_JDK17}。先按手册安装 Temurin 17 到 tools/ 目录。"
        )
    os.environ["PYSPARK_PYTHON"] = _PYTHON
    os.environ["PYSPARK_DRIVER_PYTHON"] = _PYTHON
    # winutils：Windows 上写本地文件（parquet 等）必需，聚合计算不需要
    _winutils = _ROOT / "tools" / "winutils"
    if _winutils.exists():
        os.environ.setdefault("HADOOP_HOME", str(_winutils))
        os.environ["PATH"] = f"{_winutils}\\bin;" + os.environ.get("PATH", "")


def get_spark(app_name: str = "qihang", shuffle_partitions: int = 4):
    """创建本地 SparkSession（关闭 UI、固定 driver host 避免 Windows 网卡解析问题）。"""
    ensure_env()
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.master("local[*]")
        .appName(app_name)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .getOrCreate()
    )


if __name__ == "__main__":
    spark = get_spark("smoke")
    from pyspark.sql import functions as F

    n = spark.range(100_000).select((F.col("id") % 10).alias("k")).groupBy("k").count()
    rows = n.orderBy("k").collect()
    print("SMOKE OK:", [(r["k"], r["count"]) for r in rows])
    spark.stop()

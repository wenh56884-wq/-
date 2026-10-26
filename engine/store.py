# engine/store.py
# 职责：存储抽象接口 Store + DuckDBStore 实现 + ClickHouseStore 留空
# 依赖：duckdb / app.config / pathlib
# 说明：业务代码只依赖 Store 接口，二期切换 ClickHouse 零改动

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from contextlib import closing
from pathlib import Path
from typing import Any

import duckdb

from app.config import get_settings


class Store(ABC):
    """分析层存储抽象接口。

    所有数值读写都经过此接口，业务代码只依赖 Store，
    二期从 DuckDB 切换到 ClickHouse 时只需替换实现类。
    """

    @abstractmethod
    def write_student_feature(self, feature: dict[str, Any]) -> int:
        """写入单条学生特征记录，返回受影响行数。"""

    @abstractmethod
    def read_student_feature(self, student_no: str, term: str) -> dict[str, Any] | None:
        """读取单条学生特征记录，不存在返回 None。"""

    @abstractmethod
    def write_recommend_log(self, log: dict[str, Any]) -> int:
        """写入单条推荐日志，返回受影响行数。"""

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查：能成功执行一条简单查询返回 True，否则 False。"""


class DuckDBStore(Store):
    """DuckDB 嵌入式分析层实现。

    路径从 app.config 读取（D:/qihang/data/analytics.duckdb）。
    每次操作独立连接，DuckDB 嵌入式无需连接池。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is not None:
            self._db_path = db_path
        else:
            self._db_path = get_settings().duckdb_path_obj
        # 确保父目录存在
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self, *, readonly: bool = False) -> duckdb.DuckDBPyConnection:
        """打开 DuckDB 连接。

        调用方必须用 `closing(...)` 包住，不能用 `with conn:`。
        DuckDB 的连接上下文管理器只做事务提交/回滚，**不关闭连接**，
        批量写 500 次就会攒下 500 个未释放的句柄，最后
        `IOException: Cannot open file ... 另一个程序正在使用此文件`。

        DuckDB 的写锁是**整库独占**的：服务在跑时本机再执行 pytest /
        build_profile_raw.py，后到的一方就会报「另一个程序正在使用此文件」。
        所以这里分三步退让：读写 → 短暂重试 → 只读。
        读接口拿不到写锁时降级为只读是安全的（只是不能写）；
        写接口最终也拿不到锁才抛错，让调用方知道这次真没写进去。
        """
        attempts = [readonly, readonly, True]  # 第三次强制以只读方式兜底
        last: Exception | None = None
        for index, ro in enumerate(attempts):
            try:
                return duckdb.connect(str(self._db_path), read_only=ro)
            except (duckdb.IOException, RuntimeError) as exc:
                last = exc
                if index < len(attempts) - 1:
                    time.sleep(0.15 * (index + 1))
        raise last if last is not None else RuntimeError(f"无法连接 {self._db_path}")

    def write_student_feature(self, feature: dict[str, Any]) -> int:
        """写入单条学生特征记录（upsert 语义）。"""
        cols = [
            "student_no", "term", "gpa", "gpa_trend", "extreme_decline", "fail_count",
            "class_rank_pct", "major_rank_pct", "attendance_rate",
            "library_visit_cnt", "library_activity",
            "consumption_regularity", "course_pref", "job_view_cnt",
            "job_favorite_cnt", "cert_count", "contest_count",
            "project_cnt", "tags", "calc_version",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)
        sql = (
            f"INSERT OR REPLACE INTO student_feature ({col_list}) "
            f"VALUES ({placeholders})"
        )
        values = []
        for c in cols:
            v = feature.get(c)
            if c in ("course_pref", "tags") and v is not None:
                values.append(json.dumps(v, ensure_ascii=False))
            else:
                values.append(v)
        with closing(self._connect()) as conn:
            conn.execute(sql, values)
        return 1

    def read_student_feature(self, student_no: str, term: str) -> dict[str, Any] | None:
        """读取单条学生特征记录。"""
        sql = (
            "SELECT student_no, term, gpa, gpa_trend, extreme_decline, fail_count, "
            "class_rank_pct, major_rank_pct, attendance_rate, "
            "library_visit_cnt, library_activity, "
            "consumption_regularity, course_pref, job_view_cnt, "
            "job_favorite_cnt, cert_count, contest_count, "
            "project_cnt, tags, calc_version, updated_at "
            "FROM student_feature WHERE student_no = ? AND term = ?"
        )
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute(sql, [student_no, term]).fetchone()
        if row is None:
            return None
        cols = [
            "student_no", "term", "gpa", "gpa_trend", "extreme_decline", "fail_count",
            "class_rank_pct", "major_rank_pct", "attendance_rate",
            "library_visit_cnt", "library_activity",
            "consumption_regularity", "course_pref", "job_view_cnt",
            "job_favorite_cnt", "cert_count", "contest_count",
            "project_cnt", "tags", "calc_version", "updated_at",
        ]
        result = dict(zip(cols, row))
        # JSON 字段反序列化
        for jf in ("course_pref", "tags"):
            v = result.get(jf)
            if isinstance(v, str) and v:
                try:
                    result[jf] = json.loads(v)
                except ValueError:
                    # 脏数据不阻断画像读取：按缺失处理，避免整条记录不可用
                    result[jf] = {} if jf == "course_pref" else []
        return result

    def write_recommend_log(self, log: dict[str, Any]) -> int:
        """写入单条推荐日志。"""
        cols = [
            "id", "student_no", "job_id", "content_score", "cf_score",
            "final_score", "hit_items", "gap_items", "advice",
            "engine_version",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)
        sql = (
            f"INSERT INTO recommend_log ({col_list}) "
            f"VALUES ({placeholders})"
        )
        values = []
        for c in cols:
            v = log.get(c)
            if c in ("hit_items", "gap_items") and v is not None:
                values.append(json.dumps(v, ensure_ascii=False))
            else:
                values.append(v)
        with closing(self._connect()) as conn:
            conn.execute(sql, values)
        return 1

    def health_check(self) -> bool:
        """健康检查：执行 SELECT 1。只读即可，别去抢写锁。"""
        try:
            with closing(self._connect(readonly=True)) as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False


class ClickHouseStore(Store):
    """ClickHouse 分析层实现（二期预留，当前不可用）。

    二期切换时实现此类的全部方法，业务代码替换 Store 工厂即可。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("ClickHouseStore 尚未实现，二期切换时补全")

    def write_student_feature(self, feature: dict[str, Any]) -> int:
        raise NotImplementedError

    def read_student_feature(self, student_no: str, term: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def write_recommend_log(self, log: dict[str, Any]) -> int:
        raise NotImplementedError

    def health_check(self) -> bool:
        raise NotImplementedError

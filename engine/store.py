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
from typing import Any, Sequence

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

    def write_student_features(self, features: Sequence[dict[str, Any]]) -> int:
        """批量 upsert 学生特征，返回写入条数。

        默认实现逐条调用 write_student_feature（保证任何 Store 实现都能用）；
        具体实现可以覆写成批量语句。1 万人规模下逐条写要 7 分钟，
        批量写只要几秒 —— 差异全在「每条一次连接 + 一次事务」的开销上。
        """
        n = 0
        for f in features:
            n += self.write_student_feature(f)
        return n

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

        重试策略按用途区分，这点很关键：
        - 读（readonly=True）：读写 → 只读 → 重试。拿不到写锁就退只读，
          照常能查数据，接口不会 500。
        - 写（readonly=False）：**只能以读写模式重试，绝不降级为只读**。
          降级成只读后 INSERT 会抛
          `Cannot execute statement of type "INSERT" ... attached in read-only mode`，
          调用方会误以为写成功了，比直接报锁冲突更糟。
        """
        if readonly:
            attempts = [False, True, True, True]
        else:
            attempts = [False, False, False, False]
        last: Exception | None = None
        for index, ro in enumerate(attempts):
            try:
                return duckdb.connect(str(self._db_path), read_only=ro)
            except (duckdb.IOException, RuntimeError) as exc:
                last = exc
                if index < len(attempts) - 1:
                    time.sleep(0.2 * (index + 1))
        hint = "（读写锁被其他进程占用，请先关闭正在运行的测试或建缓存脚本）" if not readonly else ""
        raise last if last is not None else RuntimeError(f"无法连接 {self._db_path}{hint}")

    # student_feature 的列顺序（写入/批量写入共用，避免两处各写一遍写歪）
    # _FEATURE_COLS：Python 侧键名（英文，接口与前端都依赖它，保持不变）
    # _FEATURE_DB_COLS：库中真实列名（中文），顺序与上面一一对应
    _FEATURE_COLS = (
        "student_no", "term", "gpa", "gpa_trend", "extreme_decline", "fail_count",
        "class_rank_pct", "major_rank_pct", "attendance_rate",
        "library_visit_cnt", "library_activity",
        "consumption_regularity", "course_pref", "job_view_cnt",
        "job_favorite_cnt", "cert_count", "contest_count",
        "project_cnt", "tags", "calc_version",
    )
    _FEATURE_TABLE = '"学生特征"'
    _FEATURE_DB_COLS = (
        '"学号"', '"学期"', '"绩点"', '"绩点趋势"', '"是否骤降"', '"挂科数"',
        '"班级排名比例"', '"专业排名比例"', '"出勤率"',
        '"到馆次数"', '"图书馆活跃度"',
        '"消费规律性"', '"课程偏好"', '"岗位浏览数"',
        '"岗位收藏数"', '"证书数"', '"竞赛数"',
        '"项目数"', '"标签"', '"计算版本"',
    )
    # 读侧：中文列 AS 英文别名，保证返回的 dict 仍是既有英文键
    _FEATURE_SELECT = (
        '"学号" AS student_no, "学期" AS term, "绩点" AS gpa, '
        '"绩点趋势" AS gpa_trend, "是否骤降" AS extreme_decline, '
        '"挂科数" AS fail_count, "班级排名比例" AS class_rank_pct, '
        '"专业排名比例" AS major_rank_pct, "出勤率" AS attendance_rate, '
        '"到馆次数" AS library_visit_cnt, "图书馆活跃度" AS library_activity, '
        '"消费规律性" AS consumption_regularity, "课程偏好" AS course_pref, '
        '"岗位浏览数" AS job_view_cnt, "岗位收藏数" AS job_favorite_cnt, '
        '"证书数" AS cert_count, "竞赛数" AS contest_count, '
        '"项目数" AS project_cnt, "标签" AS tags, "计算版本" AS calc_version, '
        '"更新时间" AS updated_at'
    )

    @classmethod
    def _feature_values(cls, feature: dict[str, Any]) -> list[Any]:
        """把一条特征 dict 摊成与 _FEATURE_COLS 对齐的值列表（JSON 字段序列化）。"""
        out: list[Any] = []
        for c in cls._FEATURE_COLS:
            v = feature.get(c)
            if c in ("course_pref", "tags") and v is not None:
                out.append(json.dumps(v, ensure_ascii=False))
            else:
                out.append(v)
        return out

    def write_student_feature(self, feature: dict[str, Any]) -> int:
        """写入单条学生特征记录（upsert 语义）。"""
        placeholders = ", ".join(["?"] * len(self._FEATURE_COLS))
        sql = (
            f"INSERT OR REPLACE INTO {self._FEATURE_TABLE} "
            f"({', '.join(self._FEATURE_DB_COLS)}) "
            f"VALUES ({placeholders})"
        )
        with closing(self._connect()) as conn:
            conn.execute(sql, self._feature_values(feature))
        return 1

    def write_student_features(self, features: Sequence[dict[str, Any]]) -> int:
        """批量 upsert（多行 VALUES，一次连接、一次事务）。

        1 万人逐条写要 7 分钟，批量写几秒。DuckDB 的 executemany 对
        `INSERT OR REPLACE` 支持有限，这里直接拼多行 VALUES 交给一条语句，
        由 DuckDB 自己走批量路径。按 500 行一批，避免单条 SQL 过长。
        """
        if not features:
            return 0
        ncol = len(self._FEATURE_COLS)
        one_row = "(" + ", ".join(["?"] * ncol) + ")"
        prefix = (
            f"INSERT OR REPLACE INTO {self._FEATURE_TABLE} "
            f"({', '.join(self._FEATURE_DB_COLS)}) VALUES "
        )
        batch = 500
        written = 0
        with closing(self._connect()) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                for start in range(0, len(features), batch):
                    chunk = features[start:start + batch]
                    sql = prefix + ", ".join([one_row] * len(chunk))
                    params: list[Any] = []
                    for f in chunk:
                        params.extend(self._feature_values(f))
                    conn.execute(sql, params)
                    written += len(chunk)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return written

    # 读侧返回的键顺序，必须与 _FEATURE_SELECT 的别名顺序一一对应
    _FEATURE_READ_COLS = (
        "student_no", "term", "gpa", "gpa_trend", "extreme_decline", "fail_count",
        "class_rank_pct", "major_rank_pct", "attendance_rate",
        "library_visit_cnt", "library_activity",
        "consumption_regularity", "course_pref", "job_view_cnt",
        "job_favorite_cnt", "cert_count", "contest_count",
        "project_cnt", "tags", "calc_version", "updated_at",
    )

    @classmethod
    def _feature_row(cls, row: Sequence[Any]) -> dict[str, Any]:
        """一行查询结果 → 英文键 dict（JSON 字段反序列化）。"""
        result = dict(zip(cls._FEATURE_READ_COLS, row))
        for jf in ("course_pref", "tags"):
            v = result.get(jf)
            if isinstance(v, str) and v:
                try:
                    result[jf] = json.loads(v)
                except ValueError:
                    # 脏数据不阻断画像读取：按缺失处理，避免整条记录不可用
                    result[jf] = {} if jf == "course_pref" else []
        return result

    def read_student_feature(self, student_no: str, term: str) -> dict[str, Any] | None:
        """读取单条学生特征记录。"""
        sql = (
            f"SELECT {self._FEATURE_SELECT} "
            f"FROM {self._FEATURE_TABLE} WHERE \"学号\" = ? AND \"学期\" = ?"
        )
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute(sql, [student_no, term]).fetchone()
        return None if row is None else self._feature_row(row)

    def read_student_features(self, student_nos: Sequence[str], term: str
                              ) -> list[dict[str, Any]]:
        """批量读取多名学生的特征行：一次连接、一条 IN 查询。

        为什么要有批量版：read_features 原先逐人调用 read_student_feature，
        580 人的班级就是 580 次 duckdb.connect（每次约 10ms，合计约 5.8 秒），
        是班级职业差距接口 14 秒的主因。IN 查询一次取回，返回结构与逐条读取完全一致。
        """
        nos = [str(s) for s in student_nos if s]
        if not nos:
            return []
        placeholders = ", ".join(["?"] * len(nos))
        sql = (
            f"SELECT {self._FEATURE_SELECT} FROM {self._FEATURE_TABLE} "
            f"WHERE \"学期\" = ? AND \"学号\" IN ({placeholders})"
        )
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(sql, [term, *nos]).fetchall()
        return [self._feature_row(row) for row in rows]

    def write_recommend_log(self, log: dict[str, Any]) -> int:
        """写入单条推荐日志。"""
        cols = [
            "id", "student_no", "job_id", "content_score", "cf_score",
            "final_score", "hit_items", "gap_items", "advice",
            "engine_version",
        ]
        # 库中列名（中文），顺序与 cols 一一对应
        db_cols = [
            '"编号"', '"学号"', '"岗位编号"', '"内容得分"', '"协同得分"',
            '"最终得分"', '"命中项"', '"缺口项"', '"建议"',
            '"引擎版本"',
        ]
        placeholders = ", ".join(["?"] * len(cols))
        sql = (
            f'INSERT INTO "推荐日志" ({", ".join(db_cols)}) '
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

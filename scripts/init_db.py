# scripts/init_db.py
# 职责：读 .env、执行 MySQL 多份 schema 与 duckdb_schema.sql，幂等建表
# 依赖：pymysql / duckdb / app.config / pathlib
# 说明：脚本可脱离 FastAPI 服务独立运行

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pymysql

# 把项目根目录加入 sys.path，使 app.config 可导入
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings

# SQL 文件路径（按顺序执行；后续几份都依赖 mysql_schema 里的 学生 / 岗位 等主表）
_MYSQL_SQL_FILES = (
    _ROOT / "db" / "mysql_schema.sql",
    _ROOT / "db" / "career_tables.sql",
    _ROOT / "db" / "source_tables_v2.sql",
    _ROOT / "db" / "elective_tables.sql",
    _ROOT / "db" / "competition_tables.sql",
    _ROOT / "db" / "recruit_tables.sql",
    _ROOT / "db" / "interview_tables.sql",
    _ROOT / "db" / "question_bank.sql",
    _ROOT / "db" / "rag_tables.sql",
)
_DUCKDB_SQL = _ROOT / "db" / "duckdb_schema.sql"


def _split_statements(sql_text: str) -> list[str]:
    """把 SQL 文本按分号拆成独立语句（过滤空语句与纯注释行）。"""
    stmts: list[str] = []
    for raw in sql_text.split(";"):
        lines = [
            line.strip() for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if lines:
            stmts.append("\n".join(lines))
    return stmts


def init_mysql(settings) -> None:
    """执行 MySQL schema，逐表打印创建结果。"""
    print("=" * 60)
    print("MySQL 业务库初始化")
    print(f"  host={settings.mysql_host}:{settings.mysql_port} db={settings.mysql_db}")
    print("=" * 60)

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        for sql_path in _MYSQL_SQL_FILES:
            print(f"-- {sql_path.name}")
            sql_text = sql_path.read_text(encoding="utf-8")
            for stmt in _split_statements(sql_text):
                stripped = stmt.strip()
                if not stripped:
                    continue
                # 提取表名用于日志
                table_name = _extract_table_name(stripped)
                with conn.cursor() as cur:
                    cur.execute(stripped)
                if table_name:
                    print(f"  [OK] {table_name}")
                elif stripped.upper().startswith("CREATE DATABASE"):
                    print("  [OK] database qihang")
                elif stripped.upper().startswith("INSERT"):
                    print("  [OK] seed tenant: 重庆财经学院")
                elif stripped.upper().startswith("USE "):
                    print(f"  [OK] USE {settings.mysql_db}")
        print("MySQL 初始化完成。")
    finally:
        conn.close()


def _extract_table_name(stmt: str) -> str:
    """从 CREATE TABLE 语句中提取表名，提取失败返回空串。"""
    upper = stmt.upper()
    idx = upper.find("CREATE TABLE IF NOT EXISTS")
    if idx == -1:
        idx = upper.find("CREATE TABLE")
    if idx == -1:
        return ""
    # 跳过 CREATE TABLE [IF NOT EXISTS]
    rest = stmt[idx:]
    for prefix in ("CREATE TABLE IF NOT EXISTS", "CREATE TABLE"):
        if rest.upper().startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()
    # 表名可能带反引号
    if rest.startswith("`"):
        end = rest.find("`", 1)
        return rest[1:end] if end != -1 else rest[1:].split()[0]
    return rest.split("(")[0].strip().split()[0] if rest else ""


def init_duckdb(settings) -> None:
    """执行 DuckDB schema，逐表打印创建结果。"""
    print()
    print("=" * 60)
    print("DuckDB 分析库初始化")
    print(f"  path={settings.duckdb_path}")
    print("=" * 60)

    db_path = settings.duckdb_path_obj
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sql_text = _DUCKDB_SQL.read_text(encoding="utf-8")
    statements = _split_statements(sql_text)

    conn = duckdb.connect(str(db_path))
    try:
        for stmt in statements:
            stripped = stmt.strip()
            if not stripped:
                continue
            table_name = _extract_table_name(stripped)
            conn.execute(stripped)
            if table_name:
                print(f"  [OK] {table_name}")
        print("DuckDB 初始化完成。")
    finally:
        conn.close()


def main() -> None:
    """入口：先初始化 MySQL，再初始化 DuckDB。"""
    settings = get_settings()
    init_mysql(settings)
    init_duckdb(settings)
    print()
    print("全部建表完成。")


if __name__ == "__main__":
    main()

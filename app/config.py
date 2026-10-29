# app/config.py
# 职责：用 pydantic-settings 读取 .env，暴露 Settings 单例
# 依赖：pydantic-settings BaseSettings
# 说明：所有配置只从此处取，不在代码里硬编码

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 .env 读取的全局配置单例。"""

    # --- DeepSeek ---
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # --- iFlytek Spark（OpenAI 兼容接口）---
    spark_api_key: str = ""
    spark_base_url: str = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
    spark_model: str = "spark-x2.6"

    # --- LLM 提供方 ---
    # auto = 配了星火 Key 就优先星火，否则 DeepSeek；也可显式 spark / deepseek
    llm_provider: str = "auto"

    # --- MySQL ---
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "qihang"

    # --- DuckDB ---
    duckdb_path: str = "D:/qihang/data/analytics.duckdb"

    # --- App ---
    app_port: int = 8000
    jwt_secret: str = ""
    jwt_expire_minutes: int = 120

    # --- 智能体商业化 ---
    # 每用户每日问答配额（0 = 不限量）。按 audit_log 里 agent.chat 实数计数。
    agent_daily_limit: int = 0

    # --- 前端静态托管（P10-3）---
    # 空串 = 纯 API 不托管；填了路径且目录存在时才挂载 web\dist
    frontend_dist: str = "web/dist"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def duckdb_path_obj(self) -> Path:
        """返回 DuckDB 路径的 Path 对象。"""
        return Path(self.duckdb_path)

    @property
    def mysql_dsn(self) -> str:
        """返回 PyMySQL 连接所需的 dsn 片段（不暴露密码）。"""
        return f"mysql://{self.mysql_user}@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"

    @property
    def frontend_dist_obj(self) -> Path | None:
        """前端构建目录：配置为空或目录不存在时返回 None（不托管静态页）。"""
        raw = str(self.frontend_dist or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path if path.is_dir() else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回 Settings 单例（lru_cache 保证全局唯一）。"""
    return Settings()

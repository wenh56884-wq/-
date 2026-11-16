# app/logging_config.py
# 职责：初始化控制台/滚动文件日志，供 API、后台同步和异常处理统一使用。
# 依赖：Python 标准库 logging；日志目录由项目根路径确定。
# 输出：logs/qihang.log，单文件 10MB，保留 5 份。

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONFIGURED_ATTR = "_qihang_logging_configured"


def configure_logging() -> None:
    """幂等配置日志；测试多次创建 app 不会重复添加 handler。"""
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_ATTR, False):
        return

    level_name = str(os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = Path(__file__).resolve().parents[1] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "qihang.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    root.setLevel(level)
    setattr(root, _CONFIGURED_ATTR, True)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)

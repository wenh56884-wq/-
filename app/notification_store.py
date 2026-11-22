# app/notification_store.py
# 职责：Web Push 设备订阅与投递去重持久化。
# 边界：只存设备订阅和投递状态，不改已读水位、不生成通知正文、不接收前端身份。

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence

import pymysql

from app.config import Settings, get_settings


def endpoint_digest(endpoint: str) -> str:
    """把可能很长的 endpoint 映射为定长唯一键，避免 VARCHAR 索引长度限制。"""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _connect(settings: Settings | None = None):
    s = settings or get_settings()
    return pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _query(sql: str, params: Sequence[Any] = (), settings: Settings | None = None) -> list[dict[str, Any]]:
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _execute(sql: str, params: Sequence[Any] = (), settings: Settings | None = None) -> int:
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            return int(cur.execute(sql, params))
    finally:
        conn.close()


def ensure_tables(settings: Settings | None = None) -> None:
    """幂等建表；允许已部署环境通过脚本单独初始化，不在每次请求执行。"""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS `学生推送订阅` ("
                "  `编号` BIGINT AUTO_INCREMENT PRIMARY KEY,"
                "  `租户编号` INT NOT NULL,"
                "  `学号` VARCHAR(32) NOT NULL,"
                "  `端点` VARCHAR(1000) NOT NULL,"
                "  `端点摘要` CHAR(64) NOT NULL,"
                "  `订阅密钥` TEXT NOT NULL,"
                "  `浏览器标识` VARCHAR(300) DEFAULT '',"
                "  `创建时间` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  `更新时间` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
                "  UNIQUE KEY uk_push_endpoint (`端点摘要`),"
                "  KEY idx_push_student (`租户编号`, `学号`)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS `学生推送投递` ("
                "  `编号` BIGINT AUTO_INCREMENT PRIMARY KEY,"
                "  `租户编号` INT NOT NULL,"
                "  `学号` VARCHAR(32) NOT NULL,"
                "  `端点摘要` CHAR(64) NOT NULL,"
                "  `通知源键` VARCHAR(191) NOT NULL,"
                "  `通知类型` VARCHAR(32) NOT NULL,"
                "  `投递状态` VARCHAR(16) NOT NULL DEFAULT 'sent',"
                "  `错误码` VARCHAR(32) DEFAULT '',"
                "  `创建时间` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  UNIQUE KEY uk_push_delivery (`租户编号`, `学号`, `端点摘要`, `通知源键`),"
                "  KEY idx_push_delivery_time (`创建时间`)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
    finally:
        conn.close()


def save_subscription(
    tenant_id: int,
    student_no: str,
    endpoint: str,
    keys: Mapping[str, Any],
    user_agent: str,
    settings: Settings | None = None,
) -> str:
    """按当前 JWT 身份绑定设备；同一 endpoint 重绑时替换归属，避免跨用户误投。"""
    digest = endpoint_digest(endpoint)
    raw_keys = json.dumps(dict(keys), ensure_ascii=False, separators=(",", ":"))
    _execute(
        "INSERT INTO `学生推送订阅` "
        "(`租户编号`, `学号`, `端点`, `端点摘要`, `订阅密钥`, `浏览器标识`) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "`租户编号`=VALUES(`租户编号`), `学号`=VALUES(`学号`), "
        "`端点`=VALUES(`端点`), `订阅密钥`=VALUES(`订阅密钥`), "
        "`浏览器标识`=VALUES(`浏览器标识`)",
        (tenant_id, student_no, endpoint, digest, raw_keys, user_agent[:300]),
        settings,
    )
    return digest


def delete_subscription(
    tenant_id: int,
    student_no: str,
    endpoint: str,
    settings: Settings | None = None,
) -> int:
    """退订只删除当前学生、当前租户拥有的端点，不让请求删除别人的设备。"""
    return _execute(
        "DELETE FROM `学生推送订阅` "
        "WHERE `租户编号`=%s AND `学号`=%s AND `端点摘要`=%s",
        (tenant_id, student_no, endpoint_digest(endpoint)),
        settings,
    )


def subscription_exists(
    tenant_id: int,
    student_no: str,
    endpoint: str,
    settings: Settings | None = None,
) -> bool:
    rows = _query(
        "SELECT 1 AS ok FROM `学生推送订阅` "
        "WHERE `租户编号`=%s AND `学号`=%s AND `端点摘要`=%s LIMIT 1",
        (tenant_id, student_no, endpoint_digest(endpoint)),
        settings,
    )
    return bool(rows)


def list_subscriptions(
    tenant_id: int | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """发送器读取订阅；限制显式租户，不在请求路径暴露此函数。"""
    if tenant_id is None:
        rows = _query(
            "SELECT `租户编号` AS tenant_id, `学号` AS student_no, `端点` AS endpoint, "
            "`端点摘要` AS endpoint_digest, `订阅密钥` AS keys_json "
            "FROM `学生推送订阅`", (), settings)
    else:
        rows = _query(
            "SELECT `租户编号` AS tenant_id, `学号` AS student_no, `端点` AS endpoint, "
            "`端点摘要` AS endpoint_digest, `订阅密钥` AS keys_json "
            "FROM `学生推送订阅` WHERE `租户编号`=%s", (tenant_id,), settings)
    for row in rows:
        try:
            row["keys"] = json.loads(str(row.pop("keys_json") or "{}"))
        except json.JSONDecodeError:
            row["keys"] = {}
    return rows


def delivery_exists(
    tenant_id: int,
    student_no: str,
    endpoint_digest: str,
    source_key: str,
    settings: Settings | None = None,
) -> bool:
    rows = _query(
        "SELECT 1 AS ok FROM `学生推送投递` "
        "WHERE `租户编号`=%s AND `学号`=%s AND `端点摘要`=%s AND `通知源键`=%s LIMIT 1",
        (tenant_id, student_no, endpoint_digest, source_key),
        settings,
    )
    return bool(rows)


def record_delivery(
    tenant_id: int,
    student_no: str,
    endpoint_digest: str,
    source_key: str,
    notice_type: str,
    status: str = "sent",
    error_code: str = "",
    settings: Settings | None = None,
) -> None:
    """记录一次已尝试投递；唯一键保证同一通知不因定时器重复打扰同一设备。"""
    _execute(
        "INSERT IGNORE INTO `学生推送投递` "
        "(`租户编号`, `学号`, `端点摘要`, `通知源键`, `通知类型`, `投递状态`, `错误码`) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, student_no, endpoint_digest, source_key,
         notice_type[:32], status[:16], error_code[:32]),
        settings,
    )


def mark_subscription_invalid(
    endpoint_digest: str,
    settings: Settings | None = None,
) -> None:
    """Push service 返回 404/410 时清理失效端点及其投递历史。"""
    _execute("DELETE FROM `学生推送订阅` WHERE `端点摘要`=%s",
             (endpoint_digest,), settings)
    _execute("DELETE FROM `学生推送投递` WHERE `端点摘要`=%s",
             (endpoint_digest,), settings)

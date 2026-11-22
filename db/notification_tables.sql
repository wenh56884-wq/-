-- db/notification_tables.sql
-- 职责：学生浏览器 Web Push 设备订阅与投递去重（不改既有通知水位表）。
-- 说明：身份只由 JWT 注入，学号/租户编号在服务端查库后写入；端点全局唯一。

CREATE TABLE IF NOT EXISTS `学生推送订阅` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL,
  `学号`        VARCHAR(32)  NOT NULL,
  `端点`        VARCHAR(1000) NOT NULL COMMENT 'Push service endpoint',
  `端点摘要`    CHAR(64)     NOT NULL COMMENT '端点 SHA-256，供唯一键与检索',
  `订阅密钥`    TEXT         NOT NULL COMMENT 'PushSubscription keys JSON',
  `浏览器标识`  VARCHAR(300) DEFAULT '' COMMENT 'User-Agent 摘要，仅用于设备管理',
  `创建时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  `更新时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_push_endpoint (`端点摘要`),
  KEY idx_push_student (`租户编号`, `学号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生浏览器推送设备订阅';

CREATE TABLE IF NOT EXISTS `学生推送投递` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL,
  `学号`        VARCHAR(32)  NOT NULL,
  `端点摘要`    CHAR(64)     NOT NULL,
  `通知源键`    VARCHAR(191) NOT NULL COMMENT '通知类型 + 稳定编号，按设备去重',
  `通知类型`    VARCHAR(32)  NOT NULL COMMENT 'competition / cert / exam',
  `投递状态`    VARCHAR(16)  NOT NULL DEFAULT 'sent' COMMENT 'sent / invalid / failed',
  `错误码`      VARCHAR(32)  DEFAULT '' COMMENT 'HTTP 状态或失败分类，不存推送正文',
  `创建时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_push_delivery (`租户编号`, `学号`, `端点摘要`, `通知源键`),
  KEY idx_push_delivery_time (`创建时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生浏览器推送投递去重与状态';

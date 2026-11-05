-- db/pet_memory.sql
-- AI 宠物陪伴：运行时状态 + 对话记忆的持久化（跨会话、按身份隔离）
-- 说明：时间列存 Unix 时间戳（DOUBLE，秒），与 engine/pet.py 的 time.time() 直接对应，
--       避免与 DATETIME/TIMESTAMP 来回转换的精度损失。
-- 铁律3：按身份编号隔离，租户编号冗余存储用于审计与隔离校验。

CREATE TABLE IF NOT EXISTS `宠物运行时` (
  `身份编号`        BIGINT       NOT NULL COMMENT '学生/教师内部主键（多租户隔离键）',
  `租户编号`        BIGINT       NOT NULL DEFAULT 1,
  `心情`            VARCHAR(20)  NOT NULL DEFAULT 'idle',
  `强度`            DOUBLE       NOT NULL DEFAULT 0.5,
  `上次互动时间`    DOUBLE       NOT NULL DEFAULT 0,
  `专注模式`        TINYINT(1)   NOT NULL DEFAULT 0,
  `上次说话时间`    DOUBLE       NOT NULL DEFAULT 0,
  `主动间隔秒`      INT          NOT NULL DEFAULT 480,
  `人格名字`        VARCHAR(40)  NOT NULL DEFAULT '小航',
  `更新时间`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`身份编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 宠物运行时状态（按身份隔离）';

CREATE TABLE IF NOT EXISTS `宠物记忆` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `身份编号`    BIGINT       NOT NULL,
  `租户编号`    BIGINT       NOT NULL DEFAULT 1,
  `角色`        ENUM('user','pet') NOT NULL,
  `文本`        TEXT         NOT NULL,
  `创建时间`    DOUBLE       NOT NULL,
  KEY idx_pet_memory_owner_time (`身份编号`, `创建时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 宠物对话记忆（短期窗口裁剪）';

CREATE TABLE IF NOT EXISTS `宠物人格` (
  `身份编号`    BIGINT       NOT NULL COMMENT '学生/教师内部主键（多租户隔离键）',
  `租户编号`    BIGINT       NOT NULL DEFAULT 1,
  `名字`        VARCHAR(40)  NOT NULL DEFAULT '小航',
  `物种`        VARCHAR(40)  NOT NULL DEFAULT '启航小助手',
  `语气`        VARCHAR(80)  NOT NULL DEFAULT '活泼、鼓励、像学长一样陪伴',
  `问候语`      VARCHAR(200) NOT NULL DEFAULT '嗨，我是小航，今天想聊点什么呀？',
  `鼓励池JSON`  JSON         NULL         COMMENT '鼓励语池（JSON 数组，最多 10 条）',
  `更新时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`身份编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 宠物人格配置（按身份隔离）';

CREATE TABLE IF NOT EXISTS `宠物长期记忆` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `身份编号`    BIGINT       NOT NULL,
  `租户编号`    BIGINT       NOT NULL DEFAULT 1,
  `内容`        TEXT         NOT NULL COMMENT '用户长期事实（目标/偏好/约束），不含数值',
  `类型`        VARCHAR(20)  NOT NULL DEFAULT 'fact' COMMENT 'goal/preference/fact/event',
  `重要度`      TINYINT      NOT NULL DEFAULT 3 COMMENT '1-5，越大越优先召回/保留',
  `向量`        JSON         NULL COMMENT '内容稀疏向量（agent_memory.embed 格式，去重与编辑后重算）',
  `创建时间`    DOUBLE       NOT NULL,
  KEY idx_pet_longmem_owner (`身份编号`, `创建时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 宠物长期记忆（跨会话，区别于短期对话）';

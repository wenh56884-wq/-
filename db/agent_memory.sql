-- db/agent_memory.sql
-- 智能体长期记忆（跨会话、按租户 + 角色 + 主体隔离）
-- 说明：向量列存稀疏 hashing 向量（{"i":[...],"v":[...]}）。当前 LLM 只有 chat 接口、
--       没有 embedding API，因此用 char n-gram hashing 做确定性向量索引；
--       将来接入真 embedding 时只替换 engine/agent_memory.py 的 embed()。

CREATE TABLE IF NOT EXISTS `智能体记忆` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL DEFAULT 1,
  `角色`        ENUM('teacher','student') NOT NULL,
  `主体编号`    BIGINT       NOT NULL COMMENT '学生编号 / 教师编号（内部主键）',
  `记忆类型`    VARCHAR(20)  NOT NULL DEFAULT 'fact'
                COMMENT 'fact=事实 preference=偏好 goal=目标 constraint=约束',
  `内容`        TEXT         NOT NULL COMMENT '记忆正文（用户可读，禁止写分数/排名等易变数值）',
  `向量`        JSON         NULL     COMMENT '{"i":[维度下标],"v":[权重]}，hashing 向量',
  `来源会话`    BIGINT       NULL     COMMENT '来自哪个对话会话',
  `重要度`      TINYINT      NOT NULL DEFAULT 3 COMMENT '1-5，越大越优先召回',
  `使用次数`    INT          NOT NULL DEFAULT 0,
  `创建时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  `最近使用时间` TIMESTAMP   NULL     DEFAULT NULL,
  `状态`        ENUM('active','archived') NOT NULL DEFAULT 'active',
  KEY idx_mem_owner (`租户编号`, `角色`, `主体编号`, `状态`),
  KEY idx_mem_type (`记忆类型`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体长期记忆（跨会话）';

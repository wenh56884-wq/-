-- ================================================================
-- 面试题库 + RAG 检索（阶段K）
-- 目的：模拟面试的问题不再由模型凭空生成，而是从「有出处的题库」里检索。
-- 设计要点：
--   1. 每道题必须有 source_url：没有出处就不入库（防幻觉的第一道闸）。
--   2. 题目原文照抄，不改写；模型只能在面试时做语气润色，且不得改考点。
--   3. 行业族（family）是检索的硬过滤条件：岗位行业 → 行业族 → 取题。
--      通用题 family='general'，对所有行业兜底。
--   4. 考点（keywords）由题库自带，评分时优先用它，
--      而不是用 QUESTION_TYPES 里的通用关键词（否则专业题会被误判）。
-- ================================================================

-- 1. 面试题库 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `面试题库` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `题目编号`    VARCHAR(40)  NOT NULL COMMENT '语料里的稳定业务键，如 it-major-003',
  `行业族`      VARCHAR(40)  NOT NULL DEFAULT 'general'
                COMMENT 'general=通用；其余见 engine/question_bank.py::INDUSTRY_FAMILIES',
  `岗位族`      VARCHAR(60)  NULL COMMENT '细分岗位族，如 后端开发/柜员/成本会计',
  `题型`        VARCHAR(20)  NOT NULL
                COMMENT 'motivation/major/project/scenario/stress/counter',
  `题目`        VARCHAR(500) NOT NULL COMMENT '题库原文，不改写',
  `考点`        JSON         NULL COMMENT '评分关键词，如 ["权责发生制","收付实现制"]',
  `参考答案要点` TEXT        NULL COMMENT '题库原文的参考答案/思路，供点评引用',
  `难度`        TINYINT      NOT NULL DEFAULT 1 COMMENT '1~3',
  `来源名称`    VARCHAR(120) NOT NULL COMMENT '如 应届毕业生网 / 刷刷题 / JobsAICopilot',
  `来源链接`    VARCHAR(500) NOT NULL COMMENT '必填：无出处不入库',
  `采集时间`    DATE         NOT NULL,
  `校验状态`    ENUM('verified','unverified','retired') NOT NULL DEFAULT 'verified'
                COMMENT 'verified=题面与源文一致 verified 后方可被检索命中',
  `启用`        TINYINT(1)   NOT NULL DEFAULT 1,
  `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_qb_code (`题目编号`),
  KEY idx_qb_pick (`启用`, `校验状态`, `行业族`, `题型`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='面试题库（每条可回溯到来源链接）';

-- 2. 题库导入日志 -------------------------------------------------
CREATE TABLE IF NOT EXISTS `面试题库导入日志` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `语料版本`    VARCHAR(20)  NOT NULL COMMENT '如 qb-v1',
  `总条数`      INT          NOT NULL DEFAULT 0,
  `新增`        INT          NOT NULL DEFAULT 0,
  `更新`        INT          NOT NULL DEFAULT 0,
  `跳过`        INT          NOT NULL DEFAULT 0,
  `被拒`        INT          NOT NULL DEFAULT 0 COMMENT '缺来源/字段不合法被拒的条数',
  `详情`        JSON         NULL COMMENT '{"rejected":[{"id":"","reason":""}]}',
  `操作人`      VARCHAR(60)  NULL,
  `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_qbil_time (`创建时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='题库导入日志';

-- 工作流审批表（人工审核留痕）---------------------------------
-- 场景：教师把「批量导出预警名单」「全员重算画像」这类动作定义成工作流后，
--       不希望谁点一下就跑，需要有人点头才能执行。
-- 设计：**一次运行只审一次**（uk_approval_run 唯一键），审批通过后才真正执行步骤。
--       执行用的是「提交者」的身份，不是审批人的——否则学生提交的「我的求职体检」
--       会以教师身份跑，my_warning 这类本人工具就会取到错误的人。
CREATE TABLE IF NOT EXISTS `工作流审批` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `运行编号`    BIGINT       NOT NULL,
  `租户编号`    INT          NOT NULL,
  `审批人角色`  VARCHAR(20)  NOT NULL,
  `审批人编号`  BIGINT       NULL,
  `动作`        ENUM('approve','reject') NOT NULL,
  `意见`        VARCHAR(500) NULL,
  `审批时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uk_approval_run` (`运行编号`),
  KEY `idx_approval_tenant` (`租户编号`, `审批时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工作流审批记录（一次运行只审一次）';

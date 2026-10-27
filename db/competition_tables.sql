-- db/competition_tables.sql
-- 竞赛库：数据全部来自重庆财经学院教务处官网（http://www.cfec.edu.cn），
-- 每条记录保留官方来源标题 + 原文链接 + 发布日期，可逐条点开核对。
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹。
--
-- 竞赛        ：学校《学科竞赛计划项目》名单（2026-2027 学年度，共 116 项）
-- 竞赛通知    ：教务处「学科竞赛」栏目最新发布的参赛通知（脚本抓取，可重复运行）

CREATE TABLE IF NOT EXISTS `竞赛` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `竞赛名称`  VARCHAR(200) NOT NULL COMMENT '竞赛名称（官方名单原文）',
  `类别`      VARCHAR(8)   NOT NULL COMMENT '学校认定类别：A / B / C / D',
  `组织单位`  VARCHAR(64)  NOT NULL COMMENT '组织单位（官方名单原文）',
  `去向`      VARCHAR(16)  NOT NULL COMMENT '去向：考公 / 就业 / 通用 / 文体',
  `标签`      TEXT         NOT NULL COMMENT '关联方向或能力标签 JSON 数组',
  `奖励方案`  TEXT         COMMENT '官方奖励方案原文',
  `来源标题`  VARCHAR(200) NOT NULL COMMENT '来源通知标题',
  `来源链接`  VARCHAR(300) NOT NULL COMMENT '来源通知链接（可点开核对）',
  `发布日期`  VARCHAR(16)  NOT NULL COMMENT '官方发布日期',
  `创建时间`  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_competition_name (`竞赛名称`),
  KEY idx_competition_track (`去向`),
  KEY idx_competition_category (`类别`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学科竞赛计划项目（官方名单）';

CREATE TABLE IF NOT EXISTS `竞赛通知` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `标题`      VARCHAR(300) NOT NULL COMMENT '通知标题（官方原文）',
  `发布日期`  VARCHAR(16)  COMMENT '发布日期（官方原文）',
  `链接`      VARCHAR(300) COMMENT '通知链接，抓不到时回落栏目页',
  `来源`      VARCHAR(64)  DEFAULT 'cfec-jwc' COMMENT '来源站点标识',
  `抓取时间`  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_notice_title_date (`标题`, `发布日期`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='教务处学科竞赛栏目最新通知';

-- 学生「已读到哪里」：未读 = 编号 大于水位的通知。
-- 用自增 编号 而不是时间戳：DATETIME 只有秒级精度，同一秒内发布的新通知会被漏推。
-- 也不给每人复制一份通知，只记一个水位点，学生再多都不会写爆。
CREATE TABLE IF NOT EXISTS `学生通知已读` (
  `编号`          BIGINT AUTO_INCREMENT PRIMARY KEY,
  `学号`          VARCHAR(32) NOT NULL COMMENT '学号（本租户内唯一）',
  `租户编号`      INT         NOT NULL DEFAULT 1,
  `最后已读时间`  DATETIME    NULL     COMMENT '最后一次点开的时间（仅展示用）',
  `已读通知编号`  BIGINT      NOT NULL DEFAULT 0 COMMENT '已读到的通知编号（判未读用）',
  `更新时间`      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_student_read (`租户编号`, `学号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生竞赛通知已读水位';

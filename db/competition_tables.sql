-- db/competition_tables.sql
-- 竞赛库：数据全部来自重庆财经学院教务处官网（http://www.cfec.edu.cn），
-- 每条记录保留官方来源标题 + 原文链接 + 发布日期，可逐条点开核对。
--
-- competition        ：学校《学科竞赛计划项目》名单（2026-2027 学年度，共 116 项）
-- competition_notice ：教务处「学科竞赛」栏目最新发布的参赛通知（脚本抓取，可重复运行）

CREATE TABLE IF NOT EXISTS competition (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  name         VARCHAR(200) NOT NULL COMMENT '竞赛名称（官方名单原文）',
  category     VARCHAR(8)   NOT NULL COMMENT '学校认定类别：A / B / C / D',
  org_unit     VARCHAR(64)  NOT NULL COMMENT '组织单位（官方名单原文）',
  track        VARCHAR(16)  NOT NULL COMMENT '去向：考公 / 就业 / 通用 / 文体',
  tags_json    TEXT         NOT NULL COMMENT '关联方向或能力标签 JSON 数组',
  reward       TEXT         COMMENT '官方奖励方案原文',
  source_title VARCHAR(200) NOT NULL COMMENT '来源通知标题',
  source_url   VARCHAR(300) NOT NULL COMMENT '来源通知链接（可点开核对）',
  published_at VARCHAR(16)  NOT NULL COMMENT '官方发布日期',
  created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_competition_name (name),
  KEY idx_competition_track (track),
  KEY idx_competition_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学科竞赛计划项目（官方名单）';

CREATE TABLE IF NOT EXISTS competition_notice (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  title        VARCHAR(300) NOT NULL COMMENT '通知标题（官方原文）',
  published_at VARCHAR(16)  COMMENT '发布日期（官方原文）',
  url          VARCHAR(300) COMMENT '通知链接，抓不到时回落栏目页',
  source       VARCHAR(64)  DEFAULT 'cfec-jwc' COMMENT '来源站点标识',
  fetched_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_notice_title_date (title, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='教务处学科竞赛栏目最新通知';

-- 学生「已读到哪里」：未读 = id 大于水位的通知。
-- 用自增 id 而不是时间戳：DATETIME 只有秒级精度，同一秒内发布的新通知会被漏推。
-- 也不给每人复制一份通知，只记一个水位点，学生再多都不会写爆。
CREATE TABLE IF NOT EXISTS student_notice_read (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_no      VARCHAR(32) NOT NULL COMMENT '学号（本租户内唯一）',
  tenant_id       INT         NOT NULL DEFAULT 1,
  last_read_at    DATETIME    NULL     COMMENT '最后一次点开的时间（仅展示用）',
  last_notice_id  BIGINT      NOT NULL DEFAULT 0 COMMENT '已读到的通知 id（判未读用）',
  updated_at      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_student_read (tenant_id, student_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生竞赛通知已读水位';

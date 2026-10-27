-- db/recruit_tables.sql
-- 招聘 / 招考数据（周更入库）
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹。
--
-- 设计原则（与 competition_tables.sql 一致）：
--   1. 每条记录都带**官方来源 + 原文链接 + 发布日期**，可逐条点开核对，不做推断补全；
--   2. 用 (来源, 来源键) 唯一键做幂等：同一岗位抓一百次也只入库一次；
--   3. 抓不到就是抓不到 —— 不写编造数据，blank 字段一律留 NULL（缺失不冒充）；
--   4. 周更只做「增量 upsert + 过期下线」，不做全表 TRUNCATE，历史可追溯。

-- ---------------------------------------------------------------
-- 招聘岗位（企业类，面向「就业」方向）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `招聘岗位` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL DEFAULT 1,
  `来源`        VARCHAR(40)  NOT NULL COMMENT '来源站点标识，如 cqhrss / cie-job',
  `来源键`      CHAR(32)     NOT NULL COMMENT '来源内唯一键（url/title 的 hash），用于幂等',
  `岗位名称`    VARCHAR(200) NOT NULL COMMENT '岗位名称（原文）',
  `招聘单位`    VARCHAR(200) NOT NULL COMMENT '招聘单位（原文）',
  `行业`        VARCHAR(80)  NULL     COMMENT '行业',
  `城市`        VARCHAR(60)  NULL     COMMENT '工作城市',
  `区县`        VARCHAR(60)  NULL     COMMENT '区县',
  `最低薪资`    DECIMAL(8,2) NULL     COMMENT '月薪下限（元）',
  `最高薪资`    DECIMAL(8,2) NULL     COMMENT '月薪上限（元）',
  `学历要求`    VARCHAR(20)  NULL     COMMENT '学历要求原文，如 本科 / 硕士 / 不限',
  `经验要求`    VARCHAR(30)  NULL     COMMENT '经验要求原文，如 应届 / 1-3年',
  `招聘人数`    INT          NULL     COMMENT '招聘人数',
  `技能标签`    JSON         NULL     COMMENT '技能标签（原文抽取，无则 NULL）',
  `职位描述`    TEXT         NULL     COMMENT '职位描述原文',
  `投递链接`    VARCHAR(500) NULL     COMMENT '投递/原文链接',
  `发布日期`    DATE         NULL     COMMENT '发布日期',
  `截止日期`    DATE         NULL     COMMENT '报名截止日期（有则写入）',
  `状态`        ENUM('open','closed','unknown') NOT NULL DEFAULT 'unknown'
                COMMENT 'open=在招 closed=已截止 unknown=未知（不猜）',
  `首次发现时间` TIMESTAMP   DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时间',
  `最近发现时间` TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                COMMENT '最近一次仍被抓到的时间（判断是否下架）',
  UNIQUE KEY uk_recruit_job (`租户编号`, `来源`, `来源键`),
  KEY idx_recruit_job_status (`状态`),
  KEY idx_recruit_job_city (`城市`),
  KEY idx_recruit_job_published (`发布日期`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招聘岗位（周更增量）';

-- ---------------------------------------------------------------
-- 招考公告（考公 / 考编 / 考研 三类，面向三类升学就业方向）
-- ---------------------------------------------------------------
-- 考试类型 三选一：civil=考公（公务员/选调/遴选）
--                 institution=考编（事业单位/教师编/医疗编）
--                 postgraduate=考研（硕士招生/推免/调剂）
CREATE TABLE IF NOT EXISTS `招考公告` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL DEFAULT 1,
  `考试类型`    ENUM('civil','institution','postgraduate') NOT NULL COMMENT '考试类型',
  `来源`        VARCHAR(40)  NOT NULL COMMENT '来源站点标识',
  `来源键`      CHAR(32)     NOT NULL COMMENT '来源内唯一键（幂等用）',
  `标题`        VARCHAR(300) NOT NULL COMMENT '公告标题（原文）',
  `招录单位`    VARCHAR(200) NULL     COMMENT '招录单位 / 招生院校',
  `地区`        VARCHAR(60)  NULL     COMMENT '地区，如 重庆 / 全国',
  -- 以下要求字段全部来自公告正文，抓不到就 NULL，绝不填「不限」冒充
  `学历要求`    VARCHAR(200)  NULL     COMMENT '学历要求原文',
  `学位要求`    VARCHAR(200)  NULL     COMMENT '学位要求原文',
  `专业要求`    TEXT         NULL     COMMENT '专业要求原文',
  `年龄要求`    VARCHAR(200)  NULL     COMMENT '年龄要求原文',
  `政治面貌要求` VARCHAR(200) NULL     COMMENT '政治面貌要求原文',
  `经历要求`    VARCHAR(200)  NULL     COMMENT '基层工作经历/年限要求原文',
  `证书要求`    VARCHAR(200) NULL     COMMENT '资格证书等其他要求原文',
  `其他要求`    TEXT         NULL     COMMENT '其他条件原文（户籍、四六级等）',
  `招录人数`    INT          NULL     COMMENT '招录人数',
  -- 时间线
  `发布日期`    DATE         NULL     COMMENT '公告发布日期',
  `报名开始`    DATE         NULL     COMMENT '报名开始',
  `报名截止`    DATE         NULL     COMMENT '报名截止',
  `考试日期`    DATE         NULL     COMMENT '笔试日期',
  -- 溯源
  `原文链接`    VARCHAR(500) NULL     COMMENT '公告原文链接（可点开核对）',
  `正文原文`    MEDIUMTEXT   NULL     COMMENT '公告正文原文（截断 2 万字），具体岗位表在附件时以此为准',
  `状态`        ENUM('open','closed','unknown') NOT NULL DEFAULT 'unknown',
  `首次发现时间` TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
  `最近发现时间` TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_exam_notice (`租户编号`, `来源`, `来源键`),
  KEY idx_exam_type (`考试类型`),
  KEY idx_exam_region (`地区`),
  KEY idx_exam_status (`状态`),
  KEY idx_exam_publish (`发布日期`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招考公告（考公/考编/考研，周更增量）';

-- ---------------------------------------------------------------
-- 周更运行日志（每次抓取一行，便于看「这周抓到多少、有没有失败」）
-- 也用于教师端/管理端展示数据新鲜度：最后一次成功更新时间
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `抓取运行日志` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `运行时间`  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  `触发方式`  VARCHAR(20)  NOT NULL DEFAULT 'schedule' COMMENT 'schedule / manual',
  `目标`      VARCHAR(20)  NOT NULL COMMENT 'job / civil / institution / postgraduate',
  `来源`      VARCHAR(40)  NOT NULL,
  `抓取数`    INT          NOT NULL DEFAULT 0 COMMENT '本次抓到条数',
  `新增数`    INT          NOT NULL DEFAULT 0 COMMENT '新增条数',
  `更新数`    INT          NOT NULL DEFAULT 0 COMMENT '更新条数',
  `关闭数`    INT          NOT NULL DEFAULT 0 COMMENT '本次标记为已截止的条数',
  `是否成功`  TINYINT(1)   NOT NULL DEFAULT 1,
  `错误`      VARCHAR(500) NULL,
  KEY idx_sync_run_at (`运行时间`),
  KEY idx_sync_target (`目标`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='周更抓取运行日志';

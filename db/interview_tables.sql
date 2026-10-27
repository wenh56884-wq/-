-- ================================================================
-- 模拟面试官模块建表（阶段J·P0）
-- 简历三张结构化表 + 面试会话 + 面试问答
-- 设计要点：
--   1. 简历以「版本」为单位：每次上传/自填生成一条 简历 主记录，
--      三类经历挂在其下；激活版唯一（其余 retained）。
--   2. 面试问答.引用原文 = 防虚构证据：点评里出现的「引文」必须能在
--      简历原文或学生回答里逐字找到（engine/interview.py::verify_comment）。
--   3. 所有评分由引擎先算好（引擎定数），模型只负责组织语言。
-- ================================================================

-- 1. 简历主表 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `简历` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL DEFAULT 1,
  `学生编号`    BIGINT       NOT NULL,
  `版本号`      INT          NOT NULL DEFAULT 1 COMMENT '同一学生递增',
  `来源`        ENUM('upload','questionnaire') NOT NULL
                COMMENT 'upload=上传解析 questionnaire=问卷自填（数据接口拿不到时的降级路径）',
  `来源文件名`  VARCHAR(200) NULL COMMENT '上传时的原始文件名',
  `简历原文`    MEDIUMTEXT   NULL COMMENT '上传解析出的全文（防虚构回查用）',
  `自我评价`    TEXT         NULL COMMENT '自填或原文提取',
  `意向方向`    VARCHAR(60)  NULL COMMENT '求职方向，如 后端开发 / 数据分析',
  `状态`        ENUM('active','retained') NOT NULL DEFAULT 'active'
                COMMENT 'active=当前使用 retained=历史版本（只增不删）',
  `解析版本`    VARCHAR(20)  NOT NULL DEFAULT 'resume-parse-v1',
  `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `更新时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_resume (`租户编号`, `学生编号`, `版本号`),
  KEY idx_resume_student (`租户编号`, `学生编号`, `状态`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='简历主表（版本化）';

-- 2. 简历教育经历 -------------------------------------------------
CREATE TABLE IF NOT EXISTS `简历教育经历` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `简历编号`    BIGINT       NOT NULL,
  `学校`        VARCHAR(120) NOT NULL,
  `专业`        VARCHAR(120) NULL,
  `学历`        VARCHAR(20)  NULL COMMENT '本科/硕士/大专…',
  `起止时间`    VARCHAR(60)  NULL COMMENT '原文照抄，如 2023.09-2027.06',
  `成绩排名`    VARCHAR(60)  NULL COMMENT '原文照抄，如 前10%',
  `主修课程`    JSON         NULL COMMENT '主修课程列表，如 ["数据结构","数据库"]',
  `排序号`      INT          NOT NULL DEFAULT 0,
  KEY idx_reedu ( `简历编号` )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='简历·教育经历';

-- 3. 简历技能证书 -------------------------------------------------
CREATE TABLE IF NOT EXISTS `简历技能证书` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `简历编号`    BIGINT       NOT NULL,
  `类型`        ENUM('skill','cert','language') NOT NULL DEFAULT 'skill'
                COMMENT 'skill=技能 cert=证书 language=语言能力',
  `名称`        VARCHAR(120) NOT NULL,
  `等级分数`    VARCHAR(60)  NULL COMMENT '如 CET-6 568 / 熟练 / 中级',
  `获得时间`    VARCHAR(30)  NULL,
  `排序号`      INT          NOT NULL DEFAULT 0,
  KEY idx_reskill ( `简历编号` )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='简历·技能与证书';

-- 4. 简历实践经历 -------------------------------------------------
CREATE TABLE IF NOT EXISTS `简历实践经历` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `简历编号`    BIGINT       NOT NULL,
  `类型`        ENUM('intern','project','contest','activity') NOT NULL DEFAULT 'project'
                COMMENT 'intern=实习 project=项目 contest=竞赛 activity=社团/志愿',
  `名称`        VARCHAR(200) NOT NULL,
  `角色`        VARCHAR(80)  NULL,
  `起止时间`    VARCHAR(60)  NULL,
  `描述`        TEXT         NULL COMMENT '经历描述原文（防虚构回查用）',
  `成果`        TEXT         NULL,
  `排序号`      INT          NOT NULL DEFAULT 0,
  KEY idx_reexp ( `简历编号` )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='简历·实践经历';

-- 5. 面试会话 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `面试会话` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT          NOT NULL DEFAULT 1,
  `学生编号`    BIGINT       NOT NULL,
  `简历编号`    BIGINT       NOT NULL,
  `岗位编号`    BIGINT       NULL COMMENT '招聘岗位.编号（练习可空=通用面试）',
  `岗位名称`    VARCHAR(200) NULL COMMENT '快照，防岗位后续变动',
  `岗位要求快照` JSON        NULL COMMENT '技能标签/学历等快照',
  `状态`        ENUM('ongoing','finished','abandoned') NOT NULL DEFAULT 'ongoing',
  `提纲`        JSON         NULL COMMENT '[{round,type,question,rubric}] 引擎生成',
  `当前轮次`    INT          NOT NULL DEFAULT 0,
  `最大轮次`    INT          NOT NULL DEFAULT 6 COMMENT '引擎上限，防无限追问',
  `总分`        DECIMAL(5,2) NULL COMMENT '引擎按维度加权算出，模型不参与计算',
  `报告`        MEDIUMTEXT   NULL COMMENT '面试报告（模型组织语言，数字来自引擎）',
  `差距清单`    JSON         NULL COMMENT '[{dimension,gap,action}] 引擎算出',
  `引擎版本`    VARCHAR(20)  NOT NULL DEFAULT 'interview-v1',
  `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `完成时间`    DATETIME     NULL,
  KEY idx_ivs (`租户编号`, `学生编号`, `状态`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模拟面试会话';

-- 6. 面试问答 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `面试问答` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `会话编号`    BIGINT       NOT NULL,
  `轮次`        INT          NOT NULL,
  `问题类型`    VARCHAR(20)  NOT NULL COMMENT 'motivation/major/project/scenario/stress/counter',
  `问题`        TEXT         NOT NULL,
  `学生回答`    MEDIUMTEXT   NULL COMMENT 'NULL=学生未答（跳过）',
  `点评`        TEXT         NULL COMMENT '模型点评（必须含「引文」）',
  `评分`        DECIMAL(5,2) NULL COMMENT '0-100，引擎按证据加权，模型不参与计算',
  `引用原文`    JSON         NULL COMMENT '点评引用的片段清单（每条都校验过存在于原文）',
  `点评版本`    VARCHAR(20)  NULL COMMENT 'comment-v1=模型 / comment-fallback-v1=模板降级',
  `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ivqa (`会话编号`, `轮次`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模拟面试问答（防虚构证据留痕）';

-- ============================================================
-- 启航 MySQL 8.0.21 业务库 schema（库名 qihang, utf8mb4）
-- 全中文命名：表名与字段名一律使用中文，标识符用反引号包裹。
--   兼容约定：查询侧统一用 `中文字段` AS 英文别名 的形式，
--   使 Python 取值、接口契约、前端字段保持既有英文键不变。
-- 所有数值字段禁止 FLOAT/DOUBLE，分数用 DECIMAL(5,2)，比例用 DECIMAL(5,4)
-- 幂等：全部 CREATE TABLE IF NOT EXISTS
-- ============================================================

CREATE DATABASE IF NOT EXISTS qihang
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE qihang;

-- -----------------------------------------------------------
-- 1. 租户
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `租户` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `名称`      VARCHAR(120) NOT NULL,
    `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='租户';

-- 种子数据（幂等）
INSERT INTO `租户` (`编号`, `名称`)
SELECT 1, '重庆财经学院'
    FROM DUAL
    WHERE NOT EXISTS (SELECT 1 FROM `租户` WHERE `编号` = 1);

-- -----------------------------------------------------------
-- 2. 教师
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `教师` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `姓名`      VARCHAR(60)  NOT NULL,
    `工号`      VARCHAR(40)  NOT NULL,
    `角色`      VARCHAR(20)  NOT NULL DEFAULT 'teacher',
    `口令摘要`  VARCHAR(255) NOT NULL,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_employee_no (`工号`),
    KEY idx_teacher_tenant (`租户编号`),
    CONSTRAINT fk_teacher_tenant FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='教师';

-- -----------------------------------------------------------
-- 2.1 教师任教班级（计划书“仅可访问负责班级”）
--     未配置任何行的教师回退为本租户全部班级，兼容旧演示账号；
--     一旦配置，工具层只允许访问这些班级。
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `教师任教班级` (
    `编号`      BIGINT      NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT      NOT NULL,
    `教师编号`  BIGINT      NOT NULL,
    `班级`      VARCHAR(40) NOT NULL,
    `创建时间`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_teacher_class (`教师编号`, `班级`),
    KEY idx_teacher_class_tenant (`租户编号`, `教师编号`),
    CONSTRAINT fk_tc_teacher FOREIGN KEY (`教师编号`) REFERENCES `教师`(`编号`) ON DELETE CASCADE,
    CONSTRAINT fk_tc_tenant  FOREIGN KEY (`租户编号`)  REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='教师任教班级绑定（空 = 回退租户范围）';

-- -----------------------------------------------------------
-- 3. 学生
--    学院 / 专业 取值必须来自 etl\school_cqufe.py 的 COLLEGES / MAJORS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `学生` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `学号`      VARCHAR(40)  NOT NULL,
    `姓名`      VARCHAR(60)  NOT NULL,
    `学院`      VARCHAR(80)  NOT NULL,
    `专业`      VARCHAR(80)  NOT NULL,
    `班级`      VARCHAR(40)  NOT NULL,
    `年级`      VARCHAR(10)  NOT NULL,
    `入学年份`  SMALLINT     NOT NULL,
    `口令摘要`  VARCHAR(255) NOT NULL,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_student_no (`学号`),
    KEY idx_student_tenant_class (`租户编号`, `班级`),
    KEY idx_student_college_major (`学院`, `专业`),
    CONSTRAINT fk_student_tenant FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生';

-- -----------------------------------------------------------
-- 4. 课程（按专业归属）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `课程` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `课程编号`  VARCHAR(40)  NOT NULL,
    `课程名称`  VARCHAR(120) NOT NULL,
    `学分`      DECIMAL(3,1) NOT NULL,
    `专业`      VARCHAR(80)  NOT NULL,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_course_code (`课程编号`),
    KEY idx_course_major (`专业`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='课程';

-- -----------------------------------------------------------
-- 5. 成绩
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `成绩` (
    `编号`      BIGINT        NOT NULL AUTO_INCREMENT,
    `学生编号`  BIGINT        NOT NULL,
    `课程编号`  BIGINT        NOT NULL,
    `学期`      VARCHAR(20)   NOT NULL,
    `分数`      DECIMAL(5,2)  NOT NULL,
    `是否重修`  TINYINT(1)    NOT NULL DEFAULT 0,
    PRIMARY KEY (`编号`),
    KEY idx_score_student_term (`学生编号`, `学期`),
    CONSTRAINT fk_score_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`),
    CONSTRAINT fk_score_course  FOREIGN KEY (`课程编号`)  REFERENCES `课程`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='成绩';

-- -----------------------------------------------------------
-- 5.1 学业警示记录（学生手册口径）
--     只记录已发出的学业警示快照；当前学期是否新增由 engine.warning
--     按不及格课程学分 >= 15 确定性计算，避免模型或前端改写政策。
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `学业警示记录` (
    `编号`        BIGINT        NOT NULL AUTO_INCREMENT,
    `租户编号`    BIGINT        NOT NULL,
    `学生编号`    BIGINT        NOT NULL,
    `学期`        VARCHAR(20)   NOT NULL,
    `不及格学分`  DECIMAL(5,1)  NOT NULL,
    `警示序号`    TINYINT       NOT NULL,
    `状态`        ENUM('issued','cancelled') NOT NULL DEFAULT 'issued',
    `记录时间`    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_academic_warning_student_term (`学生编号`, `学期`),
    KEY idx_academic_warning_tenant_student (`租户编号`, `学生编号`, `学期`),
    CONSTRAINT fk_academic_warning_tenant FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`),
    CONSTRAINT fk_academic_warning_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生手册学业警示历史快照';

-- -----------------------------------------------------------
-- 6. 考勤
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `考勤` (
    `编号`      BIGINT        NOT NULL AUTO_INCREMENT,
    `学生编号`  BIGINT        NOT NULL,
    `学期`      VARCHAR(20)   NOT NULL,
    `应到次数`  INT           NOT NULL,
    `缺勤次数`  INT           NOT NULL,
    `出勤率`    DECIMAL(5,4)  NOT NULL,
    PRIMARY KEY (`编号`),
    KEY idx_attendance_student_term (`学生编号`, `学期`),
    CONSTRAINT fk_attendance_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='考勤';

-- -----------------------------------------------------------
-- 7. 岗位（真实岗位表）
--    原始键 = md5(company|title|city) 唯一键防重灌
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `岗位` (
    `编号`      BIGINT        NOT NULL AUTO_INCREMENT,
    `岗位名称`  VARCHAR(200)  NOT NULL,
    `企业`      VARCHAR(200)  NOT NULL,
    `行业`      VARCHAR(80),
    `企业规模`  VARCHAR(40),
    `城市`      VARCHAR(60),
    `区县`      VARCHAR(60),
    `最低薪资`  DECIMAL(8,2),
    `最高薪资`  DECIMAL(8,2),
    `薪资单位`  ENUM('month','day') NOT NULL DEFAULT 'month',
    `薪资月数`  TINYINT       NULL,
    `最低经验`  TINYINT       NOT NULL DEFAULT 0,
    `最高经验`  TINYINT       NOT NULL DEFAULT 0,
    `学历`      VARCHAR(20),
    `技能标签`  JSON,
    `福利待遇`  JSON,
    `岗位描述`  TEXT,
    `来源`      VARCHAR(40)   NOT NULL,
    `原始键`    CHAR(32)      NOT NULL,
    `发布时间`  DATETIME,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_job_raw_key (`原始键`),
    KEY idx_job_title (`岗位名称`),
    KEY idx_job_city (`城市`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='招聘岗位（真实岗位表）';

-- -----------------------------------------------------------
-- 8. 预警阈值（按租户可配置）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `预警阈值` (
    `编号`      BIGINT        NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT        NOT NULL,
    `指标`      VARCHAR(60)   NOT NULL,
    `权重`      DECIMAL(5,4)  NOT NULL DEFAULT 1.0000,
    `红色阈值`  DECIMAL(8,2),
    `橙色阈值`  DECIMAL(8,2),
    `黄色阈值`  DECIMAL(8,2),
    `更新时间`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_threshold_tenant_metric (`租户编号`, `指标`),
    CONSTRAINT fk_threshold_tenant FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='预警阈值（租户默认）';

-- -----------------------------------------------------------
-- 8.1 班级预警阈值 —— 班级级预警阈值覆盖
--     预警阈值 仍是租户默认；本表只存“某班的覆盖值”，
--     未覆盖的指标回退租户默认，再回退 engine.rules 内置默认。
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `班级预警阈值` (
    `编号`      BIGINT        NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT        NOT NULL,
    `班级`      VARCHAR(40)   NOT NULL,
    `指标`      VARCHAR(60)   NOT NULL,
    `权重`      DECIMAL(5,4)  NULL,
    `红色阈值`  DECIMAL(8,2)  NULL,
    `橙色阈值`  DECIMAL(8,2)  NULL,
    `黄色阈值`  DECIMAL(8,2)  NULL,
    `更新时间`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_class_threshold (`租户编号`, `班级`, `指标`),
    KEY idx_class_threshold_class (`租户编号`, `班级`),
    CONSTRAINT fk_ct_tenant FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='班级级预警阈值覆盖（NULL = 回退租户默认）';

-- -----------------------------------------------------------
-- 9. 审计日志
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `审计日志` (
    `编号`        BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`    BIGINT       NOT NULL DEFAULT 1,
    `操作者类型`  VARCHAR(20)  NOT NULL,
    `操作者编号`  BIGINT       NOT NULL,
    `动作`        VARCHAR(80)  NOT NULL,
    `对象`        VARCHAR(200),
    `详情`        JSON,
    `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_audit_log_created (`创建时间`),
    KEY idx_audit_tenant_action_time (`租户编号`, `动作`, `创建时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='审计日志';

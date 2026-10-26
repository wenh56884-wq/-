-- ============================================================
-- 启航 MySQL 8.0.21 业务库 schema（库名 qihang, utf8mb4）
-- 所有数值字段禁止 FLOAT/DOUBLE，分数用 DECIMAL(5,2)，比例用 DECIMAL(5,4)
-- 幂等：全部 CREATE TABLE IF NOT EXISTS
-- ============================================================

CREATE DATABASE IF NOT EXISTS qihang
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE qihang;

-- -----------------------------------------------------------
-- 1. tenant —— 租户
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    name        VARCHAR(120) NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 种子数据（幂等）
INSERT INTO tenant (id, name)
SELECT 1, '重庆财经学院'
    FROM DUAL
    WHERE NOT EXISTS (SELECT 1 FROM tenant WHERE id = 1);

-- -----------------------------------------------------------
-- 2. teacher —— 教师
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS teacher (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT       NOT NULL,
    name           VARCHAR(60)  NOT NULL,
    employee_no    VARCHAR(40)  NOT NULL,
    role           VARCHAR(20)  NOT NULL DEFAULT 'teacher',
    password_hash  VARCHAR(255) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_employee_no (employee_no),
    KEY idx_teacher_tenant (tenant_id),
    CONSTRAINT fk_teacher_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 3. student —— 学生
--    college / major 取值必须来自 etl\school_cqufe.py 的 COLLEGES / MAJORS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS student (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT       NOT NULL,
    student_no     VARCHAR(40)  NOT NULL,
    name           VARCHAR(60)  NOT NULL,
    college        VARCHAR(80)  NOT NULL,
    major          VARCHAR(80)  NOT NULL,
    class_name     VARCHAR(40)  NOT NULL,
    grade          VARCHAR(10)  NOT NULL,
    enroll_year    SMALLINT     NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_student_no (student_no),
    KEY idx_student_tenant_class (tenant_id, class_name),
    KEY idx_student_college_major (college, major),
    CONSTRAINT fk_student_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 4. course —— 课程（按专业归属）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS course (
    id      BIGINT       NOT NULL AUTO_INCREMENT,
    code    VARCHAR(40)  NOT NULL,
    name    VARCHAR(120) NOT NULL,
    credit  DECIMAL(3,1) NOT NULL,
    major   VARCHAR(80)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_course_code (code),
    KEY idx_course_major (major)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 5. score —— 成绩
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS score (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    student_id  BIGINT        NOT NULL,
    course_id   BIGINT        NOT NULL,
    term        VARCHAR(10)   NOT NULL,
    score       DECIMAL(5,2)  NOT NULL,
    is_retake   TINYINT(1)    NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_score_student_term (student_id, term),
    CONSTRAINT fk_score_student FOREIGN KEY (student_id) REFERENCES student(id),
    CONSTRAINT fk_score_course  FOREIGN KEY (course_id)  REFERENCES course(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 6. attendance —— 考勤
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    id                BIGINT        NOT NULL AUTO_INCREMENT,
    student_id        BIGINT        NOT NULL,
    term              VARCHAR(10)   NOT NULL,
    total_sessions    INT           NOT NULL,
    absent_sessions   INT           NOT NULL,
    attendance_rate   DECIMAL(5,4)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_attendance_student_term (student_id, term),
    CONSTRAINT fk_attendance_student FOREIGN KEY (student_id) REFERENCES student(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 7. job —— 真实岗位表
--    raw_key = md5(company|title|city) 唯一键防重灌
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS job (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    title         VARCHAR(200)  NOT NULL,
    company       VARCHAR(200)  NOT NULL,
    industry      VARCHAR(80),
    company_size  VARCHAR(40),
    city          VARCHAR(60),
    district      VARCHAR(60),
    salary_min    DECIMAL(8,2),
    salary_max    DECIMAL(8,2),
    salary_unit   ENUM('month','day') NOT NULL DEFAULT 'month',
    salary_months TINYINT       NULL,
    exp_min       TINYINT       NOT NULL DEFAULT 0,
    exp_max       TINYINT       NOT NULL DEFAULT 0,
    education     VARCHAR(20),
    skill_tags    JSON,
    benefits      JSON,
    description   TEXT,
    source        VARCHAR(40)   NOT NULL,
    raw_key       CHAR(32)      NOT NULL,
    published_at  DATETIME,
    PRIMARY KEY (id),
    UNIQUE KEY uk_job_raw_key (raw_key),
    KEY idx_job_title (title),
    KEY idx_job_city (city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 8. warning_threshold —— 预警阈值（按租户可配置）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS warning_threshold (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT        NOT NULL,
    metric        VARCHAR(60)   NOT NULL,
    weight        DECIMAL(5,4)  NOT NULL DEFAULT 1.0000,
    red_value     DECIMAL(8,2),
    orange_value  DECIMAL(8,2),
    yellow_value  DECIMAL(8,2),
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_threshold_tenant_metric (tenant_id, metric),
    CONSTRAINT fk_threshold_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 9. audit_log —— 审计日志
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    actor_type  VARCHAR(20)  NOT NULL,
    actor_id    BIGINT       NOT NULL,
    action      VARCHAR(80)  NOT NULL,
    target      VARCHAR(200),
    detail      JSON,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_audit_log_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

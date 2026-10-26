-- ============================================================
-- 启航 DuckDB 分析库 schema（D:/qihang/data/analytics.duckdb）
-- 幂等：全部 CREATE TABLE IF NOT EXISTS
-- DuckDB 不支持 ENUM，用 VARCHAR + CHECK 代替
-- ============================================================

-- -----------------------------------------------------------
-- 1. student_feature —— 学生特征宽表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS student_feature (
    student_no            VARCHAR(40)   NOT NULL,
    term                  VARCHAR(20)   NOT NULL,
    gpa                   DECIMAL(5,2),
    gpa_trend             DECIMAL(5,2),
    fail_count            INTEGER,
    rank_pct              DECIMAL(5,4),
    attendance_rate       DECIMAL(5,4),
    library_activity      INTEGER,
    consumption_regularity DECIMAL(5,4),
    course_pref           JSON,
    job_view_cnt          INTEGER,
    job_favorite_cnt      INTEGER,
    cert_count             INTEGER,
    contest_count          INTEGER,
    project_cnt            INTEGER,
    tags                   JSON,
    calc_version           VARCHAR(20)   NOT NULL,
    updated_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_no, term)
);

-- -----------------------------------------------------------
-- 2. job_feature —— 岗位特征宽表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_feature (
    title         VARCHAR(200)  NOT NULL,
    city          VARCHAR(60),
    salary_min    DECIMAL(8,2),
    salary_max    DECIMAL(8,2),
    education     VARCHAR(20),
    exp_min       SMALLINT,
    exp_max       SMALLINT,
    skill_tags    JSON,
    source        VARCHAR(40)   NOT NULL,
    calc_version  VARCHAR(20)   NOT NULL,
    updated_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 3. recommend_log —— 推荐日志（每次推荐留痕）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS recommend_log (
    id            BIGINT        NOT NULL,
    student_no    VARCHAR(40)   NOT NULL,
    job_id        BIGINT         NOT NULL,
    content_score DECIMAL(5,4),
    cf_score      DECIMAL(5,4),
    final_score   DECIMAL(5,4),
    hit_items     JSON,
    gap_items     JSON,
    advice        TEXT,
    engine_version VARCHAR(20)  NOT NULL,
    created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

-- ============================================================
-- 启航 源表补齐 v2（追加 4 张表，不改动已有 9 张表）
-- 目的：让画像引擎 7 个行为/兴趣/能力特征从「缺失态」变成「有真实源数据」
-- 对齐：docs\指标口径字典.md v1.1 第 1 节、第 3 节
-- 幂等：全部 CREATE TABLE IF NOT EXISTS，可重复执行
-- 执行：mysql -u root -p qihang < db\source_tables_v2.sql
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 10. library_record —— 图书馆到馆/借阅（按学期汇总）
--     支撑特征：library_visit_cnt → library_activity
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS library_record (
    id          BIGINT   NOT NULL AUTO_INCREMENT,
    tenant_id   BIGINT   NOT NULL,
    student_id  BIGINT   NOT NULL,
    term        VARCHAR(20) NOT NULL,
    visit_cnt   INT      NOT NULL DEFAULT 0 COMMENT '本学期到馆次数（真实次数，非归一值）',
    borrow_cnt  INT      NOT NULL DEFAULT 0 COMMENT '本学期借阅册数',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_library_student_term (student_id, term),
    KEY idx_library_tenant_term (tenant_id, term),
    CONSTRAINT fk_library_student FOREIGN KEY (student_id) REFERENCES student(id),
    CONSTRAINT fk_library_tenant  FOREIGN KEY (tenant_id)  REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='图书馆行为源表（按学期汇总，非流水）';

-- -----------------------------------------------------------
-- 11. consumption_record —— 一卡通消费（按学期汇总）
--     支撑特征：consumption_regularity = min(1, active_days / 120)
--     口径：120 为学期有效天数上限常量，写死在 engine\rules.py 的 CONSUME_DAY_CAP
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS consumption_record (
    id          BIGINT   NOT NULL AUTO_INCREMENT,
    tenant_id   BIGINT   NOT NULL,
    student_id  BIGINT   NOT NULL,
    term        VARCHAR(20) NOT NULL,
    meal_cnt    INT      NOT NULL DEFAULT 0 COMMENT '本学期食堂消费笔数',
    active_days INT      NOT NULL DEFAULT 0 COMMENT '有消费的天数（规律性分子）',
    avg_amount  DECIMAL(8,2) NULL COMMENT '日均消费金额（仅展示，不参与打分）',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_consume_student_term (student_id, term),
    KEY idx_consume_tenant_term (tenant_id, term),
    CONSTRAINT fk_consume_student FOREIGN KEY (student_id) REFERENCES student(id),
    CONSTRAINT fk_consume_tenant  FOREIGN KEY (tenant_id)  REFERENCES tenant(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='一卡通消费源表（按学期汇总）';

-- -----------------------------------------------------------
-- 12. student_activity —— 证书 / 竞赛 / 项目（三合一，避免建三张结构相同的表）
--     支撑特征：cert_count、contest_count、project_cnt
--     设计意图：三类活动的字段结构完全一致（名称/级别/时间），
--               用 activity_type 区分即可，减少 3 张表的维护成本与联表复杂度
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS student_activity (
    id            BIGINT   NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT   NOT NULL,
    student_id    BIGINT   NOT NULL,
    term          VARCHAR(20) NOT NULL COMMENT '归属学期（用于按期统计）',
    activity_type VARCHAR(16) NOT NULL COMMENT 'cert=证书 / contest=竞赛 / project=项目',
    title         VARCHAR(160) NOT NULL,
    level         VARCHAR(40)  NULL COMMENT '国家级/省级/校级/企业级 等',
    got_at        DATE         NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_activity_student_term (student_id, term),
    KEY idx_activity_tenant_type (tenant_id, activity_type),
    CONSTRAINT fk_activity_student FOREIGN KEY (student_id) REFERENCES student(id),
    CONSTRAINT fk_activity_tenant  FOREIGN KEY (tenant_id)  REFERENCES tenant(id),
    CONSTRAINT ck_activity_type CHECK (activity_type IN ('cert','contest','project'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='证书/竞赛/项目源表（三合一）';

-- -----------------------------------------------------------
-- 13. job_view_log —— 岗位浏览与收藏（流水）
--     支撑特征：job_view_cnt、job_favorite_cnt、job_view_pref{方向:次数}
--     注意：这是流水表，统计时按 (student_id, term, action) 聚合，不要在 SQL 里做 COUNT(*) 全表扫
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_view_log (
    id          BIGINT   NOT NULL AUTO_INCREMENT,
    tenant_id   BIGINT   NOT NULL,
    student_id  BIGINT   NOT NULL,
    job_id      BIGINT   NOT NULL,
    action      VARCHAR(10) NOT NULL DEFAULT 'view' COMMENT 'view=浏览 / favorite=收藏',
    term        VARCHAR(20) NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_jobview_student_term (student_id, term, action),
    KEY idx_jobview_job (job_id),
    CONSTRAINT fk_jobview_student FOREIGN KEY (student_id) REFERENCES student(id),
    CONSTRAINT fk_jobview_tenant  FOREIGN KEY (tenant_id)  REFERENCES tenant(id),
    CONSTRAINT fk_jobview_job     FOREIGN KEY (job_id)     REFERENCES job(id),
    CONSTRAINT ck_jobview_action CHECK (action IN ('view','favorite'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='岗位浏览/收藏流水表';

-- -----------------------------------------------------------
-- 校验：四张表建好后应能查出 0 行而不是报错
-- -----------------------------------------------------------
SELECT 'library_record'     AS tbl, COUNT(*) AS rows_now FROM library_record
UNION ALL SELECT 'consumption_record', COUNT(*) FROM consumption_record
UNION ALL SELECT 'student_activity',   COUNT(*) FROM student_activity
UNION ALL SELECT 'job_view_log',       COUNT(*) FROM job_view_log;

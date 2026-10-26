-- ============================================================
-- 选修方向源表（解决 course_pref 全空）
-- 纯新增，不改动已有任何表
-- 执行：mysql -u root -p qihang < db\elective_tables.sql
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- elective_selection —— 学生选课记录（含方向）
--   设计要点：direction 在选课写入时就确定（由 rules\direction_keywords.json
--   的 elective_pool 课程表给出），**不靠事后猜课程名**。
--   这样 course_pref = GROUP BY direction 即可，口径可复核、可重算。
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS elective_selection (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id    BIGINT       NOT NULL,
    student_id   BIGINT       NOT NULL,
    term         VARCHAR(20)  NOT NULL,
    course_name  VARCHAR(120) NOT NULL,
    direction    VARCHAR(20)  NOT NULL COMMENT '课程所属方向，来自 elective_pool 标注',
    credit       DECIMAL(3,1) NULL COMMENT '学分',
    selected_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_student_term_course (student_id, term, course_name),
    KEY idx_tenant_term (tenant_id, term),
    KEY idx_direction (direction),
    CONSTRAINT fk_elective_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE,
    CONSTRAINT ck_elective_credit CHECK (credit IS NULL OR (credit > 0 AND credit <= 10))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生选课记录（选修方向源表）';

-- 验收：
--   SHOW TABLES LIKE 'elective%';
--   SELECT direction, COUNT(*) FROM elective_selection GROUP BY direction;
--   —— 至少覆盖 6 个方向，单方向占比不超过 40%

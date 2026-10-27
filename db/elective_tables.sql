-- ============================================================
-- 选修方向源表（解决 course_pref 全空）
-- 纯新增，不改动已有任何表
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹
-- 执行：mysql -u root -p qihang < db\elective_tables.sql
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 选课记录 —— 学生选课记录（含方向）
--   设计要点：方向 在选课写入时就确定（由 rules\direction_keywords.json
--   的 elective_pool 课程表给出），**不靠事后猜课程名**。
--   这样 课程偏好 = GROUP BY 方向 即可，口径可复核、可重算。
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `选课记录` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `学生编号`  BIGINT       NOT NULL,
    `学期`      VARCHAR(20)  NOT NULL,
    `课程名称`  VARCHAR(120) NOT NULL,
    `方向`      VARCHAR(20)  NOT NULL COMMENT '课程所属方向，来自 elective_pool 标注',
    `学分`      DECIMAL(3,1) NULL COMMENT '学分',
    `选课时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_student_term_course (`学生编号`, `学期`, `课程名称`),
    KEY idx_tenant_term (`租户编号`, `学期`),
    KEY idx_direction (`方向`),
    CONSTRAINT fk_elective_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE,
    CONSTRAINT ck_elective_credit CHECK (`学分` IS NULL OR (`学分` > 0 AND `学分` <= 10))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生选课记录（选修方向源表）';

-- 验收：
--   SHOW TABLES LIKE '选课记录';
--   SELECT `方向`, COUNT(*) FROM `选课记录` GROUP BY `方向`;
--   —— 至少覆盖 6 个方向，单方向占比不超过 40%

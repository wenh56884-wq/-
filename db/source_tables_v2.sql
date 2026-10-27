-- ============================================================
-- 启航 源表补齐 v2（追加 4 张表，不改动已有表）
-- 目的：让画像引擎 7 个行为/兴趣/能力特征从「缺失态」变成「有真实源数据」
-- 对齐：docs\指标口径字典.md v1.1 第 1 节、第 3 节
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹
-- 幂等：全部 CREATE TABLE IF NOT EXISTS，可重复执行
-- 执行：mysql -u root -p qihang < db\source_tables_v2.sql
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 图书馆记录 —— 图书馆到馆/借阅（按学期汇总）
--     支撑特征：到馆次数 → 图书馆活跃度
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `图书馆记录` (
    `编号`      BIGINT   NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT   NOT NULL,
    `学生编号`  BIGINT   NOT NULL,
    `学期`      VARCHAR(20) NOT NULL,
    `到馆次数`  INT      NOT NULL DEFAULT 0 COMMENT '本学期到馆次数（真实次数，非归一值）',
    `借阅册数`  INT      NOT NULL DEFAULT 0 COMMENT '本学期借阅册数',
    `创建时间`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_library_student_term (`学生编号`, `学期`),
    KEY idx_library_tenant_term (`租户编号`, `学期`),
    CONSTRAINT fk_library_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`),
    CONSTRAINT fk_library_tenant  FOREIGN KEY (`租户编号`)  REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='图书馆行为源表（按学期汇总，非流水）';

-- -----------------------------------------------------------
-- 消费记录 —— 一卡通消费（按学期汇总）
--     支撑特征：消费规律性 = min(1, 活跃天数 / 120)
--     口径：120 为学期有效天数上限常量，写死在 engine\rules.py 的 CONSUME_DAY_CAP
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `消费记录` (
    `编号`      BIGINT   NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT   NOT NULL,
    `学生编号`  BIGINT   NOT NULL,
    `学期`      VARCHAR(20) NOT NULL,
    `消费笔数`  INT      NOT NULL DEFAULT 0 COMMENT '本学期食堂消费笔数',
    `活跃天数`  INT      NOT NULL DEFAULT 0 COMMENT '有消费的天数（规律性分子）',
    `日均金额`  DECIMAL(8,2) NULL COMMENT '日均消费金额（仅展示，不参与打分）',
    `创建时间`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_consume_student_term (`学生编号`, `学期`),
    KEY idx_consume_tenant_term (`租户编号`, `学期`),
    CONSTRAINT fk_consume_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`),
    CONSTRAINT fk_consume_tenant  FOREIGN KEY (`租户编号`)  REFERENCES `租户`(`编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='一卡通消费源表（按学期汇总）';

-- -----------------------------------------------------------
-- 学生活动 —— 证书 / 竞赛 / 项目（三合一，避免建三张结构相同的表）
--     支撑特征：证书数、竞赛数、项目数
--     设计意图：三类活动的字段结构完全一致（名称/级别/时间），
--               用 活动类型 区分即可，减少 3 张表的维护成本与联表复杂度
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `学生活动` (
    `编号`      BIGINT   NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT   NOT NULL,
    `学生编号`  BIGINT   NOT NULL,
    `学期`      VARCHAR(20) NOT NULL COMMENT '归属学期（用于按期统计）',
    `活动类型`  VARCHAR(16) NOT NULL COMMENT 'cert=证书 / contest=竞赛 / project=项目',
    `名称`      VARCHAR(160) NOT NULL,
    `级别`      VARCHAR(40)  NULL COMMENT '国家级/省级/校级/企业级 等',
    `获得时间`  DATE         NULL,
    `创建时间`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_activity_student_term (`学生编号`, `学期`),
    KEY idx_activity_tenant_type (`租户编号`, `活动类型`),
    CONSTRAINT fk_activity_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`),
    CONSTRAINT fk_activity_tenant  FOREIGN KEY (`租户编号`)  REFERENCES `租户`(`编号`),
    CONSTRAINT ck_activity_type CHECK (`活动类型` IN ('cert','contest','project'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='证书/竞赛/项目源表（三合一）';

-- -----------------------------------------------------------
-- 岗位浏览日志 —— 岗位浏览与收藏（流水）
--     支撑特征：岗位浏览数、岗位收藏数、课程偏好{方向:次数}
--     注意：这是流水表，统计时按 (学生编号, 学期, 动作) 聚合，
--           不要在 SQL 里做 COUNT(*) 全表扫
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `岗位浏览日志` (
    `编号`      BIGINT   NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT   NOT NULL,
    `学生编号`  BIGINT   NOT NULL,
    `岗位编号`  BIGINT   NOT NULL,
    `动作`      VARCHAR(10) NOT NULL DEFAULT 'view' COMMENT 'view=浏览 / favorite=收藏',
    `学期`      VARCHAR(20) NOT NULL,
    `创建时间`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_jobview_student_term (`学生编号`, `学期`, `动作`),
    KEY idx_jobview_job (`岗位编号`),
    CONSTRAINT fk_jobview_student FOREIGN KEY (`学生编号`) REFERENCES `学生`(`编号`),
    CONSTRAINT fk_jobview_tenant  FOREIGN KEY (`租户编号`) REFERENCES `租户`(`编号`),
    CONSTRAINT fk_jobview_job     FOREIGN KEY (`岗位编号`) REFERENCES `岗位`(`编号`),
    CONSTRAINT ck_jobview_action CHECK (`动作` IN ('view','favorite'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='岗位浏览/收藏流水表';

-- -----------------------------------------------------------
-- 校验：四张表建好后应能查出 0 行而不是报错
-- -----------------------------------------------------------
SELECT '图书馆记录' AS tbl, COUNT(*) AS rows_now FROM `图书馆记录`
UNION ALL SELECT '消费记录', COUNT(*) FROM `消费记录`
UNION ALL SELECT '学生活动', COUNT(*) FROM `学生活动`
UNION ALL SELECT '岗位浏览日志', COUNT(*) FROM `岗位浏览日志`;

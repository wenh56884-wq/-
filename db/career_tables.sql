-- ============================================================
-- 职业规划规培模块 · 7 张表（career-v1）
-- 全部为新增表，不改动已有 13 张表的任何字段与索引
-- 执行：mysql -u root -p qihang < db\career_tables.sql
-- 幂等：全部 IF NOT EXISTS
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 1. student_extra —— 规划所需但学生表没有的画像事实
--    与 student 一对一；缺失即 NULL，不用默认值冒充
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS student_extra (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id         BIGINT       NOT NULL,
    student_id        BIGINT       NOT NULL,
    cet4_score        SMALLINT     NULL COMMENT '四级分数，未考为 NULL',
    cet6_score        SMALLINT     NULL COMMENT '六级分数',
    political_status  VARCHAR(20)  NULL COMMENT '群众/共青团员/中共党员/中共预备党员',
    target_city       VARCHAR(60)  NULL COMMENT '意向就业城市',
    weekly_hours      DECIMAL(5,1) NULL COMMENT '自报每周可投入学习小时数',
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_student (student_id),
    KEY idx_tenant (tenant_id),
    CONSTRAINT fk_extra_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE,
    CONSTRAINT ck_cet4 CHECK (cet4_score IS NULL OR (cet4_score BETWEEN 0 AND 710)),
    CONSTRAINT ck_cet6 CHECK (cet6_score IS NULL OR (cet6_score BETWEEN 0 AND 710))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生规划扩展事实（四六级/政治面貌等）';

-- -----------------------------------------------------------
-- 2. career_plan —— 规划原文 + 模型解析出的画像（JSON）
--    plan_json 由模型产出，但其中"当前差距"必须来自引擎；
--    记录 prompt_version + model + raw_response 便于复盘
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS career_plan (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT       NOT NULL,
    student_id      BIGINT       NOT NULL,
    raw_text        TEXT         NOT NULL COMMENT '学生填写的规划原文',
    goal_type       VARCHAR(20)  NULL COMMENT '考公/考研/就业/混合（引擎归一后）',
    plan_json       JSON         NULL COMMENT '画像结构化结果',
    gaps_json       JSON         NULL COMMENT '当前差距（engine.build_gaps 产出，模型不可改）',
    pending_questions JSON       NULL COMMENT '需要学生补充的问题（≤3）',
    prompt_version  VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    model_name      VARCHAR(60)  NULL,
    is_active       TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '同一学生仅一条 active',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_student_active (student_id, is_active),
    KEY idx_tenant (tenant_id),
    CONSTRAINT fk_plan_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='职业规划原文与画像';

-- -----------------------------------------------------------
-- 3. plan_rule —— 规则匹配结果（模板选择 + 硬门槛状态 + 阶段计划）
--    模板本身放 rules/*.json，不落库；此处只存"匹配后的实例"
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_rule (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id         BIGINT       NOT NULL,
    student_id        BIGINT       NOT NULL,
    plan_id           BIGINT       NOT NULL,
    main_template     VARCHAR(40)  NOT NULL COMMENT '主模板文件名（kaogong/kaoyan/jiuye）',
    sub_template      VARCHAR(40)  NULL COMMENT '混合目标的次模板',
    main_weight       DECIMAL(4,2) NOT NULL DEFAULT 1.00,
    gates_json        JSON         NULL COMMENT '硬门槛逐项状态（engine.check_hard_gates）',
    phases_json       JSON         NULL COMMENT '阶段划分（engine.plan_phases，日期已算好）',
    metrics_json      JSON         NULL COMMENT '每周监控指标与达标线',
    calendar_json     JSON         NULL COMMENT '关键节点日历（来自规则库+通知表）',
    hard_baseline     JSON         NULL COMMENT '硬基线项（不可调）',
    adjustable        JSON         NULL COMMENT '可调项',
    engine_version    VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_plan (plan_id),
    KEY idx_student (student_id),
    KEY idx_tenant (tenant_id),
    CONSTRAINT fk_rule_plan FOREIGN KEY (plan_id) REFERENCES career_plan (id) ON DELETE CASCADE,
    CONSTRAINT fk_rule_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='规培规则匹配结果';

-- -----------------------------------------------------------
-- 4. week_snapshot —— 周快照（三色判定由引擎算，模型只写摘要/建议）
--    "连续两周落后"依赖此表的历史行，模型不记忆
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS week_snapshot (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT       NOT NULL,
    student_id      BIGINT       NOT NULL,
    plan_id         BIGINT       NOT NULL,
    iso_year        SMALLINT     NOT NULL,
    iso_week        SMALLINT     NOT NULL,
    self_report     JSON         NULL COMMENT '学生自报：学习时长/打卡/自评',
    system_metrics  JSON         NULL COMMENT '系统数据：绩点变化/报名状态/通知数',
    judge_json      JSON         NULL COMMENT '引擎三色判定结果（含 items/overall/missing）',
    escalation_json JSON         NULL COMMENT '升级预警（engine.escalate_risks）',
    notice_push     JSON         NULL COMMENT '本周推送的通知（已过滤截止）',
    summary         VARCHAR(400) NULL COMMENT '模型生成的 150 字摘要',
    advice_json     JSON         NULL COMMENT '下周建议（≤3 条，模型产出）',
    engine_version  VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_student_week (student_id, iso_year, iso_week),
    KEY idx_plan_week (plan_id, iso_year, iso_week),
    KEY idx_tenant (tenant_id),
    CONSTRAINT fk_week_plan FOREIGN KEY (plan_id) REFERENCES career_plan (id) ON DELETE CASCADE,
    CONSTRAINT fk_week_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='周度监控快照';

-- -----------------------------------------------------------
-- 5. notice —— 学校通知（截止日期必须来自真实来源，不许模型生成）
--    来源：scripts/import_notice.py 导入 CSV；二期接官网抓取
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT       NOT NULL,
    title         VARCHAR(200) NOT NULL,
    publisher     VARCHAR(120) NULL COMMENT '发布单位',
    deadline      DATE         NULL COMMENT '截止日期，未知为 NULL',
    summary       TEXT         NULL COMMENT '正文摘要',
    url           VARCHAR(500) NULL COMMENT '原文链接（可追溯）',
    category      VARCHAR(40)  NULL COMMENT '竞赛/考试/报名/讲座/招聘',
    raw_hash      CHAR(32)     NOT NULL COMMENT 'md5(标题+截止+单位)，防重复导入',
    published_at  DATE         NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_raw_hash (raw_hash),
    KEY idx_deadline (deadline),
    KEY idx_tenant (tenant_id),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学校通知（截止日期为事实数据）';

-- -----------------------------------------------------------
-- 6. notice_match —— 通知 × 学生 相关性（模型判相关性，但截止状态由引擎给）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_match (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    tenant_id   BIGINT      NOT NULL,
    notice_id   BIGINT      NOT NULL,
    student_id  BIGINT      NOT NULL,
    relevance   VARCHAR(10) NOT NULL COMMENT 'high/medium/low',
    reason      VARCHAR(120) NULL COMMENT '推送理由（≤30 字，须对应画像字段）',
    created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_notice_student (notice_id, student_id),
    KEY idx_student (student_id),
    CONSTRAINT fk_match_notice FOREIGN KEY (notice_id) REFERENCES notice (id) ON DELETE CASCADE,
    CONSTRAINT fk_match_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE,
    CONSTRAINT ck_relevance CHECK (relevance IN ('high', 'medium', 'low'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='通知与学生画像的相关性判定';

-- -----------------------------------------------------------
-- 7. career_intent —— 学生自选职业目标（大一先选，大二/大三可调整）
--    只存学生选择，不存模型判断；规划文案由 engine.career_guide 生成
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS career_intent (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    tenant_id   BIGINT      NOT NULL,
    student_id  BIGINT      NOT NULL,
    intent      VARCHAR(20) NOT NULL COMMENT '考公/考研/考编/就业',
    created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_intent_student (tenant_id, student_id),
    KEY idx_intent_student (student_id),
    CONSTRAINT fk_intent_student FOREIGN KEY (student_id) REFERENCES student (id) ON DELETE CASCADE,
    CONSTRAINT ck_intent CHECK (intent IN ('考公', '考研', '考编', '就业'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生职业目标选择（大一先选，可调整）';

-- 验收：
--   SHOW TABLES LIKE '%career%';  SHOW TABLES LIKE 'student_extra';
--   SHOW TABLES LIKE 'notice%';   SHOW TABLES LIKE 'week_snapshot';
--   SHOW TABLES LIKE 'career_intent';
--   共 7 张新表

-- ============================================================
-- 职业规划规培模块 · 7 张表（career-v1）
-- 全部为新增表，不改动已有表的任何字段与索引
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹
-- 执行：mysql -u root -p qihang < db\career_tables.sql
-- 幂等：全部 IF NOT EXISTS
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 1. 学生扩展信息 —— 规划所需但学生表没有的画像事实
--    与 学生 一对一；缺失即 NULL，不用默认值冒充
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `学生扩展信息` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `学生编号`  BIGINT       NOT NULL,
    `四级分数`  SMALLINT     NULL COMMENT '四级分数，未考为 NULL',
    `六级分数`  SMALLINT     NULL COMMENT '六级分数',
    `政治面貌`  VARCHAR(20)  NULL COMMENT '群众/共青团员/中共党员/中共预备党员',
    `意向城市`  VARCHAR(60)  NULL COMMENT '意向就业城市',
    `每周学时`  DECIMAL(5,1) NULL COMMENT '自报每周可投入学习小时数',
    `更新时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_student (`学生编号`),
    KEY idx_tenant (`租户编号`),
    CONSTRAINT fk_extra_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE,
    CONSTRAINT ck_cet4 CHECK (`四级分数` IS NULL OR (`四级分数` BETWEEN 0 AND 710)),
    CONSTRAINT ck_cet6 CHECK (`六级分数` IS NULL OR (`六级分数` BETWEEN 0 AND 710))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生规划扩展事实（四六级/政治面貌等）';

-- -----------------------------------------------------------
-- 2. 职业规划 —— 规划原文 + 模型解析出的画像（JSON）
--    规划内容 由模型产出，但其中"当前差距"必须来自引擎；
--    记录 提示词版本 + 模型名称 + 原始响应 便于复盘
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `职业规划` (
    `编号`        BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`    BIGINT       NOT NULL,
    `学生编号`    BIGINT       NOT NULL,
    `规划原文`    TEXT         NOT NULL COMMENT '学生填写的规划原文',
    `目标类型`    VARCHAR(20)  NULL COMMENT '考公/考研/就业/混合（引擎归一后）',
    `规划内容`    JSON         NULL COMMENT '画像结构化结果',
    `差距内容`    JSON         NULL COMMENT '当前差距（engine.build_gaps 产出，模型不可改）',
    `待补问题`    JSON         NULL COMMENT '需要学生补充的问题（≤3）',
    `提示词版本`  VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    `模型名称`    VARCHAR(60)  NULL,
    `是否生效`    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '同一学生仅一条 active',
    `创建时间`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_student_active (`学生编号`, `是否生效`),
    KEY idx_tenant (`租户编号`),
    CONSTRAINT fk_plan_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='职业规划原文与画像';

-- -----------------------------------------------------------
-- 3. 规划规则 —— 规则匹配结果（模板选择 + 硬门槛状态 + 阶段计划）
--    模板本身放 rules/*.json，不落库；此处只存"匹配后的实例"
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `规划规则` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `学生编号`  BIGINT       NOT NULL,
    `规划编号`  BIGINT       NOT NULL,
    `主模板`    VARCHAR(40)  NOT NULL COMMENT '主模板文件名（kaogong/kaoyan/jiuye）',
    `次模板`    VARCHAR(40)  NULL COMMENT '混合目标的次模板',
    `主权重`    DECIMAL(4,2) NOT NULL DEFAULT 1.00,
    `门槛状态`  JSON         NULL COMMENT '硬门槛逐项状态（engine.check_hard_gates）',
    `阶段计划`  JSON         NULL COMMENT '阶段划分（engine.plan_phases，日期已算好）',
    `监控指标`  JSON         NULL COMMENT '每周监控指标与达标线',
    `节点日历`  JSON         NULL COMMENT '关键节点日历（来自规则库+通知表）',
    `硬基线`    JSON         NULL COMMENT '硬基线项（不可调）',
    `可调项`    JSON         NULL COMMENT '可调项',
    `引擎版本`  VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_plan (`规划编号`),
    KEY idx_student (`学生编号`),
    KEY idx_tenant (`租户编号`),
    CONSTRAINT fk_rule_plan FOREIGN KEY (`规划编号`) REFERENCES `职业规划` (`编号`) ON DELETE CASCADE,
    CONSTRAINT fk_rule_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='规培规则匹配结果';

-- -----------------------------------------------------------
-- 4. 周快照 —— 周快照（三色判定由引擎算，模型只写摘要/建议）
--    "连续两周落后"依赖此表的历史行，模型不记忆
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `周快照` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `学生编号`  BIGINT       NOT NULL,
    `规划编号`  BIGINT       NOT NULL,
    `ISO年`     SMALLINT     NOT NULL,
    `ISO周`     SMALLINT     NOT NULL,
    `自报内容`  JSON         NULL COMMENT '学生自报：学习时长/打卡/自评',
    `系统指标`  JSON         NULL COMMENT '系统数据：绩点变化/报名状态/通知数',
    `判定结果`  JSON         NULL COMMENT '引擎三色判定结果（含 items/overall/missing）',
    `升级预警`  JSON         NULL COMMENT '升级预警（engine.escalate_risks）',
    `通知推送`  JSON         NULL COMMENT '本周推送的通知（已过滤截止）',
    `摘要`      VARCHAR(400) NULL COMMENT '模型生成的 150 字摘要',
    `建议内容`  JSON         NULL COMMENT '下周建议（≤3 条，模型产出）',
    `引擎版本`  VARCHAR(20)  NOT NULL DEFAULT 'career-v1',
    `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_student_week (`学生编号`, `ISO年`, `ISO周`),
    KEY idx_plan_week (`规划编号`, `ISO年`, `ISO周`),
    KEY idx_tenant (`租户编号`),
    CONSTRAINT fk_week_plan FOREIGN KEY (`规划编号`) REFERENCES `职业规划` (`编号`) ON DELETE CASCADE,
    CONSTRAINT fk_week_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='周度监控快照';

-- -----------------------------------------------------------
-- 5. 学校通知 —— 学校通知（截止日期必须来自真实来源，不许模型生成）
--    来源：scripts/import_notice.py 导入 CSV；二期接官网抓取
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `学校通知` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT       NOT NULL,
    `标题`      VARCHAR(200) NOT NULL,
    `发布单位`  VARCHAR(120) NULL COMMENT '发布单位',
    `截止日期`  DATE         NULL COMMENT '截止日期，未知为 NULL',
    `摘要`      TEXT         NULL COMMENT '正文摘要',
    `链接`      VARCHAR(500) NULL COMMENT '原文链接（可追溯）',
    `分类`      VARCHAR(40)  NULL COMMENT '竞赛/考试/报名/讲座/招聘',
    `原始哈希`  CHAR(32)     NOT NULL COMMENT 'md5(标题+截止+单位)，防重复导入',
    `发布日期`  DATE         NULL,
    `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_raw_hash (`原始哈希`),
    KEY idx_deadline (`截止日期`),
    KEY idx_tenant (`租户编号`),
    KEY idx_category (`分类`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学校通知（截止日期为事实数据）';

-- -----------------------------------------------------------
-- 6. 通知匹配 —— 通知 × 学生 相关性（模型判相关性，但截止状态由引擎给）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `通知匹配` (
    `编号`      BIGINT      NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT      NOT NULL,
    `通知编号`  BIGINT      NOT NULL,
    `学生编号`  BIGINT      NOT NULL,
    `相关度`    VARCHAR(10) NOT NULL COMMENT 'high/medium/low',
    `理由`      VARCHAR(120) NULL COMMENT '推送理由（≤30 字，须对应画像字段）',
    `创建时间`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_notice_student (`通知编号`, `学生编号`),
    KEY idx_student (`学生编号`),
    CONSTRAINT fk_match_notice FOREIGN KEY (`通知编号`) REFERENCES `学校通知` (`编号`) ON DELETE CASCADE,
    CONSTRAINT fk_match_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE,
    CONSTRAINT ck_relevance CHECK (`相关度` IN ('high', 'medium', 'low'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='通知与学生画像的相关性判定';

-- -----------------------------------------------------------
-- 7. 职业意向 —— 学生自选职业目标（大一先选，大二/大三可调整）
--    只存学生选择，不存模型判断；规划文案由 engine.career_guide 生成
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `职业意向` (
    `编号`      BIGINT      NOT NULL AUTO_INCREMENT,
    `租户编号`  BIGINT      NOT NULL,
    `学生编号`  BIGINT      NOT NULL,
    `意向`      VARCHAR(20) NOT NULL COMMENT '考公/考研/考编/就业',
    `创建时间`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `更新时间`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    UNIQUE KEY uk_intent_student (`租户编号`, `学生编号`),
    KEY idx_intent_student (`学生编号`),
    CONSTRAINT fk_intent_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE,
    CONSTRAINT ck_intent CHECK (`意向` IN ('考公', '考研', '考编', '就业'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学生职业目标选择（大一先选，可调整）';

-- 验收：
--   SHOW TABLES LIKE '%职业%';  SHOW TABLES LIKE '学生扩展信息';
--   SHOW TABLES LIKE '学校通知'; SHOW TABLES LIKE '周快照';
--   SHOW TABLES LIKE '职业意向';
--   共 7 张表

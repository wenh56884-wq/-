-- ============================================================
-- 软技能测评模块建表（assessment-v1）
-- 两张新增表，不改动已有表；中文命名，标识符反引号包裹
-- 执行：mysql -u root -p qihang < db\assessment_tables.sql
-- 幂等：全部 IF NOT EXISTS
-- ============================================================

USE qihang;

-- -----------------------------------------------------------
-- 1. 测评题目 —— 量表题库，选项与分值唯一真相源
--    scoring 存 JSON：{"A":5,"B":4,...}，反向题把分值顺序倒过来
--    维度(如 逻辑思维)由引擎映射到复合能力(professional_skills 等)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `测评题目` (
    `编号`      BIGINT       NOT NULL AUTO_INCREMENT,
    `类别`      VARCHAR(40)  NOT NULL COMMENT '性格特质/职业兴趣/能力评估/职业价值观/IT专项能力',
    `维度`      VARCHAR(40)  NOT NULL COMMENT '量表细粒度维度，如 逻辑思维/外向性',
    `题面`      TEXT         NOT NULL COMMENT '题目内容',
    `选项`      JSON         NULL COMMENT '{"A":"非常符合",...} 展示文案',
    `选项分值`  JSON         NULL COMMENT '{"A":5,"B":4,...} 各选项得分，唯一计分来源',
    `排序`      INT          NOT NULL DEFAULT 0,
    `是否启用`  TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=启用 0=停用',
    `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_dim (`维度`),
    KEY idx_enabled (`是否启用`, `排序`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='软技能测评题库（选项分值唯一真相源）';

-- -----------------------------------------------------------
-- 2. 测评结果 —— 学生提交的答题与引擎算出的画像
--    分数/画像全部由 engine.assessment 计算后落库，模型不得改写
--    学生仅可读本人（租户 + 学生编号 隔离在查询层）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `测评结果` (
    `编号`          BIGINT       NOT NULL AUTO_INCREMENT,
    `租户编号`      BIGINT       NOT NULL,
    `学生编号`      BIGINT       NOT NULL,
    `答案`          JSON         NULL COMMENT '{"题目编号":"选项键",...}',
    `维度得分`      JSON         NULL COMMENT '{维度:{score,max,count,pct}}',
    `总分`          DECIMAL(8,1) NULL,
    `满分`          DECIMAL(8,1) NULL,
    `复合能力`      JSON         NULL COMMENT '{professional_skills,learning_ability,...} 0-100',
    `引擎版本`      VARCHAR(20)  NOT NULL DEFAULT 'assessment-v1',
    `创建时间`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`编号`),
    KEY idx_student (`租户编号`, `学生编号`),
    KEY idx_created (`创建时间`),
    CONSTRAINT fk_assess_student FOREIGN KEY (`学生编号`) REFERENCES `学生` (`编号`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='软技能测评结果（引擎计分）';

-- 验收：
--   SHOW TABLES LIKE '测评%';
--   共 2 张表

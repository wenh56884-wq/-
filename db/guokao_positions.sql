-- db/guokao_positions.sql
-- 国考职位表（国家公务员局《招考简章》逐职位明细，年度更新）
-- 全中文命名：表名与字段名一律中文，标识符用反引号包裹。
--
-- 设计原则（与 recruit_tables.sql 一致）：
--   1. 每条职位都带年度、来源、官方专题链接，可逐条回溯到官方《招考简章》；
--   2. 用 (租户编号, 年度, 部门代码, 职位代码) 做唯一键：同一职位抓多次只入库一次；
--   3. 字段原样入库，不推断、不补全；源表空值就留 NULL（缺失不冒充）；
--   4. 只做增量 upsert，不 TRUNCATE，历年职位可并存查询。

CREATE TABLE IF NOT EXISTS `国考职位` (
  `编号`            BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`        INT          NOT NULL DEFAULT 1,
  `年度`            SMALLINT     NOT NULL COMMENT '考试年度，如 2027',
  `来源`            VARCHAR(40)  NOT NULL DEFAULT 'scs-gk' COMMENT '来源标识',
  `来源键`          CHAR(32)     NOT NULL COMMENT 'md5(年度|部门代码|职位代码)，幂等用',
  `简章分类`        VARCHAR(100) NULL     COMMENT '《招考简章》sheet 分类，如 中央党群机关',
  `部门代码`        VARCHAR(20)  NOT NULL COMMENT '部门代码（原文）',
  `部门名称`        VARCHAR(200) NOT NULL COMMENT '部门名称（原文）',
  `用人司局`        VARCHAR(200) NULL     COMMENT '用人司局（原文）',
  `机构性质`        VARCHAR(100) NULL     COMMENT '机构性质（原文）',
  `招考职位`        VARCHAR(300) NOT NULL COMMENT '招考职位（原文）',
  `职位属性`        VARCHAR(60)  NULL     COMMENT '职位属性（原文）',
  `职位分布`        VARCHAR(60)  NULL     COMMENT '职位分布（原文）',
  `职位简介`        TEXT         NULL     COMMENT '职位简介（原文）',
  `职位代码`        VARCHAR(30)  NOT NULL COMMENT '职位代码（原文）',
  `机构层级`        VARCHAR(60)  NULL     COMMENT '机构层级（原文）',
  `考试类别`        VARCHAR(200) NULL     COMMENT '考试类别（原文）',
  `招考人数`        INT          NULL     COMMENT '招考人数（原文）',
  `专业`            TEXT         NULL     COMMENT '专业要求（原文）',
  `学历`            VARCHAR(120) NULL     COMMENT '学历要求（原文）',
  `学位`            VARCHAR(120) NULL     COMMENT '学位要求（原文）',
  `政治面貌`        VARCHAR(120) NULL     COMMENT '政治面貌要求（原文）',
  `基层工作最低年限` VARCHAR(50)  NULL     COMMENT '基层工作最低年限（原文）',
  `服务基层项目工作经历` VARCHAR(200) NULL COMMENT '服务基层项目工作经历（原文）',
  `是否组织专业能力测试` VARCHAR(10) NULL COMMENT '是否在面试阶段组织专业能力测试（原文）',
  `面试人员比例`    VARCHAR(20)  NULL     COMMENT '面试人员比例（原文）',
  `工作地点`        VARCHAR(200) NULL     COMMENT '工作地点（原文）',
  `落户地点`        VARCHAR(200) NULL     COMMENT '落户地点（原文）',
  `备注`            TEXT         NULL     COMMENT '备注（原文）',
  `部门网站`        VARCHAR(300) NULL     COMMENT '部门网站（原文）',
  `咨询电话1`       VARCHAR(60)  NULL     COMMENT '咨询电话1（原文）',
  `咨询电话2`       VARCHAR(60)  NULL     COMMENT '咨询电话2（原文）',
  `咨询电话3`       VARCHAR(60)  NULL     COMMENT '咨询电话3（原文）',
  `公告链接`        VARCHAR(500) NULL     COMMENT '官方专题链接（可点开核对）',
  `数据文件`        VARCHAR(300) NULL     COMMENT '入库来源文件名',
  `首次发现时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  `最近发现时间`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_gk_position (`租户编号`, `年度`, `部门代码`, `职位代码`),
  KEY idx_gk_year (`年度`),
  KEY idx_gk_dept (`部门名称`),
  KEY idx_gk_edu (`学历`),
  KEY idx_gk_place (`工作地点`),
  KEY idx_gk_political (`政治面貌`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国考职位表（年度增量）';

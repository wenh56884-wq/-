-- ============================================================
-- 启航 DuckDB 分析库 schema（D:/qihang/data/analytics.duckdb）
-- 全中文命名：表名与字段名一律中文，标识符用双引号包裹。
--   兼容约定：查询侧统一用 "中文字段" AS 英文别名，
--   使 Python 取值、接口契约、前端字段保持既有英文键不变。
-- 幂等：全部 CREATE TABLE IF NOT EXISTS
-- DuckDB 不支持 ENUM，用 VARCHAR + CHECK 代替
-- ============================================================

-- -----------------------------------------------------------
-- 1. 学生特征 —— 学生特征宽表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS "学生特征" (
    "学号"              VARCHAR(40)   NOT NULL,
    "学期"              VARCHAR(20)   NOT NULL,
    "绩点"              DECIMAL(5,2),
    "绩点趋势"          DECIMAL(5,2),  -- 本学期 − 上学期：正数 = 进步
    "是否骤降"          BOOLEAN,       -- 绩点趋势 <= -30：界面据此加红色警示
    "挂科数"            INTEGER,
    "班级排名比例"      DECIMAL(5,4),  -- 按班级分组：0=班级第一，1=班级末位
    "专业排名比例"      DECIMAL(5,4),  -- 按专业分组：0=专业第一，1=专业末位
    "出勤率"            DECIMAL(5,4),
    "到馆次数"          INTEGER,       -- 原始到馆/借阅次数
    "图书馆活跃度"      DECIMAL(5,4),  -- 0-1 归一值 = min(1, cnt/60)
    "消费规律性"        DECIMAL(5,4),
    "课程偏好"          JSON,
    "岗位浏览数"        INTEGER,
    "岗位收藏数"        INTEGER,
    "证书数"            INTEGER,
    "竞赛数"            INTEGER,
    "项目数"            INTEGER,
    "标签"              JSON,
    "计算版本"          VARCHAR(20)   NOT NULL,
    "更新时间"          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("学号", "学期")
);

-- -----------------------------------------------------------
-- 2. 岗位特征 —— 岗位特征宽表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS "岗位特征" (
    "岗位名称"    VARCHAR(200)  NOT NULL,
    "城市"        VARCHAR(60),
    "最低薪资"    DECIMAL(8,2),
    "最高薪资"    DECIMAL(8,2),
    "学历"        VARCHAR(20),
    "最低经验"    SMALLINT,
    "最高经验"    SMALLINT,
    "技能标签"    JSON,
    "来源"        VARCHAR(40)   NOT NULL,
    "计算版本"    VARCHAR(20)   NOT NULL,
    "更新时间"    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 3. 推荐日志 —— 推荐日志（每次推荐留痕）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS "推荐日志" (
    "编号"        BIGINT        NOT NULL,
    "学号"        VARCHAR(40)   NOT NULL,
    "岗位编号"    BIGINT        NOT NULL,
    "内容得分"    DECIMAL(5,4),
    "协同得分"    DECIMAL(5,4),
    "最终得分"    DECIMAL(5,4),
    "命中项"      JSON,
    "缺口项"      JSON,
    "建议"        TEXT,
    "引擎版本"    VARCHAR(20)   NOT NULL,
    "创建时间"    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("编号")
);

-- ================================================================
-- RAG 知识库 / 多轮对话记忆 / 工作流（阶段L）
-- 目的：让对话助手从「只有校园数据工具」扩成「能读企业文档、能记住上下文、
--       能查网上、能按流程自动办事」的助手，同时不放宽防幻觉红线。
-- 设计要点：
--   1. 每块文本都必须挂在某份文档上，检索结果一律带「文档名 + 页码/块号」，
--      回答里的引用编号必须能回溯到真实分块，回不去就不算通过。
--   2. 内容哈希唯一：同一份文件重复上传不重复入库，也不产生重复引用。
--   3. 对话消息落库而不是只靠前端传：关掉页面再打开还能接着聊，
--      摘要字段给「超长会话」做压缩，避免把整段历史塞进 prompt。
--   4. 工作流只允许白名单工具、顺序执行、逐步留痕；失败即停并记录原因，
--      不做任何「猜一个结果继续跑」的兜底。
-- ================================================================

-- 1. 知识库文档 ---------------------------------------------------
CREATE TABLE IF NOT EXISTS `知识库文档` (
  `编号`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`    INT           NOT NULL,
  `标题`        VARCHAR(200)  NOT NULL COMMENT '展示名，默认取文件名（不含扩展名）',
  `文件名`      VARCHAR(255)  NULL COMMENT '原始文件名；手工粘贴/URL 导入时可为空',
  `来源类型`    ENUM('pdf','docx','md','txt','url') NOT NULL,
  `来源地址`    VARCHAR(500)  NULL COMMENT 'url 类型才有，用于回源核对',
  `内容哈希`    CHAR(64)      NOT NULL COMMENT 'SHA-256：防重复入库',
  `字节数`      INT           NOT NULL DEFAULT 0,
  `页数`        INT           NOT NULL DEFAULT 0 COMMENT 'PDF 为真实页数，其它为 0',
  `分块数`      INT           NOT NULL DEFAULT 0,
  `状态`        ENUM('ready','failed','disabled') NOT NULL DEFAULT 'ready',
  `失败原因`    VARCHAR(300)  NULL,
  `上传人角色`  VARCHAR(20)   NULL,
  `上传人编号`  BIGINT        NULL,
  `创建时间`    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uk_doc_hash` (`租户编号`, `内容哈希`),
  KEY `idx_doc_tenant` (`租户编号`, `状态`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业知识库文档主表';

-- 2. 知识库分块 ---------------------------------------------------
CREATE TABLE IF NOT EXISTS `知识库分块` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `文档编号`  BIGINT       NOT NULL,
  `块号`      INT          NOT NULL COMMENT '文档内从 1 开始的连续序号',
  `页码`      INT          NULL COMMENT 'PDF 页码；其它类型为 NULL',
  `文本`      MEDIUMTEXT   NOT NULL COMMENT '原文片段，不做任何改写',
  `字数`      INT          NOT NULL DEFAULT 0,
  `关键词`    JSON         NULL COMMENT '切块时抽出的高频词，供检索加权与解释命中',
  UNIQUE KEY `uk_doc_chunk` (`文档编号`, `块号`),
  KEY `idx_chunk_doc` (`文档编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库分块（检索的最小单位，引用可回溯到这一级）';

-- 3. 对话会话 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `对话会话` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`  INT          NOT NULL,
  `角色`      VARCHAR(20)  NOT NULL COMMENT 'student / teacher',
  `主体编号`  BIGINT       NOT NULL COMMENT '学生编号或教师编号',
  `标题`      VARCHAR(200) NOT NULL DEFAULT '新对话' COMMENT '首轮提问自动截取',
  `摘要`      VARCHAR(1000) NULL COMMENT '超长会话的规则摘要（不含任何模型编造内容）',
  `消息数`    INT          NOT NULL DEFAULT 0,
  `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `最近时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_sess_owner` (`租户编号`, `角色`, `主体编号`, `最近时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话（多轮记忆的容器）';

-- 4. 对话消息 -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `对话消息` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `会话编号`  BIGINT       NOT NULL,
  `角色`      ENUM('user','assistant') NOT NULL,
  `内容`      MEDIUMTEXT   NOT NULL,
  `工具`      VARCHAR(40)  NULL COMMENT '本轮命中的工具/能力名，如 kb_search',
  `引用`      JSON         NULL COMMENT '引用清单：[{doc_id,title,page,chunk_no,score}]',
  `追踪号`    VARCHAR(40)  NULL,
  `是否降级`  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=走了降级话术（不含数值/不含检索内容）',
  `耗时毫秒`  INT          NULL,
  `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_msg_session` (`会话编号`, `编号`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息（含引用留痕，便于事后核对）';

-- 5. 工作流定义 ---------------------------------------------------
CREATE TABLE IF NOT EXISTS `工作流定义` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `租户编号`  INT          NOT NULL,
  `名称`      VARCHAR(120) NOT NULL,
  `描述`      VARCHAR(500) NULL,
  `步骤`      JSON         NOT NULL COMMENT '[{id,tool,args,title}]；tool 必须在白名单内',
  `是否启用`  TINYINT(1)   NOT NULL DEFAULT 1,
  `创建人`    VARCHAR(40)  NULL,
  `创建时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uk_wf_name` (`租户编号`, `名称`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工作流定义（步骤只允许调用白名单工具）';

-- 6. 工作流运行 ---------------------------------------------------
CREATE TABLE IF NOT EXISTS `工作流运行` (
  `编号`      BIGINT AUTO_INCREMENT PRIMARY KEY,
  `定义编号`  BIGINT       NOT NULL,
  `触发角色`  VARCHAR(20)  NOT NULL,
  `触发人编号` BIGINT      NULL,
  `入参`      JSON         NULL,
  `状态`      ENUM('running','success','failed') NOT NULL DEFAULT 'running',
  `步骤结果`  JSON         NULL COMMENT '[{id,tool,status,output_digest,elapsed_ms,error}]',
  `错误`      VARCHAR(300) NULL,
  `耗时毫秒`  INT          NULL,
  `开始时间`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `结束时间`  DATETIME     NULL,
  KEY `idx_run_def` (`定义编号`, `开始时间`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工作流运行记录（逐步留痕，失败即停）';

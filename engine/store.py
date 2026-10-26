# engine/store.py
# 职责：存储抽象——DuckDBStore（分析层）/ MySQLStore（业务层），多租户隔离在查询层
# 依赖：duckdb / pymysql / app.config
# TODO: P2/P5 阶段实现 Store 接口与 DuckDBStore 实现

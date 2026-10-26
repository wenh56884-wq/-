# app/auth.py
# 职责：JWT 解析与身份注入，student_id / teacher_id 只能从此模块获取
# 依赖：app.config（读取 JWT_SECRET / JWT_EXPIRE_MINUTES）
# TODO: P7 阶段实现 JWT 编解码与 Depends 注入

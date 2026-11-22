# 启航系统 · 生产镜像
# 基线与本机开发环境一致：Python 3.12
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8

WORKDIR /app

# curl 供容器健康检查；libgomp1 是 scikit-learn 的运行时依赖；tzdata 供时区
# 换腾讯云内网源：直连 deb.debian.org 实测单次 update 要 11 分钟
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        curl tzdata libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖再拷代码：代码改动不会击穿依赖层缓存
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com \
    && pip install --no-cache-dir -r requirements.txt

# 业务代码
COPY app ./app
COPY agents ./agents
COPY engine ./engine
COPY etl ./etl
COPY features ./features
COPY rules ./rules
COPY db ./db
COPY scripts ./scripts
COPY pytest.ini .

# 前端已构建产物（Vue SPA，由 FastAPI 直接托管）
COPY web/dist ./web/dist

# 运行时目录：data 与 logs 由 compose 挂载，这里先建好并给非 root 用户权限
RUN mkdir -p /app/data /app/logs \
    && useradd -m -u 10001 qihang \
    && chown -R qihang:qihang /app/data /app/logs

USER qihang

EXPOSE 8000

# 单 worker：LangGraph + DuckDB 是进程内状态，多 worker 会让内存翻倍并抢 DuckDB 文件锁
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

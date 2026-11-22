#!/usr/bin/env bash
# 启航系统 · 服务器端部署（不依赖 docker compose，纯 docker run）
# 目标机型：2C2G TencentOS 4
set -euo pipefail

APP_DIR=/opt/qihang
cd "$APP_DIR"

log()  { printf '\n\033[1;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '\n\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }
step="${1:-all}"

# ---------------------------------------------------------------- 1. 构建镜像
if [ "$step" = "all" ] || [ "$step" = "build" ]; then
    log "构建应用镜像（首次约 5-10 分钟，2G 机器靠 swap 慢慢装）"
    docker build -t qihang-app:latest "$APP_DIR"
fi

# ---------------------------------------------------------------- 2. MySQL
if [ "$step" = "all" ] || [ "$step" = "db" ]; then
    docker network inspect qihang-net >/dev/null 2>&1 || docker network create qihang-net

    if ! docker ps -a --format '{{.Names}}' | grep -qx qihang-mysql; then
        log "启动 MySQL 8（128M 缓冲池，关 performance_schema 省内存）"
        # --network-alias mysql：应用配置里 MYSQL_HOST=mysql，靠这个别名解析
        docker run -d --name qihang-mysql \
            --restart always \
            --network qihang-net \
            --network-alias mysql \
            -e MYSQL_ROOT_PASSWORD=qihang_root_2026 \
            -e MYSQL_DATABASE=qihang \
            -e TZ=Asia/Shanghai \
            -v qihang-mysql-data:/var/lib/mysql \
            mysql:8.0 \
            --character-set-server=utf8mb4 \
            --collation-server=utf8mb4_unicode_ci \
            --innodb-buffer-pool-size=128M \
            --performance-schema=OFF \
            --max-connections=100 \
            --skip-name-resolve
    else
        docker start qihang-mysql >/dev/null 2>&1 || true
    fi

    log "等待 MySQL 就绪"
    for i in $(seq 1 90); do
        if docker exec qihang-mysql mysqladmin ping -uroot -pqihang_root_2026 --silent >/dev/null 2>&1; then
            echo "  就绪（约 $((i*2)) 秒）"; break
        fi
        [ "$i" -eq 90 ] && { docker logs qihang-mysql --tail 40; die "MySQL 启动超时"; }
        sleep 2
    done

    TABLES=$(docker exec qihang-mysql mysql -uroot -pqihang_root_2026 -N -B \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='qihang'" 2>/dev/null | tr -d '\r')
    echo "  现有表数：${TABLES:-0}"

    if [ "${TABLES:-0}" -lt 20 ]; then
        log "导入业务数据（130 万行）"
        gunzip -c deploy/qihang.sql.gz \
            | docker exec -i qihang-mysql mysql -uroot -pqihang_root_2026 --default-character-set=utf8mb4
        TABLES=$(docker exec qihang-mysql mysql -uroot -pqihang_root_2026 -N -B \
            -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='qihang'" | tr -d '\r')
        ROWS=$(docker exec qihang-mysql mysql -uroot -pqihang_root_2026 -N -B \
            -e "SELECT SUM(table_rows) FROM information_schema.tables WHERE table_schema='qihang'" | tr -d '\r')
        echo "  导入完成：${TABLES} 张表，约 ${ROWS} 行"
        [ "$TABLES" -lt 20 ] && die "表数量异常，检查 dump"
    else
        log "数据已存在，跳过导入"
    fi
fi

# ---------------------------------------------------------------- 3. 应用
if [ "$step" = "all" ] || [ "$step" = "app" ]; then
    docker rm -f qihang-app >/dev/null 2>&1 || true
    # 容器内以 uid 10001 运行，挂载目录必须归它所有，否则写日志直接 PermissionError
    chown -R 10001:10001 "$APP_DIR/logs" "$APP_DIR/data"
    log "启动应用容器（80 → 8000）"
    docker run -d --name qihang-app \
        --restart always \
        --network qihang-net \
        --env-file "$APP_DIR/.env.production" \
        -e MYSQL_HOST=mysql \
        -e MYSQL_PORT=3306 \
        -v "$APP_DIR/data:/app/data" \
        -v "$APP_DIR/logs:/app/logs" \
        -p 80:8000 \
        qihang-app:latest

    log "等待应用就绪"
    for i in $(seq 1 90); do
        if curl -fsS --max-time 3 http://127.0.0.1/health >/dev/null 2>&1; then
            echo "  就绪（约 $((i*2)) 秒）"; break
        fi
        [ "$i" -eq 90 ] && { docker logs qihang-app --tail 60; die "应用启动超时"; }
        sleep 2
    done
fi

# ---------------------------------------------------------------- 4. 验收
log "健康检查"
curl -sS http://127.0.0.1/health; echo
echo "  GET  /            -> $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)"
echo "  POST /auth/login  -> $(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
        -H 'Content-Type: application/json' -d '{"role":"teacher","account":"T001","password":"123456h"}')"
echo ""
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo ""
free -m | head -3
printf '\n\033[1;32m部署完成\033[0m  http://101.34.254.115/\n'

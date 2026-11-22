#!/usr/bin/env bash
# 启航系统 · 云服务器一键部署
# 用法：sudo bash deploy.sh
# 幂等：重复执行只会重建应用镜像，不会重复导入数据
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/qihang}"
cd "$APP_DIR"

log() { printf '\n\033[1;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 或 sudo 执行"

# ---------------------------------------------------------------- 1. 系统体检
log "系统信息"
. /etc/os-release 2>/dev/null || true
echo "  发行版 : ${PRETTY_NAME:-unknown}"
echo "  内核   : $(uname -r)"
MEM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
echo "  内存   : ${MEM_MB} MB"
echo "  磁盘   : ${DISK_GB} GB 可用"

# 内存小于 4G 时补 swap：MySQL + Python 同时跑，没有 swap 容易被 OOM Killer 打死
if [ "$MEM_MB" -lt 4096 ] && [ ! -f /swapfile ]; then
    log "内存 ${MEM_MB}MB < 4G，创建 2G swap"
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=10 >/dev/null
fi

# ---------------------------------------------------------------- 2. Docker
if ! command -v docker >/dev/null 2>&1; then
    log "安装 Docker"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        apt-get install -y ca-certificates curl gnupg
        install -m 0755 -d /etc/apt/keyrings
        # 腾讯云内网镜像优先，拉不动再回退官方源
        if curl -fsSL --max-time 20 https://mirrors.cloud.tencent.com/docker-ce/linux/ubuntu/gpg \
             -o /etc/apt/keyrings/docker.asc 2>/dev/null; then
            chmod a+r /etc/apt/keyrings/docker.asc
            CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.cloud.tencent.com/docker-ce/linux/ubuntu $CODENAME stable" \
                > /etc/apt/sources.list.d/docker.list
            apt-get update -y
            apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        else
            curl -fsSL https://get.docker.com | sh
        fi
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y dnf-plugins-core
        dnf config-manager --add-repo https://mirrors.cloud.tencent.com/docker-ce/linux/centos/docker-ce.repo
        dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    elif command -v yum >/dev/null 2>&1; then
        yum install -y yum-utils
        yum-config-manager --add-repo https://mirrors.cloud.tencent.com/docker-ce/linux/centos/docker-ce.repo
        yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    else
        die "无法识别的包管理器，请手动安装 Docker"
    fi
fi

systemctl enable --now docker >/dev/null 2>&1 || service docker start || true

# 国内加速：拉 python/mysql 官方镜像经常超时
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": ["https://mirror.ccs.tencentyun.com"],
  "log-driver": "json-file",
  "log-opts": { "max-size": "30m", "max-file": "3" }
}
JSON
    systemctl restart docker || true
    sleep 3
fi

docker --version
docker compose version || die "缺少 docker compose 插件"

# ---------------------------------------------------------------- 3. 端口自检
log "检查 80 端口占用"
if ss -lntp 2>/dev/null | grep -q ':80 '; then
    OCCUPIED=$(ss -lntp 2>/dev/null | awk '$4 ~ /:80$/ {print $6}' | head -1)
    warn "80 端口已被占用：${OCCUPIED}"
    warn "若是 nginx，请先停止：systemctl stop nginx  （后文会给出反代方案）"
    die "请释放 80 端口后重跑本脚本"
fi

# ---------------------------------------------------------------- 4. 构建启动
log "构建并启动容器（首次构建约 3-8 分钟）"
docker compose pull mysql
docker compose build app
docker compose up -d

log "等待 MySQL 就绪"
for i in $(seq 1 60); do
    if docker exec qihang-mysql mysqladmin ping -h 127.0.0.1 -uroot -pqihang_root_2026 --silent >/dev/null 2>&1; then
        echo "  MySQL 已就绪（${i}0s 内）"
        break
    fi
    [ "$i" -eq 60 ] && die "MySQL 启动超时，查看：docker logs qihang-mysql --tail 50"
    sleep 2
done

# ---------------------------------------------------------------- 5. 导入数据
log "检查业务数据"
TABLE_COUNT=$(docker exec qihang-mysql mysql -uroot -pqihang_root_2026 -N -B \
    -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='qihang'" 2>/dev/null | tr -d '\r')
echo "  当前 qihang 库表数：${TABLE_COUNT:-0}"

if [ "${TABLE_COUNT:-0}" -lt 5 ]; then
    [ -f deploy/qihang.sql.gz ] && SQL=deploy/qihang.sql.gz
    [ -f deploy/qihang.sql ] && SQL=deploy/qihang.sql
    [ -z "${SQL:-}" ] && die "找不到 deploy/qihang.sql，数据未上传"

    log "导入数据：$SQL（130 万行，约 1-3 分钟）"
    case "$SQL" in
        *.gz) gunzip -c "$SQL" | docker exec -i qihang-mysql mysql -uroot -pqihang_root_2026 --default-character-set=utf8mb4 ;;
        *)    docker exec -i qihang-mysql mysql -uroot -pqihang_root_2026 --default-character-set=utf8mb4 < "$SQL" ;;
    esac
    NEW_COUNT=$(docker exec qihang-mysql mysql -uroot -pqihang_root_2026 -N -B \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='qihang'" | tr -d '\r')
    echo "  导入后表数：${NEW_COUNT}"
    [ "$NEW_COUNT" -lt 20 ] && die "导入后表数量异常，检查 dump 完整性"
else
    log "数据已存在（${TABLE_COUNT} 张表），跳过导入"
fi

# ---------------------------------------------------------------- 6. 重启应用
log "重启应用容器（让它连上新导入的数据）"
docker compose restart app
for i in $(seq 1 60); do
    if docker exec qihang-app curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    [ "$i" -eq 60 ] && { docker logs qihang-app --tail 60; die "应用启动超时"; }
    sleep 2
done

# ---------------------------------------------------------------- 7. 验收
log "健康检查"
docker exec qihang-app curl -sS http://127.0.0.1:8000/health; echo
log "首页与登录接口"
code_home=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)
code_login=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"role":"teacher","account":"T001","password":"123456h"}')
echo "  GET  /          -> $code_home"
echo "  POST /auth/login -> $code_login"

PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me || echo "<服务器公网IP>")
printf '\n\033[1;32m部署完成\033[0m\n'
echo "  访问地址 : http://${PUBLIC_IP}/"
echo "  演示账号 : 教师 T001 / 学生 AI20260001、AI20230001，统一口令 123456h"
echo "  容器状态 : docker compose ps"
echo "  实时日志 : docker compose logs -f app"
echo ""
echo "  若外网打不开，去腾讯云控制台 → 安全组 → 放行 80 端口（入站 TCP:80）"

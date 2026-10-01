#!/usr/bin/env bash
# 10-postgres.sh —— 安装并调优 PostgreSQL，建库建用户
#
# ⚠️ 跑之前先改下面的密码
#
# 用法：sudo bash 10-postgres.sh
set -euo pipefail

DB_NAME=miniflux
DB_USER=miniflux
DB_PASS='CHANGE_ME_PASSWORD'          # ← 改这里，并同步改 /etc/miniflux.conf
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "请用 root / sudo 运行"; exit 1; }

# ---------- 安装 ----------
log "安装 PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq postgresql postgresql-contrib

PG_VER=$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1)
[ -n "$PG_VER" ] || { echo "找不到 PostgreSQL 配置目录"; exit 1; }
PG_CONF_DIR="/etc/postgresql/${PG_VER}/main"
echo "  版本 $PG_VER  配置 $PG_CONF_DIR"

# ---------- 调优 ----------
log "应用调优配置"
mkdir -p "${PG_CONF_DIR}/conf.d"
cp "$HERE/postgresql-tuning.conf" "${PG_CONF_DIR}/conf.d/99-miniflux-tune.conf"

# 确保 postgresql.conf 有 include conf.d（Debian 默认有，保险起见补一次）
if ! grep -qE "^[[:space:]]*include_dir[[:space:]]*=[[:space:]]*'conf.d'" "${PG_CONF_DIR}/postgresql.conf"; then
    echo "include_dir = 'conf.d'" >> "${PG_CONF_DIR}/postgresql.conf"
fi
# 只听本机（不暴露到公网）
sed -i "s/^#\?listen_addresses.*/listen_addresses = '127.0.0.1'/" "${PG_CONF_DIR}/postgresql.conf"

systemctl restart postgresql
sleep 3

# ---------- 建库建用户 ----------
log "建库建用户"
if su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1; then
    echo "  用户已存在，改密码"
    su postgres -c "psql -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""
else
    su postgres -c "psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""
fi

if su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1; then
    echo "  库已存在"
else
    su postgres -c "createdb -O ${DB_USER} ${DB_NAME}"
fi

# ---------- 校验 ----------
log "校验实际生效的配置"
su postgres -c "psql -tAc 'SHOW shared_buffers; SHOW work_mem; SHOW max_connections;'" | sed 's/^/  /'

log "PG 实际内存占用"
ps -o rss= -C postgres 2>/dev/null | awk '{s+=$1} END{printf "  所有 postgres 进程 RSS 合计: %.1f MB\n", s/1024}'

cat <<'EOF'

下一步：
  1. 确认 /etc/miniflux.conf 里的 DATABASE_URL 密码与本脚本一致
  2. 跑 20-miniflux.sh

⚠️ 内存压制是否到位，以 ps 实测为准：
   ps -o rss= -C postgres | awk '{s+=$1} END{print s/1024" MB"}'
   本脚本给的 52MB 是按 PG 内存模型推算（16 + 5x5 + 8 + 约12），未在目标机实测。
EOF

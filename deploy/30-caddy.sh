#!/usr/bin/env bash
# 30-caddy.sh —— 安装 Caddy 并配置反代
#
# 用法：sudo bash 30-caddy.sh <你的域名>
#   例：sudo bash 30-caddy.sh miniflux.example.com
set -euo pipefail

DOMAIN="${1:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "请用 root / sudo 运行"; exit 1; }
[ -n "$DOMAIN" ] || { echo "用法: sudo bash $0 <域名>"; exit 1; }

# ---------- 安装 ----------
log "安装 Caddy（官方源）"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
apt-get update -qq
apt-get install -y -qq caddy

# ---------- 配置 ----------
log "写 Caddyfile（域名 $DOMAIN）"
mkdir -p /var/www/feeds /var/log/caddy
sed "s/miniflux\.example\.com/${DOMAIN}/" "$HERE/Caddyfile" > /etc/caddy/Caddyfile

# caddy 需要能读 feed 目录
chown -R caddy:caddy /var/www/feeds /var/log/caddy 2>/dev/null || true
chmod 755 /var/www/feeds

# ---------- 启动 ----------
log "启动 Caddy"
systemctl enable --now caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy
sleep 5

if systemctl is-active --quiet caddy; then
    echo "  caddy: active"
else
    echo "  启动失败："
    journalctl -u caddy -n 40 --no-pager
    exit 1
fi

log "证书状态（首次可能要等十几秒）"
journalctl -u caddy -n 20 --no-pager | grep -iE "certificate|obtain|tls" | tail -5 || true

cat <<EOF

自检：
  curl -I https://${DOMAIN}/                     # 应返回 Miniflux 的 200/302
  curl -I https://${DOMAIN}/feeds/aihot-selected.xml   # 生成 feed 后应返回 200

⚠️ 若外网访问不了，检查两层（缺一不可）：
  1. OCI 控制台 VCN → Security List / NSG 放行 TCP 80,443
  2. 实例内 iptables（00-prereqs.sh 已处理）
EOF

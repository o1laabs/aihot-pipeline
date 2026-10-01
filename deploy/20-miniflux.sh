#!/usr/bin/env bash
# 20-miniflux.sh —— 安装 Miniflux（官方 deb）
#
# 流程：下载 deb → 校验 → 装 → 写 /etc/miniflux.conf → 起服务
# 用法：sudo bash 20-miniflux.sh
set -euo pipefail

MF_VERSION="${MF_VERSION:-2.3.3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"

log() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "请用 root / sudo 运行"; exit 1; }

ARCH=$(dpkg --print-architecture)
case "$ARCH" in
    amd64|arm64|armhf) ;;
    *) echo "不支持的架构: $ARCH"; exit 1 ;;
esac

# ---------- 下载 ----------
log "下载 miniflux ${MF_VERSION} (${ARCH})"
BASE="https://github.com/miniflux/v2/releases/download/${MF_VERSION}"
DEB="miniflux_${MF_VERSION}_${ARCH}.deb"
curl -fsSL --retry 3 -o "$TMP/$DEB" "$BASE/$DEB"
echo "  已下载 $(du -h "$TMP/$DEB" | cut -f1)"

# deb 本身无官方校验文件；架构与版本从包内 control 复核
log "复核包内容"
dpkg-deb -f "$TMP/$DEB" Package Version Architecture | sed 's/^/  /'

# ---------- 安装 ----------
log "安装"
apt-get install -y -qq "$TMP/$DEB" || dpkg -i "$TMP/$DEB" || apt-get -f install -y -qq

# ---------- 配置 ----------
log "写 /etc/miniflux.conf"
if [ -f /etc/miniflux.conf ] && [ ! -f /etc/miniflux.conf.orig ]; then
    cp /etc/miniflux.conf /etc/miniflux.conf.orig
fi
if grep -q 'CHANGE_ME' /etc/miniflux.conf 2>/dev/null; then
    echo "  检测到已有配置（含 CHANGE_ME 占位），保留不覆盖"
    echo "  → 如需重置：cp $HERE/miniflux.conf /etc/miniflux.conf"
else
    cp "$HERE/miniflux.conf" /etc/miniflux.conf
    chmod 640 /etc/miniflux.conf
    chown root:miniflux /etc/miniflux.conf 2>/dev/null || chmod 644 /etc/miniflux.conf
fi

# deb 的 systemd unit 里有 After=postgresql.service
log "启动"
systemctl daemon-reload
systemctl enable --now miniflux

sleep 4
log "状态"
systemctl is-active miniflux && echo "  miniflux: active" || {
    echo "  启动失败，看日志："
    journalctl -u miniflux -n 30 --no-pager
    exit 1
}
ps -o rss= -C miniflux 2>/dev/null | awk '{printf "  miniflux RSS: %.1f MB\n", $1/1024}' || true

cat <<'EOF'

⚠️ 后续必须做（否则跑不起来 / 不安全）：
  1. /etc/miniflux.conf 里把这三处改掉：
       DATABASE_URL 的密码、BASE_URL 的域名、ADMIN_PASSWORD
     然后 systemctl restart miniflux
  2. 如果 CREATE_ADMIN=1 只在库为空时生效；改管理员密码用：
       sudo -u miniflux miniflux -change-password
  3. 对外访问靠 Caddy 反代（跑 30-caddy.sh），不要直接把 8080 暴露公网
EOF
rm -rf "$TMP"

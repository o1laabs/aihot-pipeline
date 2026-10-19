#!/usr/bin/env bash
# 40-aihot-pipeline.sh —— 部署 AIHOT → Miniflux 管线 + 定时任务
#
# 用法：sudo bash 40-aihot-pipeline.sh [域名]
#   域名可省略 —— 会自动从 /etc/caddy/Caddyfile 里读（30-caddy.sh 写的）
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 管线源码目录
DEST=/opt/aihot-pipeline
FEED_DIR=/var/www/feeds
HTML_DIR=/var/www/reports

log() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "请用 root / sudo 运行"; exit 1; }

# ---------- 0. 确定对外域名（报告里的永久链接靠它）----------
DOMAIN="${1:-}"
if [ -z "$DOMAIN" ] && [ -f /etc/caddy/Caddyfile ]; then
    DOMAIN=$(awk '/^[^#[:space:]].*\{/{print $1; exit}' /etc/caddy/Caddyfile \
             | sed 's/{//; s#^https\?://##; s#/$##')
fi
if [ -z "$DOMAIN" ]; then
    echo "无法确定域名。用法: sudo bash $0 <域名>"
    exit 1
fi
BASE_URL="https://${DOMAIN}"
echo "对外域名: $DOMAIN"

# ---------- 1. 落地代码 ----------
log "复制管线到 $DEST"
mkdir -p "$DEST" "$FEED_DIR" "$HTML_DIR"
for f in aihot_api.py aihot2rss.py store.py report.py watch.py md2html.py report_rss.py README.md; do
    [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DEST/"
done
chmod +x "$DEST"/*.py
cp "$SRC/deploy/run.sh" "$DEST/run.sh"
# 把域名写进 run.sh（报告永久链接 + 自引用 feed 靠它）
sed -i "s#^BASE_URL=.*#BASE_URL=\"${BASE_URL}\"#" "$DEST/run.sh"
chmod +x "$DEST/run.sh"
echo "  BASE_URL = $BASE_URL"

# 数据目录（SQLite + 状态文件）与代码分开，方便备份
mkdir -p "$DEST/reports"
echo "  文件："; ls "$DEST" | sed 's/^/    /'

# 管线只用标准库，无需 venv。确认 python3 在
command -v python3 >/dev/null || { echo "缺 python3"; exit 1; }
echo "  python3: $(python3 -V)"

# ---------- 2. systemd 单元 ----------
log "安装 systemd 单元"
install -m 644 "$SRC/deploy/systemd/aihot-sync.service"      /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-sync.timer"        /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-watch.service"     /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-watch.timer"       /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-report@.service"   /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-report-daily.timer"   /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-report-weekly.timer"  /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/aihot-report-monthly.timer" /etc/systemd/system/

systemctl daemon-reload

# ---------- 3. 首次跑一次 ----------
log "首次运行（累积数据 + 生成 feed）"
"$DEST/run.sh" sync || echo "  ! sync 失败（检查网络 / DNS）"

log "生成一次三种报告"
for k in daily weekly monthly; do
    "$DEST/run.sh" "$k" || true
done
# 报告 HTML 要给 Caddy 读
chown -R caddy:caddy "$HTML_DIR" "$FEED_DIR" 2>/dev/null || true
chmod -R a+rX "$HTML_DIR" "$FEED_DIR" 2>/dev/null || true

# ---------- 4. 启用定时器 ----------
log "启用定时器"
systemctl enable --now aihot-sync.timer aihot-watch.timer \
                          aihot-report-daily.timer aihot-report-weekly.timer \
                          aihot-report-monthly.timer
systemctl list-timers 'aihot*' --no-pager | sed 's/^/  /'

# ---------- 5. 结果 ----------
log "产物"
ls -la "$FEED_DIR" | sed 's/^/  /'
echo
ls -la "$DEST/reports" | sed 's/^/  /'

cat <<EOF

完成。接下来在 Miniflux 里订阅三个 feed：

  1. https://${DOMAIN}/feeds/aihot-selected.xml   精选线索（约 20 条/天）
  2. https://${DOMAIN}/feeds/aihot-all.xml        全部线索（量更大）
  3. https://${DOMAIN}/feeds/reports.xml          ★ 日报/周报/月报

  ⚠️ 建议给 1、2 开启 "Fetch original content"
     —— feed 的 link 指向原文，Miniflux 会去抓正文，阅读器里直接看全文。
     ⚠️ 报告 feed(3) 不用开：内容已内嵌。

实时推送：改 /opt/aihot-pipeline/run.sh 里 watch 分支的 --hook，例如
  "$PY" watch.py once --min-score 80 --hook 'curl -d "{body}" ntfy.sh/你的topic'
EOF

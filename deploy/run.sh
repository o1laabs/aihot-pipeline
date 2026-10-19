#!/usr/bin/env bash
# run.sh —— 管线总入口，给 systemd timer 调用
#
# 用法：
#   ./run.sh sync      累积数据 + 重新生成 feed（每 30 分钟）
#   ./run.sh daily     日报 + 更新报告 feed
#   ./run.sh weekly    周报 + 更新报告 feed
#   ./run.sh monthly   月报 + 更新报告 feed
#   ./run.sh publish   只更新报告 feed（HTML + reports.xml）
#   ./run.sh watch     实时轮询 + 推送
set -euo pipefail

PIPE_DIR="${PIPE_DIR:-/opt/aihot-pipeline}"
FEED_DIR="${FEED_DIR:-/var/www/feeds}"     # Caddy 托管：/feeds/*
HTML_DIR="${HTML_DIR:-/var/www/reports}"   # Caddy 托管：/reports/*
# ⚠️ 必须改成你的真实域名（报告里的永久链接靠它）
BASE_URL="${BASE_URL:-https://miniflux.example.com}"
PY="${PY:-/usr/bin/python3}"

cd "$PIPE_DIR"
mkdir -p "$FEED_DIR" "$HTML_DIR" reports

ts() { date '+%Y-%m-%d %H:%M:%S'; }

publish_reports() {
    "$PY" report_rss.py --base-url "$BASE_URL" \
        --out "$FEED_DIR/reports.xml" --html-dir "$HTML_DIR"
    chmod 644 "$FEED_DIR"/*.xml "$HTML_DIR"/*.html 2>/dev/null || true
}

case "${1:-}" in
  sync)
    echo "[$(ts)] store sync"
    "$PY" store.py sync
    echo "[$(ts)] 生成 feed"
    "$PY" aihot2rss.py --mode selected        --out "$FEED_DIR/aihot-selected.xml"
    "$PY" aihot2rss.py --mode all --window 7d --out "$FEED_DIR/aihot-all.xml"
    chmod 644 "$FEED_DIR"/*.xml 2>/dev/null || true
    echo "[$(ts)] done"
    ;;
  daily|weekly|monthly)
    echo "[$(ts)] 报告: $1"
    "$PY" report.py "$1"
    echo "[$(ts)] 更新报告 feed"
    publish_reports
    ;;
  publish)
    publish_reports
    ;;
  watch)
    echo "[$(ts)] watch"
    # 阈值和推送通道按需改；--hook 支持 {title} {body} 占位
    "$PY" watch.py once --min-score 0
    ;;
  *)
    echo "用法: $0 {sync|daily|weekly|monthly|publish|watch}"; exit 2 ;;
esac

#!/usr/bin/env bash
# 00-prereqs.sh —— 系统准备
#
# 干三件事：
#   1. 加 swap（1 GB 机器上的保命措施）
#   2. 关掉不需要的服务，省内存
#   3. 放行 80/443 —— ⚠️ Oracle 实例的 iptables 是独立于云平台安全列表的一层
#
# 用法：sudo bash 00-prereqs.sh
set -euo pipefail

log() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "请用 root / sudo 运行"; exit 1; }

# ---------- 1. swap ----------
log "检查 swap"
if swapon --show | grep -q .; then
    echo "已有 swap，跳过"
    swapon --show
else
    SIZE_MB=$(awk '/MemTotal/{print int($2/1024/2)}' /proc/meminfo)   # 约物理内存的一半
    [ "$SIZE_MB" -lt 1024 ] && SIZE_MB=1024
    [ "$SIZE_MB" -gt 2048 ] && SIZE_MB=2048
    echo "创建 ${SIZE_MB}MB swapfile"
    fallocate -l "${SIZE_MB}M" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count="$SIZE_MB"
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # 尽量少换出：swap 只作 OOM 兜底，不作常规内存
    sysctl -w vm.swappiness=10
    grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
    grep -q '^vm.vfs_cache_pressure' /etc/sysctl.conf || echo 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf
fi

# ---------- 2. 省内存 ----------
log "关闭非必需服务（省内存）"
for svc in snapd apport apt-daily.timer apt-daily-upgrade.timer motd-news.timer \
           unattended-upgrades fwupd.service; do
    if systemctl list-unit-files --type=service,timer 2>/dev/null | grep -q "^${svc}"; then
        systemctl disable --now "$svc" 2>/dev/null || true
        echo "  已停 $svc"
    fi
done
# journald 限制磁盘占用
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size.conf <<'EOF'
[Journal]
SystemMaxUse=100M
RuntimeMaxUse=20M
EOF
systemctl restart systemd-journald 2>/dev/null || true

# ---------- 3. 防火墙 ----------
log "放行 80 / 443"
if command -v ufw >/dev/null && ufw status | grep -qi active; then
    ufw allow 80/tcp
    ufw allow 443/tcp
    echo "  ufw 已放行"
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
    echo "  firewalld 已放行"
else
    echo "  未检测到 active 的 ufw/firewalld，改走 iptables"
fi

# ⚠️ Oracle 的 Ubuntu 镜像自带 iptables 规则（与云平台安全列表是两层独立拦截）
if command -v iptables >/dev/null; then
    for port in 80 443; do
        if ! iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
            # 插在 REJECT 规则之前（OCI 镜像通常在 INPUT 链末尾有 REJECT all）
            line=$(iptables -L INPUT --line-numbers -n | awk '/REJECT|DROP/{print $1; exit}')
            if [ -n "${line:-}" ]; then
                iptables -I INPUT "$line" -p tcp --dport "$port" -j ACCEPT
            else
                iptables -A INPUT -p tcp --dport "$port" -j ACCEPT
            fi
            echo "  iptables 已放行 $port"
        fi
    done
    if command -v netfilter-persistent >/dev/null; then
        netfilter-persistent save
    elif [ -d /etc/iptables ]; then
        iptables-save > /etc/iptables/rules.v4
    fi
fi

warn "别忘了在 OCI 控制台放行 80/443："
warn "  VCN → Security Lists（或 NSG）→ Add Ingress Rule → TCP 80/443, 0.0.0.0/0"
warn "  只配了实例 iptables 而没配云平台，会表现为「本机能访问、外面访问不了」"

log "完成。当前内存："
free -m

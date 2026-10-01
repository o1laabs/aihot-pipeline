# Oracle 免费层部署（AMD 实例：1/8 OCPU + 1 GB）

Miniflux（阅读层）+ AIHOT 管线（供给层）的完整部署方案。

---

## 0. 先纠正一件事：这台机器上不要用 Docker

我在不知道实例规格时推荐过 Docker。**确认是 AMD 1 GB 之后，这个建议要改。**

| | 常驻内存 | 1 GB 机器上 |
|---|---|---|
| **原生部署** | 无额外开销 | ✅ 推荐 |
| **Docker** | dockerd + containerd **约 120–150 MB** | ❌ 相当于白扔 15% 内存 |

在 1 GB 的机器上，Docker 的便利（`pull` 升级）不值这 120 MB。
**本方案的脚本全部走原生安装。**

---

## 1. 一个你可能没注意到的事实：你免费拿 2 台

Oracle 官网原文：

> AMD based Compute VMs with 1/8 OCPU and 1 GB memory each
> **2 AMD based compute VMs**

**是 2 台。** 所以你有这些选择：

| 方案 | 说明 |
|---|---|
| **A. 全部塞一台**（本方案默认） | Miniflux + PG + 管线 常驻约 340 MB，1 GB 够 |
| **B. 拆两台** | 一台跑 Miniflux+PG，另一台跑管线。但管线是 cron 触发、大部分时间空闲，**拆开收益很小** |

**建议 A。** 第二台留着做别的（或当备用）。

⚠️ 但注意：**1/8 OCPU 是 burstable，CPU 基线很低。** 内存能省，CPU 省不了。
这是本方案最大的实际约束 —— 别指望它跑重活。

---

## 2. 内存预算（1 GB 机器）

### 常驻

| 组件 | 内存 | 说明 |
|---|---|---|
| Ubuntu 24.04 minimal | ~200 MB | 已按 00-prereqs.sh 关掉 snapd/apport 等 |
| **PostgreSQL**（调优后） | **~52 MB** | 见 `postgresql-tuning.conf` |
| Miniflux | ~30 MB | Go 单二进制 |
| Caddy | ~25 MB | 反代 + TLS |
| systemd / journald | ~30 MB | journald 已限 100 MB 磁盘 |
| **合计** | **~337 MB** | |
| **剩余** | **~660 MB** | ✅ 宽裕 |

### 突发（瞬时，不常驻）

| 场景 | 峰值 |
|---|---|
| `store.py sync` | ~40 MB |
| `report.py` 生成报告 | ~40 MB |
| `aihot2rss.py` | ~35 MB |

**这些都跑完就释放，不会叠加。**

### ⚠️ 关于那个 52 MB

**这是按 PostgreSQL 内存模型推算的，不是实测值：**

```
shared_buffers 16MB + wal_buffers 1MB
+ 5 连接 × (work_mem 1MB×2 + temp_buffers 1MB + 进程 ~2MB) ≈ 25MB
+ maintenance_work_mem 8MB
+ 后台进程（bgwriter/checkpointer/walwriter）~12MB
≈ 52MB
```

**部署后必须实测确认：**
```bash
ps -o rss= -C postgres | awk '{s+=$1} END{print s/1024" MB"}'
```

---

## 3. 部署步骤

### 前置

- Oracle 上的 Ubuntu 22.04 / 24.04（x86_64）
- 一个域名，DNS A 记录指向实例公网 IP（用于 Caddy 自动 HTTPS）
- 能 sudo

### 上传代码

```bash
# 从你的 Mac
scp -r /var/minis/shared/aihot-pipeline ubuntu@<实例IP>:/tmp/
ssh ubuntu@<实例IP>
sudo mv /tmp/aihot-pipeline /tmp/aihot-src
```

### 按顺序跑

```bash
cd /tmp/aihot-src/deploy

sudo bash 00-prereqs.sh                      # swap + 省内存 + 防火墙
sudo bash 10-postgres.sh                     # ⚠️ 先改脚本里的 DB_PASS
sudo bash 20-miniflux.sh                     # 装 Miniflux
sudo bash 30-caddy.sh miniflux.example.com   # ⚠️ 换成你的域名
sudo bash 40-aihot-pipeline.sh               # 管线 + 定时任务
```

### 跑完必须改的四处

```bash
sudo nano /etc/miniflux.conf
```
1. `DATABASE_URL` 里的密码 → 与 `10-postgres.sh` 的 `DB_PASS` 一致
2. `BASE_URL` → 你的真实域名
3. `ADMIN_PASSWORD` → 改掉（⚠️ 别留着占位符）
4. 确认 `DATABASE_MAX_CONNS=5` 和 `WORKER_POOL_SIZE=2` 在

```bash
sudo systemctl restart miniflux
```

### 在 Miniflux 里订阅

```
https://<你的域名>/feeds/aihot-selected.xml     # 精选，约 20 条/天
https://<你的域名>/feeds/aihot-all.xml          # 全部，量更大
```

⭐ **建议给这两个 feed 开启 "Fetch original content"。**
这样 Miniflux 会去抓原文正文 —— 因为我们的 feed 把 `<link>` 指向了原文，
阅读器里能直接看全文，不用跳出去。

---

## 4. ⚠️ Oracle 的两个网络坑（必看）

**这是 Oracle 免费层最经典的"我明明配好了但访问不了"。**

### 坑 1：云平台 Security List

OCI 的 VCN **默认只开 22 端口**。要在控制台加：

```
Networking → Virtual Cloud Networks → 你的 VCN
  → Security Lists → Default Security List
  → Add Ingress Rules:
       Source CIDR: 0.0.0.0/0
       IP Protocol: TCP
       Destination Port Range: 80,443
```

（如果用 NSG，则在 NSG 里加。）

### 坑 2：实例内 iptables

Oracle 的 Ubuntu 镜像**自带一套 iptables 规则**（末尾有 REJECT），
**和云平台的安全列表是两层独立的拦截。**

`00-prereqs.sh` 已经处理了，但你可以手动核：

```bash
sudo iptables -L INPUT -n --line-numbers | head -20
sudo iptables -I INPUT <REJECT前的行号> -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

**判据：本机 `curl localhost:443` 通、外面不通 → 大概率是云平台没放行。
     本机都不通 → 是实例内 iptables 或服务没起。**

---

## 5. 定时任务一览

装完后自动生效：

| timer | 频率 | 干什么 |
|---|---|---|
| `aihot-sync.timer` | 每 30 分钟 | 累积数据 + 重新生成两个 feed |
| `aihot-watch.timer` | 每 5 分钟 | 轮询新条目 + 推送 |
| `aihot-report-daily.timer` | 每天 09:00 | 日报 |
| `aihot-report-weekly.timer` | 每周一 09:05 | 周报 |
| `aihot-report-monthly.timer` | 每月 1 日 09:10 | 月报 |

查看：
```bash
systemctl list-timers 'aihot*'
journalctl -u aihot-sync -n 30
```

手动触发一次：
```bash
sudo systemctl start aihot-sync.service
```

---

## 6. 实时推送怎么配

编辑 `/opt/aihot-pipeline/run.sh` 的 `watch` 分支：

```bash
"$PY" watch.py once --min-score 80 --hook 'curl -s -d "{body}" ntfy.sh/你的topic'
```

`--min-score` 是阈值（建议 80，避免刷屏）。通道示例：

| 通道 | hook |
|---|---|
| ntfy | `curl -d "{body}" ntfy.sh/your-topic` |
| Telegram | `curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage -d chat_id=<ID> -d text="{body}"` |
| Bark(iOS) | `curl "https://api.day.app/<KEY>/{title}/{body}"` |
| 邮件 | `echo "{body}" \| mail -s "{title}" you@example.com` |

⚠️ **首次运行 `watch.py` 只建立基线、不推送**（避免把 200 条历史一次性刷给你）。
第二次起才推新条目。

---

## 7. 验证清单

```bash
# 1. 服务状态
systemctl is-active postgresql miniflux caddy        # 三个都 active

# 2. PG 内存是否压住
ps -o rss= -C postgres | awk '{s+=$1} END{print s/1024" MB"}'   # 目标 < 60

# 3. 整体内存
free -m                                              # used 应 < 500

# 4. feed 是否可访问
curl -sI https://<域名>/feeds/aihot-selected.xml | head -3      # 200

# 5. feed 的 link 是否指向原文（本方案的核心）
curl -s https://<域名>/feeds/aihot-selected.xml | grep -oP '(?<=<link>)[^<]+' | head -5
#   → 应全部是非 aihot.news 的域名

# 6. 定时器
systemctl list-timers 'aihot*' --no-pager
```

---

## 8. 诚实边界

1. **部署脚本未在目标机实测。** 本沙箱没有 apt / systemd，无法验证
   `00`–`40` 五个脚本的端到端执行。已做的验证：
   - 全部 `bash -n` 语法检查通过
   - `run.sh` 用真实路径**实跑通过**，产出的 feed 经 XML 解析校验
   - `20-miniflux.sh` 依据的是**实际拆开 deb 包**核对的内容结构
     （`/usr/bin/miniflux` + `/etc/miniflux.conf` + systemd unit + `miniflux` 系统用户）
   - 未验证的部分：apt 源可用性、Caddy 证书签发、Oracle iptables 具体行号

2. **那个 ~52 MB 是模型推算，不是实测。**

3. **AIHOT 授权边界：** 个人 / 内部使用免费；
   **对外商业产品、客户交付、公开镜像、转售须书面授权**（wzglyay@virxact.com）。

4. **AIHOT 是发现层，不是事实来源。** 它的 `summary` 是二手转述。
   报告里每条都带原文直链 —— **引用事实前必须点开原文**。

5. **`window` 只有 24h / 7d。** 月报完全依赖本地累积 ——
   **`aihot-sync.timer` 停跑超过 7 天，那段时间的数据就永久缺失了。**

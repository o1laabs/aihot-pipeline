# AIHOT → Miniflux 情报管线

把 [aihot.news](https://aihot.news) 的 AI 圈线索接进自建 RSS 阅读器，
并提供日报 / 周报 / 月报 与实时推送。

## 为什么不能直接把 aihot 官方 feed 丢给 Miniflux

AIHOT 官方 feed 的 `<link>` 指向 `aihot.news/items/<id>` —— **它自己的摘要页**，
不是原文。原文链接藏在 `<description>` 的 `<a href>` 里（实测 6/6 条可提取）。

后果：在 Miniflux 里点进去，看到的是二手转述，**到不了一手来源**。

本管线生成**自建 feed**，把 `<link>` 改成原文直链：

| | 官方 feed | 本管线 feed |
|---|---|---|
| `<link>` | aihot 摘要页 | **原文直链** |
| 摘要 | 有 | 有（内嵌 description） |
| 原文链接 | 藏在 HTML 里 | 直接可点 |

**摘要和原文都要 —— 两者兼得。**

---

## 架构

```
                        aihot.news API（匿名只读，无需 Key）
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
   aihot2rss.py              store.py                  report.py
   （转自建 feed）          （SQLite 累积）           （日报/周报/月报）
        │                         │                         │
        ▼                         ▼                         ▼
   /var/www/feeds/*.xml       aihot.db               reports/*.md
        │                                                    │
        ▼                                                    ▼
    【Miniflux】                                       通知 / 归档
    订阅这两个 feed
                                    watch.py ── 轮询新条目 ──▶ 实时推送
```

### 为什么需要 `store.py`

**AIHOT API 的 `window` 只支持 `24h` 和 `7d`。**
月报要 30 天数据 → **API 给不了**，只能每天落盘累积。
周报同理（7 天边界，跨周就丢）。

所以 `store.py` 不是可选组件，**是月报的前提**。

---

## 四个组件

| 文件 | 作用 | 何时跑 |
|---|---|---|
| `aihot_api.py` | API 客户端（纯标准库，无依赖） | 被其他脚本 import |
| `aihot2rss.py` | AIHOT → 自建 RSS（link 指向原文） | 每 15–30 分钟 |
| `store.py` | SQLite 累积（幂等，重复跑不重复存） | **每天至少一次**（月报前提） |
| `report.py` | 日报 / 周报 / 月报 | 按周期 |
| `watch.py` | 轮询 + 去重 + 实时推送 | 每 5 分钟 |

---

## 部署（Oracle 服务器）

### 1. 生成 feed 并由 Web 服务器暴露

Miniflux 通过 HTTP 抓 feed，所以自建 feed 得能被访问到。
用 Caddy 一起托管最简单（和 Miniflux 共用）：

```bash
# 生成
cd /opt/aihot-pipeline
mkdir -p /var/www/feeds
python3 aihot2rss.py --mode selected --out /var/www/feeds/aihot-selected.xml
python3 aihot2rss.py --mode all --window 7d --out /var/www/feeds/aihot-all.xml
```

Caddyfile 里加一段（和 Miniflux 反代并列）：

```
feeds.example.org {
    root * /var/www/feeds
    file_server
}
```

### 2. Miniflux 里订阅

```
https://feeds.example.org/aihot-selected.xml    # 精选（约 20 条/天）
https://feeds.example.org/aihot-all.xml         # 全部（量更大）
```

**建议在 Miniflux 里对这个 feed 开启 "Fetch original content"** —— 
这样 Miniflux 会去抓原文正文，你在阅读器里能直接看全文。

### 3. 定时任务（systemd timer）

`/etc/systemd/system/aihot.service`：

```ini
[Unit]
Description=AIHOT pipeline tick

[Service]
Type=oneshot
WorkingDirectory=/opt/aihot-pipeline
ExecStart=/bin/sh -c '\
  python3 store.py sync && \
  python3 aihot2rss.py --mode selected --out /var/www/feeds/aihot-selected.xml && \
  python3 aihot2rss.py --mode all --window 7d --out /var/www/feeds/aihot-all.xml'
```

`aihot.timer`（每 30 分钟）：

```ini
[Unit]
Description=AIHOT pipeline every 30min

[Timer]
OnBootSec=3min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

启用：`systemctl enable --now aihot.timer`

### 4. 日报 / 周报 / 月报

```
# 日报：每天 09:00
0 9 * * *  cd /opt/aihot-pipeline && python3 report.py daily

# 周报：每周一 09:00
0 9 * * 1  cd /opt/aihot-pipeline && python3 report.py weekly

# 月报：每月 1 日 09:00
0 9 1 * *  cd /opt/aihot-pipeline && python3 report.py monthly
```

### 5. 实时推送

`aihot-watch.timer`（每 5 分钟）：

```ini
[Unit]
Description=AIHOT realtime watcher

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

ExecStart 用 `python3 watch.py once --min-score 80 --hook '<你的推送命令>'`。

**推送通道**（`--hook` 填任意命令，支持 `{title}` `{body}` 占位）：

| 通道 | 示例 |
|---|---|
| ntfy | `curl -d '{body}' ntfy.sh/your-topic` |
| Telegram | `curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage -d chat_id=<ID> -d text='{body}'` |
| Bark（iOS） | `curl "https://api.day.app/<KEY>/{title}/{body}"` |
| 邮件 | `echo '{body}' \| mail -s '{title}' you@example.com` |

---

## 输出样例

**日报**结构：
1. 当日主线（取自官方 `/api/v1/dailies`）
2. 值得看的 12 条（按 score 排序，附编辑理由）
3. 多方印证（`sourceCount >= 3`，即 ≥3 家独立来源报了同一件事）
4. 分类分布

**周报 / 月报**结构：
1. 总量 + 分类分布（带条形图）
2. 每日产出量趋势
3. 各分类重点（每类前 5，按分数）
4. 产出最多的来源 Top 10

---

## 诚实边界（用之前必须知道）

1. **`summary` 是二手转述。** AIHOT 自己不存全文，摘要由它（或它的 AI）生成。
   **转述链 = 原文 → AIHOT 摘要 → 你，多一跳多一次失真。**
   报告里每条都带原文直链 —— **引用事实前必须点开原文**。

2. **`window` 只有 24h / 7d。** 超过 7 天的数据 API 取不到，
   月报完全依赖本地累积。**不跑 `store.py sync` 就没有月报。**

3. **每日产出量计数受抓取覆盖影响。** 抓取当天拉得更全，当天数字会偏高。
   跨天比较只看趋势。

4. **`category` 在 `mode=all` 里大量为 null。** 严格分类统计请用 `mode=selected`。

5. **授权边界：** 个人 / 内部使用免费；
   **对外商业产品、客户交付、公开镜像、转售须书面授权**（wzglyay@virxact.com）。

6. **本管线不做事实核查。** 它只负责把线索和原文链接送到你面前。
   AIHOT 是**发现层**，不是事实终点。

---

## 部署

完整部署步骤见 **[deploy/README.md](./deploy/README.md)**（面向 Oracle Cloud 免费层 AMD 实例：1/8 OCPU + 1 GB）。

一行速览：

```bash
cd deploy
sudo bash 00-prereqs.sh                      # swap + 省内存 + 防火墙
sudo bash 10-postgres.sh                     # ⚠️ 先改脚本里的 DB_PASS
sudo bash 20-miniflux.sh                     # 装 Miniflux
sudo bash 30-caddy.sh miniflux.example.com   # ⚠️ 换成你的域名
sudo bash 40-aihot-pipeline.sh               # 管线 + 定时任务
```

---

## 快速开始

```bash
python3 store.py sync                      # 累积（首次会拿 7 天）
python3 aihot2rss.py --mode selected --out feed.xml
python3 report.py daily                    # → reports/daily-YYYY-MM-DD.md
python3 report.py weekly
python3 report.py monthly
python3 watch.py once --min-score 80       # 实时（首次建基线不推送）
```

## 依赖

**无。** 全部脚本只用 Python 标准库（`urllib` / `sqlite3` / `xml`），
不需要 pip install，不需要 venv。Python 3.8+ 即可。

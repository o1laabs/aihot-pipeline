#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIHOT 日报 / 周报 / 月报生成器

数据来源有两种，分开用:
  日报  → 官方 /api/v1/dailies（AIHOT 自己编的当日主线）+ 本地库当日高分条目
  周/月报 → 本地库累积（API 只有 24h/7d，30 天必须靠自己攒）

用法:
  python3 report.py daily            # 日报
  python3 report.py weekly           # 周报
  python3 report.py monthly          # 月报
  python3 report.py daily --out /path.md
"""
import argparse, os, sys
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import aihot_api, store  # noqa: E402

CAT = {"ai-models": "模型", "ai-products": "产品", "paper": "论文",
       "industry": "行业", "tip": "技巧", None: "未分类"}

BOUNDARY = ("> ⚠️ 本报告的条目摘要来自 AIHOT（二手聚合），**不是事实来源**。"
            "引用前请点开原文核实。")


def _cat(c):
    return CAT.get(c, c or "未分类")


def _fmt_day(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%m-%d %H:%M")
    except Exception:
        return iso or ""


def _top(rows, n):
    return sorted(rows, key=lambda r: -(r.get("score") or 0))[:n]


def _by_category(rows):
    g = defaultdict(list)
    for r in rows:
        g[r.get("category")].append(r)
    return dict(sorted(g.items(), key=lambda kv: -len(kv[1])))


def daily(out=None):
    now = datetime.now(timezone.utc)
    rows = store.since(days=1)
    L = []
    L.append(f"# AI 日报 · {now.strftime('%Y-%m-%d')}")
    L.append("")
    L.append(BOUNDARY)
    L.append("")

    # 1) 官方日报主线
    try:
        ds = aihot_api.dailies()
        today = ds[0] if ds else None
    except Exception:
        today = None
    if today:
        L.append("## 当日主线")
        L.append("")
        L.append(f"**{today.get('leadTitle','')}**")
        L.append("")
        L.append(today.get("leadParagraph", ""))
        L.append("")
        L.append(f"[AIHOT 日报页]({(today.get('links') or {}).get('aihot','')})")
        L.append("")

    # 2) 当日高分
    L.append(f"## 值得看的 {min(12, len(rows))} 条（按评分）")
    L.append("")
    for r in _top(rows, 12):
        L.append(f"- **[{r['title']}]({r['url_original']})**  <sub>{r.get('score','-')} 分</sub>")
        if r.get("reason"):
            L.append(f"  - {r['reason']}")
    L.append("")

    # 3) 跨源印证
    try:
        hs = aihot_api.hot_topics()
    except Exception:
        hs = []
    multi = [h for h in hs if (h.get("sourceCount") or 0) >= 3]
    if multi:
        L.append("## 多方印证（≥3 家独立来源）")
        L.append("")
        for h in multi:
            L.append(f"- **[{h['title']}]({(h.get('links') or {}).get('original','')})** "
                     f"— {h.get('sourceCount')} 家来源")
        L.append("")

    # 4) 分类分布
    c = Counter(_cat(r.get("category")) for r in rows)
    if c:
        L.append("## 分类分布")
        L.append("")
        L.append(" · ".join(f"{k} {v}" for k, v in c.most_common()))
        L.append("")

    md = "\n".join(L)
    return _emit(md, out, f"daily-{now.strftime('%Y-%m-%d')}.md")


def periodic(days, label, out=None):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    rows = store.between(start.isoformat(), now.isoformat())
    L = []
    L.append(f"# AI {label} · {start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
    L.append("")
    L.append(BOUNDARY)
    L.append("")
    L.append(f"共 **{len(rows)}** 条。")
    L.append("")

    if not rows:
        L.append("_本地库暂无该区间数据。月报需要每天跑 `store.py sync` 累积。_")
        return _emit("\n".join(L), out, f"{label}-{now.strftime('%Y-%m-%d')}.md")

    # 分类分布
    L.append("## 分类分布")
    L.append("")
    c = Counter(_cat(r.get("category")) for r in rows)
    for k, v in c.most_common():
        bar = "█" * max(1, round(v / max(c.values()) * 24))
        L.append(f"- {k:<6} {v:>4}  {bar}")
    L.append("")

    # 分周趋势
    wk = Counter()
    for r in rows:
        try:
            d = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            wk[d.strftime("%m-%d")] += 1
        except Exception:
            pass
    if wk:
        L.append("## 每日产出量")
        L.append("")
        L.append("_⚠️ 该计数受抓取覆盖影响：抓取当天拉得更全，会显得当天产出偏高。_")
        L.append("_跨天比较请只看趋势，不要当精确产量。_")
        L.append("")
        mx = max(wk.values())
        for k in sorted(wk):
            L.append(f"`{k}` {'▇' * max(1, round(wk[k]/mx*30))} {wk[k]}")
        L.append("")

    # 按分类取头名
    L.append(f"## 各分类重点（每类最高分）")
    L.append("")
    for cat, items in _by_category(rows).items():
        top = _top(items, 1)
        if not top:
            continue
        # 该类整体最多来源
        L.append(f"### {_cat(cat)}（{len(items)} 条）")
        L.append("")
        for r in _top(items, 5):
            L.append(f"- **[{r['title']}]({r['url_original']})**"
                     + (f" <sub>{r.get('score')} 分</sub>" if r.get("score") else ""))
        L.append("")

    # 高频来源
    L.append("## 产出最多的来源")
    L.append("")
    for s, n in Counter(r.get("source_name") for r in rows if r.get("source_name")).most_common(10):
        L.append(f"- {s} — {n} 条")
    L.append("")

    return _emit("\n".join(L), out, f"{label}-{now.strftime('%Y-%m-%d')}.md")


def _emit(md, out, default_name):
    if not out:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, default_name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {out} ({len(md)} chars)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["daily", "weekly", "monthly"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.kind == "daily":
        daily(a.out)
    elif a.kind == "weekly":
        periodic(7, "周报", a.out)
    else:
        periodic(30, "月报", a.out)

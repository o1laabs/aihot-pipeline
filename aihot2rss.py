#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIHOT → 自建 RSS 2.0 feed

解决一个具体问题: AIHOT 官方 feed 的 <link> 指向 aihot.news 自己的摘要页，
             不是原文。RSS 阅读器里点进去只能看二手转述。

本转换器生成的 feed:
  <link>             = 原文直链      ← 点进去直达一手来源
  <description>      = 摘要 + 编辑理由 + 两个链接（原文 / AIHOT 页）
  <content:encoded>  = 同样的 HTML 块
  <guid>             = AIHOT item id ← 天然去重，内容更新时 guid 不变

用法:
  python3 aihot2rss.py --mode selected --out feed-selected.xml
  python3 aihot2rss.py --mode all --window 7d --out feed-all.xml
"""
import argparse, html, sys, time
from email.utils import formatdate
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import aihot_api  # noqa: E402

CATEGORY_LABEL = {
    "ai-models": "模型", "ai-products": "产品", "paper": "论文",
    "industry": "行业", "tip": "技巧",
}


def esc(s):
    return html.escape(s or "", quote=True)


def _ts(iso):
    """ISO8601 → RFC822（RSS 要求）"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return formatdate(dt.timestamp(), usegmt=True)
    except Exception:
        return formatdate(time.time(), usegmt=True)


def build(mode="selected", window="24h", limit=50, q=None,
          feed_title=None, self_url="", category=None):
    its, _ = aihot_api.items_all(mode=mode, window=window,
                                 max_items=limit, q=q, category=category)
    title = feed_title or (
        "AIHOT 精选（含摘要+原文直链）" if mode == "selected"
        else "AIHOT 全部（含摘要+原文直链）"
    )
    now = formatdate(time.time(), usegmt=True)

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0"',
           '     xmlns:atom="http://www.w3.org/2005/Atom"',
           '     xmlns:content="http://purl.org/rss/1.0/modules/content/">',
           '<channel>',
           f'  <title>{esc(title)}</title>',
           '  <link>https://aihot.news/</link>',
           f'  <description>AIHOT 线索 → 原文直链。摘要为 AIHOT 二手转述，事实请回原文核实。</description>',
           '  <language>zh-CN</language>',
           f'  <lastBuildDate>{now}</lastBuildDate>',
           '  <generator>minis-aihot2rss</generator>']
    if self_url:
        out.append(f'  <atom:link href="{esc(self_url)}" rel="self" type="application/rss+xml"/>')

    for it in its:
        original = aihot_api.direct_url(it)
        aihot_url = (it.get("links") or {}).get("aihot", "")
        summary = it.get("summary") or ""
        reason = it.get("reason") or ""
        src = (it.get("source") or {}).get("name", "")
        cat = it.get("category") or ""
        cat_label = CATEGORY_LABEL.get(cat, cat)

        body = [f'<p>{esc(summary)}</p>']
        if reason:
            body.append(f'<p><em>为什么值得看：</em>{esc(reason)}</p>')
        links = [f'<a href="{esc(original)}">原文</a>']
        if aihot_url:
            links.append(f'<a href="{esc(aihot_url)}">AIHOT 条目</a>')
        body.append('<p>' + ' · '.join(links) + '</p>')
        if src:
            body.append(f'<p><small>来源：{esc(src)}'
                        + (f' · 分类：{esc(cat_label)}' if cat_label else '')
                        + f' · 评分：{it.get("score", "-")}</small></p>')
        body_html = "\n".join(body)

        out += ['  <item>',
                f'    <title>{esc(it.get("title"))}</title>',
                # ★ 关键：link 指向原文，不是 aihot 页
                f'    <link>{esc(original)}</link>',
                f'    <guid isPermaLink="false">aihot:{esc(it.get("id"))}</guid>',
                f'    <pubDate>{_ts(it.get("publishedAt"))}</pubDate>']
        if cat_label:
            out.append(f'    <category>{esc(cat_label)}</category>')
        out.append(f'    <description><![CDATA[{body_html}]]></description>')
        out.append(f'    <content:encoded><![CDATA[{body_html}]]></content:encoded>')
        # 原文直链另存一份，方便下游脚本不开 CDATA 也能取到
        out.append(f'    <source url="{esc(aihot_url)}">AIHOT</source>')
        out.append('  </item>')

    out += ['</channel>', '</rss>', '']
    return "\n".join(out), len(its)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="selected", choices=["selected", "all"])
    ap.add_argument("--window", default="24h", choices=["24h", "7d"])
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--q", default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    xml, n = build(a.mode, a.window, a.limit, a.q, category=a.category)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"wrote {a.out}: {n} items, {len(xml.encode())} bytes")


if __name__ == "__main__":
    main()

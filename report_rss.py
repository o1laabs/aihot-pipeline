#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 reports/*.md 变成可订阅的 RSS（在 Miniflux 里当普通 feed 读）

做三件事：
  1. 每份 .md 生成同名 .html（Caddy 托管，提供永久链接）
  2. 汇总成 reports.xml（一份报告 = 一个 item）
  3. item 里带完整 HTML，Miniflux 里直接展开读，不必跳转

文件名映射（中文名转 URL 友好）:
  daily-2026-10-01.md   → daily-2026-10-01.html
  周报-2026-10-01.md    → weekly-2026-10-01.html
  月报-2026-10-01.md    → monthly-2026-10-01.html

用法:
  python3 report_rss.py --base-url https://miniflux.example.com
"""
import argparse, html, os, re, sys, time
from datetime import datetime, timezone
from email.utils import formatdate

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from md2html import md_to_html, render_page  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "reports")

# 文件名前缀 → (ascii slug, 中文分类名)
KINDS = [
    ("daily-",   "daily",   "日报"),
    ("周报-",    "weekly",  "周报"),
    ("月报-",    "monthly", "月报"),
    ("weekly-",  "weekly",  "周报"),
    ("monthly-", "monthly", "月报"),
]


def esc(s):
    return html.escape(s or "", quote=True)


def classify(fname):
    """返回 (slug_base, label, date_str) 或 None"""
    stem = fname[:-3] if fname.endswith(".md") else fname
    for prefix, slug, label in KINDS:
        if stem.startswith(prefix):
            date_str = stem[len(prefix):]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                return f"{slug}-{date_str}", label, date_str
    return None


def _rfc822(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=9, tzinfo=timezone.utc)
        return formatdate(dt.timestamp(), usegmt=True)
    except Exception:
        return formatdate(time.time(), usegmt=True)


def build(base_url, out_xml=None, html_dir=None):
    os.makedirs(REPORTS, exist_ok=True)
    if html_dir:
        os.makedirs(html_dir, exist_ok=True)
    entries = []
    for fname in sorted(os.listdir(REPORTS)):
        if not fname.endswith(".md"):
            continue
        info = classify(fname)
        if not info:
            continue
        slug, label, date_str = info
        md_path = os.path.join(REPORTS, fname)
        md = open(md_path, encoding="utf-8").read()
        title = md.splitlines()[0].lstrip("# ").strip() if md else slug

        # 1) 生成独立 HTML 页（永久链接）
        #    ⚠️ 输出到 html_dir（供 Caddy 托管），.md 留在管线目录
        page = render_page(md, title)
        html_path = os.path.join(html_dir or REPORTS, slug + ".html")
        open(html_path, "w", encoding="utf-8").write(page)

        # 2) feed 内嵌正文（Miniflux 直接展开）
        body = md_to_html(md)
        entries.append({
            "slug": slug, "label": label, "date": date_str,
            "title": title, "body": body,
            "link": f"{base_url.rstrip('/')}/reports/{slug}.html",
        })

    # 按日期倒序（新的在前）
    entries.sort(key=lambda e: (e["date"], e["slug"]), reverse=True)

    now = formatdate(time.time(), usegmt=True)
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<rss version="2.0"',
         '     xmlns:atom="http://www.w3.org/2005/Atom"',
         '     xmlns:content="http://purl.org/rss/1.0/modules/content/">',
         '<channel>',
         '  <title>AI 日报 / 周报 / 月报</title>',
         f'  <link>{esc(base_url)}</link>',
         '  <description>AIHOT 管线自动生成的周期报告</description>',
         '  <language>zh-CN</language>',
         f'  <lastBuildDate>{now}</lastBuildDate>',
         '  <generator>minis-report-rss</generator>',
         f'  <atom:link href="{esc(base_url)}/feeds/reports.xml" rel="self" type="application/rss+xml"/>']

    for e in entries:
        L += ['  <item>',
              f'    <title>{esc(e["title"])}</title>',
              f'    <link>{esc(e["link"])}</link>',
              f'    <guid isPermaLink="false">report:{esc(e["slug"])}</guid>',
              f'    <pubDate>{_rfc822(e["date"])}</pubDate>',
              f'    <category>{esc(e["label"])}</category>',
              f'    <description>{esc(e["title"])}</description>',
              f'    <content:encoded><![CDATA[{e["body"]}]]></content:encoded>',
              '  </item>']

    L += ['</channel>', '</rss>', '']
    xml = "\n".join(L)

    if not out_xml:
        out_xml = os.path.join(REPORTS, "..", "reports.xml")
        out_xml = os.path.normpath(out_xml)
    open(out_xml, "w", encoding="utf-8").write(xml)
    return out_xml, len(entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get(
        "AIHOT_BASE_URL", "https://miniflux.example.com"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--html-dir", default=os.environ.get("AIHOT_HTML_DIR"),
                    help="HTML 输出目录（供 Caddy 托管），默认与 .md 同目录")
    a = ap.parse_args()
    out, n = build(a.base_url, a.out, a.html_dir)
    print(f"wrote {out}: {n} reports, {len(open(out, encoding='utf-8').read())} chars")


if __name__ == "__main__":
    main()

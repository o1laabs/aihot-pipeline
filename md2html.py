#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 Markdown → HTML（只用标准库）

为什么自己写：管线刻意保持零依赖（不引入 markdown 库），
而报告只用到一个很小的语法子集。

安全策略：**先整体转义，再放行白名单标签**。
避免正文里的 < & 破坏 HTML，同时保留报告里刻意写的 <sub> 等。
"""
import re, html

# 允许原样通过的行内标签（其余一律转义）
ALLOWED_INLINE = ("sub", "/sub", "em", "/em", "strong", "/strong", "code", "/code")


def _inline(text):
    """行内转换。顺序很重要：先转义，再放行白名单，最后处理 markdown 语法。"""
    s = html.escape(text, quote=False)

    # 放行白名单标签：&lt;sub&gt; → <sub>
    for tag in ALLOWED_INLINE:
        s = s.replace(f"&lt;{tag}&gt;", f"<{tag}>")

    # 行内代码（先于粗斜体，避免 * 被误判）
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    # 图片
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img alt="\1" src="\2">', s)
    # 链接
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    # 粗体 / 斜体
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<em>\1</em>", s)
    return s


def md_to_html(md):
    """块级转换：标题 / 列表 / 引用 / 分隔线 / 段落"""
    out = []
    in_ul = False
    for raw in md.splitlines():
        line = raw.rstrip()

        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}|\*{3,}", line.strip()):
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append("<hr>")
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>"); in_ul = False
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue

        # 引用
        m = re.match(r"^>\s?(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f"<blockquote>{_inline(m.group(1))}</blockquote>")
            continue

        # 列表（支持一层缩进的续行）
        m = re.match(r"^(\s*)-\s+(.*)$", line)
        if m:
            indent, body = len(m.group(1)), m.group(2)
            if not in_ul:
                out.append("<ul>"); in_ul = True
            cls = ' class="sub"' if indent >= 2 else ""
            out.append(f"<li{cls}>{_inline(body)}</li>")
            continue

        # 普通段落
        if in_ul:
            out.append("</ul>"); in_ul = False
        out.append(f"<p>{_inline(line)}</p>")

    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 4rem;
    font: 16px/1.75 -apple-system, "PingFang SC", "Hiragino Sans GB",
          "Microsoft YaHei", system-ui, sans-serif;
    color: #1a1a1a; background: #fdfdfc;
    -webkit-text-size-adjust: 100%;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6e6e6; background: #16161a; }}
    a {{ color: #7ab8ff; }}
    blockquote {{ border-left-color: #3a3a44; color: #b8b8c0; }}
    code {{ background: #26262e; }}
    li.sub {{ color: #a8a8b2; }}
  }}
  h1 {{ font-size: 1.6rem; line-height: 1.35; margin: 0 0 1.5rem; letter-spacing: -0.01em; }}
  h2 {{ font-size: 1.2rem; margin: 2.5rem 0 .75rem; padding-bottom: .4rem;
        border-bottom: 1px solid rgba(128,128,128,.25); }}
  h3 {{ font-size: 1rem; margin: 1.75rem 0 .5rem; }}
  p {{ margin: .6rem 0; }}
  ul {{ margin: .6rem 0; padding-left: 1.25rem; }}
  li {{ margin: .4rem 0; }}
  li.sub {{ font-size: .9em; color: #555; list-style: circle; }}
  a {{ color: #0a58ca; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  blockquote {{ margin: 1rem 0; padding: .6rem 1rem; border-left: 3px solid #d0d0d8;
                color: #555; background: rgba(128,128,128,.06); border-radius: 2px; }}
  code {{ background: #f0f0f3; padding: .15em .4em; border-radius: 3px;
          font-size: .88em; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  hr {{ border: 0; border-top: 1px solid rgba(128,128,128,.25); margin: 2rem 0; }}
  sub {{ font-size: .75em; color: #777; }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid rgba(128,128,128,.2);
            font-size: .8rem; color: #888; }}
</style>
</head>
<body>
{body}
<footer>AIHOT 管线自动生成 · 摘要为二手转述，事实请回原文核实</footer>
</body>
</html>
"""


def render_page(md, title):
    return PAGE.format(title=html.escape(title), body=md_to_html(md))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: md2html.py <file.md> [out.html]")
        sys.exit(2)
    md = open(sys.argv[1], encoding="utf-8").read()
    title = md.splitlines()[0].lstrip("# ").strip() if md else "report"
    html_out = render_page(md, title)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w", encoding="utf-8").write(html_out)
        print(f"wrote {sys.argv[2]} ({len(html_out)} chars)")
    else:
        print(html_out)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIHOT 只读 API 客户端（纯标准库，无外部依赖）

端点（2026-10-01 实测）:
  GET /api/v1/items?mode=selected|all&window=24h|7d&limit=&q=&category=&by=
  GET /api/v1/dailies                     官方日报（含历史）
  GET /api/v1/hot-topics                  热点榜（带跨源印证计数）

铁律: 只把本 API 当「线索发现层」。items[].summary 是 AIHOT 的二手转述，
      引用事实必须回 items[].links.original 自己重抓。
"""
import json, time, urllib.request, urllib.error, urllib.parse, gzip

BASE = "https://aihot.news"
UA = "minis-aihot/1.0 (+personal reader; contact: local)"


def _get(path, params=None, timeout=60, retries=4):
    qs = ""
    if params:
        parts = [f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None]
        if parts:
            qs = "?" + "&".join(parts)
    url = BASE + path + qs
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            req.add_header("Accept", "application/json")
            req.add_header("Accept-Encoding", "gzip")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            # 4xx 是契约错误，不重试（沿用官方 errors 语义）
            if 400 <= e.code < 500:
                raise RuntimeError(f"HTTP {e.code} on {path}: {body}")
            last = f"HTTP {e.code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"failed {path} after {retries} tries: {last}")


def items(mode="selected", window="24h", limit=50, q=None, category=None, by=None):
    """拉线索。mode: selected|all ; window: 24h|7d ; by: timeline|published"""
    d = _get("/api/v1/items", {
        "mode": mode, "window": window, "limit": limit,
        "q": q, "category": category, "by": by,
    })
    return d.get("items", []), d.get("page", {})


def items_all(mode="selected", window="24h", max_items=200, **kw):
    """游标翻页拉取，直到 max_items 或 hasMore=False"""
    out, cursor, page = [], None, None
    while len(out) < max_items:
        params = dict(mode=mode, window=window, limit=min(50, max_items - len(out)), **kw)
        if cursor:
            params["cursor"] = cursor
        d = _get("/api/v1/items", params)
        batch = d.get("items", [])
        out.extend(batch)
        page = d.get("page", {})
        cursor = page.get("nextCursor")
        if not cursor or not page.get("hasMore"):
            break
    return out[:max_items], page


def dailies():
    """官方日报索引（含历史），返回 [{date, generatedAt, leadTitle, leadParagraph, links}]"""
    return _get("/api/v1/dailies").get("items", [])


def hot_topics():
    """热点榜。sourceCount = 多少家独立来源报了同一件事（跨源印证）"""
    return _get("/api/v1/hot-topics").get("items", [])


def direct_url(it):
    """取原文直链 —— 这是唯一可信入口"""
    return (it.get("links") or {}).get("original") or (it.get("links") or {}).get("aihot", "")


if __name__ == "__main__":
    its, pg = items(limit=3)
    print(f"items={len(its)} hasMore={pg.get('hasMore')}")
    for i in its:
        print(f"  [{i.get('score')}] {i.get('title')[:56]}")
        print(f"    原文: {direct_url(i)}")
    print()
    ds = dailies()
    print(f"dailies={len(ds)}  最新={ds[0]['date'] if ds else '-'}")
    hs = hot_topics()
    print(f"hot={len(hs)}  榜首 sourceCount={hs[0].get('sourceCount') if hs else '-'}")

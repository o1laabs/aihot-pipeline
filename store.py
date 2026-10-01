#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIHOT 本地累积存储（SQLite）

为什么必须有: AIHOT API 的 window 只支持 24h / 7d。
              月报需要 30 天数据 → 只能自己每天落盘累积。

用法:
  python3 store.py sync                 # 拉一次并落盘（幂等，重复跑不会重复存）
  python3 store.py stats                # 看库里有多少
"""
import os, sqlite3, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import aihot_api  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aihot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id             TEXT PRIMARY KEY,
    title          TEXT,
    original_title TEXT,
    summary        TEXT,
    reason         TEXT,
    url_original   TEXT,
    url_aihot      TEXT,
    source_name    TEXT,
    category       TEXT,
    score          INTEGER,
    published_at   TEXT,
    discovered_at  TEXT,
    first_seen     TEXT
);
CREATE INDEX IF NOT EXISTS idx_pub  ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_cat  ON items(category);
CREATE INDEX IF NOT EXISTS idx_seen ON items(first_seen);
"""


def conn(path=DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def upsert(c, its):
    """幂等写入。返回 (新增数, 已存在数)"""
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    for it in its:
        row = (it.get("id"), it.get("title"), it.get("originalTitle"),
               it.get("summary"), it.get("reason"),
               aihot_api.direct_url(it),
               (it.get("links") or {}).get("aihot"),
               (it.get("source") or {}).get("name"),
               it.get("category"), it.get("score"),
               it.get("publishedAt"), it.get("discoveredAt"), now)
        cur = c.execute(
            """INSERT OR IGNORE INTO items
               (id,title,original_title,summary,reason,url_original,url_aihot,
                source_name,category,score,published_at,discovered_at,first_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
        if cur.rowcount == 1:
            new += 1
    c.commit()
    return new, len(its) - new


def sync(max_items=200):
    """拉精选+全部，两个 window 都覆盖，最大化覆盖面"""
    total_new = total = 0
    for mode in ("selected", "all"):
        for window in ("24h", "7d"):
            try:
                its, _ = aihot_api.items_all(mode=mode, window=window,
                                             max_items=max_items)
            except Exception as e:
                print(f"  ! {mode}/{window} 失败: {e}")
                continue
            n, e_ = upsert(conn(), its)
            total_new += n
            total += len(its)
            print(f"  {mode:8s}/{window:4s}: 拉到 {len(its):3d} 条, 新增 {n:3d}")
            time.sleep(0.6)  # 对上游客气一点
    return total_new, total


def since(days=7, path=DB):
    c = conn(path)
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [dict(r) for r in c.execute(
        "SELECT * FROM items WHERE published_at >= ? ORDER BY published_at DESC",
        (cut,))]


def between(start_iso, end_iso, path=DB):
    c = conn(path)
    return [dict(r) for r in c.execute(
        "SELECT * FROM items WHERE published_at >= ? AND published_at < ? "
        "ORDER BY published_at DESC", (start_iso, end_iso))]


def stats(path=DB):
    c = conn(path)
    n = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if not n:
        return {"count": 0}
    d = c.execute("SELECT MIN(published_at) a, MAX(published_at) b FROM items").fetchone()
    cats = c.execute("SELECT category, COUNT(*) n FROM items "
                     "GROUP BY category ORDER BY n DESC LIMIT 8").fetchall()
    return {"count": n, "earliest": d["a"], "latest": d["b"],
            "categories": [(r["category"], r["n"]) for r in cats]}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "sync":
        n, t = sync()
        print(f"\n完成: 拉到 {t} 条, 新增 {n} 条")
    s = stats()
    print(f"库统计: {s}")

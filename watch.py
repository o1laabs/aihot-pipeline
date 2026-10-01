#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIHOT 实时消息推送

机制: 轮询 /api/v1/items → 与本地已见集合比对 → 只推新的
状态: 复用 store.py 的 SQLite（first_seen 字段即"首次见到时刻"）

⚠️ 部署位置很重要:
   Minis 沙箱的进程会随 App 挂起而停止 → 不能放在手机里做 7×24 推送。
   必须跑在 Oracle 服务器上（systemd timer / cron）。

用法:
  python3 watch.py once                    # 跑一次，推送新条目
  python3 watch.py once --min-score 80     # 只推 80 分以上的
  python3 watch.py loop --interval 300     # 常驻，每 5 分钟一次
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import aihot_api, store  # noqa: E402

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state.json")


def _load_state():
    try:
        with open(STATE) as f:
            return set(json.load(f).get("seen", []))
    except Exception:
        return None  # None = 首次运行，不做历史回溯推送


def _save_state(seen, cap=5000):
    with open(STATE, "w") as f:
        json.dump({"seen": list(seen)[-cap:],
                   "updatedAt": datetime.now(timezone.utc).isoformat()}, f)


def fetch_new(min_score=0, max_items=200):
    """返回本次新出现的条目（已按分数过滤）"""
    seen = _load_state()
    its, _ = aihot_api.items_all(mode="selected", window="24h",
                                 max_items=max_items)
    fresh = []
    for it in its:
        if seen is not None and it.get("id") in seen:
            continue
        fresh.append(it)
    # 落盘累积
    c = store.conn()
    store.upsert(c, its)
    _save_state((seen or set()) | {i.get("id") for i in its})

    if seen is None:
        print(f"[首次运行] 建立基线 {len(its)} 条，本轮不推送（避免刷屏）")
        return []

    fresh = [i for i in fresh if (i.get("score") or 0) >= min_score]
    fresh.sort(key=lambda i: -(i.get("score") or 0))
    return fresh


# ---------- 推送通道 ----------

def push_local(title, body):
    """本地设备通知（Minis 的 android-notification）"""
    try:
        subprocess.run(["android-notification", "send", "--title", title,
                        "--body", body], timeout=20, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"  ! 本地通知失败: {e}")
        return False


def push_stdout(title, body):
    print(f"\n{'='*60}\n{title}\n{'-'*60}\n{body}\n")


def push_hook(cmd, title, body):
    """自定义推送命令。cmd 里用 {title} {body} 占位"""
    try:
        subprocess.run(cmd.replace("{title}", title).replace("{body}", body),
                       shell=True, timeout=30, check=False)
        return True
    except Exception as e:
        print(f"  ! hook 失败: {e}")
        return False


def run_once(min_score=0, channel="stdout", hook=None):
    fresh = fetch_new(min_score=min_score)
    if not fresh:
        print(f"无新条目（阈值 {min_score} 分）")
        return 0
    print(f"新条目 {len(fresh)} 条")
    sent = 0
    for it in fresh:
        title = it.get("title", "")[:80]
        body = (it.get("summary") or "")[:200] + f"\n\n原文: {aihot_api.direct_url(it)}"
        if hook:
            push_hook(hook, title, body)
        elif channel == "local":
            push_local(title, body)
        else:
            push_stdout(title, body)
        sent += 1
        time.sleep(0.3)
    return sent


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="once", choices=["once", "loop"])
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--channel", default="stdout", choices=["stdout", "local"])
    ap.add_argument("--hook", default=None, help="自定义推送命令, 支持 {title} {body} 占位")
    a = ap.parse_args()

    if a.mode == "once":
        run_once(a.min_score, a.channel, a.hook)
    else:
        print(f"常驻模式，每 {a.interval}s 一次（Ctrl-C 停）")
        while True:
            try:
                run_once(a.min_score, a.channel, a.hook)
            except Exception as e:
                print(f"  轮询异常: {e}")
            time.sleep(a.interval)

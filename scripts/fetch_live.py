#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_live.py — RailAround 全国实时列车快照抓取（GitHub Action 每 10 分钟）

页面端（index.html 内嵌「⚡实时」图层）读取 data/live/latest.json 插值动画：
  { fetched_at_ms, fetched_at_jst:"YYYY-MM-DD HH:MM:SS", count,
    trains: [ {id, icon, rday, tmap_id(str), schs} ... ] }

接口（已逆向验证）:
  GET /api/train?type=railway&ids=<全部rw_ids>&trainSTime=<now>&systemSTime=<now>
             &multiplier=1&firstRun=true&getTrainFreq=3&dataSpan=5
  → trains[] = {_id, rday, tmap_id, schs, icon}
    - schs: 交错时刻（schs[0]=首站发车分钟; 奇数位=站间运行→到站; 偶数位=停站→发车; 长度=2N-2）
    - rday: 位掩码 1=平日 2=周六 4=周日·假日（组合 3/5/6/7）
  tmap_id → 停站序列查 data/live/tmaps.json（由 railaround_build_tmaps.py 构建，每日/按需刷新）

合规: robots.txt Disallow:/api/ + Crawl-delay:2 → 单次请求即可取全量，间隔 2.2s。
用法: python3 scripts/fetch_live.py [--out data/live/latest.json] [--sleep 2.2]
"""
import argparse, datetime, json, os, time, urllib.request

BASE = "https://www.railaround.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

def get_train(ids_csv, now_ms):
    u = (f"{BASE}/api/train?type=railway&ids={ids_csv}"
         f"&trainSTime={now_ms}&systemSTime={now_ms}"
         f"&multiplier=1&firstRun=true&getTrainFreq=3&dataSpan=5")
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("trains", [])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="data/live/lines.json")
    ap.add_argument("--out", default="data/live/latest.json")
    ap.add_argument("--sleep", type=float, default=2.2)
    args = ap.parse_args()

    lines = json.load(open(args.lines, encoding="utf-8"))["lines"]
    rw_ids, seen = [], set()
    for ln in lines:
        for rw in ln["rw_ids"]:
            if rw not in seen:
                seen.add(rw)
                rw_ids.append(rw)
    print(f"实时抓取: {len(rw_ids)} 个 rw_id（1 个请求）", flush=True)

    now_ms = int(time.time() * 1000)
    trains = get_train(",".join(map(str, rw_ids)), now_ms)
    jst = datetime.timezone(datetime.timedelta(hours=9))
    out = {
        "fetched_at_ms": now_ms,
        "fetched_at_jst": datetime.datetime.fromtimestamp(now_ms / 1000, jst).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(trains),
        "trains": [{"id": t["_id"], "icon": t.get("icon", ""),
                    "rday": t.get("rday", 7), "tmap_id": str(t["tmap_id"]),
                    "schs": t.get("schs", [])} for t in trains],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    json.dump(out, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, args.out)
    time.sleep(args.sleep)
    print(f"完成: 列车={len(trains)} → {args.out}", flush=True)

if __name__ == "__main__":
    main()

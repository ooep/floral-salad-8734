#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_timetables.py — 全量时刻表刷新（GitHub Action 用，每周/手动）

读取 data/lines_index.json（含全部线路 rw_ids），对每条线路按正确编码
请求 3 次 /api/train（平日/周六/周日·假日），schs 解码后写出紧凑格式：

  data/timetables/<seq>_<线路名>.json
    { line, rw_ids, fetched_at, trains: [ {train_id, icon, rday, origin, dest,
       stops:[{st, arr, dep}] } ] }

合规：robots.txt Disallow:/api/ + Crawl-delay:2 → 每请求间隔 2.2s。
全量约 577 线 × 3 请求 ≈ 1,730 请求 ≈ 65 分钟（单线程，无 429 风险）。
非必需：页面实时层只用 live_trains/live_geo；本脚本保持"全量时刻表"数据常新，
供后续按站查询功能使用。也可 --only <线路名> 只刷新单线。

用法：
  python scripts/fetch_timetables.py                  # 全量（慢，CI 用）
  python scripts/fetch_timetables.py --only 高山本線  # 单线冒烟
  python scripts/fetch_timetables.py --resume         # 跳过已存在
"""
import argparse, datetime, json, os, sys, time, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
      "Accept": "application/json"}
BASE = "https://www.railaround.com"
SLEEP = 2.2
MAX_RETRY = 3

# 参考日编码（正确 rday 位掩码机制）：
# trainSTime = 参考日 JST 03:00 -> UTC 前日 18:00
# （实测 JST 12:00 窗口对大线会缺 0-9 点早高峰班次;03:00 窗口返回全日 4226 班 ⊇ 12:00 窗口 2874 班）
# day: 2=平日(2024-01-02 周二) 6=周六(2024-01-06) 7=周日(2024-01-07)
RUNADAYS = {"weekday": (2, 1), "saturday": (6, 2), "sunday": (7, 4)}

def _http(method, url, body=None):
    last_err = None
    for att in range(1, MAX_RETRY + 1):
        try:
            if method == "GET":
                req = urllib.request.Request(url, headers=UA)
            else:
                req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", **UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(4 * att); continue
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(3 * att); continue
    raise RuntimeError(f"请求失败({last_err}): {url}")

def get_trains(rw_ids, day):
    import time as _t
    train_stime = int(datetime.datetime(2024, 1, day - 1, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    sys_stime = int(_t.time() * 1000)
    url = (f"{BASE}/api/train?type=railway&ids={','.join(map(str, rw_ids))}"
           f"&trainSTime={train_stime}&systemSTime={sys_stime}&multiplier=1"
           f"&firstRun=true&getTrainFreq=100&dataSpan=1440")
    d = _http("GET", url)
    return d.get("trains", [])

def decode_stops(train):
    """schs 解码 -> stops[{st?, arr, dep}]（无站名；站名由调用方按 tmap 补齐或省略）"""
    schs = train.get("schs") or []
    if not schs:
        return []
    # schs 长度 = 2N-2(N=站数); (L+1)//2 对偶数 L 恒少 1 站 → 全量构建后 s 长度
    # 与页面 2N-2 校验不符,3D 页所有列车会被跳过。正确 N = L//2 + 1
    N = len(schs) // 2 + 1
    dep0 = schs[0]
    stops = [{"arr": None, "dep": dep0}]
    for i in range(1, N):
        arr = stops[-1]["dep"] + schs[2 * i - 1]
        dep = arr + (schs[2 * i] if 2 * i < len(schs) else 0)
        stops.append({"arr": arr, "dep": dep if i < N - 1 else None})
    return stops

def process_line(seq, line, rw_ids, out_dir, resume):
    fname = f"{seq:03d}_{line}.json"
    path = os.path.join(out_dir, fname)
    if resume and os.path.exists(path):
        return "skip", None
    merged = {}
    for runday, (day, bit) in RUNADAYS.items():
        try:
            trains = get_trains(rw_ids, day)
        except Exception as e:
            return "error", str(e)
        time.sleep(SLEEP)
        for t in trains:
            key = t["_id"] + "|" + json.dumps(t.get("schs", []), separators=(",", ":"))
            if key in merged:
                continue
            merged[key] = {
                "train_id": t["_id"], "tmap_id": t.get("tmap_id"),
                "icon": t.get("icon", ""), "rday": t.get("rday", 0),
                "origin": t.get("origin", ""), "dest": t.get("dest", ""),
                "stops": decode_stops(t),
            }
    trains = list(merged.values())
    if not trains:
        return "empty", None
    rec = {"line": line, "rw_ids": rw_ids,
           "fetched_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds"),
           "trains_total": len(trains), "trains": trains}
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    return "ok", len(trains)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="data/lines_index.json")
    ap.add_argument("--out", default="data/timetables")
    ap.add_argument("--only", default="", help="只刷新该线路名")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--delay", type=float, default=SLEEP)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    idx = json.load(open(os.path.join(root, args.lines), encoding="utf-8"))
    out_dir = os.path.join(root, args.out)

    stat = {"ok": 0, "empty": 0, "error": 0, "skip": 0, "trains": 0}
    errors = []
    for r in idx:
        if r.get("status") != "ok":
            continue
        line = r["line"]
        if args.only and line != args.only:
            continue
        rw = r.get("rw_ids")
        if isinstance(rw, str):
            rw = [int(x) for x in rw.replace("[", "").replace("]", "").split(";") if x.strip()]
        rw = [int(x) for x in rw]
        st, info = process_line(r["seq"], line, rw, out_dir, args.resume)
        stat[st] = stat.get(st, 0) + 1
        if st == "ok":
            stat["trains"] += info
        if st == "error":
            errors.append(f"{line}: {info}")
        print(f"[{st}] {line} {info if st in ('ok','empty') else ''}", flush=True)
    print("\n统计:", stat)
    if errors:
        print("错误:", *errors, sep="\n  ")

if __name__ == "__main__":
    main()

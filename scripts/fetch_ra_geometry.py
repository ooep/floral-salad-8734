#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_ra_geometry.py — 一次性拉取官方线路几何(含每区间坐标串)

对 lines_index.json 中每个 rw_id 请求 /api/animation/initial, 原始响应存到
scripts/geo/ra_official/<rw_id>.json (resume 友好)。

响应结构:
  tmaps[].tmap_id / s_jas (站序原始名, 含县括号) / l_ids (每区间线段ID, 符号=方向)
  line[].l_id / gis_len / coords [lon,lat,...] / coords_count / bds
车站坐标 = 相邻线段端点相接: l_id>0 时 s[i-1]=coords 首, s[i]=尾; <0 反向。

合规: 与 fetch_timetables.py 相同, 单线程 + 2.2s 节流 (robots: Crawl-delay 2)。
用法: python3 scripts/fetch_ra_geometry.py [--sleep 2.2]
"""
import argparse, json, os, sys, time, urllib.request

BASE = "https://www.railaround.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scripts", "geo", "ra_official")
H = {"Content-Type": "application/json",
     "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
     "Referer": "https://www.railaround.com/ja/railway/",
     "Accept": "application/json"}

def post_initial(rw_id, retry=3):
    body = json.dumps({"type": "railway", "ids": [rw_id], "locale": "ja"}).encode()
    last = None
    for att in range(retry):
        try:
            req = urllib.request.Request(BASE + "/api/animation/initial", data=body, headers=H)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (att + 1))
    raise RuntimeError(last)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=2.2)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    _idx = json.load(open(os.path.join(ROOT, "data", "lines_index.json"), encoding="utf-8"))
    idx = _idx["lines"] if isinstance(_idx, dict) else _idx
    rws = []
    seen = set()
    for l in idx:
        for rw in l["rw_ids"]:
            if rw not in seen:
                seen.add(rw); rws.append(rw)
    ok = skip = fail = 0
    failed = []
    t0 = time.time()
    for n, rw in enumerate(rws, 1):
        path = os.path.join(OUT, f"{rw}.json")
        if os.path.exists(path) and os.path.getsize(path) > 50:
            skip += 1; continue
        try:
            d = post_initial(rw)
            json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            ok += 1
        except Exception as e:
            fail += 1; failed.append((rw, str(e)))
            print(f"[FAIL] rw={rw} {e}", flush=True)
        if n % 25 == 0:
            el = time.time() - t0
            print(f"{n}/{len(rws)} ok={ok} skip={skip} fail={fail} {el:.0f}s", flush=True)
        time.sleep(args.sleep)
    print(f"DONE ok={ok} skip={skip} fail={fail} total={len(rws)} {(time.time()-t0):.0f}s")
    if failed:
        json.dump(failed, open(os.path.join(OUT, "_failed.json"), "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()

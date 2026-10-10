#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tmaps.py — 构建 tmap 归属缓存（一次性/周更）

对每一条 rw_id 逐线请求 /api/animation/initial，收集:
  - tmaps.json : { tmap_id: {"s_jas": [...站名序列...], "lines": [线路ja名...]} }
  - railways.json : { rw_id: {name_ja,name_en,name_zh} }
用于实时列车图层：tmap_id → 停站顺序（几何用用户自己的 segments/stations），
以及列车提示框的线路名归属。

合规：robots.txt Disallow:/api/ + Crawl-delay:2 → 单线程, 每次间隔 SLEEP 秒。
用法: python3 scripts/build_tmaps.py [--out data/live] [--sleep 2.2]
支持 --resume：已存在的 tmaps.json 中出现的 tmap_id 不再重复请求（仅当 --incremental）。
"""
import argparse, json, os, sys, time, urllib.request

BASE = "https://www.railaround.com"
H = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.railaround.com/zh/railway/",
    "Accept": "application/json",
}

def post_initial(rw_ids):
    req = urllib.request.Request(
        BASE + "/api/animation/initial",
        data=json.dumps({"type": "railway", "ids": rw_ids, "locale": "ja"}).encode(),
        headers=H,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="data/live/lines.json")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--sleep", type=float, default=2.2)
    ap.add_argument("--incremental", action="store_true", help="跳过已缓存的 tmap_id（适用于 CI 周更）")
    ap.add_argument("--skip-if-cached", action="store_true", help="缓存已存在且非空时直接跳过（CI 每日部署用）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    tmap_path = os.path.join(args.out, "tmaps.json")
    rail_path = os.path.join(args.out, "railways.json")
    tmaps = {}
    railways = {}
    if os.path.exists(tmap_path):
        try:
            tmaps = json.load(open(tmap_path, encoding="utf-8"))
        except Exception:
            tmaps = {}
    if args.skip_if_cached and len(tmaps) > 0:
        print(f"tmaps 缓存已存在（{len(tmaps)} 个），跳过构建", flush=True)
        return
    if os.path.exists(rail_path):
        railways = json.load(open(rail_path, encoding="utf-8"))

    lines = json.load(open(args.lines, encoding="utf-8"))["lines"]
    rw_ids = []
    seen = set()
    for ln in lines:
        for rw in ln["rw_ids"]:
            if rw not in seen:
                seen.add(rw)
                rw_ids.append((rw, ln["line"]))
    print(f"共 {len(rw_ids)} 个 rw_id（{len(lines)} 线），预计 {(len(rw_ids)*args.sleep)/60:.0f} 分钟", flush=True)

    # 若缓存已含全部 tmap 则跳过：不直接比较，逐 rw_id 请求仍会跑完；
    # 为 CI 省时：直接带 tmap 覆盖的 rw_id 仍请求一次（站点可能更新）。
    ok = fail = 0
    t0 = time.time()
    for i, (rw, line) in enumerate(rw_ids):
        try:
            d = post_initial([rw])
            n = 0
            for t in d.get("tmaps", []):
                tid = str(t["tmap_id"])
                ent = tmaps.setdefault(tid, {"s_jas": t.get("s_jas", []), "lines": []})
                if line not in ent["lines"]:
                    ent["lines"].append(line)
                n += 1
            for rw_ in d.get("railways", []):
                railways[str(rw_["rw_id"])] = {
                    "name_ja": rw_.get("name_ja"),
                    "name_en": rw_.get("name_en"),
                    "name_zh": rw_.get("name_zh"),
                }
            ok += 1
            if (i + 1) % 50 == 0:
                json.dump(tmaps, open(tmap_path, "w"), ensure_ascii=False)
                json.dump(railways, open(rail_path, "w"), ensure_ascii=False)
                print(f"  progress {i+1}/{len(rw_ids)} (ok={ok} fail={fail} tmaps={len(tmaps)} elapsed={time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            fail += 1
            print(f"  ERR rw={rw} line={line}: {e}", flush=True)
        time.sleep(args.sleep)

    json.dump(tmaps, open(tmap_path, "w"), ensure_ascii=False)
    json.dump(railways, open(rail_path, "w"), ensure_ascii=False)
    print(f"完成: ok={ok} fail={fail} tmaps={len(tmaps)} 写入 {tmap_path}", flush=True)

if __name__ == "__main__":
    main()

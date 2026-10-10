#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_trains.py — 从本地全量时刻表构建页面用的轻量列车文件（不访问网络）

输入（自动识别）：
  - railaround/output/day_shard*/<seq>_<线>.json   （VM 全量抓取格式，rday1..rday7 分组）
  - data/timetables/<seq>_<线>.json                 （fetch_timetables.py 格式，trains[]）
输出（3 个按运行日分组的文件 + 页面只加载今日对应那份）：
  data/live/trains_wd.json   rday&1  （平日）
  data/live/trains_sa.json   rday&2  （周六）
  data/live/trains_su.json   rday&4  （周日·假日）
每班次紧凑记录：{"t":tmap_id,"r":rday,"w":"发车分,终到分","s":"schs 逗号串","i":"车种","_":"train_id"}
schs = [dep0, run1, dwell1, run2, dwell2, ...]（长度 2N-2，终点站无停留字段），与页面解码一致。

用法：
  python3 scripts/build_trains.py                          # 自动找源
  python3 scripts/build_trains.py --src <目录> --out <目录>
"""
import argparse, datetime, glob, json, os, re, sys
from collections import Counter

def mn(s):
    if not s:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = re.match(r"(\d{1,2}):(\d{2})", str(s).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None

def iter_trains(path):
    """yield (train_id, tmap_id, icon, rday, stops)"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and any(k.startswith("rday") and isinstance(d.get(k), list) for k in d):
        for key in [f"rday{i}" for i in range(1, 8)]:
            for tr in d.get(key, []) or []:
                yield (tr.get("train_id") or tr.get("_id"), tr.get("tmap_id"), tr.get("icon", ""), tr.get("rday"), tr.get("stops", []))
    elif isinstance(d, dict) and isinstance(d.get("trains"), list):
        for tr in d["trains"]:
            stops = tr.get("stops", [])
            yield (tr.get("train_id") or tr.get("_id"), tr.get("tmap_id"), tr.get("icon", ""), tr.get("rday"), stops)

def convert(stops):
    """stops: [{station/st, arr, dep}] -> (schs, dep0, arr_last) or None"""
    N = len(stops)
    if N < 2:
        return None
    d0 = mn(stops[0].get("dep")) or mn(stops[0].get("arr"))
    if d0 is None:
        return None
    schs = [d0]
    prev_dep = d0
    arr_last = d0
    for i in range(1, N):
        a = mn(stops[i].get("arr")) or mn(stops[i].get("dep"))
        de = mn(stops[i].get("dep")) or a
        if a is None or de is None:
            return None
        r = a - prev_dep
        if r < 0:
            r = 0
        schs.append(r)
        if i < N - 1:
            w = de - a
            if w < 0:
                w = 0
            schs.append(w)
        prev_dep = de
        arr_last = a
    if len(schs) != 2 * N - 2:
        return None
    return schs, d0, arr_last

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="", help="时刻表源目录（默认自动探测全量抓取目录或 data/timetables）")
    ap.add_argument("--out", default=os.path.join(root, "data", "live"))
    args = ap.parse_args()

    src = args.src
    if not src:
        cands = [os.path.join(root, "..", "railaround", "output"), os.path.join(root, "data", "timetables")]
        for c in cands:
            if glob.glob(os.path.join(c, "day_shard*", "*.json")) or glob.glob(os.path.join(c, "*.json")):
                src = c
                break
    if not src:
        print("未找到时刻表源目录（--src）")
        sys.exit(1)

    files = sorted(glob.glob(os.path.join(src, "day_shard*", "*.json")) + glob.glob(os.path.join(src, "*.json")))
    if not files:
        print("源目录无 JSON:", src)
        sys.exit(1)

    recs = {}
    skipped = {"short": 0, "bad": 0, "dup": 0}
    neg_clamped = 0
    day_counts = {"wd": 0, "sa": 0, "su": 0}
    for fp in files:
        try:
            for tid, tmap_id, icon, rday, stops in iter_trains(fp):
                if not tid or tmap_id is None or not rday:
                    skipped["bad"] += 1
                    continue
                if tid in recs:
                    skipped["dup"] += 1
                    continue
                conv = convert(stops)
                if not conv:
                    skipped["short"] += 1
                    continue
                schs, d0, arr_last = conv
                recs[tid] = {"t": tmap_id, "r": rday, "w": f"{d0},{arr_last}",
                             "s": ",".join(map(str, schs)), "i": icon or "", "_": tid}
                for bit, name in ((1, "wd"), (2, "sa"), (4, "su")):
                    if rday & bit:
                        day_counts[name] += 1
        except Exception:
            continue

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes").replace("+00:00", " UTC")
    os.makedirs(args.out, exist_ok=True)
    meta = {"b": now, "n": len(recs), "src": os.path.basename(os.path.normpath(src))}
    for bit, name, label in ((1, "wd", "平日"), (2, "sa", "周六"), (4, "su", "周日·假日")):
        day_recs = [r for r in recs.values() if r["r"] & bit]
        path = os.path.join(args.out, f"trains_{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"b": now, "n": len(day_recs), "T": day_recs}, f, ensure_ascii=False, separators=(",", ":"))
        print(f"trains_{name}.json ({label}): {len(day_recs)} 班次 -> {path} ({os.path.getsize(path)/1e6:.1f}MB)")

    print(f"唯一班次总数: {len(recs)} | 跳过: {skipped} | 负区间钳制: {neg_clamped}")
    print(f"完成 @ {now}")

if __name__ == "__main__":
    main()

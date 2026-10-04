#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_verify.py — 交付前最终验证（独立于页面，重算页面 IIFE 逻辑）
对 data/live/latest.json + data/live/tmaps.json + segments/stations.geojson 做：
  1) tmap 覆盖率：最新快照列车 tmap_id 在 tmaps.json 中的占比
  2) 定位率：按页面同款算法（2N-2 解码 + BFS 沿轨寻路 + 直线回退）统计当前 JST 定位成功
  3) 线路名覆盖率：定位列车中有精确线路名的占比
  4) 时刻倒退检查：跨站到站分钟非递减
"""
import json, datetime, math, sys
from collections import Counter

root = sys.argv[1] if len(sys.argv) > 1 else "."
def L(p): return json.load(open(f"{root}/{p}", encoding="utf-8"))

segs = L("data/segments.geojson")["features"]
stas = L("data/stations.geojson")["features"]
latest = L("data/live/latest.json")
tmaps = L("data/live/tmaps.json")

stationCoord = {f["properties"]["station"]: f["geometry"]["coordinates"] for f in stas}
adj, edgeCoords, edgeLine, segIndex = {}, {}, {}, {}
for f in segs:
    p = f["properties"]
    adj.setdefault(p["from"], set()).add(p["to"])
    adj.setdefault(p["to"], set()).add(p["from"])
    edgeCoords[p["from"] + "|" + p["to"]] = f["geometry"]["coordinates"]
    edgeCoords[p["to"] + "|" + p["from"]] = f["geometry"]["coordinates"][::-1]
    edgeLine[p["from"] + "|" + p["to"]] = p.get("line", "")
    edgeLine[p["to"] + "|" + p["from"]] = p.get("line", "")
    segIndex.setdefault(p["from"] + "|" + p["to"], []).append(f["geometry"]["coordinates"])
    segIndex.setdefault(p["to"] + "|" + p["from"], []).append(f["geometry"]["coordinates"][::-1])

pathMemo = {}
def pointAlong(coords, frac):
    if not coords or len(coords) < 2: return None
    if frac <= 0: return coords[0]
    if frac >= 1: return coords[-1]
    total = sum(math.hypot(coords[i][0]-coords[i-1][0], coords[i][1]-coords[i-1][1]) for i in range(1, len(coords)))
    if total <= 0: return coords[0]
    target, acc = frac * total, 0.0
    for i in range(1, len(coords)):
        seg = math.hypot(coords[i][0]-coords[i-1][0], coords[i][1]-coords[i-1][1])
        if acc + seg >= target:
            f = 0 if seg == 0 else (target - acc) / seg
            return [coords[i-1][0] + (coords[i][0]-coords[i-1][0]) * f, coords[i-1][1] + (coords[i][1]-coords[i-1][1]) * f]
        acc += seg
    return coords[-1]

def pathAlong(A, B):
    key = A + "|" + B
    if key in pathMemo: return pathMemo[key]
    if A not in adj or B not in adj:
        pathMemo[key] = None; return None
    prev = {A: None}; q = [A]
    while q and B not in prev:
        cur = q.pop(0)
        for nb in adj.get(cur, ()):
            if nb not in prev: prev[nb] = cur; q.append(nb)
    if B not in prev:
        pathMemo[key] = None; return None
    stops = [B]; cur = B
    while cur != A: cur = prev[cur]; stops.append(cur)
    stops.reverse()
    coords, segLines, segLens = [], [], []
    for i in range(len(stops)-1):
        c = edgeCoords.get(stops[i]+"|"+stops[i+1]) or [[0,0],[0,0]]
        coords.extend(c if i == 0 else c[1:])
        segLines.append(edgeLine.get(stops[i]+"|"+stops[i+1], ""))
        segLens.append(sum(math.hypot(c[j][0]-c[j-1][0], c[j][1]-c[j-1][1]) for j in range(1, len(c))))
    total = sum(segLens)
    def lineAt(fr):
        if total <= 0: return segLines[0] if segLines else ""
        t, acc = fr * total, 0.0
        for i in range(len(segLens)):
            if acc + segLens[i] >= t: return segLines[i]
            acc += segLens[i]
        return segLines[-1] if segLines else ""
    res = {"coords": coords, "lineAt": lineAt}
    pathMemo[key] = res
    return res

def trainPosition(t, M):
    tm = tmaps.get(str(t["tmap_id"]))
    if not tm or not tm.get("s_jas") or len(tm["s_jas"]) < 2: return None, "no_tmap"
    st, schs, N = tm["s_jas"], t["schs"], len(tm["s_jas"])
    if len(schs) < 2*N-2: return None, "schs_short"
    dep, arr = [0.0]*N, [0.0]*N
    dep[0] = float(schs[0])
    for i in range(1, N):
        arr[i] = dep[i-1] + schs[2*i-1]
        dep[i] = arr[i] + (schs[2*i] if i < N-1 else 0)
    MM = M
    if dep[N-1] < 300 and M > 1400: MM = M - 1440
    if dep[0] > 1400 and M < 300: MM = M + 1440
    if MM < dep[0]-1e-6 or MM > arr[N-1]+1e-6: return None, "out_window"
    meta_line = tm["lines"][0] if len(tm.get("lines", [])) == 1 else ""
    for i in range(N-1):
        if dep[i]-1e-6 <= MM <= arr[i+1]+1e-6:
            run = arr[i+1]-dep[i]
            frac = 0 if run <= 0 else (MM-dep[i])/run
            A, B = st[i], st[i+1]
            d = segIndex.get(A+"|"+B)
            if d:
                pt = pointAlong(d[0], frac)
                if pt: return {"pt": pt, "line": edgeLine.get(A+"|"+B, meta_line)}, "seg"
            pa = pathAlong(A, B)
            if pa:
                pt = pointAlong(pa["coords"], frac)
                if pt: return {"pt": pt, "line": pa["lineAt"](frac) or meta_line}, "bfs"
            ca, cb = stationCoord.get(A), stationCoord.get(B)
            if ca and cb:
                return {"pt": [ca[0]+(cb[0]-ca[0])*frac, ca[1]+(cb[1]-ca[1])*frac], "line": meta_line}, "straight"
            if ca: return {"pt": ca, "line": meta_line}, "at_station"
            if cb: return {"pt": cb, "line": meta_line}, "at_station"
            return None, "no_geo"
        if i+1 < N-1 and MM > arr[i+1]+1e-6 and MM <= dep[i+1]+1e-6:
            c = stationCoord.get(st[i+1])
            if c: return {"pt": c, "line": meta_line}, "dwell"
    return None, "loop_end"

# 时刻倒退检查（跨站到站分钟）
regress = 0
for t in latest["trains"]:
    tm = tmaps.get(str(t["tmap_id"]))
    if not tm: continue
    st, schs, N = tm.get("s_jas", []), t["schs"], len(tm.get("s_jas", []))
    if N < 2 or len(schs) < 2*N-2: continue
    dep, arr = [0.0]*N, [0.0]*N
    dep[0] = float(schs[0])
    for i in range(1, N):
        arr[i] = dep[i-1] + schs[2*i-1]
        dep[i] = arr[i] + (schs[2*i] if i < N-1 else 0)
        if arr[i] < arr[i-1]: regress += 1; break
    if arr[N-1] < dep[0]: regress += 1

jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
M = jst.hour*60 + jst.minute + jst.second/60.0
d = jst.weekday()
bit = 1 if d <= 4 else (2 if d == 5 else 4)

tm_hit = sum(1 for t in latest["trains"] if str(t["tmap_id"]) in tmaps)
tot = hit = 0
methods = Counter(); line_ok = 0
for t in latest["trains"]:
    if not (t["rday"] & bit): continue
    tot += 1
    r, m = trainPosition(t, M)
    if r:
        hit += 1; methods[m] += 1
        if r["line"]: line_ok += 1

print(f"== 最终验证（{jst:%Y-%m-%d %H:%M:%S} JST, 位掩码={bit}）==")
print(f"tmaps 覆盖: {tm_hit}/{len(latest['trains'])} ({tm_hit/len(latest['trains'])*100:.1f}%)  tmaps总量={len(tmaps)}")
print(f"今日运行列车: {tot}  定位成功: {hit} ({hit/tot*100:.1f}%)")
print(f"  定位方式: " + " ".join(f"{k}={v}" for k, v in methods.most_common()))
print(f"  带精确线路名: {line_ok}/{hit} ({line_ok/hit*100:.0f}%)" if hit else "  无定位")
print(f"时刻倒退(跨站到站递减): {regress} 条")

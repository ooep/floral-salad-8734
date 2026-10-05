#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sim_verify.py — 列车位置离线回归验证(引擎 trainPosition 的 Python 等价实现)

数据流与 index.html 新逻辑一致:
  stopC = station_map 官方区间折线端点拼接(tmap_lids + segments)
  路径  = 官方区间折线(与本站 segments3d 同源); run<=0 用平滑窗
  位置  = 按 (M-dep)/run 在路径累计里程上插值; 停车停在起点站
检查: 距 segments3d(地图实际轨道) 最短距离分布 / >3km 离轨 / 相邻时刻瞬移(>400km/h)
用法: python3 scripts/sim_verify.py [trains_wd.json] [M1 M2 ... | start:end:step]
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "mini-japanrail-3d", "data")

def geo_km(a, b):
    dx = (b[0]-a[0]) * math.cos((a[1]+b[1])/2 * math.pi/180) * 111.32
    dy = (b[1]-a[1]) * 110.57
    return math.hypot(dx, dy)

def cum_len(pts):
    cum = [0.0]
    for k in range(1, len(pts)): cum.append(cum[-1] + geo_km(pts[k-1], pts[k]))
    return cum

def pos_on(pts, cum, f):
    target = max(0, min(1, f)) * cum[-1]
    lo, hi = 1, len(cum)-1
    while lo < hi:
        mid = (lo+hi) >> 1
        if cum[mid] < target: lo = mid+1
        else: hi = mid
    k = lo; sl = cum[k]-cum[k-1]
    r = 0 if sl <= 0 else (target-cum[k-1])/sl
    return [pts[k-1][0]+(pts[k][0]-pts[k-1][0])*r, pts[k-1][1]+(pts[k][1]-pts[k-1][1])*r]

sm = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
tmaps = json.load(open(os.path.join(DATA, 'tmaps.json'), encoding='utf-8'))
segfc = json.load(open(os.path.join(DATA, 'segments3d.geojson'), encoding='utf-8'))
SM_SEG = sm['segments']; SM_LIDS = sm.get('tmap_lids', {})

def official_path(tid, i):
    lids = SM_LIDS.get(str(tid))
    if not lids or i >= len(lids) or lids[i] is None: return None
    out = []
    for p in str(lids[i]).split('@'):
        L = int(p); q = SM_SEG.get(str(abs(L)))
        if not q or len(q) < 2: return None
        if L < 0: q = q[::-1]
        if out and geo_km(out[-1], q[0]) < 0.3: out.extend(q[1:])
        else: out.extend([x[:] for x in q])
    return out if len(out) >= 2 else None

def official_stops(tid, N):
    lids = SM_LIDS.get(str(tid))
    if not lids or len(lids) < N-1: return None
    stops = [None]*N
    for i in range(1, N):
        p = official_path(tid, i-1)
        if not p: continue
        stops[i-1] = p[0]; stops[i] = p[-1]
    return stops if any(stops) else None

# ---------- segments3d 距离网格(numpy) ----------
EDGE = []; GRID = defaultdict(list)
for f in segfc['features']:
    g = f['geometry']; co = g['coordinates']
    parts = co if g['type'] == 'MultiLineString' else [co]
    for q in parts:
        for k in range(1, len(q)):
            eid = len(EDGE); EDGE.append((q[k-1][0], q[k-1][1], q[k][0], q[k][1]))
            GRID[(int((q[k-1][0]+q[k][0])/2*20), int((q[k-1][1]+q[k][1])/2*20))].append(eid)
# 官方补缺轨道(引擎 boot 时会合并进同一 source, 回归需同样计入; 在网格 np 化之前追加)
for q in [e['coords'] for e in sm.get('extra_segments', [])]:
    for k in range(1, len(q)):
        eid = len(EDGE); EDGE.append((q[k-1][0], q[k-1][1], q[k][0], q[k][1]))
        GRID[(int((q[k-1][0]+q[k][0])/2*20), int((q[k-1][1]+q[k][1])/2*20))].append(eid)
EDGE = np.array(EDGE); GRID = {k: np.array(v) for k, v in GRID.items()}
def dist_batch(pts):
    P = np.asarray(pts, dtype=float); out = np.full(len(P), 1e9)
    for j in range(len(P)):
        x, y = P[j]; gx, gy = int(x*20), int(y*20); ids = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                v = GRID.get((gx+dx, gy+dy))
                if v is not None and len(v): ids.append(v)
        if not ids: continue
        E = EDGE[np.concatenate(ids)]
        rx, ry = E[:,2]-E[:,0], E[:,3]-E[:,1]; L2 = rx*rx+ry*ry
        tt = np.clip(((x-E[:,0])*rx+(y-E[:,1])*ry)/np.where(L2 == 0, 1, L2), 0, 1)
        cx, cy = E[:,0]+rx*tt, E[:,1]+ry*tt
        mlat = math.radians(y)
        ddx = (cx-x)*math.cos(mlat)*111.32; ddy = (cy-y)*110.57
        out[j] = np.sqrt(ddx*ddx+ddy*ddy).min()
    return out

# ---------- 参数 ----------
fn = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith('.json') else 'trains_wd.json'
args = [a for a in sys.argv[1:] if not a.endswith('.json')]
if len(args) == 1 and ':' in args[0]:
    a0, a1, st = map(float, args[0].split(':')); Ms = []; x = a0
    while x <= a1 + 1e-9: Ms.append(round(x, 3)); x += st
elif args:
    Ms = [float(x) for x in args]
else:
    Ms = [x*10+300 for x in range(100)]
tj = json.load(open(os.path.join(DATA, fn), encoding='utf-8'))

fb_samples = 0; zero_runs = 0; records = []
for uid, tr in enumerate(tj['T']):
    tid = str(tr['t']); v = tmaps.get(tid)
    if not v: continue
    s = v['s_jas']; N = len(s); ss = tr['s'].split(',')
    if len(ss) != 2*N-2: continue
    dep = [float(ss[0])]; arr = [0.0]*N
    for i in range(1, N):
        arr[i] = dep[i-1] + float(ss[2*i-1])
        dep.append(arr[i] + (float(ss[2*i]) if 2*i < len(ss) else 0))
    stops = official_stops(tr['t'], N)
    paths = [official_path(tr['t'], i) for i in range(N-1)]
    cums = [cum_len(p) if p else None for p in paths]
    for i in range(N-1):
        if arr[i+1]-dep[i] <= 0: zero_runs += 1
    w0, w1 = map(float, tr['w'].split(','))
    for M in Ms:
        if M < w0 or M > w1: continue
        i = 0
        while i < N-1 and M > arr[i+1]: i += 1
        if i < N-2 and arr[i+1]-dep[i] > 0 and arr[i+2]-dep[i+1] <= 0:
            dn = dep[i+1]-arr[i+1]; bn = min(0.5, max(0, dn))
            r0n = bn if bn > 0.05 else 0.25
            if M >= arr[i+2]-r0n and M <= arr[i+2]+1e-6: i += 1
        if i >= N-1: continue
        run = arr[i+1]-dep[i]; pos = None; state = 'run'
        if M < dep[i]-1e-9 and M > arr[i]-1e-9:
            pos = stops[i] if stops and stops[i] else None; state = 'dwell'
        if pos is None:
            if run > 0:
                if paths[i]: pos = pos_on(paths[i], cums[i], (M-dep[i])/run)
                else: fb_samples += 1; state = 'fallback'
            else:
                dw = dep[i]-arr[i]; bo = min(0.5, max(0, dw))
                r0 = bo if bo > 0.05 else 0.25; t0 = arr[i+1]-r0
                if paths[i]:
                    pos = pos_on(paths[i], cums[i], min(1, (M-t0)/r0)) if M >= t0 else paths[i][0]
                else: fb_samples += 1; state = 'fallback'
        if pos: records.append((uid, tid, tr, M, i, state, pos, s, N))

# ---------- 批量测距 + 统计 ----------
dists = []; off3 = []; jumps = []; last_pos = {}
watch = {'2793','10688','7361','3934','7323','7386','6193','14336','5631','10881','5526','6317','10345','1603'}
watch_tracks = defaultdict(list)
for b0 in range(0, len(records), 4096):
    chunk = records[b0:b0+4096]; ds = dist_batch([r[6] for r in chunk])
    for (uid, tid, tr, M, i, state, pos, s, N), d in zip(chunk, ds):
        dists.append(float(d))
        if d > 3: off3.append((tid, tr.get('i',''), s[i], s[i+1], round(M,1), round(float(d),2)))
        lp = last_pos.get(uid)
        if lp:
            dt = M-lp[0]
            if 0 < dt <= 1.2:
                vj = geo_km(lp[1], pos)/(dt/60)
                if vj > 400:
                    jumps.append((tid, tr.get('i',''), round(lp[0],2), round(M,2), s[i], s[i+1],
                                  round(geo_km(lp[1],pos),2), round(vj)))
        last_pos[uid] = (M, pos)
        if tid in watch and len(watch_tracks[tid]) < 6:
            watch_tracks[tid].append((round(M,1), s[i], s[i+1], state,
                                      [round(pos[0],4), round(pos[1],4)], round(float(d),2)))

dists.sort()
def pct(q): return dists[min(len(dists)-1, int(len(dists)*q))]
print(f"file={fn} tmap_covered={len(SM_LIDS)}")
print(f"samples={len(dists)} fallback_pos={fb_samples} zero_run_intervals={zero_runs}")
print(f"dist-to-track km: p50={pct(.5):.3f} p90={pct(.9):.3f} p99={pct(.99):.3f} max={dists[-1]:.2f}")
print(f"off-track(>3km): {len(off3)}   teleport jumps(>400km/h): {len(jumps)}")
for x in jumps[:20]: print("  JUMP", x)
for x in off3[:25]: print("  OFF", x)
print("--- watched trains ---")
for tid in sorted(watch_tracks, key=int):
    print(f"#{tid}")
    for w in watch_tracks[tid]: print("   ", w)

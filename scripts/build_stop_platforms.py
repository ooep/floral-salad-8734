#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_stop_platforms.py —— 生成按线站台停点表(仅“末端越过站台”的修剪类)

背景(2026-11-07 B 类调研):
- 无官方 lids 的区间里,stopC 距官方站坐标 >50m 的 35 段(82 行),绝大多数是
  「站心坐标」问题:轨道末端已经在真实站台上(末端→站台 ≤5m),只是离站心 200–350m。
  这类不动,避免把车移到别的站台。
- 真正可修的只有「几何末端越过站台」的一类:末端沿行进方向超出站台 30–80m。
  本脚本用 OSM 站台几何(station_platforms.geojson)找末端最近站台,取其最近点
  作为停点;运行期 app 按 tmap|到站序号 查表,把 stopC 钳到该点(snapToStops 会裁尾)。

输出:mini-japanrail-3d/data/stop_platforms.json
  {"version":1,"p":{"<tmapId>|<到站站序>":[lng,lat], ...}}
  —— 数据周更后 tmap id 可能变化,需随数据重建(见 build_static_assets.py)。
"""
import json, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, 'mini-japanrail-3d', 'data')
OUT = os.path.join(DATA, 'stop_platforms.json')

def geo_km(a, b):
    return math.hypot((b[0]-a[0]) * math.cos((a[1]+b[1])/2 * math.pi/180) * 111.32,
                      (b[1]-a[1]) * 110.57)

def norm(n):
    s = str(n)
    import re
    s = re.sub(r'\([^)]*\)', '', s).replace('ケ', 'ヶ')
    return s[:-1] if s.endswith('駅') else s

def main():
    tmaps = json.load(open(os.path.join(DATA, 'tmaps.json'), encoding='utf-8'))
    sm = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
    segfc = json.load(open(os.path.join(DATA, 'segments3d.geojson'), encoding='utf-8'))
    plfc = json.load(open(os.path.join(DATA, 'station_platforms.geojson'), encoding='utf-8'))
    ST, LIDS = sm['stations'], sm['tmap_lids']

    rings = []
    for f in plfc['features']:
        g = f['geometry']; pts = g['coordinates']
        ring = pts[0] if g['type'] == 'Polygon' else (pts[0][0] if g['type'] == 'MultiPolygon' else pts)
        if len(ring) >= 3: rings.append(ring)

    seg = {}
    for f in segfc['features']:
        g = f['geometry']; p = f['properties']
        parts = g['coordinates'] if g['type'] == 'MultiLineString' else [g['coordinates']]
        for co in parts:
            if len(co) < 2: continue
            seg.setdefault(norm(p.get('from')) + '|' + norm(p.get('to')), []).append(co)
            seg.setdefault(norm(p.get('to')) + '|' + norm(p.get('from')), []).append(co[::-1])

    def tbl(name):
        e = ST.get(norm(name)); return e.get('coord') if e else None

    def closest(p, ring):
        bd, bp = 1e18, None
        cosf = math.cos(p[1] * math.pi / 180)
        for k in range(len(ring)-1):
            a, b = ring[k], ring[k+1]
            ax = (b[0]-a[0]) * cosf * 111.32; ay = (b[1]-a[1]) * 110.57
            l2 = ax*ax + ay*ay
            t = 0 if l2 <= 0 else max(0, min(1, (((p[0]-a[0]) * cosf * 111.32) * ax + ((p[1]-a[1]) * 110.57) * ay) / l2))
            d = math.hypot((p[0]-a[0]) * cosf * 111.32 - ax*t, (p[1]-a[1]) * 110.57 - ay*t)
            if d < bd: bd, bp = d, [a[0] + (b[0]-a[0]) * t, a[1] + (b[1]-a[1]) * t]
        return bd * 1000, bp

    out = {}
    hit = 0
    # 2026-11-07 批准范围:仅中央本線 金山→名古屋 的 2 行(末端越过站台 43m)。
    # 其余“末端越过站台”的段未经批准不动(见 analysis 归档)。
    ONLY = {('金山(愛知県)', '名古屋')}
    for tid, tm in tmaps.items():
        jas = tm.get('s_jas') or []; N = len(jas)
        if N < 2: continue
        lids = LIDS.get(str(tid)) or [None] * (N-1)
        for i in range(N-1):
            if (jas[i], jas[i+1]) not in ONLY: continue
            if lids[i] is not None: continue                  # 官方 lids 段不需要
            A, B = norm(jas[i]), norm(jas[i+1])
            cands = seg.get(A + '|' + B)
            if not cands: continue
            cB = tbl(jas[i+1])
            if not cB: continue
            # 取端点在站附近(≤2km)的候选里、末端离站最近的一条(先按站坐标定向)
            best = None
            for co in cands:
                co = co if geo_km(co[-1], cB) <= geo_km(co[0], cB) else co[::-1]
                if min(geo_km(co[0], cB), geo_km(co[-1], cB)) > 2: continue
                d = geo_km(co[-1], cB)
                if best is None or d < best[0]: best = (d, co)
            if not best: continue
            co = best[1]
            if geo_km(co[-1], cB) * 1000 <= 50: continue      # 已由 stopC 投影/裁剪处理
            p1, p0 = co[-1], co[-2]
            cosf = math.cos((p0[1]+p1[1])/2 * math.pi/180)
            dx = (p1[0]-p0[0]) * cosf * 111.32; dy = (p1[1]-p0[1]) * 110.57
            L = math.hypot(dx, dy)
            if L < 1e-9: continue
            dx /= L; dy /= L
            # 找末端 80m 内最近的站台
            pb = None
            for ring in rings:
                d, bp = closest(p1, ring)
                if d <= 80 and (pb is None or d < pb[0]): pb = (d, bp)
            if not pb: continue
            rx = (pb[1][0]-p1[0]) * cosf * 111.32 * 1000
            ry = (pb[1][1]-p1[1]) * 110.57 * 1000
            along = rx*dx + ry*dy; lat = abs(rx*dy - ry*dx)
            # 只收「站台在后方(越过)」且横向 ≤5m:回剪,不涉及换站台
            if -80 <= along <= -30 and lat <= 5:
                out['%s|%d' % (tid, i+1)] = [round(pb[1][0], 6), round(pb[1][1], 6)]
                hit += 1
    payload = {'version': 1,
               'note': '按线站台停点(仅末端越过站台的修剪类);tmap|到站站序 -> [lng,lat]',
               'p': out}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    print('[stop_platforms] %d 条 -> %s (%.1f KB)' % (len(out), OUT, os.path.getsize(OUT)/1024))

if __name__ == '__main__':
    main()

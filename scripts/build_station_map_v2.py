#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_station_map_v2.py — 用官方几何生成权威车站坐标映射

输入:
  scripts/geo/ra_official/<rw_id>.json   (fetch_ra_geometry.py 产物)
  mini-japanrail-3d/data/tmaps.json      (页面实际使用的车次→站序)
  trains_wd/su/sa.json                   (速度/连续性校验)
输出:
  mini-japanrail-3d/data/station_map.json
    {
      version: 2,
      tmap_stops: { "<tmap_id>": [[lon,lat], ...] },   # 与 tmaps[t].s_jas 等长等序, 引擎主用
      tt:   { "<raw站名>": cid },                       # 站名检索(同名多簇时取最大簇)
      stations: { cid: {name, pref, coord, lines, tmaps:[...], derived} },
      missing_tmaps: [...],                             # 官方几何未覆盖的车次
      stats: {...}
    }

拼接规则: 区间 i (s[i-1]->s[i]) 的 l_id=L, 段点串 pts:
  L>0: s[i-1]=pts[0],  s[i]=pts[-1]
  L<0: s[i-1]=pts[-1], s[i]=pts[0]
相邻区间在共享站端点应重合(<300m), 否则记 seam 冲突。
"""
import json, math, os, re, glob, statistics, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "mini-japanrail-3d", "data")
GEO = os.path.join(ROOT, "scripts", "geo", "ra_official")

def geo_km(a, b):
    dx = (b[0]-a[0]) * math.cos((a[1]+b[1])/2 * math.pi/180) * 111.32
    dy = (b[1]-a[1]) * 110.57
    return math.hypot(dx, dy)

def pref_of(coord):
    """47 都道府県 point-in-polygon (100m 网格缓存); geojson 缺失时降级返回 ''"""
    import json as _j
    _p = os.path.join(ROOT, "scripts", "geo", "japan_pref.geojson")
    if not os.path.exists(_p):
        print("[warn] japan_pref.geojson 缺失, 无括号站 pref 留空(不影响几何/映射)")
        return lambda c: ''
    fc = _j.load(open(_p, encoding="utf-8"))
    grids = {}
    def pip(x, y, poly):
        inside = False; j = len(poly)-1
        for i in range(len(poly)):
            xi, yi = poly[i]; xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi):
                inside = not inside
            j = i
        return inside
    cache = {}
    def f(coord):
        x, y = coord; gx, gy = round(x*1000), round(y*1000)
        key = (gx, gy)
        if key in cache: return cache[key]
        res = ''
        for feat in fc['features']:
            nm = feat['properties'].get('nam_ja') or feat['properties'].get('name')
            for poly in feat['geometry']['coordinates']:
                ring = poly[0] if isinstance(poly[0][0], list) else poly
                if pip(x, y, ring):
                    res = nm; break
            if res: break
        cache[key] = res
        return res
    return f

_pref = pref_of(None)
PREFS = set(['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県',
             '埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県',
             '岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県',
             '鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県',
             '佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県'])
def bracket_of(raw):
    m = re.search(r'[（(]([^）)]*)[）)]', str(raw))
    return m.group(1) if m else ''

# ---------- 1. 汇总全部官方响应 ----------
segments = {}   # abs(l_id) -> pts list
seg_rw = {}     # abs(l_id) -> 首次出现该段的 rw 官方线名(段归属权, 用于补缺轨道命名)
tmap_geo = {}   # tmap_id -> (s_jas, l_ids[str], lines)
seam_bad = []
n_files = 0
for path in sorted(glob.glob(os.path.join(GEO, "*.json"))):
    bn = os.path.basename(path)
    if not bn[:-5].isdigit(): continue
    d = json.load(open(path, encoding="utf-8"))
    n_files += 1
    rw_id_here = int(bn[:-5])
    rw_name = ''
    for r in d.get("railways", []):
        if r.get("rw_id") == rw_id_here: rw_name = r.get("name_ja", '')
    if not rw_name and d.get("railways"): rw_name = d["railways"][0].get("name_ja", '')
    for L in d.get("line", []):
        c = L["coords"]
        pts = [(round(c[i], 6), round(c[i+1], 6)) for i in range(0, len(c)-1, 2)]
        if len(pts) >= 2:
            lid = abs(int(L["l_id"]))
            if lid not in segments: segments[lid] = pts   # 同 l_id 多 rw 重复, 保留首次
            if lid not in seg_rw and rw_name: seg_rw[lid] = rw_name
    rw_lines = [r.get("name_ja") for r in d.get("railways", [])]
    for t in d.get("tmaps", []):
        tid = str(t["tmap_id"])
        tmap_geo[tid] = (t.get("s_jas", []), [str(x) for x in t.get("l_ids", [])], rw_lines)

def resolve_pts(lid_str):
    """区间 id: 单段 '1068' 或复合 '1068@3896@7917'(多段首尾相接); 每段符号独立定向"""
    out = []
    for x in str(lid_str).split('@'):
        L = int(x); q0 = segments.get(abs(L))
        if not q0: return None
        q = q0[::-1] if L < 0 else q0
        if out and geo_km(out[-1], q[0]) < 0.3:
            out.extend(q[1:])
        else:
            out.extend(q)
    return out or None

# ---------- 2. 逐 tmap 拼站坐标 + 区间折线(按站序方向) ----------
tmap_stops = {}     # tid -> [coord|None,...]
tmap_paths = {}     # tid -> [ 区间折线, ...] 长度 N-1, 方向 s[i-1]->s[i]
raw_obs = {}        # raw -> [coord,...]   (所有出现位置)
raw_lines = {}
for tid, (s, lids, rwl) in tmap_geo.items():
    coords = [None] * len(s)
    paths = [None] * max(0, len(s) - 1)
    if len(lids) >= len(s) - 1:
        prev_end = None
        for i in range(1, len(s)):
            lid = lids[i-1]
            pts = resolve_pts(lid)
            if not pts: continue
            a, b = pts[0], pts[-1]            # 方向已在逐段定向时处理
            if prev_end is not None and geo_km(prev_end, a) > 0.5:
                seam_bad.append((tid, s[i-1], round(geo_km(prev_end, a), 2)))
            coords[i-1] = list(a)
            coords[i] = list(b)
            paths[i-1] = [[p[0], p[1]] for p in pts]
            prev_end = b
    tmap_stops[tid] = coords
    tmap_paths[tid] = paths
    for raw, c in zip(s, coords):
        if c:
            raw_obs.setdefault(raw, []).append(tuple(c))
            raw_lines.setdefault(raw, set()).update(x for x in rwl if x)

# ---------- 3. canonical 聚类(同 raw 名, 1km 网格凝聚) ----------
def cluster_obs(obs, r=1.0):
    clusters = []   # [pts]
    for p in obs:
        for cl in clusters:
            if any(geo_km(p, m) < r for m in cl):
                cl.append(p); break
        else:
            clusters.append([p])
    # 合并质心接近的簇(迭代到稳定)
    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            for j in range(i+1, len(clusters)):
                ci = (statistics.mean(p[0] for p in clusters[i]), statistics.mean(p[1] for p in clusters[i]))
                cj = (statistics.mean(p[0] for p in clusters[j]), statistics.mean(p[1] for p in clusters[j]))
                if geo_km(ci, cj) < r:
                    clusters[i].extend(clusters[j]); del clusters[j]; changed = True; break
            if changed: break
    return clusters

stations = {}
tt = {}
cid_by_raw_cluster = {}
for raw, obs in raw_obs.items():
    base = re.sub(r'[（(][^）)]*[）)]', '', raw)
    br = bracket_of(raw)
    cl = cluster_obs(obs)
    # 簇按观测数排序(主簇在前)
    cl.sort(key=lambda c: -len(c))
    cids = []
    for k, c in enumerate(cl):
        lon = round(statistics.mean(p[0] for p in c), 6)
        lat = round(statistics.mean(p[1] for p in c), 6)
        pref = br if br in PREFS else _pref((lon, lat))
        suffix = '' if (len(cl) == 1 and not br) else (br or pref or str(k+1))
        cid = f"{base}({suffix})" if suffix else base
        if cid in stations and geo_km(stations[cid]['coord'], (lon, lat)) > 1:
            cid = f"{base}({suffix}#{k+1})"
        n = 1
        base_cid = cid
        while cid in stations and geo_km(stations[cid]['coord'], (lon, lat)) > 1:
            n += 1; cid = f"{base_cid}#{n}"
        stations[cid] = {'name': base, 'pref': pref, 'coord': [lon, lat],
                         'lines': sorted(raw_lines.get(raw, [])), 'obs': len(c), 'derived': False}
        cids.append(cid)
    tt[raw] = cids[0]
    cid_by_raw_cluster[raw] = cids

# ---------- 4. 页面 tmaps 覆盖率 ----------
page_tmaps = json.load(open(os.path.join(DATA, "tmaps.json"), encoding="utf-8"))
missing_tmaps = [tid for tid in page_tmaps if tid not in tmap_stops]
incomplete = [tid for tid, c in tmap_stops.items() if any(x is None for x in c)]

# ---------- 5. 速度校验(全部三时刻) ----------
def load_trains(fn):
    j = json.load(open(os.path.join(DATA, fn), encoding="utf-8"))
    out = []
    for t in j['T']:
        v = page_tmaps.get(str(t['t']))
        if not v: continue
        s = v['s_jas']; ss = t['s'].split(',')
        if len(ss) != 2*len(s)-2: continue
        out.append((str(t['t']), s, ss))
    return out
trips_all = {}
for fn in ['trains_wd.json', 'trains_su.json', 'trains_sa.json']:
    for tid, s, ss in load_trains(fn):
        trips_all[tid] = (s, ss)
speed_bad = []
for tid, (s, ss) in trips_all.items():
    co = tmap_stops.get(tid)
    if not co or len(co) != len(s): continue
    for i in range(1, len(s)):
        run = float(ss[2*i-1])
        if run > 0 and co[i-1] and co[i]:
            v = geo_km(co[i-1], co[i]) / (run/60)
            if v > 450: speed_bad.append((tid, s[i-1], s[i], round(geo_km(co[i-1], co[i]),1), run, round(v)))

# ---------- 6. 输出(交付文件不含 tmap_stops: 引擎用 segments+tmap_lids 现拼, 省体积) ----------
seg_out = {str(k): [[round(p[0], 6), round(p[1], 6)] for p in pts] for k, pts in segments.items()}
tmap_lids_out = {tid: tmap_geo[tid][1][:len(tmap_geo[tid][0])-1]
                 for tid in tmap_geo if tid in tmap_stops}

# ---------- 5b. 官方有、本站地图缺的轨道段 -> extra_segments/extra_stations ----------
# 车沿官方几何跑, 若本站 segments3d 没画该段(新开线/遗漏私铁), 车会在空白地面跑;
# 以官方权威几何补画(不是改线型, 是补缺线), 引擎 boot 时合并进同一 GeoJSON source。
import numpy as np
from collections import Counter, defaultdict as _dd
_EDGE = []; _GRID = _dd(list)
_our = json.load(open(os.path.join(DATA, "segments3d.geojson"), encoding="utf-8"))
for _f in _our['features']:
    _g = _f['geometry']; _co = _g['coordinates']
    for _q in (_co if _g['type'] == 'MultiLineString' else [_co]):
        for _k in range(1, len(_q)):
            _eid = len(_EDGE); _EDGE.append((_q[_k-1][0], _q[_k-1][1], _q[_k][0], _q[_k][1]))
            _GRID[(int((_q[_k-1][0]+_q[_k][0])/2*20), int((_q[_k-1][1]+_q[_k][1])/2*20))].append(_eid)
_EDGE = np.array(_EDGE); _GRID = {k: np.array(v) for k, v in _GRID.items()}
def _dist_batch(pts):
    P = np.asarray(pts, float); out = np.full(len(P), 1e9)
    for j in range(len(P)):
        x, y = P[j]; gx, gy = int(x*20), int(y*20); ids = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                v = _GRID.get((gx+dx, gy+dy))
                if v is not None and len(v): ids.append(v)
        if not ids: continue
        E = _EDGE[np.concatenate(ids)]
        rx, ry = E[:,2]-E[:,0], E[:,3]-E[:,1]; L2 = rx*rx+ry*ry
        tt = np.clip(((x-E[:,0])*rx+(y-E[:,1])*ry)/np.where(L2 == 0, 1, L2), 0, 1)
        cx, cy = E[:,0]+rx*tt, E[:,1]+ry*tt
        ddx = (cx-x)*math.cos(math.radians(y))*111.32; ddy = (cy-y)*110.57
        out[j] = np.sqrt(ddx*ddx+ddy*ddy).min()
    return out
# 段 -> 使用它的(车次,区间idx)
seg_use = _dd(list)
for tid, lids in tmap_lids_out.items():
    for i, tok in enumerate(lids):
        for p in str(tok).split('@'):
            seg_use[str(abs(int(p)))].append((tid, i))
EXTRA_COLORS = {'西鉄甘木線': '#d01f3c', '大牟田線': '#d01f3c', '太宰府線': '#d01f3c',
                '和歌山港線': '#0057a5', '北神線': '#009966', '西神線': '#009966',
                '山手線': '#009966', '北大阪急行線': '#0099cc', '南北線': '#0099cc',
                '中央線': '#019a69', 'けいはんな線': '#019a69'}
extra_segments = []; missing_seg_ids = set()
for sid, pts in seg_out.items():
    sample = [pts[round(k*(len(pts)-1)/6)] for k in range(7)]
    ds = _dist_batch(sample)
    if int((ds > 0.3).sum()) < 5: continue
    missing_seg_ids.add(sid)
    uses = seg_use.get(sid, [])
    line_c, name_a, name_b = Counter(), Counter(), Counter()
    for tid, i in uses:
        tv = page_tmaps.get(tid)
        if tv:
            for ln in tv.get('lines', []): line_c[ln] += 1
            ss2 = tv['s_jas']
            if i < len(ss2): name_a[ss2[i]] += 1
            if i+1 < len(ss2): name_b[ss2[i+1]] += 1
    line = seg_rw.get(int(sid), '') or (line_c.most_common(1)[0][0] if line_c else '')
    color = next((c for ln, c in EXTRA_COLORS.items() if ln and ln in line), '#8b94a3')
    fr = name_a.most_common(1)[0][0] if name_a else ''
    to = name_b.most_common(1)[0][0] if name_b else ''
    extra_segments.append({'id': int(sid), 'from': fr, 'to': to, 'line': line,
                           'color': color, 'kind': 'rail', 'coords': pts})
# 缺失段端点站: 本站 stations3d 同名 1km 内没有才补
_our_sta = json.load(open(os.path.join(DATA, "stations3d.geojson"), encoding="utf-8"))
_sta_by_name = _dd(list)
for _f in _our_sta['features']:
    _p = _f['properties']; _sta_by_name[_p.get('station', '')].append(_f['geometry']['coordinates'])
_extra_sta = {}
for e in extra_segments:
    for nm, coord in ((e['from'], e['coords'][0]), (e['to'], e['coords'][-1])):
        have = _sta_by_name.get(nm, [])
        if any(geo_km(coord, q) < 1 for q in have): continue
        key = f"{nm}@{round(coord[0],3)},{round(coord[1],3)}"
        if key not in _extra_sta:
            _extra_sta[key] = {'name': nm, 'coord': coord, 'line': e['line']}
extra_stations = list(_extra_sta.values())

for c in stations.values(): c.pop('obs', None)
out = {'version': 2,
       'generated_at': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds'),
       'source': 'official railway geometry',
       'geo_files': n_files,
       'tmap_lids': tmap_lids_out,
       'segments': seg_out,
       'extra_segments': extra_segments,
       'extra_stations': extra_stations,
       'tt': tt,
       'stations': stations,
       'missing_tmaps': missing_tmaps,
       'incomplete_tmaps': incomplete,
       'seam_conflicts': seam_bad[:200],
       'speed_violations': speed_bad[:200],
       'stats': {'geo_files': n_files, 'official_segments': len(segments),
                 'tmaps_with_geo': len(tmap_stops), 'page_tmaps': len(page_tmaps),
                 'missing_tmaps': len(missing_tmaps), 'incomplete_tmaps': len(incomplete),
                 'raw_stations': len(raw_obs), 'canonical_stations': len(stations),
                 'seam_conflicts': len(seam_bad), 'speed_violations': len(speed_bad),
                 'extra_segments': len(extra_segments), 'extra_stations': len(extra_stations)}}
json.dump(out, open(os.path.join(DATA, "station_map.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(',', ':'))
# 完整校验报告(含每站坐标, 不部署)
report = {'stats': out['stats'], 'tmap_stops':
          {tid: [[round(c[0],6), round(c[1],6)] if c else None for c in co] for tid, co in tmap_stops.items()},
          'seam_conflicts': seam_bad, 'speed_violations': speed_bad,
          'missing_tmaps': missing_tmaps, 'incomplete_tmaps': incomplete}
json.dump(report, open(os.path.join(ROOT, "scripts", "geo", "station_map_report.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(',', ':'))
print(json.dumps(out['stats'], ensure_ascii=False, indent=1))
print("speed bad sample:", speed_bad[:8])
print("seam bad sample:", seam_bad[:8])
print("missing tmaps sample:", missing_tmaps[:10])

#!/usr/bin/env python3
# build_leg_orm_map.py v3.1 严格线名版 — 简易腿 → 真实 ORM 股道连通路径(Dijkstra)
# 与 v3 差别:canon 只做「JR前缀/本線→線」归一(严禁族包含),颜色通道整体禁用 ——
# 多线并行区(东京站)「山手貨物線→山手線」「東海道橙↔中央橙」式错配是列车窜线根因。
import json, math, os, re, heapq

ROOT = os.path.join(os.path.dirname(__file__), '..', 'mini-japanrail-3d', 'data')
DENS = 0.08
DEV_MAX = 0.070
END_MAX = 0.150

def norm_line(s):
    return re.sub(r'\s*[（(].*?[)）]\s*', '', s or '').strip()

def fam(s):
    s = norm_line(s)
    s = re.sub(r'^(JR|ＪＲ)\s*', '', s)
    return s.replace('本線', '線').replace(' ', '')

def geo_km(a, b):
    dx = (a[0]-b[0]) * math.cos(math.radians((a[1]+b[1])/2)) * 111.32
    dy = (a[1]-b[1]) * 110.57
    return math.hypot(dx, dy)

def densify(co, step=DENS):
    pts = [co[0]]
    for k in range(1, len(co)):
        a, b = co[k-1], co[k]
        L = geo_km(a, b)
        n = max(1, int(L/step))
        for j in range(1, n+1):
            pts.append([a[0]+(b[0]-a[0])*j/n, a[1]+(b[1]-a[1])*j/n])
    return pts

class Grid:
    def __init__(self, cell=0.005):
        self.cell = cell; self.d = {}
    def add(self, pt):
        k = (int(pt[0]/self.cell), int(pt[1]/self.cell))
        self.d.setdefault(k, []).append(pt)
    def near(self, pt, maxd):
        gx, gy = int(pt[0]/self.cell), int(pt[1]/self.cell)
        out = []
        r = max(1, int(maxd/(self.cell*111))+1)
        for dx in range(-r, r+1):
            for dy in range(-r, r+1):
                for q in self.d.get((gx+dx, gy+dy), ()):
                    dd = geo_km(pt, q)
                    if dd <= maxd: out.append(dd)
        return out

def main():
    segs = json.load(open(os.path.join(ROOT, 'segments3d.geojson'), encoding='utf-8'))['features']
    seg_fams = {}
    for f in segs: seg_fams.setdefault(fam(f['properties'].get('line','')), f['properties'].get('line',''))
    orm = []
    for part in (0, 1):
        for f in json.load(open(os.path.join(ROOT, f'orm_tracks.{part}.geojson'), encoding='utf-8'))['features']:
            g = f['geometry']
            lines = [g['coordinates']] if g['type'] == 'LineString' else (g['coordinates'] if g['type'] == 'MultiLineString' else [])
            nm = norm_line(f['properties'].get('line',''))
            for co in lines:
                if len(co) >= 2: orm.append((nm, co))
    print('ORM polylines:', len(orm), flush=True)
    def canon(nm):
        if not nm: return None
        fm = fam(nm)
        if fm in seg_fams: return seg_fams[fm]
        for sf, std in seg_fams.items():
            if not sf: continue
            if sf.replace('本線','線') == fm or fm.replace('本線','線') == sf: return std
        return None
    by_line = {}
    for nm, co in orm:
        std = canon(nm)
        if std: by_line.setdefault(std, []).append(co)

    out, stats = {}, {'ok':0, 'skip':0, 'nocand':0}
    for f in segs:
        p = f['properties']
        ln = p.get('line','')
        key = f"{p.get('from','')}|{p.get('to','')}|{ln}"
        co = f['geometry']['coordinates']
        if f['geometry']['type'] == 'MultiLineString': co = [pt for part in co for pt in part]
        if len(co) < 2 or ln not in by_line: stats['nocand'] += 1; continue
        cand = by_line[ln]
        ref = densify(co)
        grid = Grid()
        for q in ref: grid.add(q)
        edges = []
        for eco in cand:
            if len(eco) > 400: continue
            ds = []
            for q in densify(eco, 0.12):
                ns = grid.near(q, DEV_MAX)
                if not ns: ds = None; break
                ds.append(min(ns))
            if not ds: continue
            dev = sum(ds)/len(ds)
            if dev > DEV_MAX: continue
            L = sum(geo_km(eco[k-1], eco[k]) for k in range(1, len(eco)))
            if L < 0.005: continue
            edges.append({'co': eco, 'dev': dev, 'len': L})
        if not edges: stats['nocand'] += 1; continue
        nodeOf, nodes = {}, []
        def nid(pt):
            k = (round(pt[0]/0.00005), round(pt[1]/0.00005))
            if k not in nodeOf:
                nodeOf[k] = len(nodes); nodes.append(pt)
            return nodeOf[k]
        adj = {}
        for ei, e in enumerate(edges):
            a, b = nid(e['co'][0]), nid(e['co'][-1])
            cost = e['len'] * (1 + e['dev']/0.05) + 0.02
            adj.setdefault(a, []).append((b, cost, ei, 1))
            adj.setdefault(b, []).append((a, cost, ei, -1))
        startPts, endPts = co[0], co[-1]
        starts = [nid(e['co'][0]) for e in edges if geo_km(e['co'][0], startPts) < END_MAX] + \
                 [nid(e['co'][-1]) for e in edges if geo_km(e['co'][-1], startPts) < END_MAX]
        goals = set([nid(e['co'][0]) for e in edges if geo_km(e['co'][0], endPts) < END_MAX] + \
                    [nid(e['co'][-1]) for e in edges if geo_km(e['co'][-1], endPts) < END_MAX])
        if not starts or not goals: stats['skip'] += 1; continue
        dist, prev, pq = {}, {}, []
        for s in set(starts): dist[s] = 0; heapq.heappush(pq, (0, s))
        found = None
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, 1e18): continue
            if u in goals: found = u; break
            for v, c, ei, dirn in adj.get(u, []):
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd; prev[v] = (u, ei, dirn); heapq.heappush(pq, (nd, v))
        if found is None: stats['skip'] += 1; continue
        seq = []
        u = found
        while u in prev:
            pu, ei, dirn = prev[u]; seq.append((ei, dirn)); u = pu
        seq.reverse()
        path = []
        for ei, dirn in seq:
            eco = edges[ei]['co']
            sp = eco if dirn > 0 else eco[::-1]
            for q in sp:
                if not path or geo_km(path[-1], q) > 0.003: path.append(q)
        if len(path) < 2: stats['skip'] += 1; continue
        plen = sum(geo_km(path[k-1], path[k]) for k in range(1, len(path)))
        slen = sum(geo_km(co[k-1], co[k]) for k in range(1, len(co)))
        if slen > 0.3 and (plen < slen*0.6 or plen > slen*1.8+1.0): stats['skip'] += 1; continue
        if geo_km(path[0], startPts) > 0.4 or geo_km(path[-1], endPts) > 0.4: stats['skip'] += 1; continue
        out[key] = [[round(q[0],5), round(q[1],5)] for q in path]
        stats['ok'] += 1
        if stats['ok'] % 300 == 0: print('ok', stats['ok'], flush=True)
    dst = os.path.join(ROOT, 'leg_orm_map.json')
    json.dump({'v':3, 'strict': True, 'legs':out}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',',':'))
    print('DONE', stats, 'sizeMB=%.1f' % (os.path.getsize(dst)/1048576), flush=True)

if __name__ == '__main__':
    main()

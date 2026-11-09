#!/usr/bin/env python3
# build_leg_orm_map.py — 简易腿(segments3d) → ORM 详细股道走廊映射(v2 双通道)
# 产物 mini-japanrail-3d/data/leg_orm_map.json:
#   {"v":1, "legs": {"from|to|line": [[lng,lat],...]}}
# 候选通道 = 线名族(去JR前缀/本線→線/族包含) ∪ 线路色(官方线路色,用户已核验同源),
# 空间 80m 内最近者胜;前端 ormEnabled 时把区间中段替换为该映射。
# 质量门:吸附覆盖率>=0.55 且平均偏差<=32m,不合格段不输出(前端回退简易腿)。
import json, math, os, re

ROOT = os.path.join(os.path.dirname(__file__), '..', 'mini-japanrail-3d', 'data')
MAXD = 0.080
DENS = 0.080
COVER_MIN = 0.55
AVG_MAX = 0.032

def norm_line(s):
    if not s: return ''
    return re.sub(r'\s*[（(].*?[)）]\s*', '', s).strip()

def fam(s):
    s = norm_line(s)
    s = re.sub(r'^(JR|ＪＲ)\s*', '', s)
    s = s.replace('本線', '線').replace(' ', '')
    return s

def geo_km(a, b):
    dx = (a[0]-b[0]) * math.cos(math.radians((a[1]+b[1])/2)) * 111.32
    dy = (a[1]-b[1]) * 110.57
    return math.hypot(dx, dy)

def main():
    segs = json.load(open(os.path.join(ROOT, 'segments3d.geojson'), encoding='utf-8'))['features']
    seg_fams = {}
    for f in segs:
        ln = f['properties'].get('line', '')
        seg_fams.setdefault(fam(ln), ln)
    orm = []
    for part in (0, 1):
        p = os.path.join(ROOT, f'orm_tracks.{part}.geojson')
        for f in json.load(open(p, encoding='utf-8'))['features']:
            g = f['geometry']
            if g['type'] == 'LineString': lines = [g['coordinates']]
            elif g['type'] == 'MultiLineString': lines = g['coordinates']
            else: continue
            nm = norm_line(f['properties'].get('line', ''))
            col = (f['properties'].get('color') or '').lower()
            for co in lines:
                if len(co) >= 2: orm.append((nm, col, co))
    print(f'ORM polylines: {len(orm)}', flush=True)

    def canon(nm):
        if not nm: return None
        fm = fam(nm)
        if fm in seg_fams: return seg_fams[fm]
        shink = '新幹線' in fm
        for sf, std in seg_fams.items():
            if not sf or len(sf) < 2 or len(fm) < 2: continue
            if ('新幹線' in sf) != shink: continue
            if sf in fm or fm in sf: return std
        return None

    by_line, by_color = {}, {}
    for nm, col, co in orm:
        std = canon(nm)
        if std: by_line.setdefault(std, []).append(co)
        if col: by_color.setdefault(col, []).append(co)

    GRID = 0.01
    def build_idx(polys):
        idx = {}
        for pi, co in enumerate(polys):
            for ki, pt in enumerate(co):
                key = (int(pt[0]/GRID), int(pt[1]/GRID))
                idx.setdefault(key, []).append((pi, ki))
        return idx
    idx_line = {ln: build_idx(ps) for ln, ps in by_line.items()}
    idx_color = {c: build_idx(ps) for c, ps in by_color.items()}
    print(f'line groups: {len(by_line)}, color groups: {len(by_color)}', flush=True)

    def nearest_in(polys, idx, pt, bd):
        gx, gy = int(pt[0]/GRID), int(pt[1]/GRID)
        best = None
        for r in range(0, 9):
            found = False
            for dx in range(-r, r+1):
                for dy in range(-r, r+1):
                    if max(abs(dx), abs(dy)) != r: continue
                    for pi, ki in idx.get((gx+dx, gy+dy), ()):
                        q = polys[pi][ki]
                        d = geo_km(pt, q)
                        if d < bd: best, bd = q, d; found = True
            if found and r >= 1: break
        return best, bd

    out, stats = {}, {'ok':0, 'skip':0, 'nocand':0}
    for f in segs:
        p = f['properties']
        ln = p.get('line', '')
        col = (p.get('color') or '').lower()
        key = f"{p.get('from','')}|{p.get('to','')}|{ln}"
        co = f['geometry']['coordinates']
        if f['geometry']['type'] == 'MultiLineString':
            co = [pt for part in co for pt in part]
        if len(co) < 2: stats['nocand'] += 1; continue
        candL = (ln in by_line, col in by_color)
        if not any(candL): stats['nocand'] += 1; continue
        pts = [co[0]]
        for k in range(1, len(co)):
            a, b = co[k-1], co[k]
            L = geo_km(a, b)
            n = max(1, int(L / DENS))
            for j in range(1, n+1):
                if len(pts) > 1500: break
                pts.append([a[0]+(b[0]-a[0])*j/n, a[1]+(b[1]-a[1])*j/n])
        snapped, ds = [], []
        for pt in pts:
            bd = MAXD; best = None
            if ln in by_line:
                best, bd = nearest_in(by_line[ln], idx_line[ln], pt, bd)
            if col in by_color:
                b2, bd2 = nearest_in(by_color[col], idx_color[col], pt, bd)
                if b2 is not None: best, bd = b2, bd2
            if best is not None: snapped.append(best); ds.append(bd)
            else: snapped.append(pt); ds.append(None)
        good = [d for d in ds if d is not None]
        cover = len(good) / max(1, len(ds))
        avg = sum(good)/len(good) if good else 1e9
        if cover < COVER_MIN or avg > AVG_MAX:
            stats['skip'] += 1; continue
        clean = [snapped[0]]
        for k in range(1, len(snapped)):
            if geo_km(clean[-1], snapped[k]) > 0.15:
                clean.append(pts[k])
            if geo_km(clean[-1], snapped[k]) > 0.004:
                clean.append(snapped[k])
        if len(clean) < 2: stats['skip'] += 1; continue
        out[key] = [[round(q[0],5), round(q[1],5)] for q in clean]
        stats['ok'] += 1
        if stats['ok'] % 500 == 0: print('ok', stats['ok'], flush=True)
    dst = os.path.join(ROOT, 'leg_orm_map.json')
    json.dump({'v':1, 'legs':out}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',',':'))
    print('DONE', stats, 'sizeMB=%.1f' % (os.path.getsize(dst)/1048576), flush=True)

if __name__ == '__main__':
    main()

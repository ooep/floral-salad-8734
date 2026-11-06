#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10 级1 几何/站表补丁（纯数据，幂等）。

作用对象：mini-japanrail-3d/data/{segments3d.geojson,stations3d.geojson}
—— 这两个文件不在 refresh.yml / deploy.yml 的任何构建步骤里重新生成，
   直接改产物即可长期生效（详见 round10/REPORT.md「生效路径」）。

补丁内容：
  A. 七隈線：删除 1 条粗化段（键名 姪浜|福岡空港 两端皆错），
     按官方 station_map.segments 重建 15 条相邻站对段 + 2023 延伸段 2 条
     （天神南→櫛田神社前→博多），共 17 条。
  B. 山陰線：补 松江|玉造温泉（由 松江|乃木 + 乃木|玉造温泉 顶点拼接）。
  C. 山陽線：补 姫路|東姫路、東姫路|御着（保留 御着|姫路 原直连段，
     另在其東姫路投影顶点处切出两条停站子段）。
  D. 山陽線：① 清理「はりま勝原」错名簇（上郡 被误写成 はりま勝原 的重复段与焊点桩）；
     ② 对 7 个跨城同名站（本郷/島田/戸田/下松/大門/曽根/大久保）补「跨过被污染
     站名槽位」的贯通段，顶点全部由既有相邻段拼接，无新造几何。
  E. 站表补 櫛田神社前（官方 8967 尾点 / 6337 首点的接缝点，
     与 station_map.stations 的官方坐标一致）。
  「橋本」只判定不改（见 REPORT）。

用法：
  python3 scripts/fix_level1_geometry.py --data mini-japanrail-3d/data          # 打补丁
  python3 scripts/fix_level1_geometry.py --data mini-japanrail-3d/data --check  # 只校验
"""
import argparse
import json
import math
import sys

SEVEN_LINE = '七隈線'
TOL = 1e-6


def load(p):
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def save(p, obj):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=True)


def dist_m(a, b):
    return math.hypot((b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2)) * 111320.0,
                      (b[1] - a[1]) * 110570.0)


def mkseg(frm, to, line, coords, color, op, kind='鉄道'):
    return {
        'type': 'Feature',
        'properties': {'line': line, 'from': frm, 'color': color, 'op': op, 'to': to, 'kind': kind},
        'geometry': {'type': 'LineString', 'coordinates': coords},
    }


def find(features, frm, to, line):
    for f in features:
        p = f['properties']
        if p.get('from') == frm and p.get('to') == to and p.get('line') == line:
            return f
    return None


def find2(features, a, b, line):
    """按无序站对找段（from/to 方向不定）。"""
    for f in features:
        p = f['properties']
        if p.get('line') != line:
            continue
        if {p.get('from'), p.get('to')} == {a, b}:
            return f
    return None


def nearest_idx(coords, pt):
    return min(range(len(coords)), key=lambda i: dist_m(coords[i], pt))


def compose(fa, fb, gap_m=600):
    """把两段拼成一段：枚举 4 种方向，取端点距离最小者；接缝 <gap_m 则去重接缝点。"""
    best = None
    for ra in (False, True):
        ca = list(reversed(fa)) if ra else list(fa)
        for rb in (False, True):
            cb = list(reversed(fb)) if rb else list(fb)
            d = dist_m(ca[-1], cb[0])
            if best is None or d < best[0]:
                best = (d, ca, cb)
    d, ca, cb = best
    if d >= gap_m:
        raise ValueError('接缝 %.0f m 超限，拒绝拼接' % d)
    return ca + cb[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='mini-japanrail-3d/data 目录')
    ap.add_argument('--check', action='store_true', help='只校验，不写盘')
    opts = ap.parse_args()
    D = opts.data.rstrip('/') + '/'
    seg_p, sta_p = D + 'segments3d.geojson', D + 'stations3d.geojson'
    seg, sta = load(seg_p), load(sta_p)
    F, S = seg['features'], sta['features']
    log = []

    def add(feat, tag):
        F.append(feat)
        p = feat['properties']
        log.append('  + %-14s %-26s %3d pts' % (tag, p['from'] + '|' + p['to'], len(feat['geometry']['coordinates'])))

    # ---- A. 七隈線：粗化段替换为官方 16 段 + 延伸段 2 段 ----
    coarse = [f for f in F
              if f['properties'].get('line') == SEVEN_LINE
              and f['properties'].get('from') == '姪浜' and f['properties'].get('to') == '福岡空港']
    if coarse and not opts.check:
        sm = load(D + 'station_map.json')
        tmap = load(D + 'tmaps.json')['1699']
        color = coarse[0]['properties'].get('color') or '#008B4F'
        op = coarse[0]['properties'].get('op') or '福岡市'
        lids = [int(str(x).split('@')[0]) for x in sm['tmap_lids']['1699']]
        names = tmap['s_jas']
        for f in coarse:
            F.remove(f)
            log.append('  - 七隈線        姪浜|福岡空港 粗化段删除（%d pts）'
                       % len(f['geometry']['coordinates']))
        made = 0
        for i, lid in enumerate(lids):
            if lid <= 0:
                continue
            co = sm['segments'].get(str(lid)) or sm['segments'].get(lid)
            if not co:
                sys.exit('station_map.segments 缺少 l_id=%d' % lid)
            frm, to = names[i], names[i + 1]
            if find(F, frm, to, SEVEN_LINE):
                made += 1
                continue
            add(mkseg(frm, to, SEVEN_LINE, co, color, op), '七隈線重建')
            made += 1
        log.append('  七隈線重建 %d 段' % made)

    # ---- B. 松江|玉造温泉 ----
    if not find(F, '松江', '玉造温泉', '山陰線'):
        f1 = find(F, '松江', '乃木', '山陰線')
        f2 = find(F, '乃木', '玉造温泉', '山陰線')
        if f1 and f2 and not opts.check:
            co = compose(f1['geometry']['coordinates'], f2['geometry']['coordinates'])
            add(mkseg('松江', '玉造温泉', '山陰線', co, f1['properties']['color'], f1['properties']['op']), '山陰線贯通')

    # ---- C. 東姫路：在 御着|姫路 上断开 ----
    east = next((f['geometry']['coordinates'] for f in S
                 if f['properties'].get('station') == '東姫路'), None)
    while east and not (find(F, '東姫路', '御着', '山陽線') and find(F, '東姫路', '姫路', '山陽線')) and not opts.check:
        base = find(F, '御着', '姫路', '山陽線')
        if not base:
            break
        co = base['geometry']['coordinates']
        k = nearest_idx(co, east)
        if not (1 <= k < len(co) - 1):
            break
        pr = base['properties']
        add(mkseg('東姫路', '御着', '山陽線', list(reversed(co[:k + 1])), pr['color'], pr['op']), '山陽線東姫路')
        add(mkseg('東姫路', '姫路', '山陽線', co[k:], pr['color'], pr['op']), '山陽線東姫路')
        log.append('  御着|姫路 断面 idx=%d/%d，顶点距東姫路 %.1f m'
                   % (k, len(co) - 1, dist_m(co[k], east)))
        break

    # ---- D1. 「はりま勝原」错名簇：把 上郡 误写成 はりま勝原 的段改回正名 ----
    #     现实里 はりま勝原 只和 英賀保/網干 相邻；凡与 三石/上郡/苔縄/有年 成对、
    #     且端点落在上郡站坐标附近者，一律改回 上郡（同键已存在则删除该重复段）。
    JUNK_NB = {'三石', '上郡', '苔縄', '有年'}
    ue = next((f['geometry']['coordinates'] for f in S
               if f['properties'].get('station') == '上郡'), None)
    if ue:
        for f in list(F):
            p = f['properties']
            if 'はりま勝原' not in (p.get('from'), p.get('to')):
                continue
            other = p['to'] if p['from'] == 'はりま勝原' else p['from']
            if other not in JUNK_NB:
                continue
            co = f['geometry']['coordinates']
            at_ue = min(dist_m(co[0], ue), dist_m(co[-1], ue)) < 300
            if opts.check:
                continue
            if not at_ue:
                sys.exit('拒绝改键：%s 端点不在上郡附近' % (p['from'] + '|' + p['to']))
            if find2(F, '上郡', other, p['line']):
                F.remove(f)
                log.append('  - 错名簇          %-24s %3d pts（同键正名段已存在，删重复）'
                           % (p['from'] + '|' + p['to'], len(co)))
            else:
                p['from' if p['from'] == 'はりま勝原' else 'to'] = '上郡'
                log.append('  ~ 错名簇          %-24s %3d pts → 上郡|%s'
                           % ('はりま勝原|' + other, len(co), other))

    # ---- D2. 同名站断链：跨过被污染节点的贯通段（顶点全部来自既有相邻段） ----
    BYPASS = [('本郷', '三原', '河内'), ('島田', '岩田', '光'),
              ('戸田', '富海', '福川'), ('下松', '櫛ヶ浜', '光'),
              ('大門', '東福山', '笠岡'), ('曽根', 'ひめじ別所', '宝殿'),
              ('大久保', '魚住', '西明石')]
    for mid, x, y in BYPASS:
        if find2(F, x, y, '山陽線'):
            continue
        fa, fb = find2(F, x, mid, '山陽線'), find2(F, mid, y, '山陽線')
        if fa and fb and not opts.check:
            co = compose(fa['geometry']['coordinates'], fb['geometry']['coordinates'])
            add(mkseg(x, y, '山陽線', co, fa['properties']['color'], fa['properties']['op']), '同名站贯通')

    # ---- E. 站表 櫛田神社前 ----
    # 接缝点 = 8967（天神南→櫛田神社前）的尾点 + 6337（櫛田神社前→博多）的首点。
    # 注意不能取 8967 首点——那是天神南侧端点，取错会把站坐标偏到两站半路（~453 m）。
    if not any(f['properties'].get('station') == '櫛田神社前' for f in S) and not opts.check:
        sm = load(D + 'station_map.json')
        c1 = sm['segments'].get('8967')
        c2 = sm['segments'].get('6337')
        pts = []
        if c1:
            pts.append(c1[-1])
        if c2:
            pts.append(c2[0])
        if pts:
            coord = pts[0] if len(pts) == 1 else [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2]
            S.append({'type': 'Feature',
                      'properties': {'station': '櫛田神社前', 'op': '福岡市', 'line': SEVEN_LINE},
                      'geometry': {'type': 'Point', 'coordinates': [round(coord[0], 6), round(coord[1], 6)]}})
            log.append('  + stations3d    櫛田神社前 coord=%s' % ([round(coord[0], 6), round(coord[1], 6)],))

    print('\n'.join(log) if log else 'no-op（全部补丁已存在）')
    if opts.check:
        ok = all([find2(F, '松江', '玉造温泉', '山陰線'),
                  find2(F, '姫路', '東姫路', '山陽線'), find2(F, '東姫路', '御着', '山陽線'),
                  find2(F, '三原', '河内', '山陽線'), find2(F, '岩田', '光', '山陽線'),
                  find2(F, '富海', '福川', '山陽線'), find2(F, '櫛ヶ浜', '光', '山陽線'),
                  find2(F, '東福山', '笠岡', '山陽線'), find2(F, 'ひめじ別所', '宝殿', '山陽線'),
                  find2(F, '魚住', '西明石', '山陽線'), find2(F, '上郡', '有年', '山陽線'),
                  not [f for f in F if 'はりま勝原' in (f['properties'].get('from'), f['properties'].get('to'))
                       and (f['properties'].get('to') in JUNK_NB or f['properties'].get('from') in JUNK_NB)],
                  not [f for f in F if f['properties'].get('line') == SEVEN_LINE
                       and f['properties'].get('from') == '姪浜'],
                  any(f['properties'].get('station') == '櫛田神社前' for f in S)])
        print('CHECK', 'PASS' if ok else 'FAIL')
        sys.exit(0 if ok else 1)
    save(seg_p, seg)
    save(sta_p, sta)
    print('segments3d features=%d  stations3d features=%d' % (len(F), len(S)))


if __name__ == '__main__':
    main()

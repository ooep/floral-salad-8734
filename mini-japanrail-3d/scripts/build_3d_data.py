#!/usr/bin/env python3
# build_3d_data.py — 从 japanrail 数据生成 3D 页面精简资产（只留渲染所需字段）
import json, os

SRC_SEG = '/home/user/Doubao/chats/38445511791035394/japanrail/data/segments.geojson'
SRC_STA = '/home/user/Doubao/chats/38445511791035394/japanrail/data/stations.geojson'
OUT_DIR = '/home/user/Doubao/chats/38445511791035394/mini-japanrail-3d/data'

seg = json.load(open(SRC_SEG, encoding='utf-8'))
feats = []
kept = {'from', 'to', 'line', 'color', 'kind', 'op'}
for f in seg['features']:
    p = f['properties']
    np = {k: p[k] for k in kept if k in p}
    feats.append({'type': 'Feature', 'properties': np, 'geometry': f['geometry']})
out = {'type': 'FeatureCollection', 'features': feats}
json.dump(out, open(os.path.join(OUT_DIR, 'segments3d.geojson'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('segments3d:', len(feats), f'{os.path.getsize(os.path.join(OUT_DIR, "segments3d.geojson"))/1e6:.1f}MB')

sta = json.load(open(SRC_STA, encoding='utf-8'))
feats = []
for f in sta['features']:
    p = f['properties']
    np = {'station': p.get('station')}
    if 'op' in p: np['op'] = p['op']
    if 'line' in p: np['line'] = p['line']
    feats.append({'type': 'Feature', 'properties': np, 'geometry': f['geometry']})
out = {'type': 'FeatureCollection', 'features': feats}
json.dump(out, open(os.path.join(OUT_DIR, 'stations3d.geojson'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('stations3d:', len(feats), f'{os.path.getsize(os.path.join(OUT_DIR, "stations3d.geojson"))/1e6:.1f}MB')

# 统计: 线路颜色覆盖
from collections import Counter
c = Counter(f['properties'].get('color', '#888') for f in seg['features'])
print('有官方色的 segment 数:', sum(v for k, v in c.items() if k != '#888' and k and k != 'null'), '/', len(seg['features']))
print('样例颜色:', c.most_common(5))

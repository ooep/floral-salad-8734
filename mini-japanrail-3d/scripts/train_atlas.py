#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_atlas.py — 把 trainfrontview 车头小图打包成 WebGL 纹理图集（Mini JapanRail 3D）

输入：train_icons/line_icons_new.json（线路→图）+ final_tokkyu_icons.json（爱称→图）
输出：mini-japanrail-3d/data/train_icons_atlas.png + train_icons_atlas.json

所有引用图 40×48（含 2px padding 格子 44×52），防线性过滤 bleed。
atlas.json: { cols, cell:[44,52], img:[40,48], size:[W,H], line:{线路名:idx}, tokkyu:{爱称:idx} }
用法：python3 scripts/train_atlas.py
"""
import json, os, math, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = '/home/user/Doubao/chats/38445690044862978/train_icons/jr_icons'
LINES = '/home/user/Doubao/chats/38445690044862978/train_icons/line_icons_new.json'
TOKKYU = '/home/user/Doubao/chats/38445690044862978/train_icons/final_tokkyu_icons.json'
OUT = os.path.join(ROOT, 'data')

CELL_W, CELL_H = 44, 52
IMG_W, IMG_H = 40, 48
PAD = 2
# 未知线路/爱称兜底图（E217 湘南色，通用通勤电车外观）
FALLBACK_FILE = '02_east/tokaido-line__e217td.png'

def build():
    lines = json.load(open(LINES))
    tok = json.load(open(TOKKYU))

    # 线路键 → 图（保留全部，同图复用）
    line_map = {ln: files[0] for ln, files in lines.items() if files}
    tok_map = {nm: files[0] for nm, files in tok.items() if files}

    # 唯一图列表（保持稳定顺序：先 tokkyu 再 line，取第一个出现的文件路径）
    uniq, idx_of = [], {}
    def add(f):
        if f not in idx_of:
            idx_of[f] = len(uniq); uniq.append(f)
    for f in line_map.values(): add(f)
    for f in tok_map.values(): add(f)
    add(FALLBACK_FILE)  # 保证兜底图在图集中

    cols = 24
    rows = math.ceil(len(uniq) / cols)
    W, H = cols * CELL_W, rows * CELL_H
    atlas = Image.new('RGBA', (W, H), (0, 0, 0, 0))

    missing = []
    for i, rel in enumerate(uniq):
        src = os.path.join(ICON_DIR, rel)
        if not os.path.exists(src):
            missing.append(rel); continue
        im = Image.open(src).convert('RGBA')
        if im.size != (IMG_W, IMG_H):
            im = im.resize((IMG_W, IMG_H), Image.LANCZOS)
        cx, cy = (i % cols) * CELL_W + PAD, (i // cols) * CELL_H + PAD
        atlas.paste(im, (cx, cy))

    atlas.save(os.path.join(OUT, 'train_icons_atlas.png'))
    data = {
        'cols': cols, 'cell': [CELL_W, CELL_H], 'img': [IMG_W, IMG_H],
        'size': [W, H],
        'line': {ln: idx_of[f] for ln, f in line_map.items()},
        'tokkyu': {nm: idx_of[f] for nm, f in tok_map.items()},
        'fallback': idx_of[FALLBACK_FILE],
    }
    json.dump(data, open(os.path.join(OUT, 'train_icons_atlas.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'图集: {W}x{H}px, 唯一图 {len(uniq)}, 线路键 {len(line_map)}, 爱称键 {len(tok_map)}')
    if missing: print('缺失:', missing)

if __name__ == '__main__':
    build()

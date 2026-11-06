#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_atlas_vec.py — 矢量图标集（jr_icons_vector 抠图后）→ WebGL 纹理图集
与 train_atlas.py 同规格（cell 44×52 / img 40×48 / pad 2 / cols 24），
键结构与现有 train_icons_atlas.json 完全一致（line / tokkyu / fallback）。

用法: python3 scripts/train_atlas_vec.py
"""
import json, os, math, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_DIR = '/home/user/Doubao/chats/38446277312877314/train-vector-icons'
ICON_DIR = os.path.join(ROOT, 'data', 'icons_vec')
OUT = os.path.join(ROOT, 'data')

CELL_W, CELL_H = 44, 52
IMG_W, IMG_H = 40, 48
PAD = 2
FALLBACK_FILE = '02_east/tokaido-line__e217td1.png'

def build():
    lines = json.load(open(os.path.join(MAP_DIR, 'line_icons_new.json')))
    tok = json.load(open(os.path.join(MAP_DIR, 'final_tokkyu_icons.json')))

    line_map = {ln: files[0] for ln, files in lines.items() if files}
    tok_map = {nm: files[0] for nm, files in tok.items() if files}

    uniq, idx_of = [], {}
    def add(f):
        if f not in idx_of:
            idx_of[f] = len(uniq); uniq.append(f)
    for f in line_map.values(): add(f)
    for f in tok_map.values(): add(f)
    add(FALLBACK_FILE)

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
            # 方形大图 cover 裁到 40:48
            w, h = im.size
            target = IMG_W / IMG_H
            if w / h > target:  # 太宽:裁宽
                nw = int(h * target); x0 = (w - nw) // 2
                im = im.crop((x0, 0, x0 + nw, h))
            else:               # 太高:裁高
                nh = int(w / target); y0 = (h - nh) // 2
                im = im.crop((0, y0, w, y0 + nh))
            im = im.resize((IMG_W, IMG_H), Image.LANCZOS)
        cx, cy = (i % cols) * CELL_W + PAD, (i // cols) * CELL_H + PAD
        atlas.paste(im, (cx, cy))

    atlas.save(os.path.join(OUT, 'train_icons_atlas_vec.png'))
    data = {
        'cols': cols, 'cell': [CELL_W, CELL_H], 'img': [IMG_W, IMG_H],
        'size': [W, H],
        'line': {ln: idx_of[f] for ln, f in line_map.items()},
        'tokkyu': {nm: idx_of[f] for nm, f in tok_map.items()},
        'fallback': idx_of[FALLBACK_FILE],
    }
    json.dump(data, open(os.path.join(OUT, 'train_icons_atlas_vec.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'矢量图集: {W}x{H}px, 唯一图 {len(uniq)}, 线路键 {len(line_map)}, 爱称键 {len(tok_map)}')
    if missing: print('缺失:', missing)

if __name__ == '__main__':
    build()

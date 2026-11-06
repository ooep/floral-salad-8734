#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_atlas_cute.py — 可爱图标集（kasu_icons 关东车型）→ WebGL 纹理图集
策略: 爱称/线路映射到 kasu 可爱图; 未覆盖的键从现有 train_icons_atlas 拷贝对应图(与图标模式一致)。

用法: python3 scripts/train_atlas_cute.py
"""
import json, os, math
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KASU_DIR = '/home/user/Doubao/chats/38446277312877314/train-vector-icons/kasu_icons'
MAP_DIR = '/home/user/Doubao/chats/38446277312877314/train-vector-icons'
OUT = os.path.join(ROOT, 'data')

CELL_W, CELL_H = 44, 52
IMG_W, IMG_H = 40, 48
PAD = 2
# 可爱模式通用兜底: E233系0番台 通勤电车
CUTE_FALLBACK = 'E233_0c.png'

# ---------------- 映射表: 爱称(tokkyu) → kasu 图 ----------------
TOKKYU_CUTE = {
    # 新干线
    'のぞみ': 'shinkansenN700kei.png', 'ひかり': 'shinkansenN700kei.png', 'こだま': 'shinkansenN700kei.png',
    'さくら': 'shinkansenN700kei_7000.png', 'みずほ': 'shinkansenN700kei_7000.png',
    'つばめ': 'shinkansen800kei_0.png',
    'はやぶさ': 'shinkansenE5kei.png', 'はやて': 'shinkansenE5kei.png', 'やまびこ': 'shinkansenE5kei.png', 'なすの': 'shinkansenE5kei.png',
    'こまち': 'shinkansenE6kei.png',
    'とき': 'shinkansenE2kei_J.png', 'たにがわ': 'shinkansenE2kei_J.png',
    'かがやき': 'shinkansenE7kei.png', 'はくたか': 'shinkansenE7kei.png', 'つるぎ': 'shinkansenE7kei.png',
    'あさま': 'shinkansenE2kei_N.png',
    'つばさ': 'shinkansenE3kei_1000_2.png',
    'かもめ': 'shinkansenN700S_8000.png',
    # JR东 特急(有 kasu 图)
    '成田エクスプレス': 'E259.png',
    'あかぎ': '211_0c2.png', '草津': '211_0c2.png',
    'しおさい': 'E257_500bs.png', 'わかしお': 'E257_500bs.png', 'さざなみ': 'E257_500bs.png',
    '湘南': 'E257_500bs.png', 'はちおうじ': 'E257_500bs.png',
    '踊り子': 'E257_0c1.png',
    'きぬがわ': '253_1000_2.png', 'けごん': '253_1000_2.png',
    'えのしま': 'E259.png',
    'スーパーひたち': 'E657系无图_fallback',  # 占位防错,实际走 fallback
}

# ---------------- 映射表: 线路(line) → kasu 图 ----------------
# 键名以时刻表/图集实际使用的线路名为准(检查自 trains/tmaps + train_icons_atlas.json)
LINE_CUTE = {
    # 新干线线路(线路键, 爱称另有 tokkyu 映射)
    '東海道新幹線': 'shinkansenN700kei.png', '山陽新幹線': 'shinkansenN700kei.png',
    '東北新幹線': 'shinkansenE5kei.png', '北海道新幹線': 'shinkansenH5kei.png',
    '上越新幹線': 'shinkansenE2kei_J.png', '北陸新幹線': 'shinkansenE7kei.png',
    '九州新幹線': 'shinkansenN700kei_7000.png', '西九州新幹線': 'shinkansenN700S_8000.png',
    '秋田新幹線': 'shinkansenE6kei.png', '山形新幹線': 'shinkansenE3kei_1000_2.png',
    # 东京首都圈 JR 东
    '山手線': 'E235y.png',
    '根岸線': 'E233_1000k.png', # 京浜東北線列车由根岸線键代表
    '中央線': 'E233_0c.png', '中央本線': 'E233_0c.png', '青梅線': 'E233_0c.png', '五日市線': 'E233_0c.png',
    '総武本線': 'E231_500y.png', '横須賀線': 'E235o2.png',
    '常磐線': 'E231_0m.png',
    '川越線': 'E233_7000a.png', '赤羽線': 'E233_7000a.png', # 埼京線列车由川越/赤羽键代表
    '京葉線': 'E233_5000e.png', '外房線': 'E233_5000e.png', '内房線': 'E233_5000e.png',
    '武蔵野線': 'E231_0m.png',
    '南武線': 'E233_8000n.png', '南武支線': 'E233_8000n.png',
    '鶴見線': 'E131_600nk.png',
    '相模線': 'E131_500gm.png',
    '横浜線': 'E233_6000h.png',
    '八高線': 'Dc110hc.png',
    'jr日光線': '205_600nk.png', '日光線': 'E131_200c.png',
    '東海道本線': 'E231_0m.png', '東海道線': 'E231_0m.png',
    '高崎線': 'E231t.png',
    '両毛線': '211_0c2.png',
    '信越本線': '115c2.png', '篠ノ井線': '115c2.png',
    '水戸線': 'E531_0j1.png',
    '仙石線': '205_1000i.png',
    '成田線': 'E233_3000t.png', '成田空港線': 'E259.png',
}

def main():
    lines = json.load(open(os.path.join(MAP_DIR, 'line_icons_new.json')))
    tok = json.load(open(os.path.join(MAP_DIR, 'final_tokkyu_icons.json')))
    line_map = {ln: files[0] for ln, files in lines.items() if files}
    tok_map = {nm: files[0] for nm, files in tok.items() if files}

    # 现有图集(供未覆盖键拷贝)
    base = json.load(open(os.path.join(OUT, 'train_icons_atlas.json')))
    base_img = Image.open(os.path.join(OUT, 'train_icons_atlas.png')).convert('RGBA')
    base_crop_cache = {}
    def base_crop(idx):
        if idx not in base_crop_cache:
            col = idx % base['cols']; row = idx // base['cols']
            x = col * base['cell'][0] + PAD; y = row * base['cell'][1] + PAD
            base_crop_cache[idx] = base_img.crop((x, y, x + base['img'][0], y + base['img'][1])).copy()
        return base_crop_cache[idx]

    # kasu 图缓存
    kasu_cache = {}
    def kasu_img(fn):
        if fn not in kasu_cache:
            im = Image.open(os.path.join(KASU_DIR, fn)).convert('RGBA')
            if im.size != (IMG_W, IMG_H):
                im = im.resize((IMG_W, IMG_H), Image.LANCZOS)
            kasu_cache[fn] = im
        return kasu_cache[fn]

    uniq, idx_of = [], {}
    def add(im):
        key = id(im)
        if key not in idx_of:
            idx_of[key] = len(uniq); uniq.append(im)
        return idx_of[key]

    line_idx, tok_idx = {}, {}
    cute_used, base_used = 0, 0

    def resolve(fn_or_file):
        """返回 (图, 是否kasu)"""
        nonlocal cute_used, base_used
        if fn_or_file in LINE_CUTE.values() or fn_or_file in TOKKYU_CUTE.values():
            cute_used += 1
            return kasu_img(fn_or_file), True
        return None, False

    # line 键
    for ln, rel in line_map.items():
        f = LINE_CUTE.get(ln)
        if f and f != '_fallback':
            line_idx[ln] = add(kasu_img(f)); cute_used += 1
        else:
            b = base['line'].get(ln)
            if b is not None:
                line_idx[ln] = add(base_crop(b)); base_used += 1
            else:
                line_idx[ln] = add(kasu_img(CUTE_FALLBACK)); cute_used += 1

    # tokkyu 键
    for nm, rel in tok_map.items():
        f = TOKKYU_CUTE.get(nm)
        if f and f != '_fallback':
            tok_idx[nm] = add(kasu_img(f)); cute_used += 1
        else:
            b = base['tokkyu'].get(nm)
            if b is not None:
                tok_idx[nm] = add(base_crop(b)); base_used += 1
            else:
                tok_idx[nm] = add(kasu_img(CUTE_FALLBACK)); cute_used += 1

    # 兜底
    fb = add(kasu_img(CUTE_FALLBACK)); cute_used += 1

    cols = 24
    rows = math.ceil(len(uniq) / cols)
    W, H = cols * CELL_W, rows * CELL_H
    atlas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for i, im in enumerate(uniq):
        cx, cy = (i % cols) * CELL_W + PAD, (i // cols) * CELL_H + PAD
        atlas.paste(im, (cx, cy))

    atlas.save(os.path.join(OUT, 'train_icons_atlas_cute.png'))
    data = {
        'cols': cols, 'cell': [CELL_W, CELL_H], 'img': [IMG_W, IMG_H],
        'size': [W, H],
        'line': line_idx, 'tokkyu': tok_idx, 'fallback': fb,
    }
    json.dump(data, open(os.path.join(OUT, 'train_icons_atlas_cute.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'可爱图集: {W}x{H}px, 唯一图 {len(uniq)} (kasu {cute_used} / 现有拷贝 {base_used}), 线路键 {len(line_idx)}, 爱称键 {len(tok_idx)}')

if __name__ == '__main__':
    main()

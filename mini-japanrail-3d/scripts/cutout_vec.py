#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cutout_vec.py — jr_icons_vector 批量抠图（白/浅色底 → 透明）
AI 矢量重绘图标为黑描边平涂风格，白色车体被描边包围，用四角 flood-fill 安全去除背景。
用法: python3 scripts/cutout_vec.py <src_dir> <out_dir>
"""
import os, sys, glob
from concurrent.futures import ProcessPoolExecutor
from PIL import Image
import numpy as np
from collections import deque

def flood_fill_transparent(src, out, tol=20):
    im = Image.open(src).convert('RGBA')
    a = np.array(im)
    h, w = a.shape[:2]
    rgb = a[:, :, :3].astype(int)
    is_white = (np.abs(rgb - 255).max(axis=2) <= tol)
    mask = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        if is_white[0, x] and not mask[0, x]: dq.append((0, x)); mask[0, x] = True
        if is_white[h-1, x] and not mask[h-1, x]: dq.append((h-1, x)); mask[h-1, x] = True
    for y in range(h):
        if is_white[y, 0] and not mask[y, 0]: dq.append((y, 0)); mask[y, 0] = True
        if is_white[y, w-1] and not mask[y, w-1]: dq.append((y, w-1)); mask[y, w-1] = True
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
            ny, nx = y+dy, x+dx
            if 0 <= ny < h and 0 <= nx < w and not mask[ny, nx] and is_white[ny, nx]:
                mask[ny, nx] = True
                dq.append((ny, nx))
    a[mask] = [0, 0, 0, 0]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(a).save(out)

def worker(arg):
    src, out = arg
    try:
        flood_fill_transparent(src, out)
        return (src, True)
    except Exception as e:
        return (src, False, str(e))

def main():
    src_dir, out_dir = sys.argv[1], sys.argv[2]
    files = sorted(glob.glob(os.path.join(src_dir, '**', '*.png'), recursive=True))
    print(f'共 {len(files)} 张')
    jobs = [(f, os.path.join(out_dir, os.path.relpath(f, src_dir))) for f in files]
    done = 0
    with ProcessPoolExecutor(max_workers=6) as ex:
        for res in ex.map(worker, jobs):
            if res[1]: done += 1
            else: print('ERR', res[0], res[2])
    print(f'完成 {done}/{len(files)}')

if __name__ == '__main__':
    main()

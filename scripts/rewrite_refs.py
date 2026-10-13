#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rewrite_refs.py — 一次性改写脚本：把仓库内页面/JS/CSS 的大文件引用域名改为 jr-static.suki.ing
用法: python3 scripts/rewrite_refs.py
"""
import io, sys, os

SB = 'https://jr-static.suki.ing'
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def apply(path, pairs, label):
    with io.open(path, encoding='utf-8') as f:
        s = f.read()
    total = 0
    for old, new in pairs:
        n = s.count(old)
        if n:
            s = s.replace(old, new)
            total += n
            print('  %s: %d × %s' % (label, n, old[:60]))
    if total:
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(s)
    return total

ICONS = [
    ('"apple-touch-icon.png"', '"%s/apple-touch-icon.png"' % SB),
    ('"favicon-dark.png"', '"%s/favicon-dark.png"' % SB),
    ('"favicon.png"', '"%s/favicon.png"' % SB),
    ('"icon-192.png"', '"%s/icon-192.png"' % SB),
    ('"logo-dark.png"', '"%s/logo-dark.png"' % SB),
    ('"logo.png"', '"%s/logo.png"' % SB),
]
ICONS_SQ = [
    ("'favicon-dark.png'", "'%s/favicon-dark.png'" % SB),
    ("'favicon.png'", "'%s/favicon.png'" % SB),
    ("'logo-dark.png'", "'%s/logo-dark.png'" % SB),
    ("'logo.png'", "'%s/logo.png'" % SB),
]
DATA_SQ = [("'data/", "'%s/data/" % SB)]
DATA_ICON_MIX = DATA_SQ + ICONS + ICONS_SQ

ok = True

# 1) mini-japanrail-3d/index.html（主站）
ok &= apply(os.path.join(BASE, 'mini-japanrail-3d/index.html'),
    DATA_SQ + [('"logos/', '"%s/logos/' % SB)] + ICONS + ICONS_SQ +
    [('https://jr.suki.ing/og-image.png', '%s/og-image.png' % SB)], 'mini/index') > 0

# 2) journey.html
ok &= apply(os.path.join(BASE, 'mini-japanrail-3d/journey.html'),
    DATA_SQ + ICONS + ICONS_SQ, 'journey') > 0

# 3) orm-demo.html
ok &= apply(os.path.join(BASE, 'mini-japanrail-3d/orm-demo.html'),
    DATA_SQ + ICONS, 'orm-demo') > 0

# 4) privacy.html
ok &= apply(os.path.join(BASE, 'mini-japanrail-3d/privacy.html'), ICONS, 'privacy') > 0

# 5) 根站页面
ok &= apply(os.path.join(BASE, 'index.html'), DATA_ICON_MIX, 'root/index') > 0
ok &= apply(os.path.join(BASE, 'index-la.html'), DATA_ICON_MIX, 'root/index-la') > 0
ok &= apply(os.path.join(BASE, 'index-quest.html'),
    DATA_SQ + [('url(data/train_icons_atlas.png)', 'url(%s/data/quest/train_icons_atlas.png)' % SB)] + ICONS + ICONS_SQ, 'root/index-quest') > 0

print('DONE, ok=%s' % ok)
sys.exit(0 if ok else 1)

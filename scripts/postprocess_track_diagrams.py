#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
postprocess_track_diagrams.py — jr-track 配线图发布副本后处理（幂等）

在 deploy.yml 拉取 jr-track 之后、注入 jr-static 资产之前运行，只改发布副本，
jr-track 源仓库保持不动。三项处理：

  1) 去整块白色背景：删除宽高≈画布(≥98%)、fill 为白(#fff/#ffffff/white/rgb(255,255,255))
     的 rect；多层白矩形堆叠时逐层命中全部删除。当前语料(2026-11, head b9d6f70)命中 0 ——
     源 SVG 本身透明，白底曾来自前端 CSS 背景（已一并移除）；此闸门防 jr-track 未来改版。
  2) 去底部虚线分隔行：源图用一排小 rect(高≤2.5、宽≤15) 在画布底部(y≥90%高)拼出虚线，
     整行(≥4 个)删除；随之的空白带由前端透明底+间距消化，块间只留 gap。
  3) 重着色保对比度：stroke/fill 属性与 <style> 声明中相对亮度>0.12 的 hex 色，
     向 #0b1220 混色 75% 压暗（透明底叠毛玻璃后线条/文字仍 ≥4.5:1）；
     纯白 fill(站名遮罩) 改半透明 rgba(255,255,255,.55)。

幂等性：三类操作均为不动点——已删元素不再存在；压暗后亮度≤0.12 不再命中；
rgba 串不是 hex 不再映射；虚线行删除后无行可删。重复运行输出 0 改动且不重写文件
（仅内容有变化时写盘）。用法：python3 scripts/postprocess_track_diagrams.py <dir>
"""
import os
import re
import sys

WHITE = ('#fff', '#ffffff', 'white', 'rgb(255,255,255)')
DARK_ANCHOR = (11, 18, 32)          # #0b1220
LUMA_CAP = 0.12
MIX = 0.75

RECT_RE = re.compile(r'<rect\b[^>]*>', re.I)
ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
HEX_RE = re.compile(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')
ATTR_SF_RE = re.compile(r'(stroke|fill)="([^"]*)"', re.I)
STYLE_RE = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.S | re.I)
STYLE_SF_RE = re.compile(r'(stroke|fill)\s*:\s*(#[0-9a-fA-F]{3,6})', re.I)
STYLE_WHITE_RE = re.compile(r'(fill\s*:\s*)(#fff\b|#ffffff\b)', re.I)


def _hex_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _luma(rgb):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _darken(hexstr):
    """亮度>阈值的 hex 压暗；已暗或非法返回 None（不动点保证幂等）。"""
    try:
        rgb = _hex_rgb(hexstr)
    except ValueError:
        return None
    if _luma(rgb) <= LUMA_CAP:
        return None
    return '#%02x%02x%02x' % tuple(
        int(round(c + (a - c) * MIX)) for c, a in zip(rgb, DARK_ANCHOR))


def _recolor(s, stats):
    def attr_sub(m):
        pre, val = m.group(1), m.group(2)
        if pre.lower() == 'fill' and val.strip().lower() in ('#fff', '#ffffff'):
            stats['color'] += 1
            return pre + '="rgba(255,255,255,.55)"'
        def hx(mm):
            d = _darken(mm.group(1))
            if d is None:
                return mm.group(0)
            stats['color'] += 1
            return d
        return pre + '="' + HEX_RE.sub(hx, val) + '"'

    s = ATTR_SF_RE.sub(attr_sub, s)

    def style_sub(m):
        body = m.group(2)
        def sf(mm):
            d = _darken(mm.group(2))
            if d is None:
                return mm.group(0)
            stats['color'] += 1
            return mm.group(1) + ': ' + d
        body = STYLE_SF_RE.sub(sf, body)
        body = STYLE_WHITE_RE.sub(lambda mm: mm.group(1) + 'rgba(255,255,255,.55)', body)
        return m.group(1) + body + m.group(3)

    return STYLE_RE.sub(style_sub, s)


def process_file(path):
    with open(path, encoding='utf-8', errors='ignore', newline='') as f:
        orig = f.read()
    s = orig
    stats = {'bg': 0, 'dash': 0, 'color': 0}

    m = re.search(r'viewBox="[-\d.eE]+[ ,]+[-\d.eE]+[ ,]+([-\d.eE]+)[ ,]+([-\d.eE]+)"', s)
    vw = vh = None
    if m:
        vw, vh = float(m.group(1)), float(m.group(2))

    tags = RECT_RE.findall(s)
    dash_set = set()
    if vh:
        dash = []
        for tag in tags:
            a = dict(ATTR_RE.findall(tag))
            try:
                hgt = float(a.get('height') or 9)
                wid = float(a.get('width') or 9)
                y = float(a.get('y') or 0)
            except ValueError:
                continue
            if hgt <= 2.5 and wid <= 15 and y >= vh * 0.9:
                dash.append(tag)
        if len(dash) >= 4:                      # 整行才删，避免误伤内容小 rect
            dash_set = set(dash)

    def repl(m):
        tag = m.group(0)
        if tag in dash_set:
            stats['dash'] += 1
            return ''
        a = dict(ATTR_RE.findall(tag))
        fill = (a.get('fill') or '').strip().lower()
        if vw and fill in WHITE:
            try:
                x = float(a.get('x') or 0)
                y = float(a.get('y') or 0)
                rw = float(a.get('width') or 0)
                rh = float(a.get('height') or 0)
            except ValueError:
                return tag
            if rw >= vw * 0.98 and rh >= vh * 0.98 and x <= vw * 0.02 and y <= vh * 0.02:
                stats['bg'] += 1
                return ''
        return tag

    s = RECT_RE.sub(repl, s)
    s = _recolor(s, stats)

    if s != orig:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(s)
        return stats
    return None


def main():
    if len(sys.argv) < 2:
        print('usage: postprocess_track_diagrams.py <dir>', file=sys.stderr)
        return 2
    root = sys.argv[1]
    tot = {'bg': 0, 'dash': 0, 'color': 0}
    changed = files = 0
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.lower().endswith('.svg'):
                continue
            files += 1
            st = process_file(os.path.join(dp, fn))
            if st:
                changed += 1
                for k in tot:
                    tot[k] += st[k]
    print('[trackdiagrams-post] files=%d changed=%d 白背景rect=%d 虚线rect=%d 重着色=%d'
          % (files, changed, tot['bg'], tot['dash'], tot['color']))
    return 0


if __name__ == '__main__':
    sys.exit(main())

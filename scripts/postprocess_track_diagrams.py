#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
postprocess_track_diagrams.py — jr-track 配线图发布副本后处理（幂等，v2）

deploy.yml 拉取 jr-track 后、注入 jr-static 资产前运行；只改发布副本，源仓库不动。
每个源 SVG 产出两个变体：
  <name>.svg     浅色主题版：中性深灰结构线 + 降饱和/压暗的线路色 + 深墨文字
  <name>.dk.svg  深色主题版：中性浅灰结构线 + 线路官方色(暗色提亮保对比) + 浅墨文字

处理项：
  1) 去整块白色背景 rect(≥98% 画布、白 fill，含堆叠)；当前语料命中 0（源本透明），闸门保留。
  2) 去底部虚线分隔行（高≤2.5 宽≤15 且 y≥90% 画布高的小 rect，整行≥4 个）。
  3) 主线路识别：x 跨度≥40% 画布宽的 line/path/polyline 描边元素 = 该线走向主线；
     其余描边元素 = 站台/场内/道岔结构线，着中性灰。线路色取 linecolor.md/线路色.md
     既有线路色表（按线路名，去括号注记）；映射不到的线路主线也用中性灰并计入未命中清单。
  4) 文字 ink 与白遮罩按变体重置（遮罩保持半透明 .55）。
  5) 幂等：根元素后写入标记 <!--mjr-td2-->，已带标记的文件直接跳过；重复运行 0 改动。

线路色对比度约束：浅色版线路色饱和度×0.75 且亮度压到 ≤0.233（对浅衬底 ≥3:1）；
深色版官方色亮度 <0.40 者提亮到 0.40（对深衬底 ≥3:1），亮色保持原亮度。

用法：python3 scripts/postprocess_track_diagrams.py <trackdiagrams_dir> [index_json] [color_md...]
"""
import colorsys
import os
import re
import sys
import collections

WHITE = ('#fff', '#ffffff', 'white', 'rgb(255,255,255)')
MARK = '<!--mjr-td2-->'
LONG_SPAN = 0.40

LIGHT = {'struct': '#3f4650', 'ink': '#16181d', 'mask': 'rgba(255,255,255,.55)'}
DARK = {'struct': '#98a2b0', 'ink': '#e8eaed', 'mask': 'rgba(16,18,22,.55)'}

RECT_RE = re.compile(r'<rect\b[^>]*>', re.I)
STROKE_EL_RE = re.compile(r'<(line|path|polyline)\b[^>]*>', re.I)
ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
HEX_RE = re.compile(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')
STYLE_RE = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.S | re.I)


def hx(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tohex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def luma(rgb):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def light_variant_color(hexcolor):
    """浅色版线路色：降一档饱和 + 压暗到 L≤0.233。"""
    r, g, b = (c / 255.0 for c in hx(hexcolor))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s *= 0.75
    l = min(l, 0.38)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    rgb = (r * 255, g * 255, b * 255)
    while luma(rgb) > 0.233 and l > 0.02:
        l -= 0.02
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        rgb = (r * 255, g * 255, b * 255)
    return tohex(rgb)


def dark_variant_color(hexcolor):
    """深色版线路色：保持原亮度；过暗者提亮到 L≈0.40 保 ≥3:1。"""
    rgb = hx(hexcolor)
    if luma(rgb) >= 0.40:
        return tohex(rgb)
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(l, 0.52)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    out = (r * 255, g * 255, b * 255)
    while luma(out) < 0.40 and l < 0.95:
        l += 0.02
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        out = (r * 255, g * 255, b * 255)
    return tohex(out)


def load_colors(paths):
    colors = {}
    for p in paths:
        if not os.path.isfile(p):
            continue
        for line in open(p, encoding='utf-8', errors='ignore'):
            m = re.match(r'\|\s*([^|]+?)\s*\|\s*(#[0-9a-fA-F]{3,6})\s*\|', line)
            if not m:
                continue
            name = re.sub(r'[（(][^（）()]*[）)]\s*$', '', m.group(1)).strip()
            colors.setdefault(name, m.group(2).strip())
    return colors


def load_chunk_lines(index_path):
    """file -> 该分块归属线路（索引中被引用时的众数线路）。"""
    if not os.path.isfile(index_path):
        return {}
    import json
    idx = json.load(open(index_path, encoding='utf-8'))['stations']
    vote = collections.defaultdict(collections.Counter)
    for entries in idx.values():
        for e in entries:
            for f in e['files']:
                vote[f][e['line']] += 1
    return {f: c.most_common(1)[0][0] for f, c in vote.items()}


def process_file(path, root, colors, chunk_lines, stats):
    with open(path, encoding='utf-8', errors='ignore', newline='') as f:
        orig = f.read()
    if MARK in orig:
        return None
    s = orig
    m = re.search(r'viewBox="[-\d.eE]+[ ,]+[-\d.eE]+[ ,]+([-\d.eE]+)[ ,]+([-\d.eE]+)"', s)
    vw = float(m.group(1)) if m else 1000.0
    vh = float(m.group(2)) if m else 1000.0

    # 1) 白背景 + 2) 虚线行
    dash = []
    for tag in RECT_RE.findall(s):
        a = dict(ATTR_RE.findall(tag))
        try:
            hgt = float(a.get('height') or 9)
            wid = float(a.get('width') or 9)
            y = float(a.get('y') or 0)
        except ValueError:
            continue
        if hgt <= 2.5 and wid <= 15 and y >= vh * 0.9:
            dash.append(tag)
    dash_set = set(dash) if len(dash) >= 4 else set()

    def rect_repl(mo):
        tag = mo.group(0)
        if tag in dash_set:
            stats['dash'] += 1
            return ''
        a = dict(ATTR_RE.findall(tag))
        fill = (a.get('fill') or '').strip().lower()
        if fill in WHITE:
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

    s = RECT_RE.sub(rect_repl, s)

    # 3) 主线/结构线分色
    rel = os.path.relpath(path, root).replace(os.sep, '/')
    line_name = chunk_lines.get(rel) or chunk_lines.get(os.path.basename(path))
    official = None
    if line_name:
        for cand in (line_name, line_name.replace('本線', '線'), line_name.replace('線', '本線')):
            if cand in colors:
                official = colors[cand]
                break
    if line_name and not official:
        stats['unmapped'][line_name] += 1

    # 先收集跨度，再统一改写
    spans = {}
    for mo in STROKE_EL_RE.finditer(s):
        tag = mo.group(0)
        a = dict(ATTR_RE.findall(tag))
        if 'x1' in a:
            try:
                span = abs(float(a.get('x2', a['x1'])) - float(a['x1']))
            except (KeyError, ValueError):
                span = 0
        else:
            nums = re.findall(r'-?\d+\.?\d*', a.get('d', ''))[0::2][:120]
            xs = [float(x) for x in nums]
            span = (max(xs) - min(xs)) if xs else 0
        spans[tag] = span

    def make_variant(pal, route_color):
        out = s

        def set_attr(tag, name, val):
            """替换或插入属性，正确处理自闭合标签。"""
            pat = re.compile(r'%s="[^"]*"' % name)
            if pat.search(tag):
                return pat.sub('%s="%s"' % (name, val), tag, count=1)
            if tag.endswith('/>'):
                return tag[:-2].rstrip() + ' %s="%s"/>' % (name, val)
            return tag[:-1].rstrip() + ' %s="%s">' % (name, val)

        def el_repl(mo):
            tag = mo.group(0)
            is_route = spans.get(tag, 0) >= vw * LONG_SPAN
            col = route_color if (is_route and route_color) else pal['struct']
            if is_route and route_color:
                stats['routed'] += 1
            return set_attr(tag, 'stroke', col)
        out = STROKE_EL_RE.sub(el_repl, out)
        # 文字 ink
        def txt_repl(mo):
            return set_attr(mo.group(0), 'fill', pal['ink'])
        out = re.sub(r'<text\b[^>]*>', txt_repl, out, flags=re.I)
        # 白遮罩半透明
        out = re.sub(r'fill="#(?:fff|ffffff)"', 'fill="%s"' % pal['mask'], out, flags=re.I)
        out = re.sub(r'(fill\s*:\s*)#(?:fff|ffffff)\b', lambda mm: mm.group(1) + pal['mask'], out, flags=re.I)
        return out

    light_col = light_variant_color(official) if official else None
    dark_col = dark_variant_color(official) if official else None
    v_light = make_variant(LIGHT, light_col)
    v_dark = make_variant(DARK, dark_col)
    # 标记 + 透明画布（无背景 rect 即透明）
    v_light = re.sub(r'(<svg\b[^>]*>)', lambda mm: mm.group(1) + MARK, v_light, count=1)
    v_dark = re.sub(r'(<svg\b[^>]*>)', lambda mm: mm.group(1) + MARK, v_dark, count=1)
    stats['files'] += 1
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(v_light)
    with open(path[:-4] + '.dk.svg', 'w', encoding='utf-8', newline='') as f:
        f.write(v_dark)
    return stats


def main():
    if len(sys.argv) < 2:
        print('usage: postprocess_track_diagrams.py <dir> [index_json] [color_md...]', file=sys.stderr)
        return 2
    root = sys.argv[1]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    index_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(repo, 'mini-japanrail-3d', 'data', 'track_diagram_index.json')
    color_paths = sys.argv[3:] or [os.path.join(repo, 'linecolor.md'), os.path.join(repo, '线路色.md')]
    colors = load_colors(color_paths)
    chunk_lines = load_chunk_lines(index_path)
    stats = {'bg': 0, 'dash': 0, 'files': 0, 'routed': 0, 'unmapped': collections.Counter()}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.lower().endswith('.svg') or fn.endswith('.dk.svg'):
                continue
            process_file(os.path.join(dp, fn), root, colors, chunk_lines, stats)
    print('[trackdiagrams-post] files=%d 白背景rect=%d 虚线rect=%d 主线上色=%d 未命中线路=%d'
          % (stats['files'], stats['bg'], stats['dash'], stats['routed'], len(stats['unmapped'])))
    for name, c in stats['unmapped'].most_common():
        print('  unmapped: %s (%d chunks)' % (name, c))
    return 0


if __name__ == '__main__':
    sys.exit(main())

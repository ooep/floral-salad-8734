#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 ja 维基线路词条的 {{BS-table}}/{{BS-map}} 模板代码，本地渲染 BS 风格全线配线图 SVG。

用户指出维基配线图 = BSicon 散件 + 模板代码拼装（无单张整图文件）。
V6 方案：直接抓词条 wikitext 中的 BS 模板行（数据源=维基，含里程/站名/隧道/方向注释），
按 BS 版式本地渲染 SVG（主轨道列 + 右列里程/站名/注释），形态对齐维基「海峡線」BS-map。

BS 行格式（ja 维基实测）：
  {{BS2|STR||||↑JR東：津軽線（青森方面）|}}
  {{BS2|BHF||0.0|中小国駅||}}
  {{BS2|DST|O1=HUBa||2.3|新中小国信号場||}}
  {{BS3-2|KBHFxe||eBHF|品川駅|目黒駅<ref>…</ref>|}}

产出：
  data/line_bsdiagrams/<lname>.svg            渲染 SVG（深色玻璃风格，可内联）
  data/line_bsdiagrams.json                   索引 {lname: {rows, source, ...}}
用法：python3 seo/fetch_bs_diagrams.py [--limit-lines N] [--out DIR]
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
API_JA = 'https://ja.wikipedia.org/w/api.php'
UA = {'User-Agent': 'MiniJapanRail-SEO/1.0 (https://jr.suki.ing; contact: admin@jr.suki.ing)'}

OUT_DIR = os.path.join(DATA, 'line_bsdiagrams')
OUT_IDX = os.path.join(DATA, 'line_bsdiagrams.json')

# ---- BSicon → SVG 图形（20x20 网格，右列文字另算）----
def icon_svg(code):
    """把 BSicon 代码渲染为单行轨道区 SVG 片段（宽 24 高 20）。支持 O1=/O2= 覆盖。"""
    main = (code or 'STR').split('|')[0]
    overlays = [x.split('=', 1)[1] for x in (code or '').split('|')[1:] if '=' in x]
    t = main or 'STR'
    dashed = False
    if t.startswith('ex'):
        dashed = True
        t = t[2:]
    tunnel = False
    if t.startswith('t'):
        tunnel = True
        t = t[1:]
    if t.startswith('x'):
        t = t[1:]
    if t.startswith('e'):
        t = t[1:]
    base = re.sub(r'[+lrqgfm1-9-]+$', '', t)
    vert = '<line x1="10" y1="0" x2="10" y2="20" stroke="currentColor" stroke-width="2.4"' + (' stroke-dasharray="3 2"' if dashed else '') + '/>'
    nodes = {
        'STR': vert,
        'STRq': '<line x1="0" y1="10" x2="20" y2="10" stroke="currentColor" stroke-width="2.4"/>',
        'BHF': vert + '<circle cx="10" cy="10" r="2.6" fill="currentColor"/>',
        'KBHF': vert + '<circle cx="10" cy="10" r="3.4" fill="currentColor"/>',
        'HST': vert + '<line x1="6" y1="10" x2="14" y2="10" stroke="currentColor" stroke-width="2.6"/>',
        'DST': vert + '<rect x="7" y="7" width="6" height="6" fill="currentColor"/>',
        'KRZ': vert + '<line x1="0" y1="10" x2="20" y2="10" stroke="currentColor" stroke-width="2.4"/>',
        'ABZgl': '<path d="M10 0 L10 10 M10 10 L0 20" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'ABZg+r': '<path d="M10 0 L10 10 L20 20" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'ABZgl+l': '<path d="M10 0 L10 20 M10 10 L0 10" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'ABZg+r+r': '<path d="M10 0 L10 20 M10 10 L20 10" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'STR+r': '<path d="M10 0 L10 20 M10 20 L0 20" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'STR+l': '<path d="M10 0 L10 20 M10 0 L0 0" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'STRr': '<path d="M10 0 L10 20 M10 0 L20 0" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'STRl': '<path d="M10 0 L10 20 M10 20 L20 20" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'TUNNEL1': '<line x1="10" y1="0" x2="10" y2="20" stroke="currentColor" stroke-width="2.4"/>' +
                   '<path d="M4 3 h12 M4 8 h12 M4 13 h12 M4 18 h12" stroke="currentColor" stroke-width="1.1" opacity=".55"/>',
        'TUNNEL2': '<path d="M10 0 L10 10 L2 20 M10 0 L10 10 L18 20" fill="none" stroke="currentColor" stroke-width="2.4"/>',
        'tSTRa': '<path d="M10 0 L10 20" stroke="currentColor" stroke-width="2.4"/>' +
                 '<path d="M6 0 h8 M4 3 h12" stroke="currentColor" stroke-width="1.1" opacity=".5"/>',
        'tSTRe': '<path d="M10 0 L10 20" stroke="currentColor" stroke-width="2.4"/>' +
                 '<path d="M4 17 h12 M6 20 h8" stroke="currentColor" stroke-width="1.1" opacity=".5"/>',
        'HUB': '<circle cx="10" cy="10" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>',
        'HUBa': '<path d="M10 10 a3.2 3.2 0 0 1 3.2 -3.2 L10 10 Z" fill="currentColor"/>',
        'HUBaq': '<path d="M10 10 a3.2 3.2 0 0 0 0 -6.4 L10 10 Z" fill="currentColor"/>',
        'HUBe': '<path d="M10 10 a3.2 3.2 0 0 1 -3.2 3.2 L10 10 Z" fill="currentColor"/>',
        'HUBeq': '<path d="M10 10 a3.2 3.2 0 0 0 0 6.4 L10 10 Z" fill="currentColor"/>',
        'KHSTa': '<path d="M10 0 L10 20" stroke="currentColor" stroke-width="2.4"/>' +
                 '<circle cx="10" cy="10" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    }
    if tunnel:
        nodes['STR'] = nodes['TUNNEL1']
    body = nodes.get(base) or nodes.get(t) or vert
    # 覆盖图标（如 O1=HUBa 叠加在 BHF 上）
    for ov in overlays:
        ob = nodes.get(re.sub(r'[+lrqgfm1-9-]+$', '', ov)) or ''
        if ob and ('circle' in ob or 'path' in ob):
            body += ob
    return body


def strip_wiki(s):
    """去掉 [[链接]]、<ref>、{{}}、HTML 标签，保留可读文字。"""
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', s)
    s = re.sub(r'\{[^{}]*\}', '', s)
    return s.strip()


_ICON_RE = re.compile(r'^[OP]\d+=|^[A-Za-z][A-Za-z0-9+.\-@]*\d*$')
_ICONISH_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-@()]*\d*$')


def _keepable(p):
    """嵌套模板参数里值得保留的：含非 ASCII 的文字（日文/中文站名注释、Ü 等）或里程数字。"""
    if not p:
        return False
    if re.search(r'[^\x00-\x7f]', p):
        return True
    return bool(re.match(r'^[\d,.\-]+(m|km|T)?$', p))


def flatten_templates(s):
    """把行内嵌套的 {{BSn|...}} 子模板展平：丢弃子模板的图标/修饰参数，
    保留文字参数（站名/注释/里程），避免图标代码泄漏进文字列。迭代剥到无 {{ 为止。"""
    def rep(m):
        inner = m.group(0)[2:-2]
        parts = inner.split('|')[1:]  # 跳过模板名
        keep = [p for p in parts if _keepable(p)]
        return '|'.join(keep) if keep else ''
    for _ in range(6):
        s2 = re.sub(r'\{\{[^{}]*\}\}', rep, s)
        if s2 == s:
            break
        s = s2
    return s


def parse_bs_rows(text):
    """从 wikitext 提取 {{BSn|...}} / {{BSn-x|...}} 行。

    按字段类型分流（不依赖 BS 模板参数位置——维基 O/P 修饰与图标位混排，位置启发式必然出错）：
      icon 风格（STR/BHF/O1=HUBa/uSTRc4…）→ 图标列
      数字 → 里程；其余 → 站名/注释
    """
    rows = []
    for m in re.finditer(r'^\{\{(BS\d+(?:-\d+)?)\|(.*?)\}\}\s*$', text, re.M):
        tpl, body = m.group(1), m.group(2)
        # 预处理：[[A|B]]→B、ref/嵌套模板剔除（避免其内部 | 污染字段）
        body2 = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', body)
        body2 = re.sub(r'<ref[^>]*/>', '', body2)
        body2 = re.sub(r'<ref[^>]*>.*?</ref>', '', body2, flags=re.S)
        body2 = flatten_templates(body2)
        parts = [x for x in body2.split('|') if not re.match(r'^\s*\d+px\s*$', x)]
        icons = []
        texts = []
        for p in parts:
            if not p:
                continue
            if _ICON_RE.match(p) and len(icons) < 8:
                icons.append(p)
            elif (len(p) <= 20 and not re.search(r'[\s\u3000-\u9fff]', p)
                  and re.match(r'^[A-Za-zÜü]', p)):
                continue   # 疑似图标代码（纯 ASCII/无全角、字母开头、无空格）：不渲染也不显示
            else:
                texts.append(clean_txt(p))
        km = texts[0] if texts and re.match(r'^[\d,\.\-]+', texts[0]) else ''
        if km and len(texts) > 1:
            name = texts[1]
            note = ' '.join(texts[2:])
        else:
            name = texts[0] if texts else ''
            note = ' '.join(texts[1:])
        rows.append({'icons': icons, 'km': km, 'name': name, 'note': note})
    return rows


def clean_txt(s):
    """去掉模板残留：'''粗体'''、[0014px link=xxx 名称]、{}、行内 14px 样式后缀 等。"""
    s = re.sub(r"'''", '', s)
    s = re.sub(r'\[\s*\d+px\s+link=[^\s\]]+\s+([^\]]+)\]', r'\1', s)   # [14px link=xxx 名称] → 名称
    s = re.sub(r'link=[^\s\]]+', '', s)
    s = re.sub(r'\{\}', '', s)
    s = re.sub(r'\d+px', '', s)     # 行内样式后缀（東急田園都市線14px → 東急田園都市線）
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def render_svg(lname, rows):
    """rows → BS 风格深色 SVG。左=图标列，右=里程/站名/注释。"""
    if not rows:
        return ''
    ROWH = 22
    NW = 26 * max((len(r['icons']) for r in rows), default=1)
    H = ROWH * len(rows) + 14
    W = NW + 300
    parts = []
    for i, r in enumerate(rows):
        y = 8 + i * ROWH
        for c, ic in enumerate(r['icons']):
            cx = 6 + c * 26
            body = icon_svg(ic)
            for ov in ic.split('|')[1:]:
                body += icon_svg(ov)
            parts.append('<g transform="translate(%d,%d)" color="#cfe0f5">%s</g>' % (cx, y - 10, body))
        tx = NW + 6
        txt = []
        if r['km']:
            txt.append('<text x="%d" y="%d" font-size="10" fill="rgba(150,165,190,.9)">%s</text>' % (tx, y + 4, esc(r['km'])))
        nm = r['name']
        is_dir = bool(nm) and nm[0] in '↑↓←→'
        if nm and not is_dir:
            txt.append('<text x="%d" y="%d" font-size="10.5" font-weight="600" fill="rgba(235,242,252,.97)">%s</text>' % (tx + 46, y + 4, esc(nm)))
        elif nm:
            txt.append('<text x="%d" y="%d" font-size="9.5" fill="rgba(160,175,200,.92)">%s</text>' % (tx + 46, y + 4, esc(nm)))
        if r['note']:
            txt.append('<text x="%d" y="%d" font-size="9.5" fill="rgba(160,175,200,.92)">%s</text>' % (tx + 130, y + 4, esc(r['note'])))
        parts.append(''.join(txt))
    return ('<figure class="mapfig diag"><svg viewBox="0 0 %d %d" role="img" aria-label="%s 全线配线图（维基 BS 版式）" xmlns="http://www.w3.org/2000/svg">%s</svg>'
            '<figcaption>全线配线图（依据维基百科「%s」词条的铁路系统标示模板数据渲染）</figcaption></figure>'
            % (W, H, esc(lname), ''.join(parts), esc(lname)))


def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def api_get(params, host=API_JA, timeout=30):
    params = dict(params, format='json', formatversion='2')
    url = host + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def fetch_wikitexts(titles):
    """批量拿 wikitext：{title: content}"""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        d = api_get({'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                     'rvslots': 'main', 'titles': '|'.join(chunk)})
        for pg in d.get('query', {}).get('pages', []):
            revs = pg.get('revisions') or []
            if revs:
                main = (revs[0].get('slots') or {}).get('main') or {}
                out[pg['title']] = main.get('content', '')
        time.sleep(0.2)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    limit = None
    if '--limit-lines' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit-lines') + 1])
    titles_arg = None
    if '--titles' in sys.argv:
        titles_arg = [x.strip() for x in sys.argv[sys.argv.index('--titles') + 1].split(',') if x.strip()]
    cache = json.load(open(os.path.join(DATA, 'eki_wiki_cache.json'), encoding='utf-8'))
    idx = json.load(open(OUT_IDX, encoding='utf-8')) if os.path.exists(OUT_IDX) else {}
    # 词条名集合：① 全部线路名（segments3d 轨道数据的 line，自身即候选 ja 词条名）
    #             ② cache 词条 line title 覆盖（更规范）
    sm = json.load(open(os.path.join(DATA, 'segments3d.geojson'), encoding='utf-8'))
    lnames = {}
    for f in sm.get('features', []):
        ln = f.get('properties', {}).get('line') or ''
        if ln:
            lnames.setdefault(ln, ln)
    # 站 lines 兜底（轨道段缺失的线）
    stmap = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
    for v in stmap.get('stations', {}).values():
        for ln in v.get('lines') or []:
            lnames.setdefault(ln, ln)
    for f, ent in cache.items():
        line = ent.get('line') or {}
        lj = line.get('ja') or {}
        lz = line.get('zh') or {}
        t = lj.get('title') or lz.get('title')
        if t:
            lnames.setdefault(t, f)
    names = list(lnames.keys())
    if titles_arg:
        names = [t for t in titles_arg if t in lnames]
        print('按 --titles 取词条:', names, flush=True)
    if limit:
        names = names[:limit]
    print('待抓线路词条:', len(names), flush=True)
    wts = fetch_wikitexts(names)
    print('已取得 wikitext:', len(wts), flush=True)
    n_bs = 0
    for title in names:
        text = wts.get(title)
        if not text:
            print('  !! 无内容: %s' % title, flush=True)
            continue
        rows = parse_bs_rows(text)
        if not rows:
            continue
        n_bs += 1
        svg = render_svg(title, rows)
        fn = os.path.join(OUT_DIR, title + '.svg')
        open(fn, 'w', encoding='utf-8').write(svg)
        idx[title] = {'rows': len(rows), 'source': 'https://ja.wikipedia.org/wiki/' + urllib.parse.quote(title),
                      'bytes': len(svg)}
        print('  [%d] %s: %d 行' % (n_bs, title, len(rows)), flush=True)
    json.dump(idx, open(OUT_IDX, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('完成: %d/%d 线路含 BS 配线图' % (n_bs, len(names)), flush=True)


if __name__ == '__main__':
    main()

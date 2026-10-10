#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini JapanRail — SEO 静态化生成器
=====================================
为纯静态部署生成「伪静态」SEO 页面（每线路 / 每车站一个独立 HTML），以及
sitemap / robots / 404 / OG 分享图等搜索引擎基础设施。

用法:
    python3 seo/build_seo_static.py                 # 输出到仓库根目录
    python3 seo/build_seo_static.py --root /path    # 输出到指定目录
    python3 seo/build_seo_static.py --config ...    # 指定配置

设计要点（不影响主站 index.html 的任何交互功能）:
  * 每线路 → lines/<线路名>/index.html
  * 每车站 → stations/<站名>/index.html
  * 页面为纯 HTML（无 JS 依赖），爬虫直接拿到完整数据；
  * 页面内嵌 ja / zh / en 三语站名、线路名，覆盖各语言搜索引擎；
  * JSON-LD 结构化数据（TrainStation / BreadcrumbList / ItemList）；
  * 每个页面带 canonical、OG / Twitter 标签，并回链主站地图（hash 深链）；
  * 输出 sitemap.xml（索引）+ sitemap-lines / sitemap-stations / sitemap-pages；
  * 输出 robots.txt、404.html、og-image.png。

只依赖 Python 标准库（PIL 可选，仅用于生成 og-image.png，缺失时跳过并告警）。
"""
import argparse
import base64
import json
import math
import os
import re
import sys
import urllib.parse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # mini-japanrail-3d/
CONFIG_PATH = os.path.join(ROOT, 'seo', 'seo_config.json')
DATA_DIR = os.path.join(ROOT, 'data')

DEFAULT_CONFIG = {
    'site_base': 'https://jr.suki.ing',
    'site_name': 'Mini JapanRail',
    'default_lang': 'zh-Hans',
    'og_image': 'og-image.png',
    'lastmod_date': '',
}
FALLBACK_COLOR = '#4f8ef7'
FALLBACK_KIND = '鉄道'


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception as e:
        print('[warn] 无法读取配置 %s: %s，使用默认值' % (path, e))
    cfg['site_base'] = cfg['site_base'].rstrip('/')
    return cfg


# ---------------- HTML 转义 / URL ----------------
def esc(s):
    return (str(s if s is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def xml_esc(s):
    return (str(s if s is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def quote_path(s):
    """URL 路径段百分号编码（保留中文可读性，兼容所有静态主机）。"""
    return urllib.parse.quote(str(s), safe='')


def abs_url(cfg, path):
    if path.startswith('http'):
        return path
    return cfg['site_base'] + '/' + path.lstrip('/')


# ---------------- 中文转写（与主站 index.html 的 toZh 完全一致） ----------------
def parse_js_obj(text):
    """解析 JS 中的 { '键':'值', ... } 对象字面量。"""
    pairs = re.findall(r"'([^']*)'\s*:\s*'([^']*)'", text)
    return dict(pairs)


def build_tozh(index_html):
    m = re.search(r'const JP2CN = \{(.*?)\};', index_html, re.S)
    m2 = re.search(r'const KANA2ZH = \{(.*?)\};', index_html, re.S)
    JP2CN = parse_js_obj(m.group(1)) if m else {}
    KANA2ZH = parse_js_obj(m2.group(1)) if m2 else {}
    MONO_RE = re.compile(r'モノレール')

    def tozh(s):
        s = str(s)
        for k, v in KANA2ZH.items():
            s = s.replace(k, v)
        mono = []
        s = MONO_RE.sub(lambda mm: (mono.append(mm.group(0)) or '\ue000'), s)
        out = ''.join(JP2CN.get(ch, ch) for ch in s)
        for m_ in mono:
            out = out.replace('\ue000', m_)
        return out
    return tozh


# ---------------- 数据加载 ----------------
def load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding='utf-8') as f:
        return json.load(f)


def build_canon(lines_map):
    """lines_map: {canonical: [alias...]} → {任意名字: canonical}（含自身）。"""
    canon_of = {}
    for c, aliases in lines_map.items():
        canon_of[c] = c
        for a in aliases:
            canon_of.setdefault(a, c)
    return canon_of


# ---------------- 记录构建 ----------------
def build_records(cfg):
    sm = load_json('station_map.json')
    ni = load_json('names_i18n.json')
    sg = load_json('segments3d.geojson')
    lm = load_json('lines_map.json')
    skj = load_json('station_key_index.json')  # 裸名 → 消歧候选（含ケ/ヶ 等写法变体）
    try:
        wiki = load_json('line_wiki.json')    # Wikipedia 线路摘要缓存（可缺省）
    except Exception:
        wiki = {}
    try:
        eki_cache = load_json('eki_wiki_cache.json')  # 站内本地化百科词条（ooep/eki-wiki 同源精简缓存）
    except Exception:
        eki_cache = {}
    try:
        floorplan = load_json('eki_floorplan.json')   # 站 key → 构内図（配线图）直链索引
    except Exception:
        floorplan = {}
    try:
        wlm = load_json('wiki_line_map.json')         # 站key → 词条线路文件（与主站信息 tab 同源）
    except Exception:
        wlm = {}
    index_html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    tozh = build_tozh(index_html)
    canon_of = build_canon(lm)

    ni_st = ni.get('stations') or {}
    ni_lines = ni.get('lines') or {}
    stations = sm['stations']

    # ---- 车站记录 ----
    st = {}
    for key, v in stations.items():
        name = v.get('name') or key
        lns = [canon_of.get(l, l) for l in (v.get('lines') or [])]
        # 去重保序
        seen, lines_c = set(), []
        for l in lns:
            if l not in seen:
                seen.add(l)
                lines_c.append(l)
        i18n = ni_st.get(key) or ni_st.get(name) or {}
        zh = tozh(name)
        st[key] = {
            'key': key, 'name': name, 'pref': v.get('pref') or '',
            'coord': v.get('coord') or [0, 0],
            'lines': lines_c,
            'en': (i18n.get('en') or '').strip(),
            'kana': (i18n.get('kana') or '').strip(),
            'zh': zh,
            'derived': v.get('derived', False),
        }

    # ---- 线路记录 ----
    raw_names = set()
    for f in sg['features']:
        raw_names.add(f['properties'].get('line') or '')
    for v in stations.values():
        for l in v.get('lines') or []:
            raw_names.add(l)
    raw_names.discard('')

    lines = {}
    for raw in sorted(raw_names):
        c = canon_of.get(raw, raw)
        rec = lines.setdefault(c, {
            'name': c, 'color': FALLBACK_COLOR, 'kind': FALLBACK_KIND,
            'op': '', 'raw_names': set(), 'seg_features': [],
            'station_keys': [], 'coord_sum': [0.0, 0.0], 'coord_n': 0,
            'en': '', 'zh': tozh(c),
        })
        rec['raw_names'].add(raw)

    # 给线路补色/类型/运营方
    for f in sg['features']:
        p = f['properties']
        line = p.get('line') or ''
        if not line:
            continue
        c = canon_of.get(line, line)
        if c not in lines:
            continue
        rec = lines[c]
        rec['seg_features'].append(f)
        if not rec['color'] or rec['color'] == FALLBACK_COLOR:
            rec['color'] = p.get('color') or FALLBACK_COLOR
        if not rec['kind'] or rec['kind'] == FALLBACK_KIND:
            rec['kind'] = p.get('kind') or FALLBACK_KIND
        if not rec['op']:
            rec['op'] = p.get('op') or ''

    # 线路 → 车站集合 / 中心点
    for key, rec in st.items():
        for l in rec['lines']:
            if l in lines:
                lr = lines[l]
                lr['station_keys'].append(key)
                lr['coord_sum'][0] += rec['coord'][0]
                lr['coord_sum'][1] += rec['coord'][1]
                lr['coord_n'] += 1

    for l, rec in lines.items():
        rec['station_keys'] = sorted(set(rec['station_keys']))
        if rec['coord_n']:
            rec['centroid'] = [rec['coord_sum'][0] / rec['coord_n'],
                               rec['coord_sum'][1] / rec['coord_n']]
        else:
            rec['centroid'] = [135.5, 36.5]
        # en 名：优先取有英文名的原始名
        rec['en'] = next((ni_lines.get(r, '') for r in sorted(rec['raw_names']) if ni_lines.get(r)), ni_lines.get(l, '')).strip()

    # ---- 线路长度（沿轨道折线估算，去重边）----
    for l, rec in lines.items():
        seen_e, km = set(), 0.0
        for f in rec['seg_features']:
            p = f['properties']
            a, b = p.get('from'), p.get('to')
            if not a or not b or a == b:
                continue
            e = (a, b) if a < b else (b, a)
            if e in seen_e:
                continue
            seen_e.add(e)
            ca = st.get(a, {}).get('coord') if a in st else None
            cb = st.get(b, {}).get('coord') if b in st else None
            if ca and cb:
                km += haversine_km(ca, cb)
        rec['approx_km'] = round(km)

    # ---- 同名车站分组（用于消歧链接与裸名解析）----
    name_groups = defaultdict(list)
    for key, rec in st.items():
        name_groups[rec['name']].append(key)

    # ---- 每线：裸名 → 消歧 key 邻接表（segments 与 station_map 站名写法不一致）----
    resolved_adjs = {l: resolve_line_adj(rec, st, name_groups, skj) for l, rec in lines.items()}

    # ---- 线路车站沿轨道顺序 ----
    line_orders = {}
    for l, rec in lines.items():
        line_orders[l] = order_line_stations(resolved_adjs[l], set(st), rec['station_keys'])

    # ---- 线路途经都道府县（按沿轨道真实站序，避免 station_map 直通归并污染）----
    for l, rec in lines.items():
        seen_p, prefs, cnt = set(), [], {}
        for k in line_orders[l]:
            p = st[k].get('pref') or ''
            if p:
                cnt[p] = cnt.get(p, 0) + 1
                if p not in seen_p:
                    seen_p.add(p)
                    prefs.append(p)
        rec['prefs'] = prefs
        rec['pref_counts'] = cnt  # 途经县 → 站数（供线路页明细）

    # ---- 相邻车站（按线路，key 级）----
    adj = defaultdict(list)
    for l, adj_ in resolved_adjs.items():
        seen_e = set()
        for a, lst in adj_.items():
            for b in lst:
                if a == b:
                    continue
                e = (a, b) if a < b else (b, a)
                if e in seen_e:
                    continue
                seen_e.add(e)
                adj[a].append((l, b))
                adj[b].append((l, a))

    neighbors = defaultdict(list)  # station_key → [(line, other)]
    for k, lst in adj.items():
        seen_n = set()
        for l, o in lst:
            if (l, o) not in seen_n:
                seen_n.add((l, o))
                neighbors[k].append((l, o))

    # ---- 附近车站（同都道府县内地理最近 5 站 + 距离公里）----
    by_pref = defaultdict(list)
    for k, r in st.items():
        by_pref[r.get('pref') or '—'].append(k)
    nearby = {}
    for k, r in st.items():
        c = r['coord']
        pf = r.get('pref') or '—'
        ds = []
        for o in by_pref[pf]:
            if o == k:
                continue
            oc = st[o]['coord']
            d = (oc[0] - c[0]) ** 2 + (oc[1] - c[1]) ** 2
            ds.append((d, o))
        ds.sort()
        nearby[k] = [(o, round(haversine_km(c, st[o]['coord']), 1)) for _, o in ds[:5]]

    return {
        'cfg': cfg, 'tozh': tozh, 'canon_of': canon_of,
        'stations': st, 'lines': lines, 'neighbors': neighbors,
        'name_groups': dict(name_groups), 'line_orders': line_orders,
        'nearby': nearby, 'line_wiki': wiki,
        'eki_cache': eki_cache, 'wlm': wlm, 'floorplan': floorplan,
        'station_map_meta': {k: sm[k] for k in ('generated_at',) if k in sm},
    }


# ---------------- 线路车站排序（沿轨道顺序） ----------------
def haversine_km(a, b):
    """两坐标点间大圆距离（公里，用于线路长度粗估算）。"""
    import math
    R = 6371.0
    la1, lo1 = math.radians(a[1]), math.radians(a[0])
    la2, lo2 = math.radians(b[1]), math.radians(b[0])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def resolve_line_adj(rec, st, name_groups, skj):
    """把线路 segments 的 from/to 裸名解析为 station_map 消歧 key，返回 key 级邻接表。

    segments3d 与 station_map 站名写法不一致（如 市ヶ谷 vs 市ケ谷、
    三宮 vs 三宮(神戸市営)）。解析顺序：station_map key → name 字段分组 →
    station_key_index（含 ヶ/ケ 等写法变体）；多候选用已解析邻居坐标取最近，
    最后无上下文的多候选取首项兜底（保证有独立页面）。
    """
    edges, nodes = [], set()
    for f in rec['seg_features']:
        p = f['properties']
        a, b = p.get('from'), p.get('to')
        if not a or not b or a == b:
            continue
        edges.append((a, b))
        nodes.add(a)
        nodes.add(b)

    def cands_of(n):
        c = name_groups.get(n)
        if c:
            return c
        idx = skj.get(n)
        return [d['k'] for d in idx] if idx else None

    def nearest(cands, hint):
        best, bd = None, None
        for k in cands:
            c = st[k]['coord']
            d = (c[0] - hint[0]) ** 2 + (c[1] - hint[1]) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        return best

    resolved = {}
    for n in nodes:
        if n in st:
            resolved[n] = n
        else:
            cands = cands_of(n)
            if cands and len(cands) == 1:
                resolved[n] = cands[0]

    pending = [n for n in nodes if n not in resolved]
    while pending:
        progressed = False
        for n in list(pending):
            cands = cands_of(n)
            if not cands:
                pending.remove(n)
                continue
            hint = None
            for (a, b) in edges:
                if a == n and b in resolved:
                    hint = st[resolved[b]]['coord']
                    break
                if b == n and a in resolved:
                    hint = st[resolved[a]]['coord']
                    break
            if hint:
                resolved[n] = nearest(cands, hint)
                pending.remove(n)
                progressed = True
        if not progressed:
            for n in list(pending):
                cands = cands_of(n)
                if cands:
                    resolved[n] = cands[0]
                pending.remove(n)

    adj = defaultdict(list)
    for (a, b) in edges:
        ra, rb = resolved.get(a), resolved.get(b)
        if ra and rb and ra != rb:
            if rb not in adj[ra]:
                adj[ra].append(rb)
            if ra not in adj[rb]:
                adj[rb].append(ra)
    return adj


def order_line_stations(adj, known, station_keys):
    nodes = [k for k in adj if k in known]
    if not nodes:
        return sorted(station_keys)
    deg1 = [k for k in nodes if len(adj[k]) == 1]
    start = deg1[0] if deg1 else sorted(nodes)[0]
    seq, seen = [], set()
    cur = start
    seen.add(cur)
    seq.append(cur)
    while True:
        nbrs = [n for n in adj[cur] if n not in seen and n in known]
        if not nbrs:
            break
        # 优先沿「度>1」的邻居走（主线），支线留待末尾
        spine = [n for n in nbrs if len(adj[n]) > 1]
        nxt = spine[0] if spine else nbrs[0]
        seen.add(nxt)
        seq.append(nxt)
        cur = nxt
    for n in sorted(adj):
        if n not in seen and n in known:
            seq.append(n)
    return seq


# ---------------- 主站地图深链（与 index.html stateHash 同构） ----------------
def map_hash(lng, lat, zoom, lang='zh', extra=None):
    """stateHash JSON。extra 携带 SEO 深链字段 {t:'line'|'station', q:名称}——
    主站 applyUrlState/hashchange 据此选中线路/车站；旧链接无 t/q 行为不变。"""
    h = {'c': [round(float(lng), 4), round(float(lat), 4)], 'z': round(float(zoom), 2),
         'p': 0, 'b': 0, 'j': 'globe', 'l': lang, 'm': 'auto', 'v': 0, 's': 'pale'}
    if extra:
        h.update(extra)
    return base64.b64encode(json.dumps(h, separators=(',', ':')).encode('utf-8')).decode()


def map_url(cfg, lng, lat, zoom, lang='zh', extra=None):
    return abs_url(cfg, 'index.html#mjr3d=' + map_hash(lng, lat, zoom, lang, extra))


def wiki_links_html(cfg, ja_name, zh_name, en_name):
    """三语 Wikipedia 相关百科外链：ja 词条直链，zh/en 用 Special:Search 兜底（避免死链）。"""
    ja = 'https://ja.wikipedia.org/wiki/' + urllib.parse.quote(ja_name.replace(' ', '_'))
    zh = 'https://zh.wikipedia.org/wiki/Special:Search?search=' + urllib.parse.quote(zh_name or ja_name)
    en = 'https://en.wikipedia.org/wiki/Special:Search?search=' + urllib.parse.quote(en_name or ja_name)
    return ('<p class="wiki-links">相关百科：'
            '<a href="%s" hreflang="ja" rel="noopener">日本語 Wikipedia</a> · '
            '<a href="%s" hreflang="zh-Hans" rel="noopener">中文维基百科</a> · '
            '<a href="%s" hreflang="en" rel="noopener">English Wikipedia</a></p>\n'
            % (esc(ja), esc(zh), esc(en)))


# ---------------- 本地化百科词条（ooep/eki-wiki 同源，主站「信息 tab」用同一数据） ----------------
_LINE_SUFFIX = re.compile(r'号線|線|本線|快速線|新線|支線')
_ZH_CONV = re.compile(r'-\{-\}|（\s*）|\(\s*\)')


def _norm_sta(s):
    """站名归一：ケ/ヶ 统一，尾部「駅」转「站」（词条按中文站名组织）。"""
    s = (s or '').strip().replace('ケ', 'ヶ')
    if s.endswith('駅'):
        s = s[:-1] + '站'
    return s


def _norm_line_title(t):
    """线路词条标题归一（同主站 normLineName）：ケ/ヶ 统一 + 去 線/本線 等后缀。"""
    return _LINE_SUFFIX.sub('', (t or '').replace('ケ', 'ヶ'))


def _clean_lead(s):
    """清洗词条首段：去 MediaWiki 变体转换标记 -{}- / {...}、空括号（音读过滤后残留）。"""
    s = re.sub(r'-\{}-', '', s or '')
    s = re.sub(r'\{[^{}]*\}', '', s)
    s = _ZH_CONV.sub('', s)
    return s.strip()


def _common_suffix(a, b):
    """最长公共后缀（用于 canonical 编号名 ↔ 词条通称 匹配，如 3号線銀座線 ↔ 東京メトロ銀座線）。"""
    i = 0
    la, lb = len(a), len(b)
    while i < la and i < lb and a[-1 - i] == b[-1 - i]:
        i += 1
    return a[-i:] if i else ''


def eki_line_for(lname, keys, cache, wlm, tozh):
    """线路页取词条文件：词条标题（去运营前缀后）与 canonical 名相等或公共后缀≥2字。"""
    if not cache:
        return None
    nl = _norm_line_title(lname)
    m = re.search(r'[（(]([^（）()]*)[）)]$', nl)
    if m and len(m.group(1)) >= 2:
        nl = m.group(1).strip()   # 尾部括号注记取通称（1号線(御堂筋線)→御堂筋）
    if nl:
        for f in cache:
            lj = cache[f]['line'].get('ja') or {}
            lz = cache[f]['line'].get('zh') or {}
            t = lj.get('title') or lz.get('title')
            if not t:
                continue
            nt = _norm_line_title(t)
            if nt == nl:
                return f
            if len(nt) >= 2 and len(_common_suffix(nl, nt)) >= 2:
                return f
    cnt = {}
    for k in (keys or []):
        f = wlm.get(k)
        if f and f in cache:
            cnt[f] = cnt.get(f, 0) + 1
    if cnt:
        best = max(cnt, key=cnt.get)
        bj = cache[best]['line'].get('ja') or {}
        bz = cache[best]['line'].get('zh') or {}
        bt = bj.get('title') or bz.get('title')
        if bt and _norm_line_title(bt) == nl:
            return best
    return None


def eki_station_for(key, name, wlm, cache):
    """站页取词条：wiki_line_map[key] → 文件内按归一站名找车站条目。"""
    if not cache:
        return None
    f = wlm.get(key)
    if not f or f not in cache:
        return None
    sts = cache[f]['stations']
    for cand in (_norm_sta(key), _norm_sta(name), name):
        if cand in sts:
            return sts[cand]
    return None


def station_line_diagram(rec, stations, line_orders, lines, max_lines=5):
    """基于站内真实轨道数据（沿轨道站序 + 坐标）自绘「站线配置示意」SVG。

    取该站每条途经线路在站序中的前后邻站窗口，投影到以本站为中心的局部平面，
    绘制轨道走向折线（线路色）、本站站台条、行车方向箭头与线路图例。
    返回内联 SVG 字符串；无轨道数据时返回空串。示意性质，非股道级真实配线图。
    """
    key = rec['key']
    me = stations.get(key)
    if not me:
        return ''
    paths = []
    for l in rec.get('lines') or []:
        if len(paths) >= max_lines:
            break
        seq = line_orders.get(l)
        if not seq or key not in seq:
            continue
        i = seq.index(key)
        win = seq[max(0, i - 2):i + 3]
        pts = []
        for k2 in win:
            c = stations.get(k2)
            if c and c.get('coord'):
                pts.append((k2, c['coord']))
        if len(pts) >= 2:
            paths.append((l, pts))
    if not paths:
        return ''
    cx, cy = me['coord']
    k = math.cos(math.radians(cy))
    W, H, pad = 300, 220, 30
    def proj(c):
        return ((c[0] - cx) * k, c[1] - cy)
    flat = [proj(c) for _, ps in paths for _, c in ps]
    xs = [p[0] for p in flat]
    ys = [p[1] for p in flat]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    s = 1.0
    if span_x > 1e-9 or span_y > 1e-9:
        s = min((W - 2 * pad) / span_x if span_x > 1e-9 else 1e9,
                (H - 2 * pad) / span_y if span_y > 1e-9 else 1e9)
    s = min(s, 60.0)  # 防极端放大（邻站极近时）
    def X(c):
        return W / 2 + (proj(c)[0] - proj(me['coord'])[0]) * s
    def Y(c):
        return H / 2 + (proj(c)[1] - proj(me['coord'])[1]) * s
    # 图例（最多 4 条，其余合计）
    legend = []
    for l, ps in paths[:4]:
        col = (lines.get(l) or {}).get('color') or FALLBACK_COLOR
        legend.append('<span class="lg"><i style="background:' + esc(col) + '"></i>' + esc(l) + '</span>')
    more_n = len(paths) - 4
    if more_n > 0:
        legend.append('<span class="lg"><i style="background:#aab"></i>等 %d 条线路</span>' % more_n)
    # 绘制：先画轨道线（邻站→本站→邻站），再本站站台条，再箭头
    svg_parts = []
    for l, ps in paths:
        col = (lines.get(l) or {}).get('color') or FALLBACK_COLOR
        d = ''
        first = True
        for k2, c in ps:
            d += ('M' if first else 'L') + '%.1f %.1f' % (X(c), Y(c))
            first = False
        svg_parts.append('<path d="' + d + '" fill="none" stroke="' + esc(col) + '" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" opacity=".92"/>')
    # 站台条：本站点，垂直于主线走向
    main_pts = []
    for l, ps in paths[:1]:
        for k2, c in ps:
            main_pts.append((X(c), Y(c)))
    if len(main_pts) >= 2:
        mx, my = main_pts[0]
        nx, ny = main_pts[-1]
        dx, dy = nx - mx, ny - my
        ln = math.hypot(dx, dy) or 1
        px, py = -dy / ln, dx / ln
        hx, hy = X(me['coord']), Y(me['coord'])
        svg_parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="rgba(255,255,255,.55)" stroke-width="4"/>' % (hx - px * 9, hy - py * 9, hx + px * 9, hy + py * 9))
    # 方向箭头（沿各线末段指向行进方向：站序 = 上行→下行）
    for l, ps in paths:
        if len(ps) < 2:
            continue
        p1 = proj(ps[-2][1]); p2 = proj(ps[-1][1])
        ax1, ay1 = X(ps[-2][1]), Y(ps[-2][1])
        ax2, ay2 = X(ps[-1][1]), Y(ps[-1][1])
        vx, vy = ax2 - ax1, ay2 - ay1
        vln = math.hypot(vx, vy) or 1
        ux, uy = vx / vln, vy / vln
        bx, by = ax1 + ux * (vln * 0.55), ay1 + uy * (vln * 0.55)
        tip_x, tip_y = bx + ux * 8, by + uy * 8
        nx_, ny_ = -uy, ux
        svg_parts.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="rgba(255,255,255,.85)"/>' % (
            bx - nx_ * 4, by - ny_ * 4, bx + nx_ * 4, by + ny_ * 4, tip_x, tip_y))
    # 邻站名（每线路仅标与本站轨道直接相连、最近的一个邻站；去重、加底防叠字）
    labels = []
    for l, ps in paths:
        a, z = ps[0][0], ps[-1][0]
        ca_, cz_ = stations[a]['coord'], stations[z]['coord']
        da_ = (ca_[0] - cx) ** 2 + (ca_[1] - cy) ** 2
        dz_ = (cz_[0] - cx) ** 2 + (cz_[1] - cy) ** 2
        pick = a if da_ <= dz_ else z
        if pick == key or any(o == pick for o, _, _, _ in labels):
            continue
        nm = stations.get(pick, {}).get('name') or pick
        labels.append((pick, nm, X(stations[pick]['coord']), Y(stations[pick]['coord'])))
    for k2, nm, lx_, ly_ in labels[:5]:
        svg_parts.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="rgba(255,255,255,.7)"/>' % (lx_, ly_))
        anchor = 'middle'
        if lx_ < 44:
            anchor = 'start'; tx = 4
        elif lx_ > W - 44:
            anchor = 'end'; tx = W - 4
        else:
            tx = lx_
        # 默认放站点上方；视图上半部可放下方，避免与本站名区重叠
        ty = ly_ + 15 if ly_ < 66 else ly_ - 9
        if ty > H - 12:
            ty = ly_ - 9
        wdt = len(nm) * 5.6 + 8
        bx = tx - wdt / 2 if anchor == 'middle' else tx
        if anchor == 'end':
            bx = tx - wdt
        svg_parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="12" rx="3" fill="rgba(6,10,18,.72)"/>' % (bx, ty - 9.5, wdt))
        svg_parts.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="9.5" fill="rgba(230,238,250,.95)">%s</text>' % (tx, ty, anchor, esc(nm)))
    # 本站名（左下角固定，避免中心堆叠）
    nm_me = rec.get('name') or key
    wdt = len(nm_me) * 6.6 + 14
    svg_parts.append('<rect x="8" y="%d" width="%.1f" height="16" rx="5" fill="rgba(47,109,232,.55)"/>' % (H - 26, wdt))
    svg_parts.append('<text x="15" y="%d" font-size="11" font-weight="700" fill="rgba(255,255,255,.98)">%s</text>' % (H - 14, esc(nm_me)))
    lg_html = '<div class="lgrow">' + ''.join(legend) + '</div>'
    return ('<figure class="mapfig diag">'
            '<svg viewBox="0 0 %d %d" role="img" aria-label="%s 站线配置示意" xmlns="http://www.w3.org/2000/svg">'
            '%s</svg>'
            '<figcaption>站线配置示意（基于站内轨道数据绘制，含本站与邻近车站的线路走向）</figcaption>%s</figure>'
            % (W, H, esc(rec.get('name') or key), ''.join(svg_parts), lg_html))


def eki_brief_html(sec_id, title, entry, lang, more_url=''):
    """本地化词条 → 「百科简介」玻璃卡（清洗后首段 + 延伸章节 + 跳转主站实时地图的链接）。"""
    if not entry:
        return ''
    lead = _clean_lead(entry.get('lead'))
    if not lead:
        return ''
    if len(lead) > 300:
        lead = lead[:297] + '…'
    more = (' <a class="mini" href="' + esc(more_url) + '">在主站查看 ↗</a>') if more_url else ''
    ch_html = ''
    for ch in (entry.get('chapters') or [])[:2]:
        t = _clean_lead(ch.get('t'))
        if t:
            ch_html += ('<span class="wiki-ch"><b>' + esc(ch.get('h') or '') + '</b>：'
                        + esc(t) + '</span>')
    return ('<h2 id="' + sec_id + '" style="--lc:#5fd4f4">' + esc(title) + '</h2>\n'
            '<p class="wiki-x"><span lang="' + lang + '">' + esc(lead) + '</span>' + more + ch_html + '</p>\n')


# ---------------- 模板 ----------------
# 样式与主站 index.html 的「Liquid Glass 液态玻璃」设计语言对齐
# （--glass / --glass-panel / --glass-edge / --acc / --r 等 token 同源）
CSS = """
  :root{
    --bg:#0b0f16; --txt:#e8edf4; --dim:#bccbdd;
    --acc:#2f6de8; --acc-txt:#6da9ff; --acc2:#5fd4f4;
    --glass:rgba(255,255,255,.10); --glass-2:rgba(255,255,255,.16);
    --glass-edge:rgba(255,255,255,.22); --glass-hi:rgba(255,255,255,.34); --glass-lo:rgba(0,0,0,.16);
    --glass-sh:0 6px 20px rgba(0,0,0,.30), 0 2px 6px rgba(0,0,0,.22);
    --glass-panel:linear-gradient(180deg, rgba(255,255,255,.18) 0%, rgba(255,255,255,.05) 34%, rgba(255,255,255,.09) 100%), rgba(255,255,255,.10);
    --glass-panel-blur:blur(26px) saturate(1.9);
    --r:16px; --r-sm:10px; --r-xs:7px; --r-pill:999px;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  ::-webkit-scrollbar{width:5px;height:5px}
  ::-webkit-scrollbar-thumb{background:rgba(120,140,180,.28);border-radius:3px}
  ::-webkit-scrollbar-thumb:hover{background:rgba(120,140,180,.45)}
  ::-webkit-scrollbar-track{background:transparent}
  body{min-height:100vh;font-family:-apple-system,"SF Pro SC","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Yu Gothic UI","Noto Sans JP",sans-serif;background:var(--bg);color:var(--txt);line-height:1.7;padding:30px 14px 64px;-webkit-font-smoothing:antialiased}
  body::before{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;background:
    radial-gradient(52% 44% at 16% 10%, rgba(47,109,232,.26), transparent 62%),
    radial-gradient(44% 38% at 88% 20%, rgba(95,212,244,.14), transparent 60%),
    radial-gradient(60% 50% at 50% 98%, rgba(79,142,247,.12), transparent 66%)}
  .wrap{position:relative;z-index:1;max-width:920px;margin:0 auto;background:var(--glass-panel);
    backdrop-filter:var(--glass-panel-blur);-webkit-backdrop-filter:var(--glass-panel-blur);
    border:1px solid var(--glass-edge);border-radius:22px;padding:24px 30px 30px;
    box-shadow:inset 0 1px 1px var(--glass-hi), inset 0 -1px 2px var(--glass-lo), var(--glass-sh)}
  nav.breadcrumb{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:13px;color:var(--dim);
    margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--glass-edge)}
  nav.breadcrumb a{color:var(--acc-txt);text-decoration:none;transition:color .15s}
  nav.breadcrumb a:hover{color:#8db9ff;text-decoration:underline}
  nav.breadcrumb a:first-child{display:inline-flex;align-items:center;gap:8px;font-weight:700;color:var(--txt);text-decoration:none}
  nav.breadcrumb a:first-child:hover{color:#fff;text-decoration:none}
  nav.breadcrumb a:first-child::before{content:'';width:24px;height:24px;border-radius:50%;flex:none;
    background:
      radial-gradient(circle at 32% 28%, rgba(255,255,255,.55), rgba(255,255,255,0) 52%),
      linear-gradient(180deg, transparent 32%, #fff 32%, #fff 37%, transparent 37%, transparent 54%, #fff 54%, #fff 59%, transparent 59%),
      linear-gradient(180deg,#2f6de8,#1c51d6);
    box-shadow:0 2px 8px rgba(47,109,232,.4), inset 0 1px 1px rgba(255,255,255,.45)}
  .topnav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}
  .topnav a{font-size:12.5px;font-weight:600;color:var(--txt);background:var(--glass);
    border:1px solid var(--glass-edge);border-radius:var(--r-pill);padding:5px 14px;
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    box-shadow:inset 0 1px 1px var(--glass-hi), inset 0 -1px 2px var(--glass-lo);
    transition:background .2s,border-color .2s,color .2s,transform .3s cubic-bezier(.34,1.45,.44,1)}
  .topnav a:hover{background:var(--glass-2);border-color:var(--glass-hi);color:#fff;transform:translateY(-1px);text-decoration:none}
  .topnav a:active{transform:scale(.95)}
  h1{font-size:30px;font-weight:800;letter-spacing:-.3px;line-height:1.3;margin-bottom:8px;word-break:break-all}
  h1 .alt{font-size:15px;color:var(--dim);font-weight:600}
  h1 .alt em{font-style:normal;color:var(--dim);opacity:.75}
  .lead{color:var(--dim);font-size:15px;margin-bottom:22px}
  h2{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:800;letter-spacing:.3px;
    margin:30px 0 12px;color:var(--txt);border:0;padding:0}
  h2::before{content:'';width:9px;height:9px;border-radius:3px;background:var(--lc,#4f8ef7);flex:none;
    box-shadow:0 0 10px var(--lc,#4f8ef7)}
  h2::after{content:'';flex:1;height:1px;background:var(--glass-edge)}
  ul,ol{margin:0 0 6px 2px;list-style:none}
  li{margin-bottom:5px}
  a{color:var(--acc-txt);text-decoration:none;transition:color .15s}
  a:hover{color:#8db9ff;text-decoration:underline}
  .chip{display:inline-block;font-size:13px;padding:4px 12px;border-radius:var(--r-pill);border:1px solid var(--glass-edge);margin:0 6px 8px 0;background:var(--glass)}
  .chip b{color:var(--txt)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:6px 14px}
  table.kv{width:100%;border-collapse:collapse;font-size:14px}
  table.kv th{width:110px;text-align:left;color:var(--dim);font-weight:600;padding:9px 10px;border-bottom:1px dashed var(--glass-edge);vertical-align:top}
  table.kv td{padding:9px 10px;border-bottom:1px dashed var(--glass-edge);word-break:break-all;color:var(--txt)}
  table.kv.wide th{width:auto}
  .map-cta{position:relative;display:inline-block;margin:20px 0 6px;background:var(--acc);color:#fff!important;
    padding:11px 20px;border-radius:var(--r-sm);font-size:14px;font-weight:700;text-decoration:none;overflow:hidden;
    box-shadow:0 6px 18px rgba(47,109,232,.35), inset 0 1px 1px rgba(255,255,255,.45);
    transition:background .2s,transform .3s cubic-bezier(.34,1.45,.44,1),box-shadow .2s}
  .map-cta::before{content:'';position:absolute;inset:0;pointer-events:none;
    background:linear-gradient(165deg, rgba(255,255,255,.35), rgba(255,255,255,0) 50%)}
  .map-cta:hover{background:#245ce6;transform:translateY(-1px);text-decoration:none;box-shadow:0 8px 24px rgba(47,109,232,.45), inset 0 1px 1px rgba(255,255,255,.5)}
  .map-cta:active{transform:scale(.96)}
  .lang-links{font-size:13px;color:var(--dim);margin-top:10px}
  .lang-links a{color:var(--acc2);margin-right:10px}
  .lang-links a:hover{color:#7fe2ff}
  footer{border-top:1px solid var(--glass-edge);margin-top:32px;padding-top:14px;font-size:12.5px;color:var(--dim)}
  footer a{color:var(--dim)}
  footer a:hover{color:#fff}
  .count{color:var(--acc2);font-variant-numeric:tabular-nums}
  .adj-dir{font-size:13.5px;color:var(--dim);margin:0 0 8px}
  .toc{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px;padding-bottom:14px;border-bottom:1px solid var(--glass-edge)}
  .toc a{font-size:12px;font-weight:600;color:var(--acc-txt);background:var(--glass);border:1px solid var(--glass-edge);
    border-radius:var(--r-pill);padding:4px 12px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
    box-shadow:inset 0 1px 1px var(--glass-hi), inset 0 -1px 2px var(--glass-lo);
    transition:background .2s,border-color .2s,color .2s}
  .toc a:hover{background:var(--glass-2);border-color:var(--glass-hi);color:#fff;text-decoration:none}
  .near{list-style:none;margin:0}
  .near li{padding:7px 2px;border-bottom:1px dashed var(--glass-edge);font-size:14px}
  .near li:last-child{border-bottom:0}
  .km{color:var(--dim);font-size:12.5px;font-weight:600;font-variant-numeric:tabular-nums;margin-left:6px}
  .pcnt{color:var(--dim);font-size:12.5px;font-weight:600;font-variant-numeric:tabular-nums}
  .fstat{color:var(--dim);font-size:12px;margin-bottom:4px;letter-spacing:.2px}
  .wiki-x{color:var(--dim);font-size:14px;line-height:1.8;background:var(--glass);
    border:1px solid var(--glass-edge);border-radius:var(--r-sm);padding:12px 14px;
    box-shadow:inset 0 1px 1px var(--glass-hi), inset 0 -1px 2px var(--glass-lo);
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);margin-bottom:22px}
  .wiki-x .mini{margin-left:4px}
  .wiki-ch{display:block;margin-top:7px;color:var(--dim);font-size:13px;line-height:1.75;border-top:1px dashed rgba(255,255,255,.14);padding-top:7px}
  .wiki-ch b{color:var(--txt);font-weight:600;margin-right:2px}
  .mapfig{margin:10px 0 4px;background:var(--glass);border:1px solid var(--glass-edge);border-radius:var(--r-sm);padding:10px;overflow:hidden}
  .mapfig img{display:block;width:100%;height:auto;border-radius:6px;background:#fff}
  .mapfig figcaption{color:var(--dim);font-size:12px;margin-top:8px;line-height:1.6}
  .mapfig.diag svg{background:rgba(6,10,18,.55);border-radius:6px;display:block;width:100%;height:auto}
  .lgrow{display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:9px}
  .lg{display:inline-flex;align-items:center;gap:5px;color:var(--dim);font-size:12px;white-space:nowrap}
  .lg i{width:10px;height:10px;border-radius:3px;display:inline-block}
  .wiki-links{font-size:12.5px;color:var(--dim);margin-top:6px}
  .wiki-links a{color:var(--acc-txt);margin-right:2px}
  .mini{font-size:12px;color:var(--acc2);text-decoration:none;margin-left:7px;white-space:nowrap}
  .mini:hover{color:#7fe2ff;text-decoration:underline}
  .dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px;
    box-shadow:0 0 8px rgba(255,255,255,.28)}
  .tag{font-size:12px;color:var(--dim);border:1px solid var(--glass-edge);border-radius:var(--r-pill);padding:1px 9px;margin-left:6px;white-space:nowrap;background:var(--glass)}
  .trns li{background:var(--glass);border:1px solid var(--glass-edge);border-radius:var(--r-sm);padding:8px 12px;margin-bottom:7px;
    box-shadow:inset 0 1px 1px var(--glass-hi), inset 0 -1px 2px var(--glass-lo)}
  @media(max-width:600px){h1{font-size:24px}.wrap{padding:18px 16px 24px;border-radius:16px}}
"""


def page_head(cfg, title, desc, url, og_img_url):
    return (
        '<!DOCTYPE html>\n<html lang="zh-Hans">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>' + esc(title) + '</title>\n'
        '<meta name="description" content="' + esc(desc) + '">\n'
        '<link rel="canonical" href="' + esc(url) + '">\n'
        '<meta property="og:type" content="website">\n'
        '<meta property="og:site_name" content="' + esc(cfg['site_name']) + '">\n'
        '<meta property="og:title" content="' + esc(title) + '">\n'
        '<meta property="og:description" content="' + esc(desc) + '">\n'
        '<meta property="og:url" content="' + esc(url) + '">\n'
        '<meta property="og:image" content="' + esc(og_img_url) + '">\n'
        '<meta property="og:locale" content="zh_CN">\n'
        '<meta property="og:locale:alternate" content="ja_JP">\n'
        '<meta property="og:locale:alternate" content="en_US">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<meta name="twitter:title" content="' + esc(title) + '">\n'
        '<meta name="twitter:description" content="' + esc(desc) + '">\n'
        '<meta name="twitter:image" content="' + esc(og_img_url) + '">\n'
        '<meta name="theme-color" content="#0b0f16">\n'
        '<style>' + CSS + '</style>\n'
    )


def station_page(rec, lines, neighbors, cfg, tozh):
    key, name = rec['key'], rec['name']
    disp = key if key != name else name  # 消歧后的唯一站名（如 高田(奈良県)）
    pref_zh = tozh(rec['pref']) if rec['pref'] else ''
    zh = rec['zh']
    en = rec['en']
    slug = quote_path(key)
    url = abs_url(cfg, 'stations/' + slug + '/')
    og_img_url = abs_url(cfg, cfg['og_image'])

    # 标题：日文名优先，附中文/英文名与途经线路
    line_names = rec['lines']
    line_label = '、'.join(line_names[:3]) + (' 等' if len(line_names) > 3 else '') if line_names else ''
    if en:
        title = '%s（%s站 / %s）— 途经%s | %s' % (disp, zh, en, line_label, cfg['site_name'])
    else:
        title = '%s（%s站）— 途经%s | %s' % (disp, zh, line_label, cfg['site_name'])
    if len(title) > 78:
        title = title[:75] + '…'

    pref_en = ''
    desc_tail = ''
    if rec['pref']:
        desc_tail = '位于%s。' % (pref_zh or rec['pref'])
    line_desc = '、'.join(line_names[:3]) + (' 等' if len(line_names) > 3 else '') if line_names else '多条线路'
    desc = '%s（%s / %s）%s途经%s。在 Mini JapanRail 全日本铁路实时运行地图上查看车站位置、途经线路与实时列车。' % (
        zh, name, en or zh, desc_tail, line_desc)
    if len(desc) > 190:
        desc = desc[:187] + '…'

    # 车站链接辅助（带中文名）
    def _st_link(k):
        r2 = recs.get(k)
        if not r2:
            return esc(k)
        label = r2['name'] + ('・' + r2['zh'] if r2['zh'] and r2['zh'] != r2['name'] else '')
        return '<a href="' + esc(abs_url(cfg, 'stations/' + quote_path(k) + '/')) + '">' + esc(label) + '</a>'

    # 途经线路明细表（线路 / 类型 / 运营方 / 本站位置）
    lines_html = ''
    for ln in line_names:
        lr = lines.get(ln)
        col = lr['color'] if lr else FALLBACK_COLOR
        en_l = lr['en'] if lr else ''
        kind = tozh(lr['kind']) if lr and lr.get('kind') else ''
        op = lr['op'] if lr else ''
        label = ln + (' / ' + en_l if en_l else '')
        seq = line_orders.get(ln) or []
        pos = ''
        if key in seq:
            pos = '第 %d 站 / 共 %d 站' % (seq.index(key) + 1, len(seq))
        lines_html += '<tr><td><span class="dot" style="background:%s"></span><a href="%s"><b>%s</b></a></td><td>%s</td><td>%s</td><td>%s</td></tr>\n' % (
            esc(col), esc(abs_url(cfg, 'lines/' + quote_path(ln) + '/')), esc(label),
            esc(kind) if kind else '—', esc(op) if op else '—', esc(pos) if pos else '—')

    # 相邻车站（沿轨道方向：前站 ← 本站 → 后站）
    adj_html = ''
    first_adj = True
    for ln in line_names:
        lr = lines.get(ln)
        col = lr['color'] if lr else FALLBACK_COLOR
        seq = line_orders.get(ln) or []
        i = seq.index(key) if key in seq else -1
        fwd = seq[i - 1] if i > 0 else None
        back = seq[i + 1] if 0 <= i < len(seq) - 1 else None
        items = sorted(set(o for (l, o) in neighbors.get(key, []) if l == ln))
        if not items and fwd is None and back is None:
            continue
        dir_html = ''
        if fwd is not None or back is not None:
            parts = []
            if fwd is not None:
                parts.append('← 前站 ' + _st_link(fwd))
            if back is not None:
                parts.append('后站 ' + _st_link(back) + ' →')
            dir_html = '<p class="adj-dir">' + '　'.join(parts) + '</p>'
        rest = [o for o in items if o != fwd and o != back]
        h = '<h2' + (' id="sec-adj"' if first_adj else '') + ' style="--lc:' + esc(col) + '">' + esc(ln) + ' 沿线相邻车站</h2>\n' + dir_html
        first_adj = False
        if rest:
            h += '<p>' + ' · '.join(_st_link(o) for o in rest) + '</p>\n'
        adj_html += h

    # 同名车站（消歧链接）
    same_html = ''
    others = [k for k in name_groups.get(name, []) if k != key]
    if others:
        same_html = '<h2 id="sec-same" style="--lc:#5fd4f4">同名车站</h2>\n<p>' + ' · '.join(_st_link(k) for k in others) + '</p>\n'

    # 附近车站（同都道府县内地理最近 5 站）
    near_html = ''
    near_list = nearby.get(key, [])
    if near_list:
        parts = []
        for o, km in near_list:
            r2 = recs.get(o)
            label = r2['name'] + ('（' + r2['zh'] + '）' if r2 and r2['zh'] and r2['zh'] != r2['name'] else '')
            parts.append('<li><a href="%s">%s</a> <span class="km">约 %s 公里</span></li>' % (
                esc(abs_url(cfg, 'stations/' + quote_path(o) + '/')), esc(label), esc(str(km))))
        near_html = '<h2 id="sec-near" style="--lc:#5fd4f4">附近车站（同县最近 5 站）</h2>\n<ul class="near">\n' + '\n'.join(parts) + '\n</ul>\n'

    coord = rec['coord']
    # 同名站（name_groups 内多条）无法在 stationCoord 精确消歧，深链仅给唯一名站
    sta_extra = {'t': 'station', 'q': key} if len(name_groups.get(name, [])) == 1 else None
    map_zh = map_url(cfg, coord[0], coord[1], 14, 'zh', extra=sta_extra)
    map_ja = map_url(cfg, coord[0], coord[1], 14, 'ja', extra=sta_extra)
    map_en = map_url(cfg, coord[0], coord[1], 14, 'en', extra=sta_extra)

    # 站线配置示意（自绘 SVG，基于站内真实轨道数据）+ 站内构内図（ecomo 同源实图）
    map_img_html = ''
    diag = station_line_diagram(rec, stations, line_orders, lines)
    fp = floorplan.get(key) or floorplan.get(name)
    if diag or fp:
        block = '<h2 id="sec-map" style="--lc:#5fd4f4">站线配置图</h2>\n'
        if diag:
            block += diag
        if fp:
            img_src = abs_url(cfg, 'seo/img/stations/' + urllib.parse.quote(key) + '.png')
            block += ('<figure class="mapfig"><img src="' + esc(img_src) + '" '
                      'alt="' + esc(name + ' 站内构内図') + '" loading="lazy" decoding="async">'
                      '<figcaption>站内构内図（实拍站内平面）· 与主站「指南」tab 同源</figcaption></figure>\n')
        map_img_html = block

    # 百科简介（站内本地化词条 eki-wiki 同源，中文→日文首段；「在主站查看」跳站深链）
    eki_html = ''
    se = eki_station_for(key, name, wlm, eki_cache)
    if se:
        src = se.get('zh') or se.get('ja')
        if src:
            eki_html = eki_brief_html('sec-eki', '百科简介', src, 'zh-Hans' if se.get('zh') else 'ja', map_zh)

    # 顶部锚点目录
    toc_items = [
        ('#sec-lines', '途经线路'), ('#sec-basic', '基本信息'),
        ('#sec-adj', '相邻车站'), ('#sec-near', '附近车站'),
    ]
    if eki_html:
        toc_items.insert(0, ('#sec-eki', '百科'))
    if map_img_html:
        toc_items.insert(1, ('#sec-map', '配线图'))
    if same_html:
        toc_items.append(('#sec-same', '同名车站'))
    toc_html = '<nav class="toc" aria-label="本页目录">' + ''.join(
        '<a href="%s">%s</a>' % (h, t) for h, t in toc_items) + '</nav>\n'

    jsonld = [
        {
            '@context': 'https://schema.org',
            '@type': 'TrainStation',
            'name': disp,
            'alternateName': [zh] + ([en] if en else []) + ([rec['kana']] if rec['kana'] else []) + ([name] if name != disp else []),
            'url': url,
            'geo': {'@type': 'GeoCoordinates', 'longitude': coord[0], 'latitude': coord[1]},
            'keywords': ', '.join(line_names),
            'hasMap': map_zh,
        }
    ]
    if rec['pref']:
        jsonld[0]['address'] = {'@type': 'PostalAddress', 'addressRegion': rec['pref']}
    jsonld.append({
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': cfg['site_name'], 'item': abs_url(cfg, '')},
            {'@type': 'ListItem', 'position': 2, 'name': '车站一览', 'item': abs_url(cfg, 'stations/')},
            {'@type': 'ListItem', 'position': 3, 'name': disp, 'item': url},
        ],
    })

    body = (
        '<div class="wrap">\n'
        '<nav class="breadcrumb"><a href="' + esc(abs_url(cfg, '')) + '">' + esc(cfg['site_name']) + '</a> › '
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">车站</a> › <span>' + esc(disp) + '</span></nav>\n'
        '<p class="topnav"><a href="' + esc(abs_url(cfg, '')) + '">实时地图</a>'
        '<a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a>'
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p>\n'
        + toc_html
        + '<h1>' + esc(disp) + '<span class="alt">（<span lang="zh-Hans">' + esc(zh) + '站</span>'
        + (('<em> / </em><span lang="en">' + esc(en) + '</span>') if en else '') + '）</span></h1>\n'
        '<p class="lead">' + esc(desc) + '</p>\n'
        + eki_html
        + '<h2 id="sec-lines" style="--lc:#5fd4f4">途经线路</h2>\n'
        '<table class="kv wide">\n'
        '<tr><th>线路</th><th>类型</th><th>运营方</th><th>本站位置</th></tr>\n' + lines_html + '</table>\n'
        '<h2 id="sec-basic" style="--lc:#5fd4f4">基本信息</h2>\n'
        '<table class="kv">\n'
        '<tr><th>日文名</th><td lang="ja">' + esc(name) + '</td></tr>\n'
        '<tr><th>中文名</th><td lang="zh-Hans">' + esc(zh) + '</td></tr>\n'
        + (('<tr><th>英文名</th><td lang="en">' + esc(en) + '</td></tr>\n') if en else '')
        + (('<tr><th>假名</th><td lang="ja">' + esc(rec['kana']) + '</td></tr>\n') if rec['kana'] else '')
        + (('<tr><th>所在地</th><td><a href="%s#%s">%s</a>%s</td></tr>\n' % (
            esc(abs_url(cfg, 'stations/')), urllib.parse.quote(rec['pref'], safe=''), esc(rec['pref']),
            ('（' + esc(pref_zh) + '）' if pref_zh and pref_zh != rec['pref'] else ''))) if rec['pref'] else '')
        + '<tr><th>途经线路数</th><td>' + str(len(line_names)) + '</td></tr>\n'
        + '<tr><th>经度 / 纬度</th><td>' + str(coord[0]) + ' / ' + str(coord[1]) + '</td></tr>\n'
        + '</table>\n'
        + map_img_html
        + adj_html
        + near_html
        + same_html
        + '<a class="map-cta" href="' + esc(map_zh) + '">在地图上查看此车站（打开实时运行地图）</a>\n'
        + '<p class="lang-links">语言：<a href="' + esc(map_ja) + '" hreflang="ja">日本語</a>'
        + '<a href="' + esc(map_en) + '" hreflang="en">English</a></p>\n'
        + wiki_links_html(cfg, name, zh, en or name)
        + '<footer><p class="fstat">Mini JapanRail · 全日本 %d 条线路 · %d 个车站</p>\n' % (len(lines), len(recs))
        + '<p><a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a> · '
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a> · '
        '<a href="' + esc(abs_url(cfg, '')) + '">回到地图</a> · '
        '© Mini JapanRail</p></footer>\n'
        + '</div>\n'
    )
    return page_head(cfg, title, desc, url, og_img_url) + \
        '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + '</script>\n' \
        '</head>\n<body>\n' + body + '</body>\n</html>\n'


def line_page(rec, stations, cfg, tozh, ordered=None):
    lname = rec['name']
    zh = rec['zh']
    en = rec['en']
    slug = quote_path(lname)
    url = abs_url(cfg, 'lines/' + slug + '/')
    og_img_url = abs_url(cfg, cfg['og_image'])
    if en:
        title = '%s（%s / %s）— 线路车站一览 | %s' % (lname, zh, en, cfg['site_name'])
    else:
        title = '%s（%s）— 线路车站一览 | %s' % (lname, zh, cfg['site_name'])
    if len(title) > 78:
        title = title[:75] + '…'
    # 车站列表
    keys = ordered if ordered is not None else rec['station_keys']
    n = len(keys)
    kind_zh = tozh(rec['kind']) if rec['kind'] else '铁路'
    desc = '%s（%s%s）是%s，沿线途经车站共 %d 站' % (
        lname, zh, (' / ' + en) if en else '', ('%s线路' % kind_zh) if rec['kind'] else '一条铁路线路', n)
    if keys:
        e0, e1 = stations.get(keys[0]), stations.get(keys[-1])
        desc += '，从%s到%s' % (e0['name'] if e0 else keys[0], e1['name'] if e1 else keys[-1])
    if rec.get('approx_km'):
        desc += '，全长约 %d 公里' % rec['approx_km']
    if rec.get('prefs'):
        desc += '，途经 %d 个都道府县' % len(rec['prefs'])
    desc += '。可在 Mini JapanRail 全日本铁路实时运行地图上查看线路走向与实时列车。'
    if len(desc) > 190:
        desc = desc[:187] + '…'
    items_html = ''
    for i, k in enumerate(keys, 1):
        r2 = stations.get(k)
        label = k if not r2 else r2['name']
        extra = ''
        if r2 and r2['zh'] and r2['zh'] != r2['name']:
            extra = ' <em style="color:#8fa0c0;font-style:normal">（' + esc(r2['zh']) + '）</em>'
        mlink = ''
        if r2 and r2.get('coord'):
            dk = {'t': 'station', 'q': k} if len(name_groups.get(r2['name'], [])) == 1 else None
            murl = map_url(cfg, r2['coord'][0], r2['coord'][1], 14, 'zh', extra=dk)
            mlink = ' <a class="mini" href="' + esc(murl) + '">地图 ↗</a>'
        items_html += '<li><span class="count">%d.</span> <a href="%s">%s</a>%s%s</li>\n' % (
            i, esc(abs_url(cfg, 'stations/' + quote_path(k) + '/')), esc(label), extra, mlink)

    # 沿线换乘枢纽（本站途经商别线路）
    trns_html = ''
    trns = []
    for k in keys:
        r2 = stations.get(k)
        if not r2:
            continue
        ols = [l for l in r2['lines'] if l != lname]
        if ols:
            trns.append((k, r2, ols))
    if trns:
        shown = trns[:12]
        h = '<h2 id="sec-trns" style="--lc:' + esc(rec['color']) + '">沿线换乘枢纽</h2>\n<ul class="trns">\n'
        for k, r2, ols in shown:
            links = '、'.join('<a href="%s">%s</a>' % (esc(abs_url(cfg, 'lines/' + quote_path(l) + '/')), esc(l)) for l in ols[:4])
            if len(ols) > 4:
                links += ' 等'
            h += '<li><a href="%s">%s</a>%s — 可换乘：%s</li>\n' % (
                esc(abs_url(cfg, 'stations/' + quote_path(k) + '/')), esc(r2['name']),
                (' <em style="color:#8fa0c0;font-style:normal">（' + esc(r2['zh']) + '）</em>') if r2['zh'] and r2['zh'] != r2['name'] else '',
                links)
        more = len(trns) - len(shown)
        if more > 0:
            h += '<li style="color:#8fa0c0;font-size:13px">… 等 %d 个换乘站（完整列表见下方途经车站）</li>\n' % more
        h += '</ul>\n'
        trns_html = h

    # 同类线路推荐
    same_kind_html = ''
    same_kind = [r for n2, r in sorted(lines.items()) if n2 != lname and r['kind'] == rec['kind']]
    if same_kind:
        parts = []
        for r2 in same_kind[:6]:
            label2 = r2['name'] + ((' / ' + r2['en']) if r2['en'] else '')
            parts.append('<a href="%s">%s</a>' % (esc(abs_url(cfg, 'lines/' + quote_path(r2['name']) + '/')), esc(label2)))
        same_kind_html = '<h2 id="sec-samekind" style="--lc:' + esc(rec['color']) + '">同类线路推荐</h2>\n<p>' + ' · '.join(parts) + '</p>\n'

    # 信息表补充行（两端 / 长度 / 途经都道府县）
    ends_html = ''
    if keys:
        e0, e1 = stations.get(keys[0]), stations.get(keys[-1])
        ends_html = '<tr><th>沿线两端</th><td><a href="%s">%s</a> ↔ <a href="%s">%s</a></td></tr>\n' % (
            esc(abs_url(cfg, 'stations/' + quote_path(keys[0]) + '/')), esc(e0['name'] if e0 else keys[0]),
            esc(abs_url(cfg, 'stations/' + quote_path(keys[-1]) + '/')), esc(e1['name'] if e1 else keys[-1]))
    km_html = ''
    if rec.get('approx_km'):
        km_html = '<tr><th>线路长度</th><td>约 %d 公里（沿轨道估算）</td></tr>\n' % rec['approx_km']
    prefs_html = ''
    if rec.get('prefs'):
        if rec.get('pref_counts'):
            parts = []
            for p in rec['prefs']:
                n_p = rec['pref_counts'].get(p, 0)
                parts.append('<a href="%s#%s">%s</a> <span class="pcnt">%d 站</span>' % (
                    esc(abs_url(cfg, 'stations/')), urllib.parse.quote(p, safe=''), esc(p), n_p))
            prefs_html = '<tr><th>途经都道府县</th><td>' + '、'.join(parts) + '</td></tr>\n'
        else:
            prefs_html = '<tr><th>途经都道府县</th><td>' + '、'.join(
                '<a href="%s#%s">%s</a>' % (esc(abs_url(cfg, 'stations/')), urllib.parse.quote(p, safe=''), esc(p))
                for p in rec['prefs']) + '</td></tr>\n'
    # 同类型线路计数（信息表「类型」行用）
    kind_n = sum(1 for r2 in lines.values() if r2.get('kind') == rec['kind'])

    # 线路元信息（提前：百科卡「在主站查看」链接也用）
    c = rec['centroid']
    map_zh = map_url(cfg, c[0], c[1], 6, 'zh', extra={'t': 'line', 'q': lname})
    map_ja = map_url(cfg, c[0], c[1], 6, 'ja', extra={'t': 'line', 'q': lname})
    map_en = map_url(cfg, c[0], c[1], 6, 'en', extra={'t': 'line', 'q': lname})

    # 百科简介：优先站内本地化词条（eki-wiki 同源，中文→日文）；line_wiki.json 维基摘要作兜底
    wiki_html = ''
    ef = eki_line_for(lname, keys, eki_cache, wlm, tozh)
    if ef and eki_cache[ef]['line']:
        le = eki_cache[ef]['line']
        src = le.get('zh') or le.get('ja')
        if src:
            wiki_html = eki_brief_html('sec-wiki', '百科简介', src,
                                       'zh-Hans' if le.get('zh') else 'ja', map_zh)
    if not wiki_html:
        w = wiki.get(lname)
        if w and w.get('extract'):
            ex = w['extract']
            if len(ex) > 280:
                ex = ex[:277] + '…'
            wiki_html = ('<h2 id="sec-wiki" style="--lc:' + esc(rec['color']) + '">百科简介</h2>\n'
                         '<p class="wiki-x"><span lang="ja">' + esc(ex) + '</span> '
                         '<a class="mini" href="' + esc(map_zh) + '">在主站查看 ↗</a></p>\n')

    # 线路速览（站内数据驱动的百科式概述：不依赖外网，维基摘要缺失时保证页面信息丰富）
    summary_parts = ['%s是一条%s' % (lname, kind_zh)]
    if keys:
        e0, e1 = stations.get(keys[0]), stations.get(keys[-1])
        summary_parts.append('自%s至%s' % (e0['name'] if e0 else keys[0], e1['name'] if e1 else keys[-1]))
    if rec.get('approx_km'):
        summary_parts.append('全长约 %d 公里' % rec['approx_km'])
    summary_parts.append('共 %d 站' % n)
    if rec.get('prefs'):
        p5 = []
        for p in list(rec['prefs'])[:4]:
            p5.append(p + ('%d站' % rec['pref_counts'].get(p, 0) if rec.get('pref_counts') else ''))
        more_p = max(0, len(rec['prefs']) - 4)
        summary_parts.append('途经 %d 个都道府县（%s%s）' % (len(rec['prefs']), '、'.join(p5), ' 等' if more_p else ''))
    n_tr = len({l for _, _, ols in trns for l in ols})
    if n_tr:
        summary_parts.append('沿途可与 %d 条其他线路换乘' % n_tr)
    summary_html = '<p class="wiki-x">' + esc('，'.join(summary_parts) + '。') + '</p>\n'

    # 顶部锚点目录
    toc_items = [('#sec-info', '线路信息'), ('#sec-stations', '途经车站')]
    if wiki_html:
        toc_items.insert(0, ('#sec-wiki', '百科'))
    if trns:
        toc_items.insert(1, ('#sec-trns', '换乘枢纽'))
    if same_kind_html:
        toc_items.append(('#sec-samekind', '同类线路'))
    toc_html = '<nav class="toc" aria-label="本页目录">' + ''.join(
        '<a href="%s">%s</a>' % (h, t) for h, t in toc_items) + '</nav>\n'

    jsonld = [
        {
            '@context': 'https://schema.org',
            '@type': 'WebPage',
            'name': lname,
            'alternateName': [zh] + ([en] if en else []),
            'url': url,
            'description': desc,
            'keywords': '%s, %s车站, 日本铁路' % (lname, lname),
            'mainEntity': {
                '@type': 'ItemList',
                'name': lname + ' 车站',
                'numberOfItems': n,
                'itemListElement': [
                    {'@type': 'ListItem', 'position': i, 'name': k,
                     'url': abs_url(cfg, 'stations/' + quote_path(k) + '/')}
                    for i, k in enumerate(keys, 1)
                ],
            },
        },
        {
            '@context': 'https://schema.org',
            '@type': 'BreadcrumbList',
            'itemListElement': [
                {'@type': 'ListItem', 'position': 1, 'name': cfg['site_name'], 'item': abs_url(cfg, '')},
                {'@type': 'ListItem', 'position': 2, 'name': '线路一览', 'item': abs_url(cfg, 'lines/')},
                {'@type': 'ListItem', 'position': 3, 'name': lname, 'item': url},
            ],
        },
    ]

    body = (
        '<div class="wrap">\n'
        '<nav class="breadcrumb"><a href="' + esc(abs_url(cfg, '')) + '">' + esc(cfg['site_name']) + '</a> › '
        '<a href="' + esc(abs_url(cfg, 'lines/')) + '">线路</a> › <span>' + esc(lname) + '</span></nav>\n'
        '<p class="topnav"><a href="' + esc(abs_url(cfg, '')) + '">实时地图</a>'
        '<a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a>'
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p>\n'
        + toc_html
        + '<h1>' + esc(lname) + '<span class="alt">（<span lang="zh-Hans">' + esc(zh) + '</span>'
        + (('<em> / </em><span lang="en">' + esc(en) + '</span>') if en else '') + '）</span></h1>\n'
        '<p class="lead">' + esc(desc) + '</p>\n'
        + summary_html
        + wiki_html
        + '<h2 id="sec-info" style="--lc:' + esc(rec['color']) + '">线路信息</h2>\n'
        '<table class="kv">\n'
        '<tr><th>线路色</th><td><span style="display:inline-block;width:16px;height:16px;border-radius:4px;background:' + esc(rec['color']) + ';vertical-align:-2px"></span> ' + esc(rec['color']) + '</td></tr>\n'
        + (('<tr><th>类型</th><td>' + esc(rec['kind']) + ('（同类型线路共 %d 条）' % kind_n) + '</td></tr>\n') if rec['kind'] else '')
        + (('<tr><th>运营方</th><td>' + esc(rec['op']) + '</td></tr>\n') if rec['op'] else '')
        + '<tr><th>车站数</th><td>' + str(n) + '</td></tr>\n'
        + ends_html
        + km_html
        + prefs_html
        + '</table>\n'
        + trns_html
        + '<h2 id="sec-stations" style="--lc:' + esc(rec['color']) + '">途经车站（沿轨道顺序）</h2>\n<ol>\n' + items_html + '</ol>\n'
        + same_kind_html
        + '<a class="map-cta" href="' + esc(map_zh) + '">在地图上查看此线路（打开实时运行地图）</a>\n'
        + '<p class="lang-links">语言：<a href="' + esc(map_ja) + '" hreflang="ja">日本語</a>'
        '<a href="' + esc(map_en) + '" hreflang="en">English</a></p>\n'
        + wiki_links_html(cfg, lname, zh, en or lname)
        + '<footer><p class="fstat">Mini JapanRail · 全日本 %d 条线路 · %d 个车站</p>\n' % (len(lines), len(stations))
        + '<p><a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a> · '
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a> · '
        '<a href="' + esc(abs_url(cfg, '')) + '">回到地图</a> · '
        '© Mini JapanRail</p></footer>\n'
        + '</div>\n'
    )
    return page_head(cfg, title, desc, url, og_img_url) + \
        '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + '</script>\n' \
        '</head>\n<body>\n' + body + '</body>\n</html>\n'


def index_lines_page(lines, stations, cfg, tozh, line_counts=None):
    url = abs_url(cfg, 'lines/')
    og_img_url = abs_url(cfg, cfg['og_image'])
    title = '全部铁路线路一览 | %s' % cfg['site_name']
    desc = 'Mini JapanRail 收录的全日本铁路线路一览（%d 条）：JR、私铁、地下铁、单轨、路面电车等，每条线路均有独立页面与途经车站。' % len(lines)
    kinds_order = ['鉄道', '路面電車', 'モノレール', '案内軌条式', '鋼索鉄道', '無軌条電車', '浮上式']
    groups = defaultdict(list)
    for lname, rec in sorted(lines.items(), key=lambda kv: kv[0]):
        kind = rec['kind'] if rec['kind'] in kinds_order else 'その他'
        groups[kind].append(rec)
    html = ''
    for kind in kinds_order + ['その他']:
        g = groups.get(kind)
        if not g:
            continue
        html += '<h2 style="--lc:#5fd4f4">' + esc(kind) + '（%d）</h2>\n<ul class="grid">\n' % len(g)
        for rec in sorted(g, key=lambda r: (-(line_counts or {}).get(r['name'], 0), r['name'])):
            en_l = rec['en']
            label = rec['name'] + ((' / ' + en_l) if en_l else '')
            html += '<li><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:%s;margin-right:6px"></span><a href="%s">%s</a></li>\n' % (
                esc(rec['color']), esc(abs_url(cfg, 'lines/' + quote_path(rec['name']) + '/')), esc(label))
        html += '</ul>\n'
    jsonld = [{'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': title, 'url': url,
               'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(lines)}}]
    body = (
        '<div class="wrap">\n'
        '<nav class="breadcrumb"><a href="' + esc(abs_url(cfg, '')) + '">' + esc(cfg['site_name']) + '</a> › <span>线路一览</span></nav>\n'
        '<p class="topnav"><a href="' + esc(abs_url(cfg, '')) + '">实时地图</a>'
        '<a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a>'
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p>\n'
        '<h1>全部铁路线路 <span class="alt">（<span lang="zh-Hans">线路一览</span>）</span></h1>\n'
        '<p class="lead">' + esc(desc) + '</p>\n'
        '<p><a class="map-cta" href="' + esc(abs_url(cfg, '')) + '">打开实时运行地图</a></p>\n' + html +
        '<footer><p class="fstat">Mini JapanRail · 全日本 %d 条线路 · %d 个车站</p>\n' % (len(lines), len(stations)) +
        '<p><a href="' + esc(abs_url(cfg, '')) + '">回到地图</a> · <a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p></footer>\n</div>\n'
    )
    return page_head(cfg, title, desc, url, og_img_url) + \
        '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + '</script>\n' \
        '</head>\n<body>\n' + body + '</body>\n</html>\n'


def index_stations_page(stations, cfg, tozh, lines=None):
    url = abs_url(cfg, 'stations/')
    og_img_url = abs_url(cfg, cfg['og_image'])
    title = '全部车站一览 | %s' % cfg['site_name']
    desc = 'Mini JapanRail 收录的全日本车站一览（%d 站，按都道府县分组），每个车站均有独立页面，包含途经线路、位置与相邻车站。' % len(stations)
    groups = defaultdict(list)
    for key, rec in stations.items():
        groups[rec['pref'] or 'その他'].append(rec)
    html = '<p class="lead" style="font-size:13px">'
    for pref in sorted(groups):
        html += '<a href="#' + esc(urllib.parse.quote(pref, safe='')) + '">' + esc(pref) + '</a> · '
    html = html.rstrip(' · ') + '</p>\n'
    for pref in sorted(groups):
        g = sorted(groups[pref], key=lambda r: r['name'])
        html += '<h2 id="' + esc(urllib.parse.quote(pref, safe='')) + '" style="--lc:#5fd4f4">' + esc(pref) + '（%d）</h2>\n<ul class="grid">\n' % len(g)
        for rec in g:
            html += '<li><a href="%s">%s</a>%s</li>\n' % (
                esc(abs_url(cfg, 'stations/' + quote_path(rec['key']) + '/')),
                esc(rec['name']),
                (' <span style="color:#8fa0c0;font-size:12px">' + esc(rec['zh']) + '</span>') if rec['zh'] != rec['name'] else '')
        html += '</ul>\n'
    jsonld = [{'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': title, 'url': url,
               'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(stations)}}]
    body = (
        '<div class="wrap">\n'
        '<nav class="breadcrumb"><a href="' + esc(abs_url(cfg, '')) + '">' + esc(cfg['site_name']) + '</a> › <span>车站一览</span></nav>\n'
        '<p class="topnav"><a href="' + esc(abs_url(cfg, '')) + '">实时地图</a>'
        '<a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a>'
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p>\n'
        '<h1>全部车站 <span class="alt">（<span lang="zh-Hans">车站一览</span>）</span></h1>\n'
        '<p class="lead">' + esc(desc) + '</p>\n'
        '<p><a class="map-cta" href="' + esc(abs_url(cfg, '')) + '">打开实时运行地图</a></p>\n' + html +
        '<footer><p class="fstat">Mini JapanRail · 全日本 %d 条线路 · %d 个车站</p>\n' % (len(lines), len(stations)) +
        '<p><a href="' + esc(abs_url(cfg, '')) + '">回到地图</a> · <a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a></p></footer>\n</div>\n'
    )
    return page_head(cfg, title, desc, url, og_img_url) + \
        '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + '</script>\n' \
        '</head>\n<body>\n' + body + '</body>\n</html>\n'


# ---------------- sitemap / robots / 404 ----------------
def write_sitemaps(cfg, lines, stations):
    lastmod = cfg.get('lastmod_date') or ''
    pages = [
        (abs_url(cfg, ''), '1.0', 'daily'),
        (abs_url(cfg, 'lines/'), '0.9', 'weekly'),
        (abs_url(cfg, 'stations/'), '0.9', 'weekly'),
    ]
    def url_tag(url, prio, freq):
        lm = ('<lastmod>%s</lastmod>' % lastmod) if lastmod else ''
        return '<url><loc>%s</loc>%s<changefreq>%s</changefreq><priority>%s</priority></url>\n' % (
            xml_esc(url), lm, freq, prio)
    with open(os.path.join(ROOT, 'sitemap-pages.xml'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u, p, fr in pages:
            f.write(url_tag(u, p, fr))
        f.write('</urlset>\n')
    with open(os.path.join(ROOT, 'sitemap-lines.xml'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for lname in sorted(lines):
            f.write(url_tag(abs_url(cfg, 'lines/' + quote_path(lname) + '/'), '0.8', 'weekly'))
        f.write('</urlset>\n')
    with open(os.path.join(ROOT, 'sitemap-stations.xml'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for key in sorted(stations):
            f.write(url_tag(abs_url(cfg, 'stations/' + quote_path(key) + '/'), '0.6', 'monthly'))
        f.write('</urlset>\n')
    with open(os.path.join(ROOT, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for name in ('sitemap-pages.xml', 'sitemap-lines.xml', 'sitemap-stations.xml'):
            f.write('<sitemap><loc>%s</loc></sitemap>\n' % xml_esc(abs_url(cfg, name)))
        f.write('</sitemapindex>\n')


def write_robots(cfg):
    with open(os.path.join(ROOT, 'robots.txt'), 'w', encoding='utf-8') as f:
        f.write(
            'User-agent: *\n'
            'Allow: /\n'
            'Disallow: /data/\n'
            'Disallow: /seo/\n'
            '\n'
            '# 纯静态站点：所有线路 / 车站页面均为真实 HTML，可直接收录。\n'
            'Sitemap: %s\n' % abs_url(cfg, 'sitemap.xml'))


def write_404(cfg):
    og_img_url = abs_url(cfg, cfg['og_image'])
    title = '页面不存在（404）| %s' % cfg['site_name']
    desc = '您访问的页面不存在。返回 Mini JapanRail 全日本铁路实时运行地图，或浏览全部线路 / 全部车站。'
    body = (
        '<div class="wrap" style="text-align:center;padding-top:80px">\n'
        '<h1>404 — 页面不存在</h1>\n'
        '<p class="lead">' + esc(desc) + '</p>\n'
        '<p><a class="map-cta" href="' + esc(abs_url(cfg, '')) + '">回到实时运行地图</a></p>\n'
        '<p style="margin-top:16px"><a href="' + esc(abs_url(cfg, 'lines/')) + '">全部线路</a> · '
        '<a href="' + esc(abs_url(cfg, 'stations/')) + '">全部车站</a></p>\n'
        '</div>\n'
    )
    with open(os.path.join(ROOT, '404.html'), 'w', encoding='utf-8') as f:
        f.write(page_head(cfg, title, desc, abs_url(cfg, '404.html'), og_img_url)
                + '<meta name="robots" content="noindex,nofollow">\n</head>\n<body>\n' + body + '</body>\n</html>\n')


# ---------------- OG 分享图 ----------------
def gen_og_image(cfg, station_count, line_count):
    out = os.path.join(ROOT, cfg['og_image'])
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        print('[warn] PIL 不可用（%s），跳过 og-image 生成。' % e)
        return False
    W, H = 1200, 630
    img = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(img)
    # 背景渐变
    top, bottom = (11, 15, 22), (24, 32, 46)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    # 卡片
    card = (60, 60, W - 60, H - 60)
    d.rounded_rectangle(card, radius=28, fill=(18, 26, 40, 255), outline=(255, 255, 255, 40), width=1)
    # 列车图形
    bx, by, bw, bh = 108, 138, 260, 150
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=26, fill=(47, 109, 232))
    d.rounded_rectangle((bx + 22, by + 16, bx + bw - 22, by + 52), radius=14, fill=(255, 255, 255))
    for i, (wx, wy) in enumerate([(bx + 36, by + 74), (bx + 116, by + 74), (bx + 196, by + 74)]):
        d.rounded_rectangle((wx, wy, wx + 56, wy + 46), radius=8, fill=(157, 196, 255))
    for i, (wx, wy) in enumerate([(bx + 26, by + 128), (bx + bw - 26 - 46, by + 128)]):
        d.ellipse((wx, wy, wx + 46, wy + 46), fill=(9, 12, 18), outline=(255, 255, 255), width=6)
    # 文字
    def font(path, size, index=0):
        try:
            return ImageFont.truetype(path, size, index=index)
        except Exception:
            return None
    candidates = [
        ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 0),
        ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 0),
        ('/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf', 0),
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 0),
    ]
    f_title = f_sub = None
    for path, idx in candidates:
        f_title = font(path, 66, idx)
        if f_title:
            break
    for path, idx in candidates:
        f_sub = font(path, 34, idx)
        if f_sub:
            break
    if not f_title or not f_sub:
        print('[warn] 无可用字体，og-image 仅画图形不写字。')
    tx = 430
    if f_title:
        d.text((tx, 150), 'Mini JapanRail', font=f_title, fill=(255, 255, 255))
    if f_sub:
        d.text((tx, 250), '全日本铁路实时运行地图', font=f_sub, fill=(190, 205, 230))
        d.text((tx, 310), '%d 线路 · %d 车站' % (line_count, station_count), font=f_sub, fill=(95, 212, 244))
        d.text((tx, 380), 'Japan Rail Live Map', font=f_sub, fill=(140, 160, 190))
    img.save(out, 'PNG', optimize=True)
    print('[og-image] 已生成 %s（%dx%d）' % (out, W, H))
    return True


# ---------------- 主流程 ----------------
def main():
    global ROOT, DATA_DIR
    ap = argparse.ArgumentParser(description='Mini JapanRail SEO 静态化生成器')
    ap.add_argument('--root', default=ROOT, help='输出根目录（默认为仓库根目录）')
    ap.add_argument('--config', default=CONFIG_PATH, help='配置文件路径')
    args = ap.parse_args()

    ROOT = os.path.abspath(args.root)
    DATA_DIR = os.path.join(ROOT, 'data')

    cfg = load_config(args.config)
    d = build_records(cfg)
    global recs, line_orders, line_counts, name_groups, lines, nearby, wiki, eki_cache, wlm, stations, floorplan
    stations, lines, neighbors, tozh = d['stations'], d['lines'], d['neighbors'], d['tozh']
    recs = stations  # station_page 里引用相邻车站记录
    line_orders = d['line_orders']  # 线路车站沿轨道顺序（站页方向/位置用）
    name_groups = d['name_groups']  # 同名站消歧链接
    nearby = d['nearby']            # 附近车站（同县地理最近 5 站）
    wiki = d['line_wiki']           # Wikipedia 线路摘要缓存
    eki_cache = d['eki_cache']      # 本地化百科词条缓存（eki-wiki 同源）
    wlm = d['wlm']                  # 站key → 词条线路文件
    floorplan = d['floorplan']      # 站 key → 构内図（配线图）索引
    line_counts = {lname: len(seq) for lname, seq in line_orders.items()}

    out_lines = os.path.join(ROOT, 'lines')
    out_stations = os.path.join(ROOT, 'stations')
    os.makedirs(out_lines, exist_ok=True)
    os.makedirs(out_stations, exist_ok=True)

    # 1) 线路页
    for lname, rec in lines.items():
        d_ = os.path.join(out_lines, lname)
        os.makedirs(d_, exist_ok=True)
        with open(os.path.join(d_, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(line_page(rec, stations, cfg, tozh, ordered=line_orders[lname]))
    # 2) 车站页
    for key, rec in stations.items():
        d_ = os.path.join(out_stations, key)
        os.makedirs(d_, exist_ok=True)
        with open(os.path.join(d_, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(station_page(rec, lines, neighbors, cfg, tozh))
    # 3) 一览页
    with open(os.path.join(out_lines, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_lines_page(lines, stations, cfg, tozh, line_counts=line_counts))
    with open(os.path.join(out_stations, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_stations_page(stations, cfg, tozh, lines=lines))
    # 4) sitemap / robots / 404 / og
    write_sitemaps(cfg, lines, stations)
    write_robots(cfg)
    write_404(cfg)
    gen_og_image(cfg, len(stations), len(lines))

    total = 0
    for base in (out_lines, out_stations):
        for _, _, files in os.walk(base):
            total += len(files)
    size = 0
    for base in (out_lines, out_stations):
        for dp, _, fns in os.walk(base):
            for fn in fns:
                size += os.path.getsize(os.path.join(dp, fn))
    print('[done] 线路页 %d · 车站页 %d · 一览页 2 · 合计 %d 个文件，约 %.1f MB'
          % (len(lines), len(stations), total, size / 1024 / 1024))
    print('[done] 输出目录：%s （sitemap/robots/404 位于 %s）' % (out_lines, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())

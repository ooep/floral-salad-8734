#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Wikimedia Commons 抓取日本车站「配線図（站线配置图）」SVG 并解析入库。

用途：为 SEO 站页提供真实的股道级配线图（如维基共享的「奥津軽いまべつ駅配線図.svg」）。
设计给 GitHub Actions（seo-trackdiagrams.yml）或可达 Commons 的网络环境运行：
    python3 seo/fetch_wiki_trackdiagrams.py [--fallback]

策略（避免逐站搜索产生上万次 API 请求）：
  1. 枚举 Commons 配线图分类（日本の鉄道駅の配線図 等）的全部 SVG 文件标题
     （categorymembers 翻页，每分类 1~3 次请求即可拿全量清单）；
  2. 解析文件标题提取站名 token（去「駅」「配線図」「track diagram」等后缀、ヶ/ケ 变体归一）；
  3. 与本站站名/假名/日文词条名做本地匹配，命中即下载；
  4. --fallback：对未命中但已有本地化词条的站，用 intitle 搜索 API 兜底（仅少量请求）。

合规：仅使用 Wikimedia Commons 官方 API（api.php / upload.wikimedia.org 文件直链），
      不抓取页面 HTML，不绕过 robots.txt。图片版权（多为 CC BY-SA）随索引保存，
      页面引用时按来源署名。

产出：
  data/wiki_trackdiagrams/<key>.svg         原始 SVG
  data/wiki_trackdiagrams/<key>.svg.clean   清洗后可内联版本（XML 解析 + 去注释/压缩）
  data/wiki_trackdiagrams.json              索引 {key: {found,title,artist,license,source,bytes}}
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'wiki_trackdiagrams')
API = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'MiniJapanRail-SEO/1.0 (https://jr.suki.ing; contact: admin@jr.suki.ing)'}
CATS = (
    'Category:日本の鉄道駅の配線図',
    'Category:Track diagrams of railway stations in Japan',
    'Category:駅の配線図',
    'Category:Railway track diagrams in Japan',
)
SUF_JA = ('駅構内配線図', '駅配線略図', '駅の配線図', '駅配線図', '駅配線圖', '線路配線圖', '線路配線図',
          'プラットホーム配線図', '構内配線図', '配線図', '配線圖', '駅')
SUF_EN = (' station track diagram', ' station diagram', ' railway diagram',
          ' track diagram', ' trackmap', ' stationmap', ' platform layout',
          ' yard layout', ' track layout', ' station')
FALLBACK_GENRES = ('配線図', '配線圖', 'track diagram', 'Track diagram')


def api_get(params):
    params = dict(params, format='json')
    url = API + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def norm_station(s):
    return re.sub(r'[ヶケヵカ]', 'カ', s or '').strip()


def station_token(title):
    """File:東京駅配線図.svg → 東京；File:Osaka station track diagram.svg → Osaka"""
    t = title[5:] if title.startswith('File:') else title
    t = re.sub(r'\.svg$', '', t, flags=re.I).strip()
    changed = True
    while changed:
        changed = False
        for s in SUF_JA:
            if t.endswith(s):
                t = t[:-len(s)].strip()
                changed = True
                break  # 每轮只剥一个（low 语义不跨后缀复用）
        if changed:
            continue
        low = t.lower()
        for s in SUF_EN:
            if low.endswith(s):
                t = t[:-len(s)].strip()
                changed = True
                break
    t = re.split(r'[（(]', t)[0].strip()
    # 括号剥离后再剥一次单字后缀（高田駅（JR西日本）配線図 → 高田）
    for s in ('駅', ' station'):
        if t.endswith(s):
            t = t[:-len(s)].strip()
            break
    return t


def enum_category_files():
    """枚举分类下全部 SVG 文件标题（自动翻页）。"""
    files = []
    for cat in CATS:
        cont = {}
        guard = 0
        while guard < 40:
            guard += 1
            params = {'action': 'query', 'list': 'categorymembers',
                      'cmtitle': cat, 'cmtype': 'file', 'cmlimit': '500'}
            params.update(cont)
            try:
                d = api_get(params)
            except Exception:
                break
            for m in d.get('query', {}).get('categorymembers', []):
                t = m.get('title', '')
                if t.lower().endswith('.svg') and t not in files:
                    files.append(t)
            if 'continue' in d:
                cont = d['continue']
            else:
                break
        print('  分类 %s -> 累计文件 %d' % (cat, len(files)), flush=True)
    return files


def find_by_search(names):
    """intitle 搜索兜底（仅少量调用）。"""
    for nm in names:
        for g in FALLBACK_GENRES:
            q = 'intitle:%s %s filetype:svg' % (urllib.parse.quote(nm), g)
            try:
                d = api_get({'action': 'query', 'list': 'search', 'srsearch': q,
                             'srnamespace': '6', 'srlimit': '5'})
            except Exception:
                continue
            for hit in d.get('query', {}).get('search', []):
                t = hit.get('title', '')
                if t.startswith('File:') and t.lower().endswith('.svg'):
                    return t
    return None


def fetch_svg(title):
    d = api_get({'action': 'query', 'titles': title, 'prop': 'imageinfo',
                 'iiprop': 'url|size|extmetadata'})
    for _, pg in (d.get('query', {}).get('pages') or {}).items():
        ii = (pg.get('imageinfo') or [None])[0]
        if not ii:
            return None, None, None
        meta = ii.get('extmetadata') or {}
        artist = re.sub(r'<[^>]+>', '', (meta.get('Artist', {}) or {}).get('value', '') or '')
        artist = re.sub(r'\s+', ' ', artist).strip()[:120]
        license = (meta.get('LicenseShortName', {}) or {}).get('value', '') or ''
        req = urllib.request.Request(ii['url'], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(), artist, license
    return None, None, None


def clean_svg(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return raw
    body = ET.tostring(root, encoding='unicode')
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    body = re.sub(r'>\s+<', '><', body)
    return body


def main():
    os.makedirs(OUT, exist_ok=True)
    fallback = '--fallback' in sys.argv
    sm = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
    cache_path = os.path.join(DATA, 'eki_wiki_cache.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    idx_path = os.path.join(DATA, 'wiki_trackdiagrams.json')
    idx = json.load(open(idx_path, encoding='utf-8')) if os.path.exists(idx_path) else {}

    stations = sm['stations']
    print('车站总数:', len(stations), flush=True)

    # 站名 → key 索引（含变体归一）
    by_norm = {}
    for key, v in stations.items():
        name = v.get('name') or key
        for cand in (name, v.get('kana') or ''):
            c = norm_station(cand)
            if c and c not in by_norm:
                by_norm[c] = key
    print('站名索引:', len(by_norm), flush=True)

    # 1) 枚举分类文件
    print('枚举 Commons 配线图分类…', flush=True)
    files = enum_category_files()
    print('分类文件总数:', len(files), flush=True)

    # 2) 本地匹配
    matched = {}  # key -> title
    for t in files:
        tok = norm_station(station_token(t))
        if not tok:
            continue
        if tok in by_norm:
            key = by_norm[tok]
            matched.setdefault(key, t)
    print('分类直接命中:', len(matched), flush=True)

    # 3) 兜底搜索（仅 --fallback，对有词条站）
    if fallback:
        keys_with_wiki = set()
        for ent in cache.values():
            keys_with_wiki.update(ent.get('stations', {}).keys())
        todo = [k for k in keys_with_wiki if k not in matched and k not in idx]
        print('兜底搜索站数:', len(todo), flush=True)
        for n, key in enumerate(todo):
            v = stations.get(key, {})
            names = [v.get('name') or key]
            ja = None
            for ent in cache.values():
                for k2, st_ in ent.get('stations', {}).items():
                    if k2 == key:
                        src = st_.get('ja') or {}
                        if src.get('title'):
                            ja = src['title']
                        break
                if ja:
                    break
            if ja and ja not in names:
                names.append(ja)
            t = find_by_search(names)
            if t:
                matched[key] = t
            print('  [%d/%d] %s %s' % (n + 1, len(todo), key, matched.get(key, '无')), flush=True)
            time.sleep(0.4)

    # 4) 下载
    todo = [(k, t) for k, t in matched.items() if k not in idx]
    print('待下载:', len(todo), flush=True)
    for n, (key, t) in enumerate(todo):
        try:
            raw, artist, license = fetch_svg(t)
        except Exception as e:
            print('  下载失败 %s: %s' % (key, str(e)[:80]), flush=True)
            continue
        if not raw:
            continue
        fn = os.path.join(OUT, key + '.svg')
        open(fn, 'wb').write(raw)
        open(fn + '.clean', 'w', encoding='utf-8').write(clean_svg(raw))
        idx[key] = {
            'found': True, 'title': t,
            'artist': artist, 'license': license,
            'source': 'https://commons.wikimedia.org/wiki/' + urllib.parse.quote(t.replace(' ', '_')),
            'bytes': len(raw),
        }
        # 同步写入词条缓存（站条目 trackdiagram 字段，供 eki-wiki 词条页/生成器展示）
        for ent in cache.values():
            st_ = ent.get('stations', {}).get(key)
            if st_ is not None:
                st_['trackdiagram'] = {
                    'title': t, 'artist': artist, 'license': license,
                    'source': idx[key]['source'],
                }
                break
        print('  [%d/%d] %s <- %s' % (n + 1, len(todo), key, t), flush=True)
        time.sleep(0.35)
    json.dump(idx, open(idx_path, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    if any(st_ for ent in cache.values() for st_ in ent.get('stations', {}).values() if st_.get('trackdiagram')):
        json.dump(cache, open(cache_path, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        print('词条缓存已写入配线图元数据', flush=True)
    found = sum(1 for v in idx.values() if v.get('found'))
    print('完成. 配线图命中: %d / %d 站' % (found, len(stations)), flush=True)


if __name__ == '__main__':
    main()

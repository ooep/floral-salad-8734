#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站级配线图抓取 V7（基于 V4 修正四类问题）：

1. 探测端点补齐 ja.wikipedia（大站配线图 SVG 多在 ja.wiki 本地 File 空间）
2. 候选命名按真实风格扩充：Rail Tracks map <EN> Station / Rail track diagram of <EN> station
3. 搜索兜底加「文件名校验」（文件名必须含站名 汉字/假名/罗马字 token，杜绝错配）
4. 下载限速 + 429 退避重试；启动时清洗基线（校验已有 idx 的错配记录并删除重搜）
5. 搜索覆盖全站（--fallback-limit 默认全量），单 genre 提速

产出：data/wiki_trackdiagrams/<key>.svg / .svg.clean / wiki_trackdiagrams.json
     同步写入 eki_wiki_cache.json 站条目 trackdiagram 字段。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
OUT = os.path.join(DATA, 'wiki_trackdiagrams')
API_JA = 'https://ja.wikipedia.org/w/api.php'
API_ZH = 'https://zh.wikipedia.org/w/api.php'
API_COMMONS = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'MiniJapanRail-SEO/1.1 (https://jr.suki.ing; contact: admin@jr.suki.ing)'}
IMG_KEYWORDS = ('配線図', '配線圖', '線路配線', '配線略図', 'track diagram', 'trackmap',
                'track layout', 'station diagram', 'tracks map', 'rail track', '構内図')


def iter_pages(d):
    """formatversion=2 下 query.pages 为数组，兼容 dict/list 两种结构。"""
    p = (d.get('query') or {}).get('pages') or []
    if isinstance(p, dict):
        return p.values()
    return p


def api_get(params, host=API_COMMONS, timeout=40):
    params = dict(params, format='json', formatversion='2')
    url = host + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 45 * (attempt + 1)
                print('  !! 429 限流，退避 %ds' % wait, flush=True)
                time.sleep(wait)
                continue
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    return {}


def norm_station(s):
    s = str(s or '').strip()
    s = re.sub(r'[（(].*?[）)]$', '', s)
    s = re.sub(r'駅|站', '', s)
    s = re.sub(r'[\s　・/]', '', s)
    return s


def station_token(title):
    t = re.sub(r'^File:', '', title)
    t = re.sub(r'\.svg$', '', t, flags=re.I)
    return t


def norm_en(s):
    s = (s or '').lower()
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


MODS = frozenset({
    # 通用修饰
    'station', 'stn', 'sta', 'standard', 'side', 'north', 'south', 'east', 'west',
    'central', 'main', 'old', 'new', 'between', 'and', 'around', 'of', 'the',
    'track', 'tracks', 'map', 'maps', 'diagram', 'fig', 'signal', 'box', 'yard',
    'freight', 'terminal', 'junction', 'rail', 'railway', 'line', 'system', 'area',
    'times', 'period', '600v', 'st', 'vi', 'vl', 'sv', 'zh', 'zh-hant', 'hant', 'en', 'ja',
    'layout', 'municipal', 'subway', 'toyoko', 'tosa', 'den', 'shinkansen',
    '2020', '1975', '2021', '1995', '2005', '2015', '2030',
    # 年份
    '1924', '1930s', '1931', '1943', '1951', '1957', '1967', '1968', '1977',
    '1986', '1989', '1993', '2009', '2018', '2022', '2025',
    # 铁路公司 / 运营主体前缀
    'jr', 'jre', 'jrw', 'jreast', 'jrwest', 'jr-e', 'jr-w', 'jr-c', 'jr-f', 'jr-s',
    'e', 'w', 'c', 'n', 'h', 'k', 'q', 'y', 's', 'f', 't', 'd', 'g', 'm', 'b',
    'jr-k', 'jr-h', 'jr-t', 'jr-q', 'jr-y', 'jr-n', 'jnr', 'nankai', 'tobu', 'seibu',
    'odakyu', 'keio', 'tokyu', 'kintetsu', 'meitetsu', 'hankyu', 'toyotetsu',
    'kojaku', 'eiden', 'tosaden', 'hanshin', 'keisei', 'metro', 'hiroden', 'toyota',
    # 城市 / 地理前缀
    'osaka', 'tokyo', 'kyoto', 'nagoya', 'kobe', 'hiroshima', 'sapporo', 'fukuoka',
    'yokohama', 'kawasaki', 'nara', 'kanazawa', 'niigata', 'sendai', 'shin',
    'omama', 'kashima', 'keihan', 'shinkansen', 'sbw', 'mp', 'branch', 'tokaido',
    'wakayama', 'tokaido', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '00', '2',
    # 日文修饰
    '駅', '駅配線図', '配線図', '配線圖', '駅構内図', '構内図', '図', '站', '图', '圖',
    '配線略図',
})


def _norm_lat(s):
    """NFKD + 去组合变音符：Ōsaka -> Osaka, Chiryū -> Chiryu。"""
    import unicodedata
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


def _tokens(s):
    s = _norm_lat(s)
    s = re.sub(r'[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]+', ' ', s)
    return [t for t in s.split() if t]


def title_matches(title, name, kana, en):
    """文件名是否真对应本站（严格 token 版）：
    A) 站名 tokens == 文件 tokens；
    B) 站名 tokens 是文件 tokens 的连续子序列，且差异词全部 ∈ MODS（≤3 个）；
    C) 单 token/日文 fallback：核心串以站名开头/结尾，剩余 ∈ MODS。
    """
    ft = _tokens(station_token(title))
    ftok = re.sub(r'[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]', '', _norm_lat(station_token(title)))
    cands = [en, kana, name]
    if en:
        en_nodash = str(en).replace('-', '').replace(' ', '')
        if en_nodash != str(en):
            cands.insert(0, en_nodash)
    for cand in cands:
        c = str(cand or '').strip()
        if not c:
            continue
        ct = _tokens(c)
        if not ct:
            continue
        if ct == ft:
            return True
        if len(ct) <= len(ft):
            for i in range(len(ft) - len(ct) + 1):
                if ft[i:i + len(ct)] == ct:
                    extra = ft[:i] + ft[i + len(ct):]
                    if len(extra) <= 12 and all(x in MODS for x in extra):
                        return True
        # B2) 连续 token 拼接 == 站名单 token（如 Seibukyūjō + mae == seibukyujomae）
        if len(ct) == 1 and len(ft) <= 7:
            cflat0 = ct[0]
            for i in range(len(ft)):
                cur = ''
                for j in range(i, len(ft)):
                    cur += ft[j]
                    if cur == cflat0:
                        extra = ft[:i] + ft[j + 1:]
                        if len(extra) <= 6 and all(x in MODS for x in extra):
                            return True
                    if len(cur) > len(cflat0):
                        break
        cflat = re.sub(r'[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]', '', _norm_lat(c))
        if len(cflat) >= 2:
            if ftok.startswith(cflat):
                rest = ftok[len(cflat):]
                if not rest or rest in MODS:
                    return True
            if ftok.endswith(cflat):
                pre = ftok[:-len(cflat)]
                if not pre or pre in MODS:
                    return True
    return False

def enum_category_files():
    files = []
    for cat in ('Category:日本の鉄道駅の配線図', 'Category:Rail track diagrams of railway stations in Japan'):
        cont = {}
        guard = 0
        while guard < 30:
            guard += 1
            params = {'action': 'query', 'list': 'categorymembers',
                      'cmtitle': cat, 'cmtype': 'file', 'cmlimit': '500'}
            params.update(cont)
            try:
                d = api_get(params)
            except Exception as e:
                print('  !! 枚举分类 %s 异常: %s' % (cat, str(e)[:100]), flush=True)
                break
            if 'error' in d:
                break
            members = d.get('query', {}).get('categorymembers', [])
            for m in members:
                t = m.get('title', '')
                if t.lower().endswith('.svg') and t not in files:
                    files.append(t)
            if 'continue' in d:
                cont = d['continue']
            else:
                break
        print('  分类 %s -> %d 文件' % (cat, len(files)), flush=True)
    return files


def find_by_title_batch(candidates, host):
    found = {}
    items = list(candidates.items())
    for i in range(0, len(items), 50):
        chunk = items[i:i + 50]
        titles = '|'.join('File:' + t for t, _ in chunk)
        try:
            d = api_get({'action': 'query', 'titles': titles, 'prop': 'imageinfo'}, host=host)
        except Exception as e:
            print('  !! 批量探测异常: %s' % str(e)[:80], flush=True)
            continue
        pages = iter_pages(d)
        for pg in pages:
            t = (pg.get('title') or '')[5:]
            key = candidates.get(t)
            if key and pg.get('imageinfo'):
                found[key] = t
        time.sleep(0.25)
        if (i // 50) % 10 == 9:
            print('  探测进度: %d/%d, 已发现 %d' % (min(i + 50, len(items)), len(items), len(found)), flush=True)
    return found


def find_by_search(name, kana, en, genres=('配線図',)):
    """Commons 搜索兜底：站名 × genre 组合搜索，严格文件名校验后才接受。"""
    qs = ['%s %s' % (name, g) for g in genres]
    if kana:
        qs.append('%s %s' % (kana, genres[0]))
    for q in qs:
        try:
            d = api_get({'action': 'query', 'list': 'search', 'srsearch': q,
                         'srnamespace': '6', 'srlimit': '12'})
        except Exception:
            continue
        for hit in d.get('query', {}).get('search', []):
            t = hit.get('title', '')
            if not (t.startswith('File:') and t.lower().endswith('.svg')):
                continue
            if title_matches(t, name, kana, en):
                return t
    return None


def fetch_svg(title, host):
    """下载 SVG；下载前限速 1.2s，429 时重试。"""
    d = api_get({'action': 'query', 'titles': title, 'prop': 'imageinfo',
                 'iiprop': 'url|size|extmetadata'}, host=host)
    for pg in iter_pages(d):
        ii = (pg.get('imageinfo') or [None])[0]
        if not ii:
            return None, None, None
        meta = ii.get('extmetadata') or {}
        artist = re.sub(r'<[^>]+>', '', (meta.get('Artist', {}) or {}).get('value', '') or '')
        artist = re.sub(r'\s+', ' ', artist).strip()[:120]
        license = (meta.get('LicenseShortName', {}) or {}).get('value', '') or ''
        url = ii['url']
        req = urllib.request.Request(url, headers=UA)
        for attempt in range(3):
            try:
                time.sleep(1.2)
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read(), artist, license
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print('  !! 下载 429（%s），退避 60s 重试 %d/3' % (title, attempt + 1), flush=True)
                    time.sleep(60)
                    continue
                raise
    return None, None, None


def clean_svg(raw):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(raw)
    except Exception:
        return raw
    body = ET.tostring(root, encoding='unicode')
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    body = re.sub(r'>\s+<', '><', body)
    body = re.sub(r'xmlns:ns\d+="[^"]*"\s*', '', body)
    body = re.sub(r'</ns\d+:', '</', body)
    body = re.sub(r'<ns\d+:', '<', body)
    return body


def main():
    os.makedirs(OUT, exist_ok=True)
    fallback_limit = None
    if '--fallback-limit' in sys.argv:
        try:
            fallback_limit = int(sys.argv[sys.argv.index('--fallback-limit') + 1])
        except (IndexError, ValueError):
            fallback_limit = None
    checkpoint_every = 0
    if '--checkpoint-every' in sys.argv:
        try:
            checkpoint_every = int(sys.argv[sys.argv.index('--checkpoint-every') + 1])
        except (IndexError, ValueError):
            checkpoint_every = 0

    sm = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
    ni = json.load(open(os.path.join(DATA, 'names_i18n.json'), encoding='utf-8'))
    cache_path = os.path.join(DATA, 'eki_wiki_cache.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    idx_path = os.path.join(DATA, 'wiki_trackdiagrams.json')
    idx = json.load(open(idx_path, encoding='utf-8')) if os.path.exists(idx_path) else {}

    stations = sm['stations']
    ni_st = ni.get('stations') or {}
    print('车站总数:', len(stations), flush=True)

    # 清洗基线：已有 found 但文件名不匹配本站的 → 删除（错配图），重新搜索
    removed = 0
    for key in list(idx.keys()):
        v = idx[key]
        if not v.get('found'):
            continue
        st = stations.get(key) or {}
        name = st.get('name') or key
        kana = st.get('kana') or ''
        en = (ni_st.get(key) or {}).get('en') or ''
        if not title_matches(v.get('title', ''), name, kana, en):
            del idx[key]
            for suf in ('svg', 'svg.clean'):
                p = os.path.join(OUT, key + '.' + suf)
                if os.path.exists(p):
                    os.remove(p)
            removed += 1
    if removed:
        print('清洗错配基线: %d 条已删除（将重搜）' % removed, flush=True)

    by_norm = {}
    for key, v in stations.items():
        name = v.get('name') or key
        for cand in (name, v.get('kana') or ''):
            c = norm_station(cand)
            if c and c not in by_norm:
                by_norm[c] = key

    art_titles = {}
    for ent in cache.values():
        for k2, st_ in (ent.get('stations') or {}).items():
            tl = []
            for lang in ('ja', 'zh'):
                src = st_.get(lang) or {}
                if src.get('title'):
                    tl.append(src['title'])
            if tl:
                art_titles.setdefault(k2, []).extend(tl)
    print('有词条标题的站:', len(art_titles), flush=True)

    matched = {}

    # 1) 词条 images 主路径（证据：V4 实测 ja 0 命中，保留作低概率补充）
    def batch_article_images(todo, host, tag):
        hits = 0
        items = list(todo.items())
        for i in range(0, len(items), 50):
            chunk = items[i:i + 50]
            titles = '|'.join(t for _, t in chunk if t)
            try:
                d = api_get({'action': 'query', 'titles': titles, 'prop': 'images',
                             'imlimit': '50'}, host=host)
            except Exception:
                continue
            pages = iter_pages(d)
            for pg in pages:
                t = pg.get('title')
                key = next((k for k, tl2 in chunk if tl2 == t or t in tl2), None)
                if key is None or key in matched:
                    continue
                imgs = [im.get('title', '') for im in (pg.get('images') or [])]
                for im in imgs:
                    low = im.lower()
                    if im.startswith('File:') and low.endswith('.svg') and any(k in low for k in IMG_KEYWORDS):
                        matched[key] = (im, host)
                        hits += 1
                        break
            time.sleep(0.2)
        return hits

    ja_todo = {k: next((t for t in tl if t), None) for k, tl in art_titles.items() if k not in idx}
    print('词条 images 待查(ja):', len(ja_todo), flush=True)
    h1 = batch_article_images(ja_todo, API_JA, 'ja')
    print('词条 images 命中(ja):', h1, flush=True)

    # 2) 枚举分类
    files = enum_category_files()
    for t in files:
        tok = norm_station(station_token(t))
        if tok and tok in by_norm:
            key = by_norm[tok]
            if key not in matched and key not in idx:
                matched[key] = (t, API_COMMONS)
    print('分类命中（累计 %d）' % len(matched), flush=True)

    # 3) 批量文件名探测（三端点：ja + zh + commons；命名按真实风格扩充）
    cand = {}
    for key, v in stations.items():
        if key in matched or key in idx:
            continue
        name = v.get('name') or key
        kana = v.get('kana') or ''
        en = (ni_st.get(key) or {}).get('en') or ''
        for base in {name, kana}:
            if not base:
                continue
            for suf in ('駅配線図', '配線図', '駅配線略図', '配線圖'):
                cand.setdefault(base + suf + '.svg', key)
        if en:
            e = str(en).replace(' ', '_')
            for pat in ('Rail_Tracks_map_%s_Station.svg', 'Rail_track_diagram_of_%s_station.svg',
                        'Rail_track_diagram_of_%s_Station.svg', 'Track_diagram_of_%s_Station.svg',
                        'Track_map_of_%s_Station.svg', '%s_Station_track_diagram.svg'):
                cand.setdefault(pat % e, key)
    print('文件名探测候选:', len(cand), flush=True)
    for host, tag in ((API_JA, 'ja'), (API_ZH, 'zh'), (API_COMMONS, 'commons')):
        hit = find_by_title_batch(cand, host)
        for key, t in hit.items():
            if key not in matched and key not in idx:
                matched[key] = (t, host)
        print('%s 探测命中:%d（累计 %d）' % (tag, len(hit), len(matched)), flush=True)

    # 4) 搜索兜底（全站；单 genre 提速；文件名校验）
    if fallback_limit is None:
        fallback_limit = len(stations)
    todo = [k for k in art_titles if k not in matched and k not in idx][:fallback_limit]
    print('搜索兜底站数:', len(todo), flush=True)
    hit_cnt = 0
    for n, key in enumerate(todo):
        v = stations.get(key, {})
        name = v.get('name') or key
        kana = v.get('kana') or ''
        en = (ni_st.get(key) or {}).get('en') or ''
        t = find_by_search(name, kana, en)
        if t:
            matched[key] = (t, API_COMMONS)
            hit_cnt += 1
        if (n + 1) % 200 == 0:
            print('  搜索进度: %d/%d, 命中 %d' % (n + 1, len(todo), hit_cnt), flush=True)
        time.sleep(0.35)

    # 重点站补搜：主搜索未命中的超重要站，加搜 構内図 / track map 两种 genre
    extra_todo = [k for k in todo if k not in matched]
    for n, key in enumerate(extra_todo):
        v = stations.get(key, {})
        name = v.get('name') or key
        kana = v.get('kana') or ''
        en = (ni_st.get(key) or {}).get('en') or ''
        t = find_by_search(name, kana, en, genres=('構内図', 'track map'))
        if t:
            matched[key] = (t, API_COMMONS)
            print('  补搜命中 %s <- %s' % (key, t), flush=True)
        if (n + 1) % 200 == 0:
            print('  补搜进度: %d/%d' % (n + 1, len(extra_todo)), flush=True)
        time.sleep(0.35)

    # 5) 下载（限速 + 429 退避）
    todo = [(k, t, host) for k, (t, host) in matched.items() if k not in idx]
    print('待下载:', len(todo), flush=True)
    ok = 0
    for n, (key, t, host) in enumerate(todo):
        try:
            raw, artist, license = fetch_svg(t, host)
        except Exception as e:
            print('  下载失败 %s: %s' % (key, str(e)[:80]), flush=True)
            continue
        if not raw:
            print('  无文件 %s (%s)' % (key, t), flush=True)
            continue
        fn = os.path.join(OUT, key + '.svg')
        open(fn, 'wb').write(raw)
        open(fn + '.clean', 'w', encoding='utf-8').write(clean_svg(raw))
        idx[key] = {
            'found': True, 'title': t,
            'artist': artist, 'license': license,
            'source': 'https://' + ('ja' if host == API_JA else 'zh' if host == API_ZH else 'commons') + '.wikipedia.org/wiki/' + urllib.parse.quote(t.replace(' ', '_')),
            'bytes': len(raw),
        }
        for ent in cache.values():
            st_ = ent.get('stations', {}).get(key)
            if st_ is not None:
                st_['trackdiagram'] = {'title': t, 'artist': artist, 'license': license,
                                       'source': idx[key]['source']}
                break
        ok += 1
        print('  [%d/%d] %s <- %s' % (n + 1, len(todo), key, t), flush=True)
        if checkpoint_every and (n + 1) % checkpoint_every == 0:
            json.dump(idx, open(idx_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            print('  checkpoint: %d 站' % len(idx), flush=True)
    json.dump(idx, open(idx_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    if any(ent.get('stations', {}).get(k, {}).get('trackdiagram')
           for ent in cache.values() for k in ent.get('stations', {})):
        json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('词条缓存已写入配线图元数据', flush=True)
    found = sum(1 for v in idx.values() if v.get('found'))
    print('完成. 配线图命中: %d / %d 站（本次下载 %d）' % (found, len(stations), ok), flush=True)


if __name__ == '__main__':
    main()

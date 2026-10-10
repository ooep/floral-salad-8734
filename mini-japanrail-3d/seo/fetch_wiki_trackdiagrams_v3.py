#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Wikimedia Commons 抓取日本车站「配線図（站线配置图）」SVG 并解析入库。

V2（增量/受限版，供与 V1 并发或超时重跑使用）：
  * --fallback-limit N ：兜底搜索只覆盖前 N 个未命中站（控制总时长，优先站先拿）
  * --checkpoint-every N：下载每 N 个文件即把索引写盘（防 6h 超时被杀全丢）
  * 其余逻辑与 V1 完全一致；配合 seo-trackdiagrams-v2.yml 的「克隆基线→合并式 push」
    可与 V1 并发且不互相覆盖。

用法：python3 seo/fetch_wiki_trackdiagrams_v2.py [--fallback] [--fallback-limit N] [--checkpoint-every N]
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
    """枚举分类下全部 SVG 文件标题（自动翻页）。失败不静默：打印 API 原始响应便于排查。"""
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
            except Exception as e:
                print('  !! 枚举分类 %s 请求异常: %s（跳过该分类）' % (cat, str(e)[:120]), flush=True)
                break
            if 'error' in d:
                print('  !! 枚举分类 %s API 错误: %s（跳过该分类）' % (cat, str(d['error'])[:200]), flush=True)
                break
            members = d.get('query', {}).get('categorymembers', [])
            if not members and 'continue' not in d:
                print('  !! 分类 %s 返回 0 成员（可能分类不存在或已改名）' % cat, flush=True)
                break
            for m in members:
                t = m.get('title', '')
                if t.lower().endswith('.svg') and t not in files:
                    files.append(t)
            if 'continue' in d:
                cont = d['continue']
            else:
                break
        print('  分类 %s -> 累计文件 %d' % (cat, len(files)), flush=True)
    return files


def find_by_title_batch(candidates):
    """批量探测候选文件名是否存在（imageinfo，50 个/请求）。

    candidates: {title: key}。返回 {key: title}（存在且为 SVG 的）。
    """
    found = {}
    items = list(candidates.items())
    for i in range(0, len(items), 50):
        chunk = items[i:i + 50]
        titles = '|'.join('File:' + t for t, _ in chunk)
        try:
            d = api_get({'action': 'query', 'titles': titles, 'prop': 'imageinfo'})
        except Exception as e:
            print('  !! 批量探测请求异常: %s' % str(e)[:100], flush=True)
            continue
        pages = d.get('query', {}).get('pages', {})
        for _, pg in pages.items():
            t = (pg.get('title') or '')[5:]
            key = candidates.get(t)
            if key and pg.get('imageinfo'):
                found[key] = t
        if (i // 50) % 10 == 9:
            print('  批量探测进度: %d/%d, 已发现 %d' % (min(i + 50, len(items)), len(items), len(found)), flush=True)
    return found


def find_by_search(names):
    """搜索兜底（修正语法：去 filetype，intitle 带引号，命中即停）。"""
    for nm in names:
        for g in FALLBACK_GENRES:
            q = 'intitle:"%s" %s' % (nm, g)
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
    fallback_limit = None
    if '--fallback-limit' in sys.argv:
        i = sys.argv.index('--fallback-limit')
        try:
            fallback_limit = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            fallback_limit = None
    checkpoint_every = 0
    if '--checkpoint-every' in sys.argv:
        i = sys.argv.index('--checkpoint-every')
        try:
            checkpoint_every = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            checkpoint_every = 0
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

    # 2) 本地匹配（分类枚举命中）
    matched = {}  # key -> title
    for t in files:
        tok = norm_station(station_token(t))
        if not tok:
            continue
        if tok in by_norm:
            key = by_norm[tok]
            matched.setdefault(key, t)
    print('分类直接命中:', len(matched), flush=True)

    # 2.5) 批量文件名探测（主路径：按 Commons 命名惯例直接探测 File:<站名>駅配線図.svg 等，
    #      50 个/请求，全部站一轮即可，比逐站搜索快一个数量级且可靠）
    cand = {}
    for key, v in stations.items():
        if key in matched or key in idx:
            continue
        name = v.get('name') or key
        kana = v.get('kana') or ''
        for base in {name, kana}:
            if not base:
                continue
            for suf in ('駅配線図', '配線図', '駅配線略図'):
                cand.setdefault(base + suf + '.svg', key)
    print('文件名探测候选:', len(cand), flush=True)
    hit_batch = find_by_title_batch(cand)
    for key, t in hit_batch.items():
        matched.setdefault(key, t)
    print('探测命中:', len(hit_batch), '（累计 %d）' % len(matched), flush=True)

    # 3) 兜底搜索（仅 --fallback，对有词条站；修正后语法，命中即停）
    if fallback:
        keys_with_wiki = set()
        for ent in cache.values():
            keys_with_wiki.update(ent.get('stations', {}).keys())
        todo = [k for k in keys_with_wiki if k not in matched and k not in idx]
        if fallback_limit is not None:
            todo = todo[:fallback_limit]
        print('兜底搜索站数(限%s):' % (fallback_limit if fallback_limit is not None else '不限'), len(todo), flush=True)
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
        if checkpoint_every and (n + 1) % checkpoint_every == 0:
            json.dump(idx, open(idx_path, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            print('  checkpoint: 已下载 %d 站，索引已写盘' % len(idx), flush=True)
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

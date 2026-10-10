#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Wikimedia Commons 抓取日本车站「配線図（站线配置图）」SVG 并解析入库。

用途：为 SEO 站页提供真实的股道级配线图（如维基共享的「奥津軽いまべつ駅配線図.svg」）。
当前沙箱网络不可达 Wikimedia，本脚本设计为**部署环境（GitHub Actions CI）或可达网络**下运行：
    python3 .seo-logs/fetch_wiki_trackdiagrams.py

合规：仅使用 Wikimedia Commons 官方 API（api.php / Special:Redirect 直链），
      下载经 upload.wikimedia.org 文件直链；不抓取页面 HTML，不绕过 robots.txt。
      图片版权为 CC BY-SA 等（见 imageinfo extmetadata），页面引用时按来源署名。

流程：
  1. 读 station_map（站名/假名/消歧）与 eki_wiki_cache（日文原名）构造候选名；
  2. 对每站用 Commons 搜索 API 匹配「配線図」类 SVG（intitle 优先，含 ヶ/ケ 变体）；
  3. 下载 SVG 到 data/wiki_trackdiagrams/<key>.svg（保留原始作者/许可元数据）；
  4. 解析 SVG：XML 解析 + 清洗（去注释/去元数据/压缩空白），产出可嵌入页面的内联 SVG；
  5. 输出 data/wiki_trackdiagrams.json 索引 {key: {file,title,artist,license,source,bytes}}。

生成器侧（build_seo_static.py）读索引后，在站页「站线配置图」区块内联清洗后的 SVG。
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
GENRES = ('配線図', '配線圖', 'track diagram', 'Track diagram', '線路配線', 'プラットホーム配線')


def api_get(params):
    params = dict(params, format='json')
    url = API + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def find_trackdiagram(names):
    """按候选名在 Commons 搜索配线图 SVG，返回最佳 File 标题。"""
    for nm in names:
        for g in GENRES:
            q = 'intitle:%s %s filetype:svg' % (urllib.parse.quote(nm), g)
            try:
                d = api_get({'action': 'query', 'list': 'search', 'srsearch': q,
                             'srnamespace': '6', 'srlimit': '10'})
            except Exception:
                continue
            for hit in (d.get('query', {}).get('search') or []):
                t = hit.get('title', '')
                if t.startswith('File:') and t.lower().endswith('.svg'):
                    return t
        # 直接文件名猜测：File:<站名>配線図.svg（ja 原名）
        for g in ('配線図', '配線圖'):
            t = 'File:%s%s.svg' % (nm, g)
            try:
                d = api_get({'action': 'query', 'titles': t, 'prop': 'imageinfo',
                             'iiprop': 'url|extmetadata'})
            except Exception:
                continue
            pages = (d.get('query', {}).get('pages') or {})
            for _, pg in pages.items():
                if pg.get('imagerepository') == 'shared' and pg.get('imageinfo'):
                    return t
    return None


def fetch_svg(title):
    """取文件直链并下载 SVG。"""
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
    """解析并清洗 SVG：去注释/元数据，压缩空白，产出可嵌入页面的精简 XML。"""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return raw  # 非 XML（极少），原样保留
    # 记录可安全嵌入的 SVG（去掉最外层命名空间前缀无害；保留原始结构）
    for el in root.iter():
        for k in list(el.attrib.keys()):
            if k.startswith('{http://www.w3.org/1999/xlink}'):
                el.attrib['xlink:href' if False else k] = el.attrib[k]
    body = ET.tostring(root, encoding='unicode')
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    body = re.sub(r'>\s+<', '><', body)
    return body


def main():
    os.makedirs(OUT, exist_ok=True)
    sm = json.load(open(os.path.join(DATA, 'station_map.json'), encoding='utf-8'))
    cache_path = os.path.join(DATA, 'eki_wiki_cache.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    idx = json.load(open(os.path.join(DATA, 'wiki_trackdiagrams.json'), encoding='utf-8')) \
        if os.path.exists(os.path.join(DATA, 'wiki_trackdiagrams.json')) else {}
    stations = sm['stations']
    keys = list(stations.keys())
    print('待查车站:', len(keys), flush=True)
    for n, key in enumerate(keys):
        v = stations[key]
        name = v.get('name') or key
        cands = [name]
        if v.get('kana'):
            cands.append(v['kana'])
        ja = None
        for f, ent in cache.items():
            for k2, st_ in ent.get('stations', {}).items():
                if k2 == key or st_.get('name') == name:
                    src = st_.get('ja') or {}
                    if src.get('title'):
                        ja = src['title']
                        break
            if ja:
                break
        if ja and ja not in cands:
            cands.append(ja)
        if key in idx:
            print('  已缓存 %s' % key, flush=True)
            continue
        title = find_trackdiagram(cands)
        if not title:
            idx[key] = {'found': False}
            print('  无配线图 %s (%s)' % (key, cands[0]), flush=True)
            continue
        try:
            raw, artist, license = fetch_svg(title)
        except Exception as e:
            print('  下载失败 %s: %s' % (key, str(e)[:80]), flush=True)
            continue
        if not raw:
            continue
        fn = os.path.join(OUT, key + '.svg')
        open(fn, 'wb').write(raw)
        idx[key] = {
            'found': True, 'file': fn, 'title': title,
            'artist': artist, 'license': license,
            'source': 'https://commons.wikimedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')),
            'bytes': len(raw),
        }
        # 清洗后的内联版本
        clean = clean_svg(raw)
        open(fn + '.clean', 'w', encoding='utf-8').write(clean)
        print('  [%d/%d] %s <- %s' % (n + 1, len(keys), key, title), flush=True)
        time.sleep(0.4)
    json.dump(idx, open(os.path.join(DATA, 'wiki_trackdiagrams.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    found = sum(1 for v in idx.values() if v.get('found'))
    print('完成. 配线图命中: %d / %d' % (found, len(keys)), flush=True)


if __name__ == '__main__':
    main()

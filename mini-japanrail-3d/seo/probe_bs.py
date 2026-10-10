#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BS 散件结构探测：抓词条 wikitext，确认 {{BS-map}} 模板代码的真实结构。

用户指出：维基配线图不是整图，而是 BSicon 散件 SVG + 模板代码拼装渲染。
本脚本从 ja/zh 维基抓取样本词条的 wikitext，打印：
  * 是否存在 {{BS-map}} / {{BS-table}} 等 BS 模板块
  * 模板块的原始代码样例（BSicon 序列 + 站名/里程/注释列）
  * 词条里引用的 File:*.svg 配线图文件（若存在单文件）
跑在 GitHub Actions（网络可达 wikipedia.org）。
"""
import json
import re
import urllib.parse
import urllib.request

API_JA = 'https://ja.wikipedia.org/w/api.php'
API_ZH = 'https://zh.wikipedia.org/w/api.php'
UA = {'User-Agent': 'MiniJapanRail-SEO/1.0 (https://jr.suki.ing; contact: admin@jr.suki.ing)'}


def api(params, host, timeout=30):
    params = dict(params, format='json', formatversion='2')
    url = host + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        return {'__err__': '%s: %s' % (type(e).__name__, str(e)[:200])}


def get_wikitext(host, title):
    d = api({'action': 'query', 'prop': 'revisions', 'rvprop': 'content', 'titles': title}, host)
    for pg in d.get('query', {}).get('pages', []):
        revs = pg.get('revisions') or []
        if revs:
            return revs[0].get('content', '')
    return ''


def show_bs(title, text):
    print('===== %s (len=%d) =====' % (title, len(text)))
    # 找 BS 模板块（{{BS-map、{{BS-table、{{BS-rws、{{BS3、{{BS4 等）
    bs_blocks = []
    for m in re.finditer(r'\{\{(BS[^}\n]{0,60})([^{}]*)\}\}', text):
        bs_blocks.append(m.group(0))
    # 简化：按行找包含 |BSicon| 或 BS 图例的行
    bs_lines = [l for l in text.splitlines() if re.search(r'\{\{[Bb][Ss]', l) or re.search(r'\\|[A-Za-z]{2,6}[+\\]', l)]
    print('BS 相关行数:', len(bs_lines))
    if bs_lines:
        print('--- 前 8 行 ---')
        for l in bs_lines[:8]:
            print('  ' + l[:220])
        print('--- 后 4 行 ---')
        for l in bs_lines[-4:]:
            print('  ' + l[:220])
    # 找 File:*.svg 配线图单文件引用
    svgs = re.findall(r'File:([^\|\]\}]+\.svg)', text)
    diag = [s for s in svgs if '配線' in s or 'diagram' in s.lower() or 'track' in s.lower()]
    print('引用 SVG 文件数:', len(svgs), '| 疑似配线图:', diag[:6])
    print('')


def main():
    for host, tag in ((API_JA, 'ja'), (API_ZH, 'zh')):
        for title in ('奥津軽いまべつ駅', '東京駅'):
            show_bs('%s %s' % (tag, title), get_wikitext(host, title))
    # 线路级 BS-map 样本（海峡線 ja 词条）
    for title in ('海峡線', '山手線'):
        show_bs('ja 线路 ' + title, get_wikitext(API_JA, title))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""维基结构探测脚本（跑在 GitHub Actions，网络可达 Wikimedia）。

目标：一次性确认三条候选抓取路径的真实可用性，把原始 API 响应打出来供本地决策：
  1) 分类枚举 categorymembers（为什么 V1 拿 0 文件——是分类名不存在还是参数问题）
  2) 词条页 prop=images（从 ja 词条页直接拿其引用的图片，挑配線図 SVG——用户建议的主路径）
  3) intitle 搜索（修正语法后是否命中）
  4) 直接文件名探测（File:東京駅配線図.svg 是否存在）
只探测样本站，不下载。
"""
import json
import urllib.parse
import urllib.request

API = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'MiniJapanRail-SEO/1.0 (https://jr.suki.ing; contact: admin@jr.suki.ing)'}


def api(params, timeout=30):
    params = dict(params, format='json')
    url = API + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        return {'__err__': '%s: %s' % (type(e).__name__, str(e)[:200])}


def show(tag, d, maxlen=1200):
    s = json.dumps(d, ensure_ascii=False)
    print('=== %s ===' % tag)
    print(s[:maxlen])
    print('')


def main():
    # 1) 分类枚举（只取前 3 条，验证分类是否真实存在）
    for cat in ('Category:日本の鉄道駅の配線図',
                'Category:Track diagrams of railway stations in Japan',
                'Category:駅の配線図'):
        d = api({'action': 'query', 'list': 'categorymembers',
                 'cmtitle': cat, 'cmtype': 'file', 'cmlimit': '3'})
        show('ENUM ' + cat, d)

    # 2) 词条页 images（ja 词条名，prop=images 直接拿页面引用的文件）
    for title in ('奥津軽いまべつ駅', '東京駅', '新宿駅', '海峡線'):
        d = api({'action': 'query', 'titles': title, 'prop': 'images', 'imlimit': '50'})
        show('IMAGES ' + title, d)

    # 3) intitle 搜索（修正语法：intitle:"站名" 配線図）
    for q in ('intitle:"奥津軽いまべつ" 配線図', 'intitle:"東京駅" 配線図',
              '東京駅配線図', '奥津軽いまべつ駅配線図'):
        d = api({'action': 'query', 'list': 'search', 'srsearch': q,
                 'srnamespace': '6', 'srlimit': '5'})
        show('SEARCH ' + q, d)

    # 4) 直接文件名探测
    for t in ('File:東京駅配線図.svg', 'File:奥津軽いまべつ駅配線図.svg',
              'File:新宿駅配線図.svg', 'File:大阪駅配線図.svg'):
        d = api({'action': 'query', 'titles': t, 'prop': 'imageinfo'})
        show('PROBE ' + t, d)

    # 5) 分类内嵌子分类结构（万一主分类是子分类聚合）
    d = api({'action': 'query', 'list': 'allcategories',
             'acprefix': '日本の鉄道', 'aclimit': '20'})
    show('ALLCATS 日本の鉄道', d)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_pages_dist.py — 组装 Pages 发布目录（仅 html/css/js + SEO 静态页）

静态大文件（data/、logos/、seo/img/、图标 png 等）已由 jr-static Worker
（https://jr-static.suki.ing）托管，不再进入 Pages 发布物。

输出:
  dist/     GitHub Pages 根: index.html + index-quest.html + mini-japanrail-3d/ 前端
  cf-mj3d/  Cloudflare Pages 根: mini-japanrail-3d/ 前端内容（index.html 在根）

用法：python3 scripts/prepare_pages_dist.py
"""
import os, re, shutil, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINI = os.path.join(REPO, 'mini-japanrail-3d')

# IndexNow 密钥文件（{32位hex}.txt）：Bing/Yandex 免登录提交通道，
# 需位于站点根可访问。按格式匹配，换 key 无需改代码。
def is_indexnow_key(name):
    return re.fullmatch(r'[0-9a-f]{32}\.txt', name) is not None

# 前端可发布条目白名单（html/css/js + SEO 生成页 + 站点基础设施）
KEEP_NAMES = {
    'index.html', 'journey.html', 'privacy.html', 'orm-demo.html',
    'lines', 'stations',
    'sitemap.xml', 'sitemap-lines.xml', 'sitemap-stations.xml', 'sitemap-pages.xml',
    'robots.txt', '404.html', 'BingSiteAuth.xml', 'baidu_verify_codeva-DigR5zzAl8.html',
    'sogousiteverification.txt',
}
# 防御性剔除（即便白名单遗漏也不进 Pages）
DROP_NAMES = {
    'data', 'logos', 'seo', 'scripts', 'README.md', '.seo-logs',
    'apple-touch-icon.png', 'favicon.png', 'favicon-dark.png',
    'icon-192.png', 'icon-512.png', 'icon.png', 'icon-dark.png',
    'logo.png', 'logo-dark.png', 'og-image.png',
}


def copy_frontend(dst):
    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in os.listdir(MINI):
        if name.startswith('.') or name in DROP_NAMES or (name not in KEEP_NAMES and not is_indexnow_key(name)):
            continue
        s = os.path.join(MINI, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, name))
        else:
            shutil.copy2(s, os.path.join(dst, name))
        n += 1
    assert os.path.exists(os.path.join(dst, 'index.html')), 'missing index.html in ' + dst
    return n


def main():
    # dist/ —— GitHub Pages 根
    dist = os.path.join(REPO, 'dist')
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)
    for f in ('index.html', 'index-quest.html'):
        s = os.path.join(REPO, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dist, f))
    n = copy_frontend(os.path.join(dist, 'mini-japanrail-3d'))
    print('[dist] mini-japanrail-3d frontend entries:', n)

    # cf-mj3d/ —— Cloudflare Pages 根（前端内容直接置根）
    cf = os.path.join(REPO, 'cf-mj3d')
    if os.path.exists(cf):
        shutil.rmtree(cf)
    n = copy_frontend(cf)
    print('[cf-mj3d] frontend entries:', n)

    # 完整性检查
    for f in ('index.html', 'journey.html', 'privacy.html', 'orm-demo.html', 'robots.txt', '404.html'):
        p = os.path.join(cf, f)
        if not os.path.exists(p):
            print('::warning::cf-mj3d 缺文件: ' + f)
    for d in ('data', 'logos', 'seo'):
        if os.path.exists(os.path.join(cf, d)):
            print('::error::cf-mj3d 不应包含静态目录: ' + d)
            sys.exit(1)
    print('Pages 目录组装完成（不含任何静态大文件）')


if __name__ == '__main__':
    main()

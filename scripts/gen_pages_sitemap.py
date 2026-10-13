#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_pages_sitemap.py — 为 GitHub Pages 主站生成根级 sitemap.xml + robots.txt

主站（https://ooep.github.io/floral-salad-8734/）为单页应用入口，
发布物由 prepare_pages_dist.py 组装到 dist/ 根。本脚本在部署时扫描
dist/ 根级 HTML 页面，自动生成 sitemap 与 robots，随 Pages 一并发布，
保证每次部署 URL 列表自动刷新。

说明：mini-japanrail-3d/ 是独立子站（正式域 jr.suki.ing，自带 sitemap 体系），
不重复收录到主站 sitemap。

用法：python3 scripts/gen_pages_sitemap.py [dist_dir]
环境变量 PAGES_BASE 可覆盖站点基址（默认 https://ooep.github.io/floral-salad-8734）
"""
import os
import sys
from datetime import datetime, timezone

DEFAULT_BASE = 'https://ooep.github.io/floral-salad-8734'


def xml_esc(s):
    return (str(s if s is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def collect_pages(dist):
    """收集 dist 根级 HTML 页面（不含子目录、不含 404 页）。"""
    pages = []
    for name in sorted(os.listdir(dist)):
        if name.endswith('.html') and name != '404.html':
            pages.append(name)
    return pages


def page_url(base, name):
    if name == 'index.html':
        return base + '/'
    return base + '/' + name


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = sys.argv[1] if len(sys.argv) > 1 else os.path.join(repo, 'dist')
    base = os.environ.get('PAGES_BASE', DEFAULT_BASE).rstrip('/')
    lastmod = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if not os.path.isdir(dist):
        print('::error::dist 目录不存在: %s' % dist)
        sys.exit(1)

    pages = collect_pages(dist)
    if not pages:
        print('::error::dist 根级没有 HTML 页面，跳过 sitemap 生成')
        sys.exit(1)

    # sitemap.xml —— 主站页面不多，单文件即可
    out = os.path.join(dist, 'sitemap.xml')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for name in pages:
            url = page_url(base, name)
            prio, freq = ('1.0', 'daily') if name == 'index.html' else ('0.8', 'weekly')
            f.write('<url><loc>%s</loc><lastmod>%s</lastmod>'
                    '<changefreq>%s</changefreq><priority>%s</priority></url>\n'
                    % (xml_esc(url), lastmod, freq, prio))
        f.write('</urlset>\n')

    # robots.txt
    with open(os.path.join(dist, 'robots.txt'), 'w', encoding='utf-8') as f:
        f.write('User-agent: *\n'
                'Allow: /\n'
                '\n'
                '# 主站纯静态单页应用：真实 HTML 页面可直接收录。\n'
                'Sitemap: %s/sitemap.xml\n' % base)

    print('[sitemap] %d 个主站页面 -> %s' % (len(pages), out))
    print('[robots] -> %s' % os.path.join(dist, 'robots.txt'))


if __name__ == '__main__':
    main()

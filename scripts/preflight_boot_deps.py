#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight_boot_deps.py — 首屏依赖预检（2026-11-06 审计⑤）

静态资产部署到 jr-static 之后、前端部署之前，按线上真实 URL 逐个验证首屏
所需资源可达（200/206）。任一失败即红 —— 绝不允许「部署绿但站点白屏」再发生。

覆盖（本次 0% 事故教训：探针不能只看 script 标签，必须覆盖模块静态 import 目标）：
  R1 app.js 静态 import 目标（import ... from '...' / import '...'）
  R2 app.js 动态 import('...')
  R3 index.html 的 script[src] / link[href] / modulepreload（jr-static 与 jr.suki.ing）
  R4 importmap 条目
  R5 相对导入禁令：./ ../ 一律按 app.js 线上基址解析后探测，不可达即失败
     （项目约定：线上 main 一律 jr-static CDN 绝对地址）
  R6 app.js 内引用的全部 jr-static 数据/资产字面量（含 boot 数据）
  R7 每个 URL 要求 200/206（带重试）
  R8 失败输出 ::error:: 行（Actions 注解直接指向失败 URL）

用法：python3 scripts/preflight_boot_deps.py [--extra URL ...]
  --extra 追加探测地址（负例自测用，例如故意指向不存在的文件）。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINI = os.path.join(REPO, 'mini-japanrail-3d')
APP_BASE = 'https://jr-static.suki.ing/app/'   # app.js 的线上所在基址（相对引用据此解析）
STATIC_RE = re.compile(r"""import\s+(?:[\w${},*\s]+\s+from\s+)?['"]([^'"]+)['"]""")
DYN_RE = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
ASSET_URL_RE = re.compile(r'https://jr-static\.suki\.ing/[A-Za-z0-9_./-]+')
TAG_URL_RE = re.compile(r'<(?:script|link)\b[^>]*?\b(?:src|href)="([^"]+)"')


def collect():
    urls, relative = set(), []
    app_js = open(os.path.join(MINI, 'app.js'), encoding='utf-8').read()
    index_html = open(os.path.join(MINI, 'index.html'), encoding='utf-8').read()

    # R1/R2：app.js 静态 + 动态 import
    for ref in STATIC_RE.findall(app_js) + DYN_RE.findall(app_js):
        if ref.startswith(('http://', 'https://')):
            urls.add(ref)
        elif ref.startswith(('./', '../')):
            relative.append(ref)
        # 裸模块名（走 importmap）在 R4 覆盖

    # R6：app.js 内全部 jr-static 字面量（数据/图标/模型等）
    for u in ASSET_URL_RE.findall(app_js):
        if '.' in u.rsplit('/', 1)[-1]:   # 排除目录型 base（以 / 结尾或无扩展名）
            urls.add(u)

    # R3：index.html 标签引用（只关心本站两域名）
    for u in TAG_URL_RE.findall(index_html):
        if u.startswith(('https://jr-static.suki.ing/', 'https://jr.suki.ing/')):
            urls.add(u.split('#')[0])

    # R4：importmap
    m = re.search(r'<script type="importmap">\s*(\{.*?\})\s*</script>', index_html, re.S)
    if m:
        try:
            imap = json.loads(m.group(1)).get('imports', {})
            for v in imap.values():
                if v.startswith('http'):
                    urls.add(v)
        except Exception as e:  # noqa: BLE001
            print('::error::importmap 解析失败: %s' % e)
            sys.exit(1)
    return urls, relative


def probe(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                'Range': 'bytes=0-0',
                'User-Agent': 'boot-deps-preflight/1.0',
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:  # noqa: PERF203
            return e.code
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    return 'TIMEOUT(%s)' % last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extra', nargs='*', default=[])
    args = ap.parse_args()

    urls, relative = collect()

    # R5：相对导入 —— 解析后探测；项目约定线上 main 一律绝对地址，出现即高亮
    rel_results = []
    for ref in relative:
        resolved = urljoin(APP_BASE, ref)
        print('::warning::app.js 存在相对导入 %r → 解析为 %s（约定应使用 jr-static 绝对地址）' % (ref, resolved))
        urls.add(resolved)
        rel_results.append((ref, resolved))

    failures = []
    for u in sorted(urls | set(args.extra)):
        st = probe(u)
        ok = st in (200, 206)
        print('[preflight] %-3s %s' % (st, u))
        if not ok:
            failures.append((u, st))

    if failures:
        for u, st in failures:
            tag = '（相对导入解析目标）' if any(r[1] == u for r in rel_results) else ''
            print('::error::首屏依赖预检失败: %s -> %s%s' % (u, st, tag))
        sys.exit(1)
    print('[preflight] 全部 %d 个首屏依赖 URL 线上可达（其中相对导入解析目标 %d 个）'
          % (len(urls) + len(args.extra), len(relative)))


if __name__ == '__main__':
    main()

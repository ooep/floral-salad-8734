#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
readback_online.py — 部署后线上回读断言（2026-11-06 审计④：部署来源可追溯）

在静态资产与前端部署完成后，从线上拉取 /app/ 三件并断言：
  1. app.js / app.css / train3d.js 均存在且 200；
  2. 内容 sha256 与本次推送 commit 构建出的 static-worker/assets/app/* 完全一致
     —— 不一致 = 线上不是本 commit 的产物（工作区直发/手工上传）或 CDN 仍在吐旧内容；
  3. 线上 body 不含已知坏模式（'./vendor/ 相对导入，2026-11-06 全站 0% 事故根因）。
任一失败 → ::error:: + exit 1。绝不允许「部署绿但站点坏」静默通过。
"""
import hashlib
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(REPO, 'static-worker', 'assets', 'app')
BASE = 'https://jr-static.suki.ing/app/'
FILES = ('app.js', 'app.css', 'train3d.js')
BAD_PATTERNS = ("'./vendor/", '"./vendor/', "'../vendor/", '"../vendor/')


def fetch(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                'Cache-Control': 'no-cache',
                'User-Agent': 'deploy-readback/1.0',
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    print('::error::readback 抓取失败 %s: %s' % (url, last))
    sys.exit(1)


def main():
    if not os.path.isdir(ASSETS):
        print('::error::static-worker/assets/app 不存在（应先运行 build_static_assets.py）')
        sys.exit(1)
    bad = []
    stamp = int(time.time())
    for f in FILES:
        local = os.path.join(ASSETS, f)
        if not os.path.isfile(local):
            bad.append('%s: 本次构建产物缺失' % f)
            continue
        want = hashlib.sha256(open(local, 'rb').read()).hexdigest()
        status, body = fetch('%s%s?__readback=%d' % (BASE, f, stamp))
        got = hashlib.sha256(body).hexdigest()
        if status != 200:
            bad.append('%s: HTTP %d（期望 200）' % (f, status))
            continue
        if got != want:
            bad.append('%s: sha256 不符（线上 %s… ≠ 本次构建 %s…）'
                       '—— 线上内容不来自本 commit，或 CDN 未更新' % (f, got[:16], want[:16]))
            continue
        txt = body.decode('utf-8', 'ignore')
        hit = [p for p in BAD_PATTERNS if p in txt]
        if hit:
            bad.append('%s: 线上内容含坏模式 %r（相对导入会让模块图 404）' % (f, hit[0]))
            continue
        print('[readback] %s OK 200 sha256=%s… (%dB)' % (f, got[:16], len(body)))
    if bad:
        for b in bad:
            print('::error::%s' % b)
        sys.exit(1)
    print('[readback] /app/ 三件线上回读通过：200 + 与本 commit 构建一致 + 无坏模式')


if __name__ == '__main__':
    main()

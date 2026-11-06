#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_data_version.py — DATA_VERSION 与 data/live 同源门禁（2026-10-25「乱飞」教训）

背景：DATA_VERSION 是 IDB 索引与数据文件请求(?v=)的缓存键。数据变了而版本不递增，
老访客会拿到「旧索引 × 新时刻表」错配 → 列车乱飞。refresh.yml 周更路径会自动
bump，但任何其他路径（历史重建、手工提交）改动 data/live 都必须过本门禁。

锁文件：data/live/.version-lock  {"hash": <数据指纹>, "version": <DATA_VERSION>}
规则：锁必须与当前 (数据内容, DATA_VERSION) 恒一致，且随数据变更同一次提交更新。

用法：
  --check   部署门禁：锁缺失/与数据不同步 → 失败；同步 → 通过。
  --update  刷新锁（bump DATA_VERSION 之后、提交之前调用；refresh.yml 已接入）。
"""
import argparse
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, 'data', 'live')
LOCK = os.path.join(LIVE, '.version-lock')
APPJS = os.path.join(REPO, 'mini-japanrail-3d', 'app.js')
JOURNEY = os.path.join(REPO, 'mini-japanrail-3d', 'journey.html')


def data_hash():
    """data/live 全量内容指纹（排除锁文件自身；按路径排序保证确定性）。"""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(LIVE):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.abspath(p) == os.path.abspath(LOCK):
                continue
            rel = os.path.relpath(p, LIVE).replace(os.sep, '/')
            fh = hashlib.sha256()
            with open(p, 'rb') as fp:
                for chunk in iter(lambda: fp.read(1 << 20), b''):
                    fh.update(chunk)
            h.update(rel.encode('utf-8') + b'\0')
            h.update(fh.digest())
    return h.hexdigest()


def current_versions():
    m = re.search(r"const DATA_VERSION = '([^']+)';",
                  open(APPJS, encoding='utf-8').read())
    if not m:
        print('::error::app.js 中找不到 DATA_VERSION 声明')
        sys.exit(1)
    v_app = m.group(1)
    mj = re.search(r"const DATA_VERSION = '(mjrj-[^']+)';",
                   open(JOURNEY, encoding='utf-8').read())
    return v_app, (mj.group(1) if mj else None)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true', help='部署门禁')
    g.add_argument('--update', action='store_true', help='刷新锁文件')
    args = ap.parse_args()

    if not os.path.isdir(LIVE):
        print('::error::data/live 不存在')
        sys.exit(1)

    h = data_hash()
    v_app, v_j = current_versions()

    if v_j is not None and v_j != 'mjrj-' + v_app:
        print('::error::journey.html DATA_VERSION(%s) 与 app.js(%s) 不同源' % (v_j, v_app))
        sys.exit(1)

    if args.update:
        with open(LOCK, 'w', encoding='utf-8') as f:
            json.dump({'hash': h, 'version': v_app}, f, ensure_ascii=False)
            f.write('\n')
        print('[data-version] lock updated: %s @ %s...' % (v_app, h[:16]))
        return

    # --check
    if not os.path.isfile(LOCK):
        print('::error::缺少 data/live/.version-lock —— 数据基线未登记。'
              '请在 bump DATA_VERSION 的同一次提交里运行 scripts/check_data_version.py --update')
        sys.exit(1)
    try:
        lock = json.load(open(LOCK, encoding='utf-8'))
    except Exception as e:
        print('::error::.version-lock 不可解析: %s' % e)
        sys.exit(1)

    problems = []
    if h != lock.get('hash'):
        problems.append('data/live 内容已变（锁 %s… → 实际 %s…）' % (str(lock.get('hash'))[:16], h[:16]))
    if v_app != lock.get('version'):
        problems.append('DATA_VERSION 已变（锁 %s → 实际 %s）' % (lock.get('version'), v_app))
    if problems:
        print('::error::DATA_VERSION 同源门禁失败：%s。' % '；'.join(problems)
              + '数据变更必须与 DATA_VERSION bump 及 --update 锁刷新在同一次提交完成'
              + '（2026-10-25 乱飞事故教训）')
        sys.exit(1)
    print('[data-version] OK: 数据与版本同源（%s @ %s…）' % (v_app, h[:16]))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""models/ consist 引用可达性校验(提交前门禁,长期使用)。

用法:
  python3 scripts/verify_model_refs.py --root mini-japanrail-3d/models [--extra DIR ...]

规则(与线上布局一致):
  - consist.json 内 cars[].model / cars[].lod.model / cars[].texture / cars[].lod.texture
    均按「相对 consist.json 所在目录」解析(URL join 语义,支持 ../ 跨 slug 复用二进制);
  - --extra 目录视为将并入 --root 的待提交 slug(模拟提交后的树);
  - 任一引用解析后文件不存在 → 退出码 1(禁止提交);
  - 绝对 URL(http*)引用直接跳过(不由 models/ 承载)。
"""
import argparse
import json
import os
import posixpath
import sys

REF_KEYS = (('model',), ('texture',))


def collect_refs(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ('model', 'texture') and isinstance(v, str):
                out.append(v)
            else:
                collect_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_refs(v, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--extra', action='append', default=[])
    args = ap.parse_args()

    # slug -> 实际目录(extra 优先,模拟提交后覆盖关系:本脚本要求 extra 与 root 不重名)
    dirs = {}
    for name in sorted(os.listdir(args.root)):
        p = os.path.join(args.root, name)
        if os.path.isdir(p):
            dirs[name] = p
    for ex in args.extra:
        for name in sorted(os.listdir(ex)):
            p = os.path.join(ex, name)
            if os.path.isdir(p):
                if name in dirs:
                    print('FAIL: extra slug 与 root 重名(覆盖需人工确认): %s' % name)
                    return 1
                dirs[name] = p

    bad = 0
    checked = 0
    for slug, d in sorted(dirs.items()):
        cj = os.path.join(d, 'consist.json')
        if not os.path.isfile(cj):
            print('FAIL: %s 缺 consist.json' % slug)
            bad += 1
            continue
        try:
            data = json.load(open(cj, encoding='utf-8'))
        except Exception as e:
            print('FAIL: %s consist.json 解析失败: %s' % (slug, e))
            bad += 1
            continue
        refs = []
        collect_refs(data, refs)
        for ref in refs:
            if ref.startswith('http'):
                continue
            checked += 1
            resolved = posixpath.normpath(posixpath.join('/models', slug, ref))
            rel = resolved[len('/models/'):]
            target = None
            for name, dd in dirs.items():
                if rel == name or rel.startswith(name + '/'):
                    target = os.path.join(dd, rel[len(name):].lstrip('/'))
                    break
            if target is None or not os.path.isfile(target):
                print('FAIL: %s 引用不可达: %s -> %s' % (slug, ref, rel))
                bad += 1
    print('checked refs=%d slugs=%d bad=%d' % (checked, len(dirs), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

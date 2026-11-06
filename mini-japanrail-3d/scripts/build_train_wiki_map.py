#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_train_wiki_map.py — 生成 mini-japanrail-3d/data/train_wiki_map.json

把站点(mini-japanrail-3d)的「特急爱称 / 线路名」键空间映射到
ressha-wiki 仓库的车型文件(data/<日文车辆名>.json)，供列车详情抽屉的
「列车百科」折叠框惰性加载使用(与车站抽屉的 wiki_line_map.json 同模式)。

数据来源：
  - 站点：data/train_icons_atlas.json(line/tokkyu 键)、data/tokkyu.json(sh/nm/nmI)、data/tmaps.json(lines)
  - 百科：ressha-wiki/mapping.json(图标token到车辆 / 特急站名到图标 / 线路站名到图标)、
          ressha-wiki/index.json(车辆清单,含每车型的特急/线路网站键)

排序：站点图集实际选用的图标(files[0])对应车型在前，其余按 index.json 顺序补充。
"""
import json, os, collections

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # mini-japanrail-3d/
WIKI = '/root/work/ressha-wiki-main'                                  # ressha-wiki 仓库(本地)

def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)

def main():
    atlas = load(os.path.join(SITE, 'data/train_icons_atlas.json'))
    tokkyu = load(os.path.join(SITE, 'data/tokkyu.json'))
    tmaps = load(os.path.join(SITE, 'data/tmaps.json'))
    mp = load(os.path.join(WIKI, 'mapping.json'))
    idx = load(os.path.join(WIKI, 'index.json'))

    tok2v = mp.get('图标token到车辆') or {}
    tk_icons = mp.get('特急站名到图标') or {}
    ln_icons = mp.get('线路站名到图标') or {}
    vehicles = idx.get('车辆') or []

    def token_of(fname):
        # '02_east/azusa-kaiji__e353.png' -> 'e353'
        base = fname.rsplit('/', 1)[-1]
        if '__' not in base:
            return None
        return base.split('__', 1)[1].rsplit('.', 1)[0]

    def from_icons(files):
        out = []
        for f in files or []:
            tk = token_of(f)
            v = tok2v.get(tk) if tk else None
            if v and v not in out:
                out.append(v)
        return out

    def from_index(key, field):
        return [v['日文'] for v in vehicles if key in (v.get(field) or [])]

    def merge(key, icon_files, field):
        out = from_icons(icon_files)
        for v in from_index(key, field):
            if v not in out:
                out.append(v)
        return out

    # ---- 站点键空间 ----
    site_tk = set(atlas.get('tokkyu') or {}) | set(tk_icons)
    for d in ('sh', 'nm', 'nmI'):
        for v in (tokkyu.get(d) or {}).values():
            if v:
                site_tk.add(v)
    site_ln = set(atlas.get('line') or {}) | set(ln_icons)
    for tm in tmaps.values():
        for l in (tm.get('lines') or []):
            site_ln.add(l)

    tk_map, ln_map = {}, {}
    for k in site_tk:
        vs = merge(k, tk_icons.get(k), '特急')
        if vs:
            tk_map[k] = vs
    for k in site_ln:
        vs = merge(k, ln_icons.get(k), '线路')
        if vs:
            ln_map[k] = vs

    # 图集兜底图(E217 湘南色,train_atlas.py FALLBACK_FILE 'tokaido-line__e217td.png',
    # 其 token 'e217td' 未入百科 token 表,取同车型 token 'e217td1')对应车型:
    # 站点无可用图标键时(多线路全为共享干道等),详情卡显示的正是该车型
    fb_vehicle = tok2v.get('e217td1') or tok2v.get('e217td')

    out = {'v': 1, 'tk': dict(sorted(tk_map.items())), 'ln': dict(sorted(ln_map.items()))}
    if fb_vehicle:
        out['fb'] = [fb_vehicle]
    dst = os.path.join(SITE, 'data/train_wiki_map.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    print('train_wiki_map.json 写出:', dst)
    print('  特急键:', len(tk_map), ' 线路键:', len(ln_map),
          ' 大小: %.1f KB' % (os.path.getsize(dst) / 1024))
    print('  站点 ATLAS.tokkyu 键被百科覆盖: %d/%d' % (
        len([k for k in (atlas.get('tokkyu') or {}) if k in tk_map]), len(atlas.get('tokkyu') or {})))
    print('  站点 tmaps 线路被百科覆盖: %d/%d' % (
        len([l for l in {l for tm in tmaps.values() for l in (tm.get('lines') or [])} if l in ln_map]),
        len({l for tm in tmaps.values() for l in (tm.get('lines') or [])})))

    # ---- 覆盖率统计(平日时刻表) ----
    tr = load(os.path.join(SITE, 'data/trains_sa.json'))
    n_all = n_cov = n_multi = 0
    multi_samples = collections.Counter()
    for e in tr['T']:
        tm = tmaps.get(str(e['t']))
        if not tm:
            continue
        n_all += 1
        vs = []
        nm = None
        # 与前端 tripName 同序:特急优先
        for k, arr in tk_map.items():
            pass
        # 简化:直接用 tmaps 的 lines 统计(特急名需签名表,略)
        for l in (tm.get('lines') or []):
            for v in ln_map.get(l, []):
                if v not in vs:
                    vs.append(v)
        if vs:
            n_cov += 1
            if len(vs) > 1:
                n_multi += 1
                multi_samples[len(vs)] += 1
    print('  平日班次覆盖(仅线路维度): %d/%d = %.1f%%, 多车型 %d (分布 %s)' % (
        n_cov, n_all, 100.0 * n_cov / max(1, n_all), n_multi, dict(sorted(multi_samples.items()))))

if __name__ == '__main__':
    main()

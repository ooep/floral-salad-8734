#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_track_diagram_index.py — 构建「车站 → 线路 → 配线图 SVG」映射索引

输入:
  1) jr-track SVG 语料（解压后的 downloads/documents/，head b9d6f70）
  2) 主站 mini-japanrail-3d/data/station_map.stations.json（station_key → lines）

算法:
  Pass 1 目录→线路投票(站点特异度加权): 每个线路目录(jr/east/yamanote 等)的分块 SVG
         文本中出现的主站站名，用该站在主站数据中的 lines 投票；每票权重 1/该站线路数
         （小站一票含金量高，大枢纽站一票分摊）。候选线路须有 ≥2 个不同站名支持，
         防止单个同名站把冷门线路注入无关目录（如大阪「平野」把飯坂線注入関西本線目录）；
         全目录无任何线路达 2 名时退回取得分最高者（单站小目录仍可工作）。
         不用「1/线路全库站数」做 IDF：主站 lines 含直通运转归属（山手線被挂到 237 站），
         线路规模失真，会把真身线路过度折价。
  Pass 2 分块定线: 每个分块按自身出现的站名做特异度投票，得票最高者即「该图所属线路」
         （与目录最高候选打平时优先目录候选，稳定边界情形）。枢纽站作为邻线/交汇标签
         出现在他线图中时（如東京出现在中央線图、上野出现在常磐線图），因图属线路
         不在该站 lines 内而不生成条目——宁缺勿错。
  Pass 3 车站→分块匹配: 站名出现在分块文本中，且「分块所属线路 ∈ 该站 lines」才收录。
  线路交集过滤是防同名站错配的关键（如 5 个「高田」只命中各自所属线路的目录）。
  feature/ 专题目录（杂志企划图，非线路配线）不参与映射。

输出:
  - track_diagram_index.json（前端索引，随主站 data/ 发布到 jr-static）
  - 验证报告（--verify 抽样站核对）
"""
import json, os, re, sys, random, collections

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINI = os.path.join(REPO, 'mini-japanrail-3d')
CORPUS = os.environ.get('JRT_TRACK_CORPUS', '/tmp/jrtrack/repo/jr-track-main/downloads/documents')
PREFIX = 'downloads/documents/'

CJK = re.compile(r'[\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]')
TAG = re.compile(r'<[^>]+>')
PAREN = re.compile(r'[（(][^（）()]*[）)]\s*$')


def norm_station(name):
    """主站站名去歧义后缀: 高田(奈良県) → 高田"""
    return PAREN.sub('', name).strip()


def extract_labels(path):
    """抽取 SVG 内所有文本标签（去嵌套 tspan、去首尾空白）。"""
    try:
        s = open(path, encoding='utf-8', errors='ignore').read()
    except OSError:
        return []
    out = []
    for t in re.findall(r'<text[^>]*>(.*?)</text>', s, re.S):
        t2 = TAG.sub('', t).strip()
        t2 = re.sub(r'\s+', '', t2)
        if t2:
            out.append(t2)
    return out


def label_variants(label):
    """标签的可匹配形态：原文 + 去括号（（高輪ゲートウェイ）→ 高輪ゲートウェイ）。"""
    v = {label}
    stripped = label.strip('（）()')
    if stripped:
        v.add(stripped)
    return v


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(MINI, 'data', 'track_diagram_index.json'))
    ap.add_argument('--verify', type=int, default=10, help='随机抽样验证站数')
    ap.add_argument('--seed', type=int, default=20261104)
    args = ap.parse_args()

    # ---- 读主站车站数据 ----
    sm = json.load(open(os.path.join(MINI, 'data', 'station_map.stations.json'), encoding='utf-8'))
    stations = sm['stations']                       # key -> {name, lines, ...}
    plain_to_keys = collections.defaultdict(list)   # 去歧义站名 -> [key]
    for k, v in stations.items():
        plain_to_keys[norm_station(v.get('name') or k)].append(k)
    print('stations: %d (plain names %d)' % (len(stations), len(plain_to_keys)))

    # ---- 扫描 SVG 语料 ----
    dirs = {}   # dir(如 jr/east/yamanote) -> {file: labels}
    n_svg = 0
    for root, _d, files in os.walk(CORPUS):
        for f in sorted(files):
            if not f.lower().endswith('.svg'):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, CORPUS)     # jr/east/yamanote/figures/040_01.svg
            if rel.startswith('feature/'):
                continue                            # 专题企划图，非线路配线
            d = os.path.dirname(os.path.dirname(rel))  # jr/east/yamanote
            dirs.setdefault(d, {})[rel] = extract_labels(full)
            n_svg += 1
    print('svg scanned: %d in %d line-dirs' % (n_svg, len(dirs)))

    # ---- Pass 1: 目录 → 线路投票（站点特异度加权 + ≥2 站名支持）----
    # 每站名在每个分块内只计一次（SVG 里同一站名常有多个 <text> 重复）；
    # 同名站（如 神田(東京)/神田(長崎)）按同名数量分摊票权，防止冷门线满票注入。
    dir_votes = {}      # dir -> Counter(line -> 加权得分)
    dir_names = {}      # dir -> line -> set(站名)
    label_cache = {}    # dir -> set(所有标签变体) 供 Pass 3 快速排除
    for d, fmap in dirs.items():
        votes = collections.Counter()
        sup = collections.defaultdict(set)
        allv = set()
        for _f, labels in fmap.items():
            fseen = set()
            for lb in labels:
                for v in label_variants(lb):
                    allv.add(v)
                    if (v, ) in fseen or not plain_to_keys.get(v):
                        continue
                    fseen.add((v,))
                    hits = plain_to_keys[v]
                    for k in hits:
                        ls = stations[k]['lines']
                        w = 1.0 / (max(1, len(ls)) * len(hits))
                        for l in ls:
                            votes[l] += w
                            sup[l].add(v)
        dir_votes[d] = votes
        dir_names[d] = sup
        label_cache[d] = allv
    # 候选线路：≥2 个不同站名支持；全目录无达标者则取分最高者
    cand = {}
    for d, votes in dir_votes.items():
        cs = [l for l, s in votes.most_common() if len(dir_names[d][l]) >= 2]
        if not cs and votes:
            cs = [votes.most_common(1)[0][0]]
        cand[d] = cs
    audit = sorted((d, [(l, round(dir_votes[d][l], 3), len(dir_names[d][l])) for l in cand[d][:3]],
                     sum(dir_votes[d].values())) for d in dirs)
    no_cand = [d for d, c, _s in audit if not c]
    print('dirs with candidates: %d, without: %d %s' % (len(dirs) - len(no_cand), len(no_cand), no_cand[:6]))
    for d, top, _s in audit[:12]:
        print('  vote %-32s %s' % (d, top))

    # ---- Pass 2: 分块定线 ----
    # 规则：在「该分块站名投票支持的线路 ∩ 目录候选线路」中，取目录级加权得分最高者。
    # 目录名即线路权威（jr/east/chuo = 中央本線图）；分块投票只负责「本图确实画到该线」。
    # 原因：主站 lines 为直通运转归属（御茶ノ水/水道橋也挂山手線），东京走廊分块若只按
    # 分块投票会把中央線图判成山手線；以目录得分仲裁后，图签回归目录本线。
    chunk_line = {}     # rel -> line 或 None
    for d, fmap in dirs.items():
        cset = set(cand[d])
        dv = dir_votes[d]
        for f, labels in fmap.items():
            votes = collections.Counter()
            names = collections.defaultdict(set)
            fseen = set()
            for lb in labels:
                for v in label_variants(lb):
                    if (v,) in fseen or not plain_to_keys.get(v):
                        continue
                    fseen.add((v,))
                    hits = plain_to_keys[v]
                    for k in hits:
                        ls = stations[k]['lines']
                        w = 1.0 / (max(1, len(ls)) * len(hits))
                        for l in ls:
                            votes[l] += w
                            names[l].add(v)
            pool = [l for l in votes if l in cset]
            if not pool:
                chunk_line[f] = None
                continue
            chunk_line[f] = max(pool, key=lambda l: (dv[l], votes[l], len(names[l]), l))

    # ---- Pass 3: 车站 → 条目 ----
    index = {}          # key -> [{line, files:[rel...]}]
    match_stations = 0
    for key, sv in stations.items():
        plain = norm_station(sv.get('name') or key)
        slines = sv.get('lines') or []
        if not slines:
            continue
        slineset = set(slines)
        by_line = {}    # line -> [files]
        for d, cs in cand.items():
            if not cs:
                continue
            if plain not in label_cache[d]:
                continue
            for f, labels in dirs[d].items():
                L = chunk_line.get(f)
                if not L or L not in slineset:
                    continue
                vs = set()
                for lb in labels:
                    vs |= label_variants(lb)
                if plain in vs:
                    by_line.setdefault(L, []).append(f)
        if by_line:
            order = {l: i for i, l in enumerate(slines)}
            entries = [{'line': l, 'files': sorted(fs)} for l, fs in by_line.items()]
            entries.sort(key=lambda e: (order.get(e['line'], 999), e['files'][0]))
            index[key] = entries
            match_stations += 1
    print('stations matched: %d / %d' % (match_stations, len(stations)))

    # ---- 输出索引 ----
    doc = {
        'version': 1,
        'source': 'ooep/jr-track@b9d6f70 (downloads/documents, CC BY 4.0 配線略図.net)',
        'base': 'trackdiagrams/',
        'stations': index,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    print('index written: %s (%d bytes, %d stations)' % (args.out, os.path.getsize(args.out), len(index)))

    # ---- 抽样验证 ----
    if args.verify > 0:
        random.seed(args.seed)
        keys = random.sample(sorted(index.keys()), min(args.verify, len(index)))
        print('\n=== VERIFY (%d sampled) ===' % len(keys))
        bad = 0
        for k in keys:
            sv = stations[k]
            print('● %s  lines=%s' % (k, sv['lines']))
            for e in index[k]:
                ok_line = e['line'] in sv['lines']
                plain = norm_station(sv.get('name') or k)
                for f in e['files']:
                    d = os.path.dirname(os.path.dirname(f))
                    labels = dirs[d][f]
                    vs = set()
                    for lb in labels:
                        vs |= label_variants(lb)
                    hit = plain in vs
                    ok_chunk = chunk_line.get(f) == e['line']
                    topc = [(l, len(dir_names[d][l])) for l in cand[d][:3]]
                    if not (ok_line and hit and ok_chunk):
                        bad += 1
                    print('   %-10s %s  line∈站:%s 名∈图:%s 图属线==条线:%s 目录候选:%s'
                          % (e['line'], f, ok_line, hit, ok_chunk, topc))
        print('VERIFY RESULT: %d mismatches' % bad)
        return bad
    return 0


if __name__ == '__main__':
    sys.exit(main())

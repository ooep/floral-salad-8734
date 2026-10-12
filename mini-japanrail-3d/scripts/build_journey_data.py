#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_journey_data.py — 从主页面时刻表数据构建「换乘案内」页面用的紧凑数据（纯静态、无网络）

输入（--data 目录，默认 <repo>/mini-japanrail-3d/data）:
  tmaps.json              {tmap_id: {s_jas:[站...], lines:[线路ja...]}}      停站模板
  trains_wd/sa/su.json    {b,n,T:[{t,r,w,s,i,_}]}                          班次实例(按运行日分组)
  station_key_index.json  {normName: [{k:raw, c:[lon,lat]}]}               站名→坐标(官方几何)
  segments3d.geojson      FeatureCollection {properties:{line,from,to,color,op,kind}}
  lines_map.json          {zh: [ja,...]}                                   线路名映射
  tokkyu.json             (可选) {sh, nm, nmI}                             特急爱称识别

输出（--out 目录，默认 <data>/journey）:
  stations.json   站点节点(同名 3km 聚类): S坐标 N站名 Z中文 D显示名 R引用数
  lines.json      线路目录: [ja, zh, color]
  types.json      列车种别目录: [ja, zh]
  tmaps.json      停站模板: ids[] + T[[S停站节点, L区间线路, K区间km, P时刻pattern, TN爱称]]
  trips_wd.json   班次实例: T[[tmapIdx, patIdx, typeIdx, d0, d0, ...]]  (tmap+pattern+type 分组)
  transfers.json  换乘参数: big 大站集合 + walk 步行换乘边 [a,b,min]
  stats.json      构建统计

设计要点:
  - 时刻表分层: 同 tmap 的全部班次共享「相对时刻结构」(s 串去掉首站发车分 d0 后完全一致),
    tmap 级存 pattern 一次, trip 级仅存 d0 + 所属 pattern 序号。
  - 绝对分钟制: d0 ∈ [0, 1440+], 到站时刻不取模(跨日班次 d0 最大 1494, 终到最大 2040)。
  - 站名消歧: tmaps 的 raw 站名(含括号注记如「大宮(埼玉県)」)在 station_key_index 中
    100% 有精确坐标; 同名(去括号/去「駅」)按 3km 坐标单链聚类为换乘节点。
  - 换乘时间: 同节点 4 分钟, 大站(引用数≥阈值) 6 分钟; 异名近站 <800m 步行
    dist/80 m/min + 2 分钟(不与任何共同 tmap 相连, 避免给有列车直达的站对加噪声)。

用法:
  python3 scripts/build_journey_data.py [--data DIR] [--out DIR] [--big-threshold N]
"""
import argparse, json, math, os, re, sys, time, heapq
from collections import Counter, defaultdict

T0 = time.time()
def log(*a):
    print(f'[{time.time()-T0:7.1f}s]', *a, flush=True)

# ---------------- 基础工具 ----------------
def normName(n):
    """与主页 index.html 的 normName 一致: 去括号注记、ケ→ヶ、去尾部「駅」"""
    n = re.sub(r'\([^)]*\)', '', str(n))
    n = n.replace('ケ', 'ヶ')
    if n.endswith('駅'):
        n = n[:-1]
    return n.strip()

def segKey(n):
    """segments3d 站名归一: normName + 全角ＪＲ→半角JR(tmaps 用半_width, 几何用全角)"""
    n = normName(n)
    if n.startswith('ＪＲ'):
        n = 'JR' + n[2:]
    return n

_NUM_SEN = re.compile(r'^(\d+)号線')
def canonLine(raw):
    """线路名规范化: 「4号線丸ノ内線」→「丸ノ内線」、「5号線(千日前線)」→「千日前線」;
    「1号線・3号線」这类共用段 designation 原样保留; jr/ir 前缀统一为 JR/IR 大写"""
    ln = raw or ''
    if ln[:2].lower() == 'jr':
        ln = 'JR' + ln[2:]
    elif ln[:2].lower() == 'ir':
        ln = 'IR' + ln[2:]
    m = _NUM_SEN.match(ln)
    if m and not ln[m.end():].startswith('・'):
        ln = ln[m.end():]
        if ln.startswith('(') and ln.endswith(')'):
            ln = ln[1:-1]
    return ln

def load_jp2cn():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jp2cn_table.json')
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        return d['JP2CN'], d['KANA2ZH']
    return {}, {}

JP2CN, KANA2ZH = load_jp2cn()

def toZh(s):
    s = str(s)
    for k, v in KANA2ZH.items():
        s = s.replace(k, v)
    mono = []
    while 'モノレール' in s:
        s = s.replace('モノレール', '\ue000', 1)
        mono.append('モノレール')
    out = ''.join(JP2CN.get(ch, ch) for ch in s)
    for m in mono:
        out = out.replace('\ue000', m, 1)
    return out

def geo_km(a, b):
    dx = (b[0] - a[0]) * math.cos((a[1] + b[1]) / 2 * math.pi / 180) * 111.32
    dy = (b[1] - a[1]) * 110.57
    return math.hypot(dx, dy)

def path_km(coords):
    """折线总长(km)"""
    return sum(geo_km(coords[i - 1], coords[i]) for i in range(1, len(coords)))

def graph_path(a, b, adj, max_hops=8, line_set=None, _cache={}):
    """segments3d 站图上 a→b 的距离最短路径(含起端点实体); 返回 (路径, 折线km)。
    Dijkstra(边权=折线km)而非最小跳数: 最小跳数会在直连边被过滤时绕出
    「大崎→品川→川崎→横浜→新川崎→武蔵小杉」38km 的假路径(真实 ~14km)。
    两步搜索: 给定 line_set 时先只在同线路边内搜(跳站区间可能误走并行在来线,
    如 Nozomi 小倉→博多 走了鹿児島本線 67km 而非山陽新幹線 56km), 失败再搜全图。
    max_hops 限制中转数; 不可达返回 (None, 0) (带记忆化)"""
    def dijkstra(allowed):
        dist = {a: 0.0}
        prev = {a: None}
        hop = {a: 0}
        done = set()
        pq = [(0.0, a)]
        while pq:
            d, x = heapq.heappop(pq)
            if x in done:
                continue
            done.add(x)
            if x == b:
                path = [b]
                while path[-1] != a:
                    path.append(prev[path[-1]])
                return path[::-1], d
            if hop[x] >= max_hops:
                continue
            for (y, ln, km) in adj.get(x, ()):
                if allowed is not None and ln not in allowed:
                    continue
                nd = d + km
                if y not in dist or nd < dist[y]:
                    dist[y] = nd
                    prev[y] = x
                    hop[y] = hop[x] + 1
                    heapq.heappush(pq, (nd, y))
        return None, 0.0

    ck = (a, b, tuple(sorted(line_set)) if line_set else None)
    if ck in _cache:
        return _cache[ck]
    r = (None, 0.0)
    if a in adj and b in adj:
        if line_set:
            r = dijkstra(line_set)
        if r[0] is None:
            r = dijkstra(None)
    _cache[ck] = r
    return r

# ---------------- 新幹線公式実キロ表 ----------------
# 用途: 跳站区间与直连区间统一取官方里程。
#  ① segments3d 的新幹線几何是「站间长直段」(如山陽新幹線仅 8 条 feature, 岡山→新尾道 73.98km),
#     中间站(新倉敷/福山/徳山等)没有独立新幹線边, 跳站区间只能绕走并行在来线(+20% 误差);
#  ② 直连区间折线估计有 ±3% 噪声(品川→新横浜 18.9 vs 官方 18.76)。
# 実キロ=实际轨道距离; Yahoo! 案内显示的営業キロ在東海道新幹線略大(東京-新大阪 515.4→552.6),
# 本站几何估计同基准于実キロ, 混用不矛盾。来源: tanukiacademy.com キロ程附录(2024年开业区間)。
SHINKANSEN_KM = {
    '東海道新幹線': [('東京', 0.00), ('品川', 6.78), ('新横浜', 25.54), ('小田原', 76.65),
                 ('熱海', 95.43), ('三島', 111.30), ('新富士', 135.00), ('静岡', 167.44),
                 ('掛川', 211.30), ('浜松', 238.92), ('豊橋', 274.17), ('三河安城', 312.82),
                 ('名古屋', 342.02), ('岐阜羽島', 367.12), ('米原', 408.23), ('京都', 476.31),
                 ('新大阪', 515.35)],
    '山陽新幹線': [('新大阪', 515.35), ('新神戸', 548.00), ('西明石', 570.21), ('姫路', 601.28),
                ('相生', 621.33), ('岡山', 676.34), ('新倉敷', 702.14), ('福山', 733.07),
                ('新尾道', 750.45), ('三原', 761.00), ('東広島', 791.94), ('広島', 821.22),
                ('新岩国', 865.38), ('徳山', 903.54), ('新山口', 944.55), ('厚狭', 968.66),
                ('新下関', 992.45), ('小倉', 1013.19), ('博多', 1069.10)],
    '九州新幹線': [('博多', 1069.10), ('博多南', 1077.62), ('新鳥栖', 1095.40), ('久留米', 1101.10),
                ('筑後船小屋', 1116.98), ('新大牟田', 1128.87), ('新玉名', 1145.39), ('熊本', 1167.28),
                ('新八代', 1199.07), ('新水俣', 1241.92), ('出水', 1257.92), ('川内', 1290.65),
                ('鹿児島中央', 1325.92)],
    '東北新幹線': [('東京', 0.00), ('上野', 3.57), ('大宮', 31.33), ('小山', 80.27),
                ('宇都宮', 109.02), ('那須塩原', 152.37), ('新白河', 178.43), ('郡山', 213.94),
                ('福島', 255.14), ('白石蔵王', 286.20), ('仙台', 325.39), ('古川', 363.84),
                ('くりこま高原', 385.66), ('一ノ関', 406.26), ('水沢江刺', 431.31), ('北上', 448.61),
                ('新花巻', 463.14), ('盛岡', 496.48), ('いわて沼宮内', 527.62), ('二戸', 562.17),
                ('八戸', 593.05), ('七戸十和田', 629.22), ('新青森', 674.87)],
    '北海道新幹線': [('新青森', 674.87), ('奥津軽いまべつ', 713.38), ('木古内', 788.20),
                 ('新函館北斗', 823.66)],
    '上越新幹線': [('東京', 0.00), ('上野', 3.57), ('大宮', 31.33), ('熊谷', 67.96),
                ('本庄早稲田', 89.06), ('高崎', 108.65), ('上毛高原', 150.46), ('越後湯沢', 182.70),
                ('浦佐', 212.29), ('長岡', 245.16), ('燕三条', 268.71), ('新潟', 300.84)],
    '北陸新幹線': [('東京', 0.00), ('上野', 3.57), ('大宮', 31.33), ('高崎', 108.64),
                ('安中榛名', 127.15), ('軽井沢', 150.45), ('佐久平', 168.04), ('上田', 192.84),
                ('長野', 226.04), ('飯山', 255.97), ('上越妙高', 285.53), ('糸魚川', 322.52),
                ('黒部宇奈月温泉', 361.78), ('富山', 395.56), ('新高岡', 414.45), ('金沢', 454.07)],
}
# (站, 线路) -> km; 查表: 同线两站里程差(方向无关)
SK_LOOKUP = {}
for _ln, _stops in SHINKANSEN_KM.items():
    for _st, _km in _stops:
        SK_LOOKUP[(_st, _ln)] = _km


def sk_section_km(name_a, name_b, lines_ja):
    """两端点若同属某条新幹線且该线在 tmap 线路表中 → (线路, 区间km); 否则 None"""
    for ln in lines_ja:
        ka = SK_LOOKUP.get((name_a, ln))
        kb = SK_LOOKUP.get((name_b, ln))
        if ka is not None and kb is not None and abs(kb - ka) > 0.05:
            return ln, abs(kb - ka)
    return None

# ---------------- 列车种别显示名(供 types.json) ----------------
TYPE2ZH = {
    '普': '普通', '各': '各停', '特': '特急', '快': '快速', '急': '急行', '準': '準急',
    '区': '区間', '通': '通勤', '直': '直行', '空': '机场快速', '新': '新快速', '寝': '寝台',
    '臨': '临时', '関': '特急', '紀': '特急', '中': '特急', '丹': '特急', '京': '特急',
    '川': '特急', 'Ｔ': '特急', 'Ｓ': '特急', 'Ｎ': '特急', 'ホ': 'Liner', '拝': 'Liner',
    'ラ': 'Liner', 'ミ': 'ミュースカイ', 'ア': '特急', 'エ': '特急', 'フ': '特急',
    '富': '特急', '九': '特急', '青': '青', '大': '大', 'み': 'み',
}
SH2ZH = {  # 新干线英文名 → 中文(仅用于检索提示, 显示保留日文名)
    'Nozomi': '希望', 'Hikari': '光', 'Kodama': '回声', 'Sakura': '樱', 'Tsubame': '燕',
    'Mizuho': '瑞穗', 'Hayabusa': '隼', 'Komachi': '小町', 'Yamabiko': '山彦',
    'Nasuno': '那须野', 'Toki': '朱鹭', 'Tanigawa': '谷川', 'Kagayaki': '光辉',
    'Hakutaka': '白鹰', 'Asama': '浅间', 'Tsurugi': '剑', 'Hayate': '疾风',
    'Kamome': '海鸥', 'Tsubasa': '翼', 'Sonic': '音速',
}
# 主页 index.html 的 tokkyu 识别常量(与之一致)
TOKKYU_ICONS = set(['特', '関', '紀', '中', '丹', '寝', '京', 'ミ', 'フ', '富', '九', '川',
                    'Ｔ', 'Ｓ', 'Ｎ', 'ホ', '拝', 'ラ', 'ア', 'エ', '空'])
ICON_NAME = {
    '関': 'はるか', '紀': 'くろしお', '丹': 'こうのとり', 'ミ': 'ミュースカイ',
    'フ': 'フジサン特急', '富': 'フジサン特急', '九': '九州横断特急', '京': '京王特急',
    '川': '川越特急', 'Ｔ': '東武特急', 'Ｓ': '直通特急', 'Ｎ': '西鉄特急', 'ホ': 'ホームライナー',
    '拝': '拝島ライナー', 'ア': 'アクセス特急', 'エ': 'アクセス特急', '空': '空港快速',
    '寝': '寝台特急', '中': '中央線特急', 'ラ': 'ライナー',
}

# ---------------- 1. 加载输入 ----------------
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=os.path.join(os.path.dirname(here), 'mini-japanrail-3d', 'data'))
    ap.add_argument('--out', default='')
    ap.add_argument('--big-threshold', type=int, default=150,
                    help='大站判定: tmap 停站引用数 ≥ 该值 → 同节点换乘 6 分钟(否则 4 分钟)')
    ap.add_argument('--walk-max-m', type=int, default=800)
    ap.add_argument('--walk-max-neighbors', type=int, default=3)
    args = ap.parse_args()
    data = os.path.abspath(args.data)
    out = os.path.abspath(args.out) if args.out else os.path.join(data, 'journey')
    os.makedirs(out, exist_ok=True)

    def jload(name):
        p = os.path.join(data, name)
        if not os.path.exists(p):
            log(f'[warn] 缺少输入 {name} (将降级)')
            return None
        return json.load(open(p, encoding='utf-8'))

    tmaps = jload('tmaps.json') or {}
    trains = {}
    for day in ('wd', 'sa', 'su'):
        d = jload(f'trains_{day}.json')
        if d:
            trains[day] = d['T']
    ski = jload('station_key_index.json') or {}
    seg_fc = jload('segments3d.geojson')
    lines_map = jload('lines_map.json') or {}
    tokkyu = jload('tokkyu.json')

    log(f'输入: tmaps={len(tmaps)} ' +
        ' '.join(f'trains_{d}={len(t)}' for d, t in trains.items()) +
        f' station_key_index={len(ski)} segments={len(seg_fc["features"]) if seg_fc else 0}')

    # ---------------- 2. 站点节点(同名 3km 聚类) ----------------
    # raw -> coord(全部精确匹配; 理论覆盖率 100%)
    raw_coord = {}
    for norm, lst in ski.items():
        for c in lst:
            raw_coord[c['k']] = c['c']
    # tmap 停站引用(去重后的 raw 集合)
    raw_refs = Counter()
    tmap_stops_raw = {}
    for tid, v in tmaps.items():
        s = v['s_jas']
        tmap_stops_raw[tid] = s
        for r in s:
            raw_refs[r] += 1
    missing_raw = [r for r in raw_refs if r not in raw_coord]
    if missing_raw:
        log(f'[warn] {len(missing_raw)} 个站名无坐标(仍可换乘, 地图/聚类缺失): {missing_raw[:5]}')
    # 按 normName 分组 → 3km 单链聚类
    by_norm = defaultdict(list)
    for r in raw_refs:
        if r in raw_coord:
            by_norm[normName(r)].append((r, raw_coord[r]))
    nodes = []            # {norm, raw_repr, coord, raws:set, refs}
    raw2node = {}
    for norm, obs in by_norm.items():
        clusters = []     # [{raws:set, pts:[coord]}]
        for r, c in obs:
            placed = False
            for cl in clusters:
                if any(geo_km(c, p) < 3.0 for p in cl['pts']):
                    cl['raws'].add(r); cl['pts'].append(c); placed = True; break
            if not placed:
                clusters.append({'raws': {r}, 'pts': [c]})
        # 质心合并(迭代到稳定): 防单链把 6km 外的站串进来
        changed = True
        while changed:
            changed = False
            for i in range(len(clusters)):
                if clusters[i] is None:
                    continue
                ci = (sum(p[0] for p in clusters[i]['pts']) / len(clusters[i]['pts']),
                      sum(p[1] for p in clusters[i]['pts']) / len(clusters[i]['pts']))
                for j in range(i + 1, len(clusters)):
                    if clusters[j] is None:
                        continue
                    cj = (sum(p[0] for p in clusters[j]['pts']) / len(clusters[j]['pts']),
                          sum(p[1] for p in clusters[j]['pts']) / len(clusters[j]['pts']))
                    if geo_km(ci, cj) < 3.0:
                        clusters[i]['raws'] |= clusters[j]['raws']
                        clusters[i]['pts'].extend(clusters[j]['pts'])
                        clusters[j] = None; changed = True
            clusters = [c for c in clusters if c]
        for cl in clusters:
            lon = sum(p[0] for p in cl['pts']) / len(cl['pts'])
            lat = sum(p[1] for p in cl['pts']) / len(cl['pts'])
            refs = sum(raw_refs[r] for r in cl['raws'])
            nodes.append({'norm': norm, 'raws': cl['raws'], 'coord': [lon, lat], 'refs': refs})
            for r in cl['raws']:
                raw2node[r] = len(nodes) - 1
    # 同名多节点 → 显示名加括号注记消歧
    norm_count = Counter(n['norm'] for n in nodes)
    node_display = []
    for n in nodes:
        d = n['norm']
        if norm_count[n['norm']] > 1:
            br = ''
            for r in sorted(n['raws']):   # sorted: 与 hash 种子无关, 保证输出确定性
                m = re.search(r'\(([^)]*)\)', r)
                if m:
                    br = m.group(1); break
            d = f"{n['norm']}({br})" if br else n['norm']
        node_display.append(d)
    # 搜索别名: 运营商前缀剥离(大阪難波→難波) + 假名→汉字(なんば→難波) + 中文形式
    OP_PREFIX = ['JR', '大阪', '名鉄', '京成', '東武', '西武', '小田急', '京王', '近鉄',
                 '阪急', '阪神', '南海', '京阪', '都営', '東京メトロ', '横浜市営', '札幌市営',
                 '仙台市営', '京都市営', '名古屋市営', '福岡市地下鉄', 'OsakaMetro']
    KANA2KANJI = {'なんば': '難波', 'あびこ': '我孫子', 'なかもず': '中百舌鳥', 'しんざ': '新座',
                  'つくば': '筑波', 'いわき': '磐城', 'うきは': '浮羽', 'くびき': '頚城',
                  'あぶくま': '阿武隈', 'しきぶ': '式部', 'つきのわ': '月の輪', 'えびの': '蝦野'}
    node_alias = []
    for n in nodes:
        alts = set()
        nm = n['norm']
        for p in OP_PREFIX:
            if nm.startswith(p) and len(nm) - len(p) >= 2:
                alts.add(nm[len(p):])
        if nm in KANA2KANJI:
            alts.add(KANA2KANJI[nm])
        node_alias.append(sorted(alts))
    log(f'站点节点: raw={len(raw_refs)} → nodes={len(nodes)} (同名拆分 {sum(1 for c in norm_count.values() if c > 1)} 组, '
        f'带别名 {sum(1 for a in node_alias if a)} 个)')

    # ---------------- 3. 线路目录 ----------------
    line_names = set()
    for tid, v in tmaps.items():
        for ln in v.get('lines', []):
            if ln:
                line_names.add(canonLine(ln))
    seg_color = defaultdict(Counter)
    seg_by_pair = defaultdict(list)   # (eA,eB) sorted -> [feature]  eA/eB 为实体下标(节点为前 N 个)
    seg_adj = defaultdict(list)       # 实体 -> [(实体, line, km)]  跨站区间 BFS 用(仅可信边)
    n_untrusted = 0
    if seg_fc:
        # ---- 站实体体系: 0..N-1 为 tmap 停站节点; 之后为 segments3d 几何独有站(BFS 中间跳点用) ----
        # 同名站在不同城市(大森(東京都)/大森(静岡県))必须靠几何端点就近解析, 不能按名字建图,
        # 否则 BFS 会把东京的大森和静冈的大森连成一片(曾出现 大森→新所原 3km 的假边)
        ent_coord = [n['coord'] for n in nodes]
        ent_name = [n['norm'] for n in nodes]
        name2ent = defaultdict(list)
        CELL_E = 0.05
        ent_grid = defaultdict(list)
        for i, n in enumerate(nodes):
            name2ent[n['norm']].append(i)
            ent_grid[(int(n['coord'][0] / CELL_E), int(n['coord'][1] / CELL_E))].append(i)

        def resolve_ent(name, pt):
            """按几何端点就近解析到已有实体(5km 内); 否则新建几何独有实体"""
            cands = name2ent.get(name, [])
            if cands:
                best, bd = None, 1e9
                for e in cands:
                    d = geo_km(pt, ent_coord[e])
                    if d < bd:
                        best, bd = e, d
                if bd < 5.0:
                    return best
            return None

        n_geo_only = 0
        for f in seg_fc['features']:
            p = f['properties']
            ln = canonLine(p.get('line') or '')
            if ln:
                line_names.add(ln)
                if p.get('color'):
                    seg_color[ln][p['color']] += 1
            na, nb = segKey(p.get('from') or ''), segKey(p.get('to') or '')
            if not (na and nb):
                continue
            g = f['geometry']
            co = g['coordinates']
            pts = []
            for q in (co if g['type'] == 'MultiLineString' else [co]):
                pts.extend(q)
            if len(pts) < 2:
                continue
            km = path_km(pts)
            # 端点就近解析(几何方向: from=首点, to=末点)
            ea = resolve_ent(na, pts[0])
            if ea is None:
                ea = len(ent_coord)
                ent_coord.append(list(pts[0])); ent_name.append(na)
                name2ent[na].append(ea)
                ent_grid[(int(pts[0][0] / CELL_E), int(pts[0][1] / CELL_E))].append(ea)
                n_geo_only += 1
            eb = resolve_ent(nb, pts[-1])
            if eb is None:
                eb = len(ent_coord)
                ent_coord.append(list(pts[-1])); ent_name.append(nb)
                name2ent[nb].append(eb)
                ent_grid[(int(pts[-1][0] / CELL_E), int(pts[-1][1] / CELL_E))].append(eb)
                n_geo_only += 1
            if ea == eb:
                continue
            # 可信度: 铁路几何必不短于两端点直线距离。长区间容忍 0.85(并行线/取齐误差),
            # 短区间容忍 0.80(城市轨道折线简化误差可达 20%: 大崎→西大井 1.72km vs 直线 2.12km,
            # 该边为品鶴線真实边, 误杀会导致 BFS 绕出 38km 假路径)
            straight = geo_km(ent_coord[ea], ent_coord[eb])
            tol = 0.80 if straight < 8.0 else 0.85
            trusted = (straight < 0.5) or (km >= straight * tol)
            if not trusted:
                n_untrusted += 1
            seg_by_pair[tuple(sorted((ea, eb)))].append(f)
            if trusted:
                seg_adj[ea].append((eb, ln, km))
                seg_adj[eb].append((ea, ln, km))
        log(f'segments3d 实体解析: {len(ent_coord)} 实体(节点 {len(nodes)} + 几何独有 {n_geo_only}), '
            f'可信边过滤 {n_untrusted}/{len(seg_fc["features"])}')
    # zh 名: lines_map 反查优先, 其次 toZh
    ja2zh = {}
    for zh, jas in lines_map.items():
        for ja in jas:
            if ja not in ja2zh or len(zh) < len(ja2zh[ja]):
                ja2zh[ja] = zh
    lines_list = sorted(line_names)
    line_idx = {ln: i for i, ln in enumerate(lines_list)}
    lines_out = []
    for ln in lines_list:
        zh = ja2zh.get(ln) or toZh(ln)
        color = seg_color[ln].most_common(1)[0][0] if seg_color.get(ln) else '#8b94a3'
        lines_out.append([ln, zh, color])
    log(f'线路目录: {len(lines_out)} 条 (segments3d 索引 {len(seg_by_pair)} 站对)')

    # ---------------- 4. tmap 结构 ----------------
    # 4a. 班次 → (tmap, pattern, type) 分组; pattern 全局去重
    type_vocab = {}
    def type_idx(ic):
        if ic not in type_vocab:
            type_vocab[ic] = len(type_vocab)
        return type_vocab[ic]
    tmap_patterns = defaultdict(Counter)      # tid -> Counter(pattern_str)
    day_groups = {}                           # day -> {(tid,pat,type): [d0]}
    day_trip_count = {}
    for day, T in trains.items():
        groups = defaultdict(list)
        n = 0
        for r in T:
            tid = str(r['t'])
            if tid not in tmaps:
                continue
            s = r['s'].split(',', 1)
            pat = s[1] if len(s) > 1 else ''
            d0 = int(s[0])
            tmap_patterns[tid][pat] += 1
            groups[(tid, pat, r['i'])].append(d0)
            n += 1
        day_groups[day] = groups
        day_trip_count[day] = n
        log(f'  {day}: 有效班次 {n}, (tmap,pattern,type) 组 {len(groups)}')

    # 4b. 逐 tmap 构建 S/L/K/P/TN
    tmap_ids = []
    tmap_out = []
    tmap_index = {}
    unmatched_sections = Counter()
    km_fallback = 0
    for tid in sorted(tmap_patterns, key=lambda x: -sum(tmap_patterns[x].values())):
        s_jas = tmap_stops_raw[tid]
        N = len(s_jas)
        if N < 2:
            continue
        lines_ja = [canonLine(ln) for ln in tmaps[tid].get('lines', []) if ln]
        lines_raw = [ln for ln in tmaps[tid].get('lines', []) if ln]
        S = []
        for r in s_jas:
            ni = raw2node.get(r)
            if ni is None:
                ni = -1
            S.append(ni)
        if any(x < 0 for x in S):
            log(f'[warn] tmap {tid} 有未映射停站, 跳过')
            continue
        # 区间线路 + km
        L, K = [], []
        for i in range(1, N):
            ea, eb = S[i - 1], S[i]   # 停站节点即实体下标(实体 0..N-1)
            li, km10 = -2, None
            # 新幹線官方実キロ优先(修跳站区间绕走并行在来线 + 消直连区间几何噪声)
            sk = sk_section_km(nodes[ea]['norm'], nodes[eb]['norm'], lines_ja)
            if sk is not None:
                li = line_idx.get(sk[0], -1)
                km10 = int(round(sk[1] * 10))
            feats = seg_by_pair.get(tuple(sorted((ea, eb))), []) if sk is None else None
            if feats:
                # 直连区间: 优先 tmap 归属线路, 否则取该站对最常见线路
                pref = [f for f in feats if canonLine(f['properties'].get('line') or '') in lines_ja]
                pool = pref or feats
                cnt = Counter(canonLine(f['properties'].get('line') or '') for f in pool)
                best_ln = cnt.most_common(1)[0][0]
                grp = [f for f in pool if canonLine(f['properties'].get('line') or '') == best_ln]
                li = line_idx.get(best_ln, -1)
                # 同站对同线路可能有多条并列几何(完整线形 + 截断残桩, 如 品川→川崎 11.8km/0.9km):
                # 只收自洽者(折线 ≥ 自身端点直线 × 容差), 其中取折线最长(残桩最短, 完整线形通常最长)
                cand_km = []
                for f in grp:
                    g = f['geometry']
                    co = g['coordinates']
                    pts = []
                    for q in (co if g['type'] == 'MultiLineString' else [co]):
                        pts.extend(q)
                    if len(pts) < 2:
                        continue
                    k_ = path_km(pts)
                    st_ = geo_km(pts[0], pts[-1])
                    if st_ >= 0.5 and k_ < st_ * (0.80 if st_ < 8.0 else 0.85):
                        continue
                    cand_km.append(k_)
                if cand_km:
                    km10 = int(round(max(cand_km) * 10))
            elif sk is None:
                # 跨站区间(跳站): 在实体站图上按距离最短路径, 逐跳选边
                path, hop_km = graph_path(ea, eb, seg_adj, max_hops=8,
                                          line_set=set(lines_ja) if lines_ja else None)
                if path:
                    # 绕行检测: 折线总长远超两端点直线(×1.8+5km)说明图上有假连通, 回退直线估计
                    straight = geo_km(nodes[ea]['coord'], nodes[eb]['coord'])
                    if hop_km > straight * 1.8 + 5.0:
                        path = None
                    else:
                        hop_lines = []
                        for x, y in zip(path, path[1:]):
                            edges = seg_adj.get(x, [])
                            cand = [e for e in edges if e[0] == y]
                            if not cand:
                                hop_lines = []
                                break
                            pref = [e for e in cand if e[1] in lines_ja] or cand
                            cnt = Counter(e[1] for e in pref)
                            ln = cnt.most_common(1)[0][0]
                            hop_lines.append(ln)
                        if hop_lines:
                            cnt = Counter(hop_lines)
                            pref = [ln for ln in cnt if ln in lines_ja]
                            best_ln = (Counter({ln: cnt[ln] for ln in pref}).most_common(1)[0][0]
                                       if pref else cnt.most_common(1)[0][0])
                            li = line_idx.get(best_ln, -1)
                            km10 = int(round(hop_km * 10))
            if li == -2 and km10 is None:
                unmatched_sections[tid] += 1
                if len(lines_ja) == 1:
                    li = line_idx.get(lines_ja[0], -1)
                # 否则留 -2 由邻居继承
                km_fallback += 1
            elif li == -2:
                if len(lines_ja) == 1:
                    li = line_idx.get(lines_ja[0], -1)
            if km10 is None:
                km10 = int(round(geo_km(nodes[S[i - 1]]['coord'], nodes[S[i]]['coord']) * 1.25 * 10))
            L.append(li)
            K.append(km10)
        for i in range(len(L)):
            if L[i] == -2:
                for j in range(i - 1, -1, -1):
                    if L[j] >= 0:
                        L[i] = L[j]; break
        for i in range(len(L) - 1, -1, -1):
            if L[i] == -2:
                for j in range(i + 1, len(L)):
                    if L[j] >= 0:
                        L[i] = L[j]; break
        L = [x if x >= 0 else -1 for x in L]
        # patterns: 按班次频次降序(索引 0 = 基准 pattern)
        pats = [p for p, _ in tmap_patterns[tid].most_common()]
        pat_idx = {p: i for i, p in enumerate(pats)}
        # 特急爱称(与主页 tripName 同规则; 按 icon 解析)
        TN = None
        if tokkyu:
            icons = set()
            for day, groups in day_groups.items():
                for (t2, p2, ic) in groups:
                    if t2 == tid:
                        icons.add(ic)
            names = {}
            for ic in icons:
                if tokkyu.get('sh', {}).get(ic):
                    names[ic] = tokkyu['sh'][ic]
                elif ic in TOKKYU_ICONS:
                    o, d2 = normName(s_jas[0]), normName(s_jas[-1])
                    sig = o + '>' + d2 + '|' + '|'.join(sorted(normName(x) for x in lines_raw))
                    nm = (tokkyu.get('nmI', {}).get(sig + '|' + ic)
                          or tokkyu.get('nm', {}).get(sig) or ICON_NAME.get(ic))
                    if nm:
                        names[ic] = nm
            if names:
                TN = names
        tmap_index[tid] = len(tmap_out)
        tmap_ids.append(tid)
        tmap_out.append([S, L, K, pats, TN])
    log(f'tmap 结构: {len(tmap_out)} 个 (区间线路未匹配 {sum(unmatched_sections.values())} 处/km 回退 {km_fallback} 处)')

    # ---------------- 5. 换乘参数 ----------------
    refs_arr = [n['refs'] for n in nodes]
    big = [i for i, r in enumerate(refs_arr) if r >= args.big_threshold]
    big_set = set(big)
    log(f'大站(引用≥{args.big_threshold}): {len(big)} 个: ' +
        ','.join(node_display[i] for i in sorted(big, key=lambda i: -refs_arr[i])[:40]))
    # 步行边: 网格近邻搜索
    node_tmaps = defaultdict(set)   # node -> tmap idx 集合(用于排除有列车直达的站对)
    for ti, (S, L, K, P, TN) in enumerate(tmap_out):
        for s in set(S):
            node_tmaps[s].add(ti)
    CELL = 0.01
    grid = defaultdict(list)
    for i, n in enumerate(nodes):
        grid[(int(n['coord'][0] / CELL), int(n['coord'][1] / CELL))].append(i)
    walk = []
    seen_pairs = set()
    for i, n in enumerate(nodes):
        gx, gy = int(n['coord'][0] / CELL), int(n['coord'][1] / CELL)
        cands = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    if nodes[j]['norm'] == n['norm']:
                        continue
                    d = geo_km(n['coord'], nodes[j]['coord'])
                    if d < args.walk_max_m / 1000.0:
                        cands.append((d, j))
        cands.sort()
        for d, j in cands[:args.walk_max_neighbors]:
            if (i, j) in seen_pairs:
                continue
            if node_tmaps.get(i) and node_tmaps.get(j) and (node_tmaps[i] & node_tmaps[j]):
                continue  # 有列车直达, 不需要步行边
            seen_pairs.add((i, j))
            walk.append([i, j, int(round(d * 1000 / 80)) + 2])
    walk.sort()
    log(f'步行换乘边: {len(walk)} 条 (<{args.walk_max_m}m)')

    # ---------------- 6. 写出 -------------    json.dump 会做 ensure_ascii=False + 紧凑
    def dump(name, obj):
        p = os.path.join(out, name)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        return os.path.getsize(p)

    stations_obj = {
        'v': 1,
        'S': [[round(n['coord'][0], 6), round(n['coord'][1], 6)] for n in nodes],
        'N': [n['norm'] for n in nodes],
        'Z': [toZh(n['norm']) for n in nodes],
        'D': node_display,
        'R': refs_arr,
        'X': [[i, node_alias[i] + [toZh(a) for a in node_alias[i]]]
              for i in range(len(nodes)) if node_alias[i]],
    }
    sz_stations = dump('stations.json', stations_obj)
    sz_lines = dump('lines.json', {'v': 1, 'L': lines_out})
    tmaps_obj = {'v': 1, 'ids': tmap_ids, 'T': tmap_out}
    sz_tmaps = dump('tmaps.json', tmaps_obj)
    sz_trips = {}
    for day in ('wd', 'sa', 'su'):
        groups = day_groups.get(day, {})
        T = []
        for (tid, pat, ic), d0s in groups.items():
            ti = tmap_index.get(tid)
            if ti is None:
                continue
            T.append([ti, {p: i for i, p in enumerate(tmap_out[ti][3])}[pat], type_idx(ic)] + sorted(d0s))
        T.sort(key=lambda x: (x[0], x[3]))
        sz_trips[day] = dump(f'trips_{day}.json', {'v': 1, 'T': T})
    # types.json 必须在 trips 之后写(词表在 trips 循环中才填满)
    types_out = [[ic, TYPE2ZH.get(ic, SH2ZH.get(ic, ic))] for ic in sorted(type_vocab, key=lambda x: type_vocab[x])]
    sz_types = dump('types.json', {'v': 1, 'T': types_out})
    sz_tr = dump('transfers.json', {'v': 1, 'big': big, 'walk': walk,
                                    'bigMin': 6, 'sameMin': 4})
    stats = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'input': {'tmaps': len(tmaps), **{f'trains_{d}': day_trip_count.get(d, 0) for d in trains}},
        'nodes': len(nodes), 'raw_names': len(raw_refs),
        'same_name_split_groups': sum(1 for c in norm_count.values() if c > 1),
        'lines': len(lines_out), 'types': len(type_vocab),
        'tmaps_out': len(tmap_out),
        'patterns_total': sum(len(t[3]) for t in tmap_out),
        'unmatched_sections': sum(unmatched_sections.values()),
        'untrusted_segments': n_untrusted,
        'km_fallback_sections': km_fallback,
        'big_stations': len(big), 'walk_edges': len(walk),
        'sizes_kb': {'stations': round(sz_stations / 1024), 'lines': round(sz_lines / 1024),
                     'types': round(sz_types / 1024), 'tmaps': round(sz_tmaps / 1024),
                     **{f'trips_{d}': round(v / 1024) for d, v in sz_trips.items()},
                     'transfers': round(sz_tr / 1024)},
        'total_kb': round((sz_stations + sz_lines + sz_types + sz_tmaps + sum(sz_trips.values()) + sz_tr) / 1024),
    }
    dump('stats.json', stats)
    log('完成. ' + json.dumps({k: stats[k] for k in ('nodes', 'tmaps_out', 'patterns_total', 'big_stations', 'walk_edges', 'total_kb')}, ensure_ascii=False))
    log('输出目录: ' + out)

if __name__ == '__main__':
    main()

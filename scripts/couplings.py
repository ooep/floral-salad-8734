#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""併结检测（构建期）—— 固定服务目录 + 时刻对齐，结果固化进 trains_*.json 的 "c" 字段。

设计（2026-10-29 根治版）：
  - 浏览器不再做任何启发式併结扫描；页面上出现的每一对併结列车都来自本模块。
    时刻表刷新后不会因站序/记录形状变化而在前端悄悄错配或漏配。
  - EVENTS 列出所有真实存在的併结服务（2026-10 联网逐组核实），每条给出併结站、
    双方判定、窗口锚点（共同始发/终到站）与时刻容差。新增/废止併结只改这张表。
  - 判定只依赖两件事：共同端点的连续站序（允许中间跳站, LCS）+ 共享段逐站到发
    时刻对齐。记录被截短、绕环、同班次重复录入都不影响：配不上宁可不标。
  - 每条记录物理上只有一个併结伙伴：候选按偏差升序全局贪心一对一。
  - scan_uncatalogued() 在构建日志里报告“像併结但不在目录内”的强候选；时刻表
    新增併结服务时能第一时间看见，而不是等用户发现。

"c" 条目：{"p": 伙伴train_id, "k": "s"|"j", "sp": 併结站(normName),
  "t0"/"t1": 併结窗口(分钟), "nm": 伙伴爱称}
  k="s": 共享前缀（同起点方向, 列车在 sp 分割）
  k="j": 共享后缀（异起点方向, 列车在 sp 併结）

判定指标：共享站「到达」时刻差（分割段含併结站到达；併结段取併结站发车 +
后续各站到达, 共同终点站的到站记法差排除）。运行窗取双方 w0/w1 交集。
"""
import re

# 与页面 GRADE / 车种表一致；仅用于盲区扫描，不作为判定白名单
COUPLE_CLASSES = {
    "Hayabusa", "Komachi", "Yamabiko", "Tsubasa", "Toki", "Tanigawa",
    "Sakura", "Tsubame", "特", "新", "関", "紀", "寝",
}
_SCAN_CLASSES = (COUPLE_CLASSES - {"新"}) | {
    "Nozomi", "Hikari", "Kodama", "Mizuho", "Kagayaki", "Hakutaka", "Asama",
    "Nasuno", "Hayate", "Tsurugi", "Kamome",
}

_TOKKYU_ICONS = set("関紀中丹寝京ミフ富九川ＴＳＮホ拝ラアエ空特")
_ICON_NAME = {
    "関": "関空快速", "紀": "紀州路快速", "丹": "こうのとり", "ミ": "ミュースカイ",
    "フ": "フジサン特急", "富": "フジサン特急", "九": "九州横断特急", "京": "京王特急",
    "川": "川越特急", "Ｔ": "東武特急", "Ｓ": "直通特急", "Ｎ": "西鉄特急",
    "ホ": "ホームライナー", "拝": "拝島ライナー", "ア": "アクセス特急",
    "エ": "アクセス特急", "空": "関空快速", "寝": "寝台特急", "中": "中央線特急",
    "ラ": "ライナー", "特": "特急",
}


def norm_name(n):
    return re.sub(r"\([^)]*\)", "", str(n)).replace("ヶ", "ヶ").replace("駅", "").strip()


def trip_name(icon, jas, lines, tokkyu):
    """与页面 tripName 一致（tokkyu: {"sh","nm","nmI"}）。"""
    if tokkyu and tokkyu.get("sh", {}).get(icon):
        return tokkyu["sh"][icon]
    if icon not in _TOKKYU_ICONS:
        return None
    sig = norm_name(jas[0]) + ">" + norm_name(jas[-1]) + "|" + \
        "|".join(sorted(norm_name(l) for l in (lines or [])))
    if tokkyu:
        v = tokkyu.get("nmI", {}).get(sig + "|" + icon) or tokkyu.get("nm", {}).get(sig)
        if v:
            return v
    return _ICON_NAME.get(icon)


def couple_name(icon, jas, lines, tokkyu):
    """伙伴展示名：优先线路签名爱称（みどり/しおかぜ/いしづち 等 icon=特），
    再退回车种通用名。"""
    n = trip_name(icon, jas, lines, tokkyu)
    if n:
        return n
    if tokkyu:
        sig = norm_name(jas[0]) + ">" + norm_name(jas[-1]) + "|" + \
            "|".join(sorted(norm_name(l) for l in (lines or [])))
        v = tokkyu.get("nmI", {}).get(sig + "|" + icon) or tokkyu.get("nm", {}).get(sig)
        if v:
            return v
    return _ICON_NAME.get(icon)


def build_trip(rec, tm, tokkyu):
    """轻量班次对象。s 解码：dep0, run1, dwell1, run2, ...（长度 2N-2）。"""
    jas = tm.get("s_jas") or []
    N = len(jas)
    if N < 2:
        return None
    s = [int(x) for x in rec["s"].split(",")]
    if len(s) != 2 * N - 2:
        return None
    dep = [0] * N
    arr = [0] * N
    dep[0] = arr[0] = s[0]
    for i in range(1, N):
        arr[i] = dep[i - 1] + s[2 * i - 1]
        dep[i] = arr[i] + (s[2 * i] if 2 * i < len(s) else 0)
    w0, w1 = [int(x) for x in rec["w"].split(",")]
    return {
        "tid": rec["_"], "t": rec["t"], "i": rec.get("i", ""), "N": N,
        "jasN": [norm_name(x) for x in jas], "dep": dep, "arr": arr,
        "w0": w0, "w1": w1,
        "nm": trip_name(rec.get("i", ""), jas, tm.get("lines") or [], tokkyu),
        "cnm": couple_name(rec.get("i", ""), jas, tm.get("lines") or [], tokkyu),
    }


def _lcs_pairs(a, b):
    """最长公共子序列的站序配对（允许中间跳站：郡山通过等）。
    返回 [(i, j), ...] 按站序递增。"""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, nxt = dp[i], dp[i + 1]
        ai = a[i]
        for j in range(m - 1, -1, -1):
            row[j] = 1 + nxt[j + 1] if ai == b[j] else (nxt[j] if nxt[j] >= row[j + 1] else row[j + 1])
    out = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


# ---------------- 服务成员判定 ----------------
def _has(t, *s):
    return all(x in t["jasN"] for x in s)


def _ends(t, *s):
    return t["jasN"][0] in s or t["jasN"][-1] in s


def m_hayabusa(t):
    return t["i"] == "Hayabusa" or "はやぶさ" in (t.get("nm") or "")


def m_komachi(t):
    return t["i"] == "Komachi" or "こまち" in (t.get("nm") or "")


def m_yamabiko(t):
    return t["i"] == "Yamabiko" or "やまびこ" in (t.get("nm") or "")


def m_tsubasa(t):
    return t["i"] == "Tsubasa" or "つばさ" in (t.get("nm") or "")


def m_shiokaze(t):
    return t["i"] == "特" and _has(t, "児島") and _ends(t, "松山", "伊予西条")


def m_ishizuchi(t):
    return t["i"] == "特" and _has(t, "宇多津") and not _has(t, "児島") and \
        _ends(t, "高松", "松山", "伊予西条", "新居浜")


def m_midori(t):
    return t["i"] == "特" and _has(t, "早岐") and _ends(t, "佐世保")


def m_htb(t):
    return t["i"] == "特" and _has(t, "早岐") and _ends(t, "ハウステンボス")


def m_sunrise_seto(t):
    return t["i"] == "寝" and _has(t, "岡山") and _ends(t, "高松", "琴平")


def m_sunrise_izumo(t):
    return t["i"] == "寝" and _has(t, "岡山") and _ends(t, "出雲市")


def m_nex(t):
    return t["i"] == "特" and _has(t, "成田空港")


def m_odoriko_shuzenji(t):
    return t["i"] == "特" and _has(t, "熱海") and _ends(t, "修善寺")


def m_odoriko_izukyu(t):
    return t["i"] == "特" and _has(t, "熱海") and _ends(t, "伊豆急下田")


def m_kansai(t):
    return t["i"] == "関" and _has(t, "日根野") and _ends(t, "関西空港")


def m_kishuji(t):
    return t["i"] == "紀" and _has(t, "日根野") and \
        _ends(t, "和歌山", "海南", "湯浅", "御坊", "紀伊田辺")


def m_maizuru(t):
    return t["i"] == "特" and _has(t, "綾部") and _ends(t, "東舞鶴")


def m_kitakinki(t):
    return t["i"] == "特" and _has(t, "綾部") and \
        _ends(t, "福知山", "豊岡", "天橋立", "宮津", "城崎温泉", "香住", "浜坂", "西舞鶴", "京都")


def m_kitakinki_sym(t):
    return t["i"] == "特" and _has(t, "綾部", "福知山") and \
        _ends(t, "京都", "福知山", "豊岡", "天橋立", "宮津", "城崎温泉", "香住", "浜坂")


def m_fuji(t):
    return t["i"] == "特" and _has(t, "大月") and _ends(t, "河口湖")


def m_kaiji(t):
    return t["i"] == "特" and _has(t, "大月") and \
        _ends(t, "甲府", "竜王", "松本", "南小谷", "白馬")


def m_tobu(t):
    return t["i"] == "特" and _has(t, "下今市") and \
        _ends(t, "浅草", "東武日光", "鬼怒川温泉", "会津田島")


def m_hida(t):
    return ("ひだ" in (t.get("nm") or "")) or \
        (t["i"] == "特" and _has(t, "岐阜") and _ends(t, "高山", "飛騨古川"))


def m_hakone(t):
    return t["i"] == "特" and _has(t, "相模大野") and _ends(t, "新宿", "北千住", "箱根湯本")


def m_enoshima(t):
    return t["i"] == "特" and _has(t, "相模大野") and \
        _ends(t, "新宿", "北千住", "片瀬江ノ島", "藤沢")


# (名称, 併结站, 类型, 成员判定, 时刻容差, 共享段必经站, 端点锚, 允许一侧记录截到端点)
# 端点锚：分割=共享段首站；併结=共享段末站。允许一侧缺失相邻站（记录被截短）。
EVENTS = [
    ("はやぶさ×こまち@盛岡", "盛岡", "s", [m_hayabusa, m_komachi], 4, None, "東京", False),
    ("はやぶさ×こまち@盛岡", "盛岡", "j", [m_hayabusa, m_komachi], 4, None, "東京", False),
    ("やまびこ×つばさ@福島", "福島", "s", [m_yamabiko, m_tsubasa], 3, None, "東京", False),
    ("やまびこ×つばさ@福島", "福島", "j", [m_yamabiko, m_tsubasa], 3, None, "東京", False),
    ("しおかぜ×いしづち@宇多津", "宇多津", "s", [m_shiokaze, m_ishizuchi], 3, None, "松山", False),
    ("しおかぜ×いしづち@宇多津", "宇多津", "j", [m_shiokaze, m_ishizuchi], 3, None, "松山", False),
    # 下り 21～29 号は多度津で併合(公式編成図 2025-03-15・jr-group.jp 時刻表)。
    # 両車は宇多津→多度津を別々に走り、多度津で同刻発になる。
    ("しおかぜ×いしづち@多度津", "多度津", "j", [m_shiokaze, m_ishizuchi], 3, None, "松山", False),
    ("みどり×ハウステンボス@早岐", "早岐", "s", [m_midori, m_htb], 6, None, "博多", False),
    ("みどり×ハウステンボス@早岐", "早岐", "j", [m_midori, m_htb], 6, None, "博多", False),
    ("サンライズ瀬戸×出雲@岡山", "岡山", "s", [m_sunrise_seto, m_sunrise_izumo], 3, None, "東京", False),
    ("サンライズ瀬戸×出雲@岡山", "岡山", "j", [m_sunrise_seto, m_sunrise_izumo], 3, None, "東京", False),
    ("NEX@東京", "東京", "s", [m_nex], 3, None, "成田空港", False),
    ("NEX@東京", "東京", "j", [m_nex], 3, None, "成田空港", False),
    ("踊り子@熱海", "熱海", "s", [m_odoriko_shuzenji, m_odoriko_izukyu], 3, "東京", None, False),
    ("踊り子@熱海", "熱海", "j", [m_odoriko_shuzenji, m_odoriko_izukyu], 3, "東京", None, False),
    ("関空快速×紀州路快速@日根野", "日根野", "s", [m_kansai, m_kishuji], 4, "天王寺", None, False),
    ("関空快速×紀州路快速@日根野", "日根野", "j", [m_kansai, m_kishuji], 4, "天王寺", None, False),
    ("まいづる×北近畿@綾部", "綾部", "s", [m_maizuru, m_kitakinki], 3, None, "京都", False),
    ("まいづる×北近畿@綾部", "綾部", "j", [m_maizuru, m_kitakinki], 3, None, "京都", False),
    ("北近畿@福知山", "福知山", "s", [m_kitakinki_sym], 3, None, "京都", True),
    ("北近畿@福知山", "福知山", "j", [m_kitakinki_sym], 3, None, "京都", True),
    ("富士回遊×かいじ/あずさ@大月", "大月", "s", [m_fuji, m_kaiji], 3, "新宿", None, False),
    ("富士回遊×かいじ/あずさ@大月", "大月", "j", [m_fuji, m_kaiji], 3, "新宿", None, False),
    ("東武特急@下今市", "下今市", "s", [m_tobu], 3, None, "浅草", False),
    ("東武特急@下今市", "下今市", "j", [m_tobu], 3, None, "浅草", False),
    ("ひだ@岐阜", "岐阜", "s", [m_hida], 3, None, "高山", False),
    ("ひだ@岐阜", "岐阜", "j", [m_hida], 3, None, "高山", False),
    # 小田急 はこね×えのしま：土休日 新宿⇄相模大野 6 往復、メトロはこね×メトロえのしま
    # 北千住⇄相模大野（全列車）。新宿側の共享段只有 相模大野・新百合ケ丘・新宿 3 站。
    ("小田急はこね×えのしま@相模大野(新宿)", "相模大野", "s", [m_hakone, m_enoshima], 1, None, "新宿", False),
    ("小田急はこね×えのしま@相模大野(新宿)", "相模大野", "j", [m_hakone, m_enoshima], 1, None, "新宿", False),
    ("小田急はこね×えのしま@相模大野(北千住)", "相模大野", "s", [m_hakone, m_enoshima], 1, None, "北千住", False),
    ("小田急はこね×えのしま@相模大野(北千住)", "相模大野", "j", [m_hakone, m_enoshima], 1, None, "北千住", False),
]

# 个别服务共享段天然较短，按事件放宽最少共享站数（默认 4）。
_MIN_PAIRS = {
    "小田急はこね×えのしま@相模大野(新宿)": 3,
    "小田急はこね×えのしま@相模大野(北千住)": 3,
}

# 同一物理列车被两个来源各录一份、同刻始发，但其中一份把各站站停多记了 1 分钟，
# 累计漂移超过 tol 的对：把慢的一份对齐到快的一份再正常併结。只对已逐班核对过
# 的事件开启，避免把相邻班次误认成同一列车。上限 10 分钟。
_ALIGN_EVENTS = {"関空快速×紀州路快速@日根野"}
_ALIGN_MAX = 10


# 已知併结服务对（成员判定函数名）。盲区扫描只报“服务对本身不在目录内”的候选，
# 目录内服务的重复/截短记录不重复报警。
_ALL_MATCHERS = []
for _ev in EVENTS:
    for _fn in _ev[3]:
        if _fn not in _ALL_MATCHERS:
            _ALL_MATCHERS.append(_fn)
_EVENT_MEMBER_PAIRS = set()
for _ev in EVENTS:
    _names = [fn.__name__ for fn in _ev[3]]
    for _a in _names:
        for _b in _names:
            _EVENT_MEMBER_PAIRS.add((_a, _b))


def _service_tags(t):
    return {fn.__name__ for fn in _ALL_MATCHERS if fn(t)}


def _candidates(tagged, ev):
    """tagged: [(trip, [member_idx...])] against one event. Returns candidate list."""
    name, J, kind, preds, tol, contains, anchor, allow_edge = ev
    minp = _MIN_PAIRS.get(name, 4)
    out = []
    for x in range(len(tagged)):
        A, ma = tagged[x]
        ia = A["jasN"].index(J)
        for y in range(x + 1, len(tagged)):
            B, mb = tagged[y]
            if len(preds) > 1 and not any(a != b for a in ma for b in mb):
                continue
            ib = B["jasN"].index(J)
            if kind == "s":
                if ia == 0 or ib == 0:
                    continue
                if abs(A["arr"][ia] - B["arr"][ib]) > tol:
                    continue
                pairs = _lcs_pairs(A["jasN"][:ia + 1], B["jasN"][:ib + 1])
                if not pairs or pairs[-1] != (ia, ib) or len(pairs) < minp:
                    continue
                if anchor and A["jasN"][pairs[0][0]] != anchor:
                    continue
                if contains and contains not in (A["jasN"][i] for i, _ in pairs):
                    continue
                na = A["jasN"][ia + 1] if ia + 1 < A["N"] else None
                nb = B["jasN"][ib + 1] if ib + 1 < B["N"] else None
                if na == nb or (na is None and nb is None):
                    continue
                if (na is None or nb is None) and not allow_edge:
                    continue
                devs = [abs(A["arr"][i] - B["arr"][j]) for i, j in pairs[1:]]
                if not devs:
                    devs = [abs(A["arr"][ia] - B["arr"][ib])]
                if max(devs) > tol:
                    continue
                t0 = max(A["dep"][pairs[0][0]], B["dep"][pairs[0][1]])
                t1 = min(A["arr"][ia], B["arr"][ib])
            else:
                if ia == A["N"] - 1 or ib == B["N"] - 1:
                    continue
                if abs(A["dep"][ia] - B["dep"][ib]) > tol:
                    continue
                pairs = _lcs_pairs(A["jasN"][ia:], B["jasN"][ib:])
                if not pairs or pairs[0] != (0, 0) or len(pairs) < minp:
                    continue
                if anchor and A["jasN"][ia + pairs[-1][0]] != anchor:
                    continue
                if contains and contains not in (A["jasN"][ia + i] for i, _ in pairs):
                    continue
                pa = A["jasN"][ia - 1] if ia > 0 else None
                pb = B["jasN"][ib - 1] if ib > 0 else None
                if pa is None and pb is None:
                    continue
                if pa == pb:
                    # 同一前站:两车可能沿同一线路分开跑到 J 才併结(如 しおかぜ×いしづち@多度津)。
                    # 前站发车差 > tol 才认为是分开运行;同刻发车前站相同的,此前已连挂,
                    # 应由上游併结站认领,不能把连挂窗口截短。
                    if abs(A["dep"][ia - 1] - B["dep"][ib - 1]) <= tol:
                        continue
                elif pa is None or pb is None:
                    if not allow_edge:
                        continue
                # 併结站发车 + 中间共享站到达；共同终点到站记法差排除
                devs = [abs(A["dep"][ia] - B["dep"][ib])]
                devs += [abs(A["arr"][ia + i] - B["arr"][ib + j]) for i, j in pairs[1:-1]]
                if max(devs) > tol:
                    continue
                t0 = max(A["dep"][ia], B["dep"][ib])
                t1 = min(A["arr"][ia + pairs[-1][0]], B["arr"][ib + pairs[-1][1]])
            w0 = max(A["w0"], B["w0"])
            w1 = min(A["w1"], B["w1"])
            t0 = max(t0, w0)
            t1 = min(t1, w1)
            if t0 > t1:
                continue
            score = (max(devs), sum(devs), -len(pairs), -(A["N"] + B["N"]))
            out.append((score, A, B, t0, t1, len(pairs), name, J, kind))
    return out


def _encode_s(t):
    s = [t["dep"][0]]
    for i in range(1, t["N"]):
        s.append(max(0, t["arr"][i] - t["dep"][i - 1]))
        if i < t["N"] - 1:
            s.append(max(0, t["dep"][i] - t["arr"][i]))
    return ",".join(map(str, s))


def _rebase_times(slow, fast, pairs):
    """pairs: [(slow_idx, fast_idx)]。共享段按 fast 的到发时刻重写 slow；
    fast 跳过的站按时间比例插值偏移；分割站之后的尾段整体平移，保持本段运行时间。"""
    sa0, sd0 = slow["arr"][:], slow["dep"][:]
    fa, fd = fast["arr"], fast["dep"]
    n = slow["N"]
    new_arr, new_dep = sa0[:], sd0[:]
    off_arr = {}
    for si, fi in pairs:
        off_arr[si] = fa[fi] - sa0[si]
        new_arr[si], new_dep[si] = fa[fi], fd[fi]
    ks = [si for si, _ in pairs]
    for a, b in zip(ks, ks[1:]):
        if b - a <= 1:
            continue
        ta, tb = sa0[a], sa0[b]
        for k in range(a + 1, b):
            f = (sa0[k] - ta) / (tb - ta) if tb > ta else 0.0
            d = int(round(off_arr[a] + (off_arr[b] - off_arr[a]) * f))
            new_arr[k] = sa0[k] + d
            new_dep[k] = sd0[k] + d
    split = ks[-1]
    tail = new_dep[split] - sd0[split]
    for k in range(split + 1, n):
        new_arr[k] = sa0[k] + tail
        new_dep[k] = sd0[k] + tail
    for k in range(1, n):
        if new_arr[k] < new_dep[k - 1]:
            new_arr[k] = new_dep[k - 1]
        if new_dep[k] < new_arr[k]:
            new_dep[k] = new_arr[k]
    return new_arr, new_dep


def _apply_alignments(pool, recs, warnings):
    for ev in EVENTS:
        name, J, kind, preds, tol, contains, anchor, allow_edge = ev
        if kind != "s" or name not in _ALIGN_EVENTS or len(preds) < 2:
            continue
        minp = _MIN_PAIRS.get(name, 4)
        tagged = []
        for t in pool:
            if J not in t["jasN"] or t["N"] < 4 or t.get("bad"):
                continue
            ms = [k for k, p in enumerate(preds) if p(t)]
            if ms:
                tagged.append((t, ms))
        cands = []
        for x in range(len(tagged)):
            A, ma = tagged[x]
            ia = A["jasN"].index(J)
            if ia == 0:
                continue
            for y in range(x + 1, len(tagged)):
                B, mb = tagged[y]
                if not any(a != b for a in ma for b in mb):
                    continue
                ib = B["jasN"].index(J)
                if ib == 0:
                    continue
                # 同起点且同分钟发车：同一轨道不可能同刻两班，只能是同一列车
                if A["jasN"][0] != B["jasN"][0] or A["dep"][0] != B["dep"][0]:
                    continue
                pairs = _lcs_pairs(A["jasN"][:ia + 1], B["jasN"][:ib + 1])
                if not pairs or pairs[0] != (0, 0) or pairs[-1] != (ia, ib) or len(pairs) < minp:
                    continue
                if anchor and A["jasN"][pairs[0][0]] != anchor:
                    continue
                if contains and contains not in (A["jasN"][i] for i, _ in pairs):
                    continue
                na = A["jasN"][ia + 1] if ia + 1 < A["N"] else None
                nb = B["jasN"][ib + 1] if ib + 1 < B["N"] else None
                if na == nb or (na is None and nb is None):
                    continue
                if (na is None or nb is None) and not allow_edge:
                    continue
                devs = [abs(A["arr"][i] - B["arr"][j]) for i, j in pairs[1:]]
                m = max(devs) if devs else abs(A["arr"][ia] - B["arr"][ib])
                if m <= tol or m > _ALIGN_MAX:
                    continue
                cands.append((m, A, B, pairs))
        cands.sort(key=lambda c: c[0])
        used = set()
        for m, A, B, pairs in cands:
            if A["tid"] in used or B["tid"] in used:
                continue
            used.add(A["tid"])
            used.add(B["tid"])
            spanA = A["arr"][pairs[-1][0]] - A["dep"][pairs[0][0]]
            spanB = B["arr"][pairs[-1][1]] - B["dep"][pairs[0][1]]
            if spanA <= spanB:
                fast, slow, pr = A, B, [(j, i) for i, j in pairs]
            else:
                fast, slow, pr = B, A, pairs
            slow["arr"], slow["dep"] = _rebase_times(slow, fast, pr)
            rec = recs[slow["tid"]]
            rec["s"] = _encode_s(slow)
            rec["w"] = f"{slow['dep'][0]},{slow['arr'][-1]}"
            warnings.append(
                f"[align] {name} {A['tid'][-6:]}/{B['tid'][-6:]} 共享段站停多记漂移 {m} 分，"
                f"已按 {fast['tid'][-6:]} 对齐")


def compute_couplings(recs, tmaps, tokkyu):
    """recs: {train_id: rec}; tmaps: {tmap_id: tm}; tokkyu: 爱称表。
    返回 (c_by_tid, stats, warnings)。
    c_by_tid: {tid: [{"p","k","sp","t0","t1","nm"}, ...]}（每记录至多 1 条）
    stats: {(名称, 类型): (选中数, 候选数)}
    """
    trips = {}
    for tid, rec in recs.items():
        tm = tmaps.get(str(rec["t"]))
        if not tm:
            continue
        t = build_trip(rec, tm, tokkyu)
        if t:
            trips[tid] = t
    pool = list(trips.values())

    warnings = []
    _apply_alignments(pool, recs, warnings)

    chosen = []
    stats = {}
    for ev in EVENTS:
        name, J, kind, preds = ev[0], ev[1], ev[2], ev[3]
        at = [t for t in pool if J in t["jasN"] and t["N"] >= 4 and not t.get("bad")]
        tagged = []
        for t in at:
            ms = [k for k, p in enumerate(preds) if p(t)]
            if ms:
                tagged.append((t, ms))
        cands = _candidates(tagged, ev)
        stats[(name, kind)] = [0, len(cands)]
        chosen.extend(cands)

    chosen.sort(key=lambda c: c[0])
    used = set()
    picked = []
    for cand in chosen:
        _, A, B = cand[0], cand[1], cand[2]
        if A["tid"] in used or B["tid"] in used:
            continue
        used.add(A["tid"])
        used.add(B["tid"])
        picked.append(cand)
        stats[(cand[6], cand[8])][0] += 1

    c_by_tid = {}
    for score, A, B, t0, t1, nr, name, J, kind in picked:
        for a, b, bnm in ((A, B, B["cnm"]), (B, A, A["cnm"])):
            c_by_tid.setdefault(a["tid"], []).append(
                {"p": b["tid"], "k": kind, "sp": J, "t0": t0, "t1": t1,
                 "nm": bnm or b["i"] or ""})

    for (name, kind), (n, cand) in sorted(stats.items()):
        if n == 0 and cand > 0:
            warnings.append(f"目录事件候选全部落空: {name} ({kind}) cand={cand}")
    known = {frozenset((c[1]["tid"], c[2]["tid"])) for c in picked}
    for hit in scan_uncatalogued(pool, known):
        warnings.append("未入目录的强候选: " + hit)
    return c_by_tid, stats, warnings


def scan_uncatalogued(trips, known):
    """报告「同起点的共同前缀 / 同终点的共同后缀 + 逐站同刻」但不在目录内的
    不同种别、不同终到(始发)的强候选。只做诊断，不参与页面标注。"""
    hits = []
    tags = {}
    for t in trips:
        if t["i"] in _SCAN_CLASSES and t["N"] >= 4 and not t.get("bad"):
            tags[t["tid"]] = _service_tags(t)
    def known_service_pair(A, B):
        ta, tb = tags.get(A["tid"], ()), tags.get(B["tid"], ())
        return any(x in ta and y in tb for x, y in _EVENT_MEMBER_PAIRS)
    by_orig = {}
    for t in trips:
        if t["tid"] in tags:
            by_orig.setdefault((t["jasN"][0], t["jasN"][1] if t["N"] > 1 else ""), []).append(t)
    for lst in by_orig.values():
        lst.sort(key=lambda t: t["dep"][0])
        for i in range(len(lst)):
            A = lst[i]
            for j in range(i + 1, len(lst)):
                B = lst[j]
                if B["dep"][0] - A["dep"][0] > 2:
                    break
                if A["jasN"][-1] == B["jasN"][-1]:
                    continue
                if A["cnm"] and A["cnm"] == B["cnm"]:
                    continue
                if frozenset((A["tid"], B["tid"])) in known:
                    continue
                if known_service_pair(A, B):
                    continue
                pairs = _lcs_pairs(A["jasN"], B["jasN"])
                if len(pairs) < 5 or pairs[0] != (0, 0):
                    continue
                if pairs[-1] == (A["N"] - 1, B["N"] - 1):
                    continue
                devs = [abs(A["arr"][k] - B["arr"][m]) for k, m in pairs[1:]]
                if not devs or max(devs) > 1:
                    continue
                hits.append(f"{A['jasN'][0]}→{A['jasN'][-1]}({A['cnm'] or A['i']}) × "
                            f"{B['jasN'][0]}→{B['jasN'][-1]}({B['cnm'] or B['i']}) "
                            f"@{A['dep'][0]} 共{len(pairs)}站 dev{max(devs)}")
    by_term = {}
    for t in trips:
        if t["tid"] in tags:
            by_term.setdefault((t["jasN"][-1], t["jasN"][-2] if t["N"] > 1 else ""), []).append(t)
    for lst in by_term.values():
        lst.sort(key=lambda t: t["arr"][-1])
        for i in range(len(lst)):
            A = lst[i]
            for j in range(i + 1, len(lst)):
                B = lst[j]
                if B["arr"][-1] - A["arr"][-1] > 2:
                    break
                if A["jasN"][0] == B["jasN"][0]:
                    continue
                if A["cnm"] and A["cnm"] == B["cnm"]:
                    continue
                if frozenset((A["tid"], B["tid"])) in known:
                    continue
                if known_service_pair(A, B):
                    continue
                pairs = _lcs_pairs(A["jasN"][::-1], B["jasN"][::-1])
                if len(pairs) < 5 or pairs[0] != (0, 0):
                    continue
                if pairs[-1] == (A["N"] - 1, B["N"] - 1):
                    continue
                devs = [abs(A["arr"][A["N"] - 1 - k] - B["arr"][B["N"] - 1 - m])
                        for k, m in pairs[1:]]
                if not devs or max(devs) > 1:
                    continue
                hits.append(f"{A['jasN'][0]}→{A['jasN'][-1]}({A['cnm'] or A['i']}) × "
                            f"{B['jasN'][0]}→{B['jasN'][-1]}({B['cnm'] or B['i']}) "
                            f"@{A['arr'][-1]} 共{len(pairs)}站 dev{max(devs)}")
    # 去重（同一对可能在两个方向各出现一次）
    uniq = []
    for h in hits:
        if h not in uniq:
            uniq.append(h)
    return uniq[:20]

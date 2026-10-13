#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上行併结（join）检测 —— 构建期执行，结果固化进 trains_*.json 的 "c" 字段。

架构（2026-10-13，方向D：构建期检测 + 併结点白名单最后闸门）：
  - 下行/同起点分割（pass1）完全留在浏览器 buildCouplings 不动（零回归风险）。
  - 本模块只负责上行/异起点併结（pass2）：はやぶさ×こまち@盛岡、
    みどり×ハウステンボス@早岐、しおかぜ×いしづち@宇多津 等，
    这类列车始发站不同、共享段位于双方路线尾部，浏览器旧规则无法识别。
  - 判定链：双方终点相同 + 共享段从双方路线中部起、覆盖双方尾部（≥4站）
    + 共享段逐站发车时刻对齐 ≤ALIGN_TOL + 运行窗重叠
    + **併结点白名单 JOIN_POINTS 最后闸门**（(併结站, 终点, 始发站无序对)）。
  - 每列车物理上只有一个併结伙伴：候选对按对齐偏差升序贪心匹配，
    每条记录至多挂一个 "c"（join 条目）。

白名单来源（2026-10 联网核实）：
  盛岡   はやぶさ(新青森/新函館北斗)×こまち(秋田)        東北新幹線（上り併結）
  福島   やまびこ(盛岡)×つばさ(山形/新庄)               東北/山形新幹線（上り併結）
  宇多津 しおかぜ(岡山)×いしづち(高松)                  予讃線（上り併結）
  多度津 しおかぜ(岡山)×いしづち(高松)                  同上（一部列車）
  早岐   みどり(佐世保)×ハウステンボス(ハウステンボス)  佐世保線（上り併結）

"c" 条目格式：{"p": 伙伴train_id, "k": "j", "sp": 併结站(normName),
  "t0": 併结窗口起点, "t1": 窗口终点, "nm": 伙伴爱称}
前端只读不判：解析时按 tid 解析回活班次对象并挂到 cpl（join 型文案）。
"""
import re

# 共享段逐站发车时刻对齐容差（分钟）。物理併结车共享段时刻几乎一致；
# 但源数据对两车记录偶有 1-7min 记法偏差（早岐みどり×ハウステンボス全程差 1-4min、
# 宇多津 18:35 对差 7min 后段归 0），故取 10。真正的防误判靠 JOIN_POINTS 白名单。
ALIGN_TOL = 10

# 上行併结白名单：(併结站normName, 终点normName, frozenset(两始发站normName))
# 只有命中此表的上行/异起点併结候选才允许标注（结构性零误判）。
# 注意福島上り併结是 やまびこ(仙台発)×つばさ(山形/新庄)——盛岡発やまびこ上り不併结。
JOIN_POINTS = {
    ("盛岡", "東京", frozenset({"新青森", "秋田"})),
    ("盛岡", "東京", frozenset({"新函館北斗", "秋田"})),
    ("福島", "東京", frozenset({"仙台", "山形"})),
    ("福島", "東京", frozenset({"仙台", "新庄"})),
    ("宇多津", "松山", frozenset({"岡山", "高松"})),
    ("多度津", "松山", frozenset({"岡山", "高松"})),
    ("早岐", "博多", frozenset({"佐世保", "ハウステンボス"})),
    # サンライズ瀬戸×出雲：上り 高松/出雲市 → 岡山併结 → 東京
    ("岡山", "東京", frozenset({"高松", "出雲市"})),
}

# 参与併结的车种白名单（与 index.html COUPLE_CLASSES 一致）
COUPLE_CLASSES = {
    "Hayabusa", "Komachi", "Yamabiko", "Tsubasa", "Toki", "Tanigawa",
    "Sakura", "Tsubame", "特", "新", "関", "紀", "寝",  # 寝=寝台特急(サンライズ瀬戸×出雲)
}

_TOKKYU_ICONS = set("関紀中丹寝京ミフ富九川ＴＳＮホ拝ラアエ空")
_ICON_NAME = {
    "関": "はるか", "紀": "くろしお", "丹": "こうのとり", "ミ": "ミュースカイ",
    "フ": "フジサン特急", "富": "フジサン特急", "九": "九州横断特急", "京": "京王特急",
    "川": "川越特急", "Ｔ": "東武特急", "Ｓ": "直通特急", "Ｎ": "西鉄特急",
    "ホ": "ホームライナー", "拝": "拝島ライナー", "ア": "アクセス特急",
    "エ": "アクセス特急", "空": "空港快速", "寝": "寝台特急", "中": "中央線特急",
    "ラ": "ライナー",
}


def norm_name(n):
    return re.sub(r"\([^)]*\)", "", str(n)).replace("ヶ", "ヶ").replace("駅", "").strip()


def trip_name(icon, jas, lines, tokkyu):
    """与 index.html tripName 一致（tokkyu: {"sh","nm","nmI"}）。"""
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
    """併结伙伴展示名：优先爱称表（含「特」icon 的线路签名直查，如 みどり/しおかぜ/
    いしづち/ハウステンボス），再退回车种/爱称通用名。仅构建期 join 元数据用，
    不改页面 tripName 行为。"""
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
    """轻量班次对象（join 判定所需字段）。"""
    jas = tm.get("s_jas") or []
    N = len(jas)
    if N < 2:
        return None
    s = [int(x) for x in rec["s"].split(",")]
    if len(s) != 2 * N - 2:
        return None
    dep = [0] * N
    dep[0] = s[0]
    for i in range(1, N):
        dep[i] = dep[i - 1] + s[2 * i - 1] + (s[2 * i] if 2 * i < len(s) else 0)
    w0, w1 = [int(x) for x in rec["w"].split(",")]
    return {
        "tid": rec["_"], "t": rec["t"], "i": rec.get("i", ""), "N": N,
        "jasN": [norm_name(x) for x in jas], "dep": dep, "w0": w0, "w1": w1,
        "nm": trip_name(rec.get("i", ""), jas, tm.get("lines") or [], tokkyu),
        "cnm": couple_name(rec.get("i", ""), jas, tm.get("lines") or [], tokkyu),
    }


def _lcs(A, B):
    """最长公共连续站序（双向遍历, 与页面一致; 平局取首次出现）。返回
    (best, endA, endB)；best=0 表示无共享。"""
    best = end_a = end_b = 0
    for i in range(A["N"]):
        for j in range(B["N"]):
            if A["jasN"][i] != B["jasN"][j]:
                continue
            k = 0
            while (i + k < A["N"] and j + k < B["N"]
                   and A["jasN"][i + k] == B["jasN"][j + k]):
                k += 1
            if k > best:
                best, end_a, end_b = k, i + k - 1, j + k - 1
    return best, end_a, end_b


def detect_join(trips):
    """上行/异起点併结——尾部共享 + 终点相同 + 逐站对齐≤ALIGN_TOL + 白名单闸门。
    返回 [(tidA, tidB, sp, t0, t1, nmB, dev), ...]（sp=併结站=共享段起点）。"""
    by_term = {}
    for t in trips:
        if t["N"] < 4:
            continue
        by_term.setdefault(t["jasN"][-1], []).append(t)
    out = []
    for lst in by_term.values():
        lst.sort(key=lambda t: t["dep"][-1])
        for a in range(len(lst)):
            A = lst[a]
            for b in range(a + 1, len(lst)):
                B = lst[b]
                if B["dep"][-1] - A["dep"][-1] > ALIGN_TOL:
                    break
                if A["i"] not in COUPLE_CLASSES or B["i"] not in COUPLE_CLASSES:
                    continue
                if A["jasN"][0] == B["jasN"][0]:
                    continue  # 同始发站 = 下行/分割类型, 留在浏览器 pass1
                best, end_a, end_b = _lcs(A, B)
                if best < 4:
                    continue
                st_a, st_b = end_a - best + 1, end_b - best + 1
                if st_a == 0 or st_b == 0:
                    continue  # 共享段必须从双方路线中部开始（异起点併结）
                if end_a != A["N"] - 1 or end_b != B["N"] - 1:
                    continue  # 共享段必须是双方尾部（都到同一终点）
                na, nb = A["nm"], B["nm"]
                if na and nb and na == nb:
                    continue
                dev = 0
                ok = True
                for k in range(best):
                    d = abs(A["dep"][st_a + k] - B["dep"][st_b + k])
                    if d > ALIGN_TOL:
                        ok = False
                        break
                    dev = max(dev, d)
                if not ok:
                    continue
                t0 = max(A["dep"][st_a], B["dep"][st_b])
                t1 = min(A["dep"][end_a], B["dep"][end_b])
                w0, w1 = max(A["w0"], B["w0"]), min(A["w1"], B["w1"])
                if t0 > w1 or t1 < w0:
                    continue
                c0, c1 = max(t0, w0), min(t1, w1)
                junction = A["jasN"][st_a]
                key = (junction, A["jasN"][-1], frozenset((A["jasN"][0], B["jasN"][0])))
                if key not in JOIN_POINTS:
                    continue  # 白名单最后闸门：只认人工核实的真併结点
                out.append((A["tid"], B["tid"], junction, c0, c1, nb or B["i"], dev))
    return out


def _match_unique(cands):
    """每条记录最多保留 1 条上行併结（物理上一列车只有一个併结伙伴）。
    候选按对齐偏差升序贪心匹配，已配对的记录不再参与。"""
    cands = sorted(cands, key=lambda c: (c[6], c[3]))
    used = set()
    chosen = []
    for tid_a, tid_b, sp, t0, t1, nm, dev in cands:
        if tid_a in used or tid_b in used:
            continue
        used.add(tid_a)
        used.add(tid_b)
        chosen.append((tid_a, tid_b, sp, t0, t1, nm))
    return chosen


def compute_joins(recs, tmaps, tokkyu):
    """recs: {train_id: rec}; tmaps: {tmap_id: tm}; tokkyu: 爱称表。
    对给定记录集检测上行併结。返回 (c_by_tid, n_join)：
    c_by_tid: {tid: [{"p","k":"j","sp","t0","t1","nm"}, ...]}（每记录至多 1 条）
    不改动 recs 对象（供按日型分别调用）。"""
    trips = {}
    for tid, rec in recs.items():
        tm = tmaps.get(str(rec["t"]))
        if not tm:
            continue
        t = build_trip(rec, tm, tokkyu)
        if t:
            trips[tid] = t
    cands = detect_join(list(trips.values()))
    chosen = _match_unique(cands)
    c_by_tid = {}
    for tid_a, tid_b, sp, t0, t1, nm in chosen:
        ta, tb = trips[tid_a], trips[tid_b]
        for tid, other, other_nm in ((tid_a, tid_b, tb["cnm"]), (tid_b, tid_a, ta["cnm"])):
            c_by_tid.setdefault(tid, []).append(
                {"p": other, "k": "j", "sp": sp, "t0": t0, "t1": t1, "nm": other_nm or ""})
    return c_by_tid, len(chosen)

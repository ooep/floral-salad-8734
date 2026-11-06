#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/test_joins.py —— 併结/分割检测（scripts/couplings.py 目录锚定版）回归测试。

运行：python3 scripts/test_joins.py（在仓库根目录）
覆盖：
  正例：盛岡 はやぶさ×こまち、福島 やまびこ×つばさ（含 dep=480 郡山通过班次）、
        宇多津 しおかぜ×いしづち（分割/併结）、多度津 しおかぜ×いしづち 下り併合、
        早岐 みどり×ハウステンボス、岡山 サンライズ、
        日根野 関空×紀州路、大月 富士回遊、下今市 東武、熱海 踊り子、
        相模大野 小田急はこね×えのしま（土休日のみ）
  反例：每条记录至多一个伙伴；併结站只在目录内（无 仙台/大宮 等误标）；
        多度津 只併结不分割、宇多津 仍以分割/併结为主；
        とき×たにがわ、新快速、にちりん/ソニック 等目录外组合不出现
  一致性：JSON c 字段与计算一致（双侧挂载、k/sp/t0/t1 对称）、窗口落在双方运行窗内
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couplings as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "data", "live")
FAIL = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def load(day):
    d = json.load(open(os.path.join(LIVE, f"trains_{day}.json"), encoding="utf-8"))
    return {r["_"]: r for r in d["T"]}


def main():
    tmaps = json.load(open(os.path.join(LIVE, "tmaps.json"), encoding="utf-8"))
    tokkyu = json.load(open(os.path.join(ROOT, "mini-japanrail-3d", "data", "tokkyu.json"), encoding="utf-8"))
    catalog_junctions = {ev[1] for ev in C.EVENTS}

    for day in ("wd", "sa", "su"):
        recs = load(day)
        c_by, stats, warns = C.compute_couplings(recs, tmaps, tokkyu)
        trips = {}
        for tid, r in recs.items():
            t = C.build_trip(r, tmaps[str(r["t"])], tokkyu)
            if t:
                trips[tid] = t
        pairs = []
        for tid, cl in c_by.items():
            for c in cl:
                pairs.append((tid, c["p"], c["k"], c["sp"], c["t0"], c["t1"], c["nm"]))
        print(f"===== {day}: {len(pairs) // 2} 对, {len(c_by)} 条记录 =====")

        # ---- 结构不变量 ----
        check(f"{day} 每记录至多一个伙伴", all(len(v) <= 1 for v in c_by.values()),
              str([k for k, v in c_by.items() if len(v) > 1][:3]))
        bad = []
        for tid, p, k, sp, t0, t1, nm in pairs:
            A, B = trips.get(tid), trips.get(p)
            if not A or not B or A is B:
                bad.append(f"{tid}->{p} 伙伴缺失")
                continue
            rec = c_by.get(p) or []
            if not any(x["p"] == tid and x["k"] == k and x["sp"] == sp and x["t0"] == t0 and x["t1"] == t1 for x in rec):
                bad.append(f"{tid}<->{p} 不对称")
            w0, w1 = max(A["w0"], B["w0"]), min(A["w1"], B["w1"])
            if not (w0 <= t0 <= t1 <= w1):
                bad.append(f"{A['nm']}x{B['nm']} 窗口 {t0}-{t1} 越界 {w0}-{w1}")
            ia, ib = A["jasN"].index(sp), B["jasN"].index(sp)
            if k == "j" and (ia == A["N"] - 1 or ib == B["N"] - 1):
                bad.append(f"{A['nm']}x{B['nm']} 併结站是终点")
            if k == "s" and (ia == 0 or ib == 0):
                bad.append(f"{A['nm']}x{B['nm']} 分割站是起点")
        check(f"{day} 双侧挂载/窗口/站序一致", not bad, "; ".join(bad[:3]))
        check(f"{day} 併结站均在目录内", all(p[3] in catalog_junctions for p in pairs),
              str(sorted({p[3] for p in pairs} - catalog_junctions)))

        # ---- 正例：各目录服务的规模 ----
        def at(sp, kind):
            return [p for p in pairs if p[3] == sp and p[2] == kind]

        def ok_members(sp, kind, A, B):
            oa, ob = A["jasN"][0], B["jasN"][0]
            ta, tb = A["jasN"][-1], B["jasN"][-1]
            if sp == "盛岡":
                if kind == "s":
                    return oa == ob == "東京" and ({ta, tb} & {"新青森", "新函館北斗"}) and ({ta, tb} & {"秋田"})
                return oa != ob and ({oa, ob} & {"新青森", "新函館北斗"}) and ({oa, ob} & {"秋田"}) and ta == tb == "東京"
            if sp == "福島":
                if kind == "s":
                    return oa == ob == "東京" and ({ta, tb} & {"仙台"}) and ({ta, tb} & {"山形", "新庄"})
                return oa != ob and ({oa, ob} & {"仙台"}) and ({oa, ob} & {"山形", "新庄"}) and ta == tb == "東京"
            if sp == "宇多津":
                if kind == "s":
                    return oa == ob and oa in ("松山", "伊予西条") and {ta, tb} == {"岡山", "高松"}
                return {oa, ob} == {"岡山", "高松"} and ta == tb and ta in ("松山", "伊予西条")
            if sp == "多度津":
                # 下り 21～29 号:两车分别从岡山/高松开来,多度津同刻併结后同去松山
                return {oa, ob} == {"岡山", "高松"} and ta == tb == "松山"
            if sp == "早岐":
                if kind == "s":
                    return oa == ob == "博多" and {ta, tb} == {"佐世保", "ハウステンボス"}
                return {oa, ob} == {"佐世保", "ハウステンボス"} and ta == tb == "博多"
            if sp == "熱海":
                if kind == "s":
                    return oa == ob == "東京" and {ta, tb} == {"伊豆急下田", "修善寺"}
                return {oa, ob} == {"伊豆急下田", "修善寺"} and ta == tb == "東京"
            if sp == "大月":
                branch = {"甲府", "竜王", "松本", "南小谷", "白馬"}
                if kind == "s":
                    return oa == ob and ("河口湖" in (ta, tb)) and bool(set((ta, tb)) & branch)
                return ("河口湖" in (oa, ob)) and bool(set((oa, ob)) & branch) and ta == tb
            if sp == "綾部":
                if kind == "s":
                    return oa == ob == "京都" and ({ta, tb} & {"東舞鶴"})
                return ({oa, ob} & {"東舞鶴"}) and ta == tb == "京都"
            if sp == "岡山":
                if kind == "s":
                    return oa == ob == "東京" and ({ta, tb} & {"高松", "琴平"}) and ({ta, tb} & {"出雲市"})
                return ({oa, ob} & {"高松", "琴平"}) and ({oa, ob} & {"出雲市"}) and ta == tb == "東京"
            if sp == "日根野":
                return A["i"] in ("関", "紀") and B["i"] in ("関", "紀") and A["i"] != B["i"]
            return True

        for sp, min_s, min_j in (("盛岡", 20, 20), ("福島", 15, 15), ("宇多津", 10, 10),
                                 ("多度津", 0, 4),
                                 ("早岐", 5, 5), ("東京", 13, 13), ("熱海", 2, 2),
                                 ("日根野", 50, 50), ("綾部", 7, 7), ("大月", 4, 4),
                                 ("下今市", 5, 5), ("岡山", 1, 1)):
            for kind, mn in (("s", min_s), ("j", min_j)):
                lst = at(sp, kind)
                check(f"{day} {sp} {'分割' if kind == 's' else '併结'} ≥{mn}", len(lst) >= mn, f"got {len(lst)}")
                bad = [f"{trips[p[0]]['jasN'][0]}→{trips[p[0]]['jasN'][-1]}×"
                       f"{trips[p[1]]['jasN'][0]}→{trips[p[1]]['jasN'][-1]}"
                       for p in lst if not ok_members(sp, kind, trips[p[0]], trips[p[1]])]
                if bad:
                    check(f"{day} {sp} 伙伴走向", False, "; ".join(bad[:3]))

        # 多度津 只有併合(下り 21～29 号),不得凭空产生分割
        check(f"{day} 多度津 无分割", not at("多度津", "s"), f"got {len(at('多度津', 's'))}")

        # ---- 关键个例 ----
        # やまびこ dep=480（郡山通过，连续站序会断）必须有福島分割伙伴
        y480 = [t for t in trips.values() if t["i"] == "Yamabiko" and t["dep"][0] == 480 and "福島" in t["jasN"]]
        check(f"{day} やまびこ dep480 存在", bool(y480), f"got {len(y480)}")
        for t in y480:
            cl = c_by.get(t["tid"]) or []
            check(f"{day} やまびこ dep480 有福島伙伴",
                  any(x["sp"] == "福島" and x["nm"] == "つばさ" for x in cl), str(cl))

        # はやぶさ 分割站不得标成 仙台（记录截短导致旧 pass1 错标）
        bad_sp = [p for p in pairs if p[3] == "仙台"]
        check(f"{day} 无仙台併结站", not bad_sp, f"{len(bad_sp)} 对")

        # 旧启发式的错误组合不得出现
        banned = {"とき", "たにがわ", "南風", "しまんと", "にちりん", "にちりんシーガイア",
                  "ソニック", "ひゅうが", "新快速", "さくら", "つばめ"}
        hit = []
        for tid, p, k, sp, t0, t1, nm in pairs:
            A, B = trips[tid], trips[p]
            names = {A["nm"], B["nm"], nm}
            if names & banned:
                hit.append(f"{A['jasN'][0]}→{A['jasN'][-1]}×{B['jasN'][0]}→{B['jasN'][-1]}")
        check(f"{day} 无目录外服务组合", not hit, "; ".join(hit[:3]))

        # 小田急：平日无併结，土休日有 はこね×えのしま
        od = [p for p in pairs if p[3] == "相模大野"]
        if day == "wd":
            check(f"{day} 小田急平日不标注", not od, f"got {len(od)}")
        else:
            check(f"{day} 小田急土休日 ≥10 对", len(od) >= 10, f"got {len(od)}")
            for tid, p, k, sp, t0, t1, nm in od:
                A, B = trips[tid], trips[p]
                ok = ({A["nm"], B["nm"]} & {"はこね", "メトロはこね"}) and \
                     ({A["nm"], B["nm"]} & {"えのしま", "メトロえのしま"})
                check(f"{day} 小田急伙伴车型", ok, f"{A['nm']}×{B['nm']}")
                break

        # ---- JSON 与计算一致（rebake 后生效）----
        mismatch = 0
        for tid, cl in c_by.items():
            got = recs[tid].get("c") or []
            want = sorted((x["p"], x["k"], x["sp"], x["t0"], x["t1"], x["nm"]) for x in cl)
            have = sorted((x["p"], x["k"], x["sp"], x["t0"], x["t1"], x["nm"]) for x in got)
            if want != have:
                mismatch += 1
        for tid, r in recs.items():
            if tid not in c_by and r.get("c"):
                mismatch += 1
        check(f"{day} JSON c 与计算一致", mismatch == 0, f"{mismatch} 条不一致")

        for w in warns:
            print(f"  [warn] {w}")

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} 项失败: {FAIL[:10]}")
        sys.exit(1)
    print("✅ 全部通过")


if __name__ == "__main__":
    main()

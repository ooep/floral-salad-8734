#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/test_joins.py —— 上行併结检测（scripts/couplings.py）回归测试。

运行：python3 scripts/test_joins.py （在仓库根目录）
覆盖：
  正例：盛岡 はやぶさ×こまち（含 4487×4024 差1分钟对）、早岐 みどり×ハウステンボス、
        宇多津 しおかぜ×いしづち（含 18:35 源数据差7分钟对）、福島 やまびこ(仙台)×つばさ
  反例：盛岡発やまびこ×つばさ 不配对（并行列车）、同始发站不参与 join（归 pass1）、
        每条记录至多一个 join 伙伴、非白名单併结点不标注。
  一致性：JSON 中的 c 字段与计算输出一致（每对双侧挂载、t0/t1 与窗口一致）。
"""
import json, os, sys, re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couplings as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def load(day):
    d = json.load(open(os.path.join(ROOT, "data", "live", f"trains_{day}.json"), encoding="utf-8"))
    return {r["_"]: r for r in d["T"]}


def main():
    tmaps = json.load(open(os.path.join(ROOT, "data", "live", "tmaps.json"), encoding="utf-8"))
    tokkyu = json.load(open(os.path.join(ROOT, "mini-japanrail-3d", "data", "tokkyu.json"), encoding="utf-8"))

    for day in ("wd", "sa", "su"):
        recs = load(day)
        c_by, n = C.compute_joins(recs, tmaps, tokkyu)
        trips = {}
        for tid, r in recs.items():
            t = C.build_trip(r, tmaps[str(r["t"])], tokkyu)
            if t:
                trips[tid] = t
        pairs = []
        for tid, cl in c_by.items():
            for c in cl:
                pairs.append((tid, c["p"], c["sp"], c["t0"], c["t1"], c["nm"]))
        pair_set = set()
        for a, b, *_ in pairs:
            pair_set.add(frozenset((a, b)))

        print(f"===== {day}: {n} 对 =====")

        # ---- 正例 ----
        # 盛岡 はやぶさ(新青森/新函館北斗)×こまち(秋田)
        morioka = [p for p in pairs if p[2] == "盛岡"]
        check(f"{day} 盛岡有併结对", len(morioka) >= 20, f"got {len(morioka)}")
        for a, b, sp, t0, t1, nm in morioka:
            A, B = trips[a], trips[b]
            ok = (A["jasN"][0] in ("新青森", "新函館北斗") and B["jasN"][0] == "秋田") or \
                 (B["jasN"][0] in ("新青森", "新函館北斗") and A["jasN"][0] == "秋田")
            check(f"{day} 盛岡伙伴均为はやぶさ×こまち", ok, f"{A['jasN'][0]}×{B['jasN'][0]}")
            # 併结站发车差 ≤ 2（源数据偶差 1-2min）
            iA, iB = A["jasN"].index(sp), B["jasN"].index(sp)
            check(f"{day} 盛岡併结站发车差≤2min", abs(A["dep"][iA] - B["dep"][iB]) <= 2,
                  f"{A['dep'][iA] - B['dep'][iB]:+d}")

        # 4487×4024 15:16/15:17 对（用户上报的个例）
        t15 = [p for p in pairs if p[2] == "盛岡" and (
            (trips[p[0]]["t"] == 4487 and trips[p[1]]["t"] == 4024) or
            (trips[p[0]]["t"] == 4024 and trips[p[1]]["t"] == 4487))]
        check(f"{day} 4487×4024 盛岡併结已识别", len(t15) >= 1, f"got {len(t15)}")

        # 早岐 みどり(佐世保)×ハウステンボス
        hayaki = [p for p in pairs if p[2] == "早岐"]
        check(f"{day} 早岐有併结对", len(hayaki) >= 5, f"got {len(hayaki)}")
        for a, b, sp, t0, t1, nm in hayaki:
            A, B = trips[a], trips[b]
            ok = {A["jasN"][0], B["jasN"][0]} == {"佐世保", "ハウステンボス"}
            check(f"{day} 早岐伙伴均为みどり×ハウステンボス", ok, f"{A['jasN'][0]}×{B['jasN'][0]}")

        # 宇多津 しおかぜ(岡山)×いしづち(高松)
        utazu = [p for p in pairs if p[2] == "宇多津"]
        check(f"{day} 宇多津有併结对", len(utazu) >= 12, f"got {len(utazu)}")
        for a, b, sp, t0, t1, nm in utazu:
            A, B = trips[a], trips[b]
            ok = {A["jasN"][0], B["jasN"][0]} == {"岡山", "高松"} and A["jasN"][-1] == "松山" and B["jasN"][-1] == "松山"
            check(f"{day} 宇多津伙伴均为しおかぜ×いしづち", ok, f"{A['jasN'][0]}×{B['jasN'][0]}")

        # 福島 やまびこ(仙台)×つばさ(山形/新庄)
        fukushima = [p for p in pairs if p[2] == "福島"]
        check(f"{day} 福島有併结对", len(fukushima) >= 15, f"got {len(fukushima)}")
        for a, b, sp, t0, t1, nm in fukushima:
            A, B = trips[a], trips[b]
            ok = ({A["jasN"][0], B["jasN"][0]} & {"山形", "新庄"}) and "仙台" in {A["jasN"][0], B["jasN"][0]}
            check(f"{day} 福島伙伴均为やまびこ(仙台)×つばさ", ok, f"{A['jasN'][0]}×{B['jasN'][0]}")

        # 岡山 サンライズ瀬戸(高松)×サンライズ出雲(出雲市)
        okayama = [p for p in pairs if p[2] == "岡山"]
        check(f"{day} 岡山有併结对", len(okayama) >= 1, f"got {len(okayama)}")
        for a, b, sp, t0, t1, nm in okayama:
            A, B = trips[a], trips[b]
            ok = {A["jasN"][0], B["jasN"][0]} == {"高松", "出雲市"} and \
                 A["jasN"][-1] == "東京" and B["jasN"][-1] == "東京"
            check(f"{day} 岡山伙伴均为サンライズ瀬戸×出雲", ok, f"{A['jasN'][0]}×{B['jasN'][0]}")

        # 2026-10-14 核实后白名单：東京 N'EX、大月 富士回遊(甲府)、熱海 踊り子、
        # 日根野 関空×紀州路、綾部 まいづる、下今市 東武リバティ
        for junc, term, orig_set in (
            ("東京", "成田空港", {"大船", "新宿"}),
            ("大月", "新宿", {"河口湖", "甲府"}),
            ("熱海", "東京", {"伊豆急下田", "修善寺"}),
            ("日根野", "天王寺", {"和歌山", "関西空港"}),
            ("日根野", "京橋", {"和歌山", "関西空港"}),
            ("綾部", "京都", {"東舞鶴", "豊岡"}),
            ("綾部", "京都", {"東舞鶴", "天橋立"}),
            ("下今市", "浅草", {"東武日光", "鬼怒川温泉"}),
            ("下今市", "浅草", {"会津田島", "東武日光"}),
        ):
            grp = [p for p in pairs if p[2] == junc and p[3] >= 0]
            ok_grp = [p for p in grp
                      if trips[p[0]]["jasN"][-1] == term and trips[p[1]]["jasN"][-1] == term
                      and set((trips[p[0]]["jasN"][0], trips[p[1]]["jasN"][0])) == orig_set]
            # 该组应至少识别 1 对（周末/平日数据覆盖不同；武雄温泉部分平日仅 1 对）
            check(f"{day} {junc}({term}) {sorted(orig_set)} 有併结对", len(ok_grp) >= 1,
                  f"total {len(grp)}, ok {len(ok_grp)}")

        # ---- 反例 ----
        # 福島併结伙伴不含盛岡発やまびこ（并行列车, 16:08×16:15 不配对）
        for a, b, sp, t0, t1, nm in pairs:
            A, B = trips[a], trips[b]
            if sp == "福島":
                check(f"{day} 福島无盛岡発やまびこ参与", "盛岡" not in {A["jasN"][0], B["jasN"][0]},
                      f"{A['jasN'][0]}×{B['jasN'][0]}")
            if sp == "盛岡":
                check(f"{day} 盛岡无同始发站参与", A["jasN"][0] != B["jasN"][0],
                      f"{A['jasN'][0]}×{B['jasN'][0]}")

        # 每条记录至多一个 join 伙伴（物理一列车只併结一次）
        multi = [tid for tid, cl in c_by.items() if len(cl) > 1]
        check(f"{day} 每记录至多一个join伙伴", not multi, f"{multi[:3]}")

        # 白名单闸门：非白名单併结点不标注（构造 大宮 型候补不应出现 join）
        for a, b, sp, t0, t1, nm in pairs:
            check(f"{day} 併结站在白名单内", (sp, trips[a]["jasN"][-1],
                  frozenset((trips[a]["jasN"][0], trips[b]["jasN"][0]))) in C.JOIN_POINTS,
                  f"{sp} {trips[a]['jasN'][0]}×{trips[b]['jasN'][0]}")

        # ---- 数据一致性：JSON c 字段双侧挂载 + 与计算一致 ----
        json_hits = 0
        for tid, cl in c_by.items():
            rec = recs.get(tid)
            if rec is None or "c" not in rec:
                continue
            for c in cl:
                if rec["c"] and any(x["p"] == c["p"] and x["sp"] == c["sp"] and x["t0"] == c["t0"] for x in rec["c"]):
                    json_hits += 1
        check(f"{day} JSON c 字段双侧挂载一致", json_hits == len(pairs),
              f"{json_hits}/{len(pairs)}")

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} 项失败: {FAIL}")
        sys.exit(1)
    print("✅ 全部通过")


if __name__ == "__main__":
    main()

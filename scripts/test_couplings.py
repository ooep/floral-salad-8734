#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""併结/分割检测护栏回归测试（对应 cf-mj3d/index.html 与 mini-japanrail-3d/index.html
中 buildCouplings 的防误判规则, 2026-10-13）：
  ① 共享连续站序 ≥4（主干 3 站巧合不算併结：新干线 东京-上野-大宫、南海 なんば-新今宫-天下茶屋 等）
  ② 共享段必须从双方始发站开始（併结均在起点连挂；中途公共段如 やまびこ×はやぶさ 是巧合）
断言：
  - 误判对全部消失：かがやき×つばさ(大宫)、かがやき×はくたか、やまびこ×つばさ(大宫)、やまびこ×はやぶさ
  - 真实对全部保留：はやぶさ×こまち(盛冈)、やまびこ×つばさ(福岛)、とき×たにがわ(越后汤泽)
  - 去重删除的 4 条重复记录不参与任何併结（去重与新护栏互不干扰）
运行：python3 scripts/test_couplings.py   （纯本地、无网络）
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "data", "live")

DROPPED_TIDS = {  # 2026-10-13 保守去重删除的 4 条（train_id 全量）
    "6aa4bfe2e2b0cadc244aa525", "6aa4bfe2e2b0cadc244acde8",
    "6aa4bfe2e2b0cadc244a9c96", "6aa4bfe2e2b0cadc244acc5a",
}


def norm_name(n):
    return re.sub(r"\([^)]*\)", "", str(n)).replace("ヶ", "ヶ").replace("駅", "").strip()


def trips_from(path):
    d = json.load(open(path, encoding="utf-8"))
    tmaps = json.load(open(os.path.join(LIVE, "tmaps.json"), encoding="utf-8"))
    trips = []
    for r in d["T"]:
        tm = tmaps.get(str(r["t"]))
        if not tm or not tm.get("s_jas") or len(tm["s_jas"]) < 2:
            continue
        s = [int(x) for x in r["s"].split(",")]
        N = len(tm["s_jas"])
        if len(s) != 2 * N - 2:
            continue
        jas_n = [norm_name(x) for x in tm["s_jas"]]
        dep = [0.0] * N
        dep[0] = s[0]
        for i in range(1, N):
            dep[i] = dep[i - 1] + s[2 * i - 1] + (s[2 * i] if 2 * i < len(s) else 0)
        w0, w1 = [int(x) for x in r["w"].split(",")]
        trips.append({"tid": r["_"], "t": r["t"], "i": r["i"], "jasN": jas_n, "N": N,
                      "dep": dep, "w0": w0, "w1": w1})
    return trips, tmaps


COUPLE_CLASSES = {
    "Hayabusa", "Komachi", "Yamabiko", "Tsubasa", "Toki", "Tanigawa",
    "Sakura", "Tsubame", "特", "新", "関", "紀",
}


def couplings_new(trips):
    """与 index.html buildCouplings（2026-10-13 起, 含车种白名单）逐条对齐的规则。"""
    by_dep = {}
    for t in trips:
        if t["N"] < 4:
            continue
        by_dep.setdefault(t["dep"][0], []).append(t)
    pairs = set()
    for bucket in by_dep.values():
        if len(bucket) < 2:
            continue
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                A, B = bucket[a], bucket[b]
                if A["i"] not in COUPLE_CLASSES or B["i"] not in COUPLE_CLASSES:
                    continue  # 车种白名单: 近郊 快/普/急/準/各/直/区 不併结
                if A["jasN"][0] != B["jasN"][0] or A["jasN"][1] != B["jasN"][1]:
                    continue
                best = end_a = end_b = 0
                for i in range(A["N"]):
                    for j in range(B["N"]):
                        if A["jasN"][i] != B["jasN"][j]:
                            continue
                        k = 0
                        while i + k < A["N"] and j + k < B["N"] and A["jasN"][i + k] == B["jasN"][j + k]:
                            k += 1
                        if k > best:
                            best, end_a, end_b = k, i + k - 1, j + k - 1
                if best < 4:
                    continue
                st_a, st_b = end_a - best + 1, end_b - best + 1
                if st_a != 0 or st_b != 0:
                    continue
                if end_a == A["N"] - 1 and end_b == B["N"] - 1:
                    continue
                if A["i"] == B["i"]:
                    continue
                t0 = max(A["dep"][st_a], B["dep"][st_b])
                t1 = min(A["dep"][end_a], B["dep"][end_b])
                w0, w1 = max(A["w0"], B["w0"]), min(A["w1"], B["w1"])
                if t0 > w1 or t1 < w0:
                    continue
                pairs.add((frozenset((A["i"], B["i"])), A["jasN"][end_a], A["tid"], B["tid"]))
    return pairs


def main():
    failures = []
    def check(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failures.append(name)

    for n in ("wd", "sa", "su"):
        trips, _ = trips_from(os.path.join(LIVE, f"trains_{n}.json"))
        pairs = couplings_new(trips)
        def has(a, b, split=None):
            return any(x[0] == frozenset((a, b)) and (split is None or x[1] == split) for x in pairs)
        print(f"--- trains_{n}.json: {len(pairs)} 对 ---")
        check(f"{n}: 所有对均在车种白名单内",
              all(x[0] <= frozenset(COUPLE_CLASSES) for x in pairs))
        check(f"{n}: かがやき×つばさ(大宫)消失", not has("Kagayaki", "Tsubasa"))
        check(f"{n}: かがやき×はくたか 消失", not has("Kagayaki", "Hakutaka"))
        check(f"{n}: やまびこ×つばさ(大宫)消失", not has("Yamabiko", "Tsubasa", "大宮"))
        check(f"{n}: やまびこ×はやぶさ 消失", not has("Yamabiko", "Hayabusa"))
        check(f"{n}: ひかり×さくら(博多)消失", not has("Hikari", "Sakura"))
        # 近郊/私铁/市电错标签(白名单过滤)全部消失
        for name, a, b in [("鹿児島市電 普×直", "普", "直"), ("相模原 快×各", "快", "各"),
                           ("新羽 快×普", "快", "普"), ("立川 中×快", "中", "快"),
                           ("豊中 急×準", "急", "準"), ("成増 準×普", "準", "普")]:
            check(f"{n}: {name} 不标注", not has(a, b))
        if n == "wd":
            check(f"{n}: 总数落在合理区间(白名单后 ~85)", 70 <= len(pairs) <= 110)
            check(f"{n}: はやぶさ×こまち(盛冈)保留", has("Hayabusa", "Komachi", "盛岡"))
            check(f"{n}: やまびこ×つばさ(福岛)保留", has("Yamabiko", "Tsubasa", "福島"))
            check(f"{n}: とき×たにがわ(越后汤泽)保留", has("Toki", "Tanigawa", "越後湯沢"))
            check(f"{n}: 関空×紀州路(日根野)保留", has("関", "紀", "日根野"))
            check(f"{n}: さくら×つばめ(新水俣)保留", has("Sakura", "Tsubame", "新水俣"))
        for tid in DROPPED_TIDS:
            used = any(tid in (p[2], p[3]) for p in pairs)
            check(f"{n}: 去重删除记录 {tid[-8:]} 未参与併结", not used)

    print("\n结果: " + ("全部通过 ✔" if not failures else f"失败 {len(failures)} 项 ✘"))
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()

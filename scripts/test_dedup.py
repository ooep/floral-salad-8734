#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_dedup.py — 本地验证 build_trains.dedup_express_dups 的保守去重逻辑。

数据源: 仓库 data/live/trains_{wd,sa,su}.json（真实时刻表快照，无网络访问）。

用例:
  1. きりしま #2933 (18:39/18:40 重复)          → 合并为 1 条（保留较早 18:39）
  2. こまち 18:18/18:19 重复                    → 合并
  3. 特急 9:59/10:00 重复                       → 合并
  4. 特急 13:56/13:57 重复                      → 合并
  5. 快速 21:49/21:50 同形但车种=快             → 不合并（保守排除，近郊真实列车）
  6. みずほ #14387/#324（熊本指令边界改号，tmap 不同）→ 不合并
  7. はやぶさ #5937/#4832（新青森跨公司直通，tmap 不同）→ 不合并
  8. はやぶさ+こまち 并结组（同发车、不同 tmap）→ 全部保留
  9. 普通/快速类删除数必须为 0（绝不误删近郊真实列车）
  10. 全量: 合并后存活记录的字段与输入完全一致（不损坏数据）
  11. 端到端: 从 live 重建源（注入合成重复对） → 跑 build_trains.py → 输出无损重建当前 live 数据
     （注入的重复对被合并, 可见 stdout「保守去重合并: 4」）

运行: python3 scripts/test_dedup.py
（2026-10-13 起 data/live 已是去重后数据, 测试改为按保留记录合成 +1 分钟副本注入输入, 自包含可复现）
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_trains import dedup_express_dups, MERGE_CLASSES  # noqa: E402

LIVE = os.path.join(REPO, "data", "live")

def build_recs():
    recs = {}
    for n in ("wd", "sa", "su"):
        with open(os.path.join(LIVE, f"trains_{n}.json"), encoding="utf-8") as f:
            d = json.load(f)
        for tr in d["T"]:
            recs.setdefault(tr["_"], tr)
    return recs

def find_dup_pair(recs, icon, dep0):
    """返回共享 (t,r,rel) 且发车为 dep0/dep0+1 的相邻对 [(dep, tid), ...]。
    同形组内可能有多个真实班次（如 596/716/836/837），只取 dep0 开始的相邻对。"""
    groups = {}
    for tid, rec in recs.items():
        if rec["i"] != icon:
            continue
        s = rec["s"].split(",")
        groups.setdefault((rec["t"], rec["r"], ",".join(s[1:])), []).append((int(s[0]), tid))
    for lst in groups.values():
        lst.sort()
        for i in range(len(lst) - 1):
            if lst[i][0] == dep0 and lst[i + 1][0] - lst[i][0] <= 1:
                return lst[i:i + 2]
    return None

def stops_from_s(s):
    """compact s -> fetch_timetables.py 源格式 stops[]（分钟 -> HH:MM 无损往返）"""
    vals = list(map(int, s.split(",")))
    N = len(vals) // 2 + 1
    fmt = lambda m: f"{m // 60}:{m % 60:02d}"
    dep0 = vals[0]
    stops = [{"arr": None, "dep": fmt(dep0)}]
    dep = dep0
    for i in range(1, N):
        arr = dep + vals[2 * i - 1]
        de = arr + (vals[2 * i] if 2 * i < len(vals) else 0)
        stops.append({"arr": fmt(arr), "dep": fmt(de)})
        dep = de
    return stops

def main():
    failures = []
    def check(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failures.append(name)

    recs = build_recs()
    # 2026-10-13 起 data/live 已是去重后数据, 原重复对已不在仓库内。
    # 为使测试自包含（不依赖会被部署覆盖的旧快照）, 按已知 4 组重复的
    # 「保留记录」合成 +1 分钟副本注入输入, 重建当年触发的场景。
    for t, icon, dep0 in [(2933, "特", 1119), (4024, "Komachi", 1098),
                          (13987, "特", 599), (12288, "特", 836)]:
        base = next((tid, r) for tid, r in recs.items()
                    if r["t"] == t and r["i"] == icon and r["s"].startswith(f"{dep0},"))
        tid, r = base
        dup = dict(r)
        dup["_"] = tid + "_DUP"
        vals = r["s"].split(",")
        vals[0] = str(int(vals[0]) + 1)          # 仅发车分钟 +1, 相对时刻串(s[1:])保持相同
        dup["s"] = ",".join(vals)
        recs[dup["_"]] = dup
    before = dict(recs)
    merged, dropped = dedup_express_dups(recs)
    print(f"输入 {len(before)} 条 → 合并后 {len(merged)} 条, 合并删除 {dropped} 条\n")

    # 1 きりしま #2933
    k = [r for r in merged.values() if r["t"] == 2933]
    check("1. きりしま#2933 两条合并为 1 条, 保留 18:39(1119)", len(k) == 1 and k[0]["s"].startswith("1119,"))

    # 2-4 其余三组已知重复
    for name, icon, dep0 in [("2. こまち 18:18/18:19 合并", "Komachi", 1098),
                             ("3. 特急 9:59/10:00 合并", "特", 599),
                             ("4. 特急 13:56/13:57 合并", "特", 836)]:
        lst = find_dup_pair(before, icon, dep0)
        ok = lst is not None and lst[0][1] in merged and all(tid not in merged for _, tid in lst[1:])
        check(name, ok)

    # 5 快速 21:49/21:50 不合并（保守排除）
    lst = find_dup_pair(before, "快", 1309)
    ok = lst is not None and all(tid in merged for _, tid in lst)
    check("5. 快速 21:49/21:50 同形不合并（车种=快, 保守排除）", ok)

    # 6 みずほ 熊本改号拆两条（tmap 14387/324 不同）不合并
    mz = [tid for tid, r in before.items() if r["t"] in (14387, 324) and r["s"].startswith("954,")]
    check("6. みずほ#14387/#324 边界拆条 2 条全部保留", len(mz) == 2 and all(tid in merged for tid in mz))

    # 7 はやぶさ 新青森跨公司直通拆两条不合并
    hb = [tid for tid, r in before.items() if r["t"] in (5937, 4832) and r["s"].startswith("517,")]
    check("7. はやぶさ#5937/#4832 跨公司拆条 2 条全部保留", len(hb) == 2 and all(tid in merged for tid in hb))

    # 8 はやぶさ+こまち 并结组全部保留（同发车时刻、不同 tmap）
    groups = {}
    for tid, r in before.items():
        if r["i"] in ("Hayabusa", "Komachi"):
            groups.setdefault((r["r"], r["s"].split(",")[0]), set()).add(r["i"])
    coup_groups = [k for k, icons in groups.items() if len(icons) > 1]
    ok = True
    for key in coup_groups:
        c_before = sum(1 for tid, r in before.items() if r["r"] == key[0] and r["s"].split(",")[0] == key[1] and r["i"] in ("Hayabusa", "Komachi"))
        c_after = sum(1 for tid, r in merged.items() if r["r"] == key[0] and r["s"].split(",")[0] == key[1] and r["i"] in ("Hayabusa", "Komachi"))
        if c_before != c_after:
            ok = False
            print(f"      并结组 {key}: {c_before} -> {c_after}")
    check(f"8. はやぶさ+こまち 并结组 {len(coup_groups)} 组全部保留", ok and len(coup_groups) > 0)

    # 9 删除的必须全部是 MERGE_CLASSES（普/快/各绝不误删）
    dropped_recs = [before[tid] for tid in set(before) - set(merged)]
    check("9. 删除记录全部属于优等列车车种（普/快/各 0 误删）",
          len(dropped_recs) == dropped and all(r["i"] in MERGE_CLASSES for r in dropped_recs) and dropped == 4)

    # 10 存活记录字段与输入一致
    check("10. 存活记录字段与输入逐条一致", all(merged[tid] == before[tid] for tid in merged))

    # 11 端到端: 重建源 → build_trains.py
    orig_counts = {}
    for n in ("wd", "sa", "su"):
        with open(os.path.join(LIVE, f"trains_{n}.json"), encoding="utf-8") as f:
            orig_counts[n] = json.load(f)["n"]
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src"); out = os.path.join(tmp, "out")
        os.makedirs(src)
        trains = [{"train_id": tid, "tmap_id": r["t"], "icon": r["i"], "rday": r["r"],
                   "origin": "", "dest": "", "stops": stops_from_s(r["s"])} for tid, r in before.items()]
        with open(os.path.join(src, "000_roundtrip.json"), "w", encoding="utf-8") as f:
            json.dump({"line": "__roundtrip__", "rw_ids": [], "fetched_at": "", "trains": trains}, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, os.path.join(HERE, "build_trains.py"), "--src", src, "--out", out],
                           capture_output=True, text=True)
        ok = r.returncode == 0
        sizes = {}
        if ok:
            for n in ("wd", "sa", "su"):
                try:
                    dd = json.load(open(os.path.join(out, f"trains_{n}.json"), encoding="utf-8"))
                    sizes[n] = dd["n"]
                    assert isinstance(dd["T"], list)
                except Exception:
                    ok = False
        check("11. 端到端 build_trains.py 成功且无损重建当前 live 数据（合成重复被合并）",
              ok and sizes.get("wd") == orig_counts["wd"]
              and sizes.get("sa") == orig_counts["sa"]
              and sizes.get("su") == orig_counts["su"])
        if ok:
            dd = json.load(open(os.path.join(out, "trains_sa.json"), encoding="utf-8"))
            k = [x for x in dd["T"] if x["t"] == 2933]
            check("11b. 端到端输出中 きりしま#2933 剩 1 条且为 18:39", len(k) == 1 and k[0]["s"].startswith("1119,"))
        merge_line = [l for l in r.stdout.splitlines() if "去重" in l]
        print("  (端到端 stdout 合并行: " + (merge_line[-1] if merge_line else "未找到") + ")")

    print(f"\n结果: {'全部通过 ✔' if not failures else '失败 %d 项 ✘' % len(failures)}")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()

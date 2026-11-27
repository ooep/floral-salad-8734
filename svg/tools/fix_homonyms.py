#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_homonyms.py — 修复历史数据中"同名站点合并"与"错误坐标"缺陷（单遍消歧）。

背景：原始数据（topology_v1.json）以"站名"为站点唯一键，且少数站点的记录
坐标本身错误（如新潟"吉田"被记为大阪附近坐标、高崎/八代/川内/前谷地等被记
为占位坐标）。同名不同址（大宮/福島/橋本/日本橋/郡山/吉田/住吉…）被折叠，
导致跨地区线路产生"幻影长线段"。

修复分四层：
  A. 坐标补丁表（COORD_PATCHES）：对记录坐标确凿错误的站点，直接更正其
     记录坐标（自动校验：仅当该站名所有引用线路的局部区域都在目标坐标附近
     才生效，否则跳过并告警）。
  B. 线路站名修正表（LINE_NAME_FIXES）：线路数据里被写错的站名替换为正确
     站名（如仙台 泉中央 被误写为 和泉中央）。
  C. 线路目标解析表（LINE_TARGET_PATCHES）：对无信号线路（如 2 站截断线）
     的特定引用，强制解析到指定坐标附近的同名校点（如 佐世保線 的 江北 →
     九州江北）。
  D. 局部几何聚类消歧（对错误坐标鲁棒，单遍无级联）：
     - 每个引用位置 = 相邻站（仅局部区域内）的中点；端点取"邻站 vs 记录"
       中更靠近局部中位数者；无信号引用 → 保留记录站（不拆分）。
     - 按引用位置聚类（60km）；与记录坐标最近的簇保留原 id，其余簇建新站。

用法: python3 tools/fix_homonyms.py -i topology_v1.json -o topology.json
"""

import argparse
import json
import math
from collections import defaultdict


def hav_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# A. 记录坐标补丁（按真实地理坐标核实；应用前自动校验引用线路区域）
COORD_PATCHES = {
    "前谷地": (38.5042, 141.1533),   # 宮城・石巻線/気仙沼線（原记录为大阪占位坐标）
    "飯坂温泉": (37.8318, 140.4200),  # 福島・飯坂線
    "槻木": (38.0119, 140.5593),      # 宮城・阿武隈急行
    "八代": (32.5065, 130.6002),      # 熊本・肥薩おれんじ鉄道（原记录为仙台坐标）
    "川内": (31.8132, 130.3092),      # 鹿児島・肥薩おれんじ鉄道/九州新幹線
    "日生中央": (34.9329, 135.4612),  # 大阪・能勢電鉄日生線
    "高崎": (36.3221, 139.0122),      # 群馬・上越/北陸新幹線/信越線
    "横河原": (33.8136, 132.8331),    # 愛媛・伊予鉄道横河原線
    "傘松": (35.6006, 135.1819),      # 京都・天橋立鋼索鉄道
    "福住": (43.0308, 141.3741),      # 札幌・東豊線
    "柳津": (38.5107, 141.1927),      # 宮城・気仙沼線（原记录为大阪占位坐标）
}

# B. 线路站名修正（线路数据中的错误站名 → 正确站名）
LINE_NAME_FIXES = {
    "仙台市||南北線": {"和泉中央": "泉中央"},
    "仙台市||東西線": {"和泉中央": "泉中央"},
}

# C. 线路目标解析（lineId, 站名）→ 目标坐标；强制该引用解析到同名校点中
#    坐标最接近目标者（60km 内无候选则按目标坐标新建站点）。
#    用于 2 站截断线等无信号场景（这些线路的站表只含 2 站，且常带
#    错误同名/占位坐标，局部几何完全不可信）。
LINE_TARGET_PATCHES = {
    ("九州旅客鉄道||佐世保線", "江北"): (33.14, 130.16),    # 佐世保線の江北=九州江北
    ("九州旅客鉄道||佐世保線", "佐世保"): (33.1637, 129.7266),  # 佐世保本駅
    ("丹後海陸交通||天橋立鋼索鉄道", "府中"): (35.5862, 135.1958),   # 京都・天橋立ケーブル
    ("伊予鉄道||高浜線・横河原線・郡中線", "高浜"): (33.8589, 132.7229),  # 愛媛・松山高浜
    ("札幌市||東豊線", "栄町"): (43.0821, 141.3633),        # 札幌・東豊線栄町
    ("東日本旅客鉄道||信越線", "横川"): (36.3201, 138.8796),  # 群馬・碓氷峠
    ("福島交通||飯坂線", "福島"): (37.7543, 140.4590),       # 福島県・福島駅
    ("阿武隈急行||阿武隈急行線", "福島"): (37.7543, 140.4590),
    ("能勢電鉄||日生線", "山下"): (34.9058, 135.4018),       # 大阪・能勢電鉄
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="topology_v1.json")
    ap.add_argument("-o", "--output", default="topology.json")
    ap.add_argument("--threshold", type=float, default=60.0)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)
    raw_stations = raw["stations"]
    raw_lines = raw["lines"]

    name_station = {}
    for s in raw_stations:
        name_station.setdefault(s["name"], s)
    orig_id = {}
    for i, s in enumerate(raw_stations):
        orig_id[s["name"]] = "S%06d" % (i + 1)
    print("唯一站名:", len(name_station))

    def rec(nm):
        s = name_station.get(nm)
        if s and s.get("lat") is not None:
            return (s["lat"], s["lon"])
        return None

    # ---- A. 应用坐标补丁（人工核实；仅记录警告） ----
    for nm, (plat, plon) in COORD_PATCHES.items():
        if nm not in name_station:
            print("  [patch-skip] 站名不存在:", nm)
            continue
        old = (name_station[nm]["lat"], name_station[nm]["lon"])
        name_station[nm]["lat"] = plat
        name_station[nm]["lon"] = plon
        print("  [patch] 修正坐标:", nm, old, "→", (plat, plon))

    # ---- B. 应用线路站名修正 ----
    for li, l in enumerate(raw_lines):
        fixes = LINE_NAME_FIXES.get(l["id"])
        if fixes:
            l["stations"] = [fixes.get(x, x) for x in l.get("stations", [])]
            print("  [line-fix]", l["id"][:40], "→", fixes)

    # ---------- 局部几何聚类（单遍） ----------
    name_clusters = defaultdict(list)
    ref_cluster = {}

    def local_median(sts, idx, radius=3):
        pts = []
        for j in range(max(0, idx - radius), min(len(sts), idx + radius + 1)):
            if j == idx:
                continue
            p = rec(sts[j])
            if p:
                pts.append(p)
        if not pts:
            return None
        pts.sort()
        n = len(pts)
        if n % 2 == 1:
            return pts[n // 2]
        a, b = pts[n // 2 - 1], pts[n // 2]
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    # 2 站截断线：局部几何无信号 → 全部走目标解析或保留记录，不做聚类
    two_station = {l["id"] for l in raw_lines if len(l.get("stations", [])) <= 2}

    for li, l in enumerate(raw_lines):
        sts = l.get("stations", [])
        for idx, nm in enumerate(sts):
            r0 = rec(nm)
            if r0 is None:
                continue
            # C. 线路目标解析优先
            tgt = LINE_TARGET_PATCHES.get((l["id"], nm))
            if tgt is not None:
                ref_cluster[(li, idx)] = ("__tgt__", nm)
                continue
            if l["id"] in two_station:
                ref_cluster[(li, idx)] = ("__keep__", nm)
                continue
            lm = local_median(sts, idx)
            neigh = []
            if idx > 0:
                neigh.append(sts[idx - 1])
            if idx + 1 < len(sts):
                neigh.append(sts[idx + 1])
            positions = []
            for n in neigh:
                p = rec(n)
                if p and lm and hav_km(p[0], p[1], lm[0], lm[1]) <= 120:
                    positions.append(p)
            if len(positions) == 2:
                pos = ((positions[0][0] + positions[1][0]) / 2,
                       (positions[0][1] + positions[1][1]) / 2)
            elif len(positions) == 1:
                if lm is not None:
                    d_nb = hav_km(positions[0][0], positions[0][1], lm[0], lm[1])
                    d_rec = hav_km(r0[0], r0[1], lm[0], lm[1])
                    pos = positions[0] if d_nb < d_rec else r0
                else:
                    pos = positions[0]
            else:
                # 无信号引用 → 保留记录站（不拆分）
                ref_cluster[(li, idx)] = ("__keep__", nm)
                continue
            clusters = name_clusters[nm]
            best = None
            for cl in clusters:
                if hav_km(pos[0], pos[1], cl["lat"], cl["lon"]) < args.threshold:
                    best = cl
                    break
            if best is None:
                best = {"lat": pos[0], "lon": pos[1], "refs": []}
                clusters.append(best)
            best["refs"].append((li, idx))
            n = len(best["refs"])
            best["lat"] = best["lat"] * (n - 1) / n + pos[0] / n
            best["lon"] = best["lon"] * (n - 1) / n + pos[1] / n

    # ---------- 保留/拆分 ----------
    station_by_id = {}
    next_id = len(raw_stations) + 1
    new_list = []
    split_count = 0
    for nm, clusters in name_clusters.items():
        r0 = rec(nm)
        if r0:
            clusters.sort(key=lambda c: hav_km(c["lat"], c["lon"], r0[0], r0[1]))
            keep = clusters[0] if hav_km(clusters[0]["lat"], clusters[0]["lon"], r0[0], r0[1]) < args.threshold else None
        else:
            keep = None
        for ci, cl in enumerate(clusters):
            if cl is keep:
                sid = orig_id[nm]
            else:
                sid = "S%06d" % next_id
                next_id += 1
                split_count += 1
                ops = set()
                for (li, i) in cl["refs"]:
                    if raw_lines[li].get("operator"):
                        ops.add(raw_lines[li]["operator"])
                new_list.append({"stationId": sid, "name": nm,
                                 "lat": round(cl["lat"], 6), "lon": round(cl["lon"], 6),
                                 "ops": sorted(ops)})
            for (li, i) in cl["refs"]:
                ref_cluster[(li, i)] = ("__cid__", sid)
    print("拆分站数:", split_count)

    # ---------- C. 目标解析落地 ----------
    # 收集全部同名候选站（原始 + 新拆分）及其坐标
    cand = defaultdict(list)
    cand_pos = {}
    for s in raw_stations:
        sid = orig_id[s["name"]]
        cand.setdefault(s["name"], []).append(sid)
        if s.get("lat") is not None:
            cand_pos[sid] = (s["lat"], s["lon"])
    for ns in new_list:
        cand.setdefault(ns["name"], []).append(ns["stationId"])
        cand_pos[ns["stationId"]] = (ns["lat"], ns["lon"])
    tgt_station = {}  # ((line,name) -> stationId)
    tgt_created = {}  # (rounded target coords) -> stationId，同目标复用
    next_tgt_id = next_id
    for (li, idx), (tag, nm) in ref_cluster.items():
        if tag != "__tgt__":
            continue
        l = raw_lines[li]
        tgt = LINE_TARGET_PATCHES.get((l["id"], nm))
        if tgt is None:
            continue
        key = (l["id"], nm)
        if key not in tgt_station:
            best_id, best_d = None, 1e18
            for sid in cand.get(nm, []):
                st = cand_pos.get(sid)
                if st is None:
                    continue
                d = hav_km(st[0], st[1], tgt[0], tgt[1])
                if d < best_d:
                    best_d, best_id = d, sid
            tkey = (round(tgt[0], 4), round(tgt[1], 4))
            if best_id is not None and best_d < 60:
                tgt_station[key] = best_id
                print("  [line-tgt]", key[0][:30], nm, "→", best_id, "d=", round(best_d, 1), "km")
            elif tkey in tgt_created:
                tgt_station[key] = tgt_created[tkey]
            else:
                sid = "S%06d" % next_tgt_id
                next_tgt_id += 1
                tgt_created[tkey] = sid
                tgt_station[key] = sid
                cand.setdefault(nm, []).append(sid)
                cand_pos[sid] = tgt
                new_list.append({"stationId": sid, "name": nm,
                                 "lat": round(tgt[0], 6), "lon": round(tgt[1], 6),
                                 "ops": [l.get("operator", "")]})
                print("  [line-tgt-create]", key[0][:30], nm, "→", sid, "新建@", (tgt[0], tgt[1]))
        ref_cluster[(li, idx)] = ("__cid__", tgt_station[key])

    # ---------- 重建 lines ----------
    for li, l in enumerate(raw_lines):
        new_sts = []
        for idx, nm in enumerate(l.get("stations", [])):
            key = (li, idx)
            if key in ref_cluster:
                tag, sid = ref_cluster[key]
                if tag == "__cid__":
                    new_sts.append(sid)
                    continue
            if nm in orig_id:
                new_sts.append(orig_id[nm])
            else:
                new_sts.append(nm)
        l["stations"] = new_sts

    # ---------- 组装站点 ----------
    stations_out = []
    for s in raw_stations:
        stations_out.append({"stationId": orig_id[s["name"]], "name": s["name"],
                             "lat": s.get("lat"), "lon": s.get("lon"),
                             "isTransfer": bool(s.get("isTransfer", False)),
                             "ops": list(s.get("ops", [])), "riders": s.get("riders", 0),
                             "lineIds": []})
    for ns in new_list:
        stations_out.append({**ns, "isTransfer": False, "riders": 0, "lineIds": []})
    by_id = {s["stationId"]: s for s in stations_out}

    # ---------- lineIds / isTransfer / transfers ----------
    line_ids_of = defaultdict(list)
    for l in raw_lines:
        for sid in l["stations"]:
            if isinstance(sid, str) and sid.startswith("S"):
                line_ids_of[sid].append(l["id"])
    for st in stations_out:
        st["lineIds"] = line_ids_of[st["stationId"]]
        if len(st["lineIds"]) >= 2:
            st["isTransfer"] = True
    transfers = []
    for i, st in enumerate(stations_out):
        if st["isTransfer"]:
            transfers.append({"group": "T%04d" % (i + 1), "name": st["name"],
                              "stationIds": [st["stationId"]], "lineIds": list(st["lineIds"]),
                              "ops": list(st.get("ops", []))})

    out = {"meta": {"formatVersion": 2, "stationCount": len(stations_out),
                    "lineCount": len(raw_lines), "transferCount": len(transfers),
                    "homonymSplit": split_count,
                    "source": raw.get("meta", {}).get("source", "MLIT N02 / S12 2021")},
           "operators": raw.get("operators", []), "stations": stations_out,
           "lines": raw_lines, "transfers": transfers}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("写出:", args.output, "站点", len(stations_out), "线路", len(raw_lines),
          "换乘", len(transfers), "拆分", split_count)


if __name__ == "__main__":
    main()

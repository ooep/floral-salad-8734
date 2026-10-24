#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_platform_map_online.py —— 从 dokorail.jp【线上】拉取最新时刻表数据，
提取站台编号（pw 主数据 + pf 里程区间补充 + pat.json platformEdges OSM 番线），
与主站 tmaps 对齐，生成 mini-japanrail-3d/data/platform_map.json（version 5）。

线上端点（已实测可用）:
  index : https://dokorail.jp/rail/timetables/startup-v3-index.json?b=<build>
  bundle: https://tiles.dokorail.jp/timetables/v3/sha256/<sha>.json

v5 相对 v4 的改进（实测: UI 口径站位覆盖 47.2% → 66.6% → 67.0%, 具体单值 22890 → 23725, tmap 8747 → 9338 → 9341）:
  1. 全量线路:v3 构建时网络抖动只成功 ~379/557 条 bundle → 大量线路整体缺失;
     v4 对拉取失败重试 4 次,并用 /tmp/dkr_online 做持久缓存(可断点续跑)
  2. 坐标救援:站名对不上的停靠站,用 station_key_index.json 坐标在 250m 内
     找 doko 站（优先本班次已匹配 ≥2 站的线路;全局唯一近邻才允许跨线）,
     doko bundle 自带 lng/lat
  3. 取值回退链(v5):pw 单值 → pf 里程区间唯一值 → pat.json platformEdges
     (OSM 番线挂轨道边,与 pw/pf 互补,如山手線 pw 仅 3/32 而 platformEdges 31/32)
     单值 → pw 多值 → pe 多值。严格单调,不并集稀释具体单值
  4. 渲染端 platOk 括号区域校验保持不变（本脚本不再重复该过滤）

站台取值口径: pw = 车站级该线路站台全集（与 dokorail 站窗一致）;
dokorail 按「列车实时位置 × pf 区间」几何解析单班车番线,静态数据无法复刻,
pf 唯一时取其值是可得范围内最具体的近似。
"""
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMAPS = os.path.join(REPO, "data", "live", "tmaps.json")
SKEY = os.path.join(REPO, "mini-japanrail-3d", "data", "station_key_index.json")
OUT = os.path.join(REPO, "mini-japanrail-3d", "data", "platform_map.json")
CACHE = "/tmp/dkr_online"
os.makedirs(CACHE, exist_ok=True)

INDEX_URL = "https://dokorail.jp/rail/timetables/startup-v3-index.json"
BUNDLE_URL = "https://tiles.dokorail.jp/timetables/v3/sha256/{sha}.json"


def fetch(url, fp):
    if os.path.exists(fp) and os.path.getsize(fp) > 0:
        return True
    for att in range(4):
        subprocess.run(["curl", "-sL", "--noproxy", "*", "-m", "90", "-o", fp, url], check=False)
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            try:
                json.load(open(fp, encoding="utf-8"))
                return True
            except Exception:
                os.remove(fp)
        time.sleep(1 + att)
    return False


def norm(name):
    name = re.sub(r"\s+", "", name or "")
    return re.sub(r"[（(].*?[)）]", "", name)


def load_railways_online():
    idx_fp = os.path.join(CACHE, "startup-v3-index.json")
    if not fetch(INDEX_URL, idx_fp):
        sys.exit("startup index 拉取失败")
    idx = json.load(open(idx_fp, encoding="utf-8"))
    railways = {}
    n = 0
    for rid, v in idx["railways"].items():
        cals = (v.get("bundle") or {}).get("calendars") or {}
        fname = None
        for c in ("Weekday", "SaturdayHoliday"):
            if c in cals:
                fname = cals[c]["sha256"]
                break
        if not fname:
            continue
        fp = os.path.join(CACHE, fname + ".json")
        if not fetch(BUNDLE_URL.format(sha=fname), fp):
            print("  [warn] bundle 拉取失败,跳过:", rid)
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, list) or len(d) < 3:
            continue
        geo = d[2]
        if not isinstance(geo, dict):
            continue
        sts = (geo.get("railway") or {}).get("stations")
        if not isinstance(sts, list):
            continue
        stations = []
        rw_name = norm(((geo.get("railway") or {}).get("title") or {}).get("ja")) or rid
        for st in sts:
            if not isinstance(st, dict):
                continue
            ja = norm((st.get("title") or {}).get("ja"))
            if not ja:
                continue
            stations.append({
                "ja": ja, "pw": st.get("pw") or "", "pf": st.get("pf"),
                "m": st.get("m"), "lng": st.get("lng"), "lat": st.get("lat"),
                "pe": "",
            })
        # pat.json platformEdges:OSM 站台番线挂轨道边(按站序索引),与 pw 互补
        # (山手線 bundle pw 仅 3/32 站有值,platformEdges 31/32)
        if v.get("patterns") and v.get("operator"):
            pfp = os.path.join(CACHE, f"{rid}.pat.json")
            if fetch(f"https://dokorail.jp/rail/{v['operator']}/{rid}.pat.json", pfp):
                try:
                    pd = json.load(open(pfp, encoding="utf-8"))
                    pe = pd.get("platformEdges") or {}
                    per = defaultdict(set)
                    for k, edges in pe.items():
                        try:
                            ki = int(k)
                        except Exception:
                            continue
                        for e in edges.values():
                            if isinstance(e, dict) and re.fullmatch(r"\d+", str(e.get("number") or "")):
                                per[ki].add(str(e["number"]))
                    for ki, nums in per.items():
                        if 0 <= ki < len(stations):
                            stations[ki]["pe"] = ";".join(sorted(nums, key=lambda x: int(x)))
                except Exception:
                    pass
        if stations:
            railways[rid] = {"name": rw_name, "stations": stations, "idx": {}, "by_ja": {}}
            for k, st in enumerate(stations):
                railways[rid]["idx"].setdefault(st["ja"], k)
                railways[rid]["by_ja"].setdefault(st["ja"], st)
        n += 1
        if n % 50 == 0:
            print("  已拉取线路:", n)
    for rid, r in railways.items():
        r["id"] = rid
    return railways


def dist_m(a, b):
    dlng = (a[0] - b[0]) * math.cos((a[1] + b[1]) / 2 * math.pi / 180) * 111320
    dlat = (a[1] - b[1]) * 110570
    return math.hypot(dlng, dlat)


def plat_value(st):
    """严格单调回退链(不并集,防止把具体单值稀释成集合):
    pw 单值 → pf 里程区间唯一值 → platformEdges(OSM) 单值 → pw 多值 → pe 多值。
    pe 只在 v4 完全无值时兜底(山手線 pw 仅 3/32、pf 唯一 30/32、pe 31/32,三源高度重叠)"""
    pw = st.get("pw") or ""
    if pw and ";" not in pw:
        return pw
    pf = st.get("pf")
    m = st.get("m")
    if pf and isinstance(m, (int, float)):
        hits = []
        for r in pf:
            if isinstance(r, list) and len(r) >= 3 and isinstance(r[0], (int, float)) \
                    and isinstance(r[1], (int, float)) and r[0] <= m <= r[1]:
                hits.append(str(r[2]))
        if len(set(hits)) == 1:
            return hits[0]
    pe = st.get("pe") or ""
    if pe and ";" not in pe:
        return pe
    if pw:
        return pw
    return pe


def main():
    print("读取主站 tmaps / station_key_index ...")
    tm = json.load(open(TMAPS, encoding="utf-8"))
    skey = json.load(open(SKEY, encoding="utf-8"))
    print("  tmap 数:", len(tm), " 站名坐标索引:", len(skey))

    print("从 dokorail.jp 线上拉取线路 ...")
    railways = load_railways_online()
    total_st = sum(len(r["stations"]) for r in railways.values())
    print("  含站点线路:", len(railways), " 站点总数:", total_st)

    # 全局名字索引 + 0.01° 网格空间索引
    name_idx = defaultdict(list)
    grid = defaultdict(list)
    for rid, r in railways.items():
        for k, st in enumerate(r["stations"]):
            name_idx[st["ja"]].append((rid, k))
            if st["lng"] and st["lat"]:
                grid[(round(st["lat"] / 0.01), round(st["lng"] / 0.01))].append((rid, k, st))

    def nearby(lng, lat, radius_m=250):
        out = []
        dcell = int(radius_m / 1110) + 1
        cy, cx = round(lat / 0.01), round(lng / 0.01)
        for dy in range(-dcell, dcell + 1):
            for dx in range(-dcell, dcell + 1):
                for rid, k, st in grid.get((cy + dy, cx + dx), []):
                    if st["lng"] and dist_m((lng, lat), (st["lng"], st["lat"])) <= radius_m:
                        out.append((rid, k, st))
        return out

    def stop_coord(nm):
        cands = skey.get(norm(nm))
        if cands and cands[0].get("c"):
            return cands[0]["c"]
        return None

    def best_rid_from(stops, i):
        """从 i 起按连续站名序列找覆盖最长的 doko 线路"""
        best, best_len = None, 0
        s0 = norm(stops[i])
        for rid, k in name_idx.get(s0, []):
            r = railways[rid]
            ln, j, p = 1, i + 1, k
            while j < len(stops):
                ns = norm(stops[j])
                if not ns:
                    j += 1
                    continue
                npos = r["idx"].get(ns)
                if npos is None or npos != p + 1:
                    break
                ln += 1
                p = npos
                j += 1
            if ln > best_len:
                best, best_len = rid, ln
        return best, best_len

    out_t = {}
    total = rescued = single = tmaps_with = 0
    for tid, t in tm.items():
        stops = t.get("s_jas") or []
        n = len(stops)
        assigned = [None] * n  # (rid, station_idx)
        i = 0
        rid_stops = defaultdict(int)
        while i < n:
            if not norm(stops[i]):
                i += 1
                continue
            rid, ln = best_rid_from(stops, i)
            if not rid:
                i += 1
                continue
            r = railways[rid]
            for j in range(i, min(i + ln, n)):
                st = r["by_ja"].get(norm(stops[j]))
                if st:
                    assigned[j] = (rid, r["stations"].index(st))
                    rid_stops[rid] += 1
            i += ln
        # 坐标救援:名字没对上的停靠站,按坐标找 250m 内 doko 站
        # 优先:本班次已连续匹配 ≥2 站的线路;其次:全局唯一近邻
        for j in range(n):
            if assigned[j] or not norm(stops[j]):
                continue
            c = stop_coord(stops[j])
            if not c:
                continue
            hits = nearby(c[0], c[1])
            if not hits:
                continue
            pref = [h for h in hits if h[0] in rid_stops and rid_stops[h[0]] >= 2]
            pool = pref or hits if len(hits) == 1 else pref
            if len(pool) == 1:
                rid, k, _st = pool[0]
                assigned[j] = (rid, k)
                rescued += 1
        by_line = defaultdict(lambda: [None] * n)
        for j in range(n):
            a = assigned[j]
            if not a:
                continue
            rid, k = a
            st = railways[rid]["stations"][k]
            v = plat_value(st)
            if not v:
                continue
            by_line[railways[rid]["name"]][j] = v
            total += 1
            if ";" not in v:
                single += 1
        filtered = {ln: arr for ln, arr in by_line.items() if any(arr)}
        if filtered:
            tmaps_with += 1
            out_t[tid] = filtered

    print(f"匹配统计: 站位命中 {total}(单值 {single}, 坐标救援 {rescued}), 有站台数据的 tmap {tmaps_with}/{len(tm)}")
    result = {"version": 5, "source": "dokorail.jp 线上", "t": out_t}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("写出:", OUT, "大小:", os.path.getsize(OUT))


if __name__ == "__main__":
    main()

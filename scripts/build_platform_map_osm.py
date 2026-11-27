#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_platform_map_osm.py —— OSM 站台番线补空（v2：线路轨道走廊过滤）

用仓库内已有 OSM 站台几何（station_platforms.geojson，ODbL）为 platform_map.json（上游番线数据）
缺失（null）的站台番线补值，覆盖全部铁路公司。

v2 精度改进（针对大站"站级并集"污染单线路）：
  - 小站（站级并集番线数 <= 6）：直接按 车站名 -> OSM 番线并集 补入（小站物理上就只有几个番线，并集即精确）。
  - 大站（并集 > 6）：用该 tmap 的官方轨道几何（station_map.json segments + tmap_lids）
    做"轨道走廊过滤"——只保留质心距该线路轨道 <= 110m 的站台番线，排除并行/新干线/他社线的番线。
  - 过滤后无结果则保持 null（优雅降级），不改动上游已有值。

v3 格式统一（version 5）：
  - 新幹線号段守卫：非新幹線线路剔除 >=20 番（京都30-34/新大阪20-27/東京20-23 等新幹線高架站台
    与在来線走廊几何重叠，距离分不开，按号段规则兜底）；新幹線线路保留全量。
  - 输出值统一为上游规范：升序数字、分号分隔（"1;2;3"），保留真实存在的 0 番线（千葉/米子等）。

匹配流程：
  1. OSM platform(ref) 质心 -> 最近官方车站点（station_map.json stations/extra_stations，400m 内）
  2. tmap 轨道折线：tmap_lids -> segments（@ 链、负号反向）
  3. 逐 tmap 逐站补空，大站用 numpy 向量化计算站台到轨道窗口的最小距离
"""
import json
import math
import os
import re
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAT_GEOJSON = os.path.join(REPO, "mini-japanrail-3d", "data", "station_platforms.geojson")
STATION_MAP = os.path.join(REPO, "mini-japanrail-3d", "data", "station_map.json")
TMAPS = os.path.join(REPO, "data", "live", "tmaps.json")
PLAT_MAP = os.path.join(REPO, "mini-japanrail-3d", "data", "platform_map.json")
OUT = PLAT_MAP

MAX_DIST = 400.0      # 站台质心 -> 车站点最大匹配距离(米)
SMALL_UNION = 6       # 并集番线数 <= 该值走快速并集路径
TRACK_DIST = 110.0    # 大站站台质心到轨道折线的最大距离(米)
WINDOW = 200          # 轨道窗口半径(顶点数)


def centroid(coords, gtype):
    if gtype == "Point":
        return coords[0], coords[1]
    if gtype == "Polygon":
        pts = [(p[0], p[1]) for p in coords[0]]
    elif gtype == "LineString":
        pts = [(p[0], p[1]) for p in coords]
    elif gtype == "MultiPolygon":
        pts = [(p[0], p[1]) for p in coords[0][0]]
    elif gtype == "MultiLineString":
        pts = [(p[0], p[1]) for p in coords[0]]
    else:
        return None
    if not pts:
        return None
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def hav_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


REF_SPLIT = re.compile(r"[;,・、／/\s]+")


def parse_ref(r):
    if not r:
        return set()
    out = set()
    for tok in REF_SPLIT.split(str(r)):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"^(\d{1,2})$", tok)
        if m:
            out.add(int(m.group(1)))
    return out


SHINKANSEN_MIN = 20  # 在来線番线号段上限：>=20 基本只属于新幹線（京都30-34/新大阪20-27/東京20-23）


def refs_for_line(refs, line_name):
    """非新幹線线路剔除 >= SHINKANSEN_MIN 的番线（新幹線高架站台与在来線走廊几何重叠，
    距离过滤分不开，按号段规则兜底）；新幹線线路保留全量。"""
    if "新幹線" in line_name:
        return set(refs)
    return {r for r in refs if r < SHINKANSEN_MIN}


def build_polyline(lid_entries, segs):
    """tmap_lids -> 折线 [[lon,lat],...]；@ 链拆开、负号反向、去重复连接点。"""
    pts = []
    for entry in lid_entries:
        for lid_s in entry.split("@"):
            lid = int(lid_s)
            seg = segs.get(str(abs(lid)))
            if not seg:
                continue
            sp = seg if lid > 0 else list(reversed(seg))
            if pts and pts[-1] == sp[0]:
                pts.extend(sp[1:])
            else:
                pts.extend(sp)
    return pts


def track_refs(cands, poly, p_lon, p_lat):
    """大站轨道过滤：cands=[(lon,lat,refs),...]，返回质心距折线窗口 <= TRACK_DIST 的 refs 并集。"""
    if not cands or len(poly) < 3:
        return None
    poly = np.asarray(poly, dtype=np.float64)  # (n,2) [lon,lat]
    # 车站点 -> 最近顶点索引（全折线向量化）
    d = (poly[:, 0] - p_lon) ** 2 + ((poly[:, 1] - p_lat) * math.cos(math.radians(p_lat))) ** 2
    vi = int(np.argmin(d))
    a = max(0, vi - WINDOW)
    b = min(len(poly), vi + WINDOW + 1)
    win = poly[a:b]
    # 逐候选站台：到窗口所有线段的距离（向量化）
    keep = set()
    for lon, lat, refs in cands:
        C = np.array([[lon, lat]], dtype=np.float64)
        P0 = win[:-1]
        P1 = win[1:]
        dx = P1[:, 0] - P0[:, 0]
        dy = (P1[:, 1] - P0[:, 1]) * math.cos(math.radians(lat))
        seg2 = dx * dx + dy * dy
        seg2[seg2 == 0] = 1e-12
        t = ((C[0, 0] - P0[:, 0]) * dx + (C[0, 1] - P0[:, 1]) * dy) / seg2
        t = np.clip(t, 0.0, 1.0)
        px = P0[:, 0] + t * dx
        py = P0[:, 1] + t * dy
        dist = np.sqrt((C[0, 0] - px) ** 2 + ((C[0, 1] - py) * math.cos(math.radians(lat))) ** 2)
        # 上式为"纬度度数"单位：1 度 ≈ 111.32km，换算成米后再与阈值比较
        dist_m = float(np.min(dist)) * 111320.0
        if dist_m <= TRACK_DIST:
            keep.update(refs)
    return keep if keep else None


def main():
    print("1) 读取 OSM 站台几何 ...")
    sp = json.load(open(PLAT_GEOJSON, encoding="utf-8"))
    feats = sp.get("features", [])
    platforms = []  # (centroid, refs)
    for f in feats:
        p = f.get("properties") or {}
        ref = p.get("ref")
        if not ref:
            continue
        g = f.get("geometry") or {}
        c = centroid(g.get("coordinates"), g.get("type"))
        if not c:
            continue
        refs = parse_ref(ref)
        if refs:
            platforms.append((c, refs))
    print("   带 ref 的 OSM 站台:", len(platforms), "/", len(feats))

    print("2) 读取官方车站点 ...")
    sm = json.load(open(STATION_MAP, encoding="utf-8"))
    stations = dict(sm.get("stations") or {})
    for es in sm.get("extra_stations") or []:
        if es.get("name") and es.get("coord"):
            stations.setdefault(es["name"], {"coord": es["coord"]})
    segs = sm.get("segments") or {}
    lids = sm.get("tmap_lids") or {}
    print("   车站点数:", len(stations), "| segments:", len(segs), "| tmap_lids:", len(lids))

    print("3) 站台 -> 最近车站匹配 ...")
    station_plats = defaultdict(list)   # 站名 -> [(lon,lat,refs),...]
    station_union = defaultdict(set)    # 站名 -> 番线并集
    dists = []
    matched = 0
    for c, refs in platforms:
        best_n, best_d = None, None
        for nm, st in stations.items():
            coord = st.get("coord")
            if not coord:
                continue
            d = hav_m(c[0], c[1], coord[0], coord[1])
            if best_d is None or d < best_d:
                best_d, best_n = d, nm
        if best_n is not None and best_d <= MAX_DIST:
            station_plats[best_n].append((c[0], c[1], refs))
            station_union[best_n].update(refs)
            dists.append(best_d)
            matched += 1
    if dists:
        dists.sort()
        print("   匹配站台:", matched, "| 距离中位 %.0fm / p90 %.0fm" % (
            dists[len(dists) // 2], dists[int(len(dists) * 0.9)]))
    big = sum(1 for u in station_union.values() if len(u) > SMALL_UNION)
    print("   有番线的车站:", len(station_union), "| 大站(并集>%d):" % SMALL_UNION, big)

    print("4) 读取 tmaps / platform_map ...")
    tm = json.load(open(TMAPS, encoding="utf-8"))
    pm = json.load(open(PLAT_MAP, encoding="utf-8"))
    t = pm.get("t", {})
    total_null = fill_union = fill_track = 0
    refsize = defaultdict(int)
    drop_track = 0
    big_cells = 0
    per_line_fill = defaultdict(int)
    track_samples = []

    for tid, by_rid in t.items():
        stops = (tm.get(tid) or {}).get("s_jas") or []
        pline = None
        for ln, arr in by_rid.items():
            for k, v in enumerate(arr):
                if v is not None:
                    continue
                total_null += 1
                if k >= len(stops):
                    continue
                nm = stops[k]
                union = station_union.get(nm)
                if not union:
                    continue
                if len(union) <= SMALL_UNION:
                    u = refs_for_line(union, ln)
                    if not u:
                        continue
                    arr[k] = ";".join(str(x) for x in sorted(u))
                    fill_union += 1
                    refsize[len(u)] += 1
                    per_line_fill[ln] += 1
                    continue
                # 大站 -> 轨道走廊过滤
                big_cells += 1
                st = stations.get(nm)
                cands = station_plats.get(nm)
                if not st or not cands:
                    drop_track += 1
                    continue
                if pline is None:
                    entries = lids.get(tid)
                    pline = build_polyline(entries, segs) if entries else []
                if not pline:
                    drop_track += 1
                    continue
                coord = st["coord"]
                kept = track_refs(cands, pline, coord[0], coord[1])
                if not kept:
                    drop_track += 1
                    continue
                kept = refs_for_line(kept, ln)
                if not kept:
                    drop_track += 1
                    continue
                val = ";".join(str(x) for x in sorted(kept))
                arr[k] = val
                fill_track += 1
                refsize[len(kept)] += 1
                per_line_fill[ln] += 1
                if len(track_samples) < 8:
                    track_samples.append((tid, ln, nm, sorted(union), sorted(kept)))

    print("5) 统计 ...")
    print("   null 总数:", total_null,
          "| 快速并集补:", fill_union,
          "| 轨道过滤补:", fill_track,
          "| 合计补:", fill_union + fill_track,
          "| 仍缺:", total_null - fill_union - fill_track)
    print("   大站候选单元:", big_cells, "| 过滤后丢弃(null):", drop_track)
    print("   轨道过滤样例 (tmap/线路/站: 并集 -> 过滤后):")
    for tid, ln, nm, u, k in track_samples:
        print("     %s %s %s: %s -> %s" % (tid, ln, nm, u, k))
    top_ln = sorted(per_line_fill.items(), key=lambda x: -x[1])[:10]
    print("   补得最多的线路:", top_ln)

    result = {
        "version": 5,
        "source": "上游线上 + OSM(ODbL)",
        "osm": {
            "filled": fill_union + fill_track,
            "union_filled": fill_union,
            "track_filled": fill_track,
            "stations": len(station_union),
            "platforms": matched,
            "shinkansen_min": SHINKANSEN_MIN,
            "license": "ODbL (© OpenStreetMap contributors)",
        },
        "t": t,
    }
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("写出:", OUT, "大小:", os.path.getsize(OUT))


if __name__ == "__main__":
    main()

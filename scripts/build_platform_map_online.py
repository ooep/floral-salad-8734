#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_platform_map_online.py —— 从 dokorail.jp【线上】拉取最新时刻表数据，
提取站台编号（pw 主数据 + pf 里程区间补充），与主站 tmaps 对齐，
生成 mini-japanrail-3d/data/platform_map.json（version 2）。

线上端点（已实测可用）:
  index : https://dokorail.jp/rail/timetables/startup-v3-index.json?b=<build>
  bundle: https://tiles.dokorail.jp/timetables/v3/sha256/<sha>.json

站台解析逻辑（与 dokorail 前端 bt() 一致）:
  pf 存在且当前站里程落在区间内 -> 用 pf 区间站台号（优先）
  否则用 pw（分号分隔站台号）
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMAPS = os.path.join(REPO, "data", "live", "tmaps.json")
OUT = os.path.join(REPO, "mini-japanrail-3d", "data", "platform_map.json")
CACHE = "/tmp/dkr_online"
os.makedirs(CACHE, exist_ok=True)

INDEX_URL = "https://dokorail.jp/rail/timetables/startup-v3-index.json"
BUNDLE_URL = "https://tiles.dokorail.jp/timetables/v3/sha256/{sha}.json"


def fetch(url, fp):
    if os.path.exists(fp) and os.path.getsize(fp) > 0:
        return True
    subprocess.run(["curl", "-sL", "--noproxy", "*", "-m", "60", "-o", fp, url], check=False)
    return os.path.exists(fp) and os.path.getsize(fp) > 0


def norm(name):
    name = re.sub(r"\s+", "", name or "")
    name = re.sub(r"[（(].*?[)）]", "", name)
    return name


def pf_platform(st):
    """pf: [[start,end,'站台号'],...]；当前站里程 m 落区间则取该号，否则取第一条"""
    pf = st.get("pf")
    if not pf:
        return None
    m = st.get("m")
    if isinstance(m, (int, float)):
        for rng in pf:
            if isinstance(rng, list) and len(rng) >= 3:
                try:
                    a, b, num = float(rng[0]), float(rng[1]), rng[2]
                    if a <= m <= b:
                        return str(num)
                except Exception:
                    pass
    for rng in pf:
        if isinstance(rng, list) and len(rng) >= 3:
            return str(rng[2])
    return None


def load_railways_online():
    idx_fp = os.path.join(CACHE, "startup-v3-index.json")
    if not fetch(INDEX_URL + "?b=" + "fc103c9484ec617061fbaf00e5855b1640281c9b", idx_fp):
        idx_fp = os.path.join(CACHE, "startup-v3-index.json")
        fetch(INDEX_URL, idx_fp)
    idx = json.load(open(idx_fp, encoding="utf-8"))
    railways = {}
    n = 0
    for rid, v in idx["railways"].items():
        bundle = (v.get("bundle") or {}).get("calendars") or {}
        fname = None
        for c in ("Weekday", "SaturdayHoliday"):
            if c in bundle:
                fname = bundle[c]["sha256"]
                break
        if not fname:
            continue
        fp = os.path.join(CACHE, fname + ".json")
        if not fetch(BUNDLE_URL.format(sha=fname), fp):
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
        seq, stations = [], []
        for st in sts:
            if not isinstance(st, dict):
                continue
            title = st.get("title") or {}
            ja = norm(title.get("ja"))
            if not ja:
                continue
            seq.append(ja)
            stations.append({
                "ja": ja, "en": title.get("en"), "id": st.get("id"),
                "sc": st.get("sc"), "pw": st.get("pw") or "",
                "pf": st.get("pf"), "m": st.get("m"),
            })
        if stations:
            railways[rid] = {"seq": seq, "stations": stations}
        n += 1
        if n % 50 == 0:
            print("  已拉取线路:", n)
    return railways


def match_tmap(stops, railways):
    n = len(stops)
    pws = [None] * n
    if n == 0:
        return pws
    cur_rail = None
    for i, raw in enumerate(stops):
        s = norm(raw)
        if not s:
            continue
        cand = []
        if cur_rail and s in cur_rail["idx"]:
            cand.append(cur_rail)
        for rid, r in railways.items():
            if rid == (cur_rail["id"] if cur_rail else None):
                continue
            if s in r["idx"]:
                cand.append(r)
        if not cand:
            if cur_rail is None:
                continue
            cur_rail = None
            continue
        if cur_rail is None:
            r = cand[0]
        else:
            prev_ja = norm(stops[i - 1])
            best, best_gap = None, 10 ** 9
            for rc in cand:
                gap = abs(rc["idx"][s] - rc["idx"].get(prev_ja, rc["idx"][s]))
                if gap < best_gap:
                    best_gap, best = gap, rc
            r = best or cand[0]
        st = r["by_ja"].get(s)
        if st:
            # 只用 pw（dokorail 静态确定数据，站窗行级也以此为准）。
            # pf 是里程区间默认层（如东京 1;2=中央线台），语义易错且新干线行
            # dokorail 根本不显示站台，故不引入，宁缺勿错。
            plat = st.get("pw") or ""
            if plat:
                pws[i] = plat
        cur_rail = r
    return pws


def main():
    print("读取主站 tmaps ...")
    tm = json.load(open(TMAPS, encoding="utf-8"))
    print("  tmap 数:", len(tm))

    print("从 dokorail.jp 线上拉取线路 ...")
    railways = load_railways_online()
    print("  含站点的线路数:", len(railways))
    for rid, r in railways.items():
        r["id"] = rid
        r["idx"] = {}
        r["by_ja"] = {}
        for k, st in enumerate(r["stations"]):
            r["idx"].setdefault(st["ja"], k)
            r["by_ja"].setdefault(st["ja"], st)
    total_st = sum(len(r["stations"]) for r in railways.values())
    print("  站点总数:", total_st)

    out_t = {}
    matched_lines = matched_st = total_st = 0
    for tid, t in tm.items():
        stops = t.get("s_jas") or []
        pws = match_tmap(stops, railways)
        total_st += len(stops)
        got = sum(1 for p in pws if p)
        matched_st += got
        if got:
            matched_lines += 1
            out_t[tid] = pws
    print("匹配统计: 线路 %d/%d, 站 %d/%d" % (matched_lines, len(tm), matched_st, total_st))

    result = {"version": 2, "source": "dokorail.jp 线上", "t": out_t}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("写出:", OUT, "大小:", os.path.getsize(OUT))


if __name__ == "__main__":
    main()

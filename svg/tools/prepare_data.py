#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_data.py — 将带经纬度的轨道交通原始 JSON 加工为 Tube-Map 渲染器所需的
通用数据格式（formatVersion 2）。

输入（旧格式，与 MLIT 数据源对应）:
    {
      "meta": {...},
      "operators": [{"name": "...", "enName": "..."}],
      "stations": [{"name": "...", "lat": ..., "lon": ..., "ops": [...], "isTransfer": bool, "riders": ...}],
      "lines":    [{"id": "...", "name": "...", "operator": "...", "color": "#...",
                    "stationCount": N, "totalKm": ..., "stations": ["站名", ...]}]
    }

输出（新格式）:
    {
      "meta": {"formatVersion": 2, ...},
      "operators": [{"id": "...", "name": "...", "enName": "..."}],
      "stations":  [{"stationId": "S000001", "name": "...", "lat": ..., "lon": ...,
                     "isTransfer": bool, "ops": [...], "lineIds": [...], "riders": ...}],
      "lines":     [{"id": "...", "name": "...", "operator": "...", "color": "#...",
                     "stationCount": N, "totalKm": ..., "stations": ["S000001", ...]}],
      "transfers": [{"group": "T0001", "name": "新宿", "stationIds": ["S000001"],
                     "lineIds": [...], "ops": [...]}]
    }

核心约定（渲染器依赖，不可破坏）:
  * stationId 为站点唯一键；lines[].stations 引用 stationId。
  * 同一物理换乘枢纽 = 同一组 stationId（本数据集中站名唯一，组内通常为 1 个站点；
    站名重复时同名站点归入同一组）。
  * 换乘关系 = transfers 数组中每个枢纽的 lineIds（在该枢纽交汇的所有线路）。
  * 渲染器不依赖任何站名/线路名硬编码，替换同格式 JSON 即可渲染其他网络。

用法:  python3 prepare_data.py topology.json -o topology_v2.json
"""

import argparse
import json
import sys
from collections import defaultdict


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_stations(raw, id_lookup):
    """为站点分配 stationId，并加入 lineIds（途经线路）。"""
    stations = []
    for idx, s in enumerate(raw):
        sid = "S%06d" % (idx + 1)
        station = {
            "stationId": sid,
            "name": s["name"],
            "lat": s.get("lat"),
            "lon": s.get("lon"),
            "isTransfer": bool(s.get("isTransfer", False)),
            "ops": list(s.get("ops", [])),
            "lineIds": [],
            "riders": s.get("riders"),
        }
        stations.append(station)
        if s["name"] in id_lookup:
            sys.stderr.write("警告: 站名重复 %r\n" % s["name"])
        id_lookup[s["name"]] = sid
    return stations


def build_lines(raw_lines, id_lookup, station_lines):
    """线路站点改引用 stationId，同时统计每个站点的途经线路。"""
    lines = []
    for l in raw_lines:
        sids = []
        missing = []
        for name in l["stations"]:
            sid = id_lookup.get(name)
            if sid is None:
                missing.append(name)
                continue
            sids.append(sid)
            station_lines[sid].append(l["id"])
        if missing:
            sys.stderr.write("警告: 线路 %s 存在未知站点 %d 个: %s\n"
                             % (l["id"], len(missing), missing[:5]))
        lines.append({
            "id": l["id"],
            "name": l["name"],
            "operator": l["operator"],
            "color": l.get("color"),
            "stationCount": l.get("stationCount", len(sids)),
            "totalKm": l.get("totalKm"),
            "stations": sids,
        })
    return lines


def build_transfers(stations, station_lines):
    """显式换乘关系：每个换乘枢纽 = 一组物理同址站点 + 交汇线路。"""
    transfers = []
    group_no = 0
    seen = set()
    for s in stations:
        if s["stationId"] in seen:
            continue
        n = len(station_lines.get(s["stationId"], []))
        is_tf = s["isTransfer"] or n >= 2
        if not is_tf:
            continue
        group_no += 1
        sids = [s["stationId"]]
        line_ids = sorted(set(station_lines.get(s["stationId"], [])))
        transfers.append({
            "group": "T%04d" % group_no,
            "name": s["name"],
            "stationIds": sids,
            "lineIds": line_ids,
            "ops": sorted(set(s["ops"])),
        })
        seen.add(s["stationId"])
    return transfers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    raw = load(args.input)
    id_lookup = {}
    station_lines = defaultdict(list)

    stations = build_stations(raw["stations"], id_lookup)
    lines = build_lines(raw["lines"], id_lookup, station_lines)

    # 写回每个站点的 lineIds
    for s in stations:
        s["lineIds"] = sorted(set(station_lines.get(s["stationId"], [])))

    transfers = build_transfers(stations, station_lines)

    out = {
        "meta": {
            "formatVersion": 2,
            "name": raw.get("meta", {}).get("name", "Rail Tube Map"),
            "generated": raw.get("meta", {}).get("generated", "tube-map topology"),
            "source": raw.get("meta", {}).get("source", ""),
            "stationCount": len(stations),
            "lineCount": len(lines),
            "transferCount": len(transfers),
        },
        "operators": [
            {"id": "OP%03d" % (i + 1), "name": o["name"], "enName": o.get("enName", "")}
            for i, o in enumerate(raw.get("operators", []))
        ],
        "stations": stations,
        "lines": lines,
        "transfers": transfers,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # 自检
    n_stations = len(out["stations"])
    n_lines = len(out["lines"])
    n_tf = sum(1 for s in out["stations"] if s["isTransfer"])
    covered = set()
    for l in out["lines"]:
        covered.update(l["stations"])
    print("stations=%d lines=%d transfers=%d transferStations=%d covered=%d"
          % (n_stations, n_lines, len(out["transfers"]), n_tf, len(covered)))
    print("written ->", args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_service_calendar.py — 离线把 data/service_calendar.json 补进已生成的 trains_*.json

CI 每周 refresh 会全量重跑 build_trains.py（互斥规则已内置），本脚本只用于
本地源数据缺失时的回填与核对，逻辑与构建期完全同源（service_calendar.py）。

用法:
  python3 scripts/apply_service_calendar.py                 # 回填并校验
  python3 scripts/apply_service_calendar.py --dry-run       # 只报告不写盘
"""
import argparse, datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import service_calendar
from build_trains import MERGE_CLASSES


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default=os.path.join(root, "data", "live"))
    ap.add_argument("--calendar", default=os.path.join(root, "data", "service_calendar.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    calendar = service_calendar.load(a.calendar)
    tmaps_path = os.path.join(a.live, "tmaps.json")
    if not os.path.exists(tmaps_path):
        print("缺少 tmaps.json，无法解析站名: " + tmaps_path, file=sys.stderr)
        return 1
    tmaps = json.load(open(tmaps_path, encoding="utf-8"))

    files = [("wd", 1), ("sa", 2), ("su", 4)]
    data = {}
    for name, _ in files:
        p = os.path.join(a.live, "trains_%s.json" % name)
        data[name] = json.load(open(p, encoding="utf-8"))
        recs = {r["_"]: r for r in data[name]["T"]}
        names = {tid: (tmaps.get(str(r["t"])) or {}).get("s_jas") for tid, r in recs.items()}
        names_of = names.get
        times = {tid: service_calendar.decode_times(r, tmaps.get(str(r["t"])))
                 for tid, r in recs.items()}
        cal_res = service_calendar.apply_calendar(recs, names_of, calendar)
        for w in cal_res["warnings"]:
            print("[calendar] 警告: " + w)
        if cal_res["active_unmatched"]:
            print("[calendar] %s: 运転日季度未结束但规则匹配不到成对记录，拒绝写入:" % name, file=sys.stderr)
            for w in cal_res["active_unmatched"]:
                print("  - " + w, file=sys.stderr)
            return 1
        dups = service_calendar.prefix_dups(recs, names_of, times.get, cal_res["covered"],
                                            MERGE_CLASSES | {"寝"})
        if dups:
            print("[calendar] %s: 源数据另有 %d 对未被日历覆盖的成对记录（仅提示）" % (name, len(dups)))

    if a.dry_run:
        print("[calendar] dry-run：未写盘")
        return 0

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes").replace("+00:00", " UTC")
    for name, _ in files:
        data[name]["b"] = now
        p = os.path.join(a.live, "trains_%s.json" % name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data[name], f, ensure_ascii=False, separators=(",", ":"))
        print("写入 %s (%d 班次)" % (p, len(data[name]["T"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

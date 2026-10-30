#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_trains.py — 从本地全量时刻表构建页面用的轻量列车文件（不访问网络）

输入（自动识别）：
  - railaround/output/day_shard*/<seq>_<线>.json   （VM 全量抓取格式，rday1..rday7 分组）
  - data/timetables/<seq>_<线>.json                 （fetch_timetables.py 格式，trains[]）
输出（3 个按运行日分组的文件 + 页面只加载今日对应那份）：
  data/live/trains_wd.json   rday&1  （平日）
  data/live/trains_sa.json   rday&2  （周六）
  data/live/trains_su.json   rday&4  （周日·假日）
每班次紧凑记录：{"t":tmap_id,"r":rday,"w":"发车分,终到分","s":"schs 逗号串","i":"车种","_":"train_id"}
可选字段：c=併结/分割元数据；d=仅这些日期开行、x=除这些日期外开行（运転日互斥，
见 service_calendar.py 与 data/service_calendar.json）。
schs = [dep0, run1, dwell1, run2, dwell2, ...]（长度 2N-2，终点站无停留字段），与页面解码一致。

用法：
  python3 scripts/build_trains.py                          # 自动找源
  python3 scripts/build_trains.py --src <目录> --out <目录>

去重（保守版）:
  源主数据偶尔把同一班次存成两条几乎相同的记录（同 tmap、同相对时刻、发车差
  ≤1 分钟，如 きりしま#2933 的 18:39/18:40）。构建后按 MERGE_CLASSES 合并，
  保留较早发车的一条。仅限优等列车车种；快速/普通不合并（城市近郊线同模式
  1-2 分钟间隔是真实列车）。重联/并结（はやぶさ+こまち）与跨公司/指令边界改号
  （みずほ 熊本、はやぶさ 新青森、のぞみ 新大阪等）tmap_id 均不同，不受影响。
"""
import argparse, datetime, glob, json, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couplings
import service_calendar

# 参与去重的车种（优等列车/新干线）。同一 tmap 模式的特急/新干线不可能隔
# ≤1 分钟发两趟真实列车；快速/普通在城市近郊线有真实 1-2 分钟间隔，必须排除。
# 注意：新增大类（如未来新增併结车型）需同步维护此处。
MERGE_CLASSES = {"特", "Mizuho", "Nozomi", "Sakura", "Hayabusa", "Komachi",
                 "Kagayaki", "Hikari", "Kodama", "Tsubame", "新",
                 "Yamabiko", "Tsubasa", "Asama", "Toki", "Tanigawa",
                 "Tsurugi", "Hakutaka", "Nasuno", "Hayate"}

def dedup_express_dups(recs):
    """recs: {train_id: rec} -> (merged_recs, dropped)

    合并条件（全部满足）：同 tmap_id + 相对时刻串（s 去首项）相同
    + 车种 ∈ MERGE_CLASSES + 发车分钟差 ≤ 1 + 两记录日型(rday 位掩码)有交集
    → 保留较早发车的一条，并把被删记录的日型并入保留记录（防丢班次）。

    rday 是位掩码（1=平日 2=周六 4=周日·假日），源数据会把同一班车按不同
    日型范围各录一条（如 rday=1 与 rday=7），故分组键不再含 rday；但若两条
    记录日型完全无交集（如平日一班、周末一班），说明是不同日型的真实班次，
    即使同形差 1 分钟也不合并。
    """
    merged = dict(recs)
    groups = {}
    for tid, rec in merged.items():
        if rec["i"] not in MERGE_CLASSES:
            continue
        s = rec["s"].split(",")
        rel = ",".join(s[1:])
        groups.setdefault((rec["t"], rel), []).append((int(s[0]), rec["r"], tid))
    dropped = 0
    for lst in groups.values():
        lst.sort()
        anchor_dep = lst[0][0]
        anchor_r = lst[0][1]
        anchor_tid = lst[0][2]
        for dep0, r, tid in lst[1:]:
            if dep0 - anchor_dep <= 1 and (r & anchor_r):
                merged[anchor_tid]["r"] |= r   # 日型并集,防跨日型丢班次
                anchor_r |= r
                del merged[tid]
                dropped += 1
            else:
                anchor_dep = dep0
                anchor_r = r
                anchor_tid = tid
    return merged, dropped

def mn(s):
    if not s:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = re.match(r"(\d{1,2}):(\d{2})", str(s).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None

def iter_trains(path):
    """yield (train_id, tmap_id, icon, rday, stops)"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and any(k.startswith("rday") and isinstance(d.get(k), list) for k in d):
        for key in [f"rday{i}" for i in range(1, 8)]:
            for tr in d.get(key, []) or []:
                yield (tr.get("train_id") or tr.get("_id"), tr.get("tmap_id"), tr.get("icon", ""), tr.get("rday"), tr.get("stops", []))
    elif isinstance(d, dict) and isinstance(d.get("trains"), list):
        for tr in d["trains"]:
            stops = tr.get("stops", [])
            yield (tr.get("train_id") or tr.get("_id"), tr.get("tmap_id"), tr.get("icon", ""), tr.get("rday"), stops)

def convert(stops):
    """stops: [{station/st, arr, dep}] -> (schs, dep0, arr_last) or None"""
    N = len(stops)
    if N < 2:
        return None
    d0 = mn(stops[0].get("dep")) or mn(stops[0].get("arr"))
    if d0 is None:
        return None
    schs = [d0]
    prev_dep = d0
    arr_last = d0
    for i in range(1, N):
        a = mn(stops[i].get("arr")) or mn(stops[i].get("dep"))
        de = mn(stops[i].get("dep")) or a
        if a is None or de is None:
            return None
        r = a - prev_dep
        if r < 0:
            r = 0
        schs.append(r)
        if i < N - 1:
            w = de - a
            if w < 0:
                w = 0
            schs.append(w)
        prev_dep = de
        arr_last = a
    if len(schs) != 2 * N - 2:
        return None
    return schs, d0, arr_last

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="", help="时刻表源目录（默认自动探测全量抓取目录或 data/timetables）")
    ap.add_argument("--out", default=os.path.join(root, "data", "live"))
    args = ap.parse_args()

    src = args.src
    if not src:
        cands = [os.path.join(root, "..", "railaround", "output"), os.path.join(root, "data", "timetables")]
        for c in cands:
            if glob.glob(os.path.join(c, "day_shard*", "*.json")) or glob.glob(os.path.join(c, "*.json")):
                src = c
                break
    if not src:
        print("未找到时刻表源目录（--src）")
        sys.exit(1)

    files = sorted(glob.glob(os.path.join(src, "day_shard*", "*.json")) + glob.glob(os.path.join(src, "*.json")))
    if not files:
        print("源目录无 JSON:", src)
        sys.exit(1)

    recs = {}
    skipped = {"short": 0, "bad": 0, "dup": 0}
    neg_clamped = 0
    day_counts = {"wd": 0, "sa": 0, "su": 0}
    for fp in files:
        try:
            for tid, tmap_id, icon, rday, stops in iter_trains(fp):
                if not tid or tmap_id is None or not rday:
                    skipped["bad"] += 1
                    continue
                if tid in recs:
                    skipped["dup"] += 1
                    continue
                conv = convert(stops)
                if not conv:
                    skipped["short"] += 1
                    continue
                schs, d0, arr_last = conv
                recs[tid] = {"t": tmap_id, "r": rday, "w": f"{d0},{arr_last}",
                             "s": ",".join(map(str, schs)), "i": icon or "", "_": tid}
                for bit, name in ((1, "wd"), (2, "sa"), (4, "su")):
                    if rday & bit:
                        day_counts[name] += 1
        except Exception:
            continue

    recs, deduped = dedup_express_dups(recs)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes").replace("+00:00", " UTC")
    os.makedirs(args.out, exist_ok=True)
    meta = {"b": now, "n": len(recs), "src": os.path.basename(os.path.normpath(src))}

    # 併结/分割检测（构建期）：目录化服务表 + 时刻对齐，结果固化进当日记录 "c" 字段。
    # 页面不再做启发式扫描，时刻表刷新不会改变已核实服务的判定结果。
    tmaps_path = os.path.join(args.out, "tmaps.json")
    tokkyu_path = os.path.join(root, "mini-japanrail-3d", "data", "tokkyu.json")
    tmaps = json.load(open(tmaps_path, encoding="utf-8")) if os.path.exists(tmaps_path) else {}
    tokkyu = json.load(open(tokkyu_path, encoding="utf-8")) if os.path.exists(tokkyu_path) else None

    # 运転日互斥（服务日历）：把日期烘焙进记录（延伸 d / 基本 x）。
    # 数据源把同一列车拆成基本/延伸两条且 rday 都是 7，仅靠日型无法互斥；
    # 日历由人按季维护，每周刷新重跑本函数自动生效。
    calendar_path = os.path.join(root, "data", "service_calendar.json")
    try:
        calendar = service_calendar.load(calendar_path)
    except Exception as e:
        print("[calendar] 无法读取 %s: %s" % (calendar_path, e), file=sys.stderr)
        sys.exit(1)

    def names_of(tid):
        tm = tmaps.get(str(recs[tid]["t"])) or {}
        return tm.get("s_jas")

    def times_of(tid):
        return service_calendar.decode_times(recs[tid], tmaps.get(str(recs[tid]["t"])))

    cal_res = service_calendar.apply_calendar(recs, names_of, calendar)
    for w in cal_res["warnings"]:
        print("[calendar] 警告: " + w)
    if cal_res["active_unmatched"]:
        print("[calendar] 运転日季度尚未结束，但以下规则匹配不到成对记录 —— 拒绝构建，防止幽灵车复活:",
              file=sys.stderr)
        for w in cal_res["active_unmatched"]:
            print("  - " + w, file=sys.stderr)
        print("  → 核对 data/service_calendar.json 的时刻/站名，或源已改单条时更新规则", file=sys.stderr)
        sys.exit(1)
    dups = service_calendar.prefix_dups(recs, names_of, times_of, cal_res["covered"],
                                        MERGE_CLASSES | {"寝"})
    if dups:
        print("[calendar] 提示: 源数据里另有 %d 对未被日历覆盖的成对记录（与本次互斥无关，未处理）" % len(dups))
        for d in dups[:12]:
            print("  - %s(%s) 与 %s(%s) 同 %s %02d:%02d 发车" % (
                d["base"], d["base_to"], d["ext"], d["ext_to"], d["origin"],
                d["dep"] // 60, d["dep"] % 60))

    total_pairs = 0
    for bit, name, label in ((1, "wd", "平日"), (2, "sa", "周六"), (4, "su", "周日·假日")):
        # 拷贝：併结对齐会改写记录时刻，不能串到其它日型
        day_recs = {tid: dict(r) for tid, r in recs.items() if r["r"] & bit}
        c_by_tid, stats, warns = couplings.compute_couplings(day_recs, tmaps, tokkyu)
        n_pairs = sum(len(v) for v in c_by_tid.values()) // 2
        total_pairs += n_pairs
        out_recs = []
        for tid, r in day_recs.items():
            item = dict(r)
            if tid in c_by_tid:
                item["c"] = c_by_tid[tid]
            out_recs.append(item)
        path = os.path.join(args.out, f"trains_{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"b": now, "n": len(out_recs), "T": out_recs}, f, ensure_ascii=False, separators=(",", ":"))
        print(f"trains_{name}.json ({label}): {len(out_recs)} 班次 (併结/分割 {n_pairs} 对) -> {path} ({os.path.getsize(path)/1e6:.1f}MB)")
        for (ev_name, kind), (n, cand) in sorted(stats.items()):
            if n or cand:
                print(f"  [c] {ev_name} {'併结' if kind == 'j' else '分割'}: {n}/{cand}")
        for w in warns:
            print(f"  [coupling] {w}")

    print(f"唯一班次总数: {len(recs)} | 跳过: {skipped} | 负区间钳制: {neg_clamped} | 保守去重合并: {deduped}")
    print(f"併结/分割检测合计: {total_pairs} 对")
    print(f"完成 @ {now}")

if __name__ == "__main__":
    main()

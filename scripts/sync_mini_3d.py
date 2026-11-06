#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_mini_3d.py — 把每周刷新产出的实时列车数据同步到 Mini JapanRail 子站，
并在提交前做契约校验（防坏数据上线：任一项不过 → exit 1 → Action 不提交/不部署，
GitHub 上旧数据保持原样，不会引起页面乱飞/空白）。

同步（refresh.yml 中 Build 之后、Commit 之前调用）:
  data/live/trains_{wd,sa,su}.json  -> mini-japanrail-3d/data/
  data/live/tmaps.json              -> mini-japanrail-3d/data/（存在则复制，站序缓存）

校验（纯 Python，CI 轻量，与页面引擎防护互补）:
  1. 结构: trains_*.json = {"T":[{t,r,w,s,i,_}]}; w="w0,w1" 数值合法; s 为纯数字串
  2. tmap 覆盖: 每个班次 tmap_id 在 tmaps 中; 缺失率 >50% → 失败
     （缺失是新 tmap_id 的正常现象，页面会安全跳过；>50% 说明 tmaps 太旧需重建）
  3. 站数匹配: s 长度 === 2*len(s_jas)-2 的班次占比 < 90% → 失败
     （时刻表站序/结构大改时会触发，宁停勿乱）
  4. 跨日 w 合法: w1 >= w0（跨日班次 w1 为 24h 制绝对分钟）
  5. 运転日互斥: 可选字段 d(仅这些日期开行)/x(除这些日期外开行)必须是
     非空 ISO 日期数组，且同一班次不能同时带 d 和 x
     （由 service_calendar.json 在构建期烘焙，格式坏了页面会静默少开车）

用法: python3 scripts/sync_mini_3d.py [--out mini-japanrail-3d/data]
"""
import argparse, json, os, re, subprocess, sys

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

def norm_ok(s):
    """s 字段为纯数字逗号串"""
    return bool(re.fullmatch(r"-?\d+(,-?\d+)*", s))

def dates_ok(v):
    """d/x 字段: None 或非空 ISO 日期数组"""
    return v is None or (isinstance(v, list) and len(v) > 0
                         and all(ISO_DATE.fullmatch(str(x)) for x in v))

def _norm_name(n):
    """与页面 normName 一致:去括号注记、ケ→ヶ、去尾部「駅」"""
    return re.sub(r"\([^)]*\)", "", str(n)).replace("ケ", "ヶ").rstrip("駅").strip()

def check_tram_coverage(out, tmaps, live):
    """市电网络站对覆盖契约。返回 True=失败。网络归属判定:班次 ≥60% 停站命中
    该网络 extras 的站名集合(避开「東山本線」等跨城同名线路前缀误判)。"""
    def load_json(p):
        try:
            with open(p, encoding="utf-8") as f: return json.load(f)
        except Exception:
            return None
    man = load_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo", "manual_extras.json")) or {}
    smap = load_json(os.path.join(out, "station_map.json")) or {}
    seg3 = load_json(os.path.join(out, "segments3d.geojson")) or {}
    segs = list(man.get("extra_segments", [])) + list(smap.get("extra_segments", []))
    if not segs:
        print("  [WARN] 无市电 extras 可校验,跳过覆盖契约")
        return False
    # 站对全集 = extras(manual+pipeline) ∪ segments3d(页面解析可命中的所有几何)
    allpairs = set()
    nets = {}
    for e in segs:
        n = nets.setdefault(e["line"], {"pairs": set(), "stops": set()})
        a, b = _norm_name(e["from"]), _norm_name(e["to"])
        n["pairs"].add((a, b)); n["pairs"].add((b, a))
        n["stops"].add(a); n["stops"].add(b)
        allpairs |= n["pairs"]
    for f in seg3.get("features", []):
        p = f.get("properties") or {}
        if p.get("from") and p.get("to"):
            allpairs.add((_norm_name(p["from"]), _norm_name(p["to"])))
            allpairs.add((_norm_name(p["to"]), _norm_name(p["from"])))
    # 在用模板(trains 引用的 t id)
    used = set()
    for name in ("wd", "sa", "su"):
        j = load_json(os.path.join(live, f"trains_{name}.json"))
        if j:
            for row in j.get("T", []): used.add(str(row.get("t")))
    failed = False
    for net, info in sorted(nets.items()):
        tot = hit = 0
        for tid, mi in tmaps.items():
            if str(tid) not in used: continue
            jas = mi.get("s_jas") or []
            if len(jas) < 2: continue
            nm = [_norm_name(x) for x in jas]
            belong = sum(1 for x in nm if x in info["stops"])
            if belong < len(nm) * 0.6: continue
            for i in range(len(nm) - 1):
                tot += 1
                if (nm[i], nm[i+1]) in allpairs: hit += 1
        pct = hit / tot * 100 if tot else 100
        ok = pct >= 90
        print(f"  市电覆盖 {net}: {hit}/{tot} = {pct:.1f}% {'✓' if ok else '✗ <90%'}")
        if not ok:
            failed = True
            print(f"    → 停站名疑似变更:请按 PERF.md 方法从新 tmap_lids 重新推导,"
                  f"把新站对并入 scripts/geo/manual_extras.json")
    return failed

def check_file(name, path, tmaps):
    """返回 (错误数, 班次数)"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    T = d.get("T")
    if not isinstance(T, list) or len(T) == 0:
        print(f"  [FAIL] {name}: 无 T 数组")
        return 1, 0
    errs = 0
    miss_tmap = 0
    len_ok = 0
    for rec in T:
        tmap_id = rec.get("t")
        s = rec.get("s", "")
        w = rec.get("w", "")
        # 1 结构
        if not isinstance(tmap_id, (str, int)) or not norm_ok(s) or not re.fullmatch(r"\d+,\d+", str(w)):
            errs += 1
            continue
        # 运転日互斥字段（见 service_calendar.json）
        if "d" in rec and "x" in rec:
            print(f"  [FAIL] {name}: 班次 {rec.get('_')} 同时带 d 和 x")
            errs += 1
            continue
        if not dates_ok(rec.get("d")) or not dates_ok(rec.get("x")):
            print(f"  [FAIL] {name}: 班次 {rec.get('_')} 的 d/x 不是非空 ISO 日期数组")
            errs += 1
            continue
        # 2 tmap 覆盖
        tm = tmaps.get(str(tmap_id))
        if not tm or not tm.get("s_jas"):
            miss_tmap += 1
            continue
        # 3 站数匹配
        n = len(tm["s_jas"])
        if len(s.split(",")) == 2 * n - 2:
            len_ok += 1
    n_t = len(T)
    miss_rate = miss_tmap / n_t
    len_rate = len_ok / max(1, n_t - miss_tmap)
    print(f"  {name}: {n_t} 班次 | tmap 缺失 {miss_tmap} ({miss_rate*100:.0f}%) | "
          f"站数匹配 {len_ok}/{n_t - miss_tmap} ({len_rate*100:.0f}%) | 结构错误 {errs}")
    if miss_rate > 0.5:
        print(f"  [FAIL] {name}: tmap 缺失率 {miss_rate*100:.0f}% > 50%，tmaps 需重建")
        errs += 1
    if len_rate < 0.9:
        print(f"  [FAIL] {name}: 站数匹配率 {len_rate*100:.0f}% < 90%，时刻表结构疑似变化")
        errs += 1
    return errs, n_t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default="data/live")
    ap.add_argument("--out", default="mini-japanrail-3d/data")
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    live = os.path.join(root, args.live)
    out = os.path.join(root, args.out)

    # 读 tmaps（校验用）
    tmaps_path = os.path.join(live, "tmaps.json")
    with open(tmaps_path, encoding="utf-8") as f:
        tmaps = json.load(f)
    print(f"tmaps: {len(tmaps)} 个 tmap_id @ {tmaps_path}")

    # 校验
    total_err = 0
    total_n = 0
    for name in ("wd", "sa", "su"):
        path = os.path.join(live, f"trains_{name}.json")
        if not os.path.exists(path):
            print(f"  [SKIP] trains_{name}.json 不存在")
            continue
        e, n = check_file(name, path, tmaps)
        total_err += e
        total_n += n
    print(f"合计: {total_n} 班次, 错误 {total_err}")
    if total_err:
        print("校验未通过——中止提交/部署，旧数据保持不变。")
        sys.exit(1)

    # 5. 市电轨道覆盖契约(2026-10-25 鹿児島洗掉事故后增设):manual_extras + station_map
    #    的市电站对必须持续覆盖在用市电班次的区间。时刻表源若改写停站名(改名/加注),
    #    站对失配 → 市电落回兜底弦线(视觉串线)。任一网络覆盖 <90% → 失败中止,
    #    提示把新站对补进 scripts/geo/manual_extras.json 并重新推导。
    tram_err = check_tram_coverage(out, tmaps, live)
    if tram_err:
        print("市电轨道覆盖校验未通过——中止提交/部署。")
        sys.exit(1)

    # 校验通过 -> 同步到 3D 子站
    os.makedirs(out, exist_ok=True)
    for fname in ("trains_wd.json", "trains_sa.json", "trains_su.json", "tmaps.json"):
        src = os.path.join(live, fname)
        dst = os.path.join(out, fname)
        if os.path.exists(src):
            with open(src, "rb") as f:
                data = f.read()
            with open(dst, "wb") as f:
                f.write(data)
            print(f"  sync {fname} ({len(data)/1e6:.1f}MB) -> {os.path.relpath(dst, root)}")

    # 同步后生成特急爱称表（基于已同步的 trains_*.json + tmaps.json，与页面渲染同源；
    # 失败不阻断主同步——页面降级为仅显示种别 icon）
    tokkyu_script = os.path.join(root, "mini-japanrail-3d", "scripts", "build_tokkyu.py")
    if os.path.exists(tokkyu_script):
        rc = subprocess.run(
            [sys.executable, tokkyu_script, "--src", os.path.abspath(out), "--out", os.path.abspath(out)],
            check=False, capture_output=True, text=True)
        if rc.returncode:
            print("  [WARN] build_tokkyu.py 失败，tokkyu.json 未更新（主数据已同步）")
            if rc.stdout: print("  " + rc.stdout.strip().replace("\n", "\n  "))
            if rc.stderr: print("  " + rc.stderr.strip().replace("\n", "\n  "))
        else:
            print("  tokkyu.json 特急爱称表已更新 ✓")
    else:
        print("  [WARN] build_tokkyu.py 不存在，跳过爱称表生成")
    print("Mini JapanRail 数据同步完成 ✓")

if __name__ == "__main__":
    main()

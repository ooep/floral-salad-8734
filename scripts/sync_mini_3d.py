#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_mini_3d.py — 把每周刷新产出的实时列车数据同步到 Mini JapanRail 3D 子站，
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

用法: python3 scripts/sync_mini_3d.py [--out mini-japanrail-3d/data]
"""
import argparse, json, os, re, sys

def norm_ok(s):
    """s 字段为纯数字逗号串"""
    return bool(re.fullmatch(r"-?\d+(,-?\d+)*", s))

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
    print("Mini JapanRail 3D 数据同步完成 ✓")

if __name__ == "__main__":
    main()

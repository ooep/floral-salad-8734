#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tt_shards.py — 把周更后的全日时刻表切成「按 30 分钟活跃窗口」的静态分片（纯离线）

设计目标
  * 不改变任何既有端点：trains_{wd,sa,su}.json 仍原样生成/保留，老客户端不受影响。
  * 新增 additive 端点：
        data/tt/manifest.json          （~2 KB，描述每个日型的分片）
        data/tt/<day>/<00..47>.json    （每个 30 分钟窗口的班次）
  * 分片按「该 30 分钟内任意时刻可能被 updateTrains 判定为在途」的班次复制。
    这样客户端在任意分钟只需要加载「当前窗口 + 下一窗口」，不必把全日 9.5 万班次
    全部下载/解析；跨零点/24 时以后的班次也按页面现有的 windowShift 语义归入窗口。
  * 生成发生在部署流水线（周更数据提交后触发的 deploy.yml / build_static_assets.py），
    不新增工作流、不产生运行时服务；静态文件由 jr-static 边缘直服，零 Worker 调用。

分片语义与页面 windowShift 完全一致（并额外覆盖晚点尾巴）：
    active(M) := M ∈ [w0, w1+tail]
                 ∨ M+1440 ∈ [w0, w1+tail]
                 ∨ M-1440 ∈ [w0, w1+tail]
  其中 M 为当日 0..1439 分钟，tail = --delay-tail（默认 60 分钟）。
  页面 windowShift 在 t.dly>0 时把实时分钟折回计划分钟，故班次实际的活跃窗是
  [w0+dly, w1+dly]。分片只按计划时刻收录；为了让「计划已结束、但晚点仍在途」
  的班次在冷加载/换窗时也能命中，每个窗口额外收录计划结束时间 +tail 内的班次。
  超过 tail 的极端晚点由客户端「上一窗口结转」与延误源定向补片兜底（见 app.js）。

用法:
  python3 scripts/build_tt_shards.py --src data/live --out static-worker/assets/data/tt
  python3 scripts/build_tt_shards.py --src data/live --out /tmp/tt --verify
  python3 scripts/build_tt_shards.py --src data/live --out /tmp/tt --delay-tail 120
"""
import argparse
import datetime
import json
import os
import sys

BUCKET_MIN = 30
BUCKETS = 24 * 60 // BUCKET_MIN
DAYS = ("wd", "sa", "su")
DAY_LABEL = {"wd": "平日", "sa": "周六", "su": "周日·假日"}
DELAY_TAIL_MIN = 60  # 期计划终点之后继续收录的分钟数（覆盖常见晚点）


def active_intervals(w0, w1, tail=0):
    """返回该班次可能落在当日 0..1439 分钟窗口内的连续区间。

    与 app.js buildDayIndex / windowShift 保持同一口径，并把终点延伸到 w1+tail：
      [w0, w1+tail] ∩ [0,1440)
      ∪ [max(0,w0-1440), min(w0-1, w1+tail-1440)]   （前一日 24 时后发车、次日凌晨仍运行）
    """
    w1e = w1 + max(0, tail)
    out = []
    a, b = max(0, w0), min(1439, w1e)
    if b >= a:
        out.append((a, b))
    a = max(0, w0 - 1440)
    b = min(w0 - 1, w1e - 1440, 1439)
    if b >= a:
        out.append((a, b))
    return out


def trip_key(rec):
    if rec.get("_") is not None:
        return str(rec["_"])
    return "%s|%s|%s" % (rec.get("t"), rec.get("w"), rec.get("s"))


def build_day(src_path, out_dir, day, tail):
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)
    T = data.get("T") or []
    if not isinstance(T, list):
        raise ValueError("%s: T 不是数组" % src_path)

    buckets = [[] for _ in range(BUCKETS)]
    skipped = 0
    for rec in T:
        try:
            w0, w1 = (int(x) for x in str(rec.get("w", "")).split(","))
        except Exception:
            skipped += 1
            continue
        if w1 < w0:
            skipped += 1
            continue
        idxs = set()
        for a, b in active_intervals(w0, w1, tail):
            for bi in range(a // BUCKET_MIN, b // BUCKET_MIN + 1):
                idxs.add(bi)
        for bi in idxs:
            buckets[bi].append(rec)

    day_dir = os.path.join(out_dir, day)
    os.makedirs(day_dir, exist_ok=True)
    shards = []
    dup_bytes = 0
    for i, arr in enumerate(buckets):
        payload = {"b": data.get("b", ""), "i": i, "n": len(arr), "T": arr}
        path = os.path.join(day_dir, "%02d.json" % i)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        size = os.path.getsize(path)
        dup_bytes += size
        shards.append({
            "i": i,
            "f": "%s/%02d.json" % (day, i),
            "n": len(arr),
            "bytes": size,
        })
    meta = {
        "file": os.path.basename(src_path),
        "b": data.get("b", ""),
        "n": len(T),
        "bytes": os.path.getsize(src_path),
        "delay_tail_min": tail,
        "shards": shards,
    }
    print("  %s (%s): %d 班次 -> %d 分片 / %.1f MB（原文件 %.1f MB，晚点尾巴 %d 分）%s" % (
        day, DAY_LABEL[day], len(T), len(shards), dup_bytes / 1e6,
        os.path.getsize(src_path) / 1e6, tail,
        "（跳过 %d 条坏记录）" % skipped if skipped else ""))
    return meta, dup_bytes


def verify(src_dir, out_dir):
    """抽样验证：计划在途 + 晚点尾巴内的班次都必须出现在对应分片中。"""
    man_path = os.path.join(out_dir, "manifest.json")
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)
    if man.get("v") != 1 or man.get("bucket_min") != BUCKET_MIN or man.get("buckets") != BUCKETS:
        raise AssertionError("manifest 版本/窗口参数不匹配")
    tail = int(man.get("delay_tail_min", 0))
    if tail < 0 or tail > 1440:
        raise AssertionError("manifest delay_tail_min 非法: %r" % tail)
    errors = 0
    for day in DAYS:
        src_path = os.path.join(src_dir, "trains_%s.json" % day)
        with open(src_path, encoding="utf-8") as f:
            data = json.load(f)
        T = data.get("T") or []
        by_key = {trip_key(r): r for r in T}
        seen = set()
        for i in range(BUCKETS):
            sidx = man["days"][day]["shards"][i]
            with open(os.path.join(out_dir, sidx["f"]), encoding="utf-8") as f:
                shard = json.load(f)
            keys = [trip_key(r) for r in shard.get("T") or []]
            if len(keys) != sidx["n"] or len(set(keys)) != len(keys):
                print("  [FAIL] %s/%02d 分片计数不一致或重复" % (day, i))
                errors += 1
            seen.update(keys)
            # 抽样窗口首/中/尾分钟，期望集合（含晚点尾巴）必须是分片集合的子集
            for m in (i * BUCKET_MIN, i * BUCKET_MIN + BUCKET_MIN // 2, i * BUCKET_MIN + BUCKET_MIN - 1):
                exp = set()
                for rec in T:
                    try:
                        w0, w1 = (int(x) for x in str(rec.get("w", "")).split(","))
                    except Exception:
                        continue
                    for a, b in active_intervals(w0, w1, tail):
                        if a <= m <= b:
                            exp.add(trip_key(rec))
                            break
                missing = exp - set(keys)
                if missing:
                    print("  [FAIL] %s %02d:%02d 缺少 %d 班（示例 %s）" % (
                        day, m // 60, m % 60, len(missing), sorted(missing)[:3]))
                    errors += 1
        if seen != set(by_key):
            missing = set(by_key) - seen
            print("  [FAIL] %s 有 %d 班次未进入任何分片（示例 %s）" % (day, len(missing), sorted(missing)[:3]))
            errors += 1
        else:
            print("  %s 分片覆盖校验通过（%d 班次，尾巴 %d 分）" % (day, len(by_key), tail))
        # 晚点抽样：任意 dly∈[0,tail] 的实际活跃分钟都必须能在该分钟所属分片中找到该班
        import random
        rnd = random.Random(20261031)
        sample = T if len(T) <= 800 else rnd.sample(T, 800)
        shard_keys_cache = {}
        miss = 0
        for rec in sample:
            try:
                w0, w1 = (int(x) for x in str(rec.get("w", "")).split(","))
            except Exception:
                continue
            if w1 < w0:
                continue
            key = trip_key(rec)
            dly = rnd.choice((0, tail // 2, tail)) if tail else 0
            for m in {((w0 + dly) % 1440), ((w1 + dly) % 1440)}:
                bi = m // BUCKET_MIN
                if bi not in shard_keys_cache:
                    sidx = man["days"][day]["shards"][bi]
                    with open(os.path.join(out_dir, sidx["f"]), encoding="utf-8") as f:
                        shard_keys_cache[bi] = {trip_key(r) for r in (json.load(f).get("T") or [])}
                if key not in shard_keys_cache[bi] and any(a <= m <= b for a, b in active_intervals(w0, w1, tail)):
                    miss += 1
        if miss:
            print("  [FAIL] %s 晚点尾巴抽样缺失 %d 处" % (day, miss))
            errors += 1
        else:
            print("  %s 晚点尾巴抽样通过（%d 班 × dly≤%d 分）" % (day, len(sample), tail))
    if errors:
        raise SystemExit("分片校验失败: %d 项" % errors)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(root, "data", "live"))
    ap.add_argument("--out", default=os.path.join(root, "data", "tt"))
    ap.add_argument("--delay-tail", type=int, default=DELAY_TAIL_MIN,
                    help="计划终点之后额外收录的分钟数（默认 %d）" % DELAY_TAIL_MIN)
    ap.add_argument("--verify", action="store_true", help="生成后抽样校验（会额外解析原文件）")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    if args.delay_tail < 0 or args.delay_tail > 1440:
        ap.error("--delay-tail 必须在 0..1440")
    os.makedirs(out, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes").replace("+00:00", " UTC")
    man = {
        "v": 1,
        "generated_at": now,
        "bucket_min": BUCKET_MIN,
        "buckets": BUCKETS,
        "delay_tail_min": args.delay_tail,
        "days": {},
    }
    total_dup = 0
    for day in DAYS:
        src_path = os.path.join(src, "trains_%s.json" % day)
        if not os.path.exists(src_path):
            print("  [SKIP] %s 不存在" % src_path)
            continue
        meta, dup = build_day(src_path, out, day, args.delay_tail)
        man["days"][day] = meta
        total_dup += dup

    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, separators=(",", ":"))
    print("manifest -> %s（%d 字节）" % (os.path.join(out, "manifest.json"),
                                      os.path.getsize(os.path.join(out, "manifest.json"))))
    print("分片合计 %.1f MB（按 30 分钟活跃窗口复制；原三份合计 %.1f MB）" % (
        total_dup / 1e6,
        sum(man["days"][d]["bytes"] for d in man["days"]) / 1e6))
    if args.verify:
        verify(src, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

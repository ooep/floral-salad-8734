#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tmaps.py — 构建 tmap 归属缓存（一次性/周更）

对每一条 rw_id 逐线请求 /api/animation/initial，收集:
  - tmaps.json : { tmap_id: {"s_jas": [...站名序列...], "lines": [线路ja名...]} }
  - railways.json : { rw_id: {name_ja,name_en,name_zh} }
用于实时列车图层：tmap_id → 停站顺序（几何用用户自己的 segments/stations），
以及列车提示框的线路名归属。

合规：robots.txt Disallow:/api/ + Crawl-delay:2 → 单线程, 每次间隔 SLEEP 秒。
用法: python3 scripts/build_tmaps.py [--out data/live] [--sleep 2.2]
--ensure-keys（CI 周更）：先检查 trains_wd/sa/su 引用的 tmap_id 是否已全部覆盖，
  全覆盖则秒级跳过；有缺失（时刻表更新引用了新 tmap_id，如 ダイヤ改正）才全量重建。
  重建沿用旧 tmaps 作底（setdefault 合并），只增不减。
"""
import argparse, gzip, json, os, sys, time, urllib.request

BASE = "https://www.railaround.com"
H = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.railaround.com/zh/railway/",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",  # 大线响应可达数十 MB，明文传输易 TLS 断连(IncompleteRead)
}

def post_initial(rw_ids):
    req = urllib.request.Request(
        BASE + "/api/animation/initial",
        data=json.dumps({"type": "railway", "ids": rw_ids, "locale": "ja"}).encode(),
        headers=H,
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="data/live/lines.json")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--sleep", type=float, default=2.2)
    ap.add_argument("--incremental", action="store_true", help="（预留，未实现）")
    ap.add_argument("--skip-if-cached", action="store_true", help="缓存已存在且非空时直接跳过（CI 每日部署用）")
    ap.add_argument("--ensure-keys", action="store_true",
                    help="CI 智能模式: 仅当 trains_*.json 引用的 tmap_id 有缺失时才全量重建")
    ap.add_argument("--trains-dir", default="data/live", help="trains_wd/sa/su.json 所在目录（--ensure-keys 用）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    tmap_path = os.path.join(args.out, "tmaps.json")
    rail_path = os.path.join(args.out, "railways.json")
    tmaps = {}
    railways = {}
    if os.path.exists(tmap_path):
        try:
            tmaps = json.load(open(tmap_path, encoding="utf-8"))
        except Exception:
            tmaps = {}
    if args.skip_if_cached and len(tmaps) > 0:
        print(f"tmaps 缓存已存在（{len(tmaps)} 个），跳过构建", flush=True)
        return
    # --ensure-keys: 检查 trains 引用的 tmap_id 是否已全覆盖；有缺失才重建。
    # 缺失来源: build_trains 拉到的 RailAround 时刻表引用了新 tmap_id
    # （ダイヤ改正/新服务），而 tmaps 还是旧手动构建版本 -> 悬空 key 宁漏。
    if args.ensure_keys:
        import collections
        referenced = set()
        for f in ("trains_wd.json", "trains_sa.json", "trains_su.json"):
            p = os.path.join(args.trains_dir, f)
            if not os.path.exists(p):
                continue
            try:
                tr = json.load(open(p, encoding="utf-8"))
            except Exception:
                print(f"  ensure: 读取 {f} 失败，视为有缺失（将全量重建）", flush=True)
                referenced.add("__force_rebuild__")
                continue
            arr = tr.get("T", []) if isinstance(tr, dict) else tr
            for rec in arr:
                if isinstance(rec, dict) and "t" in rec:
                    referenced.add(str(rec["t"]))
        missing = referenced - set(tmaps.keys())
        if not missing:
            print(f"ensure: trains 引用的 {len(referenced)} 个 tmap_id 已全覆盖，跳过重建", flush=True)
            return
        print(f"ensure: 发现 {len(missing)} 个悬空 tmap_id（trains 引用但 tmaps 缺失），"
              f"触发全量重建（样例: {sorted(missing)[:5]}）", flush=True)
    if os.path.exists(rail_path):
        railways = json.load(open(rail_path, encoding="utf-8"))

    lines = json.load(open(args.lines, encoding="utf-8"))["lines"]
    rw_ids = []
    seen = set()
    for ln in lines:
        for rw in ln["rw_ids"]:
            if rw not in seen:
                seen.add(rw)
                rw_ids.append((rw, ln["line"]))
    print(f"共 {len(rw_ids)} 个 rw_id（{len(lines)} 线），预计 {(len(rw_ids)*args.sleep)/60:.0f} 分钟", flush=True)

    # 若缓存已含全部 tmap 则跳过：不直接比较，逐 rw_id 请求仍会跑完；
    # 为 CI 省时：直接带 tmap 覆盖的 rw_id 仍请求一次（站点可能更新）。
    def absorb(d, line):
        n = 0
        for t in d.get("tmaps", []):
            tid = str(t["tmap_id"])
            ent = tmaps.setdefault(tid, {"s_jas": t.get("s_jas", []), "lines": []})
            if line not in ent["lines"]:
                ent["lines"].append(line)
            n += 1
        for rw_ in d.get("railways", []):
            railways[str(rw_["rw_id"])] = {
                "name_ja": rw_.get("name_ja"),
                "name_en": rw_.get("name_en"),
                "name_zh": rw_.get("name_zh"),
            }
        return n

    ok = fail = 0
    failed = []
    t0 = time.time()
    for i, (rw, line) in enumerate(rw_ids):
        try:
            absorb(post_initial([rw]), line)
            ok += 1
            if (i + 1) % 50 == 0:
                json.dump(tmaps, open(tmap_path, "w"), ensure_ascii=False)
                json.dump(railways, open(rail_path, "w"), ensure_ascii=False)
                print(f"  progress {i+1}/{len(rw_ids)} (ok={ok} fail={fail} tmaps={len(tmaps)} elapsed={time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            fail += 1
            failed.append((rw, line))
            print(f"  ERR rw={rw} line={line}: {e}", flush=True)
        time.sleep(args.sleep)

    # 失败项重试一轮：大响应（如東海道本線）最易 IncompleteRead/SSL EOF，
    # 重试通常成功；仍失败则跳过（数据不完整，由下周日 ensure 补齐）。
    if failed:
        total_fail = len(failed)
        print(f"重试 {total_fail} 个失败 rw_id ...", flush=True)
        retry_ok = 0
        still = []
        for rw, line in failed:
            try:
                absorb(post_initial([rw]), line)
                retry_ok += 1
            except Exception as e:
                still.append((rw, line))
                print(f"  RETRY ERR rw={rw} line={line}: {e}", flush=True)
            time.sleep(args.sleep)
        failed = still
        print(f"重试完成: 成功 {retry_ok}/{total_fail}", flush=True)

    json.dump(tmaps, open(tmap_path, "w"), ensure_ascii=False)
    json.dump(railways, open(rail_path, "w"), ensure_ascii=False)
    print(f"完成: ok={ok} fail={fail}(重试后剩 {len(failed)}) tmaps={len(tmaps)} 写入 {tmap_path}", flush=True)

if __name__ == "__main__":
    main()

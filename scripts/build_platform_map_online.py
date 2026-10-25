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
        rw_name = norm((geo.get("railway") or {}).get("title") and ((geo.get("railway") or {}).get("title") or {}).get("ja"))
        if not rw_name:
            rw_name = str(rid)
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
                "pf": st.get("pf"), "m": st.get("m"), "_line_ja": rw_name,
            })
        if stations:
            railways[rid] = {"seq": seq, "stations": stations}
        n += 1
        if n % 50 == 0:
            print("  已拉取线路:", n)
    for rid, r in railways.items():
        r["id"] = rid
        r["name_ja"] = r["stations"][0]["_line_ja"]
        r["idx"] = {}
        r["by_ja"] = {}
        for k, st in enumerate(r["stations"]):
            r["idx"].setdefault(st["ja"], k)
            r["by_ja"].setdefault(st["ja"], st)
    return railways


def best_rid_from(stops, i, railways):
    """从 i 起找连续站覆盖最长的 doko 线路；返回 (rid, 覆盖站数)。连续约束避免多线共站选错线。"""
    best, best_len = None, 0
    s0 = norm(stops[i])
    for rid, r in railways.items():
        pos = r["idx"].get(s0)
        if pos is None:
            continue
        ln = 1
        j, p = i + 1, pos
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


PLAT_REGION_RE = re.compile(
    r"(?:石川|いしかわ|IR|七尾|あいの風|ハピライン|北陸|能登|のと|富山|福井|東京|都電|モノレール|モノ|山手|中央|総武|"
    r"京王|小田急|京急|西武|東武|メトロ|地下鉄|都営|愛知|名古屋|名鉄|近鉄|大阪|阪神|阪急|兵庫|神戸|京都|奈良|滋賀|"
    r"和歌山|三重|岐阜|静岡|山梨|長野|新潟|群馬|栃木|茨城|埼玉|千葉|神奈川|横浜|北海道|札幌|函館|青森|岩手|宮城|"
    r"仙台|秋田|山形|福島|広島|山口|島根|鳥取|岡山|香川|徳島|愛媛|松山|高知|福岡|北九州|佐賀|長崎|熊本|大分|宮崎|"
    r"鹿児島|沖縄|飯田|アルピコ|軌道|市営|地下鉄|阪堺|南海|嵐山|京福|京阪|阪急線|神鉄|加古川|福知山|日豊|指宿|"
    r"讃|徳|琴平|伊予|土讃|今治|東海道|東北本線|常磐|山手|京浜|根岸|埼京|川越|八高|武蔵野|京葉|総武|京成|都営|"
    r"ゆりかもめ|りんかい|みなとみらい|東京臨海|多摩|青梅|五日市|中央本線|篠ノ井|信越|上越|羽越|米坂|只見|磐越|"
    r"大湊|山田|八戸|いわて銀河|青い森|津軽|五能|男鹿|花輪|北上|釜石|三陸|大船渡|気仙沼|石巻|仙石|仙山|常磐|"
    r"水郡|水戸|鹿島|成田|内房|外房|久留里|東金|房総|総武|武蔵野|南武|鶴見|根岸|横浜|相鉄|小田急|江ノ島|京急|"
    r"東急|田園都市|大井町|池上|多摩川|目黒|山手|京王|井の頭|西武|東武|ゆりかもめ|埼玉高速|つくばエクスプレス|"
    r"北総|京成|新京成|東葉|成田|芝山|羽田|東京モノレール|多摩モノレール|湘南|伊東|御殿場|身延|飯田|太多|高山|"
    r"紀勢|参宮|名松|和歌山|阪和|関西|大阪環状|桜島|大和路線|おおさか東|福知山|山陰|播但|姫新|加古川|神戸|山陽|"
    r"宇野|瀬戸大橋|伯備|芸備|福塩|呉|可部|岩徳|山口|美祢|山陰|境|赤穂|津山|因美|木次|三江|山陰|舞鶴|小浜|"
    r"七尾|越美北|えちごトキめき|あいの風|ハピライン|IR|いしかわ|北陸|湖西|北陸新幹線|信越本線|上越新幹線|東北新幹線|"
    r"山形新幹線|秋田新幹線|北海道新幹線|函館|室蘭|千歳|根室|釧路|石北|宗谷|留萌|日高|胆振|富良野|札沼|学園都市|"
    r"函館市電|札幌市営|南北線|東西線|東豊線|空港|快速エアポート)")


def plat_ok(nm, ln):
    """括号站名区域校验：zone→必须词（高松三站等已知 norm 串线组），其余 zone 用区域正则放宽。
    拦截 norm 同名站串线（如 高松(石川県)↔予讃線/高徳線）。"""
    m = re.search(r"[（(]([^)）]+)[)）]", nm)
    if not m:
        return True
    zone = m.group(1)
    must = PLAT_ZONE_MUST.get(zone)
    if must:
        return any(w in ln for w in must)
    if PLAT_REGION_RE.search(zone):
        return bool(PLAT_REGION_RE.search(ln))
    return True


PLAT_ZONE_MUST = {
    "石川県": ["石川", "いしかわ", "IR", "七尾", "あいの風", "ハピライン", "北陸", "能登", "のと", "金沢"],
    "東京都": ["東京", "都", "モノ", "山手", "中央", "総武", "京王", "小田急", "京急", "西武", "東武", "メトロ",
               "地下鉄", "都営", "京成", "多摩", "青梅", "武蔵野", "京葉", "常磐", "京浜", "根岸", "埼京", "川越", "八高", "五日市"],
    "香川県": ["香川", "讃", "徳", "琴平", "多度津", "土讃", "高松", "四国", "瀬戸"],
    "愛媛県": ["愛媛", "讃", "伊予", "今治", "松山", "内子", "宇和島", "高浜"],
    "福井県": ["福井", "ハピライン", "えちご", "北陸", "越美北", "小浜", "敦賀", "三国", "九頭竜"],
    "富山県": ["富山", "あいの風", "北陸", "城端", "氷見", "高岡", "黒部", "万葉", "地鉄", "アルプス", "射水", "富山港"],
    "新潟県": ["新潟", "越後", "上越", "信越", "羽越", "米坂", "磐越", "白新", "えちご", "北越", "弥彦", "妙高", "飯山"],
    "宮城県": ["宮城", "仙台", "仙石", "仙山", "常磐", "東北本線", "石巻", "気仙沼", "阿武隈", "南北", "東西", "東豊"],
    "広島県": ["広島", "芸備", "可部", "呉", "福塩", "山陽", "宇品", "アストラム", "宮島"],
    "福岡県": ["福岡", "筑豊", "日田彦山", "香椎", "鹿児島本線", "博多", "貝塚", "西鉄", "甘木", "福北", "箱崎"],
    "長野県": ["長野", "信越", "篠ノ井", "飯山", "大糸", "北しなの", "上田", "小海", "松本", "アルピコ", "えちご", "飯田"],
    "北海道": ["北海道", "札幌", "函館", "室蘭", "千歳", "根室", "釧路", "石北", "宗谷", "留萌", "日高", "胆振",
               "富良野", "札沼", "学園", "空港"],
    "大阪府": ["大阪", "阪", "おおさか", "関西", "大和", "阪和", "関空", "なにわ", "梅田", "環状", "堺"],
    "兵庫県": ["兵庫", "神戸", "阪", "山陽", "姫", "播但", "加古川", "福知山", "篠山", "三田", "有馬", "神鉄",
               "北神", "ポート", "六甲", "和田岬"],
    "京都府": ["京都", "山陰", "奈良", "近鉄", "京阪", "嵯峨", "嵐山", "宇治", "湖西", "琵琶湖", "嵯峨野"],
    "愛知県": ["愛知", "名古屋", "名鉄", "東海道", "中央本線", "関西本線", "近鉄", "豊橋", "蒲郡", "三河", "知多",
               "名古屋市営", "あおなみ", "リニモ", "ゆとりーと"],
}


def match_tmap(stops, railways):
    """整条 tmap 按连续站序列分段匹配 doko 线路，产出 {线路名: [pw|null,...]}。
    站台取 pw（车站级全集，与 dokorail 站窗/详情行显示一致）；
    pf 是里程区间默认子集（如金沢 IR=6;7 vs pw=1-7），dokorail 界面并不用它显示站台，故不引入。
    """
    n = len(stops)
    out = {}
    i = 0
    while i < n:
        if not norm(stops[i]):
            i += 1
            continue
        rid, ln = best_rid_from(stops, i, railways)
        if not rid:
            i += 1
            continue
        r = railways[rid]
        name = r.get("name_ja") or rid
        arr = out.setdefault(name, [None] * n)
        for k in range(i, min(i + ln, n)):
            st = r["by_ja"].get(norm(stops[k]))
            if st and plat_ok(stops[k], name):
                pw = st.get("pw") or ""
                if pw:
                    arr[k] = pw
        i += ln
    return {name: arr for name, arr in out.items() if any(arr)}


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
    rid_names = {}
    for tid, t in tm.items():
        stops = t.get("s_jas") or []
        by_rid = match_tmap(stops, railways)
        total_st += len(stops)
        got = sum(1 for arr in by_rid.values() for p in arr if p)
        matched_st += got
        if by_rid:
            matched_lines += 1
            out_t[tid] = by_rid
            for nm in by_rid:
                rid_names[nm] = rid_names.get(nm, 0) + 1
    print("匹配统计: 线路 %d/%d, 站 %d/%d（有数据/总站）" % (matched_lines, len(tm), matched_st, total_st))
    print("  线路名（doko 运营线）去重数:", len(rid_names))
    for nm, c in sorted(rid_names.items(), key=lambda x: -x[1])[:12]:
        print("    %s x%d" % (nm, c))

    result = {"version": 3, "source": "dokorail.jp 线上", "t": out_t}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("写出:", OUT, "大小:", os.path.getsize(OUT))


if __name__ == "__main__":
    main()

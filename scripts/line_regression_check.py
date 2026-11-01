#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
line_regression_check.py — 列车「串线 / 线路外乱飞」回归闸门（headless Chrome + CDP）

背景：三条已修复的真实事故
  1) サンライズ瀬戸 東京→高松（官方区间几何缺失）走上平行的東海道新幹線 —— 本线优先搭桥缺失
  2) ソニック 博多→大分 在 杵築→別府 之间沿错误截取反向跑出线路 —— segSubPath 方向判定错误
  3) サンライズ瀬戸/出雲 姫路→岡山、成田エクスプレス 品川→東京 被站对选段带到并行的山陽/東海道
     新幹線 —— pickSeg 缺「在来線班次不得借用新幹線分段」的对称防线；另有 projToTrack 索引
     定位取首个落段命中的远段，截取被端点校验否决后退回站间直线（ソニック 偏离 2.5km）
  4) とき 新潟→東京 在高崎停 13 分钟后瞬移 40.8km —— 高崎|熊谷 源数据只有 26m 残段，
     pickSeg 挑中后整段长度≈0（真实上越新幹線几何按 本庄早稲田 拆分登记）
四条都是「列车跑到自己不可能走的线路上」。本脚本用页面里的 __mjr3d.e2e 钩子把它们钉成可重复的断言：

  · tripLegs：每个区间抽样 5 个时刻，检查「列车位置 → 本班次途经线路几何」的最大距离
  · jumpScan：抽样班次逐 2 分钟解算，检查相邻时刻位移 >40km 的瞬移
  · wrongPolarityScan：全量班次逐腿检查站对选段的新幹線/在来線极性是否与班次线路集合一致
  · segSanityScan：全量班次逐腿检查选段几何是否撑得起站对（残段 / 端点错位）
  · 运転日互斥：按 data/service_calendar.json 检查成对列车（基本区间/延伸区间）
    同一时刻只开一条，终点须与冻结日期的运転日规则一致（延伸日→ext_to，否则 base_to）

用法（需要一个静态服务器，默认 8766）：
  python3 -m http.server 8766 -d mini-japanrail-3d &
  python3 scripts/line_regression_check.py                      # 校验本地 app.js
  python3 scripts/line_regression_check.py --url https://jr.suki.ing/   # 校验线上
  python3 scripts/line_regression_check.py --mutex-only --freeze 2026-11-01T03:00:00+09:00
退出码：0 通过；1 有断言失败；2 环境/加载失败。
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, time, urllib.request, datetime

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# 断言阈值(km)。サンライズ瀬戸 修复后各区间 ≤0.16；ソニック 最差 宇佐→杵築 0.86
# （日豊本線该段官方几何粒度粗，属数据侧残差，非渲染串线；远离修复前的 2.5km 级偏离）
LIMITS = [
    {"name": "サンライズ瀬戸", "from": "東京", "to": "高松", "maxKm": 0.5},
    {"name": "サンライズ瀬戸", "from": "東京", "to": "琴平", "maxKm": 0.5},
    {"name": "ソニック", "from": "博多", "to": "大分", "maxKm": 1.0},
]
JUMP_KM = 40


def parse_freeze(s):
    return int(datetime.datetime.fromisoformat(s).timestamp() * 1000)


def load_service_calendar(root):
    p = os.path.join(root, "data", "service_calendar.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def calendar_dates(svc):
    out = set()
    for season in svc.get("seasons") or []:
        out |= set(season.get("dates") or [])
    return out


def norm_term(s):
    """站名归一：站牌 term 用显示名（如「高松(香川県)」），班次终点用归一化站名（「高松」）。"""
    return re.sub(r"[（(][^)）]*[)）]", "", str(s or "")).strip()


def in_any_window(wins, minute):
    """冻结分钟是否落在任一班次运行窗内（与页面 windowShift 的跨零点规则一致）。"""
    for w in wins:
        m = minute
        if m < w["w0"] and m + 1440 <= w["w1"]:
            m += 1440
        if w["w0"] <= m <= w["w1"]:
            return True
    return False


class CDP:
    def __init__(self, port, chrome, width, height, no_proxy):
        self.port = port
        self.prof = tempfile.mkdtemp(prefix="mjr_e2e_")
        args = [chrome, "--headless=new", "--remote-debugging-port=%d" % port,
                "--user-data-dir=" + self.prof, "--no-first-run", "--no-default-browser-check",
                "--use-gl=angle", "--use-angle=metal", "--window-size=%d,%d" % (width, height)]
        if no_proxy:
            args.append("--no-proxy-server")
        args.append("about:blank")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self._id = 0

    def connect(self, timeout=40):
        import websocket
        end = time.time() + timeout
        wsu = None
        while time.time() < end:
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % self.port, timeout=2))
                pg = [t for t in tabs if t.get("type") == "page"]
                if pg:
                    wsu = pg[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not wsu:
            raise RuntimeError("CDP 未就绪 (port %d)" % self.port)
        self.ws = websocket.create_connection(wsu, suppress_origin=True, timeout=30)

    def call(self, method, timeout=120, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        end = time.time() + timeout
        while time.time() < end:
            self.ws.settimeout(max(0.05, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("id") == mid:
                return msg
        return None

    def ev(self, expr, timeout=600):
        r = self.call("Runtime.evaluate", timeout=timeout, expression=expr, returnByValue=True, awaitPromise=True)
        res = (r or {}).get("result", {}) or {}
        if res.get("exceptionDetails"):
            raise RuntimeError("页面执行出错: " + str(res["exceptionDetails"])[:400])
        return (((res.get("result", {}) or {})).get("value"))

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        subprocess.run(["pkill", "-f", "remote-debugging-port=%d" % self.port], capture_output=True)
        subprocess.run(["rm", "-rf", self.prof], capture_output=True)


def local_page(root, url_path, app_src="./app.js"):
    """index.html 里 app.js 是线上地址；本地校验时生成同目录临时页指向本地文件。
    同时生成临时 app 副本把 TRAIN_FILES 指向本地 data/（才能测到 d/x 运転日字段），
    几何/图标等其余数据仍走线上 CDN。返回 (临时页面路径, 页面名, 临时 app 路径)。"""
    rel = (url_path or "/").lstrip("/") or "index.html"
    html_path = os.path.join(root, rel)
    if not os.path.exists(html_path):
        raise RuntimeError("找不到页面文件: " + html_path + " (用 --root 指定静态服务器根目录)")
    app_path = os.path.join(root, app_src.lstrip("./"))
    if not os.path.exists(app_path):
        raise RuntimeError("找不到 app.js: " + app_path)
    app_js = open(app_path, encoding="utf-8").read()
    app_js = app_js.replace("https://jr-static.suki.ing/data/trains_", "./data/trains_")
    fd2, app_tmp = tempfile.mkstemp(prefix="_e2e_app_", suffix=".js",
                                    dir=os.path.dirname(os.path.abspath(app_path)))
    with os.fdopen(fd2, "w", encoding="utf-8") as f:
        f.write(app_js)
    src = open(html_path, encoding="utf-8").read()
    out = src.replace("https://jr-static.suki.ing/app/app.js", "./" + os.path.basename(app_tmp))
    fd, p = tempfile.mkstemp(prefix="_e2e_", suffix=".html", dir=os.path.dirname(os.path.abspath(html_path)))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(out)
    return p, os.path.basename(p), app_tmp


def run_heavy_checks(cdp, stride, report, failures):
    """几何贴合 / 瞬移 / 极性 / 选段合理性全量扫描。返回 jumpScan 结果。"""
    for lim in LIMITS:
        trips = cdp.ev("JSON.stringify(window.__mjr3d.e2e.tripLegs(%s, %s, %s))" % (
            json.dumps(lim["name"], ensure_ascii=False), json.dumps(lim["from"], ensure_ascii=False),
            json.dumps(lim["to"], ensure_ascii=False)))
        trips = json.loads(trips)
        if not trips:
            failures.append("找不到班次 %s %s→%s" % (lim["name"], lim["from"], lim["to"]))
            report["checks"].append({"limit": lim, "trips": 0, "ok": False, "reason": "trip not found"})
            continue
        worst_all = 0.0
        bad = []
        for tr in trips:
            for leg in tr["legs"]:
                km = leg["km"]
                if km is None:
                    continue
                worst_all = max(worst_all, km)
                if km > lim["maxKm"]:
                    bad.append({"t": tr["t"], "leg": leg["A"] + "→" + leg["B"], "i": leg["i"], "km": km})
        ok = not bad
        if not ok:
            for b in bad[:6]:
                failures.append("%s %s→%s 区间 %s 偏离本线 %.2fkm (>%.2f)" % (
                    lim["name"], lim["from"], lim["to"], b["leg"], b["km"], lim["maxKm"]))
        report["checks"].append({"limit": lim, "trips": len(trips), "worstKm": round(worst_all, 3),
                                 "ok": ok, "bad": bad[:10]})

    jumps = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.jumpScan(%d))" % stride))
    report["jumps"] = jumps
    if jumps.get("jumps"):
        failures.append("瞬移扫描: %d 处相邻时刻位移 >%dkm" % (jumps["jumps"], JUMP_KM))

    polar = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.wrongPolarityScan())"))
    report["polarity"] = polar
    if polar.get("bad"):
        for s in polar.get("samples", [])[:6]:
            failures.append("%s %s 选段 %s 与新幹線/在来線极性不符 (%d 条同类)" % (
                s.get("nm") or "（无车名）", s.get("leg"), s.get("seg"), polar["bad"]))
        if not polar.get("samples"):
            failures.append("选段极性不符 %d 条" % polar["bad"])

    sanity = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.segSanityScan())"))
    report["segSanity"] = sanity
    if sanity.get("bad"):
        for s in sanity.get("samples", [])[:6]:
            failures.append("%s %s 选段 %s 长度 %.2fkm 撑不起站对直线 %.1fkm (%d 条同类)" % (
                s.get("nm") or "（无车名）", s.get("leg"), s.get("seg"), s.get("len", 0),
                s.get("chord", 0), sanity["bad"]))
        if not sanity.get("samples"):
            failures.append("选段几何与站对不符 %d 条" % sanity["bad"])
    return jumps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8766/index.html")
    ap.add_argument("--app", choices=["remote", "local"], default="remote",
                    help="local=把页面里的 app.js 指到同级文件(校验本地改动), remote=按页面原样")
    ap.add_argument("--root", default="", help="--app local 时的静态服务器根目录(默认 site/mini-japanrail-3d)")
    ap.add_argument("--chrome", default=DEFAULT_CHROME)
    ap.add_argument("--port", type=int, default=9611)
    ap.add_argument("--freeze", default="2026-10-30T22:40:00+09:00")
    ap.add_argument("--stride", type=int, default=31, help="jumpScan 抽样步长(班次), 默认 31≈3000 班")
    ap.add_argument("--mutex-only", action="store_true",
                    help="只跑运転日互斥断言，跳过几何/瞬移全量扫描（用于多日期抽查）")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--no-proxy", action="store_true", default=True)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    site_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if not os.path.exists(a.chrome):
        print("找不到 Chrome: " + a.chrome, file=sys.stderr)
        return 2
    try:
        import websocket  # noqa: F401
    except Exception:
        print("需要 websocket-client: pip install websocket-client", file=sys.stderr)
        return 2

    url = a.url
    tmp_page = None
    tmp_app = None
    if a.app == "local":
        from urllib.parse import urlsplit, urlunsplit
        u = urlsplit(url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            print("--app local 只支持本地 URL", file=sys.stderr)
            return 2
        root = a.root or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini-japanrail-3d")
        try:
            tmp_page, tmp_name, tmp_app = local_page(root, u.path)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        url = urlunsplit((u.scheme, u.netloc, "/" + tmp_name, u.query, u.fragment))

    cdp = CDP(a.port, a.chrome, a.width, a.height, a.no_proxy)
    failures = []
    try:
        cdp.connect()
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=a.width, height=a.height, deviceScaleFactor=1, mobile=False)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", source="""
(() => { const F = %d, R = Date;
  class D extends R { constructor(...x) { x.length ? super(...x) : super(F); } static now() { return F; } }
  window.Date = D;
  window.__e2eErrs = []; window.addEventListener('error', e => window.__e2eErrs.push(String(e.message)));
})();""" % parse_freeze(a.freeze))
        cdp.call("Page.navigate", url=url)

        end = time.time() + 300
        n = 0
        while time.time() < end:
            n = cdp.ev("window.__mjr3d && window.__mjr3d.e2e && window.__mjr3d.tripList ? window.__mjr3d.tripList().length : 0")
            if isinstance(n, int) and n > 1000:
                break
            time.sleep(2)
        if not (isinstance(n, int) and n > 1000):
            print("页面未加载出班次数据 (trips=%r)" % (n,), file=sys.stderr)
            return 2

        report = {"url": url, "trips": n, "checks": [], "jumps": None, "errors": []}

        jumps = None
        if not a.mutex_only:
            jumps = run_heavy_checks(cdp, a.stride, report, failures)

        # 运転日互斥: 同一时刻只允许一条在跑，终点随冻结日期的运転日规则切换
        cal = load_service_calendar(site_root)
        hooks = cdp.ev("!!(window.__mjr3d && window.__mjr3d.e2e && "
                       "typeof window.__mjr3d.e2e.runningNamed === 'function' && "
                       "typeof window.__mjr3d.e2e.namedWindows === 'function' && "
                       "typeof window.__mjr3d.e2e.boardNamed === 'function')")
        report["calendar"] = []
        if not cal:
            print("[WARN] 未找到 data/service_calendar.json，跳过运転日互斥断言", file=sys.stderr)
        elif not hooks:
            print("[WARN] 页面缺少运転日互斥 e2e 钩子（线上未更新到含该修复的版本），跳过断言",
                  file=sys.stderr)
        else:
            base_day = datetime.date.fromisoformat(a.freeze[:10])
            freeze_min = int(a.freeze[11:13]) * 60 + int(a.freeze[14:16])
            for svc in cal.get("services") or []:
                name = svc.get("name")
                rows = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.runningNamed(%s))" %
                                         json.dumps(name, ensure_ascii=False)))
                rows = [r for r in rows if r.get("from") == svc.get("from")]
                wins = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.namedWindows(%s))" %
                                         json.dumps(name, ensure_ascii=False)))
                wins = [w for w in wins if w.get("from") == svc.get("from")]
                dates = calendar_dates(svc)
                detail = {"service": name, "running": rows, "windows": wins, "dates": len(dates), "ok": True}
                if not wins:
                    detail["ok"] = False
                    failures.append("运転日互斥: %s 在当前日型数据里找不到任何记录（数据缺失或车名变更）" % name)
                elif len(rows) > 1:
                    detail["ok"] = False
                    failures.append("运転日互斥: %s 冻结 %s 同时有 %d 条在跑: %s" % (
                        name, a.freeze, len(rows), ", ".join((r.get("from") or "") + "→" + (r.get("to") or "") for r in rows)))
                elif not rows and in_any_window(wins, freeze_min):
                    detail["ok"] = False
                    failures.append("运転日互斥: %s 冻结 %s 在运行时段内却没有任何一条在跑（d/x 过滤误杀或车名变更）" % (name, a.freeze))
                elif rows:
                    r = rows[0]
                    svc_day = base_day - datetime.timedelta(days=1 if r.get("M2", 0) >= 1440 else 0)
                    expect_to = svc.get("ext_to") if svc_day.isoformat() in dates else svc.get("base_to")
                    detail["serviceDate"] = svc_day.isoformat()
                    detail["expectTo"] = expect_to
                    if norm_term(r.get("to")) != norm_term(expect_to):
                        detail["ok"] = False
                        failures.append("运転日互斥: %s 冻结 %s（服务日 %s）终点应为 %s，实际 %s" % (
                            name, a.freeze, svc_day.isoformat(), expect_to, r.get("to")))
                    # 站牌是「当日 0–31 时」时刻表：同刻出发行只能有当日服务日对应的那条记录
                    # （原始症状就在站牌上）。注意与「此刻在跑的那趟」是两回事：清晨的站牌
                    # 21:26 行指的是今晚发车，不是昨夜那趟跨零点尾段。
                    dep_h, dep_m = (int(x) for x in svc["dep"].split(":"))
                    board_day = base_day.isoformat()
                    board_to = svc.get("ext_to") if board_day in dates else svc.get("base_to")
                    brows = json.loads(cdp.ev("JSON.stringify(window.__mjr3d.e2e.boardNamed(%s, %s))" % (
                        json.dumps(svc.get("from"), ensure_ascii=False), json.dumps(name, ensure_ascii=False))))
                    terms = sorted({norm_term(b["term"]) for b in brows if b.get("dep") == dep_h * 60 + dep_m})
                    detail["boardServiceDate"] = board_day
                    detail["boardExpectTo"] = board_to
                    detail["boardTerms"] = terms
                    if terms != [norm_term(board_to)]:
                        detail["ok"] = False
                        failures.append("运転日互斥: %s 冻结 %s 站牌 %s 同刻出发终点应为 [%s]（服务日 %s），实际 %s" % (
                            name, a.freeze, svc.get("from"), board_to, board_day, terms or "空"))
                report["calendar"].append(detail)

        errs = json.loads(cdp.ev("JSON.stringify((window.__e2eErrs||[]).slice(0,10))"))
        report["errors"] = errs
        if errs:
            failures.append("页面运行时报错 %d 条" % len(errs))

        print(json.dumps(report, ensure_ascii=False, indent=1))
        if a.json:
            open(a.json, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=1))

        if failures:
            print("\nFAIL:")
            for f in failures:
                print("  - " + f)
            return 1
        print("\nPASS: %s (%d 班次数据, %s)" % (
            "线路贴合与瞬移扫描全部通过" if jumps else "运転日互斥断言通过",
            n, ("瞬移扫描 %d 段" % jumps.get("moves", 0)) if jumps else "跳过几何全量扫描"))
        return 0
    finally:
        cdp.close()
        for p in (tmp_page, tmp_app):
            if p and os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    sys.exit(main())

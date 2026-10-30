#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
service_calendar.py — 运転日日历：把「同一列车被拆成基本/延伸两条记录」改成按日期互斥

背景（2026-10-30 事故）：サンライズ瀬戸 每天的基本记录（東京→高松(香川県)）与
延长记录（東京→琴平）在源数据里各存一条、rday 都是 7。页面按 rday 日型过滤，
两条同时上屏 —— 同一列物理车变成了两趟，其一还只能跑在东海道新干线上。
rday 只有「平日 / 周六 / 周日·假日」三档，表达不了「周五・休日前」这类具体日期，
所以日期必须单独维护：

  data/service_calendar.json   人工维护每季运転日（公开信息，一季一次）
  build_trains.py              构建期调用本模块，把日期烘焙进记录：
                                 延伸记录  d = [运転日]   （仅这些日期开行）
                                 基本记录  x = [运転日]   （除这些日期外开行）
  refresh.yml                  每周全量重跑构建，规则自动生效，不需要每周手改

防回归：规则若在「运転日尚未过完」的季度里匹配不到成对记录（源改了发车时刻、
站名或不再拆两条），构建直接失败 —— CI 不提交、不上线，旧数据保持，人会看到
明确报错。与日历无关的重复（源里其它截短/成对记录）只打印警告，不阻断刷新。
"""
import datetime
import json
import re

JST = datetime.timezone(datetime.timedelta(hours=9))


def norm(name):
    """与页面 normName 一致：去括号注记、ケ→ヶ、去尾部「駅」"""
    return re.sub(r"\([^)]*\)", "", str(name or "")).replace("ケ", "ヶ").rstrip("駅").strip()


def dep_min(rec):
    return int(str(rec["w"]).split(",")[0])


def load(path):
    with open(path, encoding="utf-8") as f:
        cal = json.load(f)
    if not isinstance(cal.get("services"), list):
        raise ValueError("%s: 缺少 services 列表" % path)
    for rule in cal["services"]:
        for key in ("name", "from", "dep", "base_to", "ext_to", "seasons"):
            if key not in rule:
                raise ValueError("%s: 规则缺少字段 %s" % (path, key))
        if not re.fullmatch(r"\d{1,2}:\d{2}", str(rule["dep"])):
            raise ValueError("%s: dep 需为 HH:MM" % path)
        for s in rule["seasons"]:
            if not s.get("dates"):
                raise ValueError("%s: %s 的 seasons 项没有 dates" % (path, rule["name"]))
            for d in s["dates"]:
                datetime.date.fromisoformat(d)
    return cal


def rule_dates(rule):
    out = set()
    for s in rule.get("seasons", []):
        out.update(s.get("dates", []))
    return sorted(out)


def rule_active(rule, today):
    """季度未结束（还有今天及以后的运転日）→ 规则必须能匹配上源数据。"""
    return any(d >= today for d in rule_dates(rule))


def _dep_text(dep):
    h, m = str(dep).split(":")
    return int(h) * 60 + int(m)


def apply_calendar(recs, names_of, calendar, log=print):
    """把日历写进 recs（原地）。names_of(tid) -> [站名...] or None。

    返回 {"pairs": [(base_tid, ext_tid, rule_name)], "warnings": [...],
          "active_unmatched": [rule_name...], "covered": {(base_tid, ext_tid)}}。
    成对条件：同始发站、同发车分钟、基本记录停站序列是延伸记录的严格前缀、
    rday 位掩码有交集（同一天可能同时出现才构成重复）。
    """
    covered = set()
    pairs = []
    warnings = []
    active_unmatched = []
    for rule in calendar.get("services", []):
        dates = rule_dates(rule)
        dep = _dep_text(rule["dep"])
        from_n, base_n, ext_n = norm(rule["from"]), norm(rule["base_to"]), norm(rule["ext_to"])
        base_tids, ext_tids = [], []
        for tid, rec in recs.items():
            names = names_of(tid)
            if not names or len(names) < 2 or dep_min(rec) != dep:
                continue
            if norm(names[0]) != from_n:
                continue
            last = norm(names[-1])
            if last == base_n:
                base_tids.append(tid)
            elif last == ext_n:
                ext_tids.append(tid)
        matched = []
        for b in base_tids:
            nb = [norm(x) for x in names_of(b)]
            for e in ext_tids:
                ne = [norm(x) for x in names_of(e)]
                if len(ne) <= len(nb) or ne[:len(nb)] != nb:
                    continue
                if not (recs[b]["r"] & recs[e]["r"]):
                    continue
                matched.append((b, e))
        if not matched:
            msg = "%s %s %s: 日历有规则但源数据没有成对记录（时刻/站名可能已变，或源已改为单条）" % (
                rule["name"], rule["from"], rule["dep"])
            warnings.append(msg)
            if rule_active(rule, datetime.datetime.now(JST).date().isoformat()):
                active_unmatched.append(msg)
            continue
        if len(matched) > 1:
            warnings.append("%s: 匹配到 %d 对成对记录，全部按互斥处理" % (rule["name"], len(matched)))
        for b, e in matched:
            recs[e]["d"] = sorted(set(recs[e].get("d") or []) | set(dates))
            recs[b]["x"] = sorted(set(recs[b].get("x") or []) | set(dates))
            covered.add((b, e))
            pairs.append((b, e, rule["name"]))
        log("[calendar] %s %s %s: 延伸 %s / 基本 %s，%d 个运転日"
            % (rule["name"], rule["from"], rule["dep"],
               "+".join(matched[0][1:]), matched[0][0], len(dates)))
    return {"pairs": pairs, "warnings": warnings,
            "active_unmatched": active_unmatched, "covered": covered}


def decode_times(rec, tm):
    """s 串解码为 (arr, dep)，与页面 parseTrip 一致；长度不符返回 None。"""
    jas = (tm or {}).get("s_jas") or []
    N = len(jas)
    if N < 2:
        return None
    s = [int(x) for x in str(rec["s"]).split(",")]
    if len(s) != 2 * N - 2:
        return None
    arr = [0] * N
    dep = [0] * N
    dep[0] = arr[0] = s[0]
    for i in range(1, N):
        arr[i] = dep[i - 1] + s[2 * i - 1]
        dep[i] = arr[i] + (s[2 * i] if 2 * i < len(s) else 0)
    return arr, dep


def prefix_dups(recs, names_of, times_of, covered, classes):
    """与日历无关的重复扫描：优等列车里「同车种、同始发、同发车分钟、停站严格前缀、
    日型有交集、共享段时刻完全相同」且未被日历覆盖的成对记录。
    时刻完全相同 = 同一列物理车被源拆成两份；只用于报告，不阻断刷新。"""
    groups = {}
    for tid, rec in recs.items():
        if rec.get("i") not in classes:
            continue
        names = names_of(tid)
        if not names or len(names) < 2 or not times_of(tid):
            continue
        groups.setdefault((rec.get("i"), norm(names[0]), dep_min(rec)), []).append(tid)
    out = []
    for (icon, origin, dep), tids in groups.items():
        if len(tids) < 2:
            continue
        for a in tids:
            na = [norm(x) for x in names_of(a)]
            aa, da = times_of(a)
            for b in tids:
                if a == b or (a, b) in covered:
                    continue
                nb = [norm(x) for x in names_of(b)]
                if len(nb) <= len(na) or nb[:len(na)] != na:
                    continue
                if not (recs[a]["r"] & recs[b]["r"]):
                    continue
                ab, db = times_of(b)
                if aa[:len(na)] != ab[:len(na)] or da[:len(na) - 1] != db[:len(na) - 1]:
                    continue
                out.append({"base": a, "ext": b, "icon": icon, "origin": origin, "dep": dep,
                            "base_to": na[-1], "ext_to": nb[-1]})
    return out

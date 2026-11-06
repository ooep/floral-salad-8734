#!/usr/bin/env node
/** sweep_topo.js — 参数扫描：旋转比例方案 找最优 Beck 布局参数 */
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const load = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');

const { CONFIG, Projection } = (() => {
  const src = load('js/config.js') + '\n' + load('js/projection.js');
  return new Function(src + '\n;return {CONFIG, Projection};')();
})();
const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'topology.json'), 'utf8'));
const projected = Projection.project(data.stations, 1600, 1000, CONFIG.CANVAS_PADDING);

const ids = Object.keys(projected.coords);
const orig = {};
for (const id of ids) orig[id] = { x: projected.coords[id].x, y: projected.coords[id].y };

// 换乘锚点
const lineCount = {};
for (const l of data.lines) for (const sid of l.stations) lineCount[sid] = (lineCount[sid] || 0) + 1;
const isAnchor = {};
for (const s of data.stations) isAnchor[s.stationId] = !!(s.isTransfer || (lineCount[s.stationId] || 0) >= 2);

const segments = [];
for (const l of data.lines) {
  const sts = l.stations;
  for (let i = 0; i < sts.length - 1; i++) {
    const a = sts[i], b = sts[i + 1];
    if (a === b) continue;
    const pa = projected.coords[a], pb = projected.coords[b];
    if (!pa || !pb) continue;
    const len0 = Math.hypot(pb.x - pa.x, pb.y - pa.y);
    if (len0 < 0.5) continue;
    segments.push({ a, b, len0, line: l.id });
  }
}

const SNAP = [];
for (let a = 0; a < 360; a += 45) SNAP.push((a * Math.PI) / 180);
function angleDiff(a, b) { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }

function stats(c) {
  let sd = 0, dl = 0, n = 0, s2 = 0, s4 = 0;
  for (const s of segments) {
    const a = c[s.a], b = c[s.b];
    const ang = Math.atan2(b.y - a.y, b.x - a.x);
    let best = SNAP[0], bd = 1e9;
    for (const sa of SNAP) { const d = Math.abs(angleDiff(ang, sa)); if (d < bd) { bd = d; best = sa; } }
    sd += Math.abs(angleDiff(ang, best));
    dl += Math.abs(Math.hypot(b.y - a.y, b.x - a.x) - s.len0);
    n++;
    if (bd < 2 * Math.PI / 180) s2++;
    if (bd < 4 * Math.PI / 180) s4++;
  }
  return { dev: (sd / n * 180 / Math.PI).toFixed(2), dl: (dl / n).toFixed(2), s2: (s2 / n * 100).toFixed(1), s4: (s4 / n * 100).toFixed(1) };
}

function run(opts) {
  const c = JSON.parse(JSON.stringify(projected.coords));
  const { R0, ITERS, WS, WL, ANCHOR, MAXST } = opts;
  const segCnt = {};
  for (const s of segments) { segCnt[s.a] = (segCnt[s.a] || 0) + 1; segCnt[s.b] = (segCnt[s.b] || 0) + 1; }
  for (let it = 0; it < ITERS; it++) {
    const rotFrac = R0 * (1 - 0.6 * (it / ITERS));
    const wS = WS * (1 + 0.5 * (it / ITERS));
    const force = {};
    for (const id of ids) force[id] = { x: 0, y: 0 };
    for (const s of segments) {
      const a = c[s.a], b = c[s.b];
      const dx = b.x - a.x, dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 0.5;
      const ux = dx / len, uy = dy / len;
      const ang = Math.atan2(dy, dx);
      let best = SNAP[0], bd = 1e9;
      for (const sa of SNAP) { const d = Math.abs(angleDiff(ang, sa)); if (d < bd) { bd = d; best = sa; } }
      const dev = angleDiff(ang, best);
      if (Math.abs(dev) > 0.01) {
        const rot = -dev * rotFrac; // 负号：向最近八方向旋转
        const cosr = Math.cos(rot), sinr = Math.sin(rot);
        const u2x = ux * cosr - uy * sinr, u2y = ux * sinr + uy * cosr;
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const half = len / 2;
        force[s.a].x += (mx - u2x * half - a.x);
        force[s.a].y += (my - u2y * half - a.y);
        force[s.b].x += (mx + u2x * half - b.x);
        force[s.b].y += (my + u2y * half - b.y);
      }
      // 长度保持
      const dl = len - s.len0;
      if (Math.abs(dl) > 0.01) {
        force[s.a].x += WL * dl * ux;
        force[s.a].y += WL * dl * uy;
        force[s.b].x -= WL * dl * ux;
        force[s.b].y -= WL * dl * uy;
      }
    }
    for (const id of ids) {
      const n = segCnt[id] || 1;
      let fx = force[id].x / Math.sqrt(n);
      let fy = force[id].y / Math.sqrt(n);
      // 弹簧
      fx += wS * (orig[id].x - c[id].x);
      fy += wS * (orig[id].y - c[id].y);
      if (isAnchor[id]) { fx *= ANCHOR; fy *= ANCHOR; }
      const dist = Math.hypot(fx, fy);
      if (dist > MAXST) { const k = MAXST / dist; fx *= k; fy *= k; }
      c[id].x += fx; c[id].y += fy;
    }
  }
  return c;
}

/** 交叉数：异线、无共享端点的线段对求交点 */
function countCrossings(c) {
  const byLine = new Map();
  for (const s of segments) {
    if (!byLine.has(s.line)) byLine.set(s.line, []);
    byLine.get(s.line).push({ a: s.a, b: s.b, ax: c[s.a].x, ay: c[s.a].y, bx: c[s.b].x, by: c[s.b].y });
  }
  let cross = 0;
  const lines = [...byLine.keys()];
  for (let i = 0; i < lines.length; i++) {
    for (let j = i + 1; j < lines.length; j++) {
      const A = byLine.get(lines[i]), B = byLine.get(lines[j]);
      for (const a of A) for (const b of B) {
        if (a.a === b.a || a.a === b.b || a.b === b.a || a.b === b.b) continue;
        const x1 = a.ax, y1 = a.ay, x2 = a.bx, y2 = a.by;
        const x3 = b.ax, y3 = b.ay, x4 = b.bx, y4 = b.by;
        const d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
        if (Math.abs(d) < 1e-9) continue;
        const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d;
        const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / d;
        if (t > 0.0001 && t < 0.9999 && u > 0.0001 && u < 0.9999) cross++;
      }
    }
  }
  return cross;
}

function report(label, c) {
  const s = stats(c);
  console.log(`${label} => dev=${s.dev}° dl=${s.dl}px snap≤2=${s.s2}% snap≤4=${s.s4}% crossings=${countCrossings(c)}`);
}

const combos = [
  { R0: 1.0, ITERS: 70, WS: 0.012, WL: 0.35, ANCHOR: 0.4, MAXST: 4 },
];
console.log('基线:', JSON.stringify(stats(projected.coords)), 'crossings=' + countCrossings(projected.coords));
for (const c of combos) {
  const r = run(c);
  report(JSON.stringify(c), r);
  // 位移统计
  let md = 0, mx = 0;
  for (const id of ids) { const d = Math.hypot(r[id].x - projected.coords[id].x, r[id].y - projected.coords[id].y); md += d; if (d > mx) mx = d; }
  console.log("meanDisp=", (md/ids.length).toFixed(1), "maxDisp=", mx.toFixed(1));
}

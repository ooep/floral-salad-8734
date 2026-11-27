#!/usr/bin/env node
/** debug_topo.js — 逐轮追踪拓扑变形的吸附率/位移，定位算法问题 */
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const load = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');

const { CONFIG, Projection, Topo } = (() => {
  const src = load('js/config.js') + '\n' + load('js/projection.js') + '\n' + load('js/topo.js');
  return new Function(src + '\n;return {CONFIG, Projection, Topo};')();
})();

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'topology.json'), 'utf8'));
const projected = Projection.project(data.stations, 1600, 1000, CONFIG.CANVAS_PADDING);
const coords = JSON.parse(JSON.stringify(projected.coords));

// 手动复刻 Topo.run 的内循环（与 js/topo.js 同步）
const ids = Object.keys(coords);
const orig = {};
for (const id of ids) orig[id] = { x: coords[id].x, y: coords[id].y };
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
    const pa = coords[a], pb = coords[b];
    if (!pa || !pb) continue;
    const dx = pb.x - pa.x, dy = pb.y - pa.y;
    const len0 = Math.sqrt(dx * dx + dy * dy);
    if (len0 < 0.5) continue;
    segments.push({ a, b, len0 });
  }
}

const SNAP = [];
for (let a = 0; a < 360; a += 45) SNAP.push((a * Math.PI) / 180);
function angleDiff(a, b) { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
function snapPct(tolDeg) {
  const tol = tolDeg * Math.PI / 180;
  let n = 0, total = 0;
  for (const s of segments) {
    const a = coords[s.a], b = coords[s.b];
    const ang = Math.atan2(b.y - a.y, b.x - a.x);
    total++;
    for (const sa of SNAP) if (Math.abs(angleDiff(ang, sa)) <= tol) { n++; break; }
  }
  return (n / total * 100).toFixed(1);
}

const ITERS = CONFIG.TOPO_ITERATIONS, W_A = CONFIG.TOPO_W_ANGLE, W_L = CONFIG.TOPO_W_LENGTH,
  W_S = CONFIG.TOPO_W_SPRING, LR = CONFIG.TOPO_LR, ANCHOR = CONFIG.TOPO_TRANSFER_ANCHOR, MAX_STEP = CONFIG.TOPO_MAX_STEP;

console.log(`start: snap≤2=${snapPct(2)}% snap≤4=${snapPct(4)}%`);
let totalDisp = 0;
for (let iter = 0; iter < ITERS; iter++) {
  const wA = W_A * (1 - 0.45 * (iter / ITERS));
  const wS = W_S * (1 + 0.4 * (iter / ITERS));
  const grad = {};
  for (const id of ids) grad[id] = { x: 0, y: 0 };
  let snapF = 0, lenF = 0;
  for (const s of segments) {
    const a = coords[s.a], b = coords[s.b];
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 0.5;
    const ux = dx / len, uy = dy / len, px = -uy, py = ux;
    const angle = Math.atan2(dy, dx);
    let best = SNAP[0], bd = 1e9;
    for (const sa of SNAP) { const d = Math.abs(angleDiff(angle, sa)); if (d < bd) { bd = d; best = sa; } }
    const dev = angleDiff(angle, best);
    if (Math.abs(dev) > 0.001) {
      const gx = -wA * dev * (len / 2) * px;
      const gy = -wA * dev * (len / 2) * py;
      grad[s.a].x += gx; grad[s.a].y += gy;
      grad[s.b].x -= gx; grad[s.b].y -= gy;
      snapF += Math.abs(dev);
    }
    const dl = len - s.len0;
    const lx = -W_L * dl * ux, ly = -W_L * dl * uy;
    grad[s.a].x += lx; grad[s.a].y += ly;
    grad[s.b].x -= lx; grad[s.b].y -= ly;
    lenF += Math.abs(dl);
  }
  let disp = 0, step = 0;
  for (const id of ids) {
    const g = grad[id];
    let mvx = g.x + wS * (orig[id].x - coords[id].x) * 2;
    let mvy = g.y + wS * (orig[id].y - coords[id].y) * 2;
    if (isAnchor[id]) { mvx *= ANCHOR; mvy *= ANCHOR; }
    mvx *= LR; mvy *= LR;
    const dist = Math.sqrt(mvx * mvx + mvy * mvy);
    if (dist > MAX_STEP) { const k = MAX_STEP / dist; mvx *= k; mvy *= k; }
    coords[id].x += mvx; coords[id].y += mvy;
    disp += dist; step += 1;
  }
  totalDisp += disp;
  if (iter % 4 === 0 || iter === ITERS - 1) {
    console.log(`iter ${String(iter).padStart(2)}: snap≤2=${snapPct(2)}% snap≤4=${snapPct(4)}% |avgDisp=${(disp / step).toFixed(2)} avg|dev|=${(snapF / segments.length * 180 / Math.PI).toFixed(1)}° avg|dl|=${(lenF / segments.length).toFixed(2)}px`);
  }
}

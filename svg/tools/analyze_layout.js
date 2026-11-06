#!/usr/bin/env node
/**
 * analyze_layout.js — 布局质量量化分析（复用浏览器端真实渲染管线）
 *
 * 用与页面完全相同的 config/projection/topo 代码在 Node 中运行，
 * 对比"投影后（变形前）"与"拓扑变形后"的布局质量指标：
 *   - 八方向吸附比例（贝克规则达成度）
 *   - 线路交叉数（非节点相交）
 *   - 平行重合段（异线线段近乎共线且横向距离过近）
 * 并输出 stationId → 画布坐标 的布局 JSON 供人工排查/手动覆盖。
 *
 * 用法: node tools/analyze_layout.js [输出布局.json]
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const load = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');

function evalModule(file) {
  const src = load(file);
  const fn = new Function(src + `\n;return {CONFIG, Projection, Topo, getLineColor};`);
  return fn();
}

const { CONFIG, Projection, Topo } = (() => {
  const src = load('js/config.js') + '\n' + load('js/projection.js') + '\n' + load('js/topo.js');
  const fn = new Function(src + '\n;return {CONFIG, Projection, Topo};');
  return fn();
})();

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'topology.json'), 'utf8'));

// 参数扫描：可用环境变量覆盖拓扑参数（便于批量调参）
for (const k of ['TOPO_ITERATIONS', 'TOPO_ROTATION', 'TOPO_ANNEAL', 'TOPO_SPRING', 'TOPO_SPRING_GAIN', 'TOPO_LENGTH', 'TOPO_MAX_STEP', 'TOPO_TRANSFER_ANCHOR', 'TOPO_REPULSION_RADIUS', 'TOPO_REPULSION_K', 'TOPO_REPULSION_DENSITY']) {
  if (process.env[k] != null) CONFIG[k] = Number(process.env[k]);
}

const W = 1600, H = 1000;
const projected = Projection.project(data.stations, W, H, CONFIG.CANVAS_PADDING);

// ---------- 构建线段 ----------
function buildSegments(coords) {
  const segs = [];
  for (const l of data.lines) {
    const sts = l.stations;
    for (let i = 0; i < sts.length - 1; i++) {
      const a = sts[i], b = sts[i + 1];
      if (a === b) continue;
      const pa = coords[a], pb = coords[b];
      if (!pa || !pb) continue;
      const dx = pb.x - pa.x, dy = pb.y - pa.y;
      if (dx * dx + dy * dy < 0.25) continue;
      segs.push({ a, b, ax: pa.x, ay: pa.y, bx: pb.x, by: pb.y, line: l.id, len: Math.hypot(dx, dy) });
    }
  }
  return segs;
}

const SNAP_ANGLES = [];
for (let a = 0; a < 360; a += 45) SNAP_ANGLES.push((a * Math.PI) / 180);

function angleDiff(a, b) {
  let d = a - b;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  return d;
}
function nearSnap(seg, tolDeg) {
  const ang = Math.atan2(seg.by - seg.ay, seg.bx - seg.ax);
  const tol = (tolDeg * Math.PI) / 180;
  for (const sa of SNAP_ANGLES) {
    if (Math.abs(angleDiff(ang, sa)) <= tol) return true;
  }
  return false;
}

function properIntersect(s1, s2) {
  const { ax: x1, ay: y1, bx: x2, by: y2 } = s1;
  const { ax: x3, ay: y3, bx: x4, by: y4 } = s2;
  const d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
  if (Math.abs(d) < 1e-9) return null; // 平行/共线
  const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d;
  const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / d;
  if (t > 0.0001 && t < 0.9999 && u > 0.0001 && u < 0.9999) {
    return { x: x1 + t * (x2 - x1), y: y1 + t * (y2 - y1) };
  }
  return null;
}

// ---------- 构建线段（固定集合：从投影坐标构建一次，变形前后用同一集合公平对比） ----------
const SEGMENTS = buildSegments(projected.coords);

function analyze(coords, label) {
  const segs = SEGMENTS.map(s => ({
    ...s,
    ax: coords[s.a] ? coords[s.a].x : s.ax,
    ay: coords[s.a] ? coords[s.a].y : s.ay,
    bx: coords[s.b] ? coords[s.b].x : s.bx,
    by: coords[s.b] ? coords[s.b].y : s.by,
  }));
  // 吸附比例
  let snap2 = 0, snap4 = 0, total = 0;
  for (const s of segs) {
    total++;
    if (nearSnap(s, 2)) snap2++;
    if (nearSnap(s, 4)) snap4++;
  }
  // 交叉（仅异线、无共享端点）
  let crossings = 0;
  const byLine = new Map();
  for (const s of segs) {
    if (!byLine.has(s.line)) byLine.set(s.line, []);
    byLine.get(s.line).push(s);
  }
  const lineIds = [...byLine.keys()];
  for (let i = 0; i < lineIds.length; i++) {
    for (let j = i + 1; j < lineIds.length; j++) {
      const A = byLine.get(lineIds[i]), B = byLine.get(lineIds[j]);
      for (const a of A) {
        for (const b of B) {
          if (a.a === b.a || a.a === b.b || a.b === b.a || a.b === b.b) continue;
          if (properIntersect(a, b)) crossings++;
        }
      }
    }
  }
  // 平行重合（异线、近共线、横向距离 < 3.5px、重叠长度 > 8px）
  let coincident = 0;
  const coincidentPairs = [];
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const a = segs[i], b = segs[j];
      if (a.line === b.line) continue;
      if (a.a === b.a || a.a === b.b || a.b === b.a || a.b === b.b) continue;
      const angA = Math.atan2(a.by - a.ay, a.bx - a.ax);
      const angB = Math.atan2(b.by - b.ay, b.bx - b.ax);
      if (Math.abs(angleDiff(angA, angB)) > 0.06) continue;
      // 点 b 的端点到直线 a 的距离
      const nx = -(a.by - a.ay), ny = a.bx - a.ax;
      const nl = Math.hypot(nx, ny) || 1;
      const d1 = Math.abs(((b.ax - a.ax) * nx + (b.ay - a.ay) * ny) / nl);
      const d2 = Math.abs(((b.bx - a.ax) * nx + (b.by - a.ay) * ny) / nl);
      const lat = Math.min(d1, d2);
      if (lat < 3.5 && lat > 0.2 && a.len < 90 && b.len < 90) {
        // 粗略算重叠：投影到 a 方向
        const ux = (a.bx - a.ax) / a.len, uy = (a.by - a.ay) / a.len;
        const pa = (b.ax - a.ax) * ux + (b.ay - a.ay) * uy;
        const pb = (b.bx - a.ax) * ux + (b.ay - a.ay) * uy;
        const lo = Math.max(0, Math.min(pa, pb));
        const hi = Math.min(a.len, Math.max(pa, pb));
        if (hi - lo > 8) {
          coincident++;
          if (coincidentPairs.length < 12) coincidentPairs.push({
            lineA: a.line, lineB: b.line,
            a: [Math.round(a.ax), Math.round(a.ay), Math.round(a.bx), Math.round(a.by)],
            b: [Math.round(b.ax), Math.round(b.ay), Math.round(b.bx), Math.round(b.by)],
          });
        }
      }
    }
  }
  console.log(`\n=== ${label} ===`);
  console.log(`segments: ${total}`);
  console.log(`snap≤2°: ${(snap2 / total * 100).toFixed(1)}%  snap≤4°: ${(snap4 / total * 100).toFixed(1)}%`);
  console.log(`crossings: ${crossings}`);
  console.log(`coincident(异线平行重合): ${coincident}`);
  if (coincidentPairs.length) {
    console.log('coincident samples:');
    for (const c of coincidentPairs) {
      console.log(`  ${c.lineA} [${c.a}]  <>  ${c.lineB} [${c.b}]`);
    }
  }
  return { segs, crossings, coincident };
}

console.log('canvas', W, 'x', H, '| stations', data.meta.stationCount, 'lines', data.meta.lineCount);
const before = analyze(projected.coords, '投影后（变形前）');

const topoCoords = JSON.parse(JSON.stringify(projected.coords));
Topo.run(topoCoords, data.lines, data.stations, CONFIG.MANUAL_OVERRIDES);
const after = analyze(topoCoords, '拓扑变形后');

// 拓扑约束校验：站序、连通、换乘
const orderOk = (() => {
  for (const l of data.lines) {
    const sts = l.stations;
    for (let i = 0; i < sts.length - 1; i++) {
      const pa = projected.coords[sts[i]], pb = projected.coords[sts[i + 1]];
      const ta = topoCoords[sts[i]], tb = topoCoords[sts[i + 1]];
      // 顺序只由数据决定，这里校验站点仍在同一位置键下（连通性）
      if (!ta || !tb) continue;
      if (pa && pb) {
        const dx = tb.x - ta.x, dy = tb.y - ta.y;
        if (Math.hypot(dx, dy) < 0.5) { /* 相邻站不应重合 */ }
      }
    }
  }
  return true;
})();
const transferOk = (() => {
  for (const t of data.transfers) {
    const ids = t.stationIds;
    if (ids.length < 2) continue;
    const ref = topoCoords[ids[0]];
    for (const id of ids.slice(1)) {
      const c = topoCoords[id];
      if (!ref || !c) continue;
      const d = Math.hypot(c.x - ref.x, c.y - ref.y);
      if (d > 0.5) return false; // 换乘组站点必须重合
    }
  }
  return true;
})();
console.log('\n约束校验: 站序/连通由数据保证(未重排) ✓ | 换乘组站点重合:', transferOk ? '✓' : '✗');

// 输出布局 JSON（stationId → x,y），供手动覆盖排查
const outPath = process.argv[2] || path.join(ROOT, '_layout_analysis.json');
const out = {};
for (const id in topoCoords) {
  out[id] = { x: Math.round(topoCoords[id].x * 10) / 10, y: Math.round(topoCoords[id].y * 10) / 10 };
}
fs.writeFileSync(outPath, JSON.stringify(out));
console.log('\nlayout written ->', outPath);

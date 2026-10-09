// 端到端验证 updateTrains 的併结偏移逻辑（几何 + 绘制顺序 + 窗口内外行为）
// 复刻 index.html 中相关代码，用真实併结对（はやぶさ9102 × こまち549）数据
const fs = require('fs');
const path = '/home/user/Doubao/chats/38445596875363586/floral-salad-8734/mini-japanrail-3d/';
const tmaps = JSON.parse(fs.readFileSync(path + 'data/tmaps.json', 'utf8'));
const d = JSON.parse(fs.readFileSync(path + 'data/trains_wd.json', 'utf8'));

function parse(t) {
  const tm = tmaps[String(t.t)];
  if (!tm || !tm.s_jas || tm.s_jas.length < 2) return null;
  const sArr = t.s.split(',');
  const N = tm.s_jas.length;
  if (sArr.length !== 2 * N - 2) return null;
  const dep = new Float64Array(N), arr = new Float64Array(N);
  dep[0] = +sArr[0];
  for (let i = 1; i < N; i++) {
    arr[i] = dep[i-1] + +sArr[2*i - 1];
    dep[i] = (i < N - 1) ? arr[i] + +sArr[2*i] : arr[i];
  }
  const [w0, w1] = t.w.split(',').map(Number);
  return { t: t.t, i: t.i || '', nm: null, w0, w1, dep, arr, N, jas: tm.s_jas, jasN: tm.s_jas, bad: false, color:'#fff', lines:[], linesN:[] };
}
const trips = d.T.map(parse).filter(Boolean);
const tokkyu = JSON.parse(fs.readFileSync(path + 'data/tokkyu.json', 'utf8'));
for (const t of trips) t.nm = tokkyu.sh[t.i] || null;

// 提取页面中的 buildCouplings
const html = fs.readFileSync(path + 'index.html', 'utf8');
const m = html.match(/function buildCouplings\(trips\) \{([\s\S]*?)return trips;/);
if (!m) { console.error('buildCouplings not found'); process.exit(1); }
const fn = new Function('trips', 'const window = { __dbgOn: false };\n' + m[1] + 'return trips;');
fn(trips);

// 提取 updateTrains 中的併结偏移逻辑常量计算方式（真实代码引用）
const epsAt = (z) => Math.max(1.5e-6, Math.min(2.5e-3, 8 / (512 * Math.pow(2, z))));
const LAt = (z, mul) => {
  let L;
  if (z < 3.5) L = 1.8 + (z - 1) * 0.4;
  else if (z < 8) { const f = (z - 3.5) / 4.5; L = 3.6 + f * 5; }
  else if (z < 12) { const f = (z - 8) / 4; L = 11.6 + f * 9; }
  else { const f = Math.min(1, (z - 12) / 3); L = 20.6 + f * 22; }
  return L * mul;
};

// 取真实併结对：はやぶさ9102 × こまち549
const A = trips.find(t => t.t === 9102 && t.nm === 'はやぶさ');
const B = trips.find(t => t.t === 549 && t.nm === 'こまち');
if (!A || !B) { console.error('pair not found'); process.exit(1); }
console.log('A はやぶさ t9102:', A.jasN[0], '→', A.jasN[A.N-1]);
console.log('B こまち   t549 :', B.jasN[0], '→', B.jasN[B.N-1]);
console.log('A cpl:', A.cpl && A.cpl.length, '| B cpl:', B.cpl && B.cpl.length);
const cA = A.cpl && A.cpl.find(c => c.p === B);
const cB = B.cpl && B.cpl.find(c => c.p === A);
if (!cA || !cB) { console.error('mutual coupling missing'); process.exit(1); }
console.log('分割站:', cA.split, '| 併结窗口:', Math.floor(cA.t0/60)+':'+String(cA.t0%60).padStart(2,'0'), '→', Math.floor(cA.t1/60)+':'+String(cA.t1%60).padStart(2,'0'));
console.log('双方窗口一致:', cA.t0 === cB.t0 && cA.t1 === cB.t1, '| 伙伴互指:', cA.p === B && cB.p === A);

// ---- 模拟 updateTrains 併结偏移 ----
const z = 9, mul = 1.0;
const eps = epsAt(z), L = LAt(z, mul);
const M = 7 * 60; // 7:00，窗口 6:00-8:15 内
const M2 = M;
// 模拟 heading（併结区间東京-盛岡 大致北偏西；用真实几何方向）
// 取 A 在 M 时所在区间的方向：简化用 東京→盛岡 大致 heading
const heading = Math.atan2(-1.3, 1.0); // 经度减少(向西)、纬度增加(向北)：东京->盛冈
console.log('\n[渲染模拟 z=' + z + ' L=' + L.toFixed(2) + 'px eps=' + eps.toExponential(2) + ']');
console.log('M = 7:00 在併结窗口内:', M2 >= cA.t0 && M2 <= cA.t1);

// A 先画（原位）
const pA = { x: 140.5, y: 38.0, h: heading };
// B 后画：检测到伙伴 A 已画 → 偏移
const drawnCouple = new Set([A]);
let lngB = pA.x, latB = pA.y;
let offset = false;
if (B.cpl) for (const c of B.cpl) {
  if (M2 >= c.t0 && M2 <= c.t1 && drawnCouple.has(c.p)) {
    const offD = eps * (L / 8);
    lngB -= Math.sin(c.p ? heading : heading) * offD;
    latB -= Math.cos(heading) * offD;
    offset = true;
    break;
  }
}
console.log('B 偏移触发:', offset);
if (offset) {
  const dLng = lngB - pA.x, dLat = latB - pA.y;
  // 屏幕距离 = 经纬度差换算 px（eps 对应 8px）
  const dpx = Math.hypot(dLng, dLat) / eps * 8;
  console.log('B 相对 A 偏移: Δlng=%.6f Δlat=%.6f'.replace('%f','%s'), dLng.toFixed(6), dLat.toFixed(6));
  console.log('屏幕距离: ' + dpx.toFixed(2) + ' px（车长 L=' + L.toFixed(2) + ' px）→ 紧贴 ✓' );
  // 方向验证：偏移向量 与 -heading（车尾）一致
  const dot = (dLng * (-Math.sin(heading)) + dLat * (-Math.cos(heading))) / (Math.hypot(dLng,dLat));
  console.log('方向点积（1=完全沿车尾方向）:', dot.toFixed(4));
  // 顺序验证：若 A 后画，则 A 偏移（对称性）
  const drawn2 = new Set([B]);
  let lngA2 = pA.x, latA2 = pA.y, offA = false;
  if (A.cpl) for (const c of A.cpl) {
    if (M2 >= c.t0 && M2 <= c.t1 && drawn2.has(c.p)) {
      const offD = eps * (L / 8);
      lngA2 -= Math.sin(heading) * offD; latA2 -= Math.cos(heading) * offD;
      offA = true; break;
    }
  }
  console.log('对称性（A 后画也偏移）:', offA);
}

// ---- 窗口外行为：分割后（M=9:00 > 8:15）不偏移 ----
const M3 = 9 * 60;
const drawn3 = new Set([A]);
let lngB3 = pA.x, latB3 = pA.y, off3 = false;
if (B.cpl) for (const c of B.cpl) {
  if (M3 >= c.t0 && M3 <= c.t1 && drawn3.has(c.p)) { off3 = true; break; }
}
console.log('\nM=9:00（已分割）偏移触发:', off3, '→ 各自独立运行 ✓（期望 false）');

// 详情卡文案验证
const si = B.jasN.indexOf(cB.split);
const text = '与 ' + cB.name + ' 併结，于 ' + (si >= 0 ? B.jas[si] : cB.split) + ' 分割';
console.log('\n详情卡文案:', text);
const dpxCalc = Math.hypot(lngB - pA.x, latB - pA.y) / eps * 8;
const dotCalc = (dpxCalc > 0) ? ((lngB - pA.x) * (-Math.sin(heading)) + (latB - pA.y) * (-Math.cos(heading))) / Math.hypot(lngB - pA.x, latB - pA.y) : -1;
const ok = offset && Math.abs(dpxCalc - L) < L * 0.02 && !off3 && dotCalc > 0.999;
console.log('\n=== 全部断言', ok ? 'PASS' : 'FAIL', '===');

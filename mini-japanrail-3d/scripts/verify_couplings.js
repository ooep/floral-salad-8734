// 验证 index.html 中的 buildCouplings 实现（从页面提取函数体，喂真实数据）
const fs = require('fs');
const path = '/home/user/Doubao/chats/38445596875363586/floral-salad-8734/mini-japanrail-3d/';
const tmaps = JSON.parse(fs.readFileSync(path + 'data/tmaps.json', 'utf8'));
const d = JSON.parse(fs.readFileSync(path + 'data/trains_wd.json', 'utf8'));
const tokkyu = JSON.parse(fs.readFileSync(path + 'data/tokkyu.json', 'utf8'));
const ICON_NAME = {'関':'はるか','紀':'くろしお'};
function normName(s){ return s; }

// --- 复刻 parseTrip 的关键字段 ---
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
  const jas = tm.s_jas, jasN = jas.map(normName);
  return { t: t.t, i: t.i || '', nm: null, w0, w1, dep, arr, N, jas, jasN, bad: false };
}
// 爱称（简化：只按 tokkyu.sh）
function nameOf(t) { return tokkyu.sh[t.i] || null; }

const trips = d.T.map(parse).filter(Boolean);
for (const t of trips) t.nm = nameOf(t);

// --- 从 index.html 提取 buildCouplings 函数体并执行 ---
const html = fs.readFileSync(path + 'index.html', 'utf8');
const m = html.match(/function buildCouplings\(trips\) \{([\s\S]*?)return trips;/);
if (!m) { console.error('buildCouplings not found'); process.exit(1); }
const fn = new Function('trips', 'const window = { __dbgOn: false };\n' + m[1] + 'return trips;');
fn(trips);

// --- 统计与抽样核对 ---
let cplTrips = trips.filter(t => t.cpl && t.cpl.length);
console.log('trip 总数:', trips.length);
console.log('带併结信息的 trip 数:', cplTrips.length);
console.log('併结对总数:', cplTrips.reduce((s,t)=>s+t.cpl.length,0) / 2);

// 找 はやぶさ×こまち 与 関空×紀州路 验证
function findPair(nameA, nameB) {
  const hits = [];
  for (const t of trips) {
    if (!t.cpl) continue;
    for (const c of t.cpl) {
      if (nameOf(t) === nameA && c.name === nameB) hits.push({ a: t, c });
    }
  }
  return hits;
}
const hk = findPair('はやぶさ', 'こまち');
console.log('\nはやぶさ×こまち 併结对:', hk.length);
if (hk[0]) {
  const t = hk[0].a, c = hk[0].c;
  const si = t.jasN.indexOf(c.split);
  console.log('  样例: 分割站 =', c.split, '| 併结窗口', Math.floor(c.t0/60)+':'+String(c.t0%60).padStart(2,'0'), '→', Math.floor(c.t1/60)+':'+String(c.t1%60).padStart(2,'0'));
  console.log('  路线:', t.jas[0], '→', t.jas[t.N-1], '| 伙伴:', c.name, '| 详情卡文案 =', '与 ' + c.name + ' 併结，于 ' + (si>=0?t.jas[si]:c.split) + ' 分割');
}
const kk = findPair('はるか', 'くろしお');
console.log('はるか×くろしお 併结对:', kk.length);
// 関空快速(関)×紀州路快速(紀): 爱称是 ICON_NAME 兜底, tokkyu.sh 里是 '関'/'紀'?
// 检查 tokkyu.nm 是否映射 関/紀
let kanku = 0;
for (const t of trips) if (t.cpl) for (const c of t.cpl) {
  if ((t.i === '関' || t.i === '紀') && (c.name === '紀' || c.name === '関') || (t.i==='関' && c.name==='紀')) {}
}
const rk = trips.filter(t => (t.i === '関' || t.i === '紀') && t.cpl && t.cpl.length);
console.log('関/紀(関空快速/紀州路快速) 併结 trip 数:', rk.length);
if (rk[0]) {
  const t = rk[0], c = t.cpl[0];
  const si = t.jasN.indexOf(c.split);
  console.log('  样例: 分割站 =', c.split, '| 路线', t.jas[0], '→', t.jas[t.N-1], '| 伙伴', c.name);
}

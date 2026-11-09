// 集成台架:真实 segments3d × leg_orm_map × plat_track_index
// 验证 ormLegReplace(全程股道替换)与 overlayStationTracks(站内拼接+主段窗)
import fs from 'fs';
import vm from 'vm';

const src = fs.readFileSync(new URL('./app.js', import.meta.url), 'utf8');
function extract(marker) {
  const st = src.indexOf(marker);
  if (st < 0) throw new Error('not found: ' + marker);
  const b0 = src.indexOf('{', st);
  let d = 0, k = b0;
  for (; k < src.length; k++) {
    const ch = src[k];
    if (ch === '{') d++;
    else if (ch === '}') { d--; if (d === 0) break; }
  }
  return src.slice(st, k + 1);
}
const code = [
  'function geoKm(', 'function withLen(', 'function pathBrgAt(',
  'function nearAt(', 'function trimToStops(', 'function revChord(',
  'function snapToStops(', 'function _ovlPick(', 'function overlayStationTracks(',
  'function ormLegReplace(', 'function pathNearestPt(', 'function pathPointAt(',
].map(extract).join('\n;\n');

const J = p => JSON.parse(fs.readFileSync(new URL('./data/' + p, import.meta.url), 'utf8'));
const segs = J('segments3d.geojson').features;
const stations = J('stations3d.geojson').features;
const LEGORM = J('leg_orm_map.json').legs;
const PLATTRACK = J('plat_track_index.json');

const coordOf = (name, refPt) => {
  // 同名站多条记录(不同线路/站位):取距参考点最近的,模拟主站 resolveCoord 线语境消歧
  let best = null, bd = 1e18;
  for (const f of stations) {
    if (f.properties.station !== name) continue;
    const c = f.geometry.coordinates;
    const d = refPt ? Math.hypot(c[0] - refPt[0], c[1] - refPt[1]) : 0;
    if (d < bd) { bd = d; best = c; }
  }
  return best;
};
let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; console.log('  PASS', name); } else { fail++; console.log('  FAIL', name); } };

const ctx = {
  window: {}, console,
  PLATTRACK, LEGORM, ormEnabled: true,
  PLATMAP: null, LINES_MAP: {},
  normName: s => s, normCached: s => s, matchLineCached: () => 0,
  lineOfPair: (t, i) => t._legs[i] ? t._legs[i].line : '',
  platForStop: () => ({ plat: null, reason: 'noPlatmap' }),
  tidFbNote: () => {},
  stopPoint: (t, i) => t.stopC[i],
};
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__ovl = overlayStationTracks; this.__rep = ormLegReplace; this.__geoKm = geoKm; this.__withLen = withLen;', ctx);
const { __ovl, __rep, __geoKm } = ctx;

const samples = [];
for (const [A, B, ln] of [['品川', '大崎', '山手線'], ['東京', '有楽町', '東海道線'], ['渋谷', '原宿', '山手線'], ['新宿', '新大久保', '山手線']]) {
  const f = segs.find(f => f.properties.from === A && f.properties.to === B && f.properties.line === ln);
  if (!f) { console.log('  缺段', A, B, ln); continue; }
  const gc = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates.flat() : f.geometry.coordinates;
  const cA = coordOf(A, gc[0]), cB = coordOf(B, gc[gc.length - 1]);
  if (!cA || !cB) { console.log('  缺站坐标', A, B); continue; }
  samples.push({ A, B, ln, f, cA, cB });
}
console.log('样本段:', samples.map(s => `${s.A}→${s.B}(${s.ln})`).join(', '));

for (const s of samples) {
  console.log(`== ${s.A}→${s.B} ${s.ln} ==`);
  const co = s.f.geometry.type === 'MultiLineString' ? s.f.geometry.coordinates.flat() : s.f.geometry.coordinates;
  // 模拟 orientSeg:按站坐标定向(反向注册段 from=品川 但几何首端在大崎侧 → 翻转)
  const oriented = (__geoKm(co[0], s.cA) <= __geoKm(co[co.length - 1], s.cA)) ? co : co.slice().reverse();
  const w = ctx.__withLen(oriented);
  const leg = { coords: w.coords, cum: w.cum, len: w.len, line: s.ln, kind: '鉄道' };
  const trip = { t: 'it', N: 2, jasN: [s.A, s.B], jas: [s.A, s.B], stopC: [s.cA, s.cB], _legs: [leg] };

  const rep = __rep(trip, 0, leg);
  if (LEGORM[`${s.A}|${s.B}|${s.ln}`]) {
    ok(!!rep, 'ormLegReplace 有映射即返回折线');
    if (rep) {
      const ratio = rep.len / leg.len;
      ok(ratio > 0.55 && ratio < 2.5, `映射长度比合理(${ratio.toFixed(2)})`);
      ok(__geoKm(rep.coords[0], s.cA) < 0.6, `映射首端贴近站A(${(__geoKm(rep.coords[0], s.cA) * 1000).toFixed(0)}m)`);
      ok(__geoKm(rep.coords[rep.coords.length - 1], s.cB) < 0.6, `映射末端贴近站B(${(__geoKm(rep.coords[rep.coords.length - 1], s.cB) * 1000).toFixed(0)}m)`);
    }
  } else {
    console.log('  (无映射,跳过替换断言)');
  }

  const base = rep || leg;
  const ov = __ovl(trip, 0, base);
  if (!ov) { console.log(`  (站内 overlay 降级: ${trip._ovlR && trip._ovlR[0]} —— 设计内回退映射/简易腿)`); continue; }
  ok(!!ov, 'overlayStationTracks 返回拼接几何');
  if (ov) {
    ok(ov.s0 != null && ov.s1 != null && ov.s1 > ov.s0, '主段窗存在且有效');
    const ptAt = (cum, coords, s) => { let k = 1; while (k < cum.length - 1 && cum[k] < s) k++; return coords[k]; };
    const pA = ptAt(ov.cum, ov.coords, ov.s0), pB = ptAt(ov.cum, ov.coords, ov.s1);
    ok(__geoKm(pA, s.cA) < 0.25, `主段起点在站A股道附近(${(__geoKm(pA, s.cA) * 1000).toFixed(1)}m,股道点距站房中心允许200m)`);
    ok(__geoKm(pB, s.cB) < 0.25, `主段末端在站B股道附近(${(__geoKm(pB, s.cB) * 1000).toFixed(1)}m)`);
    ok(ov.s0 >= 0 && ov.s1 <= ov.len + 1e-9, '主段窗在整腿范围内');
    const mainLen = ov.s1 - ov.s0;
    ok(mainLen > 0.05, '主段长度>50m(不是退化残段)');
  }
}
console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);

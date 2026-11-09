// 全量扫描:凡有 ORM 映射的段,验证 ormLegReplace + overlay 主段窗的批量化表现
import fs from 'fs';
import vm from 'vm';

const src = fs.readFileSync(new URL('./app.js', import.meta.url), 'utf8');
function extract(marker) {
  const st = src.indexOf(marker);
  const b0 = src.indexOf('{', st);
  let d = 0, k = b0;
  for (; k < src.length; k++) { const ch = src[k]; if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) break; } }
  return src.slice(st, k + 1);
}
const code = [
  'function geoKm(', 'function withLen(', 'function pathBrgAt(', 'function nearAt(',
  'function trimToStops(', 'function revChord(', 'function snapToStops(',
  'function _ovlPick(', 'function overlayStationTracks(', 'function ormLegReplace(',
].map(extract).join('\n;\n');

const J = p => JSON.parse(fs.readFileSync(new URL('./data/' + p, import.meta.url), 'utf8'));
const segs = J('segments3d.geojson').features;
const stations = J('stations3d.geojson').features;
const LEGORM = J('leg_orm_map.json').legs;
const PLATTRACK = J('plat_track_index.json');
const stByName = {};
for (const f of stations) (stByName[f.properties.station] || (stByName[f.properties.station] = [])).push(f.geometry.coordinates);
const coordOf = (name, refPt) => {
  const cs = stByName[name];
  if (!cs) return null;
  let best = null, bd = 1e18;
  for (const c of cs) { const d = refPt ? Math.hypot(c[0] - refPt[0], c[1] - refPt[1]) : 0; if (d < bd) { bd = d; best = c; } }
  return best;
};
const ctx = {
  window: {}, console, PLATTRACK, LEGORM, ormEnabled: true, PLATMAP: null, LINES_MAP: {},
  normName: s => s, normCached: s => s, matchLineCached: () => 0,
  lineOfPair: (t, i) => t._legs[i] ? t._legs[i].line : '',
  platForStop: () => ({ plat: null, reason: 'noPlatmap' }), tidFbNote: () => {},
  stopPoint: (t, i) => t.stopC[i],
};
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__ovl = overlayStationTracks; this.__rep = ormLegReplace; this.__geoKm = geoKm; this.__withLen = withLen;', ctx);
const { __ovl, __rep, __geoKm, __withLen } = ctx;

const keys = Object.keys(LEGORM);
const LIMIT = Math.min(keys.length, 400);
const stat = { n: 0, repOk: 0, repBad: 0, ovOk: 0, ovNull: 0, mainWinBad: 0, byReason: {}, badSamples: [] };
for (const key of keys.slice(0, LIMIT)) {
  const [A, B, ln] = key.split('|');
  const f = segs.find(f => f.properties.from === A && f.properties.to === B && f.properties.line === ln);
  if (!f) continue;
  const gc = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates.flat() : f.geometry.coordinates;
  const cA = coordOf(A, gc[0]), cB = coordOf(B, gc[gc.length - 1]);
  if (!cA || !cB) continue;
  stat.n++;
  const oriented = (__geoKm(gc[0], cA) <= __geoKm(gc[gc.length - 1], cA)) ? gc : gc.slice().reverse();
  const w = __withLen(oriented);
  const leg = { coords: w.coords, cum: w.cum, len: w.len, line: ln, kind: '鉄道' };
  const trip = { t: 'sw', N: 2, jasN: [A, B], jas: [A, B], stopC: [cA, cB], _legs: [leg] };
  const rep = __rep(trip, 0, leg);
  if (rep) stat.repOk++; else stat.repBad++;
  const ov = __ovl(trip, 0, rep || leg);
  if (ov) {
    stat.ovOk++;
    if (!(ov.s1 > ov.s0)) stat.mainWinBad++;
  } else {
    stat.ovNull++;
    const r = trip._ovlR && trip._ovlR[0];
    stat.byReason[r || 'null'] = (stat.byReason[r || 'null'] || 0) + 1;
    if (stat.badSamples.length < 8) stat.badSamples.push(key + ' → ' + r);
  }
}
console.log('扫描段数:', stat.n, '(有映射的总共', keys.length, '段)');
console.log('ormLegReplace 成功:', stat.repOk, '弃用:', stat.repBad);
console.log('overlay 成功:', stat.ovOk, '失败:', stat.ovNull, '主段窗异常:', stat.mainWinBad);
console.log('失败原因分布:', stat.byReason);
console.log('失败样例:', stat.badSamples);

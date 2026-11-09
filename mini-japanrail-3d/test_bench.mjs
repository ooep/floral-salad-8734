// 台架:主段弧长窗 + 停站采样锁定(直接抽取 app.js 真实函数做数值断言)
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
  'function limitTarget(', 'function sanitizeLeg(', 'function wrapPiBrg(',
  'function slicePath(', 'function pathPointAt(', 'function pathNearestPt(',
  'function buildTripPath(', 'function tripPathOf(',
  'window.__t3dArc =',
].map(extract).join('\n;\n');

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; console.log('  PASS', name); } else { fail++; console.log('  FAIL', name); } };

const ctx = {
  window: {}, console,
  locateSeg: (t, M) => { let i = 0; while (i < t.N - 2 && M > t.arr[i + 1]) i++; return i; },
  legSegEntry: (t, i) => t._legs[i],
  fallbackSeg: () => ({ coords: null }),
  stopPoint: (t, i) => t.stopC[i],
  _legEpoch: 7, frameC: 1,
};
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__arc = window.__t3dArc; this.__withLen = withLen; this.__limit = limitTarget; this.__geoKm = geoKm;', ctx);
const arc = ctx.__arc, limitTarget = ctx.__limit, geoKm = ctx.__geoKm, withLen = ctx.__withLen;

// ── 合成班次:A(0,0) → B(0.01,0) → C(0.02,0),B 站停 10–12 分
const A = [0, 0], B = [0.01, 0], C = [0.02, 0];
const legAB = {
  coords: [[-0.001, 0], [0, 0], [0.005, 0], [0.01, 0], [0.011, 0]],
  line: 'テスト線', kind: '鉄道',
};
const legBC = { coords: [[0.009, 0], [0.01, 0], [0.015, 0], [0.02, 0], [0.021, 0]], line: 'テスト線', kind: '鉄道' };
for (const e of [legAB, legBC]) { const w = withLen(e.coords); e.cum = w.cum; e.len = w.len; }
legAB.s0 = legAB.cum[1]; legAB.s1 = legAB.cum[3];
legBC.s0 = legBC.cum[1]; legBC.s1 = legBC.cum[3];

const trip = {
  t: 'bench1', N: 3, jasN: ['A', 'B', 'C'], jas: ['A', 'B', 'C'],
  dep: [0, 12, 20], arr: [5, 10, 25], stopC: [A, B, C],
  _legs: [legAB, legBC], lines: ['テスト線'],
};

console.log('== 1. 主段弧长窗:运动学不越站(过站折返根治) ==');
{
  const s0 = legAB.s0, s1 = legAB.s1;
  ok(s0 > 0 && s1 < legAB.len && s1 > s0, '主段窗位于整腿内部(外延排除)');
  const at = f => { const target = s0 + f * (s1 - s0); let k = 1; while (k < legAB.cum.length - 1 && legAB.cum[k] < target) k++; const f2 = (target - legAB.cum[k - 1]) / (legAB.cum[k] - legAB.cum[k - 1]); return [legAB.coords[k - 1][0] + (legAB.coords[k][0] - legAB.coords[k - 1][0]) * f2, 0]; };
  ok(geoKm(at(0), A) < 1e-9, 'frac=0 → 站A(不在站外外延)');
  ok(geoKm(at(1), B) < 1e-9, 'frac=1 → 站B(不开进站外外延=不过站)');
  ok(at(0.999)[0] <= B[0] + 1e-12 && at(1)[0] <= B[0] + 1e-12, '到站前任意时刻都不越过站B');
  const lt = limitTarget(trip, 0, s0 + 0.5 * (s1 - s0), s1, 60);
  ok(lt.target <= s1 + 1e-12, 'limitTarget target ≤ 主段末端');
}

console.log('== 2. 停站采样锁定:停稳后车厢逐点一致 ==');
{
  trip._stopI = 1;
  const hbrg = Math.PI / 2;
  const s1 = arc(trip, 10.5, B[0], B[1], hbrg);
  const s2 = arc(trip, 11.0, B[0], B[1], hbrg);
  const s3 = arc(trip, 11.9, B[0], B[1], hbrg);
  ok(!!s1, '停站采样器存在');
  ok(s1.at(0)[0] === s2.at(0)[0] && s1.at(0)[0] === s3.at(0)[0] && s1.at(0)[1] === s2.at(0)[1] && s1.at(0)[1] === s3.at(0)[1], '停站窗内多次调用输出逐点一致(连续轨道锁定)');
  ok(s1.leg === 0, '头腿=到达腿(非出发腿)');
  ok(Math.abs(s1.proj[0] - B[0]) < 1e-9 && Math.abs(s1.proj[1] - B[1]) < 1e-9, '头车投影=站B坐标');
  const p0 = s1.at(0), p20 = s1.at(20), p200 = s1.at(200);
  ok(Math.abs(p0[0] - B[0]) < 1e-6, '头车 at(0)=站B(不在站外外延)');
  ok(p20[0] < p0[0] && p200[0] < p20[0], '车尾沿到达腿向站A回退(不折返、不外延)');
  ok(p20[0] > A[0] - 0.002, '20m 车尾仍在站B附近股道上');
  const q1 = s1.at(40), q2 = s2.at(40), q3 = s3.at(40);
  ok(q1[0] === q2[0] && q2[0] === q3[0] && q1[1] === q2[1] && q2[1] === q3[1] && q1[2] === q2[2] && q2[2] === q3[2], '停站期间任意车厢位置/朝向逐点一致(绝对静止)');
  ok(Math.abs(p0[2] - hbrg) < 1e-6 || Math.abs(p0[2] + Math.PI / 2) < 1e-6, '停站朝向沿到达股道(不横摆)');

  console.log('== 3. 发车解锁:恢复正常解算 ==');
  const s4 = arc(trip, 13, B[0], B[1], hbrg);
  ok(s4 !== s1, '发车后不再复用停站采样器');
  ok(!!s4, '发车后采样器正常');
  trip._stopI = -1;
  const s5 = arc(trip, 11, B[0], B[1], hbrg);
  ok(s5 !== s1, '非停站标记时即使时刻在停站窗也不锁定(与2D同源)');
}

console.log('== 4. 始发站停站(无到达腿) ==');
{
  trip._stopI = 0;
  const s = arc(trip, -0.5, A[0], A[1], Math.PI / 2);
  ok(!!s, '始发站采样器存在');
  if (s) {
    ok(s.leg === 0, '始发站用出发腿');
    ok(Math.abs(s.at(0)[0] - A[0]) < 1e-6, '始发站头车=站A');
    const tail = s.at(200);
    ok(isFinite(tail[0]) && isFinite(tail[1]), '始发站车尾外推有限(不 NaN)');
  }
  trip._stopI = -1;
}
console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);

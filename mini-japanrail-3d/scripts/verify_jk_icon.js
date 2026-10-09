#!/usr/bin/env node
/* verify_jk_icon.js — 验证京滨东北线车头图标修复逻辑
 * 复刻 index.html 中 normName / isKeihinTohokuTrip / lineIconFor，
 * 对 data/tmaps.json 全量班次计算图标索引，断言：
 *  1) 所有 JK 列车(含根岸線 或 [東海道本線,東北本線]+JK站) → 300(天蓝E233)
 *  2) 上野東京線(1055/2155) 不被误判为 JK
 *  3) 山手線单线路(4331/2507/7250) → 109 不受影响
 *  4) 抽查特急(爱称)仍走 tokkyu 分支
 * 用法: node scripts/verify_jk_icon.js
 */
const fs = require('fs');
const path = require('path');

const DATA = path.join(__dirname, '..', 'data');
const tmaps = JSON.parse(fs.readFileSync(path.join(DATA, 'tmaps.json'), 'utf8'));
const ATLAS = JSON.parse(fs.readFileSync(path.join(DATA, 'train_icons_atlas.json'), 'utf8'));

/* ---- 复刻 index.html 逻辑 ---- */
function normName(n) { return String(n).replace(/\([^)]*\)/g, '').replace(/[ケヶ]/g, 'ヶ').replace(/駅$/, '').trim(); }

const ICON_SKIP_LINES = new Set(['山手線', '東海道本線', '東北本線']);
const ICON_PRIORITY_LINES = new Set(['武蔵野線']);
const JK_ONLY_STA = new Set(['与野', '北浦和', '南浦和', '蕨', '西川口', '川口', '東十条', '王子', '上中里', '大井町', '大森', '蒲田', '桜木町', '関内', '石川町', '山手', '根岸', '磯子', '新子安', '新杉田', '洋光台', '港南台', '本郷台']);
function isKeihinTohokuTrip(t) {
  if (!t || !t.lines || !t.lines.length) return false;
  if (t._jk !== undefined) return t._jk;
  let jk = false;
  if (t.lines.includes('根岸線') || t.lines.includes('京浜東北線')) jk = true;
  else if (t.lines.length === 2 && t.lines.includes('東海道本線') && t.lines.includes('東北本線')) {
    for (let i = 0; i < t.N && !jk; i++) if (JK_ONLY_STA.has(normName(t.jas[i]))) jk = true;
  }
  t._jk = jk;
  return jk;
}
function lineIconFor(t) {
  if (!ATLAS || !t || !t.lines) return -1;
  if (isKeihinTohokuTrip(t)) { const v = ATLAS.line['根岸線']; if (v !== undefined) return v; }
  if (t.lines.length > 1) {
    for (const ln of ICON_PRIORITY_LINES) { if (t.lines.includes(ln)) { const v = ATLAS.line[ln]; if (v !== undefined) return v; } }
    for (const ln of t.lines) { if (ICON_SKIP_LINES.has(ln)) continue; const v = ATLAS.line[ln]; if (v !== undefined) return v; }
    if (ATLAS.fallback !== undefined) return ATLAS.fallback;
  }
  for (let li = 0; li < t.lines.length; li++) {
    if (t.lines.length > 1 && t.lines[li] === '山手線') continue;
    const v = ATLAS.line[t.lines[li]]; if (v !== undefined) return v;
  }
  return -1;
}
function trainIconIdx(t, lineName) {
  if (!ATLAS) return -1;
  if (t.nm && ATLAS.tokkyu[t.nm] !== undefined) return ATLAS.tokkyu[t.nm];
  if (isKeihinTohokuTrip(t)) { const v = ATLAS.line['根岸線']; if (v !== undefined) return v; }
  if (t.lines.length > 1 && t.lines.every(ln => ICON_SKIP_LINES.has(ln)) && ATLAS.fallback !== undefined) return ATLAS.fallback;
  if (lineName && ATLAS.line[lineName] !== undefined) return ATLAS.line[lineName];
  const li = lineIconFor(t);
  if (li >= 0) return li;
  return ATLAS.fallback;
}
/* ---- 构建班次视图 ---- */
const trips = [];
for (const [tid, v] of Object.entries(tmaps)) {
  const jas = (v.s_jas || []).map(String);
  trips.push({ tid, lines: (v.lines || []).map(String), jas, N: jas.length, nm: '' });
}

let fail = 0;
const report = (ok, msg) => { if (!ok) { fail++; } console.log((ok ? 'PASS' : 'FAIL') + '  ' + msg); };

/* 1) 显式指定班次断言 */
const expect300 = ['840', '5416', '5581', '3183', '8422', '5208', '2561', '5301'];
for (const tid of expect300) {
  const t = trips.find(x => x.tid === tid);
  if (!t) { report(false, '班次 ' + tid + ' 不存在'); continue; }
  const idx = lineIconFor(t);
  report(idx === 300, `JK班次 ${tid} (${t.lines.join(',')} ${t.jas[0]}→${t.jas[t.N-1]}) 图标=${idx} 期望300`);
}
/* 1b) 上野东京线直通(古河→小田原)不应为JK */
{
  const t = trips.find(x => x.tid === '5343');
  const jk = isKeihinTohokuTrip(t);
  const idx = lineIconFor(t);
  report(!jk && idx !== 300, `上野東京線 5343 (古河→小田原) 非JK (jk=${jk}, 图标=${idx})`);
}
/* 2) 上野東京線不误判 + 纯干道组合改E217湘南色(489) */
const notJK = ['1055', '2155', '5343'];
for (const tid of notJK) {
  const t = trips.find(x => x.tid === tid);
  const jk = isKeihinTohokuTrip(t);
  const idx = lineIconFor(t);
  report(!jk, `上野東京線 ${tid} 未被误判为JK (jk=${jk})`);
  report(idx === ATLAS.fallback, `上野東京線 ${tid} 图标=${idx} 期望E217湘南色兜底(${ATLAS.fallback}) 而非W223(143)`);
}
/* 3) 山手线单线路 */
for (const tid of ['4331', '2507', '7250']) {
  const t = trips.find(x => x.tid === tid);
  const idx = lineIconFor(t);
  report(idx === 109, `山手線 ${tid} 图标=${idx} 期望109`);
}

/* 4) 全量一致性: 所有含根岸線 或 两线路含JK站的班次 → 300; 统计 */
let jkCnt = 0, rootCnt = 0, tohoku2 = 0, jkViaSta = 0;
for (const t of trips) {
  const jk = isKeihinTohokuTrip(t);
  if (!jk) continue;
  jkCnt++;
  const idx = lineIconFor(t);
  if (idx !== 300) { report(false, `JK班次 ${t.tid} 图标=${idx} 应为300`); }
  if (t.lines.includes('根岸線')) rootCnt++;
  if (t.lines.length === 2 && t.lines.includes('東海道本線') && t.lines.includes('東北本線')) { tohoku2++; jkViaSta++; }
}
console.log(`\n全量: JK班次=${jkCnt} (含根岸線=${rootCnt}, 两线路JK站判定=${jkViaSta})`);

/* 5) 两线路[東海道本線,東北本線]但非JK的班次(上野東京線等)图标分布 */
const twoLineNonJK = {};
for (const t of trips) {
  if (t.lines.length === 2 && t.lines.includes('東海道本線') && t.lines.includes('東北本線') && !isKeihinTohokuTrip(t)) {
    const idx = lineIconFor(t);
    twoLineNonJK[idx] = (twoLineNonJK[idx] || 0) + 1;
  }
}
console.log('两线路非JK班次图标分布:', JSON.stringify(twoLineNonJK));

/* 6) 模拟 WebGL 兜底路径: p[3] 常用值 */
for (const p3 of ['東北線', '東海道線', '山手線', '根岸線']) {
  const t = trips.find(x => x.tid === '5581');
  const idx = trainIconIdx(t, p3);
  report(idx === 300, `JK班次5581 trainIconIdx(p3=${p3}) = ${idx} 期望300`);
}
const yt = trips.find(x => x.tid === '4331');
report(trainIconIdx(yt, '山手線') === 109, `山手线4331 trainIconIdx(p3=山手線) = ${trainIconIdx(yt, '山手線')} 期望109`);

/* 7) 武藏野线直通: 直通列车车体为E231武藏野线涂装, 应优先武蔵野線图标(152) */
const musa = [
  ['1660', ['東北本線', '武蔵野線']],        // 府中本町→大宮
  ['2058', ['東北本線', '京葉線', '武蔵野線']], // 大宮→海浜幕張
  ['1257', ['東北本線', '中央本線', '武蔵野線']], // 大宮→八王子
  ['3970', ['東海道本線', '横須賀線', '武蔵野線']], // 吉川美南→鎌倉
];
for (const [tid, lines] of musa) {
  const t = trips.find(x => x.tid === tid);
  const idx = lineIconFor(t);
  report(idx === 152, `武藏野线直通 ${tid} (${lines.join(',')}) 图标=${idx} 期望152(武蔵野線E231)`);
}
/* 7b) 京葉線+武蔵野線 组合(西船橋⇔海浜幕張方向) 也应取152 */
{
  let cnt = 0, ok = true;
  for (const t of trips) {
    if (t.lines.length === 2 && t.lines.includes('京葉線') && t.lines.includes('武蔵野線')) {
      cnt++;
      if (lineIconFor(t) !== 152) ok = false;
    }
  }
  report(ok && cnt > 0, `京葉線+武蔵野線 组合 ${cnt} 班次全部=152(武蔵野線E231)`);
}
/* 7c) 纯武蔵野線 / 東北本線+武蔵野線 不受影响 */
{
  let cnt = 0, ok = true;
  for (const t of trips) {
    if (t.lines.length === 1 && t.lines[0] === '武蔵野線') { cnt++; if (lineIconFor(t) !== 152) ok = false; }
    if (t.lines.length === 2 && t.lines.includes('東北本線') && t.lines.includes('武蔵野線')) { if (lineIconFor(t) !== 152) ok = false; }
  }
  report(ok, `纯武蔵野線 ${cnt} 班次及東北本線+武蔵野線全部=152`);
}

/* 8) 详情卡: 上野東京線在東海道線段 p[3]='東海道線' 必须走纯干道兜底(489) 而非西日本W223(143) */
for (const tid of ['1055', '2155', '5343']) {
  const t = trips.find(x => x.tid === tid);
  const idx = trainIconIdx(t, '東海道線');
  report(idx === ATLAS.fallback, `上野東京線 ${tid} 详情卡 trainIconIdx(p3=東海道線) = ${idx} 期望兜底(${ATLAS.fallback}) 非143`);
}

console.log(fail === 0 ? '\n✅ 全部通过' : `\n❌ ${fail} 项失败`);
process.exit(fail === 0 ? 0 : 1);

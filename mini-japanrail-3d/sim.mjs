// ESM 整文件仿真:DOM/地图桩 + 本地数据,复现「全车消失」
// 用法: node sim.mjs <app.js路径> [时刻(分钟,默认600=10:00)]
import fs from 'fs';
import path from 'path';

const APP = process.argv[2];
const MIN = +(process.argv[3] || 600);
const ROOT = path.dirname(path.resolve(APP));
const REPO = path.dirname(ROOT);

const el = () => ({
  classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
  style: { setProperty() {}, removeProperty() {}, getPropertyValue: () => '' }, dataset: {},
  addEventListener() {}, removeEventListener() {},
  appendChild() {}, setAttribute() {}, getAttribute: () => null,
  textContent: '', innerHTML: '', value: '', checked: false, disabled: false,
  getBoundingClientRect: () => ({ width: 1280, height: 800, left: 0, top: 0, right: 1280, bottom: 800 }),
  querySelector: () => null, querySelectorAll: () => [],
  children: [], childNodes: [], firstChild: null, parentNode: null,
  getContext: () => null, focus() {}, click() {}, remove() {},
});
const storage = () => { const m = new Map(); return { getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), clear: () => m.clear() }; };

function mapUrl(u0) {
  const u = String(u0).split('?')[0];
  const base = u.split('/').pop();
  if (/^(trains_(wd|sa|su)|tmaps|lines|railways)\.json$/.test(base)) return path.join(REPO, 'data', 'live', base);
  if (u.includes('/data/live/')) return path.join(REPO, 'data', 'live', base);
  if (u.includes('/data/') || u.startsWith('data/')) return path.join(ROOT, 'data', base);
  if (u.includes('/tt/manifest.json')) return path.join(ROOT, 'data', 'tt', 'manifest.json');
  return null;
}
const fetchLog = { ok: 0, miss: [] };
async function fetchStub(url, opt) {
  const u = typeof url === 'string' ? url : url.url;
  const method = (opt && opt.method) || 'GET';
  const p = mapUrl(u);
  if (p && fs.existsSync(p)) {
    fetchLog.ok++;
    return { ok: true, status: 200, headers: { get: () => null }, json: async () => JSON.parse(fs.readFileSync(p, 'utf8')), text: async () => fs.readFileSync(p, 'utf8'), arrayBuffer: async () => { const b = fs.readFileSync(p); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); } };
  }
  fetchLog.miss.push(u.slice(0, 110));
  return { ok: false, status: 404, headers: { get: () => null }, json: async () => { throw new Error('404 ' + u); }, text: async () => '404', arrayBuffer: async () => new ArrayBuffer(0) };
}

// 全局桩
const g = globalThis;
g.window = g;
g.self = g;
g.localStorage = storage();
g.sessionStorage = storage();
g.location = { protocol: 'file:', hostname: 'localhost', href: 'http://localhost/mini-japanrail-3d/index.html', search: '', hash: '', pathname: '/mini-japanrail-3d/index.html' };
Object.defineProperty(g, 'navigator', { value: { userAgent: 'node-sim', hardwareConcurrency: 8, deviceMemory: 8, language: 'zh-CN', onLine: true }, configurable: true, writable: true });
g.document = {
  getElementById: el, createElement: el, createElementNS: el,
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  body: el(), documentElement: el(), head: el(),
  fonts: { ready: Promise.resolve() }, hidden: false, visibilityState: 'visible', activeElement: null,
};
g.fetch = fetchStub;
g.Worker = class { constructor() {} postMessage() {} addEventListener() {} terminate() {} };
g.Image = class { constructor() { return el(); } };
g.indexedDB = undefined;
g.innerWidth = 1280; g.innerHeight = 800; g.devicePixelRatio = 1;
g.addEventListener = () => {}; g.removeEventListener = () => {};
g.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
g.requestAnimationFrame = () => 0; g.cancelAnimationFrame = () => {};
g.requestIdleCallback = fn => setTimeout(fn, 0); g.cancelIdleCallback = () => {};
g.alert = () => {}; g.confirm = () => true;
g.maplibregl = { Map: class { constructor() { return mapStub(); } } };

function mapStub() {
  return {
    on() {}, off() {}, once() {}, addSource() {}, addLayer() {}, removeLayer() {}, removeSource() {},
    getLayer: () => null, getSource: () => null,
    setLayoutProperty() {}, setPaintProperty() {}, setFilter() {},
    getZoom: () => 10, getMaxZoom: () => 16, setMaxZoom() {}, getMinZoom: () => 4,
    getCenter: () => ({ lng: 139.72, lat: 35.65 }), getPitch: () => 0, getBearing: () => 0,
    getLight: () => ({ position: [1, 210, 60] }),
    getCanvas: () => el(), getContainer: () => el(),
    project: () => ({ x: 0, y: 0 }), unproject: () => [139.72, 35.65],
    getBounds: () => ({ getWest: () => 130, getEast: () => 146, getSouth: () => 30, getNorth: () => 46, toArray: () => [[130, 30], [146, 46]] }),
    isMoving: () => false, isZooming: () => false, isRotating: () => false,
    loaded: () => true, isStyleLoaded: () => true, areTilesLoaded: () => true,
    triggerRepaint() {}, jumpTo() {}, flyTo() {}, easeTo() {}, fitBounds() {},
    setCenter() {}, setZoom() {}, setBearing() {}, setPitch() {},
    getStyle: () => ({ layers: [] }), setStyle() {},
    addControl() {}, removeControl() {}, resize() {},
    queryRenderedFeatures: () => [], getFeatureState: () => ({}), setFeatureState() {},
  };
}

// 生成仿真模块:替换 import URL,末尾导出内部函数
let src = fs.readFileSync(APP, 'utf8');
src = src.replace("from 'https://jr-static.suki.ing/vendor/maplibre/maplibre-gl.mjs'", "from './sim_vendor_maplibre.mjs'");
src += '\nexport { trainPosition, updateTrains, tripList, segIndex, fadeList, bufArr };\n';
const simFile = path.join(ROOT, 'app_sim_' + path.basename(APP, '.js') + '.mjs');
fs.writeFileSync(simFile, src);
fs.writeFileSync(path.join(ROOT, 'sim_vendor_maplibre.mjs'), 'export const Map = class { constructor() { return globalThis.__mapStub(); } };\nexport default { Map };\n');
g.__mapStub = mapStub;

console.log('[sim] loading', APP);
try {
  await import('file://' + simFile);
} catch (e) {
  console.log('[sim] 模块执行异常:', e.message, '\n', (e.stack || '').split('\n').slice(0, 8).join('\n'));
}

async function waitReady() {
  for (let i = 0; i < 100; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const tl = g.__mjr3d && g.__mjr3d.tripList();
      if (tl && tl.length > 0) return tl;
    } catch (e) {}
  }
  return null;
}
const trips = await waitReady();
console.log('[sim] tripList:', trips ? trips.length : 'NOT READY', 'fetch ok:', fetchLog.ok, 'miss:', fetchLog.miss.length);
if (fetchLog.miss.length) console.log('[sim] miss 样例:', fetchLog.miss.slice(0, 10));
if (!trips) { console.log('[sim] 初始化失败'); process.exit(2); }

const mod = await import('file://' + simFile);
const trainPosition = mod.trainPosition, updateTrains = mod.updateTrains;
let active = [];
for (const t of trips) {
  if (t.dep && t.arr && MIN >= t.dep[0] - 30 && MIN <= t.arr[t.N - 1] + 30) active.push(t);
  if (active.length >= 3000) break;
}
console.log('[sim] 在营班次样本:', active.length);
const stats = { n: 0, ok: 0, null: 0, nan: 0, err: 0, far: 0, errs: [], nanSample: [], nullSample: [] };
for (const t of active) {
  for (const M of [MIN - 5, MIN, MIN + 5]) {
    stats.n++;
    try {
      const p = trainPosition(t, M);
      if (!p) { stats.null++; if (stats.nullSample.length < 5) stats.nullSample.push(t.t + '@' + M); continue; }
      if (!isFinite(p[0]) || !isFinite(p[1]) || !isFinite(p[2])) {
        stats.nan++;
        if (stats.nanSample.length < 8) stats.nanSample.push({ tid: t.t, M, p: [p[0], p[1], p[2]], jas: t.jasN && t.jasN.slice(0, 4) });
      } else if (Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) stats.far++;
      else stats.ok++;
    } catch (e) {
      stats.err++;
      if (stats.errs.length < 6) stats.errs.push({ tid: t.t, M, err: e.message, stack: (e.stack || '').split('\n')[1] });
    }
  }
}
console.log('[sim] trainPosition 统计:', JSON.stringify({ n: stats.n, ok: stats.ok, null: stats.null, nan: stats.nan, err: stats.err, far: stats.far }));
if (stats.errs.length) console.log('[sim] 异常样例:', JSON.stringify(stats.errs, null, 1));
if (stats.nanSample.length) console.log('[sim] NaN 样例:', JSON.stringify(stats.nanSample, null, 1));
if (stats.nullSample.length) console.log('[sim] null 样例:', stats.nullSample);

try {
  updateTrains(MIN, 50);
  const fl = mod.fadeList.length, buf = mod.bufArr;
  let nanV = 0;
  if (buf) for (let i = 0; i < Math.min(buf.length, 60000); i++) if (!isFinite(buf[i])) nanV++;
  console.log('[sim] updateTrains 成功, fadeList =', fl, '顶点 NaN(前6万):', nanV);
} catch (e) {
  console.log('[sim] updateTrains 异常:', e.message, '\n', (e.stack || '').split('\n').slice(0, 6).join('\n'));
}
process.exit(0);

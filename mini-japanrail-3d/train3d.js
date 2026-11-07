/* ══════════════════════════════════════════════════════════════════════
   EXP train3d v3.6（exp/train3d-20261105，重建落盘版）
   高缩放把 2D 列车图标替换为真实比例 3D 模型；与主站同解算状态（updateTrains
   推送点/切线/M2），逐节车厢沿腿折线弧长铺车（行进向归一，跨腿端点匹配定向）。
   - 渲染：MapLibre custom layer('3d')，共享 GL 上下文与深度缓冲（建筑遮挡正确）；
     矩阵 = render(gl,args).defaultProjectionData.mainMatrix 右乘 T(中心)·S(米→世界)，
     顶点相对中心米制（float32 精度安全）；resetState 防共享上下文状态污染。
   - 分级启用：阈值固定 Z_ON=16/Z_FULL=17.5（2D 图标与 3D 的交接在基础上限处），240ms cubic-bezier(.4,0,.2,1)。
   - 光影：每车厢接触阴影；定向光方位读 map.getLight()；夜间(?t3dnight/JST18-06)车窗发光+头灯。
   - LOD：屏幕长<130px 切 stand-in.glb（__t3dNoLOD 可关），240ms 双根交叉淡化。
   - 交互：射线-定向盒 pickAt；app.js 点击/悬停 3D 优先不穿透；f>0.5 隐藏出入口层。
   - 校验：checkAxis（长轴 Z/车长±50%/单glb烘整列→回退2D）；__t3dAssert 硬断言；
     __t3dRec 异常逐帧记录；__t3dTable 逐节表（mode/dTan/adjDeg/yaw/pitch/roll）。
   ══════════════════════════════════════════════════════════════════════ */
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const FADE_MS = 240;
const LOD_FADE_MS = 400; /* LOD 交叉淡化比启用淡化更长:远景切换更柔(打磨轮) */
const MAX_INST = 30;
const EARTH_C = 40075016.686;
const LOD_PX = 130;
const LOD_PX_BACK = 165; /* 滞回:full→stand 用 LOD_PX,stand→full 需 >LOD_PX_BACK,防边界来回跳(打磨轮) */
/* 资产源:生产环境大资产在 jr-static Worker(主站 jr.suki.ing 不服务 /models/,
   相对路径会 404 → 编组元数据加载失败 → 全部实例判死、3D 永不出现);
   本地预览(file:/localhost)走同源相对路径。与 app.js M3D 的 BASE 口径一致。 */
const LOCAL = location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname);
const assetUrl = p => LOCAL ? p.replace(/^\//, '') : 'https://jr-static.suki.ing' + p;

let map = null, renderer = null, scene = null, camera = null, layerOn = false;
let disabled = false, inited = false;
let f = 0, fFrom = 0, fTo = 0, fT0 = 0;
let Z_ON = 16, Z_FULL = 17.5;
const Z_MAX = 18.5; /* 放宽硬顶:无论 base(?t3dmax 可抬至 18.5)多少,上限不超过 18.5 */
const Z_HYST = 0.4; /* 阈值滞回:进入=Z_ON,退出=Z_ON−Z_HYST(差≥0.3),防阈值附近缩放抖动使 f 来回归零闪断 */
let engaged = false; /* 滞回状态:已越入 Z_ON 后,需跌破 Z_ON−Z_HYST 才退出 */
/* 3D 开启时动态放宽缩放上限:baseMaxZoom=init 时的地图上限(不受放宽影响),
   模块激活(未 __t3dOff)即放宽 maxZoom=base+plus,关闭立即恢复 base。
   放宽不能等 f>0.5:Z_ON=16=基础上限,f>0 需 z>16,等 f 放宽则永远推不过去(死锁)。
   plus 默认 2.5(生产 z18.5):z17.5 淡入完成后仍有 1 档近观余量;
   window.__t3dZoomPlus 可覆盖 0–3。移动端不加载本模块→天然不放宽。 */
let baseMaxZoom = 0, zoomPlus = 2.5, appliedMax = -1;
const insts = new Map();
let frameFlat = [], frameSeq = 0, consumedSeq = -1;
let nightOn = false, hoverId = null, lastEntHide = false;
let Mloc = new THREE.Matrix4();
let curMpp = 1, curW = 1;
const stats = { fps: 0, n: 0, cand: 0, calls: 0, tris: 0, z: 0, f: 0, inst: 0, lod: 0, visN: 0, mpp: 1, lastT: 0, frame: 0 };

function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = t => ((ax * t + bx) * t + cx) * t;
  const dx = t => (3 * ax * t + 2 * bx) * t + cx;
  const sy = t => ((ay * t + by) * t + cy) * t;
  return x => {
    if (x <= 0) return 0; if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 5; i++) { const e = sx(t) - x; if (Math.abs(e) < 1e-4) break; const d = dx(t); if (Math.abs(d) < 1e-6) break; t -= e / d; }
    return sy(Math.min(1, Math.max(0, t)));
  };
}
const ease = cubicBezier(0.4, 0, 0.2, 1);
const animTo = (now, a, b, t0, ms) => a + (b - a) * ease(Math.min(1, (now - t0) / (ms || FADE_MS)));
const mercY = lat => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
const wrapPi = a => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };

const FOV_RAD = 0.6435011087932844;
function view() {
  const cv = map.getCanvas();
  const w = Math.max(1, cv.clientWidth), h = Math.max(1, cv.clientHeight);
  return { w, h, pitch: map.getPitch() * Math.PI / 180, bearing: map.getBearing() * Math.PI / 180, center: map.getCenter(), W: 512 * Math.pow(2, map.getZoom()), D: 0.5 / Math.tan(FOV_RAD / 2) * h };
}

let blobTex = null, blobMat = null;
function makeBlobTex(T) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const rg = g.createRadialGradient(32, 32, 4, 32, 32, 30);
  rg.addColorStop(0, 'rgba(0,0,0,0.55)'); rg.addColorStop(0.55, 'rgba(0,0,0,0.32)'); rg.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = rg; g.fillRect(0, 0, 64, 64);
  return new T.CanvasTexture(c);
}

const bakedSet = new Set(), axisBadSet = new Set();
const axisReport = {};
const axisChecked = new Set();

window.__T3D = {
  f: 0, zOn: Z_ON,
  push(trip, lng, lat, brg, path, color) { frameFlat.push(trip, lng, lat, brg, path, color); },
  begin() { frameFlat.length = 0; },
  end() { frameSeq++; },
  wake() { if (map && layerOn) map.triggerRepaint(); },
  modelOk(path) { return !bakedSet.has(path) && !axisBadSet.has(path); },
  pickAt(px, py) { return pickAt(px, py); },
  hover(id) {
    if (hoverId === id) return;
    hoverId = id;
    for (const [k, it] of insts) setHover(it, k === id);
    if (map) map.triggerRepaint();
  },
  /* EXP 让位门禁:2D 图标只在「该班次 3D 实例确已可见(淡入过半且 rootF 可见)」时才让位,
     杜绝「f 到阈值就藏 2D、3D 却因模型未就绪/渲染未起而空白」的设计缺陷 */
  trainVis(tid) { const it = insts.get(tid); return !!(it && it.rootF && it.rootF.visible && it.a > 0.5); },
  /* EXP 让位 v2:连续有效可见度 V∈[0,1] = min(1, a·f) × (rootF∥rootS 可见)。
     旧 trainVis 仅判 rootF:stand LOD(中低倍短编组)或双根交叉淡化时 rootF 不可见
     而 rootS 可见 → 判 false → 2D 图标全 alpha 压在车体上;淡入/淡出瞬态同理。
     app.js 图标 alpha ×= (1−V),与 3D 实际可见度严格互补 ——
     V 降(实例淡出/出屏/降级/模型未就绪)图标同步回补,任何时刻不出现「车没了」空窗;
     V 源自 240ms 缓动与阈值滞回,缩放推拉只产生平滑交叉淡化(天然防抖) */
  trainVisAmt(tid) {
    const it = insts.get(tid);
    if (!it) return 0;
    const rv = (it.rootF && it.rootF.visible) || (it.rootS && it.rootS.visible);
    return rv ? Math.min(1, it.a * f) : 0;
  },
};
function setHover(it, on) { if (it && it.mats) for (const m of it.mats) { if (m.emissive) m.emissive.setScalar(on ? 0.22 : 0); } }

export function init(mapObj) {
  window.__t3dInit = 'called';
  if (inited || disabled) return;
  map = mapObj;
  const mz = map.getMaxZoom();
  /* 阈值固定 16/17.5,不随 mz 相对化:2D→3D 交接点=基础上限,与放宽幅度解耦 */
  baseMaxZoom = mz;
  window.__T3D.zOn = Z_ON;
  window.__T3D.baseMaxZoom = mz;
  /* 模块激活即放宽上限(不等 f):否则 Z_ON=16=base,z>16 不可达 → 3D 永不淡入(死锁) */
  const plus0 = window.__t3dZoomPlus != null ? Math.max(0, Math.min(3, +window.__t3dZoomPlus || 0)) : zoomPlus;
  appliedMax = Math.min(Z_MAX, baseMaxZoom + (!window.__t3dOff ? plus0 : 0));
  try { map.setMaxZoom(appliedMax); } catch (e) {}
  /* 主题优先:浅色主题按白昼材质/光照,夜间也不进夜光(否则浅底图上黑块);深色主题保留昼夜时钟 */
  const themeLight = document.documentElement.getAttribute('data-theme') === 'light';
  nightOn = !themeLight && (nightByClock() || new URLSearchParams(location.search).has('t3dnight'));
  const add = () => {
    if (layerOn || !map.getLayer || map.getLayer('trains-3d-exp')) { layerOn = true; return; }
    try { map.addLayer(T3DLAYER); layerOn = true; } catch (e) { disabled = true; console.warn('[t3d] addLayer failed', e); }
  };
  setTimeout(add, 0);
  map.on('load', () => setTimeout(add, 0));
  map.on('style.load', () => { layerOn = false; setTimeout(add, 0); });
  inited = true;
}
function nightByClock() {
  try { const h = +new Date().toLocaleString('en-US', { timeZone: 'Asia/Tokyo', hour: 'numeric', hour12: false }); return h >= 18 || h < 6; } catch (e) { return false; }
}

const T3DLAYER = {
  id: 'trains-3d-exp',
  type: 'custom',
  renderingMode: '3d',
  onAdd(m, gl) {
    map = m;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: false, alpha: true });
      renderer.setPixelRatio(1);
      renderer.autoClear = false;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = nightOn ? 1.22 : 1.3;
      scene = new THREE.Scene();
      /* 环境反射兜底:glTF 多数车体 metallicFactor 缺省=1,无 envMap 时金属无漫反射 → 浅底图上呈黑块。
         与查看器同源:RoomEnvironment PMREM(每个 WebGL 上下文各自生成,不跨上下文)。 */
      try {
        const pm = new THREE.PMREMGenerator(renderer);
        scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
        scene.environmentIntensity = nightOn ? 0.4 : 1.0;
        pm.dispose();
      } catch (e) {}
      camera = new THREE.PerspectiveCamera();
      camera.matrixAutoUpdate = false;
      camera.matrixWorld.identity();
      camera.matrixWorldInverse.identity();
      let az = 210, alt = 60;
      try { const L = m.getLight && m.getLight(); if (L && L.position) { az = L.position[1]; alt = L.position[2]; } } catch (e) {}
      const ar = az * Math.PI / 180, alr = alt * Math.PI / 180;
      /* 夜间光比(打磨轮):深色底图上旧夜光(0.5/0.5/0.28)车体几乎不可读,
         提至 0.7/0.55/0.42 保轮廓可读,仍明显暗于白昼(1.75/0.6/0.42) */
      const key = new THREE.DirectionalLight(0xffffff, nightOn ? 0.7 : 1.75);
      key.position.set(Math.sin(ar) * Math.cos(alr), -Math.cos(ar) * Math.cos(alr), Math.sin(alr));
      scene.add(key);
      const hemi = new THREE.HemisphereLight(nightOn ? 0x2c3e57 : 0xdfe8ff, nightOn ? 0x10151d : 0x3a3f4a, nightOn ? 0.55 : 0.6);
      hemi.position.set(0, 0, 1);
      scene.add(hemi);
      scene.add(new THREE.AmbientLight(0xffffff, nightOn ? 0.42 : 0.42));
      blobTex = makeBlobTex(THREE);
      blobMat = new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false, opacity: 0 });
      renderer.setViewport(0, 0, m.getCanvas().width, m.getCanvas().height);
    } catch (e) { disabled = true; console.warn('[t3d] onAdd failed:', e && e.message || e); }
  },
  onRemove() {
    layerOn = false;
    if (renderer) { try { renderer.dispose(); } catch (e) {} renderer = null; }
    insts.clear();
  },
  render(gl, args) {
    if (disabled || !renderer) return;
    const D = args && args.defaultProjectionData;
    const matrix = D && (D.mainMatrix || D.fallbackMatrix);
    if (!matrix) return;
    gl.disable(gl.SCISSOR_TEST);
    gl.disable(gl.STENCIL_TEST);
    const now = performance.now();
    if (stats.lastT) { const dt = now - stats.lastT; if (dt > 0 && dt < 500) stats.fps = stats.fps ? stats.fps * 0.9 + (1000 / dt) * 0.1 : 1000 / dt; }
    stats.lastT = now;
    stats.frame++;
    const z = map.getZoom(); stats.z = z;
    /* 阈值滞回:进入用 Z_ON,退出用 Z_ON−Z_HYST;已越入后 ramp 基准下移到 Z_ON−Z_HYST,
       使阈值附近的缩放抖动(z 在 16 上下小幅往返)不把 f 拉回 0 造成闪断 */
    if (window.__t3dOff) engaged = false;
    else if (!engaged && z >= Z_ON) engaged = true;
    else if (engaged && z < Z_ON - Z_HYST) engaged = false;
    const zb = Z_ON - Z_HYST;
    const target = (engaged && !window.__t3dOff) ? Math.min(1, Math.max(0, (z - zb) / (Z_FULL - zb))) : 0;
    if (target !== fTo) { fFrom = f; fTo = target; fT0 = now; }
    f = animTo(now, fFrom, fTo, fT0);
    window.__T3D.f = f; stats.f = f;
    /* 动态缩放上限:模块激活(未 __t3dOff)即放宽,关闭/关停立即恢复 base。
       不含 f 条件:Z_ON=16=基础上限,等 f>0.5 再放宽则用户永远推不过 z16(死锁) */
    const plus = window.__t3dZoomPlus != null ? Math.max(0, Math.min(3, +window.__t3dZoomPlus || 0)) : zoomPlus;
    const wantMax = Math.min(Z_MAX, baseMaxZoom + (!window.__t3dOff ? plus : 0));
    if (appliedMax !== wantMax) {
      appliedMax = wantMax;
      try { map.setMaxZoom(wantMax); } catch (e) {}
      stats.maxZoom = wantMax;
    }
    const entHide = f > 0.5;
    if (entHide !== lastEntHide) {
      lastEntHide = entHide;
      try { if (map.getLayer('ent')) map.setLayoutProperty('ent', 'visibility', entHide ? 'none' : 'visible'); } catch (e) {}
    }
    if (frameSeq !== consumedSeq) { consume(now); consumedSeq = frameSeq; }
    let animating = Math.abs(f - fTo) > 0.002;
    animating = placeInstances(now) || animating;
    if (f <= 0.003 && insts.size === 0) return;
    const v = view();
    curW = v.W;
    curMpp = EARTH_C * Math.cos(v.center.lat * Math.PI / 180) / v.W;
    const s = 1 / (curMpp * v.W);
    const cwx = (v.center.lng + 180) / 360, cwy = mercY(v.center.lat);
    const T = new THREE.Matrix4().makeTranslation(cwx, cwy, 0).multiply(new THREE.Matrix4().makeScale(s, s, s));
    Mloc.fromArray(matrix).multiply(T);
    camera.projectionMatrix.copy(Mloc);
    camera.projectionMatrixInverse.copy(Mloc).invert();
    camera.updateMatrixWorld(true);
    renderer.setViewport(0, 0, map.getCanvas().width, map.getCanvas().height);
    renderer.resetState();
    renderer.render(scene, camera);
    stats.calls = renderer.info.render.calls;
    stats.tris = renderer.info.render.triangles;
    stats.n = insts.size;
    if (animating) map.triggerRepaint();
  },
};

const candTmp = [];
const pendingMeta = [];
/* ── 占位编组(对标 dokorail.jp 的见本车辆):模型加载失败/缺失/轴向不可校正时按节生成
   线路色盒车,高倍缩放永不整列不画。尺寸口径取 dokorail train-body 默认:车体宽 2.8m、
   高 3.65m、窗带 1.55–1.9m;车体长=节长−0.6m(其 Ve_gap 视觉缝)。占位车已是极简几何,
   不再走 stand-in 加载。 ── */
const PH_BODY = 0xd4d6d9, PH_ROOF = 0xa2a6ab, PH_WIN = 0x263238;
function synthMeta() {
  const cars = []; let z = 0;
  for (let i = 0; i < 4; i++) { const L = 20; cars.push({ model: null, len: L, d: z }); z += L + 0.03; }
  return { cars, length: z - 0.03, n: 4, synth: true };
}
function placeholderTmpl(meta, colorHex) {
  const m = (meta && meta.cars && meta.cars.length) ? meta : synthMeta();
  const group = new THREE.Group();
  const bodyMat = new THREE.MeshStandardMaterial({ color: PH_BODY, roughness: 0.55, metalness: 0 });
  const roofMat = new THREE.MeshStandardMaterial({ color: PH_ROOF, roughness: 0.7, metalness: 0 });
  const winMat = new THREE.MeshStandardMaterial({ color: PH_WIN, roughness: 0.35, metalness: 0 });
  let bandCol = 0x888888;
  try { if (colorHex) bandCol = new THREE.Color(colorHex); } catch (e) {}
  const bandMat = new THREE.MeshStandardMaterial({ color: bandCol, roughness: 0.5, metalness: 0 });
  const carNodes = [];
  for (let i = 0; i < m.cars.length; i++) {
    const L = Math.max(6, (m.cars[i].len || 20) - 0.6);
    const wrap = new THREE.Group();
    wrap.userData.m3dCar = 1;
    const body = new THREE.Mesh(new THREE.BoxGeometry(2.8, 2.9, L), bodyMat);
    body.position.y = 0.5 + 1.45;
    const band = new THREE.Mesh(new THREE.BoxGeometry(2.86, 0.35, L * 0.995), bandMat);
    band.position.y = 1.375;
    const win = new THREE.Mesh(new THREE.BoxGeometry(2.84, 0.35, L * 0.99), winMat);
    win.position.y = 1.725;
    const roof = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.25, L * 0.98), roofMat);
    roof.position.y = 3.525;
    wrap.add(body, band, win, roof);
    wrap.traverse(o => { if (o.isMesh) o.frustumCulled = false; });
    group.add(wrap);
    carNodes.push({ node: wrap, d: m.cars[i].d || 0 });
  }
  return { group, cars: carNodes, length: m.length || m.cars.length * 20, path: 'placeholder', placeholder: true };
}
function consume(now) {
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  candTmp.length = 0;
  for (let i = 0; i < frameFlat.length; i += 6) {
    const trip = frameFlat[i], lng = frameFlat[i + 1], lat = frameFlat[i + 2], brg = frameFlat[i + 3], path = frameFlat[i + 4], color = frameFlat[i + 5];
    const wx = (lng + 180) / 360 * W, wy = mercY(lat) * W;
    const dx = wx - cwx, dy = wy - cwy;
    candTmp.push({ trip, lng, lat, brg, path, color, d2: dx * dx + dy * dy });
  }
  frameFlat.length = 0;
  stats.cand = candTmp.length;
  if (candTmp.length > MAX_INST) { candTmp.sort((a, b) => a.d2 - b.d2); candTmp.length = MAX_INST; }
  const seen = new Set();
  for (const cd of candTmp) {
    seen.add(cd.trip.t);
    let it = insts.get(cd.trip.t);
    if (!it) {
      it = { trip: cd.trip, path: cd.path, rootF: null, rootS: null, tmpl: null, stand: null, carsMeta: null,
        a: 0, aFrom: 0, aTo: 0, aT0: now, mats: [], req: null, reqS: null, pending: false, lod: 'full', brgSm: cd.brg, roll: 0 };
      insts.set(cd.trip.t, it);
    }
    it.lng = cd.lng; it.lat = cd.lat; it.brg = cd.brg; it.seenFr = stats.frame; it.lastPush = now;
    if (cd.color) it.phColor = cd.color;
    if (!it.req) {
      it.pending = true;
      /* 占位回退:真模板不可用(加载失败/缺失/轴向不可校正)时用线路色盒车顶上,
         3D 层永不整列不画;让位门禁照常生效(占位车真实渲染才藏 2D) */
      const adopt = (tmpl, meta, isPh) => {
        it.tmpl = tmpl; it.carsMeta = meta; it.isPlaceholder = !!isPh;
        it.lenM = tmpl.length;   /* 必须先于 buildRoot：gap/carD 依赖 lenM（曾因此 NaN 致全列只画头车） */
        it.rootF = buildRoot(tmpl, it);
        it.aFrom = 0; it.aTo = 1; it.aT0 = performance.now();
        if (isPh) stats.ph = (stats.ph || 0) + 1;
      };
      it.req = Promise.all([window.M3D && window.M3D.ensure(it.path), consistMeta(it.path)]).then(([tmpl, meta]) => {
        it.pending = false;
        if (it.dead) return;
        const useMeta = meta || synthMeta();
        if (tmpl && window.__T3D.modelOk(it.path)) {
          checkAxis(it.path, tmpl, useMeta);
          if (window.__T3D.modelOk(it.path)) { adopt(tmpl, useMeta, false); return; }
        }
        adopt(placeholderTmpl(useMeta, it.phColor), useMeta, true);
      }).catch(() => {
        it.pending = false;
        if (it.dead) return;
        const useMeta = synthMeta();
        adopt(placeholderTmpl(useMeta, it.phColor), useMeta, true);
      });
    }
  }
  for (const [k, it] of insts) {
    if (seen.has(k)) continue;
    /* 暂停/静态时 updateTrains 仅 2Hz 补推送:两次推送之间的 consume 批次为空,
       若立即淡出/判死会造成 2Hz 振荡(整列闪烁+pending 模型反复重载)。1.5s 内未推送才淡出。 */
    if (now - (it.lastPush || 0) < 1500) continue;
    if (it.pending) { it.pending = false; it.dead = true; }
    else if (it.aTo !== 0) { it.aFrom = it.a; it.aTo = 0; it.aT0 = now; }
  }
  for (const [tid, M2, kmh] of pendingMeta) { const it = insts.get(tid); if (it) { it.M2 = M2; it.kmh = kmh; } }
  pendingMeta.length = 0;
}

const metaCache = new Map();
function consistMeta(path) {
  if (metaCache.has(path)) return metaCache.get(path);
  const base = path.slice(0, path.lastIndexOf('/') + 1);
  const p = fetch(assetUrl(base + 'consist.json')).then(r => r.ok ? r.json() : null).then(jj => {
    if (!jj) return null;
    const n = (jj.cars || []).length || 1;
    const lenOf = i => (i === 0 || i === n - 1) ? (jj.car_length_m || 20) : (jj.middle_car_length_m || jj.car_length_m || 20);
    let z = 0, prevR = 0; const cars = [];
    for (let i = 0; i < n; i++) {
      const L = lenOf(i);
      const cf = L / 2 + 0.05, cr = L / 2 + 0.05;
      if (i > 0) z += prevR + 0.03 + cf;
      cars.push({ model: (jj.cars[i] || {}).model, len: L, d: z });
      prevR = cr;
    }
    const total = z + prevR + (cars[0] ? cars[0].len : 0);
    return { cars, length: total, n };
  }).catch(() => null);
  metaCache.set(path, p);
  return p;
}

function buildRoot(tmpl, it) {
  const root = tmpl.group.clone(true);
  it.mats = [];
  const shadows = [];
  root.traverse(o => {
    if (o.isMesh) {
      o.frustumCulled = false;
      const m = o.material.clone();
      m.transparent = true; m.opacity = 0;
      fixTrainMat(m);
      if (nightOn && m.roughnessMap) applyNight(m);
      o.material = m; it.mats.push(m);
    }
  });
  root.traverse(o => { if (o.userData && o.userData.nightOnly) o.visible = nightOn; });
  it.blobMat = blobMat.clone();
  const carWraps = [];
  root.traverse(o => { if (o.userData && o.userData.m3dCar) carWraps.push(o); });
  const meta0 = it.carsMeta;
  if (meta0) {
    for (let i = 0; i < carWraps.length && i < meta0.cars.length; i++) {
      const pl = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), it.blobMat);
      pl.rotation.x = -Math.PI / 2;
      pl.position.y = 0.06;
      pl.scale.set(4.6, meta0.cars[i].len + 2.2, 1);
      pl.renderOrder = -1;
      carWraps[i].add(pl); shadows.push(pl);
    }
    const sumL = meta0.cars.reduce((a, c) => a + c.len, 0);
    /* gap 允许为负且放宽到 ±5m:consist.json 单车名义长之和与模板连挂长的标定差
       (含车钩/耦合距)可达 ±2.5m/节;钳制过紧会破坏 spread≡lenM 恒等(12506 1.24% 根因)。
       ±5 仅作坏数据 sanity 界。 */
    it.gap = meta0.n > 1 ? Math.min(5, Math.max(-5, (it.lenM - sumL) / (meta0.n - 1))) : 0;
    it.carD = []; let acc = 0;
    for (let i = 0; i < meta0.n; i++) { acc += meta0.cars[i].len / 2; it.carD.push(acc); acc += meta0.cars[i].len / 2 + it.gap; }
    it.totalLen = sumL + it.gap * (meta0.n - 1);
  }
  it.shadows = shadows;
  it.carNodesF = carWraps;
  scene.add(root);
  return root;
}
function checkAxis(path, tmpl, meta) {
  if (axisChecked.has(path)) return;
  axisChecked.add(path);
  if (meta.n === 1 && tmpl.length > 35) { bakedSet.add(path); axisReport[path] = { reason: 'single-car-glb-bakes-whole-consist', len: +tmpl.length.toFixed(1) }; return; }
  const bad = [];
  const b2 = new THREE.Box3();
  const sizeOf = nd => {
    const box = new THREE.Box3().makeEmpty();
    nd.updateMatrixWorld(true);
    nd.traverse(o => {
      if (!o.isMesh || o.visible === false) return;
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      box.union(b2.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld));
    });
    return box.getSize(new THREE.Vector3());
  };
  for (let i = 0; i < tmpl.cars.length && i < meta.cars.length; i++) {
    const sz = sizeOf(tmpl.cars[i].node);
    const L = meta.cars[i].len;
    if (!(sz.z >= sz.x * 0.999 && sz.z >= sz.y * 0.999) || Math.abs(sz.z - L) / L > 0.5) bad.push({ i, sz: [+sz.x.toFixed(1), +sz.y.toFixed(1), +sz.z.toFixed(1)], L: +L.toFixed(1) });
  }
  if (bad.length) { axisBadSet.add(path); axisReport[path] = { reason: 'local-axis-mismatch', bad }; }
}
function fixTrainMat(m) {
  /* 涂装车身纠正:glTF 未写 metallicFactor 时缺省=1,带 albedo 贴图的漆面被当作纯金属,
     无 envMap 时漫反射=0 → 浅色主题黑块。保留真金属(无贴图/低粗糙度),漆面压到 0.12。 */
  if (m && m.isMeshStandardMaterial && m.map && m.metalness > 0.6 && m.roughness >= 0.35) m.metalness = 0.12;
}
function applyNight(mat) {
  const uni = { nightAmt: { value: 1.0 } };
  mat.nightUni = uni;
  const orig = mat.onBeforeCompile;
  mat.customProgramCacheKey = () => (mat.__ck || (mat.__ck = 't3d-night-' + Math.random().toString(36).slice(2, 7)));
  mat.onBeforeCompile = sh => {
    if (orig) orig(sh);
    Object.assign(sh.uniforms, uni);
    sh.fragmentShader = sh.fragmentShader
      .replace('void main() {', 'uniform float nightAmt;\nvoid main() {')
      .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\n\ttotalEmissiveRadiance += vec3(1.0,0.87,0.62) * 3.2 * texture2D( roughnessMap, vMapUv ).a * nightAmt;');
  };
  mat.needsUpdate = true;
}

const standCache = new Map();
let standOrder = [];
function standTmpl(path, meta) {
  if (standCache.has(path)) return standCache.get(path);
  const base = path.slice(0, path.lastIndexOf('/') + 1);
  const p = (async () => {
    const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
    const loader = new GLTFLoader();
    const group = new THREE.Group(); const nodes = [];
    for (let i = 0; i < meta.cars.length; i++) {
      const cm = meta.cars[i];
      const standPath = cm.model ? cm.model.replace(/\.glb$/, '.stand-in.glb') : null;
      let g = null;
      if (standPath) { try { g = (await loader.loadAsync(assetUrl(base + standPath))).scene; } catch (e) { g = null; } }
      if (!g && cm.model) { try { g = (await loader.loadAsync(assetUrl(base + cm.model))).scene; } catch (e) { g = null; } }
      if (!g) continue;
      g.updateMatrixWorld(true);
      let box = new THREE.Box3().setFromObject(g), sz = box.getSize(new THREE.Vector3());
      if (sz.x > sz.z) { g.rotation.y += Math.PI / 2; g.updateMatrixWorld(true); box = new THREE.Box3().setFromObject(g); sz = box.getSize(new THREE.Vector3()); }
      const sc = sz.z > 1e-6 ? cm.len / sz.z : 1;
      g.scale.multiplyScalar(sc); g.updateMatrixWorld(true);
      box = new THREE.Box3().setFromObject(g);
      const c = box.getCenter(new THREE.Vector3());
      g.position.sub(new THREE.Vector3(c.x, box.min.y, c.z));
      const wrap = new THREE.Group(); wrap.add(g);
      wrap.userData.m3dCar = 1;
      wrap.traverse(o => { if (o.isMesh) o.frustumCulled = false; });
      group.add(wrap); nodes.push({ node: wrap, d: cm.d });
    }
    return { group, nodes };
  })().catch(() => null);
  standCache.set(path, p); standOrder.push(path);
  while (standOrder.length > 12) { const ev = standOrder.shift(); if (ev !== path) standCache.delete(ev); }
  return p;
}

const _v1 = new THREE.Vector3();
const AX_Z = new THREE.Vector3(0, 0, 1), AX_X = new THREE.Vector3(1, 0, 0);
const QX90 = new THREE.Quaternion().setFromAxisAngle(AX_X, Math.PI / 2);
const _q1 = new THREE.Quaternion(), _q3 = new THREE.Quaternion();
const _qq = new THREE.Quaternion(), _fwd = new THREE.Vector3(), _rgt = new THREE.Vector3();
function setCarQuat(node, brg, roll) {
  _q1.setFromAxisAngle(AX_Z, brg + Math.PI);
  _q3.setFromAxisAngle(AX_Z, roll || 0);
  node.quaternion.copy(_q1).multiply(QX90).multiply(_q3);
}
function placeInstances(now) {
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  const mpp = EARTH_C * Math.cos(c.lat * Math.PI / 180) / W;
  stats.mpp = mpp; stats.visN = 0; stats.lod = 0;
  let animating = false;
  const rel = (lng, lat, out) => { out[0] = ((lng + 180) / 360 * W - cwx) * mpp; out[1] = (mercY(lat) * W - cwy) * mpp; return out; };
  const tmp = [0, 0];
  for (const [k, it] of insts) {
    if (it.dead) { removeInst(k); continue; }
    if (it.pending || !it.rootF) continue;
    it.a = animTo(now, it.aFrom, it.aTo, it.aT0);
    if (Math.abs(it.a - it.aTo) > 0.002) animating = true;
    if (it.aTo === 0 && it.a <= 0.004) { removeInst(k); continue; }
    const vis = Math.min(1, it.a * f);
    if (it.blobMat) it.blobMat.opacity = 0.68 * vis;
    const pxLen = (it.lenM || 100) / mpp;
    /* 滞回:full→stand 阈 130px,stand→full 需 >165px —— 边界缩放不来回跳变(打磨轮) */
    const wantLod = window.__t3dNoLOD ? 'full'
      : (it.lod === 'stand' ? (pxLen > LOD_PX_BACK ? 'full' : 'stand')
                            : (pxLen < LOD_PX ? 'stand' : 'full'));
    if (wantLod !== it.lod) {
      it.lod = wantLod;
      if (wantLod === 'stand' && !it.stand && it.carsMeta && !it.reqS && !it.isPlaceholder) {
        it.reqS = standTmpl(it.path, it.carsMeta).then(st => {
          if (!st || it.dead) return;
          it.stand = st;
          it.rootS = st.group.clone(true);
          it.matsS = []; it.carNodesS = [];
          it.rootS.traverse(o => {
            if (o.isMesh) { o.frustumCulled = false; const m = o.material.clone(); m.transparent = true; m.opacity = 0; fixTrainMat(m); o.material = m; it.matsS.push(m); }
            if (o.userData && o.userData.m3dCar) it.carNodesS.push(o);
          });
          scene.add(it.rootS);
        });
      }
    }
    const wantStand = it.lod === 'stand' && !!it.rootS;
    if (it.lodTo === undefined) { it.lodT = 0; it.lodFrom = 0; it.lodTo = 0; it.lodT0 = now; }
    if ((wantStand ? 1 : 0) !== it.lodTo) { it.lodFrom = it.lodT; it.lodTo = wantStand ? 1 : 0; it.lodT0 = now; animating = true; }
    it.lodT = animTo(now, it.lodFrom, it.lodTo, it.lodT0, LOD_FADE_MS);
    if (Math.abs(it.lodT - it.lodTo) > 0.002) animating = true;
    if (it.lodT > 0.5) stats.lod++;
    const oF = vis * (1 - it.lodT), oS = vis * it.lodT;
    for (const m of it.mats) { m.opacity = oF; m.transparent = oF < 0.999; m.depthWrite = oF >= 0.02; }
    if (it.matsS) for (const m of it.matsS) { m.opacity = oS; m.transparent = oS < 0.999; m.depthWrite = oS >= 0.02; }
    it.rootF.visible = oF > 0.02;
    if (it.rootS) it.rootS.visible = oS > 0.02;
    if (!it.rootF.visible && !(it.rootS && it.rootS.visible)) continue;
    stats.visN++;
    const head = rel(it.lng, it.lat, tmp);
    const meta = it.carsMeta;
    const sam = (window.__t3dArc && it.M2 != null) ? window.__t3dArc(it.trip, it.M2, it.lng, it.lat, it.brg) : null;
    /* EXP 头车锚改取 __t3dArc 投影点:消除推送点与轨道折线间 ≈2.1m 系统偏差(复线左偏/解算线偏移)。
       仅投影误差 <30m 时采纳:错腿/重复对象等大误差情形保持推送点,防 3D/2D 撕裂。 */
    if (sam && sam.proj && (sam.projErrM || 0) < 30) { const hp = rel(sam.proj[0], sam.proj[1], [0, 0]); head[0] = hp[0]; head[1] = hp[1]; }
    else if (sam && sam.pushClamp) {
      /* EXP 注册偏移边界(推進点が腿端点外 ≤600m):头车锚取外推弧长点 at(0),
         与尾车采样同源,消除「头在推进点、尾车从腿端点起算」的数百米间距撕裂 */
      const hp0 = sam.at(0);
      if (hp0 && isFinite(hp0[0]) && isFinite(hp0[1])) { const hp = rel(hp0[0], hp0[1], [0, 0]); head[0] = hp[0]; head[1] = hp[1]; }
    }
    it.carDiag = [];
    const tfs = [];
    if (sam && meta && it.carNodesF && it.carNodesF.length && it.carD) {
      let prevH = null;
      let drift = 0; /* 逐节间距累积漂移(残桩折叠/接缝错位守卫用) */
      let prevPGap = 0; /* 上一节采样携带的腿缝断口累计(米),期望间距=step+断口增量 */
      let prevRepos = false; /* 上一节是否被漂移守卫重铺(重铺后本节信任弧长采样,防 chain 连锁) */
      const p0 = sam.at(0);
      /* EXP 整列单源回退基准:头锚 + 头部切线(轨道来源)。守卫触发/无采样/非有限 →
         沿此线共线重铺(间距恒定、横向不跨线),替代旧版「沿前节航向直铺」
         (弯道上逐节累积横向漂移,可把车体推上邻轨 = 用户所见"裂开吸附不同轨道"的来源之一) */
      const ssB = (p0 && isFinite(p0[2])) ? p0[2] : it.brg;
      it.consDx = 0; it.consDy = 0; it.consDh = 0;
      it.tanAmb = p0 ? wrapPi(p0[2] - it.brg) * 180 / Math.PI : 0;
      it.projErrM = sam.projErrM || 0;
      it._samLeg = sam.leg; it._samOrient = sam.orient; it._samSHead = sam.sHead;
      it._samRef = sam; /* 渲染时 sam 快照:走廊断言用同一来源,避免事后重算在腿边界翻转产生假阳性 */
      const nCars = Math.max(it.carNodesF.length, it.carD.length);
      /* carD 以列车前端为原点;头车节点锚在推送点(=头车中心,与 2D 同源)。
         后续车厢回退距离须减去 carD[0](半车头长),否则头车→第2节多出半车长,
         超出 chain 守卫容差被拉直(弯道逐节转折失效的表观根因之一)。 */
      const d0 = (it.carD && it.carD[0]) || 0;
      /* EXP 朝向同源修(头车斜/停站垂直两缺陷):头车与后续车厢统一用「弧长±转向架弦」
         采样定向(对标 dokorail placeTrain 全车统一口径),头车不再单独吃推送 bearing ——
         咽喉处推送 bearing 与车体链可能差一条腿(实测 head leg19/-160.1° vs 车体 leg18/-163.7°);
         采样退化时逐节回退「上一帧朝向」,再退推送 bearing,杜绝零向量/默认朝向兜底。 */
      const win0 = Math.max(0.5, ((meta.cars[0] ? meta.cars[0].len : 20) / 2 - 2.2)) / 1000;
      const pHRaw = sam.at(0, win0);
      const pH = (pHRaw && isFinite(pHRaw[0]) && isFinite(pHRaw[1]) && isFinite(pHRaw[2])) ? pHRaw : null;
      for (let i = 0; i < nCars; i++) {
        /* EXP 友商式转向架弦:朝向取 ±(carLen/2−2.2)m 窗弦(替代固定 ±15m),过渡曲线上邻节角更自洽 */
        const winI = i === 0 ? win0 : Math.max(0.5, ((meta.cars[i] ? meta.cars[i].len : 20) / 2 - 2.2)) / 1000;
        const pRaw = i === 0 ? pH : sam.at(it.carD[i] - d0, winI);
        const p = (pRaw && isFinite(pRaw[0]) && isFinite(pRaw[1]) && isFinite(pRaw[2])) ? pRaw : null;
        let cb, px, py, mode = 'arc';
        let repos = false; /* 本节是否被漂移守卫重铺(供下一节防 chain 连锁) */
        if (i === 0 && p) { cb = p[2]; const r2 = rel(p[0], p[1], [0, 0]); px = r2[0]; py = r2[1]; mode = 'head'; }
        else if (i === 0) { cb = (it.prevCbs && isFinite(it.prevCbs[0])) ? it.prevCbs[0] : it.brg; px = head[0]; py = head[1]; mode = 'head-fb'; }
        else if (p) { cb = p[2]; const r2 = rel(p[0], p[1], [0, 0]); px = r2[0]; py = r2[1]; }
        else { cb = (it.prevCbs && isFinite(it.prevCbs[i])) ? it.prevCbs[i] : ssB; mode = 'rigid'; const dd = (it.carD[i] - d0) || i * 25; px = head[0] - Math.sin(cb) * dd; py = head[1] + Math.cos(cb) * dd; }
        if (!isFinite(px) || !isFinite(py) || !isFinite(cb)) { px = head[0] - Math.sin(ssB) * ((it.carD[i] - d0) || 0); py = head[1] + Math.cos(ssB) * ((it.carD[i] - d0) || 0); cb = ssB; mode = 'rigid'; }
        if (i > 0 && tfs.length) {
          const prev = tfs[i - 1];
          const step = ((meta.cars[i] ? meta.cars[i].len : 20) + (meta.cars[i - 1] ? meta.cars[i - 1].len : 20)) / 2 + (it.gap || 0.2);
          const dd2 = Math.hypot(px - prev.px, py - prev.py);
          /* 期望间距含腿缝断口增量:数据断口(站喉 snap/平行轨变体)不再误触发 chain 直铺 */
          const pGap = (p && p[5]) || 0;
          const expct = step + (pGap - prevPGap);
          if (prevRepos) {
            /* EXP 防级联:前节是单源回退重铺位(chain/spike),其位置非弧长来源 ——
               本节恢复信任弧长采样、清零累积漂移,不与重铺位比间距,
               否则一节回退会把整列后续都拽上直线(咽喉镜像边界实测级联 5 节) */
            drift = 0;
          } else if (!isFinite(dd2) || dd2 > expct * 3 + 8 || dd2 < expct * 0.25) {
            /* EXP 诊断(chain 守卫触发取证):记录 carD/at() 原始返回/dd2 与容差带/腿状态,
               用于区分「腿接缝端点错配」与「sanitize 折叠」。上限 400 行防膨胀。 */
            const CL = window.__t3dChainLog || (window.__t3dChainLog = []);
            if (CL.length < 400) CL.push({ fr: stats.frame, tid: it.trip.t, i,
              d: +((it.carD[i] - d0) || 0).toFixed(1), d0: +d0.toFixed(1),
              pRaw: pRaw ? [+pRaw[0].toFixed(6), +pRaw[1].toFixed(6), +(pRaw[2] * 180 / Math.PI).toFixed(1), pRaw[3], +(pRaw[4] || 0).toFixed(2)] : null,
              dd2: isFinite(dd2) ? +dd2.toFixed(2) : null, step: +step.toFixed(2), expct: +expct.toFixed(2),
              lo: +(step * 0.35).toFixed(2), hi: +(step + 8).toFixed(2),
              px: +px.toFixed(2), py: +py.toFixed(2), prevPx: +prev.px.toFixed(2), prevPy: +prev.py.toFixed(2),
              prevMode: prev.mode, leg: it._samLeg, orient: it._samOrient,
              sHead: it._samSHead != null ? +it._samSHead.toFixed(4) : null });
            /* EXP 单源回退:沿头锚+头切线共线重铺(不再沿前节航向直铺 → 不再横向漂上邻轨) */
            { const D = (it.carD[i] - d0) || 0; px = head[0] - Math.sin(ssB) * D; py = head[1] + Math.cos(ssB) * D; cb = ssB; mode = 'chain'; drift = 0; }
          } else {
            /* 累积漂移守卫:残桩折叠/腿接缝错位使逐节间距偏离 step,单节 <0.5m 难察、
               累积 >1m 破坏总长恒等 → 单源共线重铺并标 spike。
               弯道弦损补偿:真实弯道上弦长 dd2 恒小于弧长步长 expct,逐节差≈step·θ²/24
               (θ=本节转向角);急弯(新幹線进站/海岸線/総武喉)单节弦损可达 0.4m,不补偿会
               误触发重铺把车从弯道上拉直(实测偏出 5–11m)。仅对负漂移(车距偏短)补偿。 */
            let dinc = dd2 - expct;
            if (dinc < 0 && prevH !== null) {
              const tn = Math.abs(wrapPi(cb - prevH));
              if (tn < 1.0) dinc = Math.min(0, dinc + step * tn * tn / 24);
            }
            drift += dinc;
            if (drift < -1.0) {
              /* 负漂移=车距偏短=弯道弦损(弧长采样已把车放在弯道上):不重铺拉直,
                 仅清零累计、信任弧长位;否则急弯车被拉直出曲线(实测偏 5–11m) */
              drift = 0;
            } else if (drift > 2.5) {
              /* 正漂移=车距偏长。均匀小幅偏长(投影/弦长微差,~0.1m/节)累积到 1m 即重铺
                 会把好车拉直偏出 5–6m,比重铺前更糟;阈值放宽到 2.5m 只拦真实断节/错缝
                 (腿缝断口已由投影接入经 gapM 计入 expct,不再灌入漂移) */
              const D = (it.carD[i] - d0) || 0; px = head[0] - Math.sin(ssB) * D; py = head[1] + Math.cos(ssB) * D;
              cb = ssB; mode = 'spike'; stats.spike = (stats.spike || 0) + 1; drift = 0; repos = true;
            }
          }
          prevPGap = pGap;
        }
        /* 尖峰守卫:弧长采样切线与前节航向差 >90° = 几何尖峰(站喉短桩/错向残段),
           不是真实弯道 → 沿用前节航向,标 spike 单独计数(不冒充 arc,不混入 chain) */
        if (mode === 'arc' && prevH !== null && Math.abs(wrapPi(cb - prevH)) > Math.PI / 2) { cb = prevH; mode = 'spike'; stats.spike = (stats.spike || 0) + 1; }
        const adjRaw = prevH === null ? 0 : wrapPi(cb - prevH);
        let cbA = cb;
        if (prevH !== null && Math.abs(adjRaw) > 0.35) { cbA = prevH + Math.sign(adjRaw) * 0.35; stats.clamp = (stats.clamp || 0) + 1; }
        const adjDeg = +(adjRaw * 180 / Math.PI).toFixed(3);
        prevH = cbA;
        tfs.push({ px, py, cb: cbA, adjDeg, p, mode });
        prevRepos = repos;
      }
      for (let i = 0; i < tfs.length; i++) {
        const tf = tfs[i];
        const rollT = Math.max(-0.05, Math.min(0.05, tf.adjDeg * Math.PI / 180 * 1.2));
        tf.roll = ((it.rolls || (it.rolls = []))[i] || 0) + (rollT - ((it.rolls || (it.rolls = []))[i] || 0)) * 0.35;
        it.rolls[i] = tf.roll;
      }
      const applyTo = (nset, on) => {
        if (!on || !nset) return;
        for (let i = 0; i < nset.length && i < tfs.length; i++) {
          const ni = nset[i];
          const node = ni && ni.node !== undefined ? ni.node : ni;
          if (!node) continue;
          node.position.set(tfs[i].px, tfs[i].py, 0);
          setCarQuat(node, tfs[i].cb, tfs[i].roll);
        }
      };
      applyTo(it.carNodesF, it.rootF.visible);
      applyTo(it.carNodesS, it.rootS && it.rootS.visible);
      for (let i = 0; i < tfs.length; i++) {
        const tf = tfs[i];
        const node = it.carNodesF && it.carNodesF[i];
        if (node) {
          node.getWorldQuaternion(_qq);
          _fwd.set(0, 0, -1).applyQuaternion(_qq);
          _rgt.set(1, 0, 0).applyQuaternion(_qq);
          tf.pitch = Math.asin(Math.max(-1, Math.min(1, _fwd.z)));
          tf.rollQ = Math.asin(Math.max(-1, Math.min(1, _rgt.z)));
        } else { tf.pitch = 0; tf.rollQ = tf.roll; }
        if (tf.p && tf.p[3] === -2) tf.mode = 'chain-oob';
        else if (tf.p && tf.p[3] === -1) tf.mode = 'rigid'; /* at() 内兜底直线外推,不算弧长证据 */
        const tg = (tf.mode === 'arc' && tf.p) ? tf.p[2] : tf.cb;
        const rlng = ((tf.px / mpp + cwx) / W) * 360 - 180;
        const rmy = (tf.py / mpp + cwy) / W;
        const rlat = (2 * Math.atan(Math.exp(Math.PI * (1 - 2 * rmy))) - Math.PI / 2) * 180 / Math.PI;
        it.carDiag.push({ i, s: +((it.carD && it.carD[i]) || 0).toFixed(1), mode: tf.mode, lng: +rlng.toFixed(6), lat: +rlat.toFixed(6), head: +(tf.cb * 180 / Math.PI).toFixed(2), dTan: +(wrapPi(tf.cb - tg) * 180 / Math.PI).toFixed(3), adjDeg: tf.adjDeg, yaw: +(tf.cb * 180 / Math.PI).toFixed(2), pitch: +((tf.pitch || 0) * 180 / Math.PI).toFixed(3), roll: +((tf.rollQ || 0) * 180 / Math.PI).toFixed(3) });
      }
    } else {
      /* sam 缺失(停站投影失败等):整列沿「上一帧头车切线」共线重铺,逐节朝向优先上一帧
         (停站前最后有效切线),杜绝停站瞬间整列吃推送 bearing 退化值(垂直缺陷放大点) */
      const cb0 = (it.prevCbs && isFinite(it.prevCbs[0])) ? it.prevCbs[0] : it.brg;
      for (let i = 0; i < (it.carD || []).length; i++) {
        const dd = it.carD[i] - ((it.carD && it.carD[0]) || 0);
        const cb = (it.prevCbs && isFinite(it.prevCbs[i])) ? it.prevCbs[i] : cb0;
        tfs.push({ px: head[0] - Math.sin(cb0) * dd, py: head[1] + Math.cos(cb0) * dd, cb, adjDeg: 0, p: null, mode: 'rigid', roll: 0 });
      }
      const applyTo = (nset, on) => {
        if (!on || !nset) return;
        for (let i = 0; i < nset.length && i < tfs.length; i++) {
          const ni = nset[i]; const node = ni && ni.node !== undefined ? ni.node : ni;
          if (!node) continue;
          node.position.set(tfs[i].px, tfs[i].py, 0); setCarQuat(node, tfs[i].cb, 0);
        }
      };
      applyTo(it.carNodesF, it.rootF.visible);
      applyTo(it.carNodesS, it.rootS && it.rootS.visible);
      it.carDiag = tfs.map((tf, i) => ({ i, s: +((it.carD && it.carD[i]) || 0).toFixed(1), mode: 'rigid', lng: +it.lng.toFixed(6), lat: +it.lat.toFixed(6), head: +(tf.cb * 180 / Math.PI).toFixed(2), dTan: 0, adjDeg: 0, yaw: +(tf.cb * 180 / Math.PI).toFixed(2), pitch: 0, roll: 0 }));
    }
    it.prevCbs = tfs.map(tf => tf.cb); /* 朝向同源修:逐节本帧朝向留存,供退化帧回退 */
    if (window.__t3dRecOn && (it.carDiag.length === 0 || (it.carNodesF || []).length !== (it.carsMeta ? it.carsMeta.n : -1))) {
      const rec = window.__t3dRec || (window.__t3dRec = []);
      if (rec.length < 240 && (!it._recT || now - it._recT > 500)) {
        it._recT = now;
        let cacheHas = null;
        try { cacheHas = window.M3D.__dbg().cache.indexOf(it.path) >= 0; } catch (e) {}
        rec.push({ fr: stats.frame, tid: it.trip.t, nF: (it.carNodesF || []).length, nCarD: (it.carD || []).length, metaN: it.carsMeta && it.carsMeta.n, diag: it.carDiag.length, lod: it.lod, lodT: +(it.lodT || 0).toFixed(2), a: +it.a.toFixed(2), pend: !!it.pending, visF: !!(it.rootF && it.rootF.visible), cacheHas, seenAge: stats.frame - (it.seenFr || 0) });
      }
    }
    /* EXP 走廊断言自动模式:开启时每 10 帧逐列普查,违例(离自身走廊/更贴近别轨/间距超差)记 __t3dCorrLog */
    if (window.__t3dCorridorOn && it.M2 != null && it.carDiag.length && stats.frame % 10 === 0) {
      try {
        const r = corrOfInst(it, 3.5, 1.0);
        if (r && r.viol.length) {
          const CLG = window.__t3dCorrLog || (window.__t3dCorrLog = []);
          if (CLG.length < 300) CLG.push({ fr: stats.frame, tid: it.trip.t, line: r.line, chainLegs: r.chainLegs, viol: r.viol });
        }
      } catch (e) {}
    }
  }
  return animating;
}
function removeInst(k) {
  const it = insts.get(k);
  if (!it) return;
  for (const r of [it.rootF, it.rootS]) if (r) scene.remove(r);
  for (const m of (it.mats || [])) m.dispose();
  for (const m of (it.matsS || [])) m.dispose();
  if (it.blobMat) it.blobMat.dispose();
  insts.delete(k);
}

function pickAt(px, py) {
  if (!inited || disabled || f < 0.3) return null;
  const v = view();
  const ndcX = (px / v.w) * 2 - 1, ndcY = 1 - (py / v.h) * 2;
  const inv = new THREE.Matrix4().copy(Mloc).invert();
  const a = new THREE.Vector4(ndcX, ndcY, -1, 1).applyMatrix4(inv);
  const b = new THREE.Vector4(ndcX, ndcY, 1, 1).applyMatrix4(inv);
  const o = new THREE.Vector3(a.x / a.w, a.y / a.w, a.z / a.w);
  const dir = new THREE.Vector3(b.x / b.w, b.y / b.w, b.z / b.w).sub(o).normalize();
  let best = null, bd = 1e18;
  const v0 = view(); const W = v0.W, c0 = v0.center;
  const cwx = (c0.lng + 180) / 360 * W, cwy = mercY(c0.lat) * W;
  const mpp = EARTH_C * Math.cos(c0.lat * Math.PI / 180) / W;
  for (const [k, it] of insts) {
    const visF = (it.rootF && it.rootF.visible) || (it.rootS && it.rootS.visible);
    if (!visF || !it.lenM) continue;
    const hx = ((it.lng + 180) / 360 * W - cwx) * mpp, hy = (mercY(it.lat) * W - cwy) * mpp;
    const fe = Math.sin(it.brgSm), fs = -Math.cos(it.brgSm);
    const re = Math.cos(it.brgSm), rs = Math.sin(it.brgSm);
    const ex = o.x - hx, ey = o.y - hy;
    const oA = ex * fe + ey * fs, oS = ex * re + ey * rs, oU = o.z;
    const dA = dir.x * fe + dir.y * fs, dS = dir.x * re + dir.y * rs, dU = dir.z;
    const L = it.lenM;
    let tmin = -1e9, tmax = 1e9;
    const slab = (o0, d0, lo, hi) => {
      if (Math.abs(d0) < 1e-9) { if (o0 < lo || o0 > hi) return false; return true; }
      let t1 = (lo - o0) / d0, t2 = (hi - o0) / d0;
      if (t1 > t2) { const tt = t1; t1 = t2; t2 = tt; }
      tmin = Math.max(tmin, t1); tmax = Math.min(tmax, t2);
      return tmax >= tmin;
    };
    if (!slab(oS, dS, -2.8, 2.8)) continue;
    if (!slab(oU, dU, -0.5, 5.0)) continue;
    if (!slab(oA, dA, -L * 0.98, 5)) continue;
    if (tmin < bd) { bd = tmin; best = it.trip; }
  }
  return best;
}

window.__t3dStats = () => ({ ...stats, inst: insts.size, fps: Math.round(stats.fps), night: nightOn, layerOn });
window.__t3dConsistency = () => {
  const v = view();
  const mpp = EARTH_C * Math.cos(v.center.lat * Math.PI / 180) / v.W;
  const out = [];
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible || it.consDx === undefined) continue;
    out.push({ trip: it.trip.t, dPx: +(Math.hypot(it.consDx, it.consDy) / mpp).toFixed(3), dHeadDeg: +((it.consDh || 0) * 180 / Math.PI).toFixed(3), tanAmbDeg: +(it.tanAmb || 0).toFixed(2), projErrM: +(it.projErrM || 0).toFixed(2), totalLenM: +((it.totalLen || it.lenM) || 0).toFixed(1), tmplLenM: +(it.lenM || 0).toFixed(1), lenErrPct: +(Math.abs((it.totalLen || it.lenM) - it.lenM) / it.lenM * 100).toFixed(2) });
    if (out.length >= 10) break;
  }
  return out;
};
window.__t3dTable = () => {
  const pick = { straight: null, gentle: null, sharp: null };
  const score = it => {
    let mx = 0;
    for (let i = 1; i < (it.carDiag || []).length; i++) mx = Math.max(mx, Math.abs(it.carDiag[i].adjDeg));
    return mx;
  };
  for (const it of insts.values()) {
    if (!it.carDiag || it.carDiag.length < 3 || !it.rootF || !it.rootF.visible) continue;
    const mx = score(it);
    const rec = { trip: it.trip.t, nm: it.trip.nm || '', line: (it.trip.lines && it.trip.lines[0]) || '', maxAdjDeg: +mx.toFixed(2), head: { lng: it.lng, lat: it.lat }, cars: it.carDiag };
    if (mx < 0.5 && !pick.straight) pick.straight = rec;
    else if (mx >= 0.5 && mx < 3 && !pick.gentle) pick.gentle = rec;
    else if (mx >= 3 && !pick.sharp) pick.sharp = rec;
  }
  return pick;
};
/* 弯道验证钩子:枚举当前视口所有 maxAdjDeg≥阈值的编组(含逐节 mode/adjDeg 与采样腿信息);
   full=false 时省略逐节 cars,用于全量普查 */
window.__t3dCurveScan = (minDeg, full) => {
  const th = minDeg == null ? 0.5 : minDeg;
  const out = [];
  for (const it of insts.values()) {
    if (!it.carDiag || it.carDiag.length < 3 || !it.rootF || !it.rootF.visible) continue;
    let mx = 0; const modes = {};
    for (const r of it.carDiag) { mx = Math.max(mx, Math.abs(r.adjDeg)); modes[r.mode] = (modes[r.mode] || 0) + 1; }
    if (mx < th) continue;
    const row = { trip: it.trip.t, nm: it.trip.nm || '', line: (it.trip.lines && it.trip.lines[0]) || '', maxAdjDeg: +mx.toFixed(2), modes, leg: it._samLeg, orient: it._samOrient, projErrM: +(it.projErrM || 0).toFixed(1), tanAmb: +(it.tanAmb || 0).toFixed(2), nDiag: it.carDiag.length, head: { lng: +it.lng.toFixed(5), lat: +it.lat.toFixed(5) } };
    if (full !== false) row.cars = it.carDiag;
    out.push(row);
  }
  return out.sort((a, b) => b.maxAdjDeg - a.maxAdjDeg);
};
/* EXP 服帖诊断(仅实验分支):逐节量化「贴线服帖度」。
   口径:车中心取实际渲染节点位置(全精度,非 carDiag 舍入值);
   devM/devPx = 车中心到原始腿折线(地图所绘轨道线)最近垂直距离(米/像素);
   gapDevM = 相邻车中心实距 − 名义步长(半车长+半车长+gap);
   dTan/adjDeg 沿用 carDiag(朝向−采样切线 / 邻节夹角)。 */
window.__t3dFit = (opt) => {
  if (!inited || disabled) return { err: 'not inited' };
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  const mpp = EARTH_C * Math.cos(c.lat * Math.PI / 180) / W;
  const relX = lng => ((lng + 180) / 360 * W - cwx) * mpp;
  const relY = lat => (mercY(lat) * W - cwy) * mpp;
  const out = [];
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible || !it.carDiag || !it.carDiag.length || it.M2 == null) continue;
    if (opt && opt.trip != null && it.trip.t !== opt.trip) continue;
    /* 参考线取净化腿(与 __t3dArc 采样同源):原始绘制折线在站喉回折尖峰处与采样线
       相差数十米(单点回折短桩),车实际贴的是净化线 —— 与走廊断言同口径,
       避免把绘制尖峰误判为错节。__t3dLegSan 缺失时退回 LegRaw。 */
    const raw = (window.__t3dLegSan || window.__t3dLegRaw) ? (window.__t3dLegSan || window.__t3dLegRaw)(it.trip, it.M2, it._samLeg) : null;
    if (!raw || raw.err) continue;
    const segs = [];
    for (const lg of raw.legs || []) {
      if (lg.none || !lg.coords) continue;
      for (let k = 1; k < lg.coords.length; k++) {
        segs.push([relX(lg.coords[k - 1][0]), relY(lg.coords[k - 1][1]), relX(lg.coords[k][0]), relY(lg.coords[k][1]), lg.k]);
      }
    }
    if (!segs.length) continue;
    const distToSeg = (px, py, s) => {
      const dx = s[2] - s[0], dy = s[3] - s[1];
      const L2 = dx * dx + dy * dy;
      const f = L2 > 1e-12 ? Math.min(1, Math.max(0, ((px - s[0]) * dx + (py - s[1]) * dy) / L2)) : 0;
      return Math.hypot(px - (s[0] + dx * f), py - (s[1] + dy * f));
    };
    const meta = it.carsMeta;
    const nodes = it.carNodesF || [];
    const cars = [];
    let prev = null;
    for (let i = 0; i < it.carDiag.length; i++) {
      const nd = nodes[i];
      if (!nd) { cars.push({ i, noNode: true }); continue; }
      const px = nd.position.x, py = nd.position.y;
      let dev = 1e9, devK = -9;
      for (const s of segs) { const d = distToSeg(px, py, s); if (d < dev) { dev = d; devK = s[4]; } }
      const row = { i, mode: it.carDiag[i].mode, devM: +dev.toFixed(2), devPx: +(dev / mpp).toFixed(2), legK: devK,
        head: it.carDiag[i].head, dTan: it.carDiag[i].dTan, adjDeg: it.carDiag[i].adjDeg, lng: it.carDiag[i].lng, lat: it.carDiag[i].lat };
      if (prev && meta && meta.cars[i] && meta.cars[i - 1]) {
        const step = (meta.cars[i].len + meta.cars[i - 1].len) / 2 + (it.gap || 0);
        const dd = Math.hypot(px - prev.px, py - prev.py);
        row.stepM = +step.toFixed(2); row.gapDevM = +(dd - step).toFixed(2);
      }
      cars.push(row); prev = { px, py };
    }
    out.push({ trip: it.trip.t, nm: it.trip.nm || '', line: (it.trip.lines && it.trip.lines[0]) || '',
      path: it.path || null,
      legs: (opt && opt.dumpLegs) ? (raw.legs || []).map(lg => {
        if (lg.none) return { k: lg.k, none: 1 };
        const row = { k: lg.k, n: lg.coords.length, c0: lg.coords[0], c1: lg.coords[lg.coords.length - 1], cum0: lg.cum ? lg.cum.slice(0, 4).map(x => +x.toFixed(4)) : null, cumN: lg.cum ? lg.cum.slice(-3).map(x => +x.toFixed(4)) : null };
        /* EXP 逐子段 cum 增量 vs 几何长度+方位:验证 cum/coords 一致性(折返塌陷排查) */
        if (lg.coords && lg.cum) {
          const cf = Math.cos(lg.coords[0][1] * Math.PI / 180);
          const subs = []; let geo = 0;
          for (let s = 1; s < lg.coords.length; s++) {
            const dLng = (lg.coords[s][0] - lg.coords[s - 1][0]) * cf, dLat = lg.coords[s][1] - lg.coords[s - 1][1];
            const g = Math.hypot(dLng, dLat) * 111.32; geo += g;
            subs.push([+(lg.cum[s] - lg.cum[s - 1]).toFixed(4), +g.toFixed(4), +(Math.atan2(dLng, dLat) * 180 / Math.PI).toFixed(1)]);
          }
          row.geoLen = +geo.toFixed(4); row.cumLen = +lg.cum[lg.cum.length - 1].toFixed(4); row.subs = subs;
        }
        return row;
      }) : undefined,
      locI: (opt && opt.dumpLegs) ? raw.locI : undefined,
      samDbg: (opt && opt.dumpLegs) ? (() => { const s2 = window.__t3dArc(it.trip, it.M2, it.lng, it.lat, it.brg); if (!s2) return null; const d0 = (it.carD && it.carD[0]) || 0; const c1r = it.carD && it.carD[1] != null ? s2.at(it.carD[1] - d0) : null; const c2r = it.carD && it.carD[2] != null ? s2.at(it.carD[2] - d0) : null; return { leg: s2.leg, sHead: +s2.sHead.toFixed(4), orient: s2.orient, L0: +s2.L0.toFixed(4), projErrM: +s2.projErrM.toFixed(1), pushClamp: !!s2.pushClamp, pushOffM: s2.pushOffM || 0, chainLegs: s2.chainLegs ? [...s2.chainLegs] : null, conn0: s2.conn0 ? [+s2.conn0[0].toFixed(6), +s2.conn0[1].toFixed(6)] : null, connBrg0: s2.connBrg0 != null ? +(s2.connBrg0 * 180 / Math.PI).toFixed(1) : null, push: [+it.lng.toFixed(6), +it.lat.toFixed(6)], car1: c1r ? c1r.map((v, j) => j < 2 ? +v.toFixed(6) : +v.toFixed(3)) : null, car2: c2r ? c2r.map((v, j) => j < 2 ? +v.toFixed(6) : +v.toFixed(3)) : null }; })() : undefined,
      lod: it.lod, pxLen: +((it.lenM || 0) / mpp).toFixed(0), nDiag: it.carDiag.length, metaN: meta && meta.n,
      nF: nodes.length, gap: it.gap == null ? null : +it.gap.toFixed(2), projErrM: +(it.projErrM || 0).toFixed(2),
      tanAmb: +(it.tanAmb || 0).toFixed(2), z: +stats.z.toFixed(2), mpp: +mpp.toFixed(3), cars });
    if (opt && opt.limit && out.length >= opt.limit) break;
  }
  return out;
};
/* EXP 走廊断言(整列单源验收):逐节量化「是否待在自己那根轨上、节节紧密相连」。
   devOwn = 车中心到本列自身腿链(chainLegs,实际采样链)折线的最近距离;
   devOther = 到窗口内其他腿折线的最近距离;
   判违:devOwn>corrM(离开自身走廊) / devOther<devOwn 且 ≤corrM(更贴近别的轨) / |间距-名义步长|>gapM。
   失败逐条给出 班次/第几节/自身腿/偏差/更贴近的腿。__t3dCorridorOn=true 时每 10 帧自动记 __t3dCorrLog。 */
function corrOfInst(it, CORR, GAP) {
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  const mpp = EARTH_C * Math.cos(c.lat * Math.PI / 180) / W;
  const relX = lng => ((lng + 180) / 360 * W - cwx) * mpp;
  const relY = lat => (mercY(lat) * W - cwy) * mpp;
  /* 用渲染时 sam 快照(含渲染期间 at() 已增长的 chainLegs);事后重算会在腿边界翻转出假阳性 */
  const sam = it._samRef || (window.__t3dArc ? window.__t3dArc(it.trip, it.M2, it.lng, it.lat, it.brg) : null);
  if (!sam || !sam.chainLegs) return null;
  if (!it._samRef && it.carD) {
    const d0c = it.carD[0] || 0;
    for (let j = 1; j < it.carD.length; j++) {
      const winJ = Math.max(0.5, (((it.carsMeta && it.carsMeta.cars[j]) ? it.carsMeta.cars[j].len : 20) / 2 - 2.2)) / 1000;
      sam.at(it.carD[j] - d0c, winJ);
    }
  }
  /* 用净化(采样同源)几何量化走廊:原始绘制折线在回折尖峰处与采样线相差数米,不算跨线 */
  const raw = (window.__t3dLegSan || window.__t3dLegRaw) ? (window.__t3dLegSan || window.__t3dLegRaw)(it.trip, it.M2, sam.leg) : null;
  if (!raw || !raw.legs) return null;
  const own = new Set(sam.chainLegs);
  const segOwn = [], segOther = [];
  for (const lg of raw.legs) {
    if (lg.none || !lg.coords) continue;
    const arr = own.has(lg.k) ? segOwn : segOther;
    for (let k = 1; k < lg.coords.length; k++) arr.push([relX(lg.coords[k - 1][0]), relY(lg.coords[k - 1][1]), relX(lg.coords[k][0]), relY(lg.coords[k][1]), lg.k]);
  }
  if (!segOwn.length) return null;
  const distSeg = (px, py, s) => {
    const dx = s[2] - s[0], dy = s[3] - s[1];
    const L2 = dx * dx + dy * dy;
    const f = L2 > 1e-12 ? Math.min(1, Math.max(0, ((px - s[0]) * dx + (py - s[1]) * dy) / L2)) : 0;
    return Math.hypot(px - (s[0] + dx * f), py - (s[1] + dy * f));
  };
  const distSet = (px, py, arr) => { let dv = 1e9, dk = -9; for (const s of arr) { const dd = distSeg(px, py, s); if (dd < dv) { dv = dd; dk = s[4]; } } return [dv, dk]; };
  const nodes = it.carNodesF || [];
  const meta = it.carsMeta;
  let prev = null;
  const rows = [];
  for (let i = 0; i < (it.carDiag || []).length; i++) {
    const nd = nodes[i]; if (!nd) continue;
    const px = nd.position.x, py = nd.position.y;
    const [dOwn, kOwn] = distSet(px, py, segOwn);
    const [dOth, kOth] = segOther.length ? distSet(px, py, segOther) : [1e9, -9];
    let gapDev = null;
    if (prev && meta && meta.cars[i] && meta.cars[i - 1]) {
      const step = (meta.cars[i].len + meta.cars[i - 1].len) / 2 + (it.gap || 0);
      gapDev = Math.hypot(px - prev.px, py - prev.py) - step;
    }
    const badCorr = dOwn > CORR;
    const badOther = dOth < dOwn && dOth <= CORR;
    const badGap = gapDev != null && Math.abs(gapDev) > GAP;
    if (badCorr || badOther || badGap) rows.push({ i, mode: it.carDiag[i].mode, legOwn: kOwn, devOwn: +dOwn.toFixed(2), legOther: kOth, devOther: dOth < 1e8 ? +dOth.toFixed(2) : null, gapDev: gapDev != null ? +gapDev.toFixed(2) : null, why: (badCorr ? 'CORR ' : '') + (badOther ? 'OTHER ' : '') + (badGap ? 'GAP' : '') });
    prev = { px, py };
  }
  return { trip: it.trip.t, line: (it.trip.lines && it.trip.lines[0]) || '', chainLegs: [...own], nCars: (it.carDiag || []).length, viol: rows };
}
window.__t3dCorridor = (opt) => {
  if (!inited || disabled) return { err: 'not inited' };
  const CORR = (opt && opt.corrM) || 3.5, GAP = (opt && opt.gapM) || 1.0;
  const out = []; let cars = 0, vCorr = 0, vOther = 0, vGap = 0;
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible || !it.carDiag || !it.carDiag.length || it.M2 == null) continue;
    const r = corrOfInst(it, CORR, GAP);
    if (!r) continue;
    cars += r.nCars;
    for (const vrow of r.viol) { if (vrow.why.includes('CORR')) vCorr++; if (vrow.why.includes('OTHER')) vOther++; if (vrow.why.includes('GAP')) vGap++; }
    out.push(r);
  }
  return { corrM: CORR, gapM: GAP, cars, vCorr, vOther, vGap, nTrains: out.length, trains: out.filter(t => t.viol.length || (opt && opt.all)) };
};
/* EXP 站喉 chain-oob 尾车审计:口径 = 比对 d(车后向距离) 与 arcToHead(头车后方已连通弧长,
   随采样返回 p[7])。d>arcToHead → 真越界(车尾在路线注册几何之外,切线反延是正确处理);
   d≤arcToHead → 外推误判(回退本可找到连通腿,属缺陷,须修判据不得放宽阈值)。 */
window.__t3dOobAudit = () => {
  if (!inited || disabled) return { err: 'not inited' };
  const rows = []; let oobCars = 0, real = 0, misjudge = 0;
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible || !it.carDiag || !it.carDiag.length || it.M2 == null) continue;
    const hasOob = it.carDiag.some(r => r.mode === 'chain-oob');
    if (!hasOob) continue;
    const sam = it._samRef || (window.__t3dArc ? window.__t3dArc(it.trip, it.M2, it.lng, it.lat, it.brg) : null);
    if (!sam) continue;
    const d0 = (it.carD && it.carD[0]) || 0;
    const cars = [];
    for (let i = 0; i < it.carDiag.length; i++) {
      if (it.carDiag[i].mode !== 'chain-oob') continue;
      oobCars++;
      const d = (it.carD && it.carD[i] != null) ? it.carD[i] - d0 : 0;
      const r = sam.at(d);
      const arcM = (r && r[6] != null && r[3] === -2) ? r[6] : null; /* extrapConn 返回 [..,k=-2,gapM,arcM] */
      const cls = arcM == null ? 'unknown' : (d > arcM ? 'real' : 'misjudge');
      if (cls === 'real') real++; else if (cls === 'misjudge') misjudge++;
      cars.push({ i, d: +d.toFixed(1), arcToHeadM: arcM, cls });
    }
    rows.push({ trip: it.trip.t, line: (it.trip.lines && it.trip.lines[0]) || '', leg: sam.leg, sHead: +sam.sHead.toFixed(4), orient: sam.orient, cars });
  }
  return { oobCars, real, misjudge, rows };
};
/* 重叠/交叉回归钩子:可见编组两两距离+中心线夹角普查。
   分类口径:A=同线占位冲突(非连挂且同线近距离);B=异线平行贴近(夹角小);C=异线共点(停站共享站坐标);
   crossing=夹角>10°且<30m(交叉或共点堆叠)。连挂伙伴(cpl)按设计紧贴,排除。 */
window.__t3dCollide = () => {
  const K = Math.PI / 180;
  const R = [];
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible) continue;
    if (!it.lenM) continue;
    R.push({ trip: it.trip.t, line: (it.trip.lines && it.trip.lines[0]) || '', lng: it.lng, lat: it.lat, brg: it.brg, lenM: it.lenM, cpl: (it.trip.cpl || []).map(c => c.p && c.p.t) });
  }
  const pairs = [];
  for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) {
    const a = R[i], b = R[j];
    const dx = (b.lng - a.lng) * Math.cos((a.lat + b.lat) / 2 * K) * 111320;
    const dy = (b.lat - a.lat) * 110540;
    const d = Math.hypot(dx, dy);
    if (d >= 50) continue;
    let ang = Math.abs(wrapPi(a.brg - b.brg)) / K; if (ang > 90) ang = 180 - ang;
    const cpl = (a.cpl.indexOf(b.trip) >= 0) || (b.cpl.indexOf(a.trip) >= 0);
    pairs.push({ a: a.trip, b: b.trip, la: a.line, lb: b.line, d: +d.toFixed(1), ang: +ang.toFixed(1), sameLine: a.line === b.line, cpl: !!cpl });
  }
  pairs.sort((x, y) => x.d - y.d);
  const real = pairs.filter(p => !p.cpl);
  const under15 = real.filter(p => p.d < 15);
  const crossing = real.filter(p => p.d < 30 && p.ang > 10);
  /* 分类阈 3.5m:槽位/复线偏移后的邻轨间距 ≥4.2m 属正常平行轨,不计冲突 */
  const clsA = real.filter(p => p.sameLine && p.d < 3.5);
  const clsC = real.filter(p => !p.sameLine && p.d < 3.5);
  const clsB = real.filter(p => !p.sameLine && p.d < 15 && p.ang <= 10);
  return { n: R.length, minPairDist: real.length ? real[0].d : null, pairsUnder15m: under15.length, crossingPairs: crossing.length, nA: clsA.length, nB: clsB.length, nC: clsC.length, pairsUnder50: real.slice(0, 40), crossing: crossing.slice(0, 40) };
};
window.__t3dAssert = () => {
  const v = view();
  const out = [];
  for (const it of insts.values()) {
    if (!it.rootF || !it.rootF.visible || !it.carsMeta) continue;
    /* 创建帧排除:carDiag 尚未填充且淡入未开始(opacity≈0,用户不可见)的 inst 不属于
       「已渲染场景」,不计入断言(单独计数 exposed 于 meta);__t3dRec 0 行证实无可见闪烁 */
    if (!(it.carDiag || []).length && it.a < 0.05) { window.__t3dAssertBirth = (window.__t3dAssertBirth || 0) + 1; continue; }
    const expect = it.carsMeta.n;
    const placed = (it.carDiag || []).length;
    const nds = it.carNodesF || [];
    let spread = 0;
    for (let i = 1; i < nds.length; i++) spread += Math.hypot(nds[i].position.x - nds[i - 1].position.x, nds[i].position.y - nds[i - 1].position.y);
    if (nds.length > 1) spread += (it.carsMeta.cars[0].len + it.carsMeta.cars[nds.length - 1].len) / 2;
    else if (nds.length === 1) spread = it.carsMeta.cars[0].len;
    const finite = (it.carDiag || []).every(r => isFinite(r.lng) && isFinite(r.lat) && isFinite(r.head) && isFinite(r.dTan) && isFinite(r.adjDeg));
    /* 验收口径修正:spread 是对相邻车节点取直线 hypot,弯道上弦长必然短于弧长,
       不能拿它和模板连挂长 lenM 比 pass/fail(12506 的 2.54% 即此假阳性)。
       真正的整列覆盖判据是:每节车都取到弧长采样(arc/head),无 rigid/chain 回退。 */
    const arcCars = (it.carDiag || []).filter(r => r.mode === 'arc' || r.mode === 'head').length;
    const fallbackCars = (it.carDiag || []).length - arcCars;
    let inview = true;
    try { const sp = map.project([it.lng, it.lat]); inview = sp.x > -200 && sp.x < v.w + 200 && sp.y > -200 && sp.y < v.h + 200; } catch (e) {}
    /* pending-new:断言采样恰好落在 inst 创建帧(carDiag 尚未填充、材质 opacity≈0 实际不可见,
       下一帧即填充;逐帧记录器 __t3dRec 0 行证实无用户可见的整列消失)。不计 bad,单独注明。 */
    const state = it.pending ? 'pending' : (placed === 0 && nds.length === expect && it.a < 0.05 ? 'pending-new' : (inview ? 'live' : 'offview'));
    out.push({ trip: it.trip.t, nm: it.trip.nm || '', grade: it.trip.g, line: (it.trip.lines && it.trip.lines[0]) || '', expect, drawn: placed, state, a: +it.a.toFixed(3), nF: nds.length, spreadM: +spread.toFixed(1), lenM: +it.lenM.toFixed(1), chordErrPct: +(Math.abs(spread - it.lenM) / it.lenM * 100).toFixed(2), arcCars, fallbackCars, finite });
    if (out.length >= 60) break;
  }
  return out;
};
window.__t3dAxisReport = () => ({ baked: [...bakedSet], axisBad: [...axisBadSet], detail: axisReport });
window.__t3dProbeInst = (tid) => {
  const it = insts.get(tid);
  if (!it) return { none: true };
  return { tid, hasRootF: !!it.rootF, visF: !!(it.rootF && it.rootF.visible), lod: it.lod, lodT: +(it.lodT || 0).toFixed(2), nF: (it.carNodesF || []).length, nCarD: (it.carD || []).length, metaN: it.carsMeta && it.carsMeta.n, diag: (it.carDiag || []).length, M2: it.M2, a: +it.a.toFixed(2), lng: +it.lng.toFixed(6), lat: +it.lat.toFixed(6), brgDeg: +(it.brg * 180 / Math.PI).toFixed(2), samLeg: it._samLeg, samOrient: it._samOrient, samSHead: it._samSHead != null ? +it._samSHead.toFixed(5) : null };
};
window.__t3dSelfTest = () => {
  if (!inited || disabled) return { err: 'not inited' };
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  const mpp = EARTH_C * Math.cos(c.lat * Math.PI / 180) / W;
  let maxErr = 0; const pts = [];
  for (const [dlng, dlat] of [[0, 0], [0.004, 0.002], [-0.005, 0.001], [0.002, -0.004]]) {
    const lng = c.lng + dlng, lat = c.lat + dlat;
    const x = ((lng + 180) / 360 * W - cwx) * mpp, zz = (mercY(lat) * W - cwy) * mpp;
    const vv = _v1.set(x, zz, 0).applyMatrix4(Mloc);
    const mx = (vv.x + 1) / 2 * v.w, my = (1 - vv.y) / 2 * v.h;
    const ref = map.project([lng, lat]);
    const err = Math.hypot(mx - ref.x, my - ref.y);
    maxErr = Math.max(maxErr, err); pts.push(+err.toFixed(2));
  }
  return { maxErr: +maxErr.toFixed(2), pts, z: map.getZoom() };
};
window.__t3dProbe = () => {
  if (!inited || disabled) return [];
  const v = view();
  const W = v.W, c = v.center;
  const cwx = (c.lng + 180) / 360 * W, cwy = mercY(c.lat) * W;
  const mpp = EARTH_C * Math.cos(c.lat * Math.PI / 180) / W;
  const out = [];
  const prj = (x, y) => {
    const vv = _v1.set(x, y, 0).applyMatrix4(Mloc);
    return [(vv.x + 1) / 2 * v.w, (1 - vv.y) / 2 * v.h];
  };
  for (const it of insts.values()) {
    if ((!it.rootF || !it.rootF.visible) && (!it.rootS || !it.rootS.visible)) continue;
    if (!it.lenM) continue;
    const half = it.lenM / 2;
    const fx = Math.sin(it.brg), fy = -Math.cos(it.brg);
    const x0 = ((it.lng + 180) / 360 * W - cwx) * mpp - fx * half, y0 = (mercY(it.lat) * W - cwy) * mpp - fy * half;
    const x1 = ((it.lng + 180) / 360 * W - cwx) * mpp + fx * half, y1 = (mercY(it.lat) * W - cwy) * mpp + fy * half;
    const A = prj(x0, y0), B = prj(x1, y1);
    out.push({ trip: it.trip.t, nm: it.trip.nm || '', line: (it.trip.lines && it.trip.lines[0]) || '', lenM: +it.lenM.toFixed(1), lod: it.lod, px: +Math.hypot(B[0] - A[0], B[1] - A[1]).toFixed(1), mid: [Math.round((A[0] + B[0]) / 2), Math.round((A[1] + B[1]) / 2)] });
  }
  return out.sort((a, b) => b.px - a.px);
};

const _push = window.__T3D.push;
window.__T3D.push = (trip, lng, lat, brg, path, M2, kmh, color) => {
  _push(trip, lng, lat, brg, path, color);
  pendingMeta.push([trip.t, M2, kmh]);
};

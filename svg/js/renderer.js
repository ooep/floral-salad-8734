/**
 * renderer.js — Tube-Map 渲染器（原生 JS + SVG）
 *
 * 职责：
 *   1. 数据 → 投影（projection.js）→ 拓扑变形（topo.js）→ SVG 绘制
 *   2. 平移缩放（滚轮缩放 + 拖拽平移），缩放后按需重建标签
 *   3. 线路路径（遇数据缺口按连续段切分）、站点圆点、换乘放大标记
 *   4. hover 悬浮显示站点/线路信息
 *   5. focusStation() 供搜索框定位站点
 *
 * 与业务数据完全解耦：任何 {stations:[{stationId,lat,lon,...}], lines:[...]}
 * 格式的 JSON 均可直接渲染，无需修改本文件。
 */
const Renderer = (() => {
  let svg, mainGroup, linesGroup, stationsGroup, labelsGroup, lineLabelsGroup;
  let width, height;
  let zoom = 1, panX = 0, panY = 0;
  let isDragging = false, dragStartX = 0, dragStartY = 0;
  let data = null, topoCoords = null;
  let stationById = new Map(), lineById = new Map();
  let tooltipEl;
  let labelTimer = null, focusAnim = null;
  let forcedLabelId = null; // 聚焦目标站强制显示标签

  /* ---------------- 初始化 ---------------- */

  function init(svgEl) {
    svg = svgEl;
    tooltipEl = document.getElementById('tooltip');
    setupDimensions();
    setupPanZoom();
    window.addEventListener('resize', () => {
      setupDimensions();
      if (data) render(data);
    });
  }

  function setupDimensions() {
    width = window.innerWidth;
    height = window.innerHeight;
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }

  function setupPanZoom() {
    // 缩放监听提升到 window 捕获阶段：无论光标停在地图、标题、图例还是
    // 其他浮层上，滚轮/触控板都能缩放地图（可滚动 UI 浮层除外，见下）。
    window.addEventListener('wheel', (e) => {
      // 图例 / 搜索结果列表需要保留原生滚动，不劫持
      const t = e.target;
      if (t && t.closest && t.closest('#legend, #search-results')) return;
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const delta = -e.deltaY * CONFIG.ZOOM_SENSITIVITY;
      const newZoom = Math.max(CONFIG.ZOOM_MIN, Math.min(CONFIG.ZOOM_MAX, zoom * (1 + delta)));
      const ratio = newZoom / zoom;
      panX = mx - (mx - panX) * ratio;
      panY = my - (my - panY) * ratio;
      zoom = newZoom;
      updateTransform();
      scheduleLabelRebuild();
    }, { passive: false, capture: true });

    svg.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      isDragging = true;
      dragStartX = e.clientX - panX;
      dragStartY = e.clientY - panY;
      svg.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      panX = e.clientX - dragStartX;
      panY = e.clientY - dragStartY;
      updateTransform();
    });

    window.addEventListener('mouseup', () => {
      isDragging = false;
      svg.style.cursor = '';
    });

    // 滚轮/拖拽时避免与文字选中冲突
    svg.addEventListener('dragstart', (e) => e.preventDefault());
  }

  let lastZoomForWidths = 1;
  function updateTransform() {
    if (mainGroup) {
      mainGroup.setAttribute('transform', `translate(${panX},${panY}) scale(${zoom})`);
    }
    if (zoom !== lastZoomForWidths) {
      lastZoomForWidths = zoom;
      updateLineWidths();
    }
  }

  /* ---------------- 渲染主流程 ---------------- */

  function render(topology) {
    data = topology;
    stationById = new Map(topology.stations.map(s => [s.stationId, s]));
    lineById = new Map(topology.lines.map(l => [l.id, l]));

    svg.innerHTML = '';
    mainGroup = document.createElementNS(CONFIG.SVG_NS, 'g');
    svg.appendChild(mainGroup);
    createDefs();

    linesGroup = makeGroup('lines-layer');
    stationsGroup = makeGroup('stations-layer');
    lineLabelsGroup = makeGroup('line-labels-layer');
    labelsGroup = makeGroup('labels-layer');

    const projected = Projection.project(
      data.stations, width, height, CONFIG.CANVAS_PADDING
    );
    topoCoords = Topo.run(projected.coords, data.lines, data.stations, CONFIG.MANUAL_OVERRIDES);

    renderLines(data.lines);
    renderStations(data.stations);
    rebuildLabels();
    updateTransform();
  }

  function makeGroup(cls) {
    const g = document.createElementNS(CONFIG.SVG_NS, 'g');
    g.setAttribute('class', cls);
    mainGroup.appendChild(g);
    return g;
  }

  function createDefs() {
    const defs = document.createElementNS(CONFIG.SVG_NS, 'defs');
    const filter = document.createElementNS(CONFIG.SVG_NS, 'filter');
    filter.setAttribute('id', 'glow');
    filter.setAttribute('x', '-80%'); filter.setAttribute('y', '-80%');
    filter.setAttribute('width', '260%'); filter.setAttribute('height', '260%');
    const blur = document.createElementNS(CONFIG.SVG_NS, 'feGaussianBlur');
    blur.setAttribute('in', 'SourceGraphic'); blur.setAttribute('stdDeviation', '1.6');
    blur.setAttribute('result', 'blur');
    const merge = document.createElementNS(CONFIG.SVG_NS, 'feMerge');
    const n1 = document.createElementNS(CONFIG.SVG_NS, 'feMergeNode'); n1.setAttribute('in', 'blur');
    const n2 = document.createElementNS(CONFIG.SVG_NS, 'feMergeNode'); n2.setAttribute('in', 'SourceGraphic');
    merge.appendChild(n1); merge.appendChild(n2);
    filter.appendChild(blur); filter.appendChild(merge);
    defs.appendChild(filter);
    mainGroup.appendChild(defs);
  }

  /* ---------------- 线路 ---------------- */

  function lineColor(line) {
    return getLineColor(line.operator, line.name, line.color);
  }

  function renderLines(lines) {
    for (const line of lines) {
      const color = lineColor(line);
      // 按连续可解析站点切分（数据缺口处断开，避免出现假直线）
      let run = [];
      const flush = () => {
        if (run.length >= 2) drawLinePath(line, color, run);
        run = [];
      };
      for (const sid of line.stations) {
        if (topoCoords[sid]) run.push(topoCoords[sid]);
        else flush();
      }
      flush();
    }
  }

  function drawLinePath(line, color, pts) {
    const d = ptsToPath(pts);
    const casing = document.createElementNS(CONFIG.SVG_NS, 'path');
    casing.setAttribute('d', d);
    casing.setAttribute('fill', 'none');
    casing.setAttribute('stroke', CONFIG.BG_COLOR);
    casing.setAttribute('stroke-width', CONFIG.LINE_CASING_WIDTH);
    casing.setAttribute('stroke-linecap', 'round');
    casing.setAttribute('stroke-linejoin', 'round');
    casing.setAttribute('vector-effect', 'non-scaling-stroke');
    casing.setAttribute('data-line', line.id);
    casing.dataset.baseW = CONFIG.LINE_CASING_WIDTH;
    casing.dataset.isCasing = '1';
    attachLineHover(casing, line, color);
    linesGroup.appendChild(casing);

    const path = document.createElementNS(CONFIG.SVG_NS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', CONFIG.LINE_WIDTH);
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('vector-effect', 'non-scaling-stroke');
    path.setAttribute('data-line', line.id);
    path.dataset.baseW = CONFIG.LINE_WIDTH;
    path.dataset.isCasing = '0';
    attachLineHover(path, line, color);
    linesGroup.appendChild(path);
  }

  /** 线宽随缩放渐进放大：屏幕线宽 = 基础值 × √zoom，封顶于 config 上限 */
  function updateLineWidths() {
    const kids = linesGroup.children;
    for (const el of kids) {
      const base = parseFloat(el.dataset.baseW);
      if (!base) continue;
      const max = el.dataset.isCasing === '1'
        ? CONFIG.LINE_CASING_WIDTH_MAX_SCREEN
        : CONFIG.LINE_WIDTH_MAX_SCREEN;
      el.setAttribute('stroke-width', Math.min(base * Math.sqrt(zoom), max).toFixed(2));
    }
  }

  function attachLineHover(el, line, color) {
    el.addEventListener('mouseenter', (e) => onLineHover(e, line, color));
    el.addEventListener('mouseleave', () => onLineLeave());
  }

  function ptsToPath(pts) {
    if (!pts.length) return '';
    let d = `M${pts[0].x.toFixed(2)},${pts[0].y.toFixed(2)}`;
    for (let i = 1; i < pts.length; i++) {
      d += `L${pts[i].x.toFixed(2)},${pts[i].y.toFixed(2)}`;
    }
    return d;
  }

  /* ---------------- 站点 ---------------- */

  function isTransferStation(station) {
    return !!(station.isTransfer || (station.lineIds && station.lineIds.length >= 2));
  }

  function renderStations(stations) {
    const sorted = [...stations].sort((a, b) => {
      const na = a.lineIds ? a.lineIds.length : 0;
      const nb = b.lineIds ? b.lineIds.length : 0;
      return na - nb; // 换乘站后绘制，位于上层
    });

    for (const station of sorted) {
      const coord = topoCoords[station.stationId];
      if (!coord) continue;
      const transfer = isTransferStation(station);
      const r = transfer ? CONFIG.TRANSFER_RADIUS : CONFIG.STATION_RADIUS;

      const circle = document.createElementNS(CONFIG.SVG_NS, 'circle');
      circle.setAttribute('cx', coord.x);
      circle.setAttribute('cy', coord.y);
      circle.setAttribute('r', r);
      circle.setAttribute('data-station', station.stationId);
      circle.dataset.baseR = r;
      circle.dataset.transfer = transfer ? '1' : '0';

      if (transfer) {
        circle.setAttribute('fill', CONFIG.BG_COLOR);
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', CONFIG.TRANSFER_STROKE);
        circle.style.filter = 'url(#glow)';
      } else {
        const color = stationColor(station);
        circle.setAttribute('fill', color);
        circle.setAttribute('stroke', CONFIG.BG_COLOR);
        circle.setAttribute('stroke-width', 1);
      }

      circle.style.cursor = 'pointer';
      circle.addEventListener('mouseenter', (e) => onStationHover(e, station));
      circle.addEventListener('mouseleave', () => onStationLeave());
      stationsGroup.appendChild(circle);
    }
  }

  function stationColor(station) {
    const lid = station.lineIds && station.lineIds[0];
    if (lid) {
      const l = lineById.get(lid);
      if (l) return lineColor(l);
    }
    return '#ffffff';
  }

  /* ---------------- 标签 ---------------- */

  function scheduleLabelRebuild() {
    if (labelTimer) clearTimeout(labelTimer);
    labelTimer = setTimeout(rebuildLabels, 120);
  }

  function textWidth(text, fontSize) {
    let w = 0;
    for (const ch of text) {
      w += ch.charCodeAt(0) > 255 ? 1.02 : 0.58; // CJK ≈ 1em，拉丁 ≈ 0.58em
    }
    return w * fontSize;
  }

  /** 网格去重标签放置；返回是否放置成功 */
  function placeLabel(occupied, x, y, w, h) {
    const cell = CONFIG.LABEL_GRID_PX / zoom;
    if (cell <= 0) return false;
    const x0 = Math.floor((x - w / 2) / cell);
    const x1 = Math.floor((x + w / 2) / cell);
    const y0 = Math.floor((y - h / 2) / cell);
    const y1 = Math.floor((y + h / 2) / cell);
    for (let cx = x0; cx <= x1; cx++) {
      for (let cy = y0; cy <= y1; cy++) {
        if (occupied.has(cx + ',' + cy)) return false;
      }
    }
    for (let cx = x0; cx <= x1; cx++) {
      for (let cy = y0; cy <= y1; cy++) occupied.add(cx + ',' + cy);
    }
    return true;
  }

  function makeText(x, y, text, fontSize, angle) {
    const t = document.createElementNS(CONFIG.SVG_NS, 'text');
    t.setAttribute('x', x);
    t.setAttribute('y', y);
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'central');
    t.setAttribute('font-size', fontSize);
    t.setAttribute('font-family', CONFIG.LABEL_FONT);
    t.setAttribute('fill', CONFIG.TEXT_COLOR);
    t.setAttribute('paint-order', 'stroke');
    t.setAttribute('stroke', CONFIG.HALO_COLOR);
    t.setAttribute('stroke-width', 3);
    t.setAttribute('stroke-linejoin', 'round');
    if (angle) t.setAttribute('transform', `rotate(${angle} ${x} ${y})`);
    t.textContent = text;
    return t;
  }

  /** 圆点半径随缩放渐进放大（基础值 × √zoom），封顶于屏幕像素上限，避免高倍成团 */
  function updateStationRadii() {
    const cs = stationsGroup.children;
    for (const c of cs) {
      const base = parseFloat(c.dataset.baseR);
      if (!base) continue;
      const isT = c.dataset.transfer === '1';
      const min = isT ? CONFIG.TRANSFER_RADIUS_MIN_SCREEN : CONFIG.STATION_RADIUS_MIN_SCREEN;
      const max = isT ? CONFIG.TRANSFER_RADIUS_MAX_SCREEN : CONFIG.STATION_RADIUS_MAX_SCREEN;
      c.setAttribute('r', Math.max(min, Math.min(max, base * Math.sqrt(zoom))).toFixed(2));
    }
  }

  function rebuildLabels() {
    if (!data || !topoCoords || labelTimer) {
      if (labelTimer) { clearTimeout(labelTimer); labelTimer = null; }
      if (!data || !topoCoords) return;
    }
    updateStationRadii();
    labelsGroup.innerHTML = '';
    lineLabelsGroup.innerHTML = '';

    const occupied = new Set();
    // 字号封顶：高倍缩放时屏幕字号不再无限放大（世界字号 = 屏幕字号 / zoom）
    const fs = Math.min(CONFIG.LABEL_FONT_SIZE * zoom, CONFIG.LABEL_FONT_MAX_SCREEN) / zoom;
    const lfs = Math.min(CONFIG.LINE_LABEL_FONT_SIZE * zoom, CONFIG.LINE_LABEL_FONT_MAX_SCREEN) / zoom;

    // 1) 换乘站标签（始终显示，按客流降序保证重要站点优先）
    const transferStations = data.stations
      .filter(s => isTransferStation(s) && topoCoords[s.stationId])
      .sort((a, b) => (b.riders || 0) - (a.riders || 0));

    for (const s of transferStations) {
      const c = topoCoords[s.stationId];
      const w = textWidth(s.name, fs);
      const h = fs * 1.3;
      const ly = c.y - (CONFIG.TRANSFER_RADIUS_MAX_SCREEN + 3) / zoom;
      if (!placeLabel(occupied, c.x, ly, w, h)) continue;
      labelsGroup.appendChild(makeText(c.x, ly, s.name, fs, 0));
    }

    // 2) 线路名标签（沿最长线段方向）
    if (zoom >= 0.45) {
      for (const line of data.lines) {
        const pts = line.stations
          .filter(sid => topoCoords[sid])
          .map(sid => topoCoords[sid]);
        if (pts.length < 2) continue;
        let best = null, bestLen = -1;
        for (let i = 0; i < pts.length - 1; i++) {
          const dx = pts[i + 1].x - pts[i].x;
          const dy = pts[i + 1].y - pts[i].y;
          const len = dx * dx + dy * dy;
          if (len > bestLen) { bestLen = len; best = { p1: pts[i], p2: pts[i + 1] }; }
        }
        if (!best || Math.sqrt(bestLen) < 10) continue;
        const mx = (best.p1.x + best.p2.x) / 2;
        const my = (best.p1.y + best.p2.y) / 2;
        let angle = Math.atan2(best.p2.y - best.p1.y, best.p2.x - best.p1.x) * 180 / Math.PI;
        if (angle > 90) angle -= 180;
        if (angle < -90) angle += 180;
        // 垂直方向偏移到线路旁
        const rad = (angle * Math.PI) / 180;
        const nx = -Math.sin(rad), ny = Math.cos(rad);
        const lx = mx + nx * 7, ly = my + ny * 7;

        const w = textWidth(line.name, lfs);
        const h = lfs * 1.4;
        if (!placeLabel(occupied, lx, ly, w + 6, h)) continue;
        lineLabelsGroup.appendChild(makeText(lx, ly, line.name, lfs, angle));
      }
    }

    // 3) 聚焦目标站标签（忽略网格占用，强制显示）
    if (forcedLabelId && topoCoords[forcedLabelId]) {
      const fs_ = stationById.get(forcedLabelId);
      if (fs_) {
        const c = topoCoords[forcedLabelId];
        const w = textWidth(fs_.name, fs);
        const h = fs * 1.3;
        const ly = c.y - (isTransferStation(fs_) ? CONFIG.TRANSFER_RADIUS : CONFIG.STATION_RADIUS) - 3;
        const cell = CONFIG.LABEL_GRID_PX / zoom;
        // 覆盖目标位置网格，挤掉与其冲突的标签
        const x0 = Math.floor((c.x - w / 2) / cell), x1 = Math.floor((c.x + w / 2) / cell);
        const y0 = Math.floor((ly - h / 2) / cell), y1 = Math.floor((ly + h / 2) / cell);
        const victims = [...occupied].filter(k => {
          const [vx, vy] = k.split(',').map(Number);
          return vx >= x0 && vx <= x1 && vy >= y0 && vy <= y1;
        });
        victims.forEach(v => occupied.delete(v));
        labelsGroup.appendChild(makeText(c.x, ly, fs_.name, fs, 0));
      }
    }

    // 4) 高缩放级别下显示全部站点标签
    if (zoom >= CONFIG.LABEL_SHOW_ALL_ZOOM) {
      const all = data.stations
        .filter(s => !isTransferStation(s) && topoCoords[s.stationId])
        .sort((a, b) => (b.riders || 0) - (a.riders || 0));
      const step = all.length > 6000 ? 2 : 1; // 站点过多时抽样，保性能
      for (let i = 0; i < all.length; i += step) {
        const s = all[i];
        const c = topoCoords[s.stationId];
        const w = textWidth(s.name, fs);
        const h = fs * 1.2;
        const ly = c.y - CONFIG.STATION_RADIUS - 2;
        if (!placeLabel(occupied, c.x, ly, w, h)) continue;
        labelsGroup.appendChild(makeText(c.x, ly, s.name, fs, 0));
      }
    }
  }

  /* ---------------- 交互：hover / 聚焦 ---------------- */

  function onLineHover(e, line, color) {
    const els = linesGroup.querySelectorAll(`path[data-line="${cssEscape(line.id)}"]`);
    els.forEach(p => {
      const isCasing = p.getAttribute('stroke') === CONFIG.BG_COLOR;
      p.setAttribute('stroke-width', isCasing ? CONFIG.LINE_CASING_WIDTH + 3 : CONFIG.LINE_WIDTH + 2.5);
    });
    showTooltip(e, `
      <div style="font-weight:800;color:${color}">${escHtml(line.operator)}</div>
      <div>${escHtml(line.name)}</div>
      <div style="color:#8b939e;font-size:11px">${line.stationCount} stations${line.totalKm ? ' · ' + line.totalKm + ' km' : ''}</div>
    `);
    svg.style.cursor = 'pointer';
  }

  function onLineLeave() {
    if (!data) return;
    for (const line of data.lines) {
      const els = linesGroup.querySelectorAll(`path[data-line="${cssEscape(line.id)}"]`);
      els.forEach(p => {
        const isCasing = p.getAttribute('stroke') === CONFIG.BG_COLOR;
        p.setAttribute('stroke-width', isCasing ? CONFIG.LINE_CASING_WIDTH : CONFIG.LINE_WIDTH);
      });
    }
    hideTooltip();
    svg.style.cursor = '';
  }

  function onStationHover(e, station) {
    const lines = (station.lineIds || []).map(id => lineById.get(id)).filter(Boolean);
    const lineNames = lines.map(l => `<span style="color:${lineColor(l)}">${escHtml(l.name)}</span>`).join(' · ');
    showTooltip(e, `
      <div style="font-weight:800;font-size:14px">${escHtml(station.name)}</div>
      ${isTransferStation(station) ? '<div style="color:#f59e0b;font-size:11px">Transfer Station</div>' : ''}
      ${lineNames ? `<div style="color:#8b939e;font-size:11px;margin-top:2px">${lineNames}</div>` : ''}
    `);
    svg.style.cursor = 'pointer';
  }

  function onStationLeave() {
    hideTooltip();
    svg.style.cursor = '';
  }

  function showTooltip(e, html) {
    tooltipEl.innerHTML = html;
    tooltipEl.style.display = 'block';
    const tw = tooltipEl.offsetWidth || 180;
    const th = tooltipEl.offsetHeight || 40;
    let left = e.clientX + 14, top = e.clientY + 14;
    if (left + tw > window.innerWidth - 8) left = e.clientX - tw - 14;
    if (top + th > window.innerHeight - 8) top = e.clientY - th - 14;
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = top + 'px';
  }

  function hideTooltip() {
    tooltipEl.style.display = 'none';
  }

  /** 搜索定位：平滑缩放到指定站点并高亮 */
  function focusStation(stationId) {
    const c = topoCoords && topoCoords[stationId];
    if (!c) return;
    if (focusAnim) cancelAnimationFrame(focusAnim);

    const targetZoom = Math.max(zoom, CONFIG.LABEL_SHOW_ALL_ZOOM * 1.15);
    const tx = width / 2 - c.x * targetZoom;
    const ty = height / 2 - c.y * targetZoom;
    const z0 = zoom, x0 = panX, y0 = panY;
    const t0 = performance.now();
    const DUR = 450;

    forcedLabelId = stationId;
    rebuildLabels();

    // 高亮圈
    const hl = document.createElementNS(CONFIG.SVG_NS, 'circle');
    hl.setAttribute('cx', c.x); hl.setAttribute('cy', c.y);
    hl.setAttribute('r', CONFIG.TRANSFER_RADIUS + 5);
    hl.setAttribute('fill', 'none');
    hl.setAttribute('stroke', '#5bb6ff');
    hl.setAttribute('stroke-width', 2.5);
    hl.style.opacity = '0';
    stationsGroup.appendChild(hl);

    (function animate(now) {
      const t = Math.min(1, (now - t0) / DUR);
      const k = 1 - Math.pow(1 - t, 3); // easeOutCubic
      zoom = z0 + (targetZoom - z0) * k;
      panX = x0 + (tx - x0) * k;
      panY = y0 + (ty - y0) * k;
      hl.setAttribute('r', CONFIG.TRANSFER_RADIUS + 5 + t * 10);
      hl.style.opacity = String(0.9 * (1 - t));
      updateTransform();
      if (t < 1) {
        focusAnim = requestAnimationFrame(animate);
      } else {
        hl.remove();
        focusAnim = null;
        rebuildLabels();
      }
    })(t0);
  }

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  return { init, render, focusStation };
})();

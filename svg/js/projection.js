/**
 * projection.js — 真实经纬度 → 画布坐标投影
 *
 * 1. 墨卡托投影（或等距圆柱）把 lon/lat 转为平面坐标
 * 2. 计算全图包围盒，等比缩放并居中到画布
 * 3. 输出以 stationId 为键的画布坐标表（供 topo.js 变形）
 *
 * 本模块与业务数据完全解耦：任何带 lat/lon 的站点数组均可直接使用。
 */
const Projection = (() => {
  /** 墨卡托投影，返回相对比例坐标（x=经度，y=墨卡托纬度值） */
  function mercatorProject(lon, lat) {
    const x = lon;
    const latRad = (lat * Math.PI) / 180;
    const y = (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + latRad / 2));
    return { x, y };
  }

  /** 等距圆柱投影（无横向畸变，适合国内轨道交通示意）；y 取负 → 北在上 */
  function equirectProject(lon, lat) {
    const latRad = (lat * Math.PI) / 180;
    const cosRef = Math.cos((34.5 * Math.PI) / 180); // 以日本中纬度基准
    return { x: lon * cosRef, y: -lat };
  }

  const PROJECTOR = equirectProject;

  function createBounds(stations) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of stations) {
      if (s.lat == null || s.lon == null) continue;
      const p = PROJECTOR(s.lon, s.lat);
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    }
    return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
  }

  /** 以屏幕中心为轴旋转（度，正值逆时针） */
  function rotatePoint(x, y, deg) {
    if (!deg) return { x, y };
    const rad = (deg * Math.PI) / 180;
    const c = Math.cos(rad), s = Math.sin(rad);
    return { x: x * c - y * s, y: x * s + y * c };
  }

  /**
   * 投影全部站点：返回 { coords: {stationId: {x,y}}, geoBounds, scale, offsetX, offsetY }
   * stations 中每一项需含 stationId/lat/lon。
   */
  function project(stations, canvasWidth, canvasHeight, padding, rotateDeg) {
    const geoBounds = createBounds(stations);
    const cx = geoBounds.minX + geoBounds.width / 2;
    const cy = geoBounds.minY + geoBounds.height / 2;

    // 旋转后重新计算包围盒，保证整图居中
    let pts = stations
      .filter(s => s.lat != null && s.lon != null)
      .map(s => {
        const p = PROJECTOR(s.lon, s.lat);
        return rotatePoint(p.x - cx, p.y - cy, rotateDeg);
      });
    let rMinX = Infinity, rMinY = Infinity, rMaxX = -Infinity, rMaxY = -Infinity;
    for (const p of pts) {
      if (p.x < rMinX) rMinX = p.x;
      if (p.y < rMinY) rMinY = p.y;
      if (p.x > rMaxX) rMaxX = p.x;
      if (p.y > rMaxY) rMaxY = p.y;
    }
    const rW = rMaxX - rMinX, rH = rMaxY - rMinY;

    const availW = canvasWidth - padding * 2;
    const availH = canvasHeight - padding * 2;
    let scale;
    if (rW <= 0 || rH <= 0) scale = 1;
    else scale = Math.min(availW / rW, availH / rH);
    const offsetX = padding + (availW - rW * scale) / 2 - rMinX * scale;
    const offsetY = padding + (availH - rH * scale) / 2 - rMinY * scale;

    const coords = {};
    for (const s of stations) {
      if (s.lat == null || s.lon == null) continue;
      const p = PROJECTOR(s.lon, s.lat);
      const r = rotatePoint(p.x - cx, p.y - cy, rotateDeg);
      coords[s.stationId] = {
        x: r.x * scale + offsetX,
        y: r.y * scale + offsetY,
      };
    }
    return { coords, geoBounds, scale, offsetX, offsetY };
  }

  return { createBounds, project, mercatorProject, equirectProject };
})();

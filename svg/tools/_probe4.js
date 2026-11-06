const fs = require('fs');
const load = (f) => fs.readFileSync(f, 'utf8');
const { CONFIG, Projection } = (() => {
  const src = load('js/config.js') + '\n' + load('js/projection.js');
  return new Function(src + '\n;return {CONFIG, Projection};')();
})();
const data = JSON.parse(fs.readFileSync('topology.json', 'utf8'));
const byId = new Map(data.stations.map((s) => [s.stationId, s]));
const projected = Projection.project(data.stations, 1280, 960, CONFIG.CANVAS_PADDING);

function havKm(a, b) {
  const R = 6371;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

// 收集 >25px 线段（投影后）
const long = [];
for (const l of data.lines) {
  for (let i = 0; i < l.stations.length - 1; i++) {
    const a = l.stations[i], b = l.stations[i + 1];
    if (a === b) continue;
    const pa = projected.coords[a], pb = projected.coords[b];
    if (!pa || !pb) continue;
    const len = Math.hypot(pb.x - pa.x, pb.y - pa.y);
    if (len > 25) {
      const sa = byId.get(a), sb = byId.get(b);
      const km = sa && sb ? havKm(sa, sb) : 0;
      long.push({ line: l.id, a, b, len: +len.toFixed(1), km: +km.toFixed(0), sa, sb });
    }
  }
}
// 分类：<350km 合理稀疏（新干线等）；>=350km 幻影
const phantom = long.filter((x) => x.km >= 350);
const sparse = long.filter((x) => x.km < 350);
console.log('长线段总数:', long.length, '| 合理稀疏(<350km):', sparse.length, '| 幻影(>=350km):', phantom.length);
console.log('---- 幻影段 ----');
for (const x of phantom) {
  console.log(x.line.slice(0, 40), '|', (x.sa ? x.sa.name : x.a), '(' + (x.sa ? x.sa.lat.toFixed(2) + ',' + x.sa.lon.toFixed(2) : '?') + ') →', (x.sb ? x.sb.name : x.b), '(' + (x.sb ? x.sb.lat.toFixed(2) + ',' + x.sb.lon.toFixed(2) : '?') + ')', x.km + 'km');
}

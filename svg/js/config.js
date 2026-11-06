/**
 * config.js — Tube-Map 渲染器全局配置
 *
 * 所有渲染参数集中于此。数据格式见 README.md / tools/prepare_data.py。
 * MANUAL_OVERRIDES 按 stationId 强制指定画布坐标，用于修正自动布局的线条重叠。
 */
const CONFIG = {
  /* ---------- 数据 ---------- */
  DATA_URL: 'topology.json',

  /* ---------- SVG ---------- */
  SVG_NS: 'http://www.w3.org/2000/svg',
  CANVAS_PADDING: 90,

  /* ---------- 几何/样式 ---------- */
  STATION_RADIUS: 2.6,          // 普通站点圆点半径（世界坐标基础值）
  TRANSFER_RADIUS: 6.2,         // 换乘站标记半径（世界坐标基础值）
  TRANSFER_STROKE: 2.2,         // 换乘站描边宽
  LINE_WIDTH: 3.4,              // 线路主线条宽（世界坐标基础值）
  LINE_CASING_WIDTH: 6.4,       // 线路底色描边（间隙/描边效果）
  LABEL_FONT_SIZE: 11,          // 站名标签字号（世界坐标）
  LINE_LABEL_FONT_SIZE: 10.5,   // 线路名标签字号
  /* 随缩放渐进放大的上限（屏幕像素）。线宽/圆点/字号 = 基础值 × √zoom，封顶于此，
     兼顾"放大后看得清"与"高倍缩放不膨胀成团"。 */
  LINE_WIDTH_MAX_SCREEN: 7,     // 线路主线条宽屏幕上限
  LINE_CASING_WIDTH_MAX_SCREEN: 11, // 线路底色描边屏幕上限
  STATION_RADIUS_MIN_SCREEN: 1.8, // 普通站圆点屏幕半径下限
  STATION_RADIUS_MAX_SCREEN: 5.5, // 普通站圆点屏幕半径上限
  TRANSFER_RADIUS_MIN_SCREEN: 4.5, // 换乘站标记屏幕半径下限
  TRANSFER_RADIUS_MAX_SCREEN: 11,  // 换乘站标记屏幕半径上限
  LABEL_FONT_MAX_SCREEN: 32,    // 站名标签屏幕字号上限（高倍缩放时不再膨胀）
  LINE_LABEL_FONT_MAX_SCREEN: 26, // 线路名标签屏幕字号上限
  LABEL_FONT: '"Noto Sans CJK JP", "Noto Sans SC", "Hiragino Sans", "PingFang SC", "Microsoft YaHei", sans-serif',

  BG_COLOR: '#0a0e17',
  TEXT_COLOR: '#d8dde3',
  HALO_COLOR: '#0a0e17',
  GRID_COLOR: '#151b27',

  /* ---------- 平移缩放 ---------- */
  ZOOM_MIN: 0.12,
  ZOOM_MAX: 12,
  ZOOM_SENSITIVITY: 0.002,
  LABEL_SHOW_ALL_ZOOM: 2.4,     // 缩放 ≥ 该值后显示全部站点标签
  LABEL_GRID_PX: 30,            // 标签去重网格（屏幕像素）

  /* ---------- 拓扑变形（贝克规则，绕中点旋转迭代松弛） ---------- */
  TOPO_ITERATIONS: 70,          // 迭代轮数
  TOPO_ROTATION: 1.0,           // 每轮向八方向旋转偏差的比例（初始）
  TOPO_ANNEAL: 0.6,             // 旋转比例随轮次退火系数
  TOPO_SPRING: 0.012,           // 地理弹簧强度（拉回真实投影位置）
  TOPO_SPRING_GAIN: 0.5,        // 弹簧随轮次增强系数
  TOPO_LENGTH: 0.35,            // 线段长度保持权重（局部拉伸/压缩）
  TOPO_MAX_STEP: 4,             // 单轮单节点最大位移
  TOPO_TRANSFER_ANCHOR: 0.4,    // 换乘站位移折减系数（更锚定）
  TOPO_REPULSION_RADIUS: 6,     // 弱斥力空间哈希半径（px，0=禁用）
  TOPO_REPULSION_K: 0.05,        // 弱斥力强度（0=禁用；越大城市核心越散开，但降低八方向吸附率）（越大越散开城市核心，但降低八方向吸附率）

  /* ---------- 线路配色 ---------- */
  LINE_COLORS: {
    '東京地下鉄': {
      '3号線銀座線': '#ff9500', '4号線丸ノ内線': '#f62e36', '2号線日比谷線': '#b5b5ac',
      '5号線東西線': '#009bbf', '9号線千代田線': '#00bb85', '8号線有楽町線': '#c1a470',
      '11号線半蔵門線': '#8f76d6', '7号線南北線': '#00ac9b', '13号線副都心線': '#9c5e31',
    },
    '東京都': {
      '1号線浅草線': '#e85298', '6号線三田線': '#0079c2',
      '10号線新宿線': '#6cbb5a', '12号線大江戸線': '#b6007a',
    },
    '大阪市高速電気軌道': {
      '1号線(御堂筋線)': '#e5171f', '2号線(谷町線)': '#522886', '3号線(四つ橋線)': '#0078ba',
      '4号線(中央線)': '#019a66', '5号線(千日前線)': '#e44d93', '6号線(堺筋線)': '#814721',
      '7号線(長堀鶴見緑地線)': '#a9cc51', '8号線（今里筋線）': '#ee7b1a',
      '南港ポートタウン線': '#00a0de',
    },
    '名古屋市': {
      '東山線': '#fab123', '名城線・名港線': '#b074d6', '鶴舞線': '#009bbf',
      '桜通線': '#c92f44', '上飯田線': '#ec78b4',
    },
    '札幌市': { '南北線': '#35a16b', '東西線': '#ff9900', '東豊線': '#0041ff' },
    '京都市': { '烏丸線': '#3cb371', '東西線': '#ff4500' },
    '神戸市': { '西神線・山手線・北神線': '#00ae8e', '海岸線': '#267dce' },
    '仙台市': { '南北線': '#008f4c', '東西線': '#0098a1' },
    '福岡市': { '空港線': '#FB7F09', '箱崎線': '#00A0E9', '七隈線': '#008B4F' },
  },

  JR_COLORS: {
    '北海道旅客鉄道': '#7fd14f',
    '東日本旅客鉄道': '#2eb35a',
    '東海旅客鉄道': '#f5821f',
    '西日本旅客鉄道': '#2f86d6',
    '四国旅客鉄道': '#22c3e6',
    '九州旅客鉄道': '#e8443b',
  },

  /**
   * 手动坐标覆盖：按 stationId 强制指定画布坐标。
   * 自动拓扑布局完成后，用这些坐标替换对应站点位置，用于修正线条重叠。
   * 键必须是数据中的 stationId（如 "S000123"）。
   * 例：
   *   'S000123': { x: 640, y: 300, strength: 1 },
   */
  MANUAL_OVERRIDES: {
    // 示例（替换为实测需要修正的站点）：
    // 'S000001': { x: 600, y: 320 },
  },
};

/**
 * 线路配色：优先线路自带 color → 线路表 → JR 表 → 确定性哈希色。
 * 完全由数据驱动，任何网络数据都能得到可区分配色。
 */
function getLineColor(op, lineName, lineColor) {
  if (lineColor) return lineColor;
  if (CONFIG.LINE_COLORS[op] && CONFIG.LINE_COLORS[op][lineName]) {
    return CONFIG.LINE_COLORS[op][lineName];
  }
  if (CONFIG.JR_COLORS[op]) return CONFIG.JR_COLORS[op];
  return hashColor(op + '|' + lineName);
}

function hashColor(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  }
  h = Math.abs(h);
  const hue = h % 360;
  const sat = 52 + (h % 30);
  const light = 52 + ((h >> 3) % 16);
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

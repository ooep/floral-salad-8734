# Mini JapanRail · Tube Map（网页版日本全国轨道交通拓扑示意图）

基于**真实经纬度** → 等距圆柱投影 → **贝克式（Beck）拓扑变形**的
Tube-Map 风格全国轨道交通网络图。纯原生 JS + SVG 实现，无地理底图，
画面只保留铁路线路、站点与文字标签。

## 目录结构

```
svg/
├── index.html            # 入口页面（搜索、图例、加载兜底）
├── topology.json         # 业务数据（formatVersion 2，见下）
├── topology_v1.json      # 旧格式权威源（以站名为键，含同名合并缺陷）
├── topology_pre_fix.json # v2 缺陷版备份（消歧前）
├── js/
│   ├── config.js         # 全部配置 + 手动坐标覆盖 MANUAL_OVERRIDES
│   ├── projection.js     # 经纬度 → 画布坐标投影（解耦，纯几何）
│   ├── topo.js           # 贝克拓扑变形（八方向吸附迭代松弛 + 弱斥力）
│   └── renderer.js       # SVG 渲染、平移缩放、hover、搜索聚焦
└── tools/
    ├── prepare_data.py   # 旧格式 → 新格式加工脚本（可复用）
    ├── fix_homonyms.py   # 同名消歧 + 错误坐标修复脚本（可复用）
    └── analyze_layout.js # 布局质量分析（吸附率/交叉数/约束校验）
```

## 运行方式

浏览器安全策略禁止 `file://` 页面 fetch 本地 JSON，任选其一：

1. **本地服务器（推荐）**：在项目根目录执行
   ```
   python3 -m http.server 8000
   ```
   然后访问 `http://localhost:8000/svg/`。
2. **直接双击 index.html**：页面会提示手动选择 `topology.json` 文件加载
   （FileReader 读取，无需服务器）。
3. 支持 `?data=路径` 参数覆盖数据文件。

## 交互

- **滚轮**：以光标为中心缩放；**拖拽**：平移
- **hover 站点**：悬浮显示站名、是否换乘、途经线路（含线路色）
- **hover 线路**：高亮整条线路，显示运营者/线路名/站数/里程
- **右上搜索**：按站名/线路名/运营者检索，回车或点击定位并缩放
- **缩放提示**：换乘站标签常显；缩放足够大后显示全部站点标签；
  线路名标签沿线路走向排布（网格去重，避免重叠）
- **高倍缩放**：线路线宽、站点圆点、标签字号均按屏幕像素封顶，
  城市核心放大后不膨胀成团

## 数据格式（formatVersion 2）

渲染器与业务数据**完全解耦**：替换同格式 JSON 即可渲染任意轨道交通网络，
无需改动任何 JS。

```jsonc
{
  "meta": {
    "formatVersion": 2,
    "name": "…",
    "stationCount": 8150,   // 可选，缺省用 stations.length
    "lineCount": 476,       // 可选
    "transferCount": 547,   // 可选
    "homonymSplit": 126     // 可选：本次消歧拆分数
  },
  "operators": [
    { "id": "OP001", "name": "東日本旅客鉄道", "enName": "" }
  ],
  "stations": [
    {
      "stationId": "S000001",      // ★ 站点唯一键（渲染/覆盖都靠它）
      "name": "新宿",
      "lat": 35.69011, "lon": 139.70061,   // WGS84
      "isTransfer": true,                  // 换乘标记放大显示
      "ops": ["京王電鉄", "東京地下鉄"],
      "lineIds": ["京王電鉄||京王線", "…"],  // ★ 途经线路 = 换乘关系
      "riders": 2204829                    // 可选，用于标签优先级
    }
  ],
  "lines": [
    {
      "id": "京王電鉄||京王線",
      "name": "京王線",
      "operator": "京王電鉄",
      "color": "#00A1E9",        // ★ 线路颜色取自数据；缺省时哈希兜底
      "stationCount": 41,
      "totalKm": 84.7,
      "stations": ["S000123", "S000124", …]   // ★ 按顺序引用 stationId
    }
  ],
  "transfers": [
    {
      "group": "T0001",
      "name": "新宿",
      "stationIds": ["S000001"],   // 同一物理枢纽的站点集合
      "lineIds": ["…"],            // 该枢纽交汇的所有线路
      "ops": ["…"]
    }
  ]
}
```

### 关键约定（渲染器依赖）

1. `stationId` 是站点唯一键；`lines[].stations` 按**运营顺序**引用 stationId。
   渲染器按该顺序连线，**绝不重排站点**。
2. 同一物理换乘枢纽的站点共享同一坐标 → 线路在换乘站自动交汇，
   **连通性与换乘拓扑由数据保证，渲染不改动**。
3. 站点缺 `lat/lon` 时该站不可渲染，线路会按连续段断开（不产生假直线）。
4. 换乘判定：`isTransfer === true` 或 `lineIds.length >= 2`。
5. 配色：`line.color` → 内置线路色表 → 运营者色表 → 确定性哈希色。
   数据自带 `color` 时完全由数据决定。

## 手动坐标覆盖（修正自动布局线条重叠）

自动拓扑变形可能在大枢纽周边产生线条重叠，可在
`js/config.js` 的 `CONFIG.MANUAL_OVERRIDES` 中**按 stationId** 强制指定画布坐标：

```js
MANUAL_OVERRIDES: {
  'S000123': { x: 640, y: 300 },   // 该站将被固定到 (640, 300)
  'S000456': { x: 610, y: 330 },
}
```

覆盖在拓扑变形**完成后**生效，用于手工校正个别重叠；不影响其余站点布局。
查找 stationId：hover 站点看名称，再到 JSON 中检索，或控制台执行
`stationById`（Renderer 内部 Map）。

## 渲染流程

```
topology.json
   │  (stations: lat/lon, lines: stationId 序列)
   ▼
Projection.project ── 经纬度 → 画布坐标（居中、等比缩放）
   ▼
Topo.run ── 贝克变形：线段绕中点旋转吸附到 8 方向（退火），
            长度保持（局部拉伸/压缩），地理弹簧拉回，
            密集核心弱斥力展开，换乘站锚定，迭代收敛
   ▼
MANUAL_OVERRIDES ── 手动覆盖（可选，最后强制生效）
   ▼
Renderer.render ── 线路（连续段切分、屏幕恒定线宽）
               → 站点（换乘放大、屏幕钳制半径）
               → 标签（网格去重、屏幕字号封顶）
```

### 拓扑参数（js/config.js 集中管理）

| 参数 | 值 | 说明 |
|---|---|---|
| TOPO_ITERATIONS | 70 | 迭代轮数 |
| TOPO_ROTATION | 1.0 | 每轮向八方向旋转偏差的比例（初始） |
| TOPO_ANNEAL | 0.6 | 旋转比例随轮次退火系数 |
| TOPO_SPRING | 0.012 | 地理弹簧强度（拉回真实投影位置） |
| TOPO_SPRING_GAIN | 0.5 | 弹簧随轮次增强系数 |
| TOPO_LENGTH | 0.35 | 线段长度保持权重（局部拉伸/压缩） |
| TOPO_MAX_STEP | 4 | 单轮单节点最大位移（px） |
| TOPO_TRANSFER_ANCHOR | 0.4 | 换乘站位移折减系数（更锚定） |
| TOPO_REPULSION_RADIUS | 6 | 弱斥力空间哈希半径（px） |
| TOPO_REPULSION_K | 0.05 | 弱斥力强度（0=禁用；越大核心越散开，但降低吸附率） |

布局质量（1280×960 口径，tools/analyze_layout.js 可复测）：
八方向吸附（≤2°）≈ 36%、（≤4°）≈ 53%，交叉数较投影后下降；
约束校验"站序/连通未重排、换乘组站点重合"始终通过。

## 数据加工（可迁移复用）

历史数据存在两类缺陷：①同名不同址站点（大宮/福島/橋本/日本橋/住吉…
260+ 站名）以站名为唯一键被合并，产生跨地区"幻影长线段"；
②少数站点记录坐标本身错误（占位/串位坐标）。

**`tools/fix_homonyms.py`（推荐顺序）**：同名消歧 + 错误坐标修复，
直接对旧格式权威源运行：

```bash
python3 tools/fix_homonyms.py -i topology_v1.json -o topology.json
```

修复策略（对错误坐标鲁棒的局部几何，单遍无级联）：
- 2 站截断线不做聚类（无信号 → 保留记录站），经核实的记录坐标补丁表
  （COORD_PATCHES）与线路目标解析表（LINE_TARGET_PATCHES）处理少数特例；
- 常规线路按"相邻站中点"聚类（60km 阈值），与记录坐标最近的簇保留原 id，
  其余簇拆分为新 stationId；
- 换乘关系按线路引用自动重建（lineIds / transfers / isTransfer）。

**`tools/prepare_data.py`**：把任意"站名为主键、线路引用站名"的旧格式
JSON 加工为 v2（分配 stationId、计算 lineIds、显式 transfers）：

```bash
python3 tools/prepare_data.py 你的旧数据.json -o 输出.json
```

**验证**：`node tools/analyze_layout.js` 输出吸附率/交叉数/约束校验；
`node tools/_probe4.js`（临时脚本）检查 >25px 异常长线段（应仅剩
新干线等稀疏线路的合理长段，无跨区域幻影段）。

## 设计约束

- **严禁改动站点顺序 / 线路连通 / 换乘拓扑**：布局只移动节点坐标，
  线路按数据顺序连线，同 stationId 共享坐标，拓扑关系由数据锁死。
- **不渲染海岸线、地形、行政边界**：画面仅铁路线路、站点、文字标签。
- **性能**：8150 站 / 476 线全量渲染；标签按缩放级别动态重建。

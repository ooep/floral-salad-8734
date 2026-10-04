# Mini JapanRail 3D — 全日本铁路实时运行地图（3D）

参考 [Mini Tokyo 3D](https://minitokyo3d.com)（deck.gl + Mapbox + Three.js）风格与交互，基于自有全量时刻表数据构建的**全国版 3D 铁路实时运行地图**，单文件 HTML，运行时零外部请求。

## 功能（对齐原版）

| 功能 | 说明 |
|---|---|
| 🌍 3D 地球 / 2D 平面 | MapLibre Globe 投影 + 深色主题，一键切换 |
| 🚄 全日本列车实时动画 | 本地时刻表驱动，客户端按 JST 每秒推算位置，沿轨道插值 |
| 🎨 官方线路色发光轨道 | 双层渲染光晕，4,729 段 + 8,532 车站（高 zoom 站名标签） |
| 🎯 跟随列车 | 点击列车 → 相机持续跟踪运行 |
| 🚉 车站详情 | 点击车站 → 途经线路列表 |
| 🔍 搜索 | 车站 / 线路日文名模糊搜索，定位 + 高亮 |
| 🗺️ 路线搜索 | 起终点 BFS 最短路径：站数 / 换乘数 / 途经线路，地图高亮 |
| ⏱️ 时钟控制 | 播放/暂停、时间滑块（任意时刻）、0.5×~8× 倍速、回到现在 |
| 📅 运行日 | 自动（按今日+节假日历）/ 平日 / 周六 / 周日·假日 |
| 🧩 线路类型过滤 | 鉄道 / 路面電車 / モノレール / 新交通 / 鋼索 / 浮上 开关 |
| 🌐 多语言 | 简体中文 / 日本語 / English UI |
| 📊 图例 + 数据面板 | 车种配色图例、时刻表构建时间 / 班次统计 |
| ⚙️ 设置 | 车站标签 / 轨道光晕 / 车站点 开关 |

## 技术架构

| 层 | 方案 |
|---|---|
| 渲染 | MapLibre GL JS v5（Globe 投影，免费无 token，unpkg CDN） |
| 轨道 | `segments3d.geojson`（精简：from/to/line/color/kind/geometry），双层 LineLayer 发光 + kind 过滤 |
| 车站 | `stations3d.geojson`（精简），CircleLayer + 高 zoom 站名标签 |
| 列车 | 本地时刻表 `trains_wd/sa/su.json`（87,515 辆唯一班次）+ `tmaps.json` 停站归属 |
| 定位算法 | schs 交错时刻解码（2N-2）+ 站间几何插值 + BFS 同网路径（快车跳站）+ JST 虚拟时钟 |
| 路线搜索 | 全网络图 BFS（最少站数），换乘数 = 线路名变化次数 |

## 数据

- 复用 japanrail 项目全量时刻表（RailAround 577 线全量抓取；`scripts/build_3d_data.py` 精简几何）
- 刷新：跟随主站 `refresh.yml`（每周日自动抓全表维护）

## 使用

打开 `index.html` → 点右上 **⚡ 实时** → 全日本列车运行；点击列车/车站查看详情，底部时钟可回放。

线上：`https://ooep.github.io/floral-salad-8734/mini-japanrail-3d/`

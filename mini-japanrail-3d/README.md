# Mini JapanRail 3D — 全日本铁路实时运行地图（3D）

参考 [Mini Tokyo 3D](https://minitokyo3d.com)（deck.gl + Mapbox + Three.js 的东京轨道交通 3D 可视化）的风格与交互，基于自有全量时刻表数据构建的**全国版 3D 铁路实时运行地图**。

## 特点

- 🌍 **3D 地球投影**（MapLibre Globe）+ 深色主题，全国 577 条线路一眼尽收
- 🚄 **全日本列车实时动画**：本地时刻表驱动，客户端按 JST 时间每秒推算列车位置，沿轨道几何插值
- 🎨 **官方线路色发光轨道**（双层渲染光晕），4,729 段线路 + 8,532 车站
- 🎯 **跟随列车**：点击任意列车，相机持续跟踪其运行
- ⏩ **倍速回放**：0.5× / 1× / 2× / 4× 快进列车运行
- 📅 **运行日切换**：自动（按今日）/ 平日 / 周六 / 周日·假日
- 📱 移动端手势：双指旋转/倾斜、单指平移

## 技术架构

| 层 | 方案 |
|---|---|
| 渲染 | MapLibre GL JS v5（Globe 投影，免费无 token，unpkg CDN） |
| 轨道 | `segments3d.geojson`（精简：from/to/line/color/geometry），双层 LineLayer 发光 |
| 车站 | `stations3d.geojson`（精简），CircleLayer + 高 zoom 站名标签 |
| 列车 | 本地时刻表 `trains_wd/sa/su.json`（87,515 辆唯一班次）+ `tmaps.json` 停站归属 |
| 定位算法 | schs 交错时刻解码（2N-2）+ 站间几何插值 + BFS 同网路径（快车跳站） |

**运行时零外部请求**：页面只读取仓库内静态 JSON；唯一外部资源是 MapLibre CDN 与站名标签字体源。

## 数据

- 复用 japanrail 项目的全量时刻表（RailAround 577 线全量抓取，`scripts/build_3d_data.py` 精简几何）
- 刷新：跟随主站 `refresh.yml`（每周日自动抓全表维护）

## 使用

打开 `index.html` → 点右上角 **⚡ 实时** 即可看到全日本列车运行；点任意列车跟随，点地图空白处取消。

线上：`https://ooep.github.io/floral-salad-8734/mini-japanrail-3d/`

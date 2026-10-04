# 日本铁路实时运行地图 · Japan Rail Live

基于原版 **Japan Rail 全国铁路地图**（MapLibre，单文件 `index.html`）改造的组合项目：

- 🗺️ 原有功能全部保留：全日本线路/车站、客流密度、搜索、换乘高亮、中/日/英切换
- ⚡ 新增「**实时**」图层（右上角 ⚡实时 开关）：显示日本全国**当前正在运行的列车**（RailAround 公开计划时刻快照），
  按列车种类着色（新干线=绿 / 特急=红 / 快速·急行=橙 / 各停·普通=蓝），悬浮显示车种、线路、当前区间，
  位置沿本项目自有 `segments.geojson` 几何插值，每 10 分钟随 GitHub Pages 部署刷新
- ⏱️ 数据管道：GitHub Action **每 10 分钟**抓取实时快照 → 提交 → 部署 Pages → 页面插值动画

## 数据来源与机制（如实说明）

| 数据 | 来源 | 更新 |
|---|---|---|
| 线路/车站几何 | 项目自带 `data/segments.geojson` + `data/stations.geojson`（OSM 全量） | 静态 |
| 实时列车位置 | RailAround `GET /api/train?getTrainFreq=3&dataSpan=5`（逆向复刻，**计划时刻**非实时调度，不含延误） | Action 每 10 分钟 |
| tmap 停站归属 | RailAround `POST /api/animation/initial`（逐线构建，含线路名归属） | 首次 + 每日按需 |

- 列车位置 = 解码 `schs` 交错时刻（`schs[0]`=首站发车分钟；奇数位=站间运行分钟→到站；偶数位=停站分钟→发车；长度=`2N-2`，N=停站数）
  → 求当前所在区间 → 沿 `segments.geojson` 站间几何插值（缺失站回退站名坐标直线插值）
- 运行日过滤：`rday` 位掩码（1=平日 2=周六 4=周日·假日，组合 3/5/6/7），页面按 JST 当日自动过滤
- 列车线路名：由当前区间在 `segments.geojson` 中的 `line` 字段给出（精确）；`tmaps.json` 的 `lines` 作兜底

## 目录

```
index.html                      # 原版改造页（唯一入口，含 ⚡实时 图层）
data/
  segments.geojson / stations.geojson / names_en.json
  live/
    lines.json                  # 577 线 → RailAround rw_ids
    tmaps.json                  # tmap_id → 停站序列 + 线路名归属（约 2 万条）
    railways.json               # rw_id → 线名 多语言
    latest.json                 # 实时快照（Action 每 10 分钟重写）
scripts/
  fetch_live.py                 # 实时快照抓取（1 请求取全量，节流 2.2s）
  railaround_build_tmaps.py     # tmap 归属缓存构建（首次/每日按需，约 23 分钟）
  fetch_timetables.py           # 全量时刻表刷新（每周日）
.github/workflows/
  live.yml                      # 每 10 分钟：快照 → 提交 → 部署 GitHub Pages
  deploy.yml                    # 每日：tmap 缓存 → 快照 → 提交 → 部署 GH Pages + Cloudflare Pages
  rail-timetable.yml            # 每周日：全量时刻表刷新
```

## 部署（GitHub Action）

1. 把本目录推送到 GitHub 仓库（目标仓库如 `ooep/floral-salad-8734`）：
   ```bash
   git init && git add -A && git commit -m "japan rail live"
   git remote add origin https://github.com/ooep/floral-salad-8734.git
   git push -u origin main
   ```
2. **GitHub Pages**：仓库 Settings → Pages → Source 选 **GitHub Actions** → 等待 `live.yml` 首次部署
   （`https://ooep.github.io/floral-salad-8734/`）
3. **Cloudflare Pages**（可选，大陆访问更稳）：仓库配置 Secret `CF_API_TOKEN`，`deploy.yml` 每日自动部署
4. 首次 tmap 归属缓存：`deploy.yml` 每日 02:30 UTC 自动构建（约 23 分钟）；或手动
   `workflow_dispatch` 勾选 `force_tmaps` 立即全量重建

> 用量提示：Public 仓库 Actions 免费且不限分钟；若仓库为 Private，`live.yml` 的 `*/10` 每分钟部署
> 会较快消耗 2000 分钟/月预算，建议把 cron 改为 `0 * * * *`（每小时一次）。

## 本地运行

```bash
python3 scripts/railaround_build_tmaps.py   # 首次：构建 tmap 归属缓存（约 23 分钟，可 --incremental 续跑）
python3 scripts/fetch_live.py               # 抓取实时快照 → data/live/latest.json
python3 -m http.server 8765                 # 打开 http://localhost:8765 → 点右上角「⚡实时」
```

## 合规与限制

- RailAround `robots.txt` 声明 `Disallow:/api/` + `Crawl-delay:2`：所有脚本单线程、2.2s/请求；
  实时快照每轮仅 1 个请求，**如长期高频抓取请先与站点确认授权**
- 数据为**计划时刻**，不含实时延误；跨线直通列车会出现在非本线区间（可按区间线路名识别）
- 实时精度 = 快照粒度（10 分钟）+ 部署间隔（10 分钟）；要秒级实时需站点开放 CORS（当前未开放，
  故必须由 GitHub Action 抓取 → 同源部署 → 页面读取）
- 页面 WebGL：地图渲染需要浏览器 WebGL 支持（现代浏览器默认开启）

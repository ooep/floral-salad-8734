# 日本铁路实时运行地图 · Japan Rail Live

基于原版 **Japan Rail 全国铁路地图**（MapLibre，单文件 `index.html`）改造的组合项目：

- 🗺️ 原有功能全部保留：全日本线路/车站、客流密度、搜索、换乘高亮、中/日/英切换
- ⚡ 新增「**实时**」图层（右上角 ⚡实时 开关）：显示日本全国**按本地时刻表推算此刻正在运行的列车**，
  按列车种类着色（新干线=绿 / 特急=红 / 快速·急行=橙 / 各停·普通=蓝），悬浮显示车种、线路、当前区间，
  位置沿本项目自有 `segments.geojson` 几何插值，**全程不访问外部接口**

## 数据来源与机制（如实说明）

| 数据 | 来源 | 更新 |
|---|---|---|
| 线路/车站几何 | 项目自带 `data/segments.geojson` + `data/stations.geojson`（OSM 全量） | 静态 |
| 本地时刻表 | 已抓取的 RailAround 全量时刻表（577 线 / 87,515 辆唯一班次）压缩为 `trains_wd/sa/su.json` | 手动 refresh.yml（按季/按需） |
| tmap 停站归属 | RailAround `POST /api/animation/initial`（逐线构建，含线路名归属） | 静态提交 |

- **页面如何决定"此刻有哪列车"**：加载**今日对应**的本地时刻表文件（平日→`trains_wd`、周六→`trains_sa`、周日·假日→`trains_su`，含日本节假日历），
  客户端按 `rday` 位掩码 + 当前 JST 时间窗口过滤 → 解码 `schs` 交错时刻（`schs[0]`=首站发车分钟；奇数位=站间运行分钟→到站；偶数位=停站分钟→发车；长度=`2N-2`）
  → 求当前所在区间 → 沿 `segments.geojson` 站间几何插值（缺失站回退站名坐标直线插值）。每秒由客户端时钟重算，**零网络请求**。
- 运行日过滤：`rday` 位掩码（1=平日 2=周六 4=周日·假日，组合 3/5/6/7）；`trains_*.json` 已按位分组，页面只取今日那份
- 列车线路名：由当前区间在 `segments.geojson` 中的 `line` 字段给出（精确）；`tmaps.json` 的 `lines` 作兜底
- 与"实时调度"的区别：数据为**计划时刻**（不含延误）。列车晚点 5 分钟，图上点位会比真车"快 5 分钟"；
  页面刷新粒度 = 客户端每秒插值（平滑动画），数据新鲜度 = 时刻表构建时间（按季才需刷新）

## 目录

```
index.html                      # 原版改造页（唯一入口，含 ⚡实时 图层）
data/
  segments.geojson / stations.geojson / names_en.json
  live/
    lines.json                  # 577 线 → RailAround rw_ids
    tmaps.json                  # tmap_id → 停站序列 + 线路名归属（约 1 万条）
    railways.json               # rw_id → 线名 多语言
    trains_wd.json              # 平日 60,780 班次（本地时刻表，紧凑格式）
    trains_sa.json              # 周六 56,813 班次
    trains_su.json              # 周日·假日 56,963 班次
scripts/
  build_trains.py               # 从全量时刻表构建 trains_*.json（不访问网络）
  fetch_timetables.py           # 全量时刻表抓取（唯一外部抓取脚本，2.2s 节流）
  railaround_build_tmaps.py     # tmap 归属缓存构建（一次性，可跳过）
  final_verify.py               # 交付前独立验证（定位率/时刻倒退/tmap 覆盖）
.github/workflows/
  deploy.yml                    # push 触发：验证数据资产 → 部署 GitHub Pages + Cloudflare Pages（零外部请求）
  refresh.yml                   # 手动：全量时刻表刷新 → 重建本地文件 → 提交 → 部署
```

## 部署（GitHub Action）

1. 把本目录推送到 GitHub 仓库（`ooep/floral-salad-8734`）：
   ```bash
   git add -A && git commit -m "japan rail live (local timetable)"
   git push -u origin main
   ```
2. **GitHub Pages**：仓库 Settings → Pages → Source 选 **GitHub Actions** → push 后 `deploy.yml` 自动部署
   （`https://ooep.github.io/floral-salad-8734/`）
3. **Cloudflare Pages**（可选，大陆访问更稳）：仓库配置 Secret `CF_API_TOKEN`，`deploy.yml` 自动部署
4. **刷新时刻表**（按季/需要时，手动）：仓库 Actions → `Refresh full timetables (manual)` → Run workflow
   （约 65 分钟，全量抓取后重建本地文件并重新部署）

> 说明：已停用原"每 10 分钟抓取实时快照"的 live.yml——按你的要求改为**本地时刻表驱动**，
> 运行时不再访问 RailAround；唯一的外部抓取入口是手动的 refresh.yml。

## 本地运行

```bash
python3 scripts/build_trains.py     # 从全量时刻表重建 data/live/trains_*.json（已内置则跳过）
python3 -m http.server 8765         # 打开 http://localhost:8765 → 点右上角「⚡实时」
```

## 合规与限制

- 运行时**零外部请求**：页面/部署均不访问 RailAround；唯一外部抓取是手动的 `refresh.yml`
  （`robots.txt` 声明 `Disallow:/api/` + `Crawl-delay:2` → 脚本单线程、2.2s/请求）
- 数据为**计划时刻**，不含实时延误；跨线直通列车按全路线渲染（已在构建期按 train_id 全局去重，共 87,515 辆唯一班次）
- 运行日判定含 2026-2027 日本节假日历（页面内 `HOLIDAYS` 常量，后续年份请按官方公告更新）
- 页面 WebGL：地图渲染需要浏览器 WebGL 支持（现代浏览器默认开启）

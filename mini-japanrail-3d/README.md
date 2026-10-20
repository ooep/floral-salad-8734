# Mini JapanRail｜全日本列车实时运行可视化地图（3D）

对标 [Mini Tokyo 3D](https://minitokyo3d.com) 的**纯前端**全日本列车 3D 实时运行地图。单文件实现（`index.html` 内联 CSS/JS），MapLibre GL JS v6 经 CDN 引入，运行时零数据请求。

**线上地址**:https://ooep.github.io/floral-salad-8734/mini-japanrail-3d/

## 功能（对齐 Mini Tokyo 3D）

| 功能 | 说明 |
|---|---|
| 🌍 3D 地球 / 2D 平面 | MapLibre v6 Globe 投影 + 深色主题，一键切换（z12 附近自动过渡墨卡托） |
| 🚄 全日本列车实时动画 | 本地时刻表驱动，客户端按 JST 每帧推算位置，沿轨道几何弧长插值，4,000+ 列车 60fps |
| 🎨 官方线路色轨道 | 双层发光渲染，4,729 段 / 8,532 站，高 zoom 日文站名标签 |
| 🎯 点击列车 → 详情 + 跟随 | 车种 / 当前线路 / 下一站与到点 / 速度 / 途经线路 / 班次号，相机连续跟踪 |
| 🚉 点击车站 → 途经线路 | 线路彩色 chip，点击可高亮整线 |
| 🏷️ 线路小图标 | 车站时刻表面板每条线路显示官方线路记号 SVG（按线路名切分存放 `data/lines_icons/*.svg`，经 jr-static CDN 分发，225 线，Wikimedia Commons 原始矢量） |
| 🔍 搜索 | 站 / 线日文名联想（高亮命中），定位 + 高亮 |
| 🗺️ 路线搜索 | 起终点最短路（Dijkstra，距离 + 换乘罚），分段按线路色高亮， nationwide 可达 |
| ⏱️ 时钟控制 | 播放/暂停、时间滑块（任意时刻回放）、0.5×–8× 倍速、回到现在（实时） |
| 📅 运行日 | 自动（JST 日期 + 节假日历 2024–2030，含振替/国民の休日推导）/ 平日 / 周六 / 周日·祝 |
| 🧩 线路类型过滤 | 鉄道 / 路面電車 / モノレール / 案内軌条式 / 鋼索鉄道 / 浮上式 / 無軌条電車 |
| 🌐 多语言 | 简体中文 / 日本語 / English（localStorage 记忆） |
| 🛤️ 详细股道 | OSM 全量轨道线位（railway=*，含侧线/货运/私铁/路面电车/单轨/缆索，13.9 万条），按线路色渲染（OSM 线路关系色 ∪ 官方线路色表 ∪ 类型兜底）；设置内开关，开启后与简易轨道层互斥切换（其余图层与交互不变） |
| 📊 图例 + 数据面板 | 在途列车数 / 班次统计 / 运行日 / FPS |
| ⚙️ 设置 | 车站标签 / 轨道光晕 / 车站点 / 底图瓦片 / 列车光晕 开关 |

## 数据契约

- `segments3d.geojson`:轨道段,`properties={from,to,line,color,kind}`,LineString/MultiLineString
- `stations3d.geojson`:车站点,`properties={station,op,line}`
- `trains_wd/sa/su.json`(平日/周六/周日祝):`{n,b,T:[{t:班次id,r:运行日位掩码(1平日/2周六/4周日祝),w:"首站发车,末站到站",s:"紧凑串",i:车种}]}`
- `s` 串解码:首项 = 首站发车分钟,**其后为相对前一站事件的差值**(到站、发车交替,终点只有到站),长度 = 2N-2
- `tmaps.json`:`{班次id: {s_jas:[停站序列], lines:[途经线路]}}`,班次 id 可被多个 T 行复用(同径不同发车时刻)
- `orm_tracks.0.geojson` / `orm_tracks.1.geojson`:ORM 线位图层(2 分片,各 <25MB 适配 CF Pages 单文件上限,客户端合并),`properties={color,line,kind,op}`,LineString;由 OSM 全日本数据构建(见下)
- `line_icons.js`:线路小图标 URL 映射,`window.LINE_ICON = {线路名: "https://jr-static.suki.ing/data/lines_icons/<线路名>.svg"}`;SVG 按线路名单独切分存放于 `data/lines_icons/`(225 个文件,由 jr-static CDN 分发,浏览器按需并行加载+缓存);来源 Wikimedia Commons 线路记号/标志/新干线图形,经 线路名×运营商 与地图数据一致性校验(同名异司线路仅在运营商一致时启用);无图标线路回退文字记号/●

## 技术要点

- **渲染**:MapLibre custom layer 注入官方 `projectTile` 投影代码;顶点着色器按行驶方向展开朝向四边形(圆角矩形 SDF + 轮廓外光晕),输出 z 固定为 0(规避 mercator 变体裁剪空间越界导致整层被 GPU 图元裁剪);独立 VAO 隔离属性状态;GPU 侧每帧 `bufferSubData` 全量更新
- **时钟**:simNow = JST 毫秒,实时/手动(滑块回放基准日 = 当日 JST 零点)双模式;跨日自动切换时刻表文件
- **质量策略**:
  - 站名归一化(去括号注记、去尾部「駅」)提升几何匹配(23.8% → 31.7%)
  - 停靠坐标优先取相邻轨道段端点(几何对齐),**不做跨城同名站全局回退**;骨架中隐含时速 >400km 的错配坐标剔除,杜绝"列车乱飞"
  - 路线搜索图节点 = (站名, 线名),换乘边需同站坐标 <800m(防异地同名站焊接);无几何区间由时刻表乘车对补边 → 全国可达
- **已知数据边界**:轨道几何覆盖 577 线/4,729 段(城市圈完整),约 3/4 偏远区间乘车对无精细几何,列车沿直线插值(帮助面板已标注)

## 性能与体验优化（2026-10-06）

- **加载提速**:6 个数据文件（约 40MB）由串行改为 `Promise.all` 并行;IndexedDB 缓存 + HTTP 304 条件重验证（二次访问 6 文件全部 304 零传输,秒开）;索引与时刻表解析分片让出主线程,不阻塞 UI;进度条新增百分比 + 阶段文案（文件→索引→时刻表）
- **索引缓存**:静态数据构建出的 19 个全局索引（segIndex/routeGraph/searchIndex 等）写入 IndexedDB（`DATA_VERSION` 变更自动失效）,二次访问跳过约 8s 索引构建（BOOT 11.1s → 2.7s）
- **视口裁剪**:z≥5 按 mercator 视口窗口裁剪在途列车,z10 省 55% / z12 省 60%,帧耗时降约 50%
- **渲染节流**:暂停且无跟随/详情/滑动时跳过顶点重建;`document.hidden` 同理;低帧率自动关列车光晕/隔帧更新;跟随列车终到自动停止
- **功能**:加载失败「↻ 重试」;URL hash 状态持久化（视角/投影/语言/主题/运行日,刷新恢复）;车站时刻表走 8,356 站预索引（替代 5.7 万班次全表扫）;比例尺
- **UI**:iOS 安全区适配;移动端倍速按钮横滚;加载失败提示
- 数据版本:`DATA_VERSION='2026-10-06a'`（改静态数据必须递增,否则命中旧缓存）

## 本地运行

```bash
cd mini-japanrail-3d
python3 -m http.server 8931
# 打开 http://127.0.0.1:8931/
```
(必须经 HTTP 访问,直接双击 file:// 无法 fetch 数据文件)

## 数据来源

- 时刻表与路网:公开时刻表源构建(577 线几何 + 全日本班次表,构建脚本见 `scripts/build_3d_data.py`)
- 底图:国土地理院 淡色地図(可选);字体字形:OpenFreeMap
- ORM 线位图层:OSM（OpenRailwayMap 同源数据）。主站「详细股道」开关开启后互斥替换简易轨道层。构建：
  ```bash
  cd .osm_work   # 仓库根下（已 gitignore）
  python3 extract_orm_layer.py raw/*.osm.pbf \
    -o /tmp/orm_tracks.geojson \
    --curated ../mini-japanrail-3d/data/segments3d.geojson \
    --lines-map ../mini-japanrail-3d/data/lines_map.json
  # 再切片为 2 个 <25MB 分片（CF Pages 单文件上限）
  python3 - <<'PY'
  import json
  gj = json.load(open('/tmp/orm_tracks.geojson'))
  n = len(gj['features']) // 2
  for i, part in enumerate([gj['features'][:n], gj['features'][n:]]):
      with open(f'../mini-japanrail-3d/data/orm_tracks.{i}.geojson', 'w', encoding='utf-8') as f:
          json.dump({'type':'FeatureCollection','features':part}, f, ensure_ascii=False, separators=(',',':'))
  PY
  ```
  区域 PBF 取自 openstreetmap.fr/geofabrik（japan 的 8 个区域分片）。重新生成后需递增 `index.html` 的 `DATA_VERSION`（ORM 文件走同一 IDB 缓存键）。

## SEO（每线路 / 每车站静态页）

本站为纯静态 SPA，为保证「每一条线路、每一个车站」都能被各语言搜索引擎收录，
部署时会由 `seo/build_seo_static.py` 额外生成 **662 个线路页 + 8,928 个车站页**
（纯 HTML、无 JS 依赖、内置日/中/英三语站名、JSON-LD、canonical、OG 标签），
以及 sitemap / robots / 404 / og-image。详见 [seo/README.md](seo/README.md)：
- 本地生成：`cd mini-japanrail-3d && python3 seo/build_seo_static.py`
- 域名配置：`seo/seo_config.json` 的 `site_base`（与 `index.html` head 中 3 处域名保持一致）
- CI 已在部署前自动重新生成，产物不入库（见仓库根 `.gitignore`）

## 换乘案内页（journey.html）

主页「路线」tab 输入起终点后点击 → 即跳转 `journey.html`——**班次级**换乘案内
（RAPTOR 算法），与主页的「线路拼接」本质不同：知道坐哪一班、几点发、换乘等多久、几点到。

- **数据**（`data/journey/`，由 `scripts/build_journey_data.py` 从 `tmaps.json` + `trains_{wd,sa,su}.json` 生成）：

  | 文件 | 内容 |
  |---|---|
  | `stations.json` | 站节点（同名站 3km 聚类为换乘节点）：坐标 + 规范名 N + 显示名 D + 中文名 Z + 别名 X |
  | `lines.json` | 线路目录 `[日名, 中名, 色]`（轨道口径，无品牌名） |
  | `tmaps.json` | 停站模板：`[S 停站节点, L 区间线路, K 区间km(×10), P 时刻pattern, TN 爱称]` |
  | `trips_{wd,sa,su}.json` | 班次实例：`[tmap, pattern, 车种, d0, d0, …]`（同 tmap+pattern 的班次只存首站发车分） |
  | `transfers.json` | 大站换乘罚时（6min/4min）+ 物理近站步行边（<800m，罚时=距离/80+2） |
  | `types.json` | 车种词表（普/快/特/各/急… + 中文名） |

  **pattern 时刻编码**：去掉首站 d0 后的 `2N-3` 差值串，偶数位=运行分 `run_i`（站 i-1 发→站 i 着），
  奇数位=停车分 `dwell_i`（站 i，i=1..N-2）。绝对时刻递推：
  `arr[i] = dep[i-1] + run_i`，`dep[i] = arr[i] + dwell_i`（**dep 含前期 dwell，不可只累加 run**）。
  已对全部 266,971 个班次做「built (pattern,d0) ↔ 原始 s 串」逐站全量审计，零误差。

- **算法**：RAPTOR（round-based）。`τ[stop]`=最早到达分钟（绝对分钟，跨日不取模）；
  「某站乘某线 ≥t 的下一班」= 在该 tmap 有序 `dep0` 数组上二分，O(log n)。
  排序四模式：**早**（跑满轮数取全局最早）/ **楽**（首轮到达即停=换乘最少）/ **指定出发** / **始発**（起点当日最早班次）。
  环线 tmap 存在重复站 → 回溯在 parent 中存 alight 下标（禁 `indexOf`）。
  **轮次语义（重要）**：上车判定用「上一轮快照」(`tauPrev`/`revPrev`)，行程回溯按轮次逐级取父指针。
  否则同一轮内会就地串联多段乘车、且 `par` 被后续轮覆盖，使「乗換上限」(少3/标准5/不限7，默认 7) 形同虚设
  （实测曾出现 maxK=5 却给出 10 次换乘的行程）。修复后返回方案严格满足换乘上限。
  **轮数 = 乗換次数 + 1**（`rideLimit()`）：N 段乘车 = N−1 次换乘，用户选「5」应允许 5 次换乘，
  故搜索轮数取 6（此前差一位，选 5 实际只给 4 次，跨日长途被迫改走次日方案）。

- **时刻基准**：与主页一致——「早」模式的出发时刻 = JST 当前分钟（`(Date.now()+9h) % 86400000`，
  与浏览器本地时区无关）；曜日默认值按 JST 日期 + 节假日历（祝日→休日时刻，振替休日/国民の休日
  推导与主页同一张 HOLIDAY_BASE 表）。

- **校准**（Yahoo!乗換案内，2026-10-12）：東京→京都 09:00 のぞみ135号 09:00→11:15 逐站一致
  （品川 09:07 / 新横浜 09:18 / 名古屋 10:41）；札幌→函館 10:30 特急北斗10号 10:56→14:40 一致。
  部分都市圈班次与现行 Yahoo 有分钟级偏差（源数据为静态快照，页面内已提示）。
  不含飞机与末电（v2）；票价无数据源，显示营业里程 km。

- **跨日长途**：搜索允许「隔夜等待」——某站当日已无 ≥ 当前时刻的班次时，自动顺延到次日（+1440）、
  再日（+2880）…的首班（最多 +3 天；反向搜索对称地向前一日顺延）。数据只有一份时刻表，次日按
  同一份表近似，结果时间带 `+1d` / `+2d` 标记。据此 宿毛→藻琴 这类跨日长途（雅虎约 30 小时）也能给出方案。
  反向搜索(終電/指定到达)的绝对时刻会**归一化到「当日」框架**(`dep ∈ [0,1440)`)，避免跨日时出发时刻显示为负值。
- **无路径兜底**：若仍无解，依次 ①**放宽乗換上限**（默认 7 → 9）②退回当日首班起检索；
  「指定到达」若指定时刻前不可达，则回退为「最早到达」方案。仅当确实不存在可达路径（不连通）时
  才提示「未找到连通路径」，避免用户看到「找不到路径」后无所适从。

- **本地预览**：
  ```bash
  cd mini-japanrail-3d && python3 -m http.server 8000
  # http://localhost:8000/journey.html
  # 带参: journey.html#mjrj=f=東京&t=京都&d=wd&m=early
  ```
- **重建数据**：`python3 scripts/build_journey_data.py`（输入默认取 `mini-japanrail-3d/data/`，输出 `data/journey/`）。
  refresh.yml 每周刷新时刻表后会自动重建；构建失败沿用旧数据（旧数据仍自洽）。

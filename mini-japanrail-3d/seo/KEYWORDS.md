# Mini JapanRail — 标题 / 关键词 / 收录 方案

> 本文件是**关键词与收录的作战地图**：把「能用上的标题写法」「值得覆盖的关键词」「帮助搜索引擎收录的手段」全部列出来，
> 并标注**哪些已落地**（写进 `index.html` / 生成器）、哪些是**备选**（按需取用）。
> 线上域名：`https://jr.suki.ing`（换域名时同步 `seo/seo_config.json` 的 `site_base`）。

---

## 一、首页标题（`<title>`）候选

主标题只能有一个，但**不同语境可以换用不同写法**（社交分享、目录提交、外链锚文本等）。以下按优先级排序，
前 3 条是当前已采用/可直接替换的，后面是**长尾/场景化备选**。

| # | 标题写法 | 适用场景 | 说明 |
|---|---|---|---|
| 1 ✅ | `Mini JapanRail｜全日本列车实时运行可视化地图・列車走行位置・運行情報 \| Japan Train Live Map` | **当前线上** | 品牌 + 中文主词 + 日文官方词 + 英文主词，三语通吃 |
| 2 | `全日本列车实时运行可视化地图・列車走行位置・運行情報｜Mini JapanRail (Japan Train Live Map)` | 中文/日文优先 | 把主词前置，牺牲品牌前置 |
| 3 | `Mini JapanRail — 日本全国の列車走行位置・運行情報｜全日本列车实时运行地图｜Japan Train Live Map` | 日文优先 | 日文词最前，利于 Yahoo! JAPAN / Naver |
| 4 | `Japan Train Live Map — Real-Time Shinkansen & Railway Tracker \| Mini JapanRail` | 英文优先 | 面向 Google 英文区 |
| 5 | `全日本铁路实时运行图｜新干线・特急实时位置追踪・列車走行位置` | 长尾「实时位置」 | 主打「实时追踪」意图 |
| 6 | `日本列车实时运行可视化系统｜新干线・地铁・电车走行位置地图` | 长尾「可视化系统」 | 对标 `trainvisual.top` |
| 7 | `日本全国铁路 3D 实时地图｜列车运行情报・车站查询・路线搜索` | 长尾「3D」 | 主打 3D 差异点 |
| 8 | `日本电车实时位置・列车运行情报地图（全国 600+ 线路）\| Mini JapanRail` | 长尾「电车」 | 中文口语「电车」 |

> **取舍原则**：`<title>` 超过约 60–75 字符（中文按 1 字≈2 字符宽）会被 SERP 截断，
> 但**被截断的部分仍参与索引**。因此把最高价值词（`列車走行位置`、`全日本列车实时运行`）尽量前置，品牌放尾或分隔符之后。

---

## 二、各页面标题公式（生成器 `seo/build_seo_static.py`）

| 页面 | 当前标题格式 | 关键词落点 |
|---|---|---|
| 首页 | 见上表 #1 | 三语主词 + 品牌 |
| 线路页 | `山手線（山手线 / Yamanote Line）— 线路车站一览・沿線の駅 \| Mini JapanRail` | 日文名 + 中文名 + 英文名 + `駅` |
| 车站页 | `東京（东京站 / Tōkyō）— 途经上越新幹線、上越線、丸ノ内線 等 \| Mini JapanRail` | 三语站名 + 途经线路 |
| 线路一览 | `全日本铁路线路一览（新干线・JR・私铁・地下铁・路面电车）路線一覧・Railway Lines \| Mini JapanRail` | 中文 + 日文 `路線一覧` + 英文 |
| 车站一览 | `全日本车站一览（新干线・JR・私铁・地下铁）駅一覧・Station List \| Mini JapanRail` | 中文 + 日文 `駅一覧` + 英文 |
| 同名站 | 自动带消歧后缀，如 `高田(奈良県)（高田站 / Kōda）— 途经…` | 地名消歧 + 都道府县 |

**要点**：日文名优先（Yahoo! JAPAN / Naver），紧跟中文（百度）与英文（Google），再放上下文与品牌。

---

## 三、关键词矩阵（已写入 `meta keywords` / `JSON-LD`）

> 说明：Google 已基本忽略 `keywords` meta，但 **Bing / Yandex / 百度 / Naver / 搜狗** 仍部分参考；
> 同时这些词也进了 `JSON-LD` 的 `keywords` 与 `alternateName`，对实体识别有用。所以「多写不亏」。

### 中文
`日本铁路` `全日本铁路` `日本铁路地图` `日本铁路实时地图` `日本列车实时位置` `日本电车实时位置` `日本列车实时追踪`
`列车运行可视化` `列车运行可视化系统` `列车运行情报` `列车走行位置` `列车实时位置` `列车运行图` `列车实时追踪`
`新干线实时位置` `新干线地图` `日本新干线` `日本地铁地图` `日本电车地图` `日本铁路线路图` `日本车站查询`
`日本列车时刻表` `日本铁路3D地图` `全日本列车在线` `3D铁路地图`

### 日文
`列車走行位置` `列車運行情報` `運行情報` `リアルタイム列車位置` `鉄道マップ` `全国鉄道マップ` `路線図` `駅一覧` `路線一覧`
`新幹線 走行位置` `在来線 走行位置` `特急 走行位置` `電車 現在位置` `鉄道 リアルタイム` `走行シミュレーション` `3D鉄道マップ`

### 英文
`Japan train live map` `Japan railway map` `real-time train tracker` `Japan train tracker` `shinkansen live map`
`shinkansen tracker` `Japan rail map` `live train map` `Japan train positions` `Japanese railway map`
`Japan transit map` `Japan 3D train map` `Japan train timetable map`

### 竞品对标（用于拓展长尾）
| 竞品 | 主打词 | 可借鉴的长尾 |
|---|---|---|
| `tetsudou-map.com` | 列車走行位置 | 列車走行位置 マップ |
| `RailAround` | 運行情報 | 全国 運行情報 マップ |
| `trainvisual.top` / 高铁通 | 列车运行可视化 | 列车运行可视化系统 在线 |
| `trainstracking.com` | train tracking | Japan train tracking live |
| `liverailmap.com` | live rail map | Japan live rail map |

---

## 四、问答式长尾（FAQ，已写入 `FAQPage` 结构化数据）

问答是最容易被「精选摘要（featured snippet）」抓取的形态。已落地的 8 组：

1. 可以实时查看日本全国的列车运行位置吗？
2. 新幹線の現在の走行位置はわかりますか？
3. Is this Japan train live map free?
4. データはどこから取得していますか？
5. 収録されている路線・駅の数は？（600+ 线路 / 8,900+ 站 / ~4,000 列车）
6. 対応している言語は？（日・中・英）
7. スマートフォンでも使えますか？
8. 時刻表の回放（タイムスライダー）はありますか？

> **后续可加**：`遅延情報はありますか？`（答：仅计划时刻表）、`東京駅の乗り入れ路線は？`、`新幹線の路線一覧は？` 等 —— 这类「站/线 + 问题」可自动挂到对应静态页，进一步吃长尾。

---

## 五、结构化数据（JSON-LD）清单

首页现有 **6 组**（已落地）：

| 类型 | 作用 |
|---|---|
| `WebSite` | 站点实体 + `alternateName`（20 个别名）+ `publisher` |
| `Organization` | 品牌实体（logo、语言），供 `publisher` 引用 |
| `WebApplication` | 应用信息（免费、WebGL、功能列表）→ 富结果 |
| `FAQPage` | 8 组问答 → 精选摘要 |
| `Dataset` | 时刻表数据集（空间/时间覆盖）→ 数据集搜索 |
| `ItemList` | 热门线路/车站内链 → 帮助发现与传递权重 |

静态页另带 `TrainStation` / `WebPage` / `BreadcrumbList` / `ItemList`。

---

## 六、收录（Indexing）动作清单

### 已落地
- ✅ `robots.txt`（`Allow: /`，屏蔽 `/data/`、`/seo/`，带 `Sitemap:` 行）
- ✅ `sitemap.xml` 索引 + `sitemap-pages/lines/stations.xml`（9,592 个 URL）
- ✅ 每页 `<link rel="canonical">`、`og:*`、`twitter:card`（含 `og:image:width/height`、`twitter:image:alt`）
- ✅ 首页 `<meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large,max-video-preview:-1">`
- ✅ 首页 `hreflang`（zh-Hans / ja / en / x-default）
- ✅ 无 JS 也能读到的 `<noscript>` 多语言落地内容（含 FAQ、功能表、内链）
- ✅ 可见的「关于」面板含关键词 + 内链（`lines/`、`stations/`）
- ✅ 662 线路页 + 8,928 车站页互相内链 + 回链主站 `#mjr3d=` 深链

### 上线后建议手动做
1. **Google Search Console**：提交 `sitemap.xml`，请求首页与热门线路页收录；
2. **Bing Webmaster / IndexNow**：提交 sitemap（Bing 支持 IndexNow 即时推送）；
3. **百度搜索资源平台**：提交站点 + sitemap（百度对 `keywords` 仍有参考）；
4. **Yandex Webmaster / Naver Search Advisor**：面向日文/韩文流量；
5. 拿到验证 token 后，把 `google-site-verification` / `msvalidate.01` 加到 `index.html` head；
6. 外链锚文本建议统一用：`列車走行位置`、`全日本列车实时运行可视化地图`、`Japan Train Live Map`。

### 可选的进一步优化（未做，按需）
- **站/线页自动 FAQ**：把「〇〇駅の乗り入れ路線は？」自动生成并挂 `FAQPage`；
- **`SearchAction`**（sitelinks searchbox）：需一个可被爬虫访问的搜索 URL，目前站内搜索是前端 hash，暂不满足；
- **面包屑富结果**：已带 `BreadcrumbList`，观察 SERP 是否展示；
- **图片 sitemap**：把 `og-image.png` 与线路色示意图纳入 `image:image`；
- **AMP / 静态落地页**：线路页已足够静态，无需 AMP。

---

## 七、维护

- 改关键词：编辑 `index.html` head（首页）与 `seo/build_seo_static.py`（站/线/一览页），跑一次
  `python3 seo/build_seo_static.py` 即可（产物 gitignore，CI 每次部署自动重跑）。
- 换域名：同步 `seo/seo_config.json` 的 `site_base` 与 `index.html` head 里的绝对 URL（canonical / og / hreflang）。

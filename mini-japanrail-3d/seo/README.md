# Mini JapanRail — SEO 静态化

把纯静态 SPA 地图站改造成「每线路 / 每车站均可被各语言搜索引擎收录」的站点，
同时**完全不影响**主站 index.html 的任何交互功能。

## 原理

主站 `index.html` 是 WebGL 单页应用，搜索爬虫拿不到线路 / 车站的静态数据。
本方案在部署时额外生成**真实的静态 HTML 页面**（对纯静态托管而言，这比 URL 伪静态更强）：

```
/lines/<线路名>/index.html      # 662 个线路页（含轨道走向站序、线路色、运营方、类型）
/stations/<站名>/index.html     # 8,928 个车站页（含三语站名、所在地、途经线路、相邻车站）
/lines/index.html               # 线路一览（按类型分组）
/stations/index.html            # 车站一览（按都道府县分组）
/sitemap.xml                    # sitemap 索引
/sitemap-pages.xml / sitemap-lines.xml / sitemap-stations.xml
/robots.txt
/404.html
/og-image.png                   # 社交分享图（1200×630）
```

每页都是**无 JS 依赖的纯 HTML**：爬虫直接拿到完整数据；页面内嵌
**日 / 中 / 英三语站名与线路名**（中文由主站 `toZh` 同名转换表生成，英文 / 假名来自
`data/names_i18n.json`），因此 Google / Bing / Yahoo! Japan / 百度 / Naver 等各语言
搜索均可命中；并带 **JSON-LD 结构化数据**（`TrainStation` / `WebPage` /
`BreadcrumbList` / `ItemList`）、canonical、OG / Twitter 卡片，页面间互相内链，
且回链主站地图（`#mjr3d=` hash 深链，打开即定位到对应车站 / 线路）。

## 使用方法

```bash
# 在仓库根目录下执行（输出到 mini-japanrail-3d/ 各目录）
cd mini-japanrail-3d
python3 seo/build_seo_static.py

# 输出到其他目录（例如先预览再上传到托管）
python3 seo/build_seo_static.py --root /path/to/deploy
```

生成脚本只依赖 Python 标准库（PIL 可选，仅用于 og-image.png）。
产物已加入 `.gitignore`（仓库根），**无需提交**——部署时由 CI 自动重新生成。

## 部署

CI（`.github/workflows/deploy.yml`）已在每次部署前自动运行生成器：

- **GitHub Pages**：`dist/mini-japanrail-3d/` 整体复制，包含全部 SEO 页面；
- **Cloudflare Pages**（项目 `mini-japanrail-3d`）：新增复制 lines / stations / sitemap 等文件。

生成失败不会阻断部署（有 `|| echo '::warning::'` 兜底），不影响现有发布流程。
若你自行用「高德飞儿」等纯静态托管上传，只需先本地跑一次生成器，再把整个
`mini-japanrail-3d/` 目录传上去。

## 关键配置

`seo/seo_config.json`：

```json
{
  "site_base": "https://jr.suki.ing",
  "site_name": "Mini JapanRail",
  "default_lang": "zh-Hans",
  "og_image": "og-image.png",
  "lastmod_date": ""
}
```

`site_base` 为线上域名（canonical / sitemap / robots / OG 图全部由它生成），
与 `index.html` head 里的 canonical、og:url、og:image 保持一致；换域名时同步两处即可。

## 标题（Title）规则建议

| 页面 | 格式 |
| --- | --- |
| 首页 | `Mini JapanRail — 全日本铁路实时运行地图 \| Japan Rail Live Map` |
| 线路页 | `山手線（山手线 / Yamanote Line）— 线路车站一览 \| Mini JapanRail` |
| 车站页 | `東京（东京站 / Tōkyō）— 途经上越新幹線、上越線 等 \| Mini JapanRail` |
| 同名站 | 自动带消歧后缀，如 `高田(奈良県)（高田站 / Kōda）…` |

要点：日文名优先（利于 Yahoo! Japan / Naver），紧跟中文与英文名（利于百度 / Google），
再放线路上下文与品牌名；控制在 70 字左右。

## 上线后的补充动作（建议）

1. 在 Google Search Console / Bing Webmaster 提交 `sitemap.xml`（以及首页 URL）；
2. 若 GH Pages 与 Cloudflare Pages 同时在线，请在 Search Console 中指定主用域名
   （canonical 已指向 `site_base`，可避免重复内容）；
3. 站点根域名的 `robots.txt` 若由托管方统一管理（如 GitHub Pages 子路径部署），
   请把 `Sitemap:` 一行补到根 robots 或直接在 Search Console 提交；
4. `google-site-verification` / Bing 验证：拿到 token 后加到 `index.html` head 即可；
5. 数据更新后重新跑一次生成器（CI 每次部署都会自动重跑，sitemap 的 lastmod
   默认取自 `data/station_map.json` 的 `generated_at`）。

## 与主站的一致性

- 中文站名 / 线路名转换直接解析主站 `index.html` 里的 `JP2CN` / `KANA2ZH` 表，
  与站内搜索用同一套映射，不会出现「页面一个名、搜索另一个名」；
- 线路站序来自 `data/segments3d.geojson` 轨道线段（按线路名规范化聚合后沿轨道行走），
  展示的是真实途经站；`station_map.json` 中因直通运行被过度归并的线路归属不会进入线路页；
- 车站页途经线路与主站抽屉的「途经线路」口径一致（取自 `station_map.json`）；
- 线路页「本站位置（第 N 站 / 共 M 站）」与「前站 ← → 后站」方向均来自沿轨道站序；
  个别站若不在该线轨道段数据中（如部分直通 / 环线断点），该列显示「—」，如实反映数据；
- `segments3d.geojson` 与 `station_map.json` 的站名写法存在差异（如 市ヶ谷/市ケ谷、
  四ッ谷/四ツ谷、三宮/三宮(神戸市営)）：生成器先用站名 / `station_key_index` 直解，
  同名多候选用邻站坐标取最近消歧，解析失败的站名不产生链接——全站链接经校验
  均指向真实存在的页面（无 404）。个别极端写法变体（如 四ッ谷）若索引缺失会被
  过滤，属源数据覆盖限制。

## 页面内容（信息量与内链）

每个页面除了三语名称 / JSON-LD / canonical / OG，还内置：

- **车站页**：途经线路明细表（线路色、类型、运营方、本站位置）、沿轨道方向的前后站、
  其他相邻车站、同名站消歧链接、基本信息表（含途经线路数、经纬度）、顶部导航
  （实时地图 / 全部线路 / 全部车站）+ 底部回链 + 地图深链按钮 + 三语语言切换；
- **线路页**：线路信息表（线路色、类型、运营方、车站数、沿线两端、约长公里数、
  途经都道府县）、沿线换乘枢纽（该线上与别线交汇的车站及可换乘线路）、
  沿轨道顺序的途经车站（每站附中文名 + 地图深链）、同类线路推荐、顶部导航 + 底部回链 + 地图深链；
- **一览页**：按类型 / 按都道府县分组，顶部「打开实时运行地图」主 CTA。

> 说明：线路长度由轨道折线的站间大圆距离累加估算（去重边），环线等曲线线路
> 会比实际里程偏低，属估算口径；所有主站回链均用 `#mjr3d=` 深链，点开即定位到对应站 / 线。

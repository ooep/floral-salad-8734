# 性能架构与优化记录(PERF)

> 2026-10-24/25 十轮性能优化(实测驱动)的机制沉淀。**改渲染管线/列车绘制前必读** ——
> 下列机制互相咬合,单独改一处很容易破坏其它轮次的假设。

## 实测基线(2026-10-25,凌晨/正午拨钟,MessageChannel 基准)

| 场景 | 优化前 | 优化后 |
|---|---|---|
| 全国(z3.4)空闲常驻 | 20fps 全量重绘 + 每帧 8.5ms 扫描 | 4fps 渲染 + 每分钟 1 次扫描 |
| 全国拖动 | 每帧重建(8.5ms,60fps 下占半核) | 纯平移免重建(重建 1/15) |
| 全国缩放 | 每帧 8.5ms 扫描 | 0 次(缓存命中) |
| 城市(z14)空闲·正午 | 每帧 4.32ms(9402 顶点全写) | 1.69ms(视口外免写) |
| 城市·凌晨 | 每帧 3.45ms(网格全扫) | 0.01ms(扫描缓存) |
| 启动 | ~90MB + 3 次大 JSON 冻结 | 懒加载省 65MB + HTTP/IDB 5min 新鲜度 |
| 拾取(悬停/点击) | 每车一次 map.project | 局部雅可比(千倍加速) |

## 渲染管线(tick → updateTrains → trains-gl)

### 1. 重建率自适应(帧步长)

```
纯平移(z<5,zoom 未变,无渐变/跟随/拖动)   → 免重建,仅 4fps 补帧(panOnly)
淡入淡出进行中(anyFading)                → 15fps(保 260ms 渐变平滑)
静态:z<5 → 4fps / z5-8 → 10fps / z≥8 → 30fps
交互(viewDirty+zoomMoved)/跟随/拖动时间轴 → 全帧
```

**不变量**:列车顶点是世界坐标 + 屏幕尺寸按 zoom 烘焙(`a_corner` × L/W)——
纯平移/旋转只由相机矩阵变换;**zoom 变化必须重建**(尺寸/等级门依赖 zoom)。
跳过帧的渲染输出与上一帧逐像素相同,故 `triggerRepaint` 仅在重建帧调度
(交互/瓦片加载帧 MapLibre 自行渲染)。

### 2. 阶段 1 扫描缓存(scanStamp 系列)

eligible 集合只取决于 `[整数分钟, 等级门, 视口矩形(z≥5), 纯线模式, 数据档]`。
缓存命中时跳过 8.2ms 全量扫描(86,085 班次)。**5s TTL 兜底**班次起终点分钟边界
(出现/消失最多迟 5s)。缓存帧 `fadeStamp` 不递增(`_ok/_fm` 语义依赖此约定);
阶段 3 的 M2 每帧重算(缓存的 `t._M2` 是扫描期旧值,禁止用于插值)。
跟随/详情强制环在缓存外**每帧**执行(≤2 辆)。

### 3. 视口外免写(阶段 3)

bbox 级 eligible 含大量「线路穿过视口但车在远处」的班次(正午 z14 東京实测
合格 9402 ≈ 屏内 ~500 的 19 倍)。解算位置在扫描视口矩形(换算成经纬度)之外 →
跳过顶点写出/颜色/图标/M3D 接管;班次留在 fadeList(alpha 保持),驶入缓冲
(≥14km)即恢复。z<5 无 vp 不启用(全国所有在途班次都可能入屏)。

### 4. 淡入淡出

`anyFading`(阶段 2 实时标记,含新入列班次)驱动升帧;alpha 按真实 dt 推进,
帧率无关。**FADE_MS=260 内改动画时长需同步检查 anyFading 升帧档(4 → 15fps)。**

### 5. 拾取(局部雅可比)

一次 pick 仅 4 次投影变换标定局部线性系数,列车用经纬度差×系数求屏幕距。
globe 模式拾取半径(10-14px)内误差 ~0.2px。**勿改回逐车 map.project**
(全国视图 9000 车/次 × 16 次/s,与渲染争抢主线程)。

## 加载与缓存

- **懒加载**:ORM 股道 44MB(`bindLazyHeavyData`,z≥11.5 延迟 3s 触发/开关)、
  站房三件套 14MB(同触发)、`platform_map.json` 3.3MB(dataReady 后 4s)。
  触发回调自续重试(深链冷缓存场景),多条链幂等。
- **HTTP 缓存**(build_static_assets.py `_headers`):数据 JSON/GeoJSON/JS 5min
  浏览器缓存;徽章图集 `sha256/*.webp` 内容寻址 → 1y immutable。
- **IDB 新鲜度**:`fetchJSONWithCache` 的 `t0` 与服务端 5min 对齐 —— 窗口内零网络
  零解析;**勿删除**(否则浏览器缓存 200 走全量重解析,反而劣化)。
- 图集:default 启动即载(加载拼图),vector/cute 首次切换懒加载(`ensureAtlas`)。
- Clarity 延后 dataReady+4s;maplibre CSS 非阻塞(preload+onload);line_icons.js defer。

## 设备分层

`__PERF_LOW`(软渲染/低端):全套降载 + 4fps 起步。
`__PERF_MID`(桌面 3-4 核):pixelRatio ≤1.5 + crossSourceCollisions:false +
prefetchZoomDelta 1。高端:无任何画质牺牲。

## 已知取舍(未做,需产品决策)

1. 玻璃面板 backdrop-filter blur(26px)→16px:面板 GPU 重模糊减半,玻璃感略薄
2. 中端档关 MSAA:降温明显,细线条略糙
3. ORM 细轨层加 minzoom(z9 以下回退官方线):低 zoom GPU 大减,改变「全量股道」观感

## 复测方法

测试副本 = `sed` 改 jr-static → 本地相对路径 + rAF/`yieldToUI` 换 MessageChannel
(绕过环境定时器钳制)+ 暴露 `window.__prof`。基准:`P.updateTrains(P.curMin(), 16)`
× 100-300 次取均值(**必须预热,首轮 JIT 冷启动数字是噪声**),拨钟
(`cSlider.value=720 + input 事件`)测正午峰值。部署包:仓库根 `perf-patches/`。

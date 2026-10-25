#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_static_assets.py — 组装 jr-static Worker 的静态资产目录

从仓库源目录合并出 static-worker/assets/：
  /data/*            <- 根站 data/ + mini-japanrail-3d/data/ 合并（唯一冲突 train_icons_atlas.png
                        根站版落入 /data/quest/ 供 index-quest 使用）
  /logos/*           <- mini-japanrail-3d/logos/
  /seo/img/*         <- mini-japanrail-3d/seo/img/
  /segments.geojson  <- 根站 segments.geojson
  /*.png 图标         <- mini-japanrail-3d/ 根级图标（与根站同名文件内容一致，一份即可）

用法：python3 scripts/build_static_assets.py [--out DIR]
输出后打印文件数与总大小用于验证。
"""
import os, shutil, sys, argparse, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINI = os.path.join(REPO, 'mini-japanrail-3d')
ROOT_DATA = os.path.join(REPO, 'data')

# 根级图标（mini 与根站同名文件 md5 一致，共用一份）
ROOT_ICONS = [
    'apple-touch-icon.png', 'favicon.png', 'favicon-dark.png',
    'icon-192.png', 'icon-512.png', 'icon.png', 'icon-dark.png',
    'logo.png', 'logo-dark.png', 'og-image.png',
]


def copy_tree(src, dst, skip_names=(), skip_dirs=()):
    """递归复制目录树（保留相对结构）。返回复制文件数。"""
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = os.path.relpath(root, src)
        target = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            if f in skip_names and rel == '.':
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(target, f))
            n += 1
    return n


# 配线图仅内联进 SEO 静态页，不随 Worker 分发（避免 100MB+ 冗余上传）
SKIP_DIRS = ('wiki_trackdiagrams', 'line_bsdiagrams')
SKIP_NAMES = ('wiki_trackdiagrams.json', 'line_bsdiagrams.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(REPO, 'static-worker', 'assets'))
    args = ap.parse_args()
    out = args.out

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    total = 0

    # 1) data/ —— 合并
    d = os.path.join(out, 'data')
    os.makedirs(d, exist_ok=True)
    n1 = copy_tree(ROOT_DATA, d, skip_names=('train_icons_atlas.png',))
    n2 = copy_tree(os.path.join(MINI, 'data'), d, skip_names=SKIP_NAMES, skip_dirs=SKIP_DIRS)
    # 根站版图集 → /data/quest/（index-quest.html 专用，布局与 mini 版不同）
    quest = os.path.join(d, 'quest')
    os.makedirs(quest, exist_ok=True)
    shutil.copy2(os.path.join(ROOT_DATA, 'train_icons_atlas.png'), os.path.join(quest, 'train_icons_atlas.png'))
    total += n1 + n2 + 1
    print('[data] root=%d mini=%d (+quest atlas)' % (n1, n2))

    # 2) logos/
    n = copy_tree(os.path.join(MINI, 'logos'), os.path.join(out, 'logos'))
    total += n
    print('[logos] %d' % n)

    # 3) seo/img/
    n = copy_tree(os.path.join(MINI, 'seo', 'img'), os.path.join(out, 'seo', 'img'))
    total += n
    print('[seo/img] %d' % n)

    # 4) segments.geojson（根站）
    seg_src = os.path.join(REPO, 'segments.geojson')
    if os.path.exists(seg_src):  # 稀疏镜像缺省跳过(CI 全量 checkout 恒存在)
        shutil.copy2(seg_src, os.path.join(out, 'segments.geojson'))
        total += 1
        print('[segments.geojson] 1')
    else:
        print('[segments.geojson] SKIP (sparse mirror)')

    # 5) 根级图标
    n = 0
    for ic in ROOT_ICONS:
        s = os.path.join(MINI, ic)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(out, ic))
            n += 1
    total += n
    print('[icons] %d' % n)

    # 5.2) badges/ —— 车站徽章（DokoRail 迁移：123 图集 webp + 11 官方 SVG + map.json）
    #      徽章按站名映射到图集裁剪坐标，前端运行时裁剪注册为 MapLibre icon；
    #      无专属徽章的站由前端文字徽章兜底（与 DokoRail 三级体系一致）。
    badges_src = os.path.join(MINI, 'data', 'badges')
    if os.path.isdir(badges_src):
        n = copy_tree(badges_src, os.path.join(out, 'data', 'badges'))
        total += n
        print('[badges] %d' % n)
    else:
        print('[badges] SKIP (not present)')

    # 5.3) platform_map.json —— 站台编号（DokoRail 迁移：9372 线路车站 pw 数据，
    #      按 tmap 站序对齐，列车详情「停靠站」显示 Plat. 1/2/3 徽章，车站「信息」tab 显示各线路站台参考）。
    plat_src = os.path.join(MINI, 'data', 'platform_map.json')
    if os.path.isfile(plat_src):
        shutil.copy2(plat_src, os.path.join(out, 'data', 'platform_map.json'))
        total += 1
        print('[platform_map] copied')
    else:
        print('[platform_map] SKIP (not present)')

    # 5.4) vendor/ —— 核心库自托管（maplibre-gl 6.12）
    #      依赖 jsdelivr 等外部 CDN 在部分网络不可达，自托管到 jr-static 保证页面可加载。
    vendor_src = os.path.join(MINI, 'vendor')
    if os.path.isdir(vendor_src):
        n = copy_tree(vendor_src, os.path.join(out, 'vendor'))
        total += n
        print('[vendor] %d' % n)
    else:
        print('[vendor] SKIP (not present)')

    # 5.5) models/ —— 列车真实外型 3D 模型（DokoRail 迁移：consist.json + glb + ktx2/textures.bin，
    #      按车型目录整体复制；首批 7 车型，后续按需增量）
    models_src = os.path.join(MINI, 'models')
    if os.path.isdir(models_src):
        n = copy_tree(models_src, os.path.join(out, 'models'))
        # 可用车型清单:前端据此跳过未同步车型(免 404 风暴)
        _dirs = sorted(x for x in os.listdir(models_src) if os.path.isdir(os.path.join(models_src, x)))
        with open(os.path.join(out, 'models', 'index.json'), 'w', encoding='utf-8') as f:
            json.dump({'models': _dirs, 'v': 1}, f, ensure_ascii=False)
        total += n + 1
        print('[models] %d (+index.json %d types)' % (n, len(_dirs)))
    else:
        print('[models] SKIP (not present)')

    # 5.6) basis/ —— Basis/KTX2 转码器（three KTX2Loader 解压模型贴图用）
    basis_src = os.path.join(MINI, 'basis')
    if os.path.isdir(basis_src):
        n = copy_tree(basis_src, os.path.join(out, 'basis'))
        total += n
        print('[basis] %d' % n)
    else:
        print('[basis] SKIP (not present)')

    # 6) _headers —— Workers Static Assets 边缘直服(不经过 fetch handler)时注入 CORS，
    #    保证浏览器 crossOrigin='anonymous' 加载图集/图标不污染 canvas（toDataURL/texImage2D 可用）。
    #    注意：此文件必须由脚本生成；rmtree 重建 assets 时手工文件会被清掉。
    headers_file = os.path.join(out, '_headers')
    with open(headers_file, 'w', encoding='utf-8') as f:
        f.write('/*\n')
        f.write('  Access-Control-Allow-Origin: *\n')
        f.write('  Access-Control-Expose-Headers: ETag, Last-Modified, Content-Length, Content-Type\n')
        # HTTP 缓存策略(性能,2026-10-25):此前全部资产 max-age=0 must-revalidate(平台默认),
        # 每次启动 ~15 个数据文件逐个条件请求,慢网络下 RTT 累积拖慢 boot。
        #  - 数据 JSON/GeoJSON:5 分钟浏览器缓存 —— 数据集按日/周刷新,5 分钟陈旧无感;
        #    5 分钟内重复启动零网络请求,超时后照旧走 ETag/304 增量验证
        #  - 徽章图集:文件名即内容 sha256(内容寻址,永不变化)→ 缓存 1 年 + immutable
        f.write('/data/*.json\n')
        f.write('  Cache-Control: public, max-age=300\n')
        f.write('/data/*.geojson\n')
        f.write('  Cache-Control: public, max-age=300\n')
        f.write('/data/*.js\n')
        f.write('  Cache-Control: public, max-age=300\n')
        # 3D 模型(2026-10-25 十七轮):/models/<车型>/ 下 consist.json+glb+ktx2+bin,
        # 打开查看器一次拉几十个文件,此前平台默认逐个条件请求(RTT 累积);
        # 5 分钟内重复打开零网络。/basis/ 为 KTX2 转码器(会话内一次)同策略。
        # 资产按目录整体刷新(model_map v 递增),5 分钟陈旧窗口与数据一致可接受
        f.write('/models/*\n')
        f.write('  Cache-Control: public, max-age=300\n')
        f.write('/basis/*\n')
        f.write('  Cache-Control: public, max-age=300\n')
        f.write('/data/badges/atlas/sha256/*\n')
        f.write('  Cache-Control: public, max-age=31536000, immutable\n')
    total += 1
    print('[_headers] 1 (CORS + data 5min cache + badge-atlas 1y immutable)')

    # 7) robots.txt / healthz —— 纯资产模式(无 Worker 脚本)下改为真实静态文件，
    #    由平台直接服务，同样不触发 Worker 调用。
    with open(os.path.join(out, 'robots.txt'), 'w', encoding='utf-8') as f:
        f.write('User-agent: *\nDisallow: /\n')
    with open(os.path.join(out, 'healthz'), 'w', encoding='utf-8') as f:
        f.write('ok\n')
    total += 2
    print('[robots.txt / healthz] 2 (static files)')

    # 汇总
    size = 0
    for root, _dirs, files in os.walk(out):
        for f in files:
            size += os.path.getsize(os.path.join(root, f))
    print('TOTAL: %d files, %.1f MB -> %s' % (total, size / 1048576, out))
    if total == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()

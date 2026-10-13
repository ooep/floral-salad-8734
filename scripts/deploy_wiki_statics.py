#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 ooep/eki-wiki 与 ooep/ressha-wiki 两个车站/列车百科仓库拉取为「纯静态资产」并部署。

为什么是纯静态（零计费）：
  - 部署模式为 Workers Static Assets「仅资产」：wrangler.toml 只有 [assets]，
    没有任何 main / 脚本。所有资产请求、404、robots 都由 CDN 边缘直服，
    不触发 Worker 执行 → 不产生调用计费。
  - CORS 由 assets 根 _headers 提供（平台边缘层应用，同样零 Worker 调用）。

用法（环境变量: CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID）：
  python3 scripts/deploy_wiki_statics.py            # 全量同步两域
  python3 scripts/deploy_wiki_statics.py eki-wiki   # 只同步 eki-wiki

每次主仓 push 时 CI 都会跑一遍；wrangler 按内容哈希去重，
仓库未变化时秒级跳过，变化时只上传新增/变更文件。
"""
import os
import sys
import subprocess
import tarfile
import tempfile
import urllib.request
import shutil

REPOS = {
    "eki-wiki": "https://codeload.github.com/ooep/eki-wiki/tar.gz/refs/heads/main",
    "ressha-wiki": "https://codeload.github.com/ooep/ressha-wiki/tar.gz/refs/heads/main",
}

HEADERS = """/*
  Access-Control-Allow-Origin: *
  Access-Control-Allow-Methods: GET, OPTIONS
  Access-Control-Allow-Headers: *
  Access-Control-Max-Age: 86400
  Access-Control-Expose-Headers: ETag, Last-Modified, Content-Length, Content-Type
"""

ROBOTS = "User-agent: *\nDisallow: /\n"


def download(url: str, dest: str) -> None:
    print(f"[*] 下载 {url}")
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:
        print(f"[!] 下载失败: {e}")
        raise
    size = os.path.getsize(dest) / 1048576
    print(f"[+] tarball {size:.1f} MB")


def assemble(worker: str, tar: str, workdir: str) -> str:
    assets = os.path.join(workdir, worker, "assets")
    os.makedirs(assets, exist_ok=True)
    with tarfile.open(tar, "r:gz") as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) == 2 and parts[1] == "data":
                pass
            if "/data/" in m.name or m.name.endswith("/data"):
                rel = m.name.split("/data", 1)[1].lstrip("/")
                if rel == "":
                    continue
                dst = os.path.join(assets, "data", rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if m.isdir():
                    os.makedirs(dst, exist_ok=True)
                else:
                    src = t.extractfile(m)
                    if src:
                        with open(dst, "wb") as f:
                            shutil.copyfileobj(src, f)
    with open(os.path.join(assets, "_headers"), "w", encoding="utf-8") as f:
        f.write(HEADERS)
    with open(os.path.join(assets, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(ROBOTS)
    n = sum(1 for _ in os.walk(assets) for _ in _[2])
    size = sum(os.path.getsize(os.path.join(r, n2)) for r, _, fs in os.walk(assets) for n2 in fs)
    print(f"[+] {worker} 资产: {n} 文件 / {size/1048576:.1f} MB (含 _headers + robots.txt)")
    return assets


def deploy(worker: str, assets: str, workdir: str) -> None:
    cfg = os.path.join(workdir, worker, "wrangler.toml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(
            f'# {worker} — 纯静态资产（无 Worker 脚本，零计费）\n'
            f'name = "{worker}"\n'
            f'compatibility_date = "2026-10-13"\n\n'
            f'[assets]\ndirectory = "{assets}"\nnot_found_handling = "404-page"\n'
        )
    print(f"[*] 部署 {worker}（纯静态，无脚本）...")
    r = subprocess.run(
        ["npx", "wrangler@4", "deploy", "--config", cfg],
        capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(out[-1200:])
    if r.returncode != 0:
        raise SystemExit(f"[!] {worker} 部署失败 (exit {r.returncode})")
    print(f"[+] {worker} 部署完成")


def main() -> None:
    targets = sys.argv[1:] or list(REPOS)
    with tempfile.TemporaryDirectory(prefix="wiki-static-") as workdir:
        for worker in targets:
            if worker not in REPOS:
                print(f"[!] 未知 worker: {worker}（可选: {list(REPOS)}）")
                continue
            tar = os.path.join(workdir, f"{worker}.tgz")
            download(REPOS[worker], tar)
            assets = assemble(worker, tar, workdir)
            deploy(worker, assets, workdir)
    print("全部完成")


if __name__ == "__main__":
    main()

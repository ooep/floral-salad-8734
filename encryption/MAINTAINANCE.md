# encryption/ — 维护手册（读这一份即可，不依赖任何聊天记录）

本仓所有**具备外部抓取能力**的脚本「入库即密文」：仓库里只有
`encrypted/<随机16hex>.enc` 与 `encryption/manifest.tsv`，真实路径与源码都在密文内。
机制与 ooep/delay、ooep/jr-comfortable 完全一致（OOEP02 信封，见 `ooep_crypto.py` 头部注释）。

## 形状

| 文件 | 作用 |
|---|---|
| `encrypted/*.enc` | 密文 blob（文件名=随机 blob_id，与路径无关） |
| `encryption/manifest.tsv` | blob_id + sha256(密文) + HMAC(明文) + 版本 + 路径集合承诺（不含路径） |
| `encryption/ooep_crypto.py` | 加密核心（纯标准库：scrypt + AES-256-GCM，含 NIST 自检向量） |
| `encryption/encrypt.py` | 本地加密工具（明文目录 → 密文 + 清单，原子重建） |
| `encryption/decrypt.py` | CI 解密/校验/清理（先验后写：全量校验通过前零落盘） |
| `encryption/prep.sh` | CI 解密入口：`prep.sh 1`=verify-only；`prep.sh 2`=物化明文 |
| `encryption/finalize.sh` | CI 常开收尾：clean + 断言工作区干净（残留即 exit 9） |
| `encryption/logrun.sh` | 日志出口：业务输出经 `shellredact.py` 脱敏（URL/域名/密钥 → 占位符） |

钥匙：GitHub Secret **CODE_KEY**，workflow 里以 `OOEP_PASSPHRASE` 环境变量注入，
**绝不写入任何文件**。`workflow YAML 本身无法加密`（GitHub 只从明文 YAML 调度），
所以步骤名/调度是公开的，藏住的是抓取脚本本体（端点、限速、参数、逻辑）。

## 日常维护：改一处抓取逻辑并重新上线

```bash
# 0) 钥匙只走环境变量（当前会话），不落盘
export OOEP_PASSPHRASE='<CODE_KEY 的值>'

# 1) 解出全部明文到临时目录（仓库工作区保持干净）
python3 encryption/decrypt.py decrypt --enc encrypted \
  --manifest encryption/manifest.tsv --out /tmp/maint

# 2) 在 /tmp/maint 里修改目标脚本（路径即仓库内相对路径）
$EDITOR /tmp/maint/scripts/fetch_timetables.py

# 3) 重新加密（整树原子重建：新随机 blob_id + 新清单，旧密文整体作废）
rm -rf encrypted && mkdir encrypted
python3 encryption/encrypt.py --src /tmp/maint --out encrypted \
  --manifest encryption/manifest.tsv

# 4) 本地自检：全量校验 + 往返一致
python3 encryption/decrypt.py decrypt --verify-only --enc encrypted \
  --manifest encryption/manifest.tsv --out .          # 期望: OK n=<文件数>
python3 encryption/decrypt.py decrypt --enc encrypted \
  --manifest encryption/manifest.tsv --out /tmp/rt
diff -r /tmp/maint /tmp/rt && echo ROUNDTRIP-OK      # 期望: 逐字节一致

# 5) 明文不留痕
python3 encryption/decrypt.py clean --out /tmp/rt
rm -rf /tmp/maint /tmp/rt

# 6) 提交（密文与清单必须同一提交；不要提交任何明文脚本）
git add encrypted encryption/manifest.tsv
git status   # 确认没有明文 .py/.sh 混入
git commit -m "chore(enc): update fetcher logic"
git push      # 禁 force；推前 git fetch 核对 head，落后则 rebase
```

## 还原（解密回明文）

```bash
export OOEP_PASSPHRASE='<CODE_KEY 的值>'
python3 encryption/decrypt.py decrypt --enc encrypted \
  --manifest encryption/manifest.tsv --out /tmp/restore
# /tmp/restore 内即加密前逐字节一致的明文（可用 sha256 对照验证）
```

## 故障定位（rescue）

| 症状 | 定位方法 |
|---|---|
| `E2 no key` | CODE_KEY 未注入/为空：检查仓库 Settings→Secrets 是否有 CODE_KEY |
| `E3 integrity check failed` | 钥匙不对，或密文被改动（GCM tag 失败） |
| `E6 ciphertext set mismatch` | encrypted/ 里的 .enc 集合与清单不一致：有人单独增删了密文却没重建清单 → 按上文「重新加密」整体重建 |
| `E8 ciphertext checksum mismatch` | 清单给出的是**哪一个 blob_id** 出错 → `encrypted/<blob_id>.enc` 就是坏文件；解密该 blob 可定位到具体路径（`decrypt.py --verbose` 仅本地用） |
| `E8 plaintext mac mismatch` | 密文完好但明文承诺不符 = 清单被改 → 整体重建 |
| `E8 path set commitment mismatch` | 密文集合里的路径集合与清单承诺不符 → 整体重建 |
| 钥匙丢了 | 密文不可恢复（scrypt+GCM，无后门）。唯一途径：从本地/备份拿到明文源码，用新钥匙整体重新加密；同时轮换所有仓的 CODE_KEY（三仓共用一把钥匙，一漏全换） |

## CI 失败语义（与 delay 一致，勿改）

无键 → exit 2（E2）；空键/错键/缺清单/密文损坏 → exit 3（E2/E3/E5/E8），
且**零文件落盘**（先验后写契约）。`finalize.sh` 发现工作区有残留 → exit 9。

## 本仓密文覆盖范围（2026-11-05 接入时）

17 个文件：`ci/step.sh`（业务步骤分发器，workflow 只写 `ci/step.sh <stage> <号>`，
业务文件名/端点不进 YAML 与日志）、`scripts/{fetch_timetables,fetch_ra_geometry,
build_tmaps,deploy_wiki_statics,line_regression_check,build_platform_map_online}.py`、
`scripts/fetch_track_diagrams.sh`（deploy.yml 配线图拉取块抽出）、
`mini-japanrail-3d/seo/{fetch_wiki_trackdiagrams{,_v2,_v3,_v4,_v7,_v8},
fetch_bs_diagrams,probe_bs,probe_wiki}.py`。
离线脚本（build_trains / sync_mini_3d / build_seo_static / build_tt_shards 等）
与全部 workflow YAML 保持明文。

`ci/step.sh` 的 stage 对照：refresh=周更时刻表链（3 抓时刻表/4 tmaps ensure/5 官方几何）、
deploy=部署链（3 配线图拉取/4 wiki 静态部署）、tdv1/tdv2/tdv4/tdv6/tdv8=配线图抓取、
probebs/probewiki=结构探测。新增抓取脚本时：放进明文源树 → 按上文流程整体重加密。

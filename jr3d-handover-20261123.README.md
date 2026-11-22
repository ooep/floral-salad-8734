# jr3d 交接包 2026-11-23（handover package）

这是 jr.suki.ing 3D 列车模型补全任务的交接包，2026-11-23 打包，取代 2026-11-22 的旧包。
目标：另一个 AI 只读这个仓库就能接着做。

## 包里有什么

- `HANDOFF.md`——总交接（v2，入口，先读它）
- `skill/`——「图纸转 3D 模型」skill v1.2.5（含全部累积经验 + scripts 内核）
- `pipeline/`——推送器原版 `push_model.py` + Linux 适配版 `push_linux.py`
- `docs/` / `lines/` / `data/`——原包内容原样；`data/current/` 是 2026-11-23 01:40 从远端拉的最新 index/map 快照（参考用）
- `staging/`——63 个车型的当前产物快照（GLB + consist.json + verify/ + audit/ + backup_*）
- `verify/` / `templates/`——原包验收对照图与派发提示词模板
- `reports/`——本会话全部报告（各车型/选型/返工/修注册/派发-待办）+ `注意事项.md`（长期规则精简版）+ `screenshots/`（各车型截图汇总）

## 快照时点状态（2026-11-23 01:40 CST，带认证 API 核实）

- 分支 models-pipeline head：`cfd801c1655658c78d3f77f4b3793aaf889a8f04`
- index：180 个模型；map：318 条线
- **快照时在建/返工中（包内是中间态）**：第七批建模中 5 辆（manyosen-mlrv1000、keihan-600、saitama-2020、hankyu-8000、utsunomiya-hu300）；返工中 5 辆（tokyu-7000、kintetsu-16000、meitetsu-300、yuirail-1000、tamamono-1000）。快照之后完成的模型不在本包里，见 `reports/派发-待办.md`（派发状态的权威记录）。
- 本 commit **没有动** `mini-japanrail-3d/models/index.json` 与 `mini-japanrail-3d/data/model_map.json`（推后核实两者内容未变）。

## 合并分卷

GitHub 单文件限 100MB，本包 272,417,506 字节，切成 7 个分卷（每卷 ≤40MB——实测 git blobs API 拒收 50MB 的 blob，40MB 可行）：

| 分卷 | 大小（字节） | sha256 |
|---|---|---|
| jr3d-handover-20261123.z01 | 41,943,040 | 2dcaff94f0f06ba673f3d55603f2d87345bb3b60b903abf52a68d24788d2038f |
| jr3d-handover-20261123.z02 | 41,943,040 | d42b28e60b00cada276dfbc30284282f75e211d155e444e355f5494f2d0299e0 |
| jr3d-handover-20261123.z03 | 41,943,040 | acc78184d62e54f7e29cc32c643f2467e1b0520e01614ba6138aeedc07091cb4 |
| jr3d-handover-20261123.z04 | 41,943,040 | 6e8d0ab3156ca1b515925da91f8e5066b225ad548582a80c8b86946ee6c24200 |
| jr3d-handover-20261123.z05 | 41,943,040 | 9239052260d1e79a0d254eb826bb2932a279f01a97b25a269428e2c293448547 |
| jr3d-handover-20261123.z06 | 41,943,040 | 41d7744a01aa4fbc33fac161b8a349344432cdc6c95b9e9e91109f4c90662f0a |
| jr3d-handover-20261123.zip | 20,759,270 | a80e3d855b943849f19634a7bf1a8ce46c497a29e6bdfc466d2f0efedb17bb31 |

合并方法（任选一种）：

```bash
# 方法 A（标准）：拼回单个 zip 再解压
cat jr3d-handover-20261123.z* > jr3d-handover-20261123.zip
unzip jr3d-handover-20261123.zip
```

```bash
# 方法 B（Linux 上 Info-ZIP unzip 抱怨 multi-part 时用）：先修复再解压
zip -FF jr3d-handover-20261123.zip --out jr3d-handover-20261123-fixed.zip
unzip jr3d-handover-20261123-fixed.zip
```

合并后的单个 zip：272,417,506 字节，sha256
`c5f31c0fa6b20ede86dfc4e7c3bb976eef5ae43cc406636635428b762f373b37`
（`cat` 拼出的文件会比它多 4 字节——分卷首部的 spanning signature，属正常现象；`zip -FF` 修复后与上述 sha256 一致。）

解压后得到目录 `jr3d-handover-20261123/`，入口是其中的 `HANDOFF.md`。

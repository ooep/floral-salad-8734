# 多会话协作规则(COLLABORATION)

> **2026-10-25 起 MC 规定:所有会话(人与 AI)推送 main 前必须遵守本规则,无例外。**

## 背景

2026-10-25 事故:两个并行会话各自持有克隆,后推送的一方携带的 `mini-japanrail-3d/index.html`
快照不含先推送方的改动,整文件覆盖导致已上线的**二至十八轮性能优化全部丢失**(十九轮幸存)。
详见 `mini-japanrail-3d/PERF.md`。

## 规则(强制)

1. **推送前必须同步**:每次 `git push` 前先 `git fetch origin && git rebase origin/main`;
   有冲突先解决(保留双方改动,禁止用「恢复旧版本」的方式解冲突)。
2. **禁止 force push** main(会抹掉其他会话已推送的工作)。
3. **小步快推**:完成一个独立改动就推,不要攒大批改动(减少冲突面与覆盖窗口)。
4. **改前先拉**:开工前先同步一次,别基于旧快照开发。

## 技术护栏(已部署)

两个克隆 `.git/hooks/pre-push` 已安装「Collaboration Guard」:
- 推送 `refs/heads/main` 时自动 `fetch origin main` 并校验本地是否为远端后代;
- 远端已前进 → **拒绝推送**,提示执行 fetch + rebase;
- 新建分支/删除分支不拦截;force push 因服务端 denyNonFastForwards 与本钩子双重阻断。

> 钩子被绕过(如 `--no-verify`)造成覆盖的,按事故处理:找回被覆盖提交并重放,
> 且该会话需要向 MC 说明原因。

## 恢复流程(万一再被覆盖)

```bash
# 1. 找覆盖点:对关键标记做存在性巡检(下例为性能轮次标记)
git show origin/main:mini-japanrail-3d/index.html | grep -c "wRect\|scanStamp\|anyFading"
# 2. 定位覆盖提交
git log --oneline --all -S "wRect" -- mini-japanrail-3d/index.html
# 3. 按序重放丢失的提交(在最新远端之上)
git cherry-pick <丢失的提交...>   # 冲突时保留双方改动
# 4. 全量标记验证后推送(钩子会再做一次同步校验)
```

各轮次标记清单见 `mini-japanrail-3d/PERF.md`。

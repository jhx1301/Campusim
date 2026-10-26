# 通过 GitHub 迁移快照 baseline 训练

更新：2026-10-26。代码和小数据通过 GitHub 同步；被忽略的校准证据和 Python 环境单独传输。新电脑应使用 Windows x64，以复用当前环境和锚点。

## 代码与数据

克隆 `https://github.com/jhx1301/Campusim.git` 的 `feature/control-protocol-v1` 分支，并固定到本次迁移提交。所有命令从仓库根目录执行。仓库的 `.gitattributes` 保留模型源码、JSON配置和UW数据的实际字节，避免 Git 自动转换换行使锚点失效。

随 Git 同步的数据：

- `data/uw_madison_2020_w1.csv` 和对应 `.provenance.json`。
- `data/uw_madison_2020_replay.csv`、对应 `.provenance.json` 和 `.sources.json`。

人口和接触网络由代码生成，不另需个体数据。正式配置是 `docs/baseline_snapshot_training_v1.json`，库路径为相对路径 `results/snapshot_baseline_v1/library`。正式库尚未生成：128 train + 9 val + 20 test + 4 pilot，共161世界、四日期644快照；val36按世界排序均分容量组。

## 单独复制的文件

`results/` 被 Git 忽略。必须完整复制 `results/e0_v5_iso0_w1trace/weekly_background_v1_local/`（约4 MiB），恢复到新仓库相同相对位置，保留以下10个文件的原始字节：

```text
control_anchor.json
source_control_anchor.json
config.json
manifest.json
summary.json
migration.json
worlds_scan.jsonl
worlds_fit.jsonl
worlds_evaluation.jsonl
worlds_migration.jsonl
```

锚点β=0.038583333332；不能只复制锚点文件。可选复制 `results/uw2020_fit_v3/final_c05r28/` 和 `results/snapshot_bootstrap_diagnostics_v2/` 以保留研究和短训练记录。旧验收快照、旧模型、其他历史results及本地代理配置不属于必需迁移数据。

## Python环境

推荐用 `conda-pack` 打包当前 `E:\pytroch\anaconda3\envs\simulation`，在新电脑解压并运行其中的 `Scripts/conda-unpack.exe`。项目和环境可以换盘符。当前已验收环境为：

```text
Python sys.version:
3.10.20 | packaged by Anaconda, Inc. | (main, Mar 11 2026, 17:42:35) [MSC v.1942 64 bit (AMD64)]

numpy==2.2.6
scipy==1.15.3
pandas==2.3.3
numba==0.65.1
sciris==3.2.9
torch==2.13.0 (CPU)
stable-baselines3==2.9.0
sb3-contrib==2.9.0
gymnasium==1.4.0
cloudpickle==3.1.2
psutil==7.2.2
```

这是实际运行版本清单，不是可独立安装的完整环境锁。锚点严格比较完整Python构建信息和前五个科学计算包版本。`requirements-control-rl-v1.in` 及其lock保留的是历史环境，不能用来代替当前实际环境；不要升级依赖、修改锚点哈希或绕过验证来完成迁移。

## 新电脑接续

只做数据和锚点加载的迁移完整性核对，不追加测试或短训练。训练入口和现有用法见[使用说明](baseline_snapshot_training.md)。真实人口新版197维、γ=1、H112截断Bootstrap的PPO256步／DDQN513步已完成真实更新和权重往返；本次短训练未见数值膨胀，但不证明长期稳定性。

**正式执行计划中的以下改造尚未实现：** snapshots／pilot／evaluate／tune的多worker调度、不同Seed独立训练入口、每2048步checkpoint的最大|V|／|Q|诊断日志。现有snapshots仍串行并共写manifest，评估池固定单worker，三个训练Seed仍轮流推进，不能直接并行运行快照写入任务。

先完成这些调度和日志改造，再根据新电脑CPU与可用内存启动正式批次：完整快照库 → pilot及val36固定参照／Threshold32候选 → PPO／DDQN各Seed11、22、33、每Seed固定8192步。现有train命令应显式传 `--maximum-budget 8192`，省略参数可能允许预算增长到16384；不自动翻倍，不提前用test选模。

迁移不要求重做E0校准。若锚点加载失败，应核对提交版本、原始文件字节、完整证据目录及实际环境版本。

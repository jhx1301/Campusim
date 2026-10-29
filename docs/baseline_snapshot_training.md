# 快照 baseline 使用说明（精简版）

当前共同任务先恢复快照并执行7天统一基线，day7首次自主决策，控制112天，总119天。主score仅计day7–118，观察期成本单列；完整记录和控制期分别对账。历史快照可继续读取，旧立即接管任务的模型不能改名冒充新任务。下文2026-10-25/26验收记录保留为历史证据。LLM持续学习入口见[统一设计](llm_feedback_component_design.md)，比较器允许额外加入一份llm独立测试报告。

已训练的旧版快照 PPO、DDQN 和 Threshold 可直接通过下方 `evaluate --baseline` 命令在新版任务中测试，无需重新训练或改写产物。加载器只放行旧 v2“立即控制112天”到新 v3“共同观察7天＋控制112天”的变化；人口、基础模型、动作、目标和其余快照配置必须一致，动作/观察编码、权重文件及校准身份继续检查。原训练任务、112天参考时域和源码摘要保留在 manifest 的 `baseline` 中；新增 `evaluation_compatibility` 记录新评估任务摘要、119天时域和当前源码摘要。此路径允许训练与评估的整体源码摘要不同，同任务加载仍保留原有严格检查。

更新：2026-10-27。[设计与审查处理](baseline_snapshot_training_plan_v1.md)；[配置](baseline_snapshot_training_v1.json)。本页对应新配置schema `uw-snapshot-training-v3`、197维观察、train/val/test拆分；旧259维模型和旧格式快照需要重新生成，旧day0任务仍使用原入口。

跨电脑接续见[GitHub迁移说明](snapshot_training_migration.md)，其中列出了必须单独传输的校准证据、实际Python环境及已完成的调度改造。

## 生成快照

```powershell
$python = 'D:\programfile\miniconda3\envs\simulation\python.exe'
$protocol = 'docs/baseline_snapshot_training_v1.json'
$anchor = 'results/e0_v5_iso0_w1trace/weekly_background_v1_local/control_anchor.json'
$library = 'results/snapshot_baseline_v1/library'
& $python -m examples.control_v1.baselines --protocol $protocol snapshots --artifact $anchor --output $library --split train
& $python -m examples.control_v1.baselines --protocol $protocol snapshots --artifact $anchor --output $library --split val
& $python -m examples.control_v1.baselines --protocol $protocol snapshots --artifact $anchor --output $library --split test
& $python -m examples.control_v1.baselines --protocol $protocol snapshots --artifact $anchor --output $library --split pilot
```

train只运行一次，三个RL学习器共用128个历史世界。val配置 `validation_worlds=9`，即20101–20109：20101–20103使用2%容量，20104–20106使用5%，20107–20109使用10%，每个世界四日期，共36回合（val36，命令仍用 `--split val`）。test为50001–50020，生成时把split改成test。完整库共161个历史世界、644快照，正式库尚未运行。可先用 `--split val --history-seed 20101 --day 21 --day 35` 验证小批次。已有文件不会被覆盖，重复运行前需要检查哪些文件已经完成；使用新输出目录时同步配置library。

每快照有轻量JSON元数据和私有pkl状态，内部version为 `uw-snapshot-control-v1`。状态哈希只在生成时记录到 `snapshots_manifest.json`，读取不反复扫描文件计算哈希。文件缺失或版本错误直接报错。训练过滤只读取元数据中的活动感染数，不扫描大状态文件，也不把隐藏计数给策略。

`snapshots`、`pilot`、`evaluate`、`tune` 支持 `--workers N`，默认1；快照按历史世界分配spawn任务，各worker只写该世界状态，父进程独占合并manifest。同一库的不同split命令须依次执行，不能同时启动；失败后保留已完成清单和文件，应核对未登记文件后再继续，不自动覆盖或重试。生成阶段必须包含test的80份快照；完成644份后汇报耗时、磁盘体积，以及train／val／test在day49／63的零活动感染数量、分母与比例，然后停止，等明确指令再运行非RL基线。

## 调参与训练

```powershell
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
& $python -m examples.control_v1.baselines --protocol $protocol pilot --artifact $anchor --reference maximum_feasible --output results/snapshot_baseline_v1/pilot
& $python -m examples.control_v1.baselines --protocol $protocol tune --artifact $anchor --output results/snapshot_baseline_v1/threshold
& $python -m examples.control_v1.baselines --protocol $protocol evaluate --artifact $anchor --split val --reference minimum --output results/snapshot_baseline_v1/minimum_val
& $python -m examples.control_v1.baselines --protocol $protocol evaluate --artifact $anchor --split val --reference maximum_feasible --output results/snapshot_baseline_v1/maximum_feasible_val
& $python -m examples.control_v1.baselines --protocol $protocol train --artifact $anchor --method ppo --train-seed 11 --maximum-budget 8192 --output results/snapshot_baseline_v1/ppo11
& $python -m examples.control_v1.baselines --protocol $protocol train --artifact $anchor --method ddqn --train-seed 11 --maximum-budget 8192 --output results/snapshot_baseline_v1/ddqn11
```

每算法训练seed11/22/33；上例仅运行seed11，其余seed须分别指定并使用不同输出目录，可由独立进程并行执行。单seed入口固定8192步，不自动延长；`train --workers N`仅控制checkpoint验证并发。2048步一次val36，选每seed最低实际J的checkpoint；Threshold32候选直接val36选1。每个checkpoint写入 `seed-X/step-N/diagnostics.json` 和根目录 `checkpoint_diagnostics.jsonl`：PPO记录当前网络对最近rollout的最大绝对V，DDQN记录当前online网络对全部已存replay观察、所有动作的最大绝对Q，附样本量且不抽样或消耗随机流。这是已采集状态上的诊断，不是全状态空间界。原三seed联合入口仍保留，省略预算默认允许至16384；本计划不使用该默认延长。train中day49／63零活动感染快照被过滤，8192步仍是512个完整自主控制112天的回合（每回合另有7天共同观察），可能遍历保留库多轮。

pilot／固定参照／Threshold选参和RL训练是分别批准的阶段；“不使用test”指不运行test评估、不用test选模，生成快照阶段仍保留test全部快照。每阶段完成后停止，不自动进入下一阶段。

8192步基准下，checkpoint验证864回合、Threshold1152回合、固定参照72回合，共2088回合，比val72减半；加上RL训练3072回合，开发合计5160回合、577920接手后模拟日。完整账本见训练计划。新选模须使用val36重新评估，旧val72结果保留为历史记录。

自主控制H112（恢复后物理day119）为时间截断，PPO/DDQN正常bootstrap。训练日志仅按真实transition记录，汇总字段为 `step_count`、`episode_count`、`simulated_days`（含已开始控制回合的观察期）、`control_simulated_days`、`observation_positive_cost`、`positive_cost`。自动reset但未step的世界不记账。学习目标含延续价值，正式评分只计实际112天成本，报告两者区别。

## 独立测试及冻结延展

```powershell
& $python -m examples.control_v1.baselines --protocol $protocol evaluate --artifact $anchor --split test --reference minimum --output results/snapshot_baseline_v1/minimum_test
& $python -m examples.control_v1.baselines --protocol $protocol evaluate --artifact $anchor --split test --baseline results/snapshot_baseline_v1/ppo11/selected-11/artifact.json --output results/snapshot_baseline_v1/ppo11_test
& $python -m examples.control_v1.baselines --protocol $protocol evaluate --artifact $anchor --split test --execution-days 168 --baseline results/snapshot_baseline_v1/ppo11/selected-11/artifact.json --output results/snapshot_baseline_v1/ppo11_extension168
```

独立test阶段输入是9个已选策略产物：PPO三个、DDQN三个、Threshold一个，以及minimum和maximum_feasible两个固定策略定义。先各自评估480场景，生成9份报告，再比较。test480场景严格共享配对身份；不依赖LLM、memory、H升级或其他release审批。扩展须单独指定，仅允许test的140／168自主控制天（物理总147／175天），保持训练的112天归一化尺度，记录第112天活动感染，不重新训练或用结果回选模型。

收集9份H112测试 `evaluation.json` 后，用JSON文件映射方法到路径列表：ppo和ddqn各3份，threshold/minimum/maximum_feasible各1份。三个RL种子必须各出现一次。然后运行：

```powershell
& $python -m examples.control_v1.baselines --protocol $protocol compare --reports results/snapshot_baseline_v1/test_reports.json --output results/snapshot_baseline_v1/comparison
```

输出 `comparison.json` 和 `report.md`，包含day21＋5%主条件、12个日期容量条件及总体，成本及分量、第112天活动感染、零活动快照比例、相对minimum的配对差值与95%区间。聚类单位为20个历史世界，RL学习器另重采样。扩展结果单独报告，不传入H112主表。

## 实际交付与测试

`tests/test_snapshot_training.py` 验证共享池／过滤、相同磁盘快照复现、静态状态保存、无哈希加载、非法动作报错、单验证集、截断bootstrap、PPO/DDQN真实更新与保存加载、冻结延展和独立比较报告。`tools.verify_snapshot_training` 使用独立小库做真实人口工程验收：prepare、control、ppo、ddqn四阶段；后两阶段为256／513自主步，非正式预算。

历史 `results/snapshot_training_acceptance/` 属于旧方案，不能宣称已验证新的终点bootstrap或197维模型。新验证使用独立输出目录，当前版本的具体通过项与未验证范围以本轮执行记录为准。完整训练、真实480场景测试和正式比较报告尚未执行。

2026-10-25 本轮验证：合并回归889个不同测试通过；剩余1项既有测试仍断言初始感染30，而当前基础配置为100。两项spawn和一项旧memory文件替换权限故障在沙箱外补跑通过；保留原有pytest `env`警告。记录为 `results/snapshot_streamlined_tests.xml`、`snapshot_streamlined_outside_tests.xml`、`snapshot_streamlined_finish_tests.xml`。

新版快照专项21项全部通过，其中包含直接核对PPO最后reward的γV补偿、DDQN在时间截断时采用原世界terminal_observation／mask并bootstrap、两个学习器实际更新与权重往返、单验证选模和独立统计报告。真实人口已生成day21／35快照，并完成两个H112、16动作的控制回合，见 `results/snapshot_streamlined_acceptance/control/verification.json`；最终评估worker也完成一次H112回合，核对学生／员工新增感染之和、终点活动感染及零感染快照元数据，见同目录 `worker_verification.json`。本轮未重跑真实人口完整RL训练，旧长时间验收不冒充新版训练结果。

2026-10-25 后续补验：新版197维、γ=1、H112截断Bootstrap已完成69,457人口的PPO256步与DDQN513步，参数更新和权重往返均通过。总耗时分别29.33／54.90分钟（两任务同时启动）；PPO40次优化中固定returns的MSE从0.209535降至0.062240，DDQN仅2次优化、最大|Q|从0.269595变为0.262760。本次未见数值膨胀，但一个seed、一个历史世界、两个快照不足以判断长期稳定性。详见[短训练诊断报告及曲线](../results/snapshot_bootstrap_diagnostics_v2/report.md)，脚本为 `tools/diagnose_snapshot_training.py`；完整RL预算仍未执行。

# Phase 6 接口与验收记录

> 2026-10-23：本文的旧校准、人口及验收数字为历史记录。当前唯一标准和运行入口以 [UW 控制接入](uw_control_integration.md) 为准；旧结果不作为 UW 验收。

更新：2026-10-23。Phase 6 实施前基线：`feature/control-protocol-v1@1a13d9e`。

当前已接入 Threshold、MaskablePPO、DDQN、源域训练/选择与案例库发布工程。工程验证、短训练、正式源域实验和共同冻结分别登记；工程通过不表示控制收益或 Phase 7 已就绪。

当前 UW 基础模型为 69,457 人、教师 2,321 / 其他职员 21,596、`campus_k_ts=3`，尚未完成该配置的完整 E0 校准。`results/e0_v2/full/` 是旧角色模型的历史研究，不能作为当前科学运行的锚点；正式 pilot、Threshold 调参、RL 训练和建库均须等待新的兼容锚点。完整前提见 [UW 控制接入](uw_control_integration.md)。

2026-10-23 指定解释器元数据核查为 Python 3.10.20、Optuna 4.8.0、Torch 2.13.0、Gymnasium 1.4.0、SB3/contrib 2.9.0；这与旧依赖快照中的 Optuna 4.9.0 / Torch 2.14.1 不同。版本清单仅说明当前安装状态，不代表已经在该组合下重新完成 RL 运行验收；本次文档同步不安装或升级依赖。

## 1. 公共执行与私有编排

- Controller 保持 `reset()/decide(PublicObservation)/observe(PublicWeekFeedback)`；不接收 reward、seed、beta、模拟器或训练器。
- 环境继续唯一负责 reset、七日推进、合法动作解析、执行和奖励。评估复用 `run_episode(mode="evaluation")`，模型选择读 `summary.positive_cost`，不读环境返回的零 reward。
- 动作是一个 `Discrete(324)` 编号，经原 decoder 转换成 `[T,S,C,E,A]`。合法 Mask 单独传入。
- `encode_rl_observation(observation, reference_population, reference_horizon)` 复用原 198 维编码，仅缩放原始 N/H 两项；原编码不变。不使用测试拟合、动态归一化或 reward normalization。
- `source_grid(protocol,pool_name,seed)` 位于轻量协议模块，供 A/B、参考策略和案例采集共用；不让正常案例加载依赖训练器。

Threshold 只读取公共完整周与当前实际动作；升档、降档都按最近完整周的共同指标立即到达目标档位，允许跨级。先按公共 Mask 下调建议 S，再交共同 resolver。所有方法 day0–6 统一执行最低干预，day7 首次自主决策；候选固定 32→4→1，不在 B 上追加搜索。

## 2. 模型与训练入口

- `load_baseline_controller(protocol, artifact_path)` 返回 Controller 和独立私有 metadata。RL 依赖延迟加载；正常控制/记忆导入不加载 Torch、Gym 或 SB3。
- `GymControlEnv` 投影现有环境；reset先执行固定首周，返回day7观察，`info` 含该首周的公共 resolution/feedback/next_mask。首周不进入学习样本或训练步数；之后step的info仍只含公共字段。H 是任务终止，不是截断；自动 reset 后 DDQN replay 使用 `terminal_observation` 和终点 next_mask。
- MaskablePPO 使用原库 loss、rollout 和历史 Mask；2048 步 `learn` 返回后保存。冻结推理显式传 Mask，保持确定性。
- DDQN 使用 online 合法 argmax、target 估值；终点不查询下一状态网络。replay 容量50000，warmup512，之后每步更新，512倍数更新后同步；epsilon 前4096步降到.05，预算升级不重置。
- 三训练 seed 各有独立模型、优化器、buffer、世界调度流；单 worker `SubprocVecEnv(spawn)`。每段切换保存/恢复学习器随机状态，独立进程评估。
- 每个 seed 以 A 取前2、B 选1；每算法保留3个模型。只有 A 曲线决定8192→16384→32768升级，PPO/DDQN可用上限一致。

薄命令入口：

```powershell
$python = 'E:/pytroch/anaconda3/envs/simulation/python.exe'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
& $python -m examples.control_v1.baselines --help
& $python -m examples.control_v1.baselines pilot --artifact results/uw_e0_roles_20261023/control_anchor.json --reference maximum_feasible --output results/uw_phase6_pilot
& $python -m examples.control_v1.baselines tune --artifact results/uw_e0_roles_20261023/control_anchor.json --output results/uw_phase6_threshold
& $python -m examples.control_v1.baselines train --artifact results/uw_e0_roles_20261023/control_anchor.json --method ppo --maximum-budget 8192 --output results/uw_phase6_ppo
```

这些是新配置 E0 完成后的入口示例，示例锚点当前尚未生成，不表示已完成校准、正式调参或训练。输出使用新目录，错误保留原运行证据；推理 checkpoint 不提供 replay/活动世界的精确崩溃恢复。

历史 Windows Conda 验收中，MKL 与 Torch 各有 OpenMP runtime，spawn 曾在 Torch 先导入时退出。上述显式 `MKL_THREADING_LAYER=SEQUENTIAL` 启动方式通过了当时的真实子进程验收；当前命令沿用该设置，不使用 `KMP_DUPLICATE_LIB_OK`，算法代码不吞掉该故障。依赖变更后仍须实际核对运行状态。

历史验收登记显卡为 RTX 5070 Ti、16 GB，使用 CPU Torch；128×128 小网络的合成2048步训练中 PPO 约1.74秒、DDQN约2.93秒。这些不是当前 UW 世界的完整训练耗时，也不证明已在 CUDA 训练；当前设备与依赖以实际检查为准。

## 3. 案例库与共同冻结

`tools.collect_observable_memory collect` 支持四策略及 `--threshold-artifact`；Threshold 必须加载实际选定产物，参数身份只入私有清单。继续复用原公共 transition、recorder、episode memory、case builder 链。

覆盖报告补动作档位/容量、联合与转移动作、历史、持续时间、测量变化和后效负担。世界留出仅诊断检索，排除同世界全部策略与周，不声称验证控制效果。

`promote_public_store(development_dir, release_path, output_dir)` 验证真实 release 后复制发布，保留原 development 目录、公共 SQLite 字节与真实 run_purpose。发布清单引用 release 和原 development 证据，独立 publication result 登记最终清单身份，避免循环 hash。

release 必须关联当前任务/H/目标/E0/代码身份、108来源、实际动作覆盖、每 seed 唯一选定模型、A/B 与预算记录、四模式 LLM、共同 H 及敏感性前置项。缺少真实证据时明确拒绝，不接受只有 `frozen=true` 或 `status=completed` 的声明。

`horizon` 命令计算112→140→168有限升级与重开发要求；协议切换、统一重训/调参/重采集由明确的下一轮命令执行，没有自动修改协议或无限循环后台任务。共同冻结前必须完成这些重开发，不能把“已输出 H 报告”当作已完成重开发。

## 4. 历史工程证据与当前缺项

2026-10-21共同首周修订后的本地回归：使用指定simulation解释器运行全部control测试，886 passed、99项无关测试未选中、无跳过，保留1条既有pytest `env`配置警告；包含实际Gym轨迹、spawn自动重置、PPO合成更新及DDQN更新/存取验证。以下原有验收数字保留为历史证据，不替代新协议下的正式训练与科学评价。

- 当时指定 simulation 环境已安装并实测 Gymnasium1.4.0、SB3/contrib2.9.0、Torch2.14.1+cpu；原 tokenizer 加载栈按项目固定版本补齐。`pip check` 当时通过，历史依赖快照见 `requirements-control-rl-v1.lock.txt`，不能将该快照视作当前安装状态。
- 控制测试整合验收849 passed，无跳过；最终删减重复代码及合并唯一预算/H公式后相关81项再次通过；CEMAS/人口兼容检查5项通过。保留一项现有 pytest 配置 `env` 未识别警告，不为此修改无关测试配置。
- RL 独立验收23 passed，无依赖跳过，包含实际 Gym 轨迹对照、spawn、Double 手算、真实梯度和模型存取。
- 合成2048步短训练仅为工程验收：PPO参数实际更新；DDQN1537梯度更新、4次target同步，二者加载动作一致。报告：`results/phase6_engineering/rl_synthetic_20261018T072730Z/report.json`。
- 旧 Notre Dame E0 在 `results/phase6_engineering/e0_primary` 完成100trial×3世界与20独立验证世界，并通过当时的兼容性加载。beta为0.03999548144249928，接近预定搜索上界；独立验证RMSE约11.223、normalized MSE约1.168。这是旧重构聚合数据的拟合证据，不表示真实世界预测验证，也不适用于当前 UW 配置。
- 真实四回合pilot位于 `results/phase6_engineering/pilot`：首次8.07秒，后续7.55/7.87/7.60秒；初始化约0.12–0.21秒；worker进程峰值驻留内存最高约247 MiB。
- 生产 `TrainingEnvFactory` 历史检查通过：单spawn推进16个旧口径周transition/112日；当前 Gym reset 会先执行固定首周，训练记录将把它单列，不计入学习transition。终点观察、自动reset、Mask、公开info和奖励对账仍需按当前协议重新登记；第二世界已初始化但未step，独立记账。报告位于 `results/phase6_engineering/rl_source_short/factory_boundary`。
- 真实源环境短训练完成（该历史记录采用旧首周计数口径；当前协议将固定首周与自主决策分开记账），汇总位于 `results/phase6_engineering/rl_source_short/summary.json`；PPO256周步/1792日，约160.84秒、40次优化步；DDQN512周步/3584日，约340.43秒、首次梯度更新与hardcopy成功。模型加载后动作一致且合法，父进程＋worker采样峰值约846/843 MiB。同训练seed的两算法世界计划前缀一致，超参数未降低；这些模型没有进行A/B选模，不能替代正式训练。

独立review已修复：重复训练seed导致字典覆盖模型；极小epsilon比例经整数化后除零；holdout命令清单文件名错误；Threshold候选参数元数据被误当成完整模型产物。另增加已加载产物的共同H/E0核对，并移除重复decoder、Gym范围检查与Threshold重复构造验证。未新增算法注册器、manager、重试器或仿真分支。

尚未完成：当前角色与接触参数配置的完整 UW E0 校准、正式Threshold360验证回合、108源轨迹、RL三seed完整预算、真实LLM四模式A/B、共同H/目标/敏感性冻结、evaluation_ready发布与Phase7就绪。付费模型调用仍须单独授权；当前配置的正式批次成本应先通过新的真实 pilot 测量。

## 5. 正式批次预算与当前交付边界

工程接入及旧模型上的 E0、pilot、短训练已有历史记录；当前模型修订后须先重做 E0，再重新计时与开发。原阶段按用户选择只交付工程与预算、未启动正式源域批次；本文不据历史授权启动当前校准、训练、采集或 API。后续运行按构建计划 P6.5 固定实际资源上限。

以下是旧模型、旧首周计数口径下的线性估算，仅保留作历史成本证据，不能用作当前 69,457 人 UW 模型的时长估计。当前H不延长：Threshold360回合、建库108回合、所有A/B及固定参考策略B的完整回合仍各为H日，不能再额外加7日。两算法各3seed的训练预算按自主决策步数计，须在这些样本的实际执行日之外，计入每个已启动世界的固定首周，包括自动reset后尚无自主决策的世界。正式训练预算以`training_budget`的`simulated_days`、`fixed_windows`和`autonomous_decisions`核算：

| 每seed可用周步上限 | 两算法纯训练 | 含上述本地验证/采集的总计 |
|---|---|---|
| 8192 | 约8.83小时 | 约10.82小时 |
| 16384 | 约17.66小时 | 约20.11小时 |
| 32768 | 约35.31小时 | 约38.69小时 |

这些是估算，不是时间保证；只测了一个训练seed和一种pilot策略，后期策略、病程及系统负载会改变成本。DDQN512步只测到首次更新，持续更新成本另有合成2048步记录，但仍需在完整曲线上报告实际消耗。

表中历史估算未计固定自主训练样本预算之外的首周日步，也未计付费LLM服务时间/费用、重试、H统一升级后的重开发及lambda=.5/2独立敏感性批次。四种LLM模式各只有一个预登记候选时，A/B本身共108回合；当前每个H112回合含1个固定首周和15个自主决策，因此共1620个自主决策、108个固定首周窗口，合计仍为108×112个模拟日；API重试另计调用次数，不增加模拟日。真实延迟、token与费用尚未测量，不预填收费金额。敏感性需要额外两套独立源域开发与兼容源库。

机器可读交付摘要与估算：`results/phase6_engineering/execution_summary.json`。已保留用户的 `docs/修改意见.md`；本地结果目录不纳入本次Git提交，发布状态以实际提交记录为准。

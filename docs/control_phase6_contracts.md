# Phase 6 接口与验收记录

更新：2026-10-18。实施基线：`feature/control-protocol-v1@1a13d9e`。

当前已接入 Threshold、MaskablePPO、DDQN、源域训练/选择与案例库发布工程。工程验证、短训练、正式源域实验和共同冻结分别登记；工程通过不表示控制收益或 Phase 7 已就绪。

## 1. 公共执行与私有编排

- Controller 保持 `reset()/decide(PublicObservation)/observe(PublicWeekFeedback)`；不接收 reward、seed、beta、模拟器或训练器。
- 环境继续唯一负责 reset、七日推进、合法动作解析、执行和奖励。评估复用 `run_episode(mode="evaluation")`，模型选择读 `summary.positive_cost`，不读环境返回的零 reward。
- 动作是一个 `Discrete(324)` 编号，经原 decoder 转换成 `[T,S,C,E,A]`。合法 Mask 单独传入。
- `encode_rl_observation(observation, reference_population, reference_horizon)` 复用原 198 维编码，仅缩放原始 N/H 两项；原编码不变。不使用测试拟合、动态归一化或 reward normalization。
- `source_grid(protocol,pool_name,seed)` 位于轻量协议模块，供 A/B、参考策略和案例采集共用；不让正常案例加载依赖训练器。

Threshold 只读取公共完整周与当前实际动作；升档不限级，降档需连续两周严格低于每条边界乘迟滞比例。先按公共 Mask 下调建议 S，再交共同 resolver。day0 无历史时保持当前档位，同时执行容量约束。候选固定 32→4→1，不在 B 上追加搜索。

## 2. 模型与训练入口

- `load_baseline_controller(protocol, artifact_path)` 返回 Controller 和独立私有 metadata。RL 依赖延迟加载；正常控制/记忆导入不加载 Torch、Gym 或 SB3。
- `GymControlEnv` 投影现有环境；`info` 只含公共 resolution/feedback/next_mask。H 是任务终止，不是截断；自动 reset 后 DDQN replay 使用 `terminal_observation` 和终点 next_mask。
- MaskablePPO 使用原库 loss、rollout 和历史 Mask；2048 步 `learn` 返回后保存。冻结推理显式传 Mask，保持确定性。
- DDQN 使用 online 合法 argmax、target 估值；终点不查询下一状态网络。replay 容量50000，warmup512，之后每步更新，512倍数更新后同步；epsilon 前4096步降到.05，预算升级不重置。
- 三训练 seed 各有独立模型、优化器、buffer、世界调度流；单 worker `SubprocVecEnv(spawn)`。每段切换保存/恢复学习器随机状态，独立进程评估。
- 每个 seed 以 A 取前2、B 选1；每算法保留3个模型。只有 A 曲线决定8192→16384→32768升级，PPO/DDQN可用上限一致。

薄命令入口：

```powershell
$python = 'D:/programfile/miniconda3/envs/simulation/python.exe'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:MKL_THREADING_LAYER = 'SEQUENTIAL'
& $python -m examples.control_v1.baselines --help
& $python -m examples.control_v1.baselines pilot --artifact results/phase6_engineering/e0_primary/artifact.json --reference maximum_feasible --output results/phase6_pilot
& $python -m examples.control_v1.baselines tune --artifact results/phase6_engineering/e0_primary/artifact.json --output results/phase6_threshold
& $python -m examples.control_v1.baselines train --artifact results/phase6_engineering/e0_primary/artifact.json --method ppo --maximum-budget 8192 --output results/phase6_ppo
```

这些是可调用入口，不表示已运行上述正式调参/训练。输出使用新目录，错误保留原运行证据；推理 checkpoint 不提供 replay/活动世界的精确崩溃恢复。

本机 Windows Conda 的 MKL 与 Torch 各有 OpenMP runtime；实测 spawn 在 Torch 先导入时退出。上述显式 `MKL_THREADING_LAYER=SEQUENTIAL` 启动环境已通过真实子进程验收，测试与正式命令均需采用；未设置 `KMP_DUPLICATE_LIB_OK`，算法代码不吞掉该故障。

本机显卡为 RTX 5070 Ti，16 GB。当前已验收 Torch 为 CPU 版本；128×128 小网络的合成2048步训练中 PPO 约1.74秒、DDQN约2.93秒，整体预算需另外计入真实世界推进。GPU 使用授权已保留，目前不据此声称已经在 CUDA 训练。

## 3. 案例库与共同冻结

`tools.collect_observable_memory collect` 支持四策略及 `--threshold-artifact`；Threshold 必须加载实际选定产物，参数身份只入私有清单。继续复用原公共 transition、recorder、episode memory、case builder 链。

覆盖报告补动作档位/容量、联合与转移动作、历史、持续时间、测量变化和后效负担。世界留出仅诊断检索，排除同世界全部策略与周，不声称验证控制效果。

`promote_public_store(development_dir, release_path, output_dir)` 验证真实 release 后复制发布，保留原 development 目录、公共 SQLite 字节与真实 run_purpose。发布清单引用 release 和原 development 证据，独立 publication result 登记最终清单身份，避免循环 hash。

release 必须关联当前任务/H/目标/E0/代码身份、108来源、实际动作覆盖、每 seed 唯一选定模型、A/B 与预算记录、四模式 LLM、共同 H 及敏感性前置项。缺少真实证据时明确拒绝，不接受只有 `frozen=true` 或 `status=completed` 的声明。

`horizon` 命令计算112→140→168有限升级与重开发要求；协议切换、统一重训/调参/重采集由明确的下一轮命令执行，没有自动修改协议或无限循环后台任务。共同冻结前必须完成这些重开发，不能把“已输出 H 报告”当作已完成重开发。

## 4. 当前证据

- 指定 simulation 环境已安装并实测 Gymnasium1.4.0、SB3/contrib2.9.0、Torch2.14.1+cpu；原 tokenizer 加载栈按项目固定版本补齐。`pip check` 通过，依赖快照见 `requirements-control-rl-v1.lock.txt`。
- 控制测试整合验收849 passed，无跳过；最终删减重复代码及合并唯一预算/H公式后相关81项再次通过；CEMAS/人口兼容检查5项通过。保留一项现有 pytest 配置 `env` 未识别警告，不为此修改无关测试配置。
- RL 独立验收23 passed，无依赖跳过，包含实际 Gym 轨迹对照、spawn、Double 手算、真实梯度和模型存取。
- 合成2048步短训练仅为工程验收：PPO参数实际更新；DDQN1537梯度更新、4次target同步，二者加载动作一致。报告：`results/phase6_engineering/rl_synthetic_20261018T072730Z/report.json`。
- E0 已在 `results/phase6_engineering/e0_primary` 完成100trial×3世界与20独立验证世界，并通过当前兼容性加载。beta为0.03999548144249928，接近预定搜索上界；独立验证RMSE约11.223、normalized MSE约1.168，这是重构聚合数据的拟合证据，不表示真实世界预测验证。
- 真实四回合pilot位于 `results/phase6_engineering/pilot`：首次8.07秒，后续7.55/7.87/7.60秒；初始化约0.12–0.21秒；worker进程峰值驻留内存最高约247 MiB。
- 生产 `TrainingEnvFactory` 检查通过：单spawn推进16个周transition/112日，终点观察、自动reset、Mask、公开info和奖励对账正确；第二世界已初始化但未step，独立记账。报告位于 `results/phase6_engineering/rl_source_short/factory_boundary`。
- 真实源环境短训练完成，汇总位于 `results/phase6_engineering/rl_source_short/summary.json`；PPO256周步/1792日，约160.84秒、40次优化步；DDQN512周步/3584日，约340.43秒、首次梯度更新与hardcopy成功。模型加载后动作一致且合法，父进程＋worker采样峰值约846/843 MiB。同训练seed的两算法世界计划前缀一致，超参数未降低；这些模型没有进行A/B选模，不能替代正式训练。

独立review已修复：重复训练seed导致字典覆盖模型；极小epsilon比例经整数化后除零；holdout命令清单文件名错误；Threshold候选参数元数据被误当成完整模型产物。另增加已加载产物的共同H/E0核对，并移除重复decoder、Gym范围检查与Threshold重复构造验证。未新增算法注册器、manager、重试器或仿真分支。

尚未宣布完成：正式Threshold360验证回合、108源轨迹、RL三seed完整预算、真实LLM四模式A/B、共同H/目标/敏感性冻结、evaluation_ready发布与Phase7就绪。付费模型调用仍须单独授权；正式批次成本先按真实pilot估算。

## 5. 正式批次预算与当前交付边界

工程、E0、pilot及短训练已完成。用户已明确选择“本轮先交付工程与预算，正式批次后续运行”，因此本轮到此交付，不启动完整非付费科学批次。当前没有后台长训练或采集任务；后续启动时再按构建计划P6.5固定实际资源上限。

按112天任务的实测周步和pilot均值线性估算（包括Threshold360回合、建库108回合、两算法各3seed、所有A及最终两候选B、固定参考策略B）：

| 每seed可用周步上限 | 两算法纯训练 | 含上述本地验证/采集的总计 |
|---|---|---|
| 8192 | 约8.83小时 | 约10.82小时 |
| 16384 | 约17.66小时 | 约20.11小时 |
| 32768 | 约35.31小时 | 约38.69小时 |

这些是估算，不是时间保证；只测了一个训练seed和一种pilot策略，后期策略、病程及系统负载会改变成本。DDQN512步只测到首次更新，持续更新成本另有合成2048步记录，但仍需在完整曲线上报告实际消耗。

表中未计付费LLM服务时间/费用、重试、H统一升级后的重开发及lambda=.5/2独立敏感性批次。四种LLM模式各只有一个预登记候选时，A/B本身共108回合、1728次决策（未计重试）；真实延迟、token与费用尚未测量，不预填收费金额。敏感性需要额外两套独立源域开发与兼容源库。

机器可读交付摘要与估算：`results/phase6_engineering/execution_summary.json`。已保留用户的 `docs/修改意见.md`；未提交或推送Git。

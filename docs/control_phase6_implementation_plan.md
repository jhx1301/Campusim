# CEMAS v1 Phase 6 构建计划：Baseline、源域开发与统一冻结

编制：2026-10-17；状态更新：2026-10-23。状态：**工程接入已实现，旧模型的 E0、计时与短训练保留为历史记录；当前 UW 角色与接触参数配置须重新校准，正式源域批次和共同冻结未完成，Phase 6 尚未整体完成。**

当前基础模型为 69,457 人、教师 2,321 / 其他职员 21,596、`campus_k_ts=3`，尚无此配置的完整 E0 结果。当前运行前提和新校准命令见 [UW 控制接入](uw_control_integration.md)；旧 `results/e0_v2/full/` 锚点不能用于新模型。

本文最初作为设计交付，随后按当时用户指令实施；历史授权覆盖依赖安装、本地测试、短训练及在新目录补做 E0，实际执行记录见 [Phase 6 实施契约](control_phase6_contracts.md)。阶段要求不代表已经完成，也不从本文或历史 JSON 的授权记录推断新的校准、训练或付费调用授权。

## 1. 目标、依据与阶段边界

Phase 6 将现有公共控制底座和 Phase 5 LLM 架构接成可训练、可验证、可追溯的一组方法，完成源域开发、统一时域确认和正式案例库发布，为 Phase 7 提供确定的实验输入。

依据优先级：当前用户要求与 AGENTS.md → 本次已讨论的接入设计及本文明确补足 → [v1 工程计划](cemas_v1_implementation_plan.md)、[推荐协议](llm_recommended_protocol_v1.md)及 [JSON](control_protocol_v1.json) → [研究 README](llm_architecture_research/README.md)下的 LLM 主架构。LLM 内部记忆、知识、检索、提示词采用新研究主方案；公共任务、信息权限、动作、执行和评价继续遵守 v1。

### 1.1 必须交付

| 交付 | 完成含义 |
|---|---|
| Threshold | 确定执行规则、32→4→1 源域调参、参数存取、公共建库接入 |
| MaskablePPO | 薄 Gymnasium 适配、合法 Mask、训练、冻结推理和模型存取 |
| 真正的 DDQN | 双网络、固定容量 replay、合法探索/贪心/bootstrap、训练与冻结推理 |
| 训练与评估编排 | 三个训练 seed、独立世界计划、A/B 选择、预算升级、私有成本与失败记录 |
| 公共源案例库 | 27 世界×四策略 development 库，覆盖与按世界留出检查，合格后发布 evaluation_ready |
| 全方法源域验证 | 共同目标与 H、LLM 四模式开发验证、资源和实际调用成本登记 |
| 冻结交付 | 参数/模型/知识/提示/检索/案例库身份、H 检查、来源与依赖版本、Phase 7 输入清单 |

### 1.2 本阶段不增加

- 新疫情引擎、第二套日步/周步、奖励公式或 resolver；不重写已有公共类型。
- LLM 微调、embedding 主检索、在线反思、审查器、多角色、世界模型或额外模拟查询。
- 通用 Agent/Artifact/Worker Manager、算法注册器、可插拔 replay、工作流平台或任意搜索框架。
- GPU、并行推进多世界、RNN、dueling、优先回放、n-step 或新的动作集。
- E1–E4 正式批量实验、城市适配、动态资源场景、E4 分叉重放和完整统计表图；这些归 Phase 7。
- 精确崩溃恢复、活动模拟器序列化、现有 source 导出的通用重建/迁移工具。P5 的已审核 source 导出重建缺口单列保留；本计划通过现有采集链生产新 development 库，最终发布可复用这批已核验数据，不依赖该缺失入口。
- E0 算法重构或默认重校准；先实际核验兼容性，确实失效后才安排单独的校准任务。

### 1.3 AGENTS.md 对实施的约束

1. 每个步骤只改其列出的文件及已证明必要的技术依赖；遇到范围外冲突先说明问题和调整。
2. 配置边界、模型/数据加载边界各校验一次；内部复用已成立的不变量，不层层重验。
3. 不把异常转成任意默认动作、零 Q、零成本或成功状态；沿用已有 LLM 重试和共同回退，不新增另一套重试。
4. 先测试当前变化，再因具体失败或回归风险扩大范围，不修改无关代码凑全绿。
5. 每步结束审阅 diff：删除重复逻辑、无调用依据的接口、假设性保护和无关改动，重跑受影响测试。

## 2. 实施前基线与复用决策记录

Phase 6 实施前静态基线：`feature/control-protocol-v1@1a13d9e`。当时只有未跟踪的 `docs/修改意见.md`，该用户资料继续保留。下表记录实施前模块与当时的调整范围，不是当前待实现清单；当前接口和证据见 [Phase 6 契约](control_phase6_contracts.md)。接续时重新检查分支、状态、依赖和实际产物，不套用历史测试数字。

当前指定解释器：`E:/pytroch/anaconda3/envs/simulation/python.exe`。数据/模型/输出路径采用项目相对默认值或显式参数，代码不硬编码机器目录。

| 实施前模块 | 当时直接复用 | 当时规划的调整 |
|---|---|---|
| `WeeklyControlEnvironment` | 唯一 initialize、七日推进、反馈、奖励、终点对账和 close | 无需修改推进主线 |
| `Controller` | `reset/decide/observe`，只接公共输入 | 新增具体控制器，契约不加 reward/learn/simulator |
| `observation.py` | 198 维顺序与公共原始字段，Mask 分开 | 增加一个双方共用的固定 RL 预处理 |
| `actions.py/resolution.py/execution.py` | 324 编解码、Mask、共同回退、实际执行 | 无需改变 |
| `rewards.py` | 唯一目标公式、固定尺度、私有分项 | 无需改变公式 |
| `runner.py` | 完整回合评估、审计、`positive_cost`、公共 transition sink | 方法/用途放行、模型元数据、共同源域映射 |
| Phase 5 memory/retrieval/knowledge/LLM | 四模式、数值检索、五字段、同一 transport/重试 | 复用；只做事先列出的有限源域配置选择 |
| 建库工具与 `memory_store.py` | 公共 SQLite＋独立私有 JSON、事务、只读与完整性 | Threshold 来源、覆盖、世界留出与最终发布证据 |

实施前 runner 未接受三种 Baseline，且有两处限制 LLM 使用 A/B；采集入口只支持三策略，evaluation_ready 也缺 P6 冻结证据接入。上述接入现已实现：runner 支持 Baseline，采集支持四策略，发布工具会核验真实 release 后晋升 development 库。剩余工作是当前模型的校准和正式源域证据生产，不能把已存在的接口当成已有科学产物。

案例兼容性当前覆盖 `cemas/control/*.py` 和 `covasim/*.py` 的源码身份。因此，**所有接入和发布代码先完成并通过工程验证，再采正式 development 库**。后续修复如使产物不兼容，应记录受影响证据并重做相应开发，不能直接改 hash 继续使用。E0 的兼容范围不同，不得据此声称任意 control 修改都必然重校准。

## 3. 固定的共同接口与数据流

评估链始终为：

```text
PublicObservation → Controller.decide → ActionProposal
→ WeeklyControlEnvironment.step_proposal → 唯一 resolver/executor
→ 公共观察与反馈 → Controller.observe
                         └→ runner 私有审计与成本汇总
```

训练链为：

```text
父进程学习器 ⇄ 单 worker SubprocVecEnv(spawn)
                → GymControlEnv → 同一个 WeeklyControlEnvironment 实现
```

| 接口约定 | 输入 → 输出 | 所在位置 |
|---|---|---|
| `encode_rl_observation` | 公共观察＋冻结参考 N/H → float32[198] | `observation.py` |
| `ThresholdController.decide` | 公共观察 → 合法 ActionProposal | `controllers.py` |
| PPO/DDQN `predict` | float32[198]＋bool[324] → 普通 int | 各自 RL 模块 |
| PPO/DDQN `decide` | 公共观察 → 编码、predict、既有 decode → ActionProposal | 各自 RL 模块 |
| `GymControlEnv` | reset/step/action_masks/close → Gymnasium 接口 | `rl/env.py` |
| `load_baseline_controller` | 协议＋产物路径 → Controller、私有元数据 | `controllers.py`，按方法延迟导入 |
| `train_controller` | 协议、方法、资源、输出 → checkpoint/选择记录 | `training.py` |
| `select_checkpoint` | 每个 seed 的 A 记录、B 评估 → 该 seed 唯一模型 | `training.py` |
| `validate_phase6_release` | 实际产物与源域证据 → 发布检查结果或明确失败 | 纯产物校验模块 |

Controller 不拿世界 seed、beta、私有 reward、完整协议或完整审计。学习器可消费训练 reward，runner/离线选择器可消费私有目标，但它们不作为下一次网络、prompt 或案例的输入。

评估时环境返回 reward=0，选择模型只读 runner 的 `summary["positive_cost"]`。必要时将现有 `_episode_summary` 提升为可复用函数，供训练完成窗口的私有汇总使用；不复制奖励计算。

### 3.1 固定 RL 预处理

旧 `encode_observation()` 和其测试保持不变。新增函数先调用旧编码，仅将原始 N/H 两项除以训练任务的公开参考 N/H，其余 196 项不变。参考值来自该训练任务协议并写入模型产物，不随测试人口重新拟合；Mask 不拼入特征。

两算法的训练和推理使用同一函数，记录 RL 编码版本。无 clip、无测试拟合、无 VecNormalize、无 reward normalization。该决定是本轮针对已知量纲差异的设计补充，不声称已证实旧编码训练失败。

### 3.2 Gym 与进程边界

- `Box(-inf,+inf,(198,),float32)`、`Discrete(324)`；维数由已有特征表核对。
- 在库边界将整数标量转换为普通 int；拒绝浮点截断，不放宽原 decoder。
- `info` 为普通字典，只投影公共 resolution、feedback、该步 next Mask；不放私有 audit。Gym reset先执行固定首周，返回day7观察及该首周的公共info；首周不进入学习样本或训练步数。
- `action_masks()` 使用缓存的当前公共观察；不建立另一套容量计算。
- H 到期是 `terminated=True,truncated=False`，不包 TimeLimit；异常使运行失败。
- `reset(seed=...)` 初始化训练调度流，实际 world_seed 来自已登记的私有回合计划；不能把 train_seed=11 当作 world_seed=11。自动 reset 继续下一行计划，不重设整个计划。
- 两算法共用一个单 worker SubprocVecEnv；DDQN 终点 next observation 取 `terminal_observation`，next Mask 取该步 info，不能取自动 reset 后新回合的day7观察。
- CPU 首版、每任务 n_envs=1。三个 seed 的模型/优化器/buffer 分开，暂停世界可驻留，同一时刻只推进一个世界。切换 seed 时保存/恢复 Python、NumPy、PyTorch CPU RNG；A/B 在独立进程评估。
- worker 只接收普通可序列化配置与路径，子进程自行加载协议；不跨进程传活动 simulator 或 MappingProxy 协议。无自建 RPC、自动恢复器或后台训练线程。

## 4. 三种 Baseline 的执行约定

### 4.1 Threshold

基础指标、五维基础边界和 loguniform 缩放读取 JSON `controllers.threshold`。执行语义固定为：

1. 每完整有效周 `z=D/N*1000*clip(2**(g/2),.5,2)`，增长无效取 g=0，该周仍有效。
2. `z >= 边界` 进入高档；基准是 observation.current_action 的实际档位。
3. day0–6 由协议统一执行最低干预；day7 首次读取完整首周公共记录并自主决策，H 不额外延长。
4. 从第二周开始，升档、降档都按最近完整周指标直接到达目标档位，允许跨级，不设等待或迟滞。
5. 根据公共 Mask，将建议 S 限到不高于目标的最高合法档；容量缩减立即生效。不能把非法 S 直接交 resolver，否则它会回退整份提案。
6. 不重复保存历史；reset/observe 无学习状态。

候选生成：局部 `Generator(82001)`，candidate_id=0..31；每候选按 `[T,S,C,E,A]` 顺序抽五个 `exp(uniform(log(.5),log(2)))`。保存完整候选表，并记录新算法语义与任务身份，不在各处重新生成。

32 候选各跑 A 九世界，按 `(mean_positive_cost,mean_normalized_activity,candidate_id)` 精确排序取4，再跑 B 十八世界选1。活动取共同 RewardBreakdown 的未加权 activity 分量。无额外基础候选、近似同分容差或 B 上手工追加搜索。

Controller 类型为 `threshold`，采集策略名为 `tuned_threshold`；一个局部映射即可。

### 4.2 MaskablePPO

使用现成 `sb3_contrib.MaskablePPO`，不重写 loss、GAE、rollout buffer 或 mask 优化。参数来自 JSON：policy/value 各128×128/Tanh，Adam3e-4，rollout256、batch64、10epochs，gamma1、GAE.95、clip.2、entropy.01、value.5、grad.5、target_KL.03。

Mask 在子进程环境中实现；采样和更新由库使用相应历史 Mask。冻结 Controller 调用 `predict(...deterministic=True,action_masks=...)`，转普通 int 后用既有 decoder。reset/observe 不学习。

每段训练2048周步，`learn(...reset_num_timesteps=False)` 返回后保存，保证本轮参数更新已完成。重复调用保留原模型、优化器和活动环境，不重新 load 或 reset。当前 lr/clip 为常数，不引入额外 schedule。

### 4.3 DDQN

一个具体模块内保留 QNetwork、固定容量 replay、DDQNTrainer、冻结 DDQNController。网络198→128ReLU→128ReLU→324；online/target各一份，target不参加梯度更新。

replay仅存 `(obs,action_id,reward,next_obs,terminated,next_mask)`，不存私有真值、世界身份或完整配置。容量50000、batch64、Adam3e-4、SmoothL1、grad norm10，参数读取JSON。

在线网在下一状态合法动作中选argmax，目标网对该动作估值；未终止目标 `r+Q_target(next,chosen)`，终止直接为r。终止行不先做无效argmax再乘零。探索、贪心、bootstrap均mask，Q并列取最小编号。

令t为成功入库的环境周transition数：前512次动作均为合法均匀随机；第512条入库后首更，此后每周一次更新；512倍数在该步更新后hardcopy。epsilon按累计t在前4096步从1降至.05，预算升级不重启或回升；评估epsilon0。以上warmup顺序及自适应预算下的epsilon口径是本计划明确补足。

## 5. 世界计划、选择与预算

| 用途 | 池/映射 | 限制 |
|---|---|---|
| 训练11/22/33 | 分别[1000000,1100000)、[2000000,2100000)、[3000000,3100000) | 右端不含，全部seed保留 |
| A | 20001–20009，九组合各1 | 筛候选/画预算曲线 |
| B | 20101–20118，九组合各2 | 最终选模与H检查，不决定预算升级 |
| 源库 | 30001–30027，九组合各3 | 四策略，不接验证/目标经验 |
| 提示开发 | 40001–40009 | 结构与有限提示开发 |
| pilot | 91001–91004 | 计时，不冒充效果验证 |
| 最终测试 | 50001及后续各专用池 | P6不开放 |

A/B/建库共用映射：pool起点a、每单元重复R；`i=seed-a; cell=i//R; beta=scales[cell//len(capacities)]; capacity=capacities[cell%len(capacities)]; replicate=i%R`。数值从JSON读取，不能复制第二套常量。

训练清单用 `SeedSequence(train_seed)` 派生世界顺序、beta、容量三个局部流：世界无放回抽取，beta∈[.85,1.15]均匀，三个静态容量等概率。同seed两算法共用同一回合计划；探索/replay流与该计划无关。记录实际使用清单，包括自动reset后已执行固定首周、尚无自主决策的世界，预算以实际模拟日、固定首周窗口和自主决策transition分别计数；固定首周不占RL学习步数。

每算法以2048为检查点串行推进三个seed：初始2048/4096/6144/8192，各检查点各seed跑完整A。某算法三个seed的A成本先平均，最近两个检查点改善 `(old-new)/max(old,1e-12) >= .02` 时，可在已记录资源上限内同升至16384、再32768；上限不超JSON阶梯。PPO/DDQN具有相同可用上限，实际训练量分列。到上限仍改善，报告训练不足。

预算决定完成后，**每algorithm×seed**从全部A检查点取前2，各跑完整B选1；同分按较早训练步数、稳定ID。每算法输出3模型，不能跨seed取最好1个。B成绩不回写训练buffer/输入；H变化后的重新开发单独版本记录，不隐去B的重复使用。

所有评估通过 `run_episode(...mode="evaluation")`，评分读取真实positive_cost。禁止普通EvalCallback或Monitor的零return选模。基础设施失败保留同身份attempt并按现有规则重做，不换世界、不对残缺样本平均；正常LLM回退轨迹保留计分。

四个H112回合共有64个执行窗口，其中60个是自主决策窗口；pilot分别测首次JIT、稳态模拟、初始化、内存与推理；梯度更新另用标记清楚的合成批次计时，不改变PPO rollout/DDQN warmup假装真实短训练。真正短训练另列。记录训练、A/B、阈值360回合、建库108回合及LLM调用的独立预算，不预承诺耗时。

不中断的预算续训保留对象与随机状态；普通推理checkpoint不声称包含replay、活动世界或精确故障恢复能力。

## 6. 公共源库与 LLM 源域开发

Threshold选定后，用原 `public_transition_sink → PublicTransitionRecorder → PublicEpisodeMemory → PublicCaseBuilder` 链采集四策略；采集时不调阈值。公共case只含公共观察、实际动作、后效和负担；参数产物hash、seed、beta、来源、选择成本留私有JSON。

先生成development库供LLM开发，不等待evaluation_ready。H112包含16个执行窗口，其中首周固定、15个自主决策；RL训练预算只计自主决策窗口，完整回合成本仍计入首周。不把周案例或同世界四轨迹当独立世界，不按隐藏reward筛掉反例。

在现有覆盖报告上只补明确缺项：九单元、每维档位、S/容量、联合及转移动作、历史长度、持续时间、测量变化、后效/负担、来源世界/策略。每维档位和可用容量下S档覆盖按v1检查；不要求324组合均匀。缺覆盖时先报告，确需增加源池或策略应单独修订，不临时填入测试世界。

按world留出只做离线检索诊断：留出一个世界必须排除该世界四策略的全部周/修订。`training.py`用私有来源映射构建一个仅实现现有`cases()/group_for()`读取接口的过滤视图，直接复用NumericRetriever，对留出案例的公共pre_observation查询并统计覆盖/距离/动作多样性。不调用LLM、不创建另一套控制回合，不新增公共query字段，也不把group/seed交给Controller。正式store完整性和任务核验保持不变；这项诊断不冒充完整的留世界控制效果实验。

LLM复用现有none/short/global/both；同模型、原四周、system、知识、五字段和resolver。旧P4两字段作为legacy，不据其与both的差异直接归因记忆。本轮不微调模型。

默认复用已定义的检索/知识/prompt配置，不做无界搜索。源域先登记每个候选、相应假设和预算；有限候选在A筛选、B确认，不反复看B再手调。若没有事先列出的替代候选，则验证并冻结当前候选，不自动创建新机制分支。记录完整token/usage、延迟、费用、重试、裁剪、解析/引用错误和回退；真实报告仅留档，不重新作为正常运行凭证。

## 7. 共同目标、H 和冻结证据

主任务保持lambda1、四负担权重各.25；本阶段检查计数/尺度合理性，不根据某方法优劣自动搜索主目标。确需改变目标数值，先说明具体问题并修订计划；不能按最终测试或不同目标综合分数大小选权重。

H按112→140→168有限升级。对JSON中七个主方法做B终点检查：完整/无显式记忆LLM、PPO、DDQN、已调Threshold、minimum、maximum_feasible；short/global另表披露，不悄悄改变主门槛集合。

一回合affected定义为：末14天新增感染>.002N **或** 终点活动感染>.005N。活动感染按引擎既有latent/infectious并集口径，不重复相加。方法affected比例严格>.20触发升级；固定/Threshold/各主LLM分母18，PPO/DDQN各汇总3seed×18=54，并保留各seed分表。只统计最终选定Threshold参数、每seed唯一选定RL模型及选定LLM配置的B结果，落选B候选不进入分母。因此分别4例、11例触发。本分组是本计划明确补足，不把三个RL模型当成只保留一个。

隐藏感染只供离线H检查，不进入在线终止/Controller。升级后先重估训练/验证/建库成本，必要时补计时，并沿用既定资源上限，不自动扩大预算；再统一全部方法的H、参考尺度及RL输入参考H，重新调阈值、训练/选模、开发LLM、重采案例。168仍持续，登记有限时域限制，不声称长期最优；不再无限增加H。

lambda=.5/2为v1规定的独立敏感性批次：复用代码，分别重新调Threshold和训练/选模，LLM使用相同公开偏好；不得只重打分冒充重新优化。公共task hash包含目标数值，因此每个lambda还须采集并冻结其兼容源库，不能只改prompt后直接加载lambda1案例库；额外采集和LLM开发预算单列，不据此建设通用案例迁移器。统一使用主任务确认的H；如该批次提供需改变共同H的证据，则回到同一有限升级流程，不为附录另选有利H。该批次必须在首次读取复用最终测试结果前完成并冻结。若未执行，交付中明确列为未完成前置项，不能宣布包含该敏感性实验的Phase7已经就绪。

### 7.1 最小产物契约

不建设管理平台，只用普通JSON与实际权重/数据文件，复用现有规范化快照/hash函数：

- **baseline artifact**：schema/方法/算法语义；Threshold最终边界与新算法语义或PPO zip/DDQN online state_dict路径和hash；编码与Mask/动作版本；参考N/H；任务数值、人口/基础模型/E0身份；训练seed、步数、训练清单和A/B选择报告身份；实际依赖版本。
- **phase6 release**：共同任务数值与H；七主方法的实际模型/配置身份；B结果与H报告；知识/prompt/retrieval/tokenizer身份；实际源库及private manifest hash、108来源与Threshold身份；覆盖/世界留出报告；软件与预算记录；未完成项和明确限制。

只在外部加载边界校验一次。完整协议hash用于溯源，兼容性比较相关语义，单纯objective.status变化不使相同数值任务失效。产物加载不依赖训练器，也不把私有元数据交给Controller。

最终发布流程：先核验原development库、原private manifest、完整108来源及上述冻结证据，再在新目录生成evaluation_ready发布副本，保留原库和原清单。发布清单记录原development清单hash；库用途的转换只改变发布元数据，不修改公共案例或真实run_purpose。读取器明确支持这种已验证promotion，不能仅删除P5报错或接受`frozen=true`。

phase6 release登记已验证development数据hash，发布清单引用release hash；单独发布结果再登记新清单hash，避免文件互相含对方hash而形成循环。没有H/目标/代码身份变化时，不重复运行108回合；变化后按兼容规则重采，不能通过换标签迁移无效案例。

## 8. 文件范围与职责

| 文件 | 必要改动 |
|---|---|
| `cemas/control/controllers.py` | Threshold、baseline加载入口；Controller契约不变，RL按需导入 |
| `cemas/control/observation.py` | 共用固定RL预处理，旧编码保持 |
| `cemas/control/runner.py` | Baseline/LLM的A/B、pilot、Threshold采集放行，私有模型元数据，共同网格映射/汇总 |
| `cemas/control/protocol.py` | 仅校验本阶段实际消费的算法/源域参数及组合约束 |
| `cemas/control/memory_store.py` | Threshold来源身份、覆盖报告必要缺项、证据核验后的promotion |
| `tools/collect_observable_memory.py` | 第四策略、实际Threshold产物、复用网格/原采集链 |
| `examples/control_v1/run_references.py` | 复用提炼后的网格函数，不再各算一套 |
| requirements/lock | 实施时核实指定环境并锁兼容torch/gymnasium/SB3/contrib；不预填未验收版本 |
| 公共导出文件 | 仅确需公开的入口，保持RL延迟依赖 |
| 协议/计划/索引文档 | 同步实际补足与证据，旧研究快照不伪装最新状态 |

新增：

- `cemas/control/rl/__init__.py`：不自动加载训练栈。
- `cemas/control/rl/env.py`：薄Gym适配、私有训练回合记录，实际执行仍在现环境。
- `cemas/control/rl/ppo.py`：现成算法构造和冻结PPOController。
- `cemas/control/rl/ddqn.py`：具体Q网络/replay/更新和冻结DDQNController。
- `cemas/control/training.py`：候选、世界计划、分段训练、RNG切换、A/B、预算、源域/H与发布编排，不实现日步或PPO loss。
- `cemas/control/worker.py`：可spawn的顶层仿真工厂、独立源域评估入口，不自建通信协议。
- `cemas/control/artifacts.py`：纯JSON/文件身份与baseline/release核验函数，无Torch/Gym/训练依赖。
- `examples/control_v1/baselines.py`：pilot/tune/train/evaluate/develop/freeze薄子命令，只转调核心函数，不写第二套循环。
- `tests/test_control_threshold.py`、`test_control_rl.py`、`test_control_training.py`；按变化扩现有runner/observation/store/integration用例。
- `docs/control_phase6_contracts.md`：实施时记录真实接口/命令/结果/限制，不预填通过数。

相比前次Baseline设计，纯`artifacts.py`是全Phase6范围内的一个明确补充：模型加载、runner来源核对与源库发布需要复用同一份产物核验；不能让正常运行导入训练编排。只放具体纯函数，不引入Artifact基类、注册器或manager。

默认不改`environment.py`、`resolution.py`、`execution.py`、`rewards.py`、公共`types.py`、传播/人口核心和E0算法。发现确需修改时先给出具体原因与最小调整，不顺手重构。

## 9. 构建步骤与验收出口

所有工程步骤先完成，正式数据生产在其后；每步按当前变化先测，证据写独立新目录，不覆盖旧结果。

| 步骤 | 工作与依赖 | 最小验收/出口 |
|---|---|---|
| P6.0 契约与前置核对 | 核对当前checkout、环境、E0实际兼容性；落实本文补足；确认依赖/真实运行授权范围 | 配置/用途/产物字段明确；无提前训练或API；缺依赖单独登记 |
| P6.1 共同接入与Threshold | Controller、runner放行、网格/评分、固定RL编码、Threshold与加载 | 边界/即时升降档/S容量/公共权限/零评估reward正确计分；旧语义产物拒绝加载 |
| P6.2 Gym与进程 | Gym、单SubprocVecEnv、回合计划、RNG隔离与私有预算记录 | scalar转换、info白名单、Mask、尾窗、terminal、自动reset不串回合；同动作轨迹一致 |
| P6.3 PPO与DDQN | 现成PPO、具体DDQN、推理/保存/加载、2048分段与三seed选择 | Double手算oracle、非法最大Q、terminal不bootstrap、warmup/同步/epsilon；PPO更新后checkpoint；加载动作一致 |
| P6.4 编排与发布工程 | A/B/预算/H有限循环、四策略采集接入、覆盖/世界留出、baseline/release/promotion、薄CLI | mock/fixture证明三seed全保留、池隔离、失败不静默删、108证据缺失拒绝；不把fixture发布正式库；工程回归通过后记录源码身份 |
| P6.5 计时与短训练 | 在P6.0–P6.4及实际依赖/E0满足后，执行4回合pilot、单env短训练、必要独立服务验证 | 实测时间/内存/梯度与调用成本，固定资源上限；工程/真实服务状态分列，报告不是运行许可证 |
| P6.6 Threshold与development库 | 正式32→4→1；加载选定参数采27×4，沿用P5链 | 360验证回合完整选择记录；108完整来源、实际动作、公共case/私有来源分离；coverage与world留出可复核 |
| P6.7 RL与LLM源域开发 | 每算法3seed，A曲线/预算升级、每seed A前2/B选1；LLM有限候选与四模式 | 6个RL模型/选择记录、实际训练清单、调用/失败/建库成本；七主方法B结果完整 |
| P6.8 共同确认与交付 | H有限升级，必要时回到P6.6/P6.7；确认目标、敏感性前置项，核验发布库与release | 主方法/H/目标/库等身份一致；promotion可只复用合格数据；Phase7所需产物和未完成项明确 |

P6.5–P6.8属于真实执行批次，只有工程代码通过不等于这些步骤完成。若本次后续执行指令仅授权工程接入，完成P6.0–P6.4并报告其余未执行，不伪造科学证据，也不擅自扩为完整训练/付费调用。

### 9.1 测试与审查顺序

1. Threshold、参数/产物边界、固定编码与私有权限。
2. Gym接口、整数动作、Mask、H终止、自动reset和随机流。
3. 合成Q输出独立验证Double公式、终点和mask；PPO适配与更新后保存；训练选择器使用人工成绩oracle。
4. runner评分、三seed全保留、A/B/池不交叉、原LLM失败/审计语义、Threshold公共采集与promotion。
5. 真实短训练/计时，随后才扩大到正式源域任务。
6. 相关`test_control_*`、CEMAS导入与必要人口回归；依赖缺失作为环境问题，不删用例凑全绿。
7. 最终diff审查；出现删减或修复后重跑受影响测试，不为扩大覆盖修改无关实现。

已建立的schema/动作合法性只在真实边界验证。Mask异常、非有限loss/输出、worker故障不得用随机动作、零Q或虚假terminal隐藏；不增加每层校验和全局异常吞噬。

## 10. 最终状态必须分开报告

| 状态 | 需要的证据 |
|---|---|
| `phase6_engineering` | 实际diff、相关测试、导入与接口验证 |
| `phase6_runtime_prerequisites` | 指定环境依赖、E0和当前tokenizer/服务资源实际状态 |
| `phase6_source_development` | Threshold/RL/LLM的A/B选择、曲线、实际预算、失败记录 |
| `phase6_source_library` | fixture/development/evaluation_ready、108来源、coverage/world留出、数据库及清单hash |
| `phase6_common_freeze` | 七主方法、目标/H、实际产物和发布证据，敏感性任务/限制 |
| `phase7_ready` | 所需开发产物齐备且未完成前置项为空；不意味着E1–E4已经执行 |

不能用工程测试通过替代收敛、服务、控制收益或正式来源覆盖。到预算上限未平台、H168仍持续、低覆盖与真实服务未验证等，必须按实际结果保留限制。

## 11. 研究依据与采用范围

- [PPO原论文](https://arxiv.org/abs/1707.06347)：采样与多轮minibatch更新；本项目复用现成实现。
- [Invalid Action Masking原论文](https://arxiv.org/abs/2006.14171)及[MaskablePPO官方文档](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)：合法分布、环境内Mask和推理时传Mask；不引入非法动作罚分。
- [Double DQN原论文](https://arxiv.org/abs/1509.06461)：online选择、target估值；不把vanilla DQN改名。
- [Gymnasium终止语义](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)及[SB3 VecEnv](https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html)：H任务终止、自动reset和terminal observation。
- [SB3输入尺度建议](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html)、[PyTorch存取说明](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html)：固定预处理与推理/恢复边界，不预建动态归一化或精确恢复系统。
- [强化学习评估研究](https://arxiv.org/abs/2108.13264)：保留训练波动和不确定性；三个seed数量与本项目统计方案来自v1，不宣称三个seed消除了不确定性。

上述研究支持实现选择，不证明这些控制器已在CEMAS收敛或某方法更优。推荐依赖版本应在指定环境实际验收后锁定，不能把网站master或文档当前版本直接写成已安装事实。

# CEMAS v1 当前工作阅读索引

交接日期：2026-10-14。此索引用于新 Codex 对话接续当前开发，集中阅读现行协议、阶段契约和当前代码。

## 1. 当前进度与接下来要做什么

项目目标是在同一个部分可观测疫情控制任务中，让各控制器共享观察、动作、执行器和评价口径。

当前工作目录为 `E:/项目/毕业设计/code`，分支为 `feature/control-protocol-v1`。本索引的代码/契约基线为 `e94b037`；当前 Git 状态以新对话核对结果为准。新对话先核对实际分支和工作区，保留已有未提交改动。

| 阶段 | 当前已有内容 |
|---|---|
| Phase 0 | 协议加载与静态验证、不可变 schema、Controller/RewardCalculator 抽象接口、公共序列化和 DecisionRecord |
| Phase 1 | `[T,S,C,E,A]` 的 324 动作编解码、公共筛查容量 mask、ActionResolution 数据契约 |
| Phase 2 | campus 场景、动作解析和共同执行器、公共 ledger/观察、198 维 float32 编码及独立私有指标；实现提交 `bbccd20` |

**下一阶段是 Phase 3：周环境、独立奖励、两个固定参照与 E0 校准，形成第一个完整运行闭环。** 当前没有完整周环境或 v1 E0 校准模块，奖励和控制器仍只有抽象契约，日志仍只有 schema/序列化。现有 Phase 2 集成测试手动推进模拟，不等于已实现周环境。

本次进度判断来自代码、契约和 Git 检查，没有重跑已完成阶段的测试、模拟或训练。下一对话先阅读并确认 Phase 3 设计，再按用户后续指令实施。

## 2. 按这个顺序阅读

| 顺序 | 文档 | 当前应关注的内容 |
|---|---|---|
| 1 | [软件工程实现计划](cemas_v1_implementation_plan.md) | 直接读 **C 节的 Phase 3**：文件范围、环境接口、时序、校准与验收。D 节是原始 Phase 0 任务清单，不是当前待办。 |
| 2 | [Phase 2 契约](control_phase2_contracts.md) | 已实现的数据路径、执行器、公共/私有边界及可复用接口；确认 Phase 3 从哪里接入。 |
| 3 | [推荐实施协议](llm_recommended_protocol_v1.md) | 优先读第 **4、5、6、7、12、13、14 节及附录 A**：观察时序、奖励建议、E0、种子隔离、终点、日志和待产物。 |
| 4 | [机器可读协议](control_protocol_v1.json) | 核对 `engine`、`actions`、`resources`、`observation`、`activity`、`objective`、`calibration`、`seeds`、`horizon_gate`、`development`，避免在代码中另写一套数值。 |
| 5 | [Phase 0 契约](control_phase0_contracts.md)、[Phase 1 契约](control_phase1_contracts.md) | 按需查 RewardCalculator、DecisionRecord、公共 schema、动作 mask 与 ActionResolution，保持现有接口。 |

工程计划负责“如何实现、做到哪里”；推荐协议和 JSON 负责“采用什么规则和参数”；阶段契约描述已交付接口。计划中的“新增文件”须与实际文件核对，不能据此覆盖已经存在的模块。归档材料和通用文档站点不在本次必读范围。

实现 E0 时补读 [data/README.md](../data/README.md)，确认诊断序列与 daily tests 的重建数据口径；校准拟合不能描述为官方原始逐日数据验证。

## 3. 文档之后，只看这些代码入口

| 已有文件 | 当前作用及 Phase 3 接入点 |
|---|---|
| [protocol.py](../cemas/control/protocol.py)、[types.py](../cemas/control/types.py) | 加载/验证协议及共享数据类型；奖励状态仍为 `recommendation_pending_phase3`。 |
| [scenarios.py](../cemas/control/scenarios.py) | `build_scenario()` 返回已初始化的 ScenarioBundle，复用其中实际挂接的 executor/analyzer。`scientific` 目前只要求显式 beta，尚未核验 E0 产物。 |
| [actions.py](../cemas/control/actions.py)、[resolution.py](../cemas/control/resolution.py) | 复用 codec、mask、解析和回退；环境接收的 action_id 经共享路径进入执行器。 |
| [execution.py](../cemas/control/execution.py)、[ledger.py](../cemas/control/ledger.py)、[metrics.py](../cemas/control/metrics.py) | 每日执行、公共日/周记录与反馈、私有 flow 聚合；用于周结算及日/周/终点对账。 |
| [observation.py](../cemas/control/observation.py) | 纯公共观察 builder 与编码；mask 单独提供。 |
| [controllers.py](../cemas/control/controllers.py)、[rewards.py](../cemas/control/rewards.py)、[logging.py](../cemas/control/logging.py) | 文件已经存在；分别补两个固定参照、具体独立奖励 calculator 和实际日志输出。 |
| [test_control_integration.py](../tests/test_control_integration.py) | 阅读现有 Phase 2 调用示例及断言，不将其当作周环境实现。 |

Phase 3 预计新增 `cemas/control/environment.py`、`cemas/control/calibration.py`、`examples/t23_control_protocol_v1.py` 及对应环境/校准测试。完整校准配置登记还需记录嵌套字段、派生值、版本与数据 hash。

## 4. Phase 3 的实施顺序与验收边界

1. **先确认最小设计。** 明确周环境生命周期、PublicInfo 白名单、训练/评估 reward 返回方式、奖励定义及版本化、CalibrationArtifact/FitReport 和日志产物契约。第5节奖励公式/权重仍是源域确认起点，不能当作已经冻结的可执行奖励。
2. **实现周环境与独立奖励。** 使用不依赖 Gymnasium 的同形接口：`reset(seed, options)`、`step(action_id)`、`action_masks()`、`close()`。训练模式可返回私有 reward；评估模式返回占位值，真值进入独立私有记录。
3. **接入两个固定参照与日志骨架。** 最低向量和当前最高资源合法向量都走同一个执行器。复用 DecisionRecord，公共输出与私有奖励分开保存；从此阶段开始记录实际执行量和运行用途。
4. **先小人口验证，再做明确标记的 smoke。** 检查 day 0、reset、尾周、终点 pending 事件、单次 finalize、同世界同动作前缀重放，以及日量之和＝周量之和＝终点总量。随后按计划用 N=12000、H=112、beta=0.016 跑两个固定参照；smoke 用于闭环检查，不作为正式实验结果。
5. **落实 v1 E0 与正式运行门禁。** 仅拟合 beta，固定层相对系数，100 trials、每候选三个固定校准世界，采用归一化日诊断 MSE；不加 R_e 惩罚。实现拟合、独立评价、完整产物保存及 hash/用途核验，正式运行加载真实 E0 产物。

E0 接口为 `make_calibration_sim()`、`fit_beta()`、`evaluate_beta()`，详细窗口、种子和数据设置以协议第6节及 JSON 为准。计划涉及的 `examples/t18_campus_calibration.py`、`examples/t18_campus_validation.py` 是待迁移代码，当前四参数路径不能作为 v1 E0 证明；先明确迁移范围，再修改。

## 5. 接续时必须保持的边界

- 所有 controller 只接收公共观察和公共反馈。PublicInfo、prompt、memory 不包含私有 reward、感染真值、beta、seed、未来事件或 simulator；完整 DecisionRecord 和运行 manifest 留在 runner/日志侧。
- 保持 `[T,S,C,E,A]`、324 动作及 level 0 的固定基线语义；公开 mask 只筛查 S，T/C 每日容量由 executor 处理。
- `build_observation()` 只消费公共 ledger、登记人口、当前动作/资源和显式任务常量，不接收 Sim 或 People。
- day 0 先决策，观察只包含前一日及以前已交付记录；一步最多推进七个真实日步。H112 对应 `n_days=111`，尾周照实际日数结算；累计感染含初始项，奖励新增感染不含初始项。
- 一回合只完整 initialize 一次，周间不重设世界随机流；finalize 只调用一次，环境独立保存进度，不能依靠 finalize 后的 `sim.t` 判断是否还有日步。
- Phase 3 聚焦校园闭环与 E0；Gymnasium 适配、LLM、PPO/DDQN、memory、城市实验分别按后续阶段推进。
- Python 使用用户指定的 `E:/pytroch/anaconda3/envs/simulation/python.exe`。环境和依赖按当前实装情况核对，不把契约中的历史环境快照当作现在的安装状态。
- 先保留现有工作区改动。Git 核对使用 `git branch --show-current`、`git status --short --branch` 和 `git log -5 --oneline`；发布操作按用户具体指令进行。

## 6. 可直接发给下一对话的提示

```text
请先阅读 docs/CEMAS_READING_INDEX.md，按其中顺序了解现行 CEMAS v1 文档和代码。
当前 Phase 0–2 已有实现，下一阶段是 Phase 3：周环境、独立奖励、两个固定参照与 E0 校准。
先核对当前分支和未提交改动，简要说明已有能力、Phase 3 设计及分步实施范围，再按我的后续指令编码。
这次先做阅读和设计确认，不需要重跑 Phase 1/2 的已有验收，也不用阅读归档材料。
保留公共/私有信息隔离、现有动作语义和已有工作区改动，使用索引中指定的 Python 环境。
```

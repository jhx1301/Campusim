# CEMAS v1 当前工作阅读索引

更新日期：2026-10-17。此索引用于接续 v1 开发，集中阅读现行协议、阶段契约和当前代码。

当前用户修订：P4/P5服务验收报告仅供开发验证和留档，不是运行凭证；正常入口不要求或读取报告，旧报告参数仅兼容接受。运行时按当前资源、输入计数、预算、实际usage和本批次实际服务身份检查。研究目录中的旧报告门禁描述属于历史方案，以当前P4/P5契约为准。

来源存储已简化为一个公共案例SQLite数据库和独立私有JSON清单；私有登记不再使用数据库，现有清单格式与运行时来源核对接口保持兼容。

## 1. 当前进度

项目目标是在同一个部分可观测疫情控制任务中，让各控制器共享观察、动作、执行器和评价口径。

当前工作目录为 `E:/项目/毕业设计/code`，v1 功能分支为 `feature/control-protocol-v1`。P3实施前基线及历史环境路径仍保留在P3契约；当前提交和未提交改动以实际Git检查为准。

| 阶段 | 内容与状态 |
|---|---|
| Phase 0 | 协议加载/静态验证、不可变 schema、Controller/RewardCalculator 接口、公共序列化和 DecisionRecord |
| Phase 1 | `[T,S,C,E,A]` 的 324 动作编解码、公共筛查容量 mask 和 ActionResolution |
| Phase 2 | campus 场景、共同执行器、公共 ledger/观察、198 维编码和独立私有指标 |
| Phase 3 | 已实现周环境、统一奖励、两个固定参照、日志/runner 和共享人口 E0；334项测试、完整smoke及主/辅助E0已验收，证据和拟合限制见 [P3 契约](control_phase3_contracts.md) |
| Phase 4 | 已实现公共prompt、严格解析、本地计数、transport、重试、共同回退和调用审计；保留独立服务验证工具，正常运行不要求验收报告，见 [P4 契约](control_phase4_contracts.md) |
| Phase 5 | 已实现确定性公共记忆、数值检索、知识卡、五字段依据、采集/冻结入口和独立服务验证；source导出重建仍有缺项，真实服务验证未执行，见 [P5 契约](control_phase5_contracts.md) |

P3 的公式和计数语义已确认，当前权重为可执行的 `development_candidate`。后续全部主方法的源域验证与 H 检查完成后再统一正式冻结；P3 闭环验收不代表权重验证、训练或最终实验完成。测试及实际 smoke/E0 结果只以契约中明确登记的证据为准，不能根据存在脚本就认定校准已经执行。

## 2. 按此顺序阅读

接续Phase 5时，先读[Phase 5契约](control_phase5_contracts.md)、[Phase 5实施计划](control_phase5_implementation_plan.md)及其[研究架构依据](llm_architecture_research/02_recommended_architecture.md)。与原P5候选冲突的模块、检索参数和LLM输出采用本次研究；P4当前限制须读契约末尾，不能用早期472项记录代表最新回归状态。

| 顺序 | 文档 | 当前应关注的内容 |
|---|---|---|
| 1 | [Phase 4 契约](control_phase4_contracts.md)、[Phase 3 契约](control_phase3_contracts.md) | 当前LLM接口/离线证据/真实验收门禁；P3生命周期、信息边界及E0历史证据 |
| 2 | [工程实现计划](cemas_v1_implementation_plan.md) | C节Phase 4–5的当前边界；D节为历史P0任务清单 |
| 3 | [推荐协议](llm_recommended_protocol_v1.md)、[JSON](control_protocol_v1.json) | 第4–7、12–14节和附录 A；配置作为数值来源，勿另写常量 |
| 4 | [Phase 2 契约](control_phase2_contracts.md) | 已有执行器、公共/私有数据路径及可复用接口 |
| 5 | [Phase 0 契约](control_phase0_contracts.md)、[Phase 1 契约](control_phase1_contracts.md) | 按需查共享类型、奖励抽象接口、DecisionRecord、mask 和动作解析 |
| 6 | [数据说明](../data/README.md) | E0 诊断序列及 daily tests 的重建数据口径，限定拟合证据范围 |

推荐协议和 JSON 负责规则与参数，工程计划负责实施范围，阶段契约负责接口及验收证据。旧方案和旧测试结果是历史记录，不是当前安装、运行或实验完成的证明。

## 3. 代码入口

| 文件 | 职责 |
|---|---|
| [protocol.py](../cemas/control/protocol.py)、[types.py](../cemas/control/types.py) | 静态配置验证及独立公共/私有类型；`objective_status` 来自已校验配置 |
| [scenarios.py](../cemas/control/scenarios.py) | `resolve_campus_parameters()` 为 E0 和控制场景提供独立参数容器；`build_scenario()` 返回已经初始化的 bundle |
| [environment.py](../cemas/control/environment.py)、[rewards.py](../cemas/control/rewards.py) | `WeeklyControlEnvironment` 推进七日窗口；`V1RewardCalculator` 及 `RewardBreakdown` 计算统一目标 |
| [actions.py](../cemas/control/actions.py)、[resolution.py](../cemas/control/resolution.py) | 共同编解码、mask、校验与回退，两种动作入口复用同一路径 |
| [execution.py](../cemas/control/execution.py)、[ledger.py](../cemas/control/ledger.py)、[metrics.py](../cemas/control/metrics.py) | 每日执行、公共交付和运营记录、私有感染 flow；用于日/周/终点对账 |
| [observation.py](../cemas/control/observation.py) | 纯公共观察构造与198维编码，mask 单独提供 |
| [controllers.py](../cemas/control/controllers.py)、[runner.py](../cemas/control/runner.py)、[logging.py](../cemas/control/logging.py) | 公共控制器及可选失败/审计出口、公共配置工厂、单回合编排、私有LLM调用日志和完成状态 |
| [llm.py](../cemas/control/llm.py)、[public_v1.json](../cemas/control/prompts/public_v1.json) | 无显式记忆LLM、纯公共两条消息、严格parser、固定本地计数资源及provider验收、transport/重试 |
| [calibration.py](../cemas/control/calibration.py) | 共享人口 E0 的拟合、独立评价、产物保存及兼容性核验 |
| [examples/control_v1/](../examples/control_v1/) | 固定参照/E0薄入口，以及 `smoke_llm.py`、`smoke_memory.py`、`run_llm.py`、`run_memory_llm.py`、`accept_memory_llm.py` |
| [tools/memory_acceptance.py](../tools/memory_acceptance.py) | 独立开发验收实现；原examples验收命令保留，正常控制包不加载或导出这些函数 |

v1 所有后续实验入口也放在 `examples/control_v1/`，运行时可复用逻辑放在 `cemas/control/`，独立开发验收实现放在 `tools/`。旧 t18 脚本和绘图保留，不创建 t23；旧四参数、旧人口产物不能作为 v1 E0 证明。

## 4. 接续时必须保持的边界

- 所有方法共用同一目标；λ=1、四类负担各0.25是开发起点。主敏感性为 λ=.5/1/2，内部权重扰动留作扩展；不能按最终测试或某方法优势选权重。
- E0 和校园控制共用完整 v1 人口配置，各用途种子独立。人口或基础模型变化须重新校准；控制 H/奖励变化本身不触发 E0 重校准。
- 控制器只接收公共观察和反馈。`PublicInfo` 仅含动作处理结果与公共周反馈；真值、reward、beta、seed、未来事件及完整审计/manifest 不进入控制器、prompt 或 memory。
- 训练向学习器返回真实 reward；评估返回 `0.0`，真实值通过 runner 私有的 `audit_snapshot()` 写日志。两种模式不改变世界轨迹。
- 保持五维动作、324组合和七日周期；公开 mask 只约束 S，T/C 的每日容量由 executor 处理。
- day0 先决策，每步最多七个真实日步；尾段按实际天数结算。只把完整周放入观察历史，尾段通过反馈和日志交付。
- `build_scenario()` 已初始化，环境不重复 initialize，周间不重新设 seed；完整回合只尝试 finalize 一次，close 幂等，进度独立于 finalize 后的 `sim.t`。
- 到 H 不额外推进、不提前交付 pending 事件。初始感染、感染新增、累计、峰值和终点活动状态分别核对。
- smoke 仅检查闭环；科学运行必须加载带独立评价的真实主窗 E0 产物，不能用裸 beta 或手填证明代替。最终实验还须通过后续统一冻结门禁。
- 当前指定Python为 `E:/pytroch/anaconda3/envs/simulation/python.exe`（本机3.10.20），P3旧环境快照作为历史保留。P4可选SDK/tokenizer依赖与版本闭包单独记录在 `requirements-control-llm-v1.in` / `.lock.txt`；测试工具使用本地隔离目录，不改共享环境。
- P4仅实现无显式记忆LLM基础链；真实API验收本轮按用户决定暂缓。P5按本次研究增加确定性公共记忆、数值检索、知识与依据输出、预算裁剪，不实现embedding或LLM反思；P6才做调优阈值、RL、训练、最终源库及权重/H冻结。

## 5. 下一次接续提示

```text
请先阅读 docs/CEMAS_READING_INDEX.md 及 P4/P3 契约，核对当前分支和未提交改动。
区分P4离线fixture结果、尚未完成的真实provider/tokenizer验收、P3历史E0证据；不能用离线通过来宣称真实LLM episode可用。
保持统一奖励、共享 v1 人口、公共/私有隔离、单次 initialize/finalize 及日周终点对账。
v1 脚本放在 examples/control_v1/，复用逻辑放在 cemas/control/，保留旧 t18 及用户文件。
先说明已完成项和剩余门槛，再按本轮用户指令继续；使用指定 simulation Python。
```

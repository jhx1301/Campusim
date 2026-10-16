# CEMAS v1 当前工作阅读索引

更新日期：2026-10-15。此索引用于接续 v1 开发，集中阅读现行协议、阶段契约和当前代码。

## 1. 当前进度

项目目标是在同一个部分可观测疫情控制任务中，让各控制器共享观察、动作、执行器和评价口径。

工作目录为 `D:/项目/毕业设计/code/Campusim`，v1 功能分支为 `feature/control-protocol-v1`，P3 实施前基线为 `8324a81`。当前提交和未提交改动以实际 Git 检查为准，保留已有 `docs/修改意见.md` 等用户文件。

| 阶段 | 内容与状态 |
|---|---|
| Phase 0 | 协议加载/静态验证、不可变 schema、Controller/RewardCalculator 接口、公共序列化和 DecisionRecord |
| Phase 1 | `[T,S,C,E,A]` 的 324 动作编解码、公共筛查容量 mask 和 ActionResolution |
| Phase 2 | campus 场景、共同执行器、公共 ledger/观察、198 维编码和独立私有指标 |
| Phase 3 | 已实现周环境、统一奖励、两个固定参照、日志/runner 和共享人口 E0；334项测试、完整smoke及主/辅助E0已验收，证据和拟合限制见 [P3 契约](control_phase3_contracts.md) |

P3 的公式和计数语义已确认，当前权重为可执行的 `development_candidate`。后续全部主方法的源域验证与 H 检查完成后再统一正式冻结；P3 闭环验收不代表权重验证、训练或最终实验完成。测试及实际 smoke/E0 结果只以契约中明确登记的证据为准，不能根据存在脚本就认定校准已经执行。

## 2. 按此顺序阅读

| 顺序 | 文档 | 当前应关注的内容 |
|---|---|---|
| 1 | [Phase 3 契约](control_phase3_contracts.md) | 设计选择、实际接口、生命周期、信息边界、E0 产物门禁和验收记录 |
| 2 | [工程实现计划](cemas_v1_implementation_plan.md) | C 节 Phase 3 的实施顺序及后续边界；D 节为历史 P0 任务清单 |
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
| [controllers.py](../cemas/control/controllers.py)、[runner.py](../cemas/control/runner.py)、[logging.py](../cemas/control/logging.py) | 两个固定参照、最小单回合编排、公共/私有日志及运行完成状态 |
| [calibration.py](../cemas/control/calibration.py) | 共享人口 E0 的拟合、独立评价、产物保存及兼容性核验 |
| [examples/control_v1/](../examples/control_v1/) | v1 薄入口：`smoke.py`、`calibrate.py`、`evaluate_calibration.py`、`run_references.py` |

v1 所有后续实验入口也放在 `examples/control_v1/`，可复用逻辑只放在 `cemas/control/`。旧 t18 脚本和绘图保留，不创建 t23；旧四参数、旧人口产物不能作为 v1 E0 证明。

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
- Python 为 `D:/programfile/miniconda3/envs/simulation/python.exe`。依赖按当前实装和用户授权核对，不把旧快照当作现在的安装状态。
- P3 不提前实现 LLM、PPO/DDQN、调优阈值、memory、训练或城市实验；后续按既定阶段推进。

## 5. 下一次接续提示

```text
请先阅读 docs/CEMAS_READING_INDEX.md 及 P3 契约，核对当前分支和未提交改动。
根据 P3 契约中的实际验收记录区分已有代码、测试、smoke 和 E0 证据，勿把脚本存在当作校准完成。
保持统一奖励、共享 v1 人口、公共/私有隔离、单次 initialize/finalize 及日周终点对账。
v1 脚本放在 examples/control_v1/，复用逻辑放在 cemas/control/，保留旧 t18 及用户文件。
先说明已完成项和剩余门槛，再按本轮用户指令继续；使用指定 simulation Python。
```

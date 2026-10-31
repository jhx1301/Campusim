# CEMAS v1 当前工作阅读索引

更新日期：2026-10-28。此索引用于接续 V1 开发；当前配置与校准接入以 [UW 控制接入](uw_control_integration.md)为准。Feedback以[新版统一设计](llm_feedback_component_design.md)和[实施合同](PLAN%20(1).md)为准；旧P5阶段范围和旧案例/规则结构不再约束新版。

## 1. 当前进度

项目目标是在同一个部分可观测疫情控制任务中，让各控制器共享观察、动作、执行器和评价口径。V1 功能分支为 `feature/control-protocol-v1`；当前提交、工作目录和未提交改动以实际 Git 检查为准。

当前模型使用 UW W1、69,457 人、初始感染 100，角色为本科生 31,650、非本科学生 13,890、教师 2,321、其他职员 21,596；`campus_k_ts=3`，员工社区背景乘数为 0.1，ta 背景乘数为 0.5（有效值 0.6）。weekly E0 已完成，背景迁移的 40 个评估世界与原记录完全一致。当前锚点为 `results/e0_v5_iso0_w1trace/weekly_background_v1_local/control_anchor.json`，β=0.038583333332。旧角色锚点及迁移前锚点不能直接接入当前运行。

| 阶段 | 内容与状态 |
|---|---|
| Phase 0 | 已实现协议加载/静态验证、不可变 schema、Controller/RewardCalculator 接口及公共序列化 |
| Phase 1 | 已实现 `[T,S,C,E,A]` 的 324 动作编解码、公共筛查容量 mask 和 ActionResolution |
| Phase 2 | 已实现 campus 场景、共同执行器、公共 ledger/观察、198 维编码和独立私有指标 |
| Phase 3 | 已实现周环境、统一奖励、固定参照和日志/runner；旧 E0 已由 `cemas/e0/` 的 UW 实现替代，旧验收仅作历史记录 |
| Phase 4 | 已实现公共 prompt、严格解析、本地计数、transport、重试、共同回退和调用审计；真实服务验收仍与离线验证分开 |
| Phase 5历史设计 | 记录早期公共记忆、数值检索、知识卡和只读源案例存储；当前持续学习已转入新版Feedback合同 |
| 新版Feedback | 单周案例、平铺参考周＋四自主周、LLM周经验、支持/相悖聚合规则、v2学习库和冻结评估 |
| Phase 6 | 已接入 Threshold、MaskablePPO、DDQN、源域训练/选择、覆盖诊断及发布校验；历史短训练不代表当前 UW 正式批次完成 |
| Phase 7 | 最终方法比较、迁移、统计和论文结论仍待前置校准、正式源域开发与共同冻结完成 |

既有RL baseline训练产物沿用已完成结果。新版LLM持续学习、共同冻结和正式方法比较应分别记录实际完成情况，不能根据已有脚本或历史工程测试数字认定科学评价已经完成。

快照入口见[精简快照 baseline 训练计划](baseline_snapshot_training_plan_v1.md)及[使用说明](baseline_snapshot_training.md)。新版LLM沿用既有RL baseline的种子和场景，恢复快照后先共同观察7天，再控制112天；持续学习和冻结评估使用[learn_memory入口](../examples/control_v1/learn_memory.py)。

## 2. 按此顺序阅读

| 顺序 | 文档 | 当前关注内容 |
|---|---|---|
| 1 | [UW 控制接入](uw_control_integration.md)、[E0 配置](e0_protocol_v2.json) | 当前模型、显式背景迁移、锚点证据与运行命令 |
| 2 | [P6 契约](control_phase6_contracts.md)、[P6 计划](control_phase6_implementation_plan.md) | 已有工程入口、历史验证、正式批次和共同冻结的剩余条件 |
| 2a | [快照 baseline 新计划](baseline_snapshot_training_plan_v1.md)、[使用说明](baseline_snapshot_training.md) | 新任务设计、快照库生成、训练入口、验证及未完成范围 |
| 2b | [Feedback统一设计](llm_feedback_component_design.md)、[实施合同](PLAN%20(1).md)、[人工样例](llm_feedback_component_examples.json) | 当前持续案例/规则学习、版本与统计、v2库及冻结评估 |
| 2c | [LLM三种子实验准备](llm_training_experiment_v1.md) | 独立库、32＋32回合且历史世界不重复、离线准备与启动命令；准备不代表实验已运行 |
| 3 | [推荐协议](llm_recommended_protocol_v1.md)、[控制配置](control_protocol_v1.json)、[记忆配置](control_memory_v1.json) | 共同任务/数值来源及当前独立 P5 配置 |
| 4 | [P5历史契约](control_phase5_contracts.md)、[P5历史计划](control_phase5_implementation_plan.md)、[架构依据](llm_architecture_research/02_recommended_architecture.md) | 追溯早期设计；弃用案例配对和规则协议以新版为准 |
| 5 | [P4 契约](control_phase4_contracts.md)、[P3 契约](control_phase3_contracts.md) | LLM 调用与审计、周生命周期、统一奖励和历史验收 |
| 6 | [P2 契约](control_phase2_contracts.md)、[P0 契约](control_phase0_contracts.md)、[P1 契约](control_phase1_contracts.md) | 按需查共享类型、执行、mask 和动作解析 |
| 7 | [数据说明](../data/README.md)、[E0 研究计划](../research/historical_epidemics/e0_calibration_research_plan.md)、[工程总计划](cemas_v1_implementation_plan.md) | 观察口径、研究假设与分阶段实施历史 |

推荐协议和配置负责规则与参数，工程计划负责范围，阶段契约登记接口和证据。P4/P5 服务验收报告仅供开发验证和留档，不是正常运行凭证；研究目录中的旧报告门禁描述以现行契约为准。

## 3. 代码入口

| 文件 | 职责 |
|---|---|
| [protocol.py](../cemas/control/protocol.py)、[types.py](../cemas/control/types.py) | 配置验证和公共/私有类型；协议仍含部分历史阶段标记，以阶段契约判定完成范围 |
| [scenarios.py](../cemas/control/scenarios.py) | 共享基础参数、人口登记和已初始化的场景 bundle |
| [environment.py](../cemas/control/environment.py)、[rewards.py](../cemas/control/rewards.py) | 七日推进、固定首周、统一奖励与终点对账 |
| [actions.py](../cemas/control/actions.py)、[resolution.py](../cemas/control/resolution.py) | 联合动作编解码、mask、校验与共同回退 |
| [execution.py](../cemas/control/execution.py)、[ledger.py](../cemas/control/ledger.py)、[metrics.py](../cemas/control/metrics.py) | 每日执行、公共交付与运营记录、私有感染流量 |
| [observation.py](../cemas/control/observation.py) | 公共观察和 198 维编码，合法 mask 单独提供 |
| [controllers.py](../cemas/control/controllers.py)、[runner.py](../cemas/control/runner.py)、[logging.py](../cemas/control/logging.py) | 控制器、单回合编排、调用/决策审计和完成状态 |
| [llm.py](../cemas/control/llm.py)、[public_v1.json](../cemas/control/prompts/public_v1.json) | 无显式记忆 LLM、两消息 prompt、计数、解析、transport 和重试 |
| [memory.py](../cemas/control/memory.py)、[memory_store.py](../cemas/control/memory_store.py)、[retrieval.py](../cemas/control/retrieval.py)、[llm_memory.py](../cemas/control/llm_memory.py) | 确定性公共记忆、案例构建/只读库、数值检索和 P5 控制器 |
| [feedback.py](../cemas/control/feedback.py)、[rule_memory.py](../cemas/control/rule_memory.py)、[learning_store.py](../cemas/control/learning_store.py)、[learning.py](../cemas/control/learning.py) | 平铺公开周、规则判断与检索、v2持久库及训练恢复 |
| [training.py](../cemas/control/training.py)、[rl/](../cemas/control/rl/) | 源域调参、RL 训练/选择及 Gym 适配 |
| [cemas/e0/](../cemas/e0/) | UW 观测、扫描/拟合/评估研究和校准锚点导出/验证 |
| [examples/control_v1/](../examples/control_v1/) | smoke、E0、固定参照、LLM、记忆和 Baseline 薄入口 |
| [collect_observable_memory.py](../tools/collect_observable_memory.py)、[memory_acceptance.py](../tools/memory_acceptance.py) | 案例采集/冻结/发布命令及独立服务验收工具 |

V1 控制实现位于 `cemas/control/`，UW 校准位于 `cemas/e0/`。旧 `covasim/llm_policy.py`、`covasim/llm_memory.py` 和 `campus_policy_agent` 不参与新决策链，但仍有公共导入、旧实验和源码哈希依赖，不能直接单删。旧 t18 和论文绘图保留用于历史追溯。

## 4. 接续时必须保持的边界

- 所有方法共用目标和执行；λ=1、四类负担各 0.25 是开发起点，不能按最终测试或某方法优势选权重。
- E0 和校园控制使用匹配的完整人口及基础模型，各用途种子隔离。人口/基础模型变化须重新校准；控制 H/奖励变化本身不改变 E0 基础模型。
- 控制器只接公共观察和闭合公共反馈。真值、reward、beta、seed、未来事件、模拟器及完整 audit/manifest 不进入 prompt、memory 或检索。
- 训练向学习器返回真实 reward；评估返回 `0.0`，真实评价写入 runner 私有审计。两者不改变世界轨迹。
- 五维动作共 324 组合，七日决策；公开 mask 只约束 S，T/C 每日容量由 executor 处理。
- 当前快照任务day0–6为共同观察，day7首次自主决策；随后112天控制，总119天、16次自主决策。尾窗按实际天数结算，不额外推进或提前交付pending事件。
- 每回合一次完整 initialize，周间不重新设 seed；保持 finalize、close 及日/周/终点对账语义。
- smoke 只检查工程闭环；科学运行必须加载兼容的真实 UW 主结果锚点及原始研究文件，最终实验还须通过正式 release 校验。
- 公开学习库与私有运行审计分离。训练持续追加独立单周案例和规则判断，正式评估只读冻结库；仍使用数值检索，不增加embedding。v1学习库拒绝使用，建立v2新库。
- 使用指定 simulation Python，依赖与历史快照说明见[文档入口](README.md#环境与依赖)；不要沿用其他机器路径或历史实装状态。

## 5. 下一次接续提示

```text
请先读 docs/uw_control_integration.md、docs/CEMAS_READING_INDEX.md 和 P6/P5 契约，核对 Git 状态与当前模型。
当前使用 weekly_background_v1_local/control_anchor.json（完整路径见上文）；40 世界背景迁移已核验。保持初始感染100、员工社区乘数0.1和ta乘数0.5，不复用旧角色或迁移前锚点。
区分已有工程入口、source 导出重建工具缺口、待执行正式批次、真实服务验证与共同冻结。
保持统一任务、公共/私有隔离、固定首周、单次 initialize/finalize 和终点对账；使用指定 simulation Python。
按用户指令继续，不启动未经本轮请求的长训练、采集或付费调用。
```

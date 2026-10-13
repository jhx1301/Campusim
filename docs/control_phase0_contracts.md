# CEMAS control v1：Phase 0 接口与 schema

本文件记录 2026-10-13 确认的工程契约，补充[推荐协议 v1](llm_recommended_protocol_v1.md)和[机器配置](control_protocol_v1.json)。schema 版本为 `cemas-control-schema-v1`。

Phase 0 只实现协议静态加载/验证、不可变数据类型、抽象接口、公共序列化及 hash、DecisionRecord schema、环境清点和测试。没有具体控制器、动作编解码或 mask 算法、reward 公式、模拟环境、记忆检索、RL 训练或实验编排。

## 控制器与动作边界

```text
Controller.reset() -> None
Controller.decide(PublicObservation) -> ActionProposal
Controller.observe(PublicWeekFeedback) -> None
ActionDecoder.decode(action_id: int) -> ActionVector
```

所有控制器对外返回 `ActionProposal(action, reasoning)`。LLM 的 JSON 仍是 `action/reason`，`reason` 映射为内部 `reasoning`；规则控制器可以不提供说明。PPO/DDQN 内部输出编号，后续通过同一个 decoder 转为向量再封装。decoder 不承担资源校验或回退。Phase 0 没有 decoder 实现。

`ActionVector.values` 固定为 `[T,S,C,E,A]`，长度5、档位范围 `[3,4,3,3,3]`。普通整数之外的布尔、浮点均拒绝；传入列表时复制成不可变 tuple。该类型统一用于控制器、日志、执行历史及后续 memory，不提供 P0–P4 转换。

Controller 不能持有或接收 simulator、environment、PrivateMetrics、私有 reward 或完整 DecisionRecord。具体实现从 Phase 4/6 开始，Phase 0 的 ABC 无法直接实例化。

## 公共与私有 schema

所有数据对象是 frozen/slots dataclass，嵌套类型显式校验，不接受自由扩展字典或 simulator 引用。模型日窗口的 start/end 两端均包含。人天、增长和代理比统一为float，零统一为0.0，避免相等数值因int/float或负零表示产生不同hash。

| 对象 | 字段与单位 |
|---|---|
| PublicPopulation | 总人口、固定五年龄段登记人数、学校/工作登记人数及交集；社区对象为全人口 |
| PublicResources | 当前临床/筛查日检测容量、日索引病例调查容量；不含未来资源排程 |
| PublicCost | 临床/筛查实际检测人次、交付通知人次；隔离、检疫、并集及学校/工作/社区限制人天 |
| PublicWeeklyRecord | 模型日窗口、交付诊断、PublicCost、执行向量、当时容量、增长/诊断检测代理比及各自有效标记 |
| PublicObservation | 决策日/H、公开初始感染总数、登记人口、当前资源/动作/各维持续天数、324位bool mask、四周记录与week_valid、前日已知隔离/检疫/并集人数 |
| PublicWeekFeedback | 已封闭的公共周记录及可选前周；允许终点不足7天的反馈窗口 |
| PrivateMetrics | 窗口、真实新增感染事件、初始感染、累计感染事件、窗口每日新增峰值、窗口终点活动感染人数 |
| ExecutedActionHistory | 不可变的 ExecutedAction tuple，每项包含实际执行窗口和ActionVector |

PrivateMetrics 的值由后续私有计数实现产生，终点活动感染按协议并集语义核对；Phase 0 不读取或聚合 simulator。

观察历史从最旧到最新排列，缺失周在左侧用零值 PublicWeeklyRecord 与 `week_valid=False` 表示；有效项只能是决策前完成的连续7天记录。增长和代理比无效时值为0，不将无历史解释为稳定。归一化、one-hot、ledger构建和mask生成均留到后续阶段。

PublicObservation 不包含感染真值、R_e、传播链、隐藏参数、未来事件/队列、seed、episode_id 或实验元数据。公开序列化只接受精确的 PublicObservation 类型，不能对私有记录全量序列化后再过滤。未来公共观察 builder 只接收交付ledger、登记人口、资源和执行动作。

## RewardCalculator

```text
RewardCalculator.compute(PrivateMetrics, PublicCost, ExecutedActionHistory) -> float
```

reward 与 environment/controller 独立，calculator 不持有 simulator，动作历史使用实际执行动作。PPO/DDQN 使用相同定义，LLM 离线评价采用相同成本口径。私有 reward 只能进入源域学习器和离线分析，不进入观察、public info、prompt、检索或公共反馈。

当前 JSON objective 保留原推荐参数供 Phase 3 源域确认，状态为 `recommendation_pending_phase3`。Phase 0 不计算reward，也不将推荐公式/权重复制成可执行默认值。Phase 3 确认后同步协议并版本化，最终测试前冻结，不能用目标测试选权重。

## DecisionRecord

记录由后续 runner 创建，Phase 0 仅提供不可变 schema 和 JSON 字典转换，不写 CSV/JSONL：

- `observation_hash`：公共基础观察的 SHA-256；UTF-8、键排序、紧凑JSON、不允许NaN。memory附加内容、私有指标及运行元数据不参与hash。
- `decision_day`、`decision_time`、`elapsed_ms`：模型日、带时区datetime及决策耗时毫秒。
- `controller_type`：llm/ppo/ddqn/threshold/minimum/maximum_feasible/uniform_legal_independent_rng；最后一项仅预留源域随机合法采集标识，没有实现策略。
- `action_proposal`、`executed_action`：请求与实际执行分开；请求失败时proposal可为空。
- `fallback_used`、`fallback_reason`、`adjustment_reason`：共同回退和调整情况。
- `reasoning`：公开决策说明，不包含私有状态。
- `retrieved_case_ids`：正整数案例ID tuple，默认空；Phase 5 启用。

序列化输出带schema版本，时间保留时区。完整记录不传回controller或memory；后续memory只使用允许的公共观察、执行动作和公共反馈。

## 初始化、版本与验证边界

每回合只执行一次完整 initialize；保留引擎内部多次设相同seed的行为，周间不重新初始化随机流。后续v1执行器对有效通知中的仍存活、未隔离康复接触者执行检疫；Phase 0 不实现处置。

历史tag为 `cemas-legacy-pre-v1`（原代码b8da645）；feature分支为 `feature/control-protocol-v1`。原协议文档单独保存为Git基线，每Phase独立提交。旧P0–P4仅作为历史实现，不维护兼容路径；旧测试校正用于核查当前历史代码，新v1契约测试独立。

指定Python为 `D:/programfile/miniconda3/envs/simulation/python.exe`。新控制契约自身仅依赖标准库；`cemas` 门面仍复用已有基础引擎导入。Phase 0 不安装依赖。`requirements-control-v1.lock.txt` 是当前实装环境快照，不是后续RL/embedding已验收的lock。

验收覆盖抽象接口、严格schema/不可变性、公共/私有嵌套隔离、空历史/有效窗口、公共hash稳定性、DecisionRecord格式、协议时域/资源/seed静态一致性、环境检查及适用的历史回归。真实模型调用显式排除。

### Phase 0 验证记录

指定Python运行以下离线套件：`test_control_contracts.py`、`test_control_protocol.py`、`test_control_environment_check.py`、`test_campus_llm_policy.py`、`test_llm_memory.py`、`test_cemas_import.py`、`test_campusLayer.py`，使用 `-m "not online" -q`：**109 passed、1 skipped、1 deselected**。跳过项是缺少embedding依赖的历史测试，排除项为真实在线API测试。

保留一项已有警告：`tests/pytest.ini` 中 `env` 选项因指定环境未安装pytest-env而不被识别。验证命令显式设置 `SCIRIS_BACKEND=agg`，没有为消除警告新增依赖。

环境检查报告位于 `results/control_v1_phase0/environment.json`（本地产物，不纳入Git）：Python3.11.14、基础包可发现，Optuna/torch/Gymnasium/SB3/sb3_contrib/sentence_transformers仍缺失。本阶段未安装依赖、调用模型、创建模拟环境或执行训练；生产传播和旧控制器代码未改。

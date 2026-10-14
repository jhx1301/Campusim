# CEMAS 推荐协议 v1 软件工程实现 Plan

本计划将[推荐实施协议](llm_recommended_protocol_v1.md)及配套[机器可读配置](control_protocol_v1.json)落实到工程接口；研究问题与设计理由保存在[归档研究方案](archive/llm_baseline_generalization_plan.md)。采用增量迁移：复用传播模拟核心，新增统一控制层，再迁移控制器、记忆和实验入口。

2026-10-14 文档整理：原确认清单的必要内容已合并到推荐协议第14节及附录 A，旧架构讨论由 Git 历史保留。本文“实测工程基线”和 D 节的 Phase 0 任务清单均为原始计划记录；Phase 0 路线中的“四份文档”指原始依据文档（基线提交 `55b12f2`），不代表当前文件清单。当前完成范围以各阶段契约及验收记录为准。

本轮已确认三项实施边界：

- 以推荐 v1 为准；多角色候选、在线仿真检验和预测偏差降权留到后续版本。
- 每回合只调用一次完整 `initialize()`，保留引擎内部设置 seed 的现有规则；周间不重新初始化随机流。
- v1 对仍存活、未隔离的已康复有效通知对象执行检疫。旧测试迁移、校正，**P0–P4 行为兼容不作为新版本验收要求**。

## A. 当前代码架构理解

### 1. 现有模块及迁移判断

| 模块 | 当前职责与问题 | 实施处理 |
|---|---|---|
| [cemas/__init__.py](D:/项目/毕业设计/code/Campusim/cemas/__init__.py) | CEMAS 门面，主要重导出 Covasim 与旧 LLM/记忆类 | 增量公开新控制接口；避免导入基础包时强制加载 Gym、torch |
| [covasim/sim.py](D:/项目/毕业设计/code/Campusim/covasim/sim.py:558) | 初始化、每日推进、传播与终点计算 | 复用 `initialize/step/finalize`；不重写日步和传播算法 |
| [covasim/people.py](D:/项目/毕业设计/code/Campusim/covasim/people.py:319) | 疾病状态、检测、诊断、隔离和检疫 | 复用检测及排程能力；由 v1 执行适配层处理交付记录和处置边界 |
| [covasim/population.py](D:/项目/毕业设计/code/Campusim/covasim/population.py:112) | 校园组织、动态层、hybrid 网络生成 | 复用网络生成；小范围增加人口登记元数据，保证实际人数可导出 |
| [covasim/interventions.py](D:/项目/毕业设计/code/Campusim/covasim/interventions.py:1604) | 旧 `campus_policy_agent` 同时负责观察、LLM、记忆、护栏、执行和日志 | 不作为新控制环境底座；新执行器复用其底层工具与参数更新方式 |
| [covasim/llm_policy.py](D:/项目/毕业设计/code/Campusim/covasim/llm_policy.py:379) | P0–P4、真值状态提取、prompt、API、旧评价 | 将新协议对应职责迁入独立模块；复用必要的传输、JSONL、hash 工具 |
| [covasim/llm_memory.py](D:/项目/毕业设计/code/Campusim/covasim/llm_memory.py:129) | SQLite 双阶段写入、短期压缩、全局检索 | 复用持久化与相似度计算方式；公共 schema、特征和反馈重新实现 |
| `examples/t15_*`、`t17_*`、`t20_*`、`t21_*` | 旧实验参数、种子、套餐、CPBU 汇总 | 保留历史入口，新增 v1 主入口；不直接扩写旧实验大脚本 |
| `examples/t18_campus_calibration.py`、`t18_campus_validation.py` | 旧校准与展示 | 迁移到统一 v1 校准模块，消除优化与展示时域不一致 |
| `tests/` | 引擎、校园、策略和记忆测试 | 保留适用的引擎测试；迁移控制用例，新增 v1 契约和隔离测试 |

新实现统一放在 **`cemas/control/`**。这样可以明确区分控制任务与传播引擎，避免继续增加 `campus_policy_agent` 的职责。

### 2. 必须解决的架构冲突

**公共数据来源冲突**

- `new_diagnoses` 当前可能在采样日计入未来阳性，不能代表实际交付诊断。
- 旧追踪提前设置 `known_contact`，不能代表已经通知。
- 新观察必须来自独立的交付 ledger，不能仅将旧观察中的感染字段换成诊断字段。

**控制信息冲突**

旧状态提取、记忆向量、趋势、文本和反馈包含真实感染、真实 `R_e`、传播层及未来病程信息。新控制器不能调用这些旧提取函数，也不能通过通用字典过滤来建立边界。

**动作及执行冲突**

- P0–P4 将检测、筛查、追踪和活动限制绑定，无法表达 324 个联合动作。
- 概率检测没有 v1 临床日容量。
- 旧筛查的周期分组、近期检测排除和跨路径去重不符合 v1。
- 旧套餐可能改变宿舍与 `ta`，新协议必须保持家庭类接触的政策乘数为 1。
- 旧真实感染护栏、模型自报 risk 豁免和保持期不得进入共同执行器。

**处置边界冲突**

旧引擎豁免已康复者的新检疫；死亡或延迟诊断还可能留下不应继续计负担的隔离标志。v1 执行适配层按本轮确认的规则处理，日终统计使用实际有效处置状态。

**校准、人口和实验冲突**

旧 E0 同时拟合多个层系数、使用 `R_e` 惩罚，并存在实际日数不一致；旧实验硬编码 beta、采用不同人口和初始感染、种子重叠、使用 CPBU 排名。均不能直接作为 v1 正式结果入口。

### 3. 实测工程基线

- Git 当前为 `master@b8da645`，已追踪文件无改动；四份设计文档及协议 JSON 尚未纳入 Git。
- 指定环境为 Python 3.11.14；Optuna、torch、Gymnasium、SB3、sb3_contrib、sentence_transformers 当前缺失。
- `requirements.txt` 与指定环境实装版本不同，不能视作该环境的有效 lock。
- 未发现可直接采用的 v1 校准、记忆库、训练权重或冻结 manifest。
- 导入与校园网络测试：**4 通过**。
- 策略与记忆离线测试：**26 通过、7 失败、1 跳过、1 在线测试排除**。失败主要是陈旧的套餐转换、prompt 和投票记录预期，先处理测试基线。

## B. 总体重构架构图

```mermaid
flowchart TD
    P["v1 协议配置与解析快照"] --> S["场景构建与人口登记"]
    S --> E["统一周控制环境"]
    O["公共观察：4周历史、动作、容量、mask"] --> C["统一 Controller 接口"]
    C --> L["LLM"]
    C --> R["PPO / DDQN"]
    C --> F["阈值 / 固定参照"]
    L --> V["共同动作校验、编码与回退"]
    R --> V
    F --> V
    V --> E
    E --> X["共同干预执行器"]
    X --> SIM["现有 Covasim 每日 step"]
    SIM --> PUB["公共交付与运营 ledger"]
    PUB --> O
    PUB --> M["公共短期经验与冻结源域案例库"]
    M --> L
    SIM --> PRI["私有感染与终点指标"]
    PRI --> T["源域训练奖励与离线评价"]
    E --> LOG["实验 runner、日志与 manifest"]
    PUB --> LOG
    PRI --> LOG
```

边界要求：

- 中央控制器只接收公共观察、公共任务定义和公共反馈。
- 执行器内部可以接触个体索引及疾病状态，以完成模拟干预。
- 私有奖励只提供给源域学习器及离线分析；不进入控制器观察、prompt 或记忆。
- LLM、PPO、DDQN、阈值和参照均通过同一个周环境、动作校验器和执行器。

## C. 分阶段 implementation plan

### Phase 0：版本基线、环境和接口准备

**目的：** 保存当前历史节点，建立可信测试基线和接口契约，使后续阶段不依赖新增训练库即可开始。

**修改文件**

- `tests/test_campus_llm_policy.py`：校正失配测试，迁移不适用于新协议的用例。
- 四份依据文档及 `docs/control_protocol_v1.json`：记录本轮确认的范围、初始化语义和康复者处置规则；不改变其他协议数值。

**新增文件**

- `cemas/control/__init__.py`
- `cemas/control/protocol.py`
- `cemas/control/types.py`
- `tools/check_control_environment.py`
- `requirements-control-v1.in`
- `requirements-control-v1.lock.txt`
- `tests/test_control_protocol.py`

**核心设计与输入输出**

```text
load_protocol(path) -> ControlProtocol
resolve_protocol(protocol, purpose, calibration_artifact) -> ResolvedProtocol
inspect_environment(python_executable) -> EnvironmentReport
```

`types.py` 定义公共、私有对象的独立类型：

- `ActionVector`、`ActionProposal`、`ActionResolution`
- `PublicPopulation`、`PublicResources`
- `PublicDailyRecord`、`PublicWeeklyRecord`
- `PublicObservation`、`PublicWeekFeedback`
- `PrivateDailyMetrics`、`PrivateWeeklyMetrics`

协议中的“本轮未修改代码/未安装依赖”等字段属于文档状态说明，不解释为未来运行配置。

**Git 路线**

1. 为 `b8da645` 创建历史 tag：`cemas-legacy-pre-v1`。
2. 创建 `feature/control-protocol-v1` 分支。
3. 精确提交四份依据文档、JSON 及其必要附件，保存协议基线；不使用 `git add .`。
4. 每阶段独立提交，记录验证结果；首个闭环验收后创建 milestone tag。
5. 不改写旧历史，不执行 force push；仓库所有权检查使用命令级 `safe.directory` 例外。

**兼容与验证**

基础 `cemas.Sim` 导入继续工作；不增加套餐转换兼容层。测试主契约逐步切换到 v1，P0–P4 只作为历史实现。

验证协议解析、配置约束、公共对象序列化边界及指定环境检查。默认测试显式排除 `online`。新增依赖在准备实际兼容安装清单后另行取得授权，安装验收完成才生成最终 lock。

---

### Phase 1：统一 action space 和公共动作语义

**依赖：** Phase 0。

**目的：** 先完成纯动作逻辑，供执行器和所有控制器共同使用。

**修改文件**

- `cemas/control/types.py`
- `cemas/control/protocol.py`

**新增文件**

- `cemas/control/actions.py`
- `tests/test_control_actions.py`

**核心接口**

```text
encode_action(vector[5]) -> action_id
decode_action(action_id) -> vector[5]
legal_action_mask(resources, population, action_spec) -> bool[324]
resolve_action(proposal, current_action, resources) -> ActionResolution
```

**行为设计**

- 顺序固定 `[T,S,C,E,A]`，档位为 `[3,4,3,3,3]`，编号公式严格采用 v1。
- 档位参数只从协议解析，避免在 LLM、RL、执行器各维护一份常量。
- 提供同一份公开动作语义、目标对象、容量单位、延迟和固定处置说明。
- RL 适配器输出普通整数编号；LLM、阈值及参照输出向量，统一进入校验路径。
- 非法请求保持当前合法动作；容量下降时仅将 S 降到最高合法档。
- `ActionResolution` 保存请求、执行向量与编号、错误、回退和调整原因。
- 每维持续时间依据实际执行动作更新，不使用单一 policy rank。

**兼容方式**

不将旧套餐映射为新联合动作；历史结果不得因为转换编号而成为 v1 数据。

**验证**

穷举 324 个动作编解码；验证三种容量分别产生 162/243/324 个合法动作；覆盖布尔、浮点、越界、非法资源、保持及 S 投影。相同公共资源下，各方法必须得到相同 mask。

---

### Phase 2：public/private observation 隔离与共同执行器

**依赖：** Phase 1。

**目的：** 建立真实交付的数据来源，并落实容量、去重、追踪和人天统计。这是信息隔离的关键阶段。

**修改文件**

- `cemas/control/types.py`
- `covasim/population.py`：仅增加必要登记元数据，不改变网络生成算法和既有返回结构。

**新增文件**

- `cemas/control/scenarios.py`
- `cemas/control/execution.py`
- `cemas/control/ledger.py`
- `cemas/control/observation.py`
- `cemas/control/metrics.py`
- `tests/test_control_execution.py`
- `tests/test_control_observation.py`
- `tests/test_control_metrics.py`

**核心类和接口**

```text
build_scenario(resolved_config, world_seed)
    -> Sim + PopulationRegistry + private_metadata

JointActionExecutor.initialize(sim)
JointActionExecutor.set_action(ActionResolution)
JointActionExecutor.apply(sim)

PublicLedgerAnalyzer.apply(sim)
PrivateMetricsAnalyzer.apply(sim)

build_observation(public_ledger, public_population,
                  current_action, resources, decision_day)
    -> PublicObservation

encode_observation(PublicObservation) -> fixed_order_float32_features
```

`build_observation()` 不接收 `Sim/People`。公共记录没有隐藏参数、个体索引、未来事件、seed 或运行标签。

**执行设计**

- 临床检测使用协议概率产生请求，按三组优先级执行，日上限 `0.02N`；超额请求当日失效。
- 筛查采用学校、非学校工作、其他三个互斥登记组；比例配额、最久未筛查优先、缺额重分。
- 两条路径统一记录实际检测，排除当天临床受检者及 `[t−3,t−1]` 实际受检者。
- 追踪只使用当日交付诊断，上限 `0.01N` 个索引病例，无欠单。
- 独立保存调查事件和待通知队列；实际交付日去重，死亡取消，降档不取消已排程通知。
- 检疫截止按有效事件的 `调查日＋14` 合并，已有检疫只延长。
- 康复接触者按本轮确认规则执行检疫；清理无效隔离残留后记录实际处置负担。
- E/A 每日按“基础层系数×当前乘数”绝对写回，避免重复叠乘；家庭层保持不变。

**人口与观察设计**

- 校园活动名单取持久 class/lab groups，不能取初始化为空的动态边。
- 实际抽取 staff 与剩余非学生分开记录，不用 `role==2` 冒充精确 staff 数量。
- 公共历史为四个完成周，最旧到最新、左侧零填充，保留有效标记。
- 严格采用 v1 的固定人口尺度、增长公式、代理比及 one-hot；mask 单独提供。
- LLM 文本和 RL 数值编码来自同一观察对象，不在目标数据上拟合归一化。

**兼容方式**

复用 `People.test()`、检疫排程、联系人查询、`get_quar_inds()` 和 runtime profile 的更新方式；不直接调用旧检测、筛查、追踪的完整 `apply()` 来冒充新规则。

**验证**

重点覆盖交付延迟、同日检测去重、两检测容量、筛查日期边界、通知合并与取消、康复者检疫、死亡隔离清理、家庭层保护、活动权重和 Q 并集。

固定公共记录后改变感染真值、beta、传播日志或未来队列，观察及其编码必须完全一致。

---

### Phase 3：Gym-style 周环境、固定参照与 E0 校准

**依赖：** Phase 2。该阶段形成第一个可运行功能里程碑。

**修改文件**

- `cemas/control/protocol.py`
- `examples/t18_campus_calibration.py`
- `examples/t18_campus_validation.py`

**新增文件**

- `cemas/control/environment.py`
- `cemas/control/controllers.py`
- `cemas/control/calibration.py`
- `cemas/control/logging.py`
- `examples/t23_control_protocol_v1.py`
- `tests/test_control_environment.py`
- `tests/test_control_calibration.py`

**环境接口**

```text
reset(seed, options) -> (PublicObservation, PublicInfo)

step(action_id)
    -> (PublicObservation, reward, terminated, truncated, PublicInfo)

action_masks() -> bool[324]
close()
```

先实现不依赖 Gymnasium 的同形接口；Phase 6 增加薄 Gymnasium 适配器，复用相同环境实现。

- 训练模式返回私有训练 reward；评估模式返回占位值，真实指标进入独立私有记录。
- runner 只将观察与 mask 传给冻结策略，不传 reward 或环境内部对象。
- `PublicInfo` 不包含真值、累计回报、seed、未来资源日期或 simulator 引用。

**时序与奖励**

- day 0 决策，历史为空；一个 step 推进最多七个真实日步。
- 保持引擎原顺序：状态预更新、接触更新、干预、处置后更新、传播、日终记录。
- 使用每日 flow 计算周量，不读取未 finalize 的累计差分。
- H112 对应 `n_days=111`、16 次决策；尾周不足七天仍正确结算。
- 达到任务 H 时 `terminated=True`，不 bootstrap；基础设施失败不伪装成正常结束。
- finalize 只执行一次；环境独立保存进度，避免 finalize 后 `sim.t` 回退造成误判。
- 固定参照为最低向量和当前最高资源合法向量，均走共同执行器。

**E0 校准接口**

```text
make_calibration_sim(beta, world_seed, window) -> Sim
fit_beta(protocol, reconstructed_data) -> CalibrationArtifact
evaluate_beta(artifact, evaluation_seeds) -> FitReport
```

迁移为仅拟合 beta、100 trials、每候选固定三个世界的归一化日诊断 MSE；删除新校准中的 `R_e` 惩罚。采用旧 t18 人口设置，主窗口 16 实际日、延迟 0；辅助留出从拟合起点连续推进。

产物包含 beta、数据与配置 hash、完整人口/引擎设置、trial、seed、独立误差及运行带。正式 runner 必须加载并核验产物，不能接受旧四参数文件作为 v1 校准证明。

**兼容与验证**

已有每日模拟调用继续使用；新入口不调用旧 `campus_policy_agent`。日志骨架在此阶段启用，不等 Phase 7 才开始记录。

先用小人口做生命周期和对账测试，再以 N12000、H112、smoke seeds、beta 0.016 跑两个固定参照。明确标记 smoke，核对：

```text
cum_infections = 30 + sum(daily_new_infections)
日量之和 = 周量之和 = 终点总量
```

同时验证 reset、尾周、终点 pending 事件、同世界同动作前缀重放。正式源域开发必须等待真实 E0 产物。

---

### Phase 4：LLM controller 重构

**依赖：** Phase 3；先实现无显式经验记忆版本。

**修改文件**

- `cemas/control/controllers.py`
- `cemas/__init__.py`

**新增文件**

- `cemas/control/llm.py`
- `tests/test_control_llm.py`

**统一控制器接口**

```text
Controller.reset()
Controller.decide(PublicObservation) -> ActionProposal
Controller.observe(PublicWeekFeedback)
```

公共任务、动作语义和目标在构造时注入；不注入 `Sim`、私有日志或实验 manifest。

**核心实现**

- `LLMController`：单控制器，保留共同四周原始历史。
- `build_public_messages()`：只序列化公共对象，使用 v1 专家知识和目标。
- `parse_action_response()`：仅接受 `action/reason`；五个普通整数，reason 非空、单行、≤120 字，拒绝额外字段。
- `LLMTransport`：独立供应商参数适配及可注入 mock client。
- 三次总尝试、固定 2/4 秒间隔、SDK 内部重试关闭、timeout120秒；解析失败用相同公共 prompt 重试。
- 输入预算 8000 token：先削减检索案例，再压缩附加短期总结；共同历史和任务字段不随记忆消融删减。
- 保存各次调用的请求/返回型号、响应、usage、延迟和错误；最终失败交共同回退器。

模型参数沿用 v1。真实服务是否接受请求、实际返回版本和 token 计数方式通过源域 API 验收取得，不能提前宣称成功。

**兼容方式**

新 parser、prompt 和控制器独立于旧套餐接口；不保留 `risk` 的执行豁免。旧文件只提供必要的通用工具复用。

**验证**

使用 mock 验证 schema、重试次数、供应商参数、预算裁剪、审计字段和共同回退；检查隐藏真值不影响 prompt。真实付费验收单独进行，不进入默认单元测试。

---

### Phase 5：公共 memory 重构

**依赖：** Phase 4。最终建库另依赖 Phase 6 的阈值调优。

**修改文件**

- `cemas/control/llm.py`
- `cemas/control/controllers.py`

**新增文件**

- `cemas/control/memory.py`
- `tools/collect_observable_memory.py`
- `tests/test_control_memory.py`

**核心接口**

```text
EpisodeMemory.reset()
EpisodeMemory.begin(public_observation, executed_action)
EpisodeMemory.complete(public_week_feedback)

ObservableMemoryStore.add_completed_case(public_case)
ObservableMemoryStore.retrieve(public_query) -> public_cases
organize_short_term(completed_public_weeks) -> PublicMemoryContext
```

所有接口均不接收 simulator 或私有 reward。

**实现内容**

- 复用 SQLite 两阶段写入、真实只读连接及查询组织方式；建立独立公共 schema。
- 新库固定为 `observable_source_memory_v1.sqlite`；旧真值向量、文本和反馈不迁入。
- 短期组织四个完成周，以五维执行动作、资源和公共后效描述轨迹。
- 周反馈在下一决策前封闭，末周在终点封闭；不得读取未来结果补写。
- 状态、趋势和文本全部采用 v1 公共字段；相似度与固定尺度按协议实现。
- 删除层相似度，权重为 `.4 / 4⁄15 / 1⁄3`；top_k6，同执行组合最多两例，同分按 case_id 排序。
- embedding 固定 revision 和本地 hash，正式评估禁止下载或静默替换。
- 四种消融只开关短期组织/全局检索，共同原始历史、专家和模型参数一致。
- 来源 seed 等追溯信息独立存放，不进入案例展示或检索返回对象。

**建库依赖**

先以测试案例和三个简单策略验证模块。阈值调优完成后采集协议规定的 27 世界×4 策略，共108轨迹；通过公共反馈和覆盖审计后冻结最终库。

**兼容与验证**

旧库保留为历史产物，新库不做污染数据迁移。验证公共键、文本、反馈和检索的真值不变性；只读写入阻断、回合清空、末周封闭、seed 分离、embedding 离线加载和目标运行前后库 hash 不变。

---

### Phase 6：PPO、DDQN、阈值及源域开发

**依赖：** Phase 3 的环境和真实校准产物；LLM/记忆模块按 Phase 4–5 接入源域验证。

**修改文件**

- `cemas/control/controllers.py`
- `cemas/control/environment.py`
- `requirements-control-v1.in`、lock

**新增文件**

- `cemas/control/rl/ppo.py`
- `cemas/control/rl/ddqn.py`
- `cemas/control/training.py`
- `cemas/control/worker.py`
- `tests/test_control_rl.py`
- `tests/test_control_training.py`

**核心接口**

```text
GymControlEnv -> Gymnasium observation/action/step interface
PPOController.predict(public_features, legal_mask) -> action_id
DDQNController.predict(public_features, legal_mask) -> action_id
ThresholdController.decide(public_observation) -> ActionProposal
train_controller(source_config, train_seed) -> checkpoint_records
select_checkpoint(validation_A, validation_B) -> FrozenControllerArtifact
```

**实施顺序**

1. 安装并锁定验收后的依赖。
2. 实现并调优公共阈值控制器。
3. 完成最终源域案例库。
4. 实现 MaskablePPO 和真正的 Double DQN。
5. 全方法源域验证、预算/H 门槛检查及冻结。

**算法要求**

- PPO 使用协议网络与超参数，mask 在环境内实现；训练和评估使用 mask-aware 路径。
- DDQN 在线网选择合法 argmax，目标网取该动作值；探索、贪心和 bootstrap 均 mask，replay 保存 next mask。
- 两算法均使用公共数值观察、324 动作和相同私有目标，gamma1。
- 阈值采用 v1 指标、边界、迟滞及 32→4→1 的源域筛选。
- 控制器使用本地 RNG；RL 仿真使用独立进程隔离世界随机流。先验证一个环境，不同时推进多世界。
- 三个训练 seed 全部保留；按 A/B 选择 checkpoint，不选最好训练 seed 代表算法。

**预算与 H**

执行四回合 pilot，记录首次 JIT、稳态模拟和训练耗时。按 v1 的预算阶梯和源域曲线决定是否升级，记录实际仿真量。

H 若从112延长，统一更新全部方法的时域和尺度，重新开发、选参及采集记忆，然后冻结；最终测试不得触发这些调整。

**兼容与验证**

采用延迟导入，基础仿真不因 RL 依赖缺失而失效。先用合成网络输出测试 Double 更新和非法最大 Q，再做短训练验证；覆盖终点不 bootstrap、mask 一致、checkpoint 选择、随机流隔离和池间不交叉。

---

### Phase 7：完整实验入口、冻结、日志与统计

**依赖：** 全方法源域开发和首个闭环验证完成。日志骨架已有，本阶段扩大实验编排能力。

**修改文件**

- `examples/t23_control_protocol_v1.py`
- `cemas/control/logging.py`
- `cemas/control/scenarios.py`

**新增文件**

- `cemas/control/experiments.py`
- `cemas/control/statistics.py`
- `tests/test_control_experiments.py`
- `tests/test_control_replay.py`
- `tests/test_control_statistics.py`

**入口与数据接口**

```text
run_experiment(protocol, purpose, experiment, method, frozen_artifacts)
    -> run_manifests

run_episode(resolved_run, controller) -> RunResult
validate_freeze(artifacts, purpose) -> validation_report
replay_prefix(prefix_record, resolved_world) -> verified_state
summarize_paired_results(run_manifests) -> tables_and_intervals
```

每个运行目录输出：

- `public_daily.csv`
- `private_daily.csv`
- `decisions.jsonl`
- `private_weekly_rewards.csv`
- `summary.json`
- `manifest.json`
- 失败记录

manifest 保存完整解析引擎参数、版本/hash、用途、seed、配对关系以及校准、模型、prompt、记忆、embedding、checkpoint 版本；不传给控制器。

**实验实施**

- E1/E2：全部开发项冻结后运行；E2 复用 E1 中等条件的完整/无记忆轨迹，只新增两分支。
- E3：生成协议年龄分布的 hybrid `popdict`，通过实际 `Sim(people=popdict)` 接口使用；学校/工作名单与网络生成条件一致，验证筛查和活动映射。
- E4：day0–27共同最低干预，day28接管；高保持在28变高，待解锁在42/56变高。
- E4 同方法分叉前复用一次决策响应、检索和实际动作，通过世界重放核对疾病、网络、交付队列、公共历史及控制器状态；不依赖 `deepcopy(sim)` 自动保存全局随机流。
- lambda 补充及第二模型开发配置在首次读取可复用最终测试结果前冻结。
- 正常 LLM 失败保留回退轨迹；基础设施失败保留 attempt，按同身份同版本重放，不覆盖原记录。

**统计与验收**

按 world 块保持配对，再重采样 RL 训练 seed；bootstrap10000、seed83001。报告原始指标、区间和预定配对差，不使用 CPBU 排名，不把复用轨迹或时间点当独立样本。

验证冻结门禁、seed 池、重复身份保护、失败保留、E4 前缀一致、未来日期无泄漏、复用不增加样本量及日周终点对账。

## D. 第一阶段具体执行任务列表

**下一次编码范围为 Phase 0。首个功能交付里程碑为 Phase 0–3：一个校园条件、两个固定参照、统一观察/动作/周环境和完整对账日志。**

Phase 0 按以下顺序执行：

1. **保存 Git 历史节点**  
   核对状态，创建 legacy tag 和功能分支，精确提交依据文档及协议配置。

2. **登记本轮已确认规则**  
   写明 v1 范围、一次完整初始化语义、康复者检疫及旧套餐兼容边界。

3. **处理现有测试基线**  
   逐项校正七个陈旧预期；可复用的执行与日志用例保留，套餐专属用例不作为 v1 契约。

4. **建立依赖检查工具**  
   使用指定 Python，输出必要包版本、缺失依赖和 CPU 环境，不读取或输出凭据。

5. **建立 `cemas/control/` 包骨架**  
   仅引入基础依赖，确认普通 `cemas` 导入不加载训练库。

6. **实现协议加载与解析**  
   检查动作结构、N/H、缩放、资源、参考尺度和 seed 范围；smoke 与正式用途明确区分。

7. **定义公共及私有类型**  
   禁止公共对象携带 simulator、真值、未来队列及运行元数据。

8. **冻结公共序列化契约**  
   明确字段顺序、单位、有效标记和 schema 版本，为后续 LLM/RL 同源编码提供依据。

9. **增加 Phase 0 验证**  
   协议解析、用途门禁、公共字段边界、基础导入及迁移后的离线测试全部运行；默认排除在线测试。

10. **提交阶段成果并记录下一门槛**  
    保存环境报告、测试结果与 Phase 0 commit。随后进入 Phase 1 动作编解码和 mask；不在此阶段安装依赖、调用模型、训练或改动传播核心。

beta 校准结果、最终 H/预算、实际依赖版本、服务返回型号和 embedding revision 均由后续实际验收产生。它们是必须生成并冻结的工程产物，不以设计值冒充完成结果。

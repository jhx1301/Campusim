# CEMAS control v1：Phase 2 执行与公共观察契约

> 2026-10-23：本文的旧校准、人口及验收数字为历史记录。当前唯一标准和运行入口以 [UW 控制接入](uw_control_integration.md) 为准；旧结果不作为 UW 验收。

Phase 2 建立统一的运行时数据路径：

```text
ActionProposal -> resolve_action -> ActionResolution
              -> JointActionExecutor -> Covasim Sim
Sim -> PublicLedgerAnalyzer -> PublicLedger -> PublicObservation
Sim -> PrivateMetricsAnalyzer -> PrivateMetrics（仅 reward / offline analysis）
```

## 运行边界

`ActionVector` 仍表示相对于固定环境运行基线的额外政策干预强度。控制器只接收
`PublicObservation`；`Sim`、`People`、个体索引、beta、感染真值、私有指标、seed、
调查队列和未来事件都不进入公共 ledger 或 observation。固定基线属于
`environment_configuration`，不进入观察。

场景通过 `build_scenario(protocol, world_seed, ...)` 构建。每个场景只调用一次完整
`sim.initialize()`；世界随机流沿用模拟器已设置的流，不在周边界重新设 seed。Phase 2
只支持 campus 场景。`purpose="smoke"` 使用协议中明确标记的 smoke beta；
`purpose="scientific"` 必须由调用方提供已校准 beta，构建器不会把 smoke 值冒充校准结果。

## 动作解析与执行

`resolve_action()` 只应用决策时可提前确定的公开约束。当前公开筛查容量使非法的
`S` 请求保留在 `requested_action`，并回退到当前动作；容量下降使当前 `S` 投影到
最高合法档。临床检测和接触追踪容量是每日运行时约束，由 executor 记录 unmet 工作量，
不会静默改变动作 level。非法 controller 输出必须先由上层解析为缺失 proposal，随后
通过 `fallback_reason` 进入 `ActionResolution`。

`JointActionExecutor` 只执行 `resolution.executed_action`。动作和资源只能在决策日、
且该日开始前设置。它返回不可变的 `PublicDailyRecord`；重复调用 `finish_day()` 是
幂等的。记录包含已交付诊断、实际检测/通知、隔离/检疫/并集人天、登记组活动限制
人天、执行动作和当日公开容量。执行审计、个体索引和通知队列保留在 executor 私有状态。

检测按 T 的病例相关优先级和公开临床日容量执行；筛查按学校、非学校工作、其他三个
互斥登记组进行最大余数配额分配，使用固定人口 `N`，并对两条检测路径统一去重：死者、
已知诊断、当日临床检测者和前 3 日任一路径实际检测者不重复筛查。筛查请求超过公开
screening capacity 时由 Phase 1 mask 提前禁止。追踪仅调查当日实际交付诊断，上限为
公开索引病例容量；通知事件按调查日、交付日、scope 和对象记录，交付时去重，死亡取消，
降档不取消已排程事件。有效通知可对存活且未隔离的康复者执行检疫。

E 只作用于课堂层，A 只作用于非课堂工作、公共和社区层；每日以固定基础 beta 乘以
当前 level 的乘数绝对写回，家庭层不改变。登记名单来自持久 class/lab groups，权重
按学校、工作、社区名册固定计算。

## Ledger、观察与私有指标

`PublicLedger` 只保存从模型日 0 连续追加的 `PublicDailyRecord`。`aggregate_week()`
拒绝混合执行动作或容量；`full_history(decision_day)` 返回决策日前完整的、最旧到最新的
四个七日窗口，左侧以 `week_valid=False` 和零记录填充。增长值只在存在前一完整周时
计算为 `log2((D_current + 1)/(D_previous + 1))`；诊断/检测代理比在分母为零时无效。

`build_observation()` 是纯公共函数，只接收 ledger、固定 `PublicPopulation`、当前
动作、资源、决策日及显式任务常量。`encode_observation()` 产生固定顺序的 float32
向量（版本 `cemas-public-observation-float32-v1`，当前 198 个特征）；动作 mask
作为单独的布尔输入，不编码进向量。计数、容量和人天使用固定 `N`、7N、登记组目标
等尺度，不进行 clipping 或目标数据拟合；无效整周整块置零。改变感染真值、beta、
传播日志、私有队列或 seed，不应改变同一公共输入的 observation/hash。

`PrivateMetricsAnalyzer` 只从模型每日感染 flow 和 active 状态记录私有指标，提供
`PrivateMetrics` 窗口聚合。该分支不被 observation、公共反馈、controller、prompt 或
memory 使用。

## Phase 2 验收边界

本阶段覆盖协议驱动的 campus 场景、动作解析、执行审计、筛查/检测/追踪容量与去重、
通知生命周期、隔离清理、活动人天、ledger 周窗口、观察编码和 private/public 隔离。
Gym-style 周环境、reward 公式、具体 controller、LLM、PPO/DDQN、memory、E0 校准和
正式实验 runner 属于后续阶段。

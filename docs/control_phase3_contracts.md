# CEMAS control v1：Phase 3 周环境、奖励与 E0 契约

本契约记录2026-10-15确认的 P3 设计及接口，与[推荐协议](llm_recommended_protocol_v1.md)、[JSON](control_protocol_v1.json)和[工程计划](cemas_v1_implementation_plan.md)配套。实施前代码基线为 `feature/control-protocol-v1@8324a81`；具体测试和运行证据见末节，不由接口存在推断验收已经完成。

P3 交付统一周环境、独立奖励、最低/最高资源合法两个固定参照、日志和最小单回合 runner、共享人口 E0 及其产物门禁。仍固定五维动作、324组合、七日周期。LLM、PPO/DDQN、调优阈值、memory、训练和完整实验编排留到后续阶段，旧 t18 及绘图保留。

## 1. 奖励和冻结边界

所有方法使用同一目标：

\[
r_k=-\left[\frac{\Delta I_k}{N}+\lambda\left(
w_T\frac{\Delta T_k}{0.12NH}+w_L\frac{\Delta L_k}{0.10NH}
+w_Q\frac{\Delta Q_k}{NH}+w_A\frac{\Delta A_k}{NH}\right)\right].
\]

| 项 | 计数及单位 |
|---|---|
| I | 已完成窗口内真实新增感染事件；不含初始感染 |
| T | 实际临床检测与筛查检测人次之和 |
| L | 实际交付通知人次；同日同人去重，跨日可重复 |
| Q | 每日日终隔离/检疫并集人数之和；同日重叠只计一次 |
| A | 学校、工作、社区名义活动限制人天之和；使用 reset 时登记的固定活动预算 |

回合内 N/H 固定，尾段使用实际计数，分母保持完整 N/H。T 的参考量是 `.12NH`，L 是 `.10NH`，均不随当周资源缩小。超参考值不裁剪。Q 与 A 是不同负担维度，允许同一人同时贡献，不解释成货币成本。

开发候选为 `formula_version=cemas-reward-v1`、`status=development_candidate`、λ=1，四项负担权重各0.25、和为1；γ=1，无切换惩罚、奖励裁剪、额外终点奖励。等权与参考尺度共同规定取舍，不代表真实单位成本相等。H112时，一例新增感染分别等价于53.76次检测、44.8次通知或448个处置/活动限制人天。

P3确认公式结构、计数语义与可执行候选；`reward_formula_confirmation_phase=3` 与 `reward_parameters_freeze_phase=6` 分开。后续全部主方法源域验证及 H 检查通过后，统一冻结权重、H和参考尺度为 `frozen`；`objective_status` 从已校验配置读取。不能按最终测试结果、某方法优势或不同目标下综合分数的绝对大小选权重。

主敏感性为 λ=.5/1/2，四项仍等权。先用开发轨迹重打分检查量级和排序敏感性；改变目标后的策略比较必须重新源域训练/选参，不能用固定轨迹重打分代替。内部单项权重乘.5/2再归一作为后续扩展，不在 P3增加训练流程。

保留抽象接口：

```text
RewardCalculator.compute(PrivateMetrics, PublicCost, ExecutedActionHistory) -> float
V1RewardCalculator(protocol, population, execution_days)
V1RewardCalculator.breakdown(...) -> RewardBreakdown
```

`RewardBreakdown.normalized/weighted` 固定按 I/T/L/Q/A 顺序，`positive_cost` 为加权和，`reward=-positive_cost`。奖励计算与日志复用同一结果，不由动作等级估算工作量；`configuration` 记录版本、权重、参考尺度及实际 N/H。calculator 不持有环境、控制器或 simulator。

## 2. 周环境与信息边界

```text
WeeklyControlEnvironment(protocol, mode='evaluation', purpose='smoke', scenario_options=None)
reset(seed, options=None) -> (PublicObservation, PublicInfo)
step(action_id) -> (PublicObservation, reward, terminated, truncated, PublicInfo)
step_proposal(proposal, fallback_reason=None) -> 同一返回
action_masks() -> bool[324]
audit_snapshot() -> EpisodeAuditSnapshot
close()
```

`step(action_id)` 先经共同 decoder 转为 ActionProposal，随后委托 `step_proposal()`；只有一个 resolve/执行主线。编号非法、资源调整及回退保留审计。`Controller.reset/decide/observe` 接口不变，runner负责 reset 控制器。

| 环节 | 契约 |
|---|---|
| reset | 新建 ScenarioBundle，清空回合状态；`build_scenario()` 已 initialize，直接使用实际挂接的 executor/analyzer，不重复初始化 |
| 第0天 | 先返回空历史和零持续时间，先决策再推进 day0；公开初始感染总数不当作已交付诊断 |
| 日推进 | 从 d 到 `min(d+6,H-1)` 逐次 `sim.step()`；保留引擎日内顺序，不周间设 seed、不按周调用默认 `sim.run()` |
| 窗口结算 | 公共反馈、私有 metrics 和奖励使用同一个闭区间；使用每日 flow，不把累计量差分和新增量混用 |
| 尾段 | 按实际日数结算，不补齐、不放大；不足七天只进入 feedback/日志，不进入完整周观察历史，198维编码保持不变 |
| 终点 | 完成 H 个日步返回 `terminated=True,truncated=False`，不 bootstrap，不按隐藏感染灭绝提前停 |
| finalize | 环境独立保存进度和 `finalize_attempted`；完整回合只尝试一次，失败不重试；不能依据 finalize 后的 sim.t 判断剩余步数 |
| close/reset中断 | close幂等；未完成回合记 aborted，基础设施异常记 failed，不伪装为正常完整结果 |

到 H 后不再决策或推进，不提前交付 pending 诊断、通知，不延长隔离/检疫人天。已执行检测仍计入T；pending数量只保存在私有审计，不能在清理时转成公共交付。

`PublicInfo` 是不可变白名单，仅含 `resolution`、`feedback`，reset时为空。观察和反馈均只从已完成公共记录构造。训练模式向学习器返回真实标量reward；评估模式返回 `0.0`，真实值另存私有日志。两模式的世界随机流、执行路径和公共轨迹一致。

感染真值、真实R_e、beta、seed、未来事件、Simulator/People、完整DecisionRecord和manifest不得进入控制器、prompt、memory或PublicInfo。公开初始感染总数仍是既有公共任务常量。学习器收到reward不表示可将其作为下一步策略输入特征。

`audit_snapshot()` 是仅供runner/日志的私有通道，返回不可变公共日记录、私有日指标、窗口奖励、终点指标、状态及配置快照；不返回模拟器或可变runtime对象。`WindowAudit`、`EpisodeAuditSnapshot` 不能传给Controller。

## 3. 固定参照、日志与入口

最低向量为 `[0,0,0,0,0]`；T0/C0的例行基线和共同隔离检疫仍存在。最高资源合法向量为 `[2,Smax,2,2,2]`，Smax仅从公共mask取得，T/C每日容量仍由执行器处理。两者经过相同校验、执行、奖励和日志路径，不要求最高参照逐随机样本感染都更少。

最小runner只编排单回合：向Controller传公共观察/反馈，创建DecisionRecord，调用环境，并将私有快照交给logger。环境推进、奖励计算、决策与写日志各自独立；logger不重新实现计数和目标。只有 finalize、对账及日志落盘均成功才登记运行completed，失败保留记录，不覆盖既有成功产物。

| 产物 | 口径 |
|---|---|
| `public_daily.csv`、`public_weekly.csv` | 已交付诊断、实际检测/通知、处置和活动人天、实际动作和当时资源 |
| `decisions.jsonl` | 公共观察hash、请求/实际动作、回退/调整原因、耗时 |
| `private_daily.csv` | 私有感染flow、初始项、累计与活动感染 |
| `private_weekly_rewards.csv` | 同一窗口日数、原始量、归一化/加权分项、真实reward和版本 |
| `summary.json`、`manifest.json`及失败记录 | 状态、终点汇总、完整解析配置、用途、种子、版本/hash及校准来源 |

“公共日志”表示字段口径，不表示整个文件自动提供给controller。含个体索引的 `DayExecutionAudit` 不得整体导出到公共日志。

所有 v1 编排和入口位于 `examples/control_v1/`：

- `smoke.py`：协议smoke世界、两个参照，默认N12000/H112/beta=.016，明确 `calibration_verified=false`。
- `calibrate.py`：拟合并保存主窗或辅助窗E0，支持 `window=primary/exploratory`。
- `evaluate_calibration.py`：对已有拟合产物做规定的独立世界评价，保存FitReport。
- `run_references.py`：加载带独立报告的真实主窗E0后运行固定参照，属于校准后开发检查，不宣称最终实验。

可复用逻辑位于 `cemas/control/`。旧 t18 和绘图保留，不创建 t23、不重复实现校准逻辑。

## 4. 共享人口 E0 与产物门禁

E0和后续校园控制使用同一套v1人口配置，以协议engine为唯一来源：N12000、初始感染30、三段年龄比例 `.60/.20/.20`、全部校园生成参数、网络和病程设置。`resolve_campus_parameters()` 是纯参数构造函数，每次返回独立容器；各用途使用独立seed，不要求同一个随机人口实现。

E0安装 `test_num`，控制环境安装共同执行器，各自只初始化一次。E0检测敏感度.95、失访0、延迟0，控制环境延迟1，分别记录。12000是合成总人口，不等同于原报告约12000名学生；旧t18人口下的多参数结果不迁入新校准。

```text
read_calibration_data(path) -> CalibrationData
make_calibration_sim(protocol, beta, world_seed, window='primary', data=..., through_holdout=False)
fit_beta(protocol, reconstructed_data, window='primary'|'exploratory') -> CalibrationArtifact
evaluate_beta(artifact, evaluation_seeds=None, protocol=None) -> FitReport
save_calibration_artifact(artifact, output_dir) -> artifact.json
save_fit_report(report, output_dir) -> fit_report.json
load_calibration_artifact(path, protocol, require_evaluation=True) -> CalibrationArtifact
```

仅拟合beta∈[.005,.04]，固定层系数，100 trials、优化器seed84001、每候选三个固定校准世界。损失为逐世界日诊断MSE的平均，再除以 `(观测日均值+1)^2`；不是平均曲线MSE，不加累计诊断或R_e惩罚。

| 用途 | 实际日步与世界 |
|---|---|
| 主窗拟合 | 2020-08-03至08-18，16步、n_days15；10001–10003 |
| 主窗独立评价 | 相同16日窗口，10021–10040，输出逐世界MAE/RMSE、累计诊断误差、均值及5%–95%运行带 |
| 辅助拟合 | 08-03至08-14，12步、n_days11；10101–10103 |
| 辅助留出 | 10121–10140从08-03初始化并连续推进到08-18，仅评价08-15至08-18；不得在留出起点用真实状态重置 |

数据只支持“重建聚合诊断序列的拟合与计数核查”，daily tests亦为重建输入。留出有已知未来检测输入，不扩大为长期无条件预测验证；不将干预后反事实差异称为独立因果证明。贴边/较大误差保留诊断并限定主张，不增加自由层参数改善曲线。

`CalibrationArtifact`保存窗口、beta、trial及失败状态、数据及hash、完整解析设置、人口统计、用途种子、版本、最佳逐世界轨迹和内容hash；`FitReport`保存独立世界、曲线、误差与产物关联。保存采用独占创建，避免覆盖旧产物。

科学环境要求真实主窗 `artifact.json` 及同目录匹配的 `fit_report.json`，核对内容hash、校准设置、数据、规定世界、trial/最佳损失及人口/基础模型兼容性。`require_evaluation=False`仅供独立评价入口读取尚未评价的拟合，不作为科学运行绕过。拒绝裸beta、旧四参数文件、旧人口、缺失报告或损坏/不兼容证据。hash是完整性与版本检查，不是可信第三方认证；不能仅凭重新计算hash把手填数据解释成真实校准。

人口、基础模型及实现来源用于兼容核验，完整协议hash用于追溯。控制H/奖励变化本身不触发E0重校准；人口或基础模型变化使旧产物不兼容。已核验E0与目标正式冻结是不同门禁：源域开发可使用候选目标，最终实验仍须后续冻结产物，不把科学参照运行等同于最终测试。

## 5. 验收与证据

核心对账为：

\[
I_{final}=I_0+\sum_d I_d=I_0+\sum_k\Delta I_k\le N,
\qquad \sum_d C_{j,d}=\sum_k\Delta C_{j,k}=C_{j,summary},
\qquad -\sum_k r_k=J_{summary}.
\]

- 日量、周量和终点量：分别核对两检测路径、通知、隔离/检疫/并集、学校/工作/社区活动；整数严格相等，浮点采用固定容差。累计量不逐周相加，峰值取max，终点活动状态取末值。
- 生命周期：H7/8/10/15覆盖完整周和尾段；H112恰有112条日记录和16次决策。验证day0、reset、单次initialize/finalize、close幂等、终点后拒绝step及日步/finalize/日志失败。
- 信息与时序：公共记录不变时私有真值、seed、未来队列不影响观察/hash/PublicInfo；训练/评估同世界同动作轨迹一致；pending不提前交付，尾段不放大，初始感染不收费，终点不重复追加总奖励。
- 动作与重放：动作编号/提案执行一致，非法请求审计及共同回退正确，同世界同动作前缀可重放。
- 校准：共享人口配置及容器独立；loss平均顺序、窗口日数、种子隔离、连续留出及产物拒绝路径正确；smoke不能冒充E0。

实施顺序为契约/验证→奖励与共享参数→周环境→固定参照/日志/runner→小人口测试与完整smoke→E0拟合/独立评价→加载产物的参照运行。指定Python为 `D:/programfile/miniconda3/envs/simulation/python.exe`，离线测试排除在线调用。

### 实际验收登记

2026-10-15，使用指定 Python3.11.14 完成以下实际验收；工作区代码尚未提交，实施前基线为8324a81。旧 t18 和传播内核未修改。

- 全部 `tests/test_control_*.py` 加 `test_cemas_import.py`、`test_campusLayer.py`，设置 `SCIRIS_BACKEND=agg`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 并排除 online：**334 passed**。保留原 `pytest.ini` 的 `env` 选项未识别警告；没有为此增加依赖。
- `compileall`、`git diff --check` 和 `pip check` 通过。用户明确授权安装 Optuna4.9.0、alembic1.20.0、colorlog6.12.0、SQLAlchemy2.1.4、Mako1.4.3、MarkupSafe3.0.4；环境及完整安装快照分别保存在本地产物和 `requirements-control-v1.lock.txt`，未安装后续RL/embedding依赖。
- 完整 smoke：90001/90002各运行两个参照，N12000/H112，每回合112条日记录、16次决策。补齐私有奖励CSV的实际窗口日数和公式版本后重新运行，最终验收目录为 `results/control_v1_phase3/smoke_verified/`；较早的 `smoke/` 原始运行保留。
- 主窗和辅助窗分别实际完成100 trials×3固定拟合世界，再各运行20个独立评价世界。辅助评价从08-03连续推进，仅计算08-15至08-18的留出误差，没有重置真实状态。
- 加载真实主窗artifact及独立报告，在源域验证A的20005世界（beta尺度1、筛查容量.05）运行两个参照，N12000/H112，结果位于 `results/control_v1_phase3/calibrated_references/`。这是校准后开发流程验收，不是最终实验。
- 独立读取六个最终验收回合的CSV/JSON重算：日/周/终点各项、初始感染、峰值、终点状态及reward全部一致，结果见 `results/control_v1_phase3/verification.json`。

| E0产物 | beta | 拟合归一化MSE | 独立平均MAE | 独立平均RMSE |
|---|---:|---:|---:|---:|
| `e0_primary/artifact.json`及`fit_report.json` | .03999548144249928 | .4268287312282556 | 5.578125 | 11.22276940880259 |
| `e0_exploratory/artifact.json`及`fit_report.json` | .02525792287386862 | .42578124999999983 | 22.8875 | 35.19842008861108 |

上述目录均位于 `results/control_v1_phase3/`，属于保留的本地产物，不纳入Git。主窗beta距离搜索上界不足1e-5，产物 `beta_at_boundary=true`；辅助四日留出误差也显示拟合限制。保留原范围、人口和单参数方法，没有据此增加自由度或选择控制权重。它们只支持重建序列的拟合与流程核查，不证明真实世界预测能力。独立世界的5%–95%带是运行带，不是参数置信区间。

从仓库根目录使用模块方式运行入口，例如：

```powershell
& 'D:/programfile/miniconda3/envs/simulation/python.exe' -m examples.control_v1.smoke --output results/new_smoke
& 'D:/programfile/miniconda3/envs/simulation/python.exe' -m examples.control_v1.calibrate --window primary --output results/new_e0
& 'D:/programfile/miniconda3/envs/simulation/python.exe' -m examples.control_v1.evaluate_calibration --artifact results/new_e0/artifact.json
& 'D:/programfile/miniconda3/envs/simulation/python.exe' -m examples.control_v1.run_references --artifact results/new_e0/artifact.json --seed 20005 --output results/new_references
```

这些命令的输出目录必须是新目录；独立评价报告不覆盖原报告。实际执行时协议快照保存在 `results/control_v1_phase3/protocol_used.json`，日志及artifact另外记录解析设置与hash。协议当前阶段元数据随后更新为P3，不改变人口/基础模型兼容核验。

后续全部主方法源域开发与验证B的H门禁、奖励正式冻结、训练充分性和最终E1–E4均不属于本阶段闭环验收结论。

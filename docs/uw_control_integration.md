# UW E0 与控制流程的唯一标准

更新：2026-10-25。本说明替代旧 Notre Dame 校准、12,000 人校园及旧校准产物的运行约定；历史验收数字保留原口径，不作为 UW 验收结果。

## 员工接触背景接入更新（2026-10-25）

当前控制配置沿用 `results/uw2020_fit_v3/final_c05r28/` 所引用的 weekly E0 背景：
`employee_cm=0.1`、`employee_ta=0.5`，初始感染为 100。该批 E0 的原始来源是
`results/e0_v5_iso0_w1trace/weekly/`，β=0.038583333332，按 weekly 目标、后移 1 天选参。

- 原始 `beta_layer.cm=0.35`、`beta_layer.ta=1.2` 保留。共享参数解析将 ta 乘 0.5，得到有效值 0.6。
- `cemas/control/background.py` 在每日社区接触重建后，仅将至少一端为员工的边乘 0.1；员工—员工边只乘一次，学生—学生边不变，同日重复调用不会再次缩放。
- E0、历史重放和控制环境复用该社区修正。重放中的日期政策和控制器选择的动作在背景上叠加；控制环境不安装历史 W2/W3 政策。
- 控制协议校验两项背景乘数与 E0 配置一致；私有运行记录保存 `campus_background`，有效层参数写入 `resolved_config.engine` 或世界的 `resolved_parameters`。校准兼容性同时绑定背景乘数、有效 ta 和共享源码。
- 实际隔离系数仍为 d/clu/clg/of/ta/cm = 0.3/0.1/0.1/0.1/0.2/0.1，检疫系数为 0.6/0.2/0.2/0.2/0.4/0.2。现有解析器会覆盖配置中的零值；本次背景接入不改变该实际行为。

旧校准锚点绑定修改前的源码和控制模型身份，不能直接用于修改后的正式控制运行。使用下述显式迁移生成关联旧证据的新锚点；原研究文件及锚点保持原样。严格加载器既核对当前身份，也核对迁移证据，不提供忽略哈希或自动接受旧锚点的开关。

## 配置与模块

- `docs/e0_protocol_v2.json` 定义当前 E0 标准：UW W1（2020-08-17～09-06）、69,457 人、初始感染 100、精确年龄段与角色人数、检测、扫描、拟合、评估种子及主选择规则。
- `docs/control_protocol_v1.json` 的 `calibration.config` 引用上述配置。控制人口、初始感染、起始日期、精确年龄人数、教师/职工比例及 `campus_k_ts=3` 必须与其一致；加载协议时即校验。其余网络/病程、112 日时域、动作、奖励、容量比例、训练预算保持原定义。容量按新人口计算，不能继续手填旧人口对应的 240/600/1200。
- `cemas/e0/` 是唯一校准实现；`data.py` 读取观测，`simulation.py` 运行世界，`study.py` 编排与汇总，`artifacts.py` 将已完成的主结果导出为控制参数锚点并核验。
- 控制环境、源域基线/RL训练、参考策略及 LLM/记忆流程统一调用 `cemas.e0.artifacts.load_calibration_artifact()`。正式环境拒绝裸 β、旧产物和不匹配的模型/数据/证据。
- 删除 `cemas/control/calibration.py`、`examples/control_v1/calibrate.py`、`evaluate_calibration.py`。不提供旧格式回退，不保留旧拟合标准。旧数据、结果、论文补充材料构建器及阶段验收记录仅用于历史追溯。

学生为 45,540 人，员工为 23,917 人；角色分别为本科生 31,650、非本科生 13,890、教师 2,321、其他职员 21,596。小人口 smoke 仅按 UW 年龄比例抽样，不携带完整人口的精确人数；正式环境不允许缩小人口。

2026-10-23 角色修订采用 [UW 官方预算报告第 12 页（PDF 第 13 页）](https://budget.wisc.edu/wp-content/uploads/sites/111/2022/02/Budget-in-Brief_2021-22_V15-1.pdf#page=13)的 Fall 2020 faculty 2,321 作为教学/实验室导师人数的模型近似。课堂从教师池中抽取授课教师，每位教师都会生成实验室组，因此不再合并教学类 academic staff 2,751，也不按既有员工总数放大。保留员工总数 23,917，其他职员为 21,596；占总人口分别为 `2321/69457` / `21596/69457`。Faculty 并不等于已核实的实验室导师人数；岗位数据也不是去重自然人数普查，原员工总数的年份与学生雇员去重口径问题仍未解决。

2026-10-23 按用户要求将 UW 的 `campus_k_ts` 从 6 调整为 3，作用于本科课堂、研究生课堂及实验室的教师—学生接触采样。这是用户指定的模型设置，并非 UW 实测值；3 是接触采样参数，不表示每位教师固定联系 3 名学生。教师/其他职员仍为 2,321/21,596，实验室组大小参数 `contacts.of=6` 保持不变。

## 原始研究与背景迁移

原始 weekly 研究已完成。`results/uw2020_fit_v3/final_c05r28/` 是使用该研究 β 的 75 天历史重放结果，不能把其 `summary.json` 当作训练锚点。`results/e0_v2/full/` 是旧角色模型，不能通过本次背景迁移接入。

```powershell
$python = 'E:\pytroch\anaconda3\envs\simulation\python.exe'
& $python -m examples.control_v1.e0_study --migrate-background results/e0_v5_iso0_w1trace/weekly/control_anchor.json --output results/e0_v5_iso0_w1trace/weekly_background_v1_local --workers 4
```

迁移只接受员工背景接入这一种变更：旧基础模型应用已声明的员工社区和 ta 乘数后，必须与当前基础模型完全一致；运行环境、观测、E0 配置和非迁移范围内的源码也必须一致。仅允许已知背景提取及证据接入文件变化，不接受其他引擎改动。

迁移执行以下核验：

1. 校验原锚点及其六份研究文件，核对完整主情景种子，从原始扫描、拟合和评估记录重建损失、选参及汇总；保持 **main、后移 1 天、weekly 目标**和原 β。
2. 在当前代码下重放最终 β 对应的全部 40 个评估世界（12201–12240）。逐世界核对原有字段，包括逐日分组阳性、检测、R_eff、人口和角色；新增有效参数必须符合当前背景配置。
3. 在新目录复制原始证据字节，保留 `source_control_anchor.json`，写入 `worlds_migration.jsonl`、`migration.json` 和新 `control_anchor.json`。任何不一致均拒绝导出并保留失败记录；输出目录已存在时拒绝复用。

扫描与拟合世界只核验原始证据并重新计算选参，不重新仿真；40 世界一致性证明只覆盖已重放的评估条件，不是所有可能参数下的数学等价证明，也不是新增外部验证。新锚点保留原选参和研究哈希，额外绑定当前身份及迁移证据。移走原目录后仍可加载完整迁移包，不能只搬运一个锚点文件。

正常 `--export-existing` 仍只接受源码匹配、完成且尚未导出锚点的研究。它不会迁移旧身份。需要全新校准时使用新目录运行 `e0_study --output ...`；后续再次修改绑定源码会使当前锚点失效，不能用本次迁移命令无限更新身份。

2026-10-25 实际验收：上述 `weekly_background_v1_local` 迁移已完成，40/40 世界的原有输出字段全部相等；原始六份研究文件及旧锚点字节保留。新锚点通过严格加载，β=0.038583333332。使用新锚点完成 69,457 人、种子 20001 的 14 天最低干预控制运行；生产 `TrainingEnvFactory`（训练 seed 11）成功执行固定首周及一次自主决策，返回 198 维观察，累计推进 14 天。记录见输出目录的 `migration.json`、`acceptance/verification.json` 和 `acceptance/training_worlds.jsonl`。这是接入验收，不是完整 RL 训练或正式策略评价。首个沙箱尝试因 Windows 多进程管道权限失败，证据保留在 `weekly_background_v1/migration_failure.json`；该目录没有可用锚点。

旧 E0 manifest 没有冻结完整的共享控制源码及基础协议快照。历史接入迁移在修改前保存当时有效的 UW 模型参数，并与迁移后的控制模型逐字段核对一致；该参数核对不能补充证明历史上未记录的源码身份，也不覆盖此次角色及教师—学生接触参数修订。锚点的源码身份从导出时开始冻结，原始 manifest 的来源记录保持原样。

## 后续运行

```powershell
$anchor = 'results/e0_v5_iso0_w1trace/weekly_background_v1_local/control_anchor.json'
& $python -m examples.control_v1.run_references --artifact $anchor --seed 20005 --output results/uw_references
& $python -m examples.control_v1.baselines pilot --artifact $anchor --reference maximum_feasible --output results/uw_pilot
& $python -m examples.control_v1.baselines tune --artifact $anchor --output results/uw_threshold
& $python -m examples.control_v1.baselines train --artifact $anchor --method ppo --maximum-budget 8192 --output results/uw_ppo
& $python -m examples.control_v1.baselines train --artifact $anchor --method ddqn --maximum-budget 8192 --output results/uw_ddqn
```

这些是迁移成功后的运行示例，不表示已完成正式调参或训练。先完成新背景下的 pilot 计时，再确定两算法统一资源上限；训练预算和选模规则保持现有协议。

锚点须与其原始研究文件一起保留和迁移。所有入口的 `--artifact` 均传入 `control_anchor.json` 文件；`--data` 仅用于移动后同字节 UW W1 文件的显式定位。奖励或控制时域调整不会改变基础校准模型，但相关控制模型/记忆/训练产物仍须遵守各自协议身份检查。既有旧人口 checkpoint、阈值、案例库和正式评价不自动视为 UW 已验收结果，需在新协议下重新开发与验证。

## 解释范围

这里接入的是 W1 样本内参数锚点，不表示已验证预测、因果或现实干预效果。分组偏差、高 β 和初始感染敏感性继续保留在研究报告中。正式控制任务仍是同一引擎中的合成干预比较，不能因完成接入而扩大科学结论。

2026-10-23 角色及接触参数修订验证（历史记录）：E0 研究、校准锚点、控制协议及场景的 203 项相关测试通过，包含 69,457 人的实际初始化和两天控制运行，确认教师 2,321 / 其他职员 21,596、本科课堂/研究生课堂/实验室的实际 `k_ts=3` 及控制运行 manifest 中的引擎参数，并验证旧角色配置的锚点被拒绝。当时控制集成测试使用测试构造的校准证据，尚未运行该配置的完整 E0 校准。

## 角色修订前的历史工程验证

完整控制/E0/公共导入回归及修复补跑合并后，877 个不同测试最终通过，未解决失败为 0。两项 RL 子进程测试因沙箱 Windows 管道权限在沙箱外补跑通过；未修改算法以绕过测试。原始测试结果记录在 `results/uw_migration_regression.xml`、`uw_migration_targeted.xml`、`uw_migration_e0_final.xml`。

使用当时真实 E0 产物运行了 69,457 人、教师 1,150 / 职工 22,767、β=0.059249999998 的最低干预控制 14 日跨周检查，状态 completed；当时的精确学生/教师/职工人数、锚点哈希、实际 β 与运行天数均已核验。输出位于 `results/uw_control_integration_20261023/minimum_14d/`，汇总见其上级的 `verification.json`。这只是旧角色配置的接入检查，不构成当前 2,321 / 21,596 配置的校准或控制验收；未执行正式 112 日方法比较或完整 RL 训练。

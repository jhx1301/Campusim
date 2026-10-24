# UW E0 与控制流程的唯一标准

更新：2026-10-23。本说明替代旧 Notre Dame 校准、12,000 人校园及旧校准产物的运行约定；历史验收数字保留原口径，不作为 UW 验收结果。

## 配置与模块

- `docs/e0_protocol_v2.json` 定义唯一 E0 标准：UW W1（2020-08-17～09-06）、69,457 人、初始感染 30、精确年龄段与角色人数、检测、扫描、拟合、评估种子及主选择规则。
- `docs/control_protocol_v1.json` 的 `calibration.config` 引用上述配置。控制人口、初始感染、起始日期、精确年龄人数、教师/职工比例及 `campus_k_ts=3` 必须与其一致；加载协议时即校验。其余网络/病程、112 日时域、动作、奖励、容量比例、训练预算保持原定义。容量按新人口计算，不能继续手填旧人口对应的 240/600/1200。
- `cemas/e0/` 是唯一校准实现；`data.py` 读取观测，`simulation.py` 运行世界，`study.py` 编排与汇总，`artifacts.py` 将已完成的主结果导出为控制参数锚点并核验。
- 控制环境、源域基线/RL训练、参考策略及 LLM/记忆流程统一调用 `cemas.e0.artifacts.load_calibration_artifact()`。正式环境拒绝裸 β、旧产物和不匹配的模型/数据/证据。
- 删除 `cemas/control/calibration.py`、`examples/control_v1/calibrate.py`、`evaluate_calibration.py`。不提供旧格式回退，不保留旧拟合标准。旧数据、结果、论文补充材料构建器及阶段验收记录仅用于历史追溯。

学生为 45,540 人，员工为 23,917 人；角色分别为本科生 31,650、非本科生 13,890、教师 2,321、其他职员 21,596。小人口 smoke 仅按 UW 年龄比例抽样，不携带完整人口的精确人数；正式环境不允许缩小人口。

2026-10-23 角色修订采用 [UW 官方预算报告第 12 页（PDF 第 13 页）](https://budget.wisc.edu/wp-content/uploads/sites/111/2022/02/Budget-in-Brief_2021-22_V15-1.pdf#page=13)的 Fall 2020 faculty 2,321 作为教学/实验室导师人数的模型近似。课堂从教师池中抽取授课教师，每位教师都会生成实验室组，因此不再合并教学类 academic staff 2,751，也不按既有员工总数放大。保留员工总数 23,917，其他职员为 21,596；占总人口分别为 `2321/69457` / `21596/69457`。Faculty 并不等于已核实的实验室导师人数；岗位数据也不是去重自然人数普查，原员工总数的年份与学生雇员去重口径问题仍未解决。

2026-10-23 按用户要求将 UW 的 `campus_k_ts` 从 6 调整为 3，作用于本科课堂、研究生课堂及实验室的教师—学生接触采样。这是用户指定的模型设置，并非 UW 实测值；3 是接触采样参数，不表示每位教师固定联系 3 名学生。教师/其他职员仍为 2,321/21,596，实验室组大小参数 `contacts.of=6` 保持不变。

## 当前配置的校准与接入

角色修订及 `campus_k_ts=3` 改变基础模型，必须在新的独占目录重新校准；当前尚无此配置的校准结果。已有 `results/e0_v2/full/` 及其中 `control_anchor.json` 保留为教师 1,150 / 职员 22,767 的历史产物，主 β=0.059249999998，不适用于当前配置；对该旧研究使用当前配置执行 `--export-existing` 会拒绝接入。

```powershell
$python = 'E:\pytroch\anaconda3\envs\simulation\python.exe'
& $python -m examples.control_v1.e0_study --output results/uw_e0_roles_20261023 --workers 4
```

上述命令完整运行研究后自动导出 `results/uw_e0_roles_20261023/control_anchor.json`，只选择 **main、后移 1 天、累计目标**；不以较低损失的敏感性结果替换主结果。`--export-existing` 仅用于配置匹配、已完成且尚未导出锚点的研究；该导出不重新运行仿真，不改写原始 E0 文件，若锚点已存在则拒绝覆盖。

导出先核对运行状态、观测/配置/已记录源代码哈希、三阶段原始文件哈希、主情景种子完整性，从原始拟合记录重新选参，从原始评估世界重建主结果并与摘要核对。锚点额外冻结当前控制模型、共享参数解析代码、E0/引擎源码和研究文件哈希。后续加载检查同一组证据。

旧 E0 manifest 没有冻结完整的共享控制源码及基础协议快照。历史接入迁移在修改前保存当时有效的 UW 模型参数，并与迁移后的控制模型逐字段核对一致；该参数核对不能补充证明历史上未记录的源码身份，也不覆盖此次角色及教师—学生接触参数修订。锚点的源码身份从导出时开始冻结，原始 manifest 的来源记录保持原样。

## 后续运行

```powershell
& $python -m examples.control_v1.run_references --artifact results/uw_e0_roles_20261023/control_anchor.json --seed 20005 --output results/uw_references
& $python -m examples.control_v1.baselines pilot --artifact results/uw_e0_roles_20261023/control_anchor.json --reference maximum_feasible --output results/uw_pilot
& $python -m examples.control_v1.baselines tune --artifact results/uw_e0_roles_20261023/control_anchor.json --output results/uw_threshold
& $python -m examples.control_v1.baselines train --artifact results/uw_e0_roles_20261023/control_anchor.json --method ppo --output results/uw_ppo
```

这些是新角色及接触参数配置完成校准后的运行示例，不表示已完成校准、正式调参或训练。

锚点须与其原始研究文件一起保留和迁移。所有入口的 `--artifact` 均传入 `control_anchor.json` 文件；`--data` 仅用于移动后同字节 UW W1 文件的显式定位。奖励或控制时域调整不会改变基础校准模型，但相关控制模型/记忆/训练产物仍须遵守各自协议身份检查。既有旧人口 checkpoint、阈值、案例库和正式评价不自动视为 UW 已验收结果，需在新协议下重新开发与验证。

## 解释范围

这里接入的是 W1 样本内参数锚点，不表示已验证预测、因果或现实干预效果。分组偏差、高 β 和初始感染敏感性继续保留在研究报告中。正式控制任务仍是同一引擎中的合成干预比较，不能因完成接入而扩大科学结论。

2026-10-23 角色及接触参数修订验证：E0 研究、校准锚点、控制协议及场景的 203 项相关测试通过，包含 69,457 人的实际初始化和两天控制运行，确认教师 2,321 / 其他职员 21,596、本科课堂/研究生课堂/实验室的实际 `k_ts=3` 及控制运行 manifest 中的引擎参数，并验证旧角色配置的锚点被拒绝。控制集成测试使用测试构造的校准证据；尚未运行当前角色及接触参数配置的完整 E0 校准。

## 角色修订前的历史工程验证

完整控制/E0/公共导入回归及修复补跑合并后，877 个不同测试最终通过，未解决失败为 0。两项 RL 子进程测试因沙箱 Windows 管道权限在沙箱外补跑通过；未修改算法以绕过测试。原始测试结果记录在 `results/uw_migration_regression.xml`、`uw_migration_targeted.xml`、`uw_migration_e0_final.xml`。

使用当时真实 E0 产物运行了 69,457 人、教师 1,150 / 职工 22,767、β=0.059249999998 的最低干预控制 14 日跨周检查，状态 completed；当时的精确学生/教师/职工人数、锚点哈希、实际 β 与运行天数均已核验。输出位于 `results/uw_control_integration_20261023/minimum_14d/`，汇总见其上级的 `verification.json`。这只是旧角色配置的接入检查，不构成当前 2,321 / 21,596 配置的校准或控制验收；未执行正式 112 日方法比较或完整 RL 训练。

# UW 2020 连续历史重放

本实验执行 [v2 计划](uw2020_replay_plan_v2.md)，使用已有 E0 主设置锚点，不重新校准基础参数，不调用策略控制执行器。住宿补偿和接触恢复比例是预设实验假设，其适合程度由结果判断。

本次锚点为 `results/e0_v3/teacher2321_k3/full/control_anchor.json`：β = 0.056666666665，人口 69,457，初始感染 30，教师 2,321，`campus_k_ts=3`，`symp_test=80`。锚点的所有数据、源码、运行环境及研究证据哈希在运行前后严格验证；已有 E0 文件不重写。

在仓库根目录运行（项目 Python 为 `E:\pytroch\anaconda3\envs\simulation\python.exe`）：

```powershell
python -m tools.build_uw_e0_data --replay-only
python -m tools.verify_uw_replay --output results/uw2020_replay_v2_acceptance/role_regression.json
python -m examples.control_v1.uw2020_replay --anchor results/e0_v3/teacher2321_k3/full/control_anchor.json --output results/uw2020_replay_v2/full_local --workers 8
```

输出目录必须不存在，避免覆盖任何历史结果。完整执行包含 1,860 个世界：固定 W2 120 个、W2 网格拟合 1,260 个、75 天评价及预设敏感性分析 480 个。固定住宿补偿为 1.15（主设置）、1.0、1.25；每档独立选择社区保留比例，不进行联合自由拟合。主恢复比例 0.5，0.25 和 0.75 为预设敏感性分析。

数据文件 `data/uw_madison_2020_replay.csv` 连续覆盖 2020/8/17–10/30。仅使用 W1 的分组检测权重。阳性数和实际检测分母在完整序列上共同后移一天，跨窗口结果保留，末尾记录至 10/31；该平移是 E0 的观测对齐假设。截止 10/30 是本次实验范围，11 月及以后的数据和措施变化未纳入本轮。

`worlds_fixed_w2.jsonl`、`worlds_fit.jsonl`、`worlds_evaluation.jsonl` 保留原始逐世界序列，`profiles.json` 保留每档住宿补偿下全部 21 个候选的平均损失、标准误和逐世界损失。评价种子不参加选参，W3 观测不反向修改 W2 参数。失败世界写入对应 `failures_*.jsonl` 并使实验失败，不更换种子。

`compatibility.json` 逐世界核对 E0 已存档的前 21 天阳性数、实际检测量、请求检测量、角色数量及分组检测权重，另核对固定方案短程和长程前 40 天完全一致。独立验收脚本进一步比较原 E0 与长程重放的逐人角色数组。`manifest.json` 记录锚点、数据、实验配置、源码及输出哈希。

`summary.json`、`daily_metrics.csv`、`window_metrics.csv`、`figures/` 和 `report.md` 给出全部评价情景的总量、学生和员工结果。5/50/95 分位数表示模拟随机性范围，不是参数置信区间；工程验收通过与模型解释成立分别判断。

针对验证：

```powershell
python -m pytest tests/test_replay_simulation.py tests/test_replay_study.py tests/test_replay_reporting.py tests/test_uw_replay_data.py tests/test_e0_study.py tests/test_e0_artifacts.py -q
```

本轮不实现中途模型状态序列化、策略接管或训练/测试接口；这些属于计划的后续阶段。

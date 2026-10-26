# UW 2020 重放任务交接

用户要求：使用最新 E0 结果执行 `docs/uw2020_replay_plan_v2.md`。现在用户要求交给其他 agent，以下是核对时的实际状态。

## 正在运行的计算

- 主进程 PID：`22136`，8 个 worker；计算进程仍在运行，未终止。
- 本会话执行工具 session ID：`66868`（其他会话未必能访问此 ID；可直接监控磁盘文件和 PID）。
- 输出：`results/uw2020_replay_v2/full_local/`。
- 最近核对：固定 W2 已完成 `120/120`；拟合 JSONL 已保存 `501/1260`；评价阶段尚未开始；两份失败文件均为 0 字节。数量会继续增长。
- 主程序会自动完成其余拟合、选参、480 个长程评价世界、汇总、绘图及 manifest，不需要手动启动下一阶段。

已启动的命令：

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -u -m examples.control_v1.uw2020_replay --anchor results/e0_v3/teacher2321_k3/full/control_anchor.json --output results/uw2020_replay_v2/full_local --workers 8
```

首次在沙箱内启动因 Windows 多进程 Pipe 的 WinError 5 失败，只有 `results/uw2020_replay_v2/full/` 中的失败 manifest/config，没有计算世界。随后获准在本机运行上述 `full_local`，正常推进。这里实际遇到的是 Windows 沙箱权限问题。

## 已完成的工作

1. 最新 E0 锚点已严格加载验证：`results/e0_v3/teacher2321_k3/full/control_anchor.json`，β=`0.056666666665`，人口 69,457、初始感染 30、教师 2,321、`campus_k_ts=3`、`symp_test=80`。
2. 锚点文件 SHA256：`21a2f9643335556755cd74351e1b49406b5cb34ca7c21e3bc40cde21c38fa8cc`；payload SHA256：`b511af95b7fe2ab3883e379ce2638624ad7609c715d04d9554b80a28b1fa029c`。
3. 构建 75 天连续观测表及来源归档；三个窗口和分组总数全部吻合。CSV SHA256：`e3d116aad694c840470d332caf6f5b59d7447da401d6b4d4ab533795da4ca846`。
4. 独立实现 `cemas/replay/simulation.py`、`study.py`、`reporting.py` 及入口、配置和测试。未修改任何 `cemas/e0/` 或 `covasim/` 绑定核心文件。
5. 真实人口 seed 12201 的原 E0、原产物和 75 天重放 W1 阳性数、检测量及逐人角色数组全等。证据：`results/uw2020_replay_v2_acceptance/role_regression.json`；复现脚本：`tools/verify_uw_replay.py`。
6. 针对测试已通过：55 项 E0/数据/重放/调度测试，另 5 项 reporting 测试，共 60 项。报表测试 XML：`results/uw2020_replay_v2_acceptance/reporting_tests.xml`。真实报表 smoke test 的图也已查看。
7. 原始观测的学生全期最高值为 **2020/9/9 的 290**；9/13=187，9/16=124。计划中的日期/形态解释按待验证假设处理，不保证单调回落。

## 接手后剩余工作

1. 先监控 PID 22136 和 `worlds_fit.jsonl` / `worlds_evaluation.jsonl`，让当前计算继续；避免重复启动相同实验。
2. 等待 `manifest.json` 为 `complete`。总计必须是 120 固定 W2 + 1260 拟合 + 480 评价 = **1860**；失败文件均应为空。若有失败，保留并调查，不静默换种子。
3. 核对 `profiles.json`：每档住宿补偿 21 个 c，各 20 个拟合种子；精确平局选较大的 c，W3 不参与选参。
4. 核对 `compatibility.json`：1860 个 W1 完全一致，120 个固定方案的 40 天/75 天前缀一致，绑定源码未变。
5. 检查 `summary.json`、三份 CSV、`report.md` 和 `figures/*.png`；查看真实图表布局、员工单独结果、10/31 尾部、W3 偏差及全部恢复敏感性分支。
6. 独立复核每个评价情景 40 个种子（12201–12240）、三档住宿、固定/校准/0.25/0.75 分支完整性；核对 manifest 的输出哈希。
7. 最后检查 diff 和相关测试，向用户交付报告链接、c*、主要 W2/W3 偏差、实际验证结果。已有 E0 结果不覆盖、不提交/推送 Git。

初步结果：固定 c=0.2 的 W2 学生总阳性中位数分别为 h=1.15：7971、h=1.0：7771、h=1.25：8083.5，而观测为1393。主 h 已完成的一部分网格中，c=0 的损失仍很大且低于其他已完成候选。**这只是中途发现，最终 c* 和 W3 结论以完整结果为准。不要为改善拟合而改 β、检测权重、初始感染或外部输入。**

## 代码与运行注意

- 使用说明：`docs/uw2020_replay.md`；实验配置：`docs/uw2020_replay_config_v2.json`。
- 模拟及选参源码已在运行开始时冻结 SHA256；中途修改这些文件会让最终检查失败。reporting 源码在实际汇总开始时另外记录 SHA256，目前已完成并冻结。
- 主脚本没有 `--resume`。如果进程中断，先保留现有 JSONL 和失败证据，再决定从已验证记录续算或在全新目录重跑；现有输出目录不能直接重用。
- 当前 repo 有未提交修改和新增文件，包括原本用户提供的 `docs/uw2020_replay_plan_v2.md`；没有创建 Git commit。
- pytest 在本机 Python 3.10/Windows 沙箱中用 mode=0700 创建 tmp_path 会遇到 ACL 错误。已用下面的**仅测试进程内**规避通过验证，没有修改项目或系统环境：

```powershell
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -c "import os,pathlib; original_mkdir=os.mkdir; pathlib._normal_accessor.mkdir=lambda path,mode=0o777: original_mkdir(path,0o777 if mode==0o700 else mode); import pytest; raise SystemExit(pytest.main(['tests/test_replay_simulation.py','tests/test_replay_study.py','tests/test_replay_reporting.py','tests/test_uw_replay_data.py','tests/test_e0_study.py','tests/test_e0_artifacts.py','-q','--basetemp=.pytest_cache/uw_replay_handoff_tests']))"
```

唯一既有 pytest 警告为 unknown config option `env`。早期测试创建的 ignored `results/replay_engine_test_tmp` 目录因 ACL 无法普通清理；它不含实验数据，清理时仅针对核实过的该目录。

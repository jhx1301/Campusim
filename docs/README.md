# CEMAS v1 开发文档

更新：2026-10-28。接续开发先读 [UW 控制接入](uw_control_integration.md)和[当前工作阅读索引](CEMAS_READING_INDEX.md)。Feedback持续学习以[新版统一设计](llm_feedback_component_design.md)为准，旧P5材料仅作历史说明。

当前 UW 配置为 69,457 人、初始感染 100、教师 2,321 / 其他职员 21,596、`campus_k_ts=3`；weekly E0 与员工接触背景迁移已完成，40 个评估世界重放一致。当前锚点为 `results/e0_v5_iso0_w1trace/weekly_background_v1_local/control_anchor.json`。P6 工程入口已经实现，正式源域开发、共同冻结和最终实验尚未完成。旧阶段验收数字和旧模型产物保留为历史证据。

| 文档 | 用途 |
|---|---|
| [UW 控制接入](uw_control_integration.md) | 当前人口/模型、E0 入口、锚点兼容性及证据边界 |
| [快照 baseline 训练计划](baseline_snapshot_training_plan_v1.md)、[代码使用说明](baseline_snapshot_training.md) | 精简共享快照池、单验证集、固定112天训练及独立baseline测试／报告入口 |
| [E0 配置](e0_protocol_v2.json)、[研究计划](../research/historical_epidemics/e0_calibration_research_plan.md) | UW W1 校准参数与原始方法记录 |
| [软件工程实现计划](cemas_v1_implementation_plan.md) | Phase 0–7 的范围、接口、产物和验收顺序 |
| [推荐实施协议](llm_recommended_protocol_v1.md)、[控制配置](control_protocol_v1.json) | 共同任务、动作、观察、资源、实验与统计规则 |
| [记忆配置](control_memory_v1.json) | 当前数值检索和记忆参数；输入不按token裁剪 |
| [Feedback统一设计](llm_feedback_component_design.md)、[实施合同](PLAN%20(1).md)、[人工样例](llm_feedback_component_examples.json) | 当前快照7天观察＋112天控制、单周案例、聚合规则统计、v2学习库及冻结评估 |
| [LLM三种子实验准备](llm_training_experiment_v1.md) | 独立库、每种子32＋32回合且历史世界不重复、离线准备、并行命令和冻结评价安排 |
| [Phase 0 契约](control_phase0_contracts.md) | 公共接口、schema 与公共/私有信息边界 |
| [Phase 1 契约](control_phase1_contracts.md) | 324 动作编解码、合法 mask 和动作解析 |
| [Phase 2 契约](control_phase2_contracts.md) | 共同执行器、公共 ledger/观察和私有指标 |
| [Phase 3 契约](control_phase3_contracts.md) | 周环境、奖励、参照策略及历史 E0 验收 |
| [Phase 4 契约](control_phase4_contracts.md) | 无显式记忆 LLM、计数、重试、共同回退与审计 |
| [Phase 5 历史计划](control_phase5_implementation_plan.md)、[历史契约](control_phase5_contracts.md) | 早期只读源案例库设计及验证记录；弃用协议不再约束新版Feedback |
| [Phase 6 计划](control_phase6_implementation_plan.md)、[契约](control_phase6_contracts.md) | Baseline/RL 工程、源域开发、案例库发布与共同冻结 |
| [LLM 架构研究](llm_architecture_research/README.md) | P5 架构依据、示例与验证设计；实际运行规则以现行契约为准 |

## 环境与依赖

指定解释器为 `D:/programfile/miniconda3/envs/simulation/python.exe`。先用 `tools/check_control_environment.py` 检查当前环境，再按具体任务选择依赖；该工具只检查发现结果和安装元数据，不代表运行验收。报告中的 `future` 是 P0 留下的历史分组名称，不表示对应库现在尚未安装或尚未接入。

2026-10-23 当前解释器为 Python 3.10.20，安装元数据为 Optuna 4.8.0、Torch 2.13.0、Gymnasium 1.4.0、SB3/contrib 2.9.0、OpenAI SDK 2.33.0、Transformers 5.13.0、pytest 9.1.1。此清单是当前环境盘点，不代表本次已重跑 RL 或真实服务验收。

- 根目录 `requirements.txt` 是旧补充材料的参考环境，也是当前 `setup.py` 的安装依赖入口；其中没有完整声明 V1 的 RL 运行依赖。
- `requirements-control-v1.in`、`requirements-control-llm-v1.in`、`requirements-control-rl-v1.in` 分别记录控制、LLM 与 RL 阶段的依赖要求。其中 Optuna 4.9.0、Torch 2.14.1 与当前实装不同，不应直接安装覆盖现有环境来消除文档差异。
- 对应 `.lock.txt` 是各阶段的历史实装快照，不能据此假定当前解释器版本一致；它们也不代表当前模型已完成科学运行。不要将不同阶段的快照叠加当作一个统一 lock。

当前使用源码 checkout 和现有 simulation 环境。独立安装包尚未验收：`setup.py`/`MANIFEST.in` 没有明确覆盖全部 V1 prompt、知识和协议资源；现有 CI 也没有安装完整 RL 依赖，不能作为完整 V1 验收凭据。

命令从项目根目录执行，V1 入口位于 `examples/control_v1/`，输出使用新的独占目录。正常运行不要求 P4/P5 验收报告；实际 tokenizer、服务响应、E0 和 source store 的兼容性检查仍然有效。

## 历史材料和原引擎文档

- [归档研究方案](archive/llm_baseline_generalization_plan.md)保留研究问题与设计理由，实施规则以现行协议和阶段契约为准。
- [旧论文技术补充](archive/technical_supplement_llm_policy_agent.tex)和根目录 `RESULT_MAPPING.md` 用于旧 P0–P4 方法与论文结果追溯。
- `tutorials/`、`api/`、`index.rst` 与 `conf.py` 仍是 Covasim 引擎的 Sphinx 文档，不是 V1 实验验收入口。

构建原引擎文档时，在 `docs/` 中安装其 `requirements.txt`，然后运行 `./build_docs never` 或 `make html`；输出位于 `docs/_build/html/`。这项构建不验证 V1 Markdown 协议、校准、训练或服务调用。旧 `.readthedocs.yaml` 仍配置 Python 3.9，与当前包要求 Python ≥3.10 冲突；该自动构建配置尚未迁移，本次不将其视为已可用。

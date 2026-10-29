# CEMAS v1 Phase 5 实施契约

> 历史材料（2026-10-28）：当前Feedback以[统一设计](llm_feedback_component_design.md)、[实施合同](PLAN%20(1).md)及[人工样例](llm_feedback_component_examples.json)为准。本文的早期只读案例库、followup配对和不含持久LLM学习的范围不再约束新版。旧格式不迁移；新版使用单周案例及v2学习库。

> 2026-10-23：本文的旧校准、人口及验收数字为历史记录。当前唯一标准和运行入口以 [UW 控制接入](uw_control_integration.md) 为准；旧结果不作为 UW 验收。

更新日期：2026-10-23。状态：**公共记忆与四策略采集/冻结链已实现；从已有 source 审计导出重建 development 库仍缺入口，真实 provider/tokenizer 验收和当前配置的正式源库未完成。**

当前基础模型为 UW 69,457 人、教师 2,321 / 其他职员 21,596、`campus_k_ts=3`。该配置尚未完成 E0 校准；旧角色配置的锚点、阈值及案例库不能直接用于当前科学运行，先按 [UW 控制接入](uw_control_integration.md) 重新校准，再开发兼容的源域产物。

本契约记录 Phase 5 的实际接口、边界和本次验证结果。它不把 fixture、fake tokenizer 或离线 transport 当作真实服务验收，也不把案例检索通过当作控制效果结论。

## 实现边界

Phase 5 将研究方案落在 `cemas/control/`：

- `PublicEpisodeMemory` 只接收精确的 `PublicObservation` 和 `PublicWeekFeedback`；`stage()` 暂存决策前公共状态，`accept()` 使用实际反馈中的动作、资源和窗口生成本地 revision。
- `PublicCaseBuilder` 仅使用一个公共 SQLite 保存案例；私有来源和编号映射在构建期间保存在内存，`finalize()` 导出已有格式的 `private_manifest.json`，不创建私有 SQLite。公共事务提交成功后才更新内存映射；失败时回滚该事务。`FrozenPublicCaseStore` 以只读连接打开并校验数据库 hash、schema、revision 和 opaque group。
- `NumericRetriever` 使用固定 38 维 state、最近三周趋势差分、`.75/.25` 权重、容量/动作/任务过滤、冲突对和确定性多样性选择；没有 embedding 或 LLM 摘要。
- `KnowledgeBundle` 固定六条 SIM 核心规则和三条版本化公共卫生卡；每张卡只解码构造一次，对象负责自身合法性，bundle负责来源、版本与集合约束，不转回字典重复构造。四种模式 `none/short/global/both` 使用同一公共 system、知识选择和五字段 wire。
- `MemoryLLMController` 通过 `LLMController` 的同一 transport、计数、重试和审计链完成消息准备与解析；runner 在执行前写 `decision_evidence.jsonl`，反馈后写实际执行动作和 `memory_revisions.jsonl`。
- `memory_collection` 只接受协议保留的 30001–30027 源池；科学采集支持 minimum、maximum_feasible、uniform_legal_independent_rng 和 tuned_threshold 四种策略，第四种必须提供实际选定的 `--threshold-artifact`。smoke 默认仅用前三种策略构造 fixture；evaluation-ready 的 108 条正式库仍须通过 Phase 6 的阈值、覆盖与共同冻结检查。

控制器和 prompt 仍只看到公共输入。私有 reward、感染真值、beta、world seed、future event、simulator 和完整 audit 不进入 memory、检索或模型消息。

## 可复现入口

从仓库根目录使用指定解释器。下面的回归命令写入新目录；依赖以当前解释器的实际安装为准，旧验收目录中的可选依赖不是运行前提：

```powershell
$repo = (Get-Location).Path
$env:PYTHONPATH = $repo
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m pytest `
  tests/test_control_memory.py tests/test_control_memory_store.py tests/test_control_retrieval.py `
  tests/test_control_knowledge.py tests/test_control_llm_memory.py `
  tests/test_control_memory_integration.py tests/test_control_llm.py `
  tests/test_control_runner.py tests/test_control_logging.py -q -m 'not online' `
  --basetemp results/control_v1_phase5/current_regression_tmp `
  --junitxml results/control_v1_phase5/current_regression.xml
```

采集工具和入口：

```powershell
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m tools.collect_observable_memory --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m examples.control_v1.smoke_memory --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m examples.control_v1.run_memory_llm --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m examples.control_v1.accept_memory_llm --help
```

真实入口只接收 credential 环境变量名称；默认名称是 `DASHSCOPE_API_KEY`，transport在内存中读取密钥，日志不保存密钥值。正常运行需要官方 tokenizer manifest、兼容的 E0 产物和（global/both 时）已验证的只读 source store，不需要 P4/P5 验收报告。

## Phase 5 历史验证记录

以下为当时已实现范围的离线验证记录，不代表完整计划或当前 UW 配置的正式产物已经验收：

- 合并后的 Phase 5 + P4 定向套件：**301 passed**，另有 **1 warning**（既有 pytest `env` 配置警告）；本次命令生成 `results/control_v1_phase5/final_02.xml`。
- 其中 Phase 5 memory、knowledge、LLM、store、retrieval 和 runner integration 的历史分组结果为 **199 passed**；P4 `LLMController`、runner、logging 回归分组为 **178 passed**。分组存在重叠，不能相加。
- 采集工具、模块导入和入口源文件通过 `py_compile`；`git diff --check` 通过。
- 验证证据目录：`results/control_v1_phase5/`，包括 `core_tests.xml`、`llm_pytest_03.xml`、`integration_tests.xml`、`review_tests.xml` 和最终定向测试 XML。

真实服务验收状态：**未执行**。本轮没有付费 API 调用、没有读取 `DASHSCOPE_API_KEY` 的值、没有正式科学仿真，也没有生产 27×4 源库。

## 运行条件与独立验收

按本轮用户修订，验收是开发完成后的独立验证，不作为程序使用规则。`make_memory_llm_controller()` 和正常运行入口不要求、不读取 P4/P5 验收报告，runner不要求四模式报告；旧报告参数仅为兼容已有调用而保留，不参与运行。live transport仍使用官方 tokenizer 检查当前输入、预算与实际usage；服务身份基于本批次首个实际返回。global/both的只读store、public task hash、私有source manifest和E0兼容性校验仍针对实际运行数据。

`examples/control_v1/accept_memory_llm.py` 保留原命令入口，实现已移到 `tools/memory_acceptance.py`，不再由 `cemas` 或 `cemas.control` 加载、导出。验收函数需显式从工具模块导入，可独立执行六类服务探针，不需要已有P4报告。生成报告时，各探针沿生产请求路径检查响应、输入计数与服务身份，并核对命名场景的覆盖要求；收尾只检查保存记录的完整性、hash、用例覆盖和消息/usage配对，不重复解析响应或执行token计数。`validate_memory_acceptance()` 用于独立读取报告，才重建原始两条消息、对实际完整请求复算计数并重新校验响应及服务身份。允许原始输入后追加一条user纠错消息；纠错不扩大原始引用registry，原始上下文仍须完全匹配。四模式覆盖要求只适用于独立验收，不影响正常运行。报告用于留档，不改变运行模式，也不参与正常回合启动。

`collect_observable_memory.py` 已支持四策略重新采集、冻结、覆盖检查及 Phase 6 验证后的晋升；`import-fixture` 只接受明确标为 synthetic fixture 的公共导出。它仍不支持凭私有审计 manifest 从已有真实 source 公共导出重建 development 库；这是独立于重新采集的计划缺口，不能据此宣称 P5 全部工程验收通过。

前次审查修复后使用 `D:\programfile\miniconda3\envs\simulation\python.exe` 运行全部 `test_control_*.py`、CEMAS 导入与校园人口回归：747 passed、1 failed；失败项为环境缺少 `tokenizers`，另有既有 pytest `env` 配置警告。结果保存在 `results/phase5_review_20261017/final.xml`。

本轮将报告与正常运行解耦后，同一范围回归为756 passed、1 failed；唯一失败仍为缺少`tokenizers`。新增用例覆盖无报告运行、旧报告参数指向不存在文件仍可使用、报告不设置实际服务基准，以及独立验证工具。证据为`results/llm_report_decoupling_20261017/final.xml`；编译、入口`--help`和`git diff --check`通过。未跳过失败用例、安装依赖或执行真实API验收。

私有来源改为JSON后，存储、检索和runner集成定向回归79 passed，证据为`results/private_provenance_json_20261017/targeted.xml`。三种简单策略的小规模采集验证（N=30、H=9、smoke seed=90001）生成3条fixture轨迹、6条案例和9个revision；staging仅含公共SQLite与`private_manifest.json`，发布库只读加载及来源对应关系检查通过，没有私有SQLite文件。删除了私有SQL表、第二连接、双库提交和对应失败状态；清单格式及来源核对接口保持兼容。

开发工具移出与重复校验清理：知识、记忆和导入定向检查62 passed；五字段控制器、runner集成、存储、检索和公共契约回归163 passed，两组无重叠，共225 passed。证据位于`results/phase5_module_cleanup_20261017/{targeted,regression}.xml`。覆盖正常导入不加载或导出验收工具、每卡仅构造一次、直接构造bundle仍检查策略，以及JSON还原动作仍拒绝错误类型、长度和档位；保留字段白名单和对象自身检查。

控制效果、策略优劣、正式源域覆盖和 evaluation-ready 发布留给 Phase 6/7；Phase 5 的离线通过不代表这些结论已经得到验证。

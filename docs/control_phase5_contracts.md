# CEMAS v1 Phase 5 实施契约

更新日期：2026-10-17。状态：**离线工程实现完成；真实 provider/tokenizer 验收未执行。**

本契约记录 Phase 5 的实际接口、边界和本次验证结果。它不把 fixture、fake tokenizer 或离线 transport 当作真实服务验收，也不把案例检索通过当作控制效果结论。

## 实现边界

Phase 5 将研究方案落在 `cemas/control/`：

- `PublicEpisodeMemory` 只接收精确的 `PublicObservation` 和 `PublicWeekFeedback`；`stage()` 暂存决策前公共状态，`accept()` 使用实际反馈中的动作、资源和窗口生成本地 revision。
- `PublicCaseBuilder` 的公共 SQLite 与私有 source manifest 分离；`FrozenPublicCaseStore` 以只读连接打开并校验数据库 hash、schema、revision 和 opaque group。
- `NumericRetriever` 使用固定 38 维 state、最近三周趋势差分、`.75/.25` 权重、容量/动作/任务过滤、冲突对和确定性多样性选择；没有 embedding 或 LLM 摘要。
- `KnowledgeBundle` 固定六条 SIM 核心规则和三条版本化公共卫生卡；四种模式 `none/short/global/both` 使用同一公共 system、知识选择和五字段 wire。
- `MemoryLLMController` 通过 `LLMController` 的同一 transport、计数、重试和审计链完成消息准备与解析；runner 在执行前写 `decision_evidence.jsonl`，反馈后写实际执行动作和 `memory_revisions.jsonl`。
- `memory_collection` 只接受协议保留的 30001–30027 源池和 minimum/maximum_feasible/uniform legal 三种策略；evaluation-ready 的 108 条正式库仍由 Phase 6 的阈值与冻结证据决定。

控制器和 prompt 仍只看到公共输入。私有 reward、感染真值、beta、world seed、future event、simulator 和完整 audit 不进入 memory、检索或模型消息。

## 可复现入口

使用指定解释器：

```powershell
$repo = (Get-Location).Path
$env:PYTHONPATH = "$repo;$repo\results\control_v1_phase4\test_dependencies"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -m pytest `
  tests/test_control_memory.py tests/test_control_memory_store.py tests/test_control_retrieval.py `
  tests/test_control_knowledge.py tests/test_control_llm_memory.py `
  tests/test_control_memory_integration.py tests/test_control_llm.py `
  tests/test_control_runner.py tests/test_control_logging.py -q -m 'not online' `
  --basetemp results/control_v1_phase5/final_pytest_02 `
  --junitxml results/control_v1_phase5/final_02.xml
```

采集工具和入口：

```powershell
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' tools/collect_observable_memory.py --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' examples/control_v1/smoke_memory.py --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' examples/control_v1/run_memory_llm.py --help
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' examples/control_v1/accept_memory_llm.py --help
```

真实入口只接收 credential 环境变量名称；默认名称是 `DASHSCOPE_API_KEY`，代码和日志不读取或保存密钥值。真实运行还要求官方 tokenizer manifest/acceptance、P5 `memory_prompt_acceptance.json`、兼容的 E0 产物和（global/both 时）已验证的只读 source store。

## 本次验证

离线工程验证已完成：

- 合并后的 Phase 5 + P4 定向套件：**301 passed**，另有 **1 warning**（既有 pytest `env` 配置警告）；本次命令生成 `results/control_v1_phase5/final_02.xml`。
- 其中 Phase 5 memory、knowledge、LLM、store、retrieval 和 runner integration 的历史分组结果为 **199 passed**；P4 `LLMController`、runner、logging 回归分组为 **178 passed**。分组存在重叠，不能相加。
- 采集工具、模块导入和入口源文件通过 `py_compile`；`git diff --check` 通过。
- 验证证据目录：`results/control_v1_phase5/`，包括 `core_tests.xml`、`llm_pytest_03.xml`、`integration_tests.xml`、`review_tests.xml` 和最终定向测试 XML。

真实服务验收状态：**未执行**。本轮没有付费 API 调用、没有读取 `DASHSCOPE_API_KEY` 的值、没有正式科学仿真，也没有生产 27×4 源库。

## 后续门禁

`make_memory_llm_controller()` 在 live transport 下要求官方 tokenizer 和 P5 receipt；global/both 还要求只读 store、public task hash、私有 source manifest 和 E0 兼容性。`validate_memory_acceptance()` 会重新解析 receipt 中的公共观察/上下文，绑定当前 prompt、知识卡、案例库、注册表、必需 flags、消息 hash 和官方计数。任一资源或服务身份变化都必须重新生成 receipt。

控制效果、策略优劣、正式源域覆盖和 evaluation-ready 发布留给 Phase 6/7；Phase 5 的离线通过不代表这些结论已经得到验证。

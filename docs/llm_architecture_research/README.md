# CEMAS v1 LLM决策架构研究入口

> 2026-10-23 阅读说明：本目录保留2026-10-17研究交付时的代码、依赖、验收和人工示例快照，正文中的“当前checkout”和P5未实施等表述指当时状态。P5主要链和P6工程已有后续实现，实际状态见[阅读索引](../CEMAS_READING_INDEX.md)、[P5契约](../control_phase5_contracts.md)和[UW控制接入](../uw_control_integration.md)。人工示例用于结构验证，不作为当前人口、已校准结果或真实服务证据；旧报告门禁按现行P4/P5契约解释。

更新：2026-10-17（America/Los_Angeles）。这是基于当前 checkout 和公开资料形成的**设计交付**。它没有修改业务代码、既有协议或历史数据，也没有调用模型、安装依赖或运行正式疫情仿真。

推荐主方案已经收敛为：**单个无会话状态的决策 LLM + 程序确定性生成的公共近期摘要 + 版本冻结的知识卡 + 只读公共案例库 + 适用性/冲突/预算检查 + 现有共同 resolver**。每周从完整公共观察重建独立请求；案例在公共反馈闭合后才形成；私有感染、reward、seed、beta、未来事件、simulator 和完整审计对象始终不能进入控制器、提示词或案例。主路径没有在线反思器、经验写手、审查器、多角色辩论、世界模型或额外模拟查询。

## 按这个顺序阅读

1. [00_current_baseline.md](00_current_baseline.md)：当前分支、真实代码/契约、时间顺序、公共/私有边界、P4门禁、P5缺口和六条规则审查。
2. [01_research_evidence.md](01_research_evidence.md)：检索日志、原始论文/官方资料、最近邻、支持与限制、创新边界和关键问题矩阵。
3. [02_recommended_architecture.md](02_recommended_architecture.md)：主方案、数据流、模块接口、案例/摘要/检索字段、生命周期、检索算法、变更及公平性。
4. [04_knowledge_and_sessions.md](04_knowledge_and_sessions.md)：WHO/CDC/UKHSA知识组织、版本/冲突/适用性、供应商无状态会话与缓存核查、单次请求选择。
5. [05_prompts_and_examples.md](05_prompts_and_examples.md)：调用清单、完整模板说明、输出结构、程序逻辑、人工贯通示例和可信边界。
6. [03_validation_and_roadmap.md](03_validation_and_roadmap.md)：V01–V27验收矩阵、指标/统计、消融、公平预算、可证伪假设、论文定位和R0–R7路线。
7. [ACCEPTANCE.md](ACCEPTANCE.md)：本目标要求覆盖、自查结果和仍需真实API/实验的门禁。

静态示例和人工数据位于 [examples/](examples/)：

- `decision_template.json` 是完整的版本化 system 模板；动态知识、摘要、案例在 user JSON 中注入。
- `none_messages.json`、`both_messages.json` 和 `failure_messages.json` 是完整两消息，不使用省略号或字符串 mask 占位。
- `synthetic_cases.json`、`query_and_retrieval.json` 和 `terminal_feedback.json` 展示实际字段、数值距离、冲突、资源适配和 H=110 的五日尾窗。
- `build_examples.py` 只读取当前公共协议/模板生成文档样例；`verify_examples.py` 只加载现有公共 dataclass 检查结构和算术，不导入模拟器、不推进环境、不调用模型。
- `verification.json` 是最近一次静态检查结果；`manifest.json` 保存示例 hash 和基线 HEAD。人工示例中的 `token_count` 为 `null`，不能当作模型计数。

## 当前证据状态

当前 checkout 为 `feature/control-protocol-v1@2950e7f72355f03fda2bb69559378a06a9ca5eba`，研究开始时工作区干净。P4 契约中的 472 项早期离线结果和后续 572 passed/1 failed 登记都是历史记录；后期原始目录不在本 checkout，且旧 E0 产物因源码 hash 变化需要重新生成。真实 provider/tokenizer、P5 memory、真实案例收益、成本、解释忠实性和论文方法效果均未验证。

本目录的外部来源按“文献结论、项目事实、设计推断、待验证效果”分开书写；现实指南不转换成 CEMAS 的 T/S/C/E/A 最优阈值，案例相似度不等于已学会最优策略，公共后效不等于因果效果。

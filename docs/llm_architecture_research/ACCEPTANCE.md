# 目标要求覆盖与自查

日期：2026-10-17。下表是交付前自查，不把设计文件当作系统能力或实验结果。

| 目标要求 | 交付位置 | 自查结论 |
|---|---|---|
| 从当前索引、v1计划、推荐协议、JSON、P0–P4契约和真实代码进入 | [00_current_baseline.md](00_current_baseline.md) §1–§7 | 已完成静态核查；当前 head、阶段限制和历史证据已区分 |
| 保持公共/私有隔离、五维324动作、七日决策、共同执行/评价边界 | [00_current_baseline.md](00_current_baseline.md) §2–§6；[02_recommended_architecture.md](02_recommended_architecture.md) §2–§4 | 主方案不改任务边界；拟议新 wire 只适配原 ActionProposal |
| 疫情NPI、ABM/POMDP和部分观测决策研究 | [01_research_evidence.md](01_research_evidence.md) E01–E05 | 原始论文/官方资料、方法/限制和适配写明；不把论文效果外推 |
| LLM agent、few-shot、RAG、案例推理、记忆、反思、验证、多/单智能体、长上下文 | [01_research_evidence.md](01_research_evidence.md) E06–E26；[04_knowledge_and_sessions.md](04_knowledge_and_sessions.md) §4–§5 | 已覆盖支持证据和反证；主方案明确关闭未必要调用 |
| 专家知识采集、来源、版本、适用条件、冲突处理、使用机制 | [04_knowledge_and_sessions.md](04_knowledge_and_sessions.md) §1–§3；[examples/knowledge_cards.json](examples/knowledge_cards.json) | 9条代表性卡片含来源/日期/证据性质/限制/映射；核心六条始终保留，现实操作建议仅解释性 |
| 六条既有规则的保留价值与缺口 | [00_current_baseline.md](00_current_baseline.md) §8；[04_knowledge_and_sessions.md](04_knowledge_and_sessions.md) §3 | 已逐条审查，不称其为已验证最优策略 |
| 有效记忆条目生命周期、延迟反馈、实际动作、冲突和是否反思 | [02_recommended_architecture.md](02_recommended_architecture.md) §4–§5；[05_prompts_and_examples.md](05_prompts_and_examples.md) §2–§4 | 程序闭合公共案例；使用实际 executed_action；默认不反思；尾段和截短后窗显式标记 |
| 短期记忆与长期案例帮助选档的可检验机制 | [02_recommended_architecture.md](02_recommended_architecture.md) §4.2–§6；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) §4–§5 | 定义字段、query、过滤、排序、多样性、OOD/冲突/空结果和实验判定；不称案例为最优标签 |
| 27×4、top-k和相似度是否足够的审查 | [00_current_baseline.md](00_current_baseline.md) §9；[02_recommended_architecture.md](02_recommended_architecture.md) §6；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) §4.1 | 保留为开发起点并明确覆盖不足、world-out和扩库门槛 |
| 每个实际LLM调用的完整提示词、变量、权限、输出、时序、预算和失败 | [05_prompts_and_examples.md](05_prompts_and_examples.md)；[examples/decision_template.json](examples/decision_template.json) | 主路径只有 decision 调用；完整 system/user JSON 和人工五字段输出已生成；P4重试/回退边界继承 |
| 无记忆、正常、检索失败/冲突、末周贯通示例 | [examples/none_messages.json](examples/none_messages.json)、[examples/both_messages.json](examples/both_messages.json)、[examples/failure_messages.json](examples/failure_messages.json)、[examples/terminal_feedback.json](examples/terminal_feedback.json) | `verify_examples.py` 已核对完整公共结构、引用和尾窗时序；全为人工示例 |
| 可核查决策记录、证据引用、程序/模型/人工检查边界 | [02_recommended_architecture.md](02_recommended_architecture.md) §4.4/§7；[05_prompts_and_examples.md](05_prompts_and_examples.md) §4/§6；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) V16–V18 | 不保存/依赖完整思维链；引用存在不冒充忠实性或因果证明 |
| 单智能体/审查器/多智能体比较与明确选择 | [02_recommended_architecture.md](02_recommended_architecture.md) §1/§7；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) §4.3/§5 | 选择单控制器；审查/多体/ensemble只作等预算研究分支 |
| 独立请求、多轮、摘要、服务状态、缓存比较 | [04_knowledge_and_sessions.md](04_knowledge_and_sessions.md) §4–§5 | 已核对 DeepSeek/Qwen 官方无状态/缓存资料；主方案每周独立请求，缓存只作优化 |
| JAAMAS/AAMAS正式名称、范围、CCF及创新风险 | [01_research_evidence.md](01_research_evidence.md) §6；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) §5 | 使用 AAMAS、JAAMAS 期刊正式名称并说明 CCF 官方页访问限制；不保证投稿等级/录用 |
| 明确推荐主方案、替代方案取舍、接口/字段/时序和实施路线 | [02_recommended_architecture.md](02_recommended_architecture.md) 全文；[03_validation_and_roadmap.md](03_validation_and_roadmap.md) §6–§8 | 主方案已收敛；替代方案成本/公平/失败模式有记录；拟议实现不伪装成已改代码 |
| 未决点集中列出原因、影响、默认、替代与判定方法 | [03_validation_and_roadmap.md](03_validation_and_roadmap.md) §8；[04_knowledge_and_sessions.md](04_knowledge_and_sessions.md) §6 | 已集中列出 API、库覆盖、embedding、OOD、wire、审查、多体、反思、H/权重和创新风险 |

## 静态验证结果

执行命令（使用项目指定解释器）：

```powershell
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -B docs/llm_architecture_research/examples/build_examples.py
& 'E:\pytroch\anaconda3\envs\simulation\python.exe' -B docs/llm_architecture_research/examples/verify_examples.py
```

最近一次结果写入 [examples/verification.json](examples/verification.json)：

- `status=passed`；检查 7 个公共观察、36 个周记录、3 个响应、113 个引用和 12 个文件 hash。
- 另检查 324 位 mask、PublicWeeklyRecord growth/proxy 数学、实际 executed action、检索 38 维/趋势距离、三条外部知识来源映射、相同 system、人工输出字段和 H=110 五日尾窗。
- 该命令只加载 `cemas/control/types.py` 的 dataclass；未导入模拟器，不推进环境，不调用 API，不安装依赖。

## 仍未满足“真实能力已证实”的门禁

1. 官方 tokenizer 资源、服务身份、usage 和真实 provider 三类消息验收。
2. P5 memory/retrieval 代码实现及其测试；当前目录是接口和静态样例。
3. 重新生成并验收与当前源码 hash 相容的 E0；不能使用历史旧产物。
4. 源域案例采集、覆盖/leave-world-out、检索与记忆消融、E1–E4目标实验、成本/延迟和统计区间。
5. 证据理由的人工盲评、扰动测试和方法创新的实证支持。

完成设计文档不等于这些门禁通过；任何后续论文结果必须引用真实运行产物、模型身份、数据划分和失败记录。

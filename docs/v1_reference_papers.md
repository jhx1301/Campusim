# CEMAS v1 构建参考论文及用途清单

整理日期：2026-10-22。

按现有仓库文档去重，可追溯到 **48 篇有明确参考用途的论文与研究报告**（含 1 篇 CDC MMWR 校园暴发报告）。范围包括 v1 任务设计、P4/P5 LLM 架构研究、P6 强化学习实现，以及后续回复和校准研究。后续补查不追溯表述为早期实现来源；具体采用边界逐项列出。

“参考”包括直接实现依据、机制借鉴、方案比较、反证及相关工作。表中的“阶段”表示关联模块，不单凭引用日期推定因果。已有文献不能代替本项目的效果验证；标为建议、比较或未移植的内容，不代表已实现。此清单覆盖已落盘记录，无法还原没有记录的全部历史阅读。

同一论文不同版本合并计数。年份优先采用正式发表年；依赖预印本的条目明确写出所读版本或首稿。逐项链接指向论文一手页面；本次核对题名与链接，参考用途以对应本地记录为依据，未重新复现实验。为忠实还原研究过程，所读预印本与其后续发表状态不混写。

**1．仿真、公共观测与控制任务（5 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 1 | [Covasim: An agent-based model of COVID-19 dynamics and interventions](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1009149)；Kerr 等，2021 | 多层接触、疾病进程、检测/追踪/隔离机制及校准思路；作为引擎基础，并提醒控制扩展仍需独立验证。 | 引擎基础；P0–P3、E0 | [LLM研究证据 E01](llm_architecture_research/01_research_evidence.md)；[校准验证调研](abm_calibration_validation_research.md) |
| 2 | [Response to a COVID-19 Outbreak on a University Campus — Indiana, August 2020](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)；Fox 等，2021；CDC MMWR | Notre Dame 校园暴发与响应资料用于 E0 重建数据和知识卡 PH-01；参考组合措施、资源扩充及报告局限。 | 数据/知识依据；E0、P5 | [v1推荐协议](llm_recommended_protocol_v1.md)；[E0数据说明](../data/README.md)；[知识与会话研究](llm_architecture_research/04_knowledge_and_sessions.md)；[现行知识卡](../cemas/control/knowledge/public_knowledge_v1.json) |
| 3 | [Planning Multiple Epidemic Interventions with Reinforcement Learning](https://www.ijcai.org/proceedings/2023/682)；Mai 等，2023；IJCAI | 周闭环控制、多干预规划和疾病负担/干预负担共同评价；v1 将其适配为公共观测及非货币负担。 | 任务设计参考；早期总体方案、P3/P6 | [早期总体方案](archive/llm_baseline_generalization_plan.md)；[回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |
| 4 | [Using Reinforcement Learning for Multi-Objective Cluster-Level Optimization of Non-Pharmaceutical Interventions for Infectious Disease](https://proceedings.mlr.press/v225/peng23a.html)；Peng 等，2023；ML4H/PMLR | 部分可观测决策和检测的信息价值；案例需保留检测强度、缺失情况，不能照搬原文阈值或感染后验。 | 任务/案例设计取舍；P4–P5 | [LLM研究证据 E02](llm_architecture_research/01_research_evidence.md) |
| 5 | [Controlling Graph Dynamics with Reinforcement Learning and Graph Neural Networks](https://proceedings.mlr.press/v139/meirom21a.html)；Meirom 等，2021；ICML | 部分可观测图过程控制与疫情检测已有先例，用于相关工作和收窄创新表述。 | 相关工作；回复补查，未移植 GNN | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |

**2．强化学习实现与评估（4 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 6 | [Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347)；Schulman 等，2017 | PPO 采样和多轮 minibatch 更新的算法依据；项目复用 MaskablePPO 实现。 | 算法实现依据；P6 | [P6实施计划](control_phase6_implementation_plan.md) |
| 7 | [A Closer Look at Invalid Action Masking in Policy Gradient Algorithms](https://arxiv.org/abs/2006.14171)；Huang、Ontañón，2020 首稿 | 用合法动作掩码约束策略分布；训练和推理保持同一合法动作语义。 | 算法实现依据；P6，衔接 P1 mask | [P6实施计划](control_phase6_implementation_plan.md) |
| 8 | [Deep Reinforcement Learning with Double Q-learning](https://arxiv.org/abs/1509.06461)；van Hasselt 等，2015 首稿／AAAI 2016 | 在线网络选动作、目标网络估值；v1 在此基础上对探索、贪心和 bootstrap 处理合法动作。 | DDQN 实现依据；P6 | [v1推荐协议](llm_recommended_protocol_v1.md)；[P6实施计划](control_phase6_implementation_plan.md)；[早期总体方案](archive/llm_baseline_generalization_plan.md) |
| 9 | [Deep Reinforcement Learning at the Edge of the Statistical Precipice](https://arxiv.org/abs/2108.13264)；Agarwal 等，2021；NeurIPS | 报告训练波动与统计不确定性，避免以最佳训练种子代表算法。三个种子的数量来自 v1 设计。 | 评估设计参考；P6–P7 | [P6实施计划](control_phase6_implementation_plan.md) |

**3．LLM 架构、案例与记忆（16 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 10 | [Case-Based Reasoning: Foundational Issues, Methodological Variations, and System Approaches](https://journals.sagepub.com/doi/10.3233/AIC-1994-7104)；Aamodt、Plaza，1994 | 检索—复用—修订—保留的案例循环；强调适配条件、失败经验及来源追踪，不能只找相似案例。 | 案例机制借鉴；P5 | [LLM研究证据 E06](llm_architecture_research/01_research_evidence.md) |
| 11 | [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)；Brown 等，2020；NeurIPS | 把案例作为推理时的上下文演示；区分外部经验注入与模型权重训练。 | 案例注入概念依据；P5 | [LLM研究证据 E07](llm_architecture_research/01_research_evidence.md) |
| 12 | [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)；Lewis 等，2020；NeurIPS | 外部检索结果进入生成上下文，检索规模在开发数据上选择；v1 未复现原文检索器/生成器联合训练。 | 检索注入思想；P5 | [LLM研究证据 E08](llm_architecture_research/01_research_evidence.md) |
| 13 | [Cognitive Architectures for Language Agents（CoALA）](https://arxiv.org/abs/2309.02427v3)；Sumers 等，2024；TMLR | 区分工作记忆、情景经验、语义知识与程序规则，明确各类信息在决策循环中的职责。 | 架构组织依据；P4–P5 | [LLM研究证据 E09](llm_architecture_research/01_research_evidence.md) |
| 14 | [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442v2)；Park 等，2023；UIST | 参考经验流、相关性/新近性检索与反思架构；因添饰和遗漏风险，v1 采用程序生成公共事实摘要。 | 方案取舍；未照搬重要性自评或反思 | [LLM研究证据 E10](llm_architecture_research/01_research_evidence.md) |
| 15 | [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)；Yao 等，2023；ICLR | 参考行动与外部反馈的闭环；v1 公共输入固定，因此没有增加自由工具探索或未来仿真试运行。 | 方案取舍；P4–P5 | [LLM研究证据 E11](llm_architecture_research/01_research_evidence.md) |
| 16 | [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)；Shinn 等，2023；NeurIPS | 参考反馈形成文本经验而不更新权重；识别公共病例变化缺乏动作因果标签，默认不增加反思调用。 | 方案取舍；后续来源建议也引用 | [LLM研究证据 E12](llm_architecture_research/01_research_evidence.md)；[全局记忆来源建议](global_memory_source_design_proposal.md) |
| 17 | [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291v2)；Wang 等，2023 所读预印本 | 参考可验证的经验复用和执行反馈；v1 固定动作集合，程序规则由版本化代码维护。 | 方案取舍；未引入自动技能代码生成 | [LLM研究证据 E13](llm_architecture_research/01_research_evidence.md) |
| 18 | [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560v2)；Packer 等，2023 首稿 | 区分外部持久记忆与上下文窗口、会话状态；支持每周显式重建请求的设计判断。 | 上下文管理取舍；P4–P5 | [LLM研究证据 E14](llm_architecture_research/01_research_evidence.md)；[知识与会话研究](llm_architecture_research/04_knowledge_and_sessions.md) |
| 19 | [A-Mem: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110v11)；Xu 等，2025；NeurIPS | 参考记忆链接和演化，同时识别自由改写的事实风险；v1 保留公共事实及显式修订链。 | 记忆修订设计取舍；未引入自由演化记忆 | [LLM研究证据 E15](llm_architecture_research/01_research_evidence.md) |
| 20 | [ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory](https://arxiv.org/abs/2509.25140v2)；Ouyang 等，2025 首稿；所读 v2 | 成功与失败经验都应保留；不把 LLM 自评分直接当作公共事实或动作效果标签。 | 案例组成与质量取舍；P5 | [LLM研究证据 E16](llm_architecture_research/01_research_evidence.md) |
| 21 | [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)；Asai 等，2024；ICLR | 参考检查检索内容是否受证据支持；v1 用适配条件及引用检查，不复现 reflection-token 训练。 | 检索使用取舍；P5 | [LLM研究证据 E17](llm_architecture_research/01_research_evidence.md) |
| 22 | [How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior](https://aclanthology.org/2026.acl-long.27/)；Xiong 等，2026；ACL | 相似经验可能诱发错误模仿；区分案例数据有效性与策略优越性，避免只按文本相似度写入/检索。 | 记忆质量与失败分析参考；P5–P7 | [LLM研究证据 E22](llm_architecture_research/01_research_evidence.md) |
| 23 | [When Continual Learning Moves to Memory: A Study of Experience Reuse in LLM Agents](https://arxiv.org/abs/2604.27003v1)；Hu 等，2026；预印本 | 外部记忆保存完好仍可能因上下文竞争产生遗忘与负迁移；支持错误/过时案例压力测试。 | 风险与验证设计参考；效果待项目验证 | [LLM研究证据 E23](llm_architecture_research/01_research_evidence.md) |
| 24 | [Reason for Future, Act for Now: A Principled Architecture for Autonomous LLM Agents（RAFA）](https://proceedings.mlr.press/v235/liu24ab.html)；Liu 等，2024；ICML | 记忆、反馈、规划和行动循环已有先例；用于相关工作与创新边界。 | 回复补查；未移植其规划算法 | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |
| 25 | [DiLu: A Knowledge-Driven Approach to Autonomous Driving with Large Language Models](https://proceedings.iclr.cc/paper_files/paper/2024/hash/93c936b9e492def9c00782cab79dbc6d-Abstract-Conference.html)；Wen 等，2024；ICLR | 知识、记忆、推理和反思相结合的决策先例；后续混合来源库建议参考其交互经验思路。 | 相关工作/后续建议；未照搬自动驾驶架构 | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md)；[全局记忆来源建议](global_memory_source_design_proposal.md) |

**4．可核查解释、上下文与单/多智能体取舍（10 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 26 | [Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting](https://arxiv.org/abs/2305.04388)；Turpin 等，2023；NeurIPS | 自然语言解释可能掩盖输入偏置；决策记录应保留可核查证据、动作与简短权衡。 | 解释边界依据；P5 | [LLM研究证据 E18](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 27 | [Enabling Large Language Models to Generate Text with Citations（ALCE）](https://aclanthology.org/2023.emnlp-main.398/)；Gao 等，2023；EMNLP | 区分答案正确、引用存在、引用覆盖和引用支持；v1 校验引用 ID，语义支持另需评估。 | 引用核验设计依据；P5 | [LLM研究证据 E19](llm_architecture_research/01_research_evidence.md) |
| 28 | [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798)；Huang 等，2024；ICLR | 无外部正确性反馈时自纠正可能退化；主调用给全规则，修正聚焦确定的格式/引用错误。 | 调用/纠错设计取舍；P4–P5 | [LLM研究证据 E20](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 29 | [Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/abs/2305.14325)；Du 等，2024；ICML | 参考多体辩论的潜在收益及错误共识、额外成本；研究分支需固定权限、预算与终止条件。 | 单/多体方案比较；主方案未引入辩论 | [LLM研究证据 E21](llm_architecture_research/01_research_evidence.md) |
| 30 | [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296v2)；Kim 等，2025 首稿；所读 v2 | 多体收益依赖任务可分性与协调结构；单校园统一观察、联合动作下优先单控制器。 | 架构取舍；不能推成单体普遍更优 | [LLM研究证据 E24](llm_architecture_research/01_research_evidence.md) |
| 31 | [Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets](https://arxiv.org/abs/2604.02460v1)；Tran、Kiela，2026；所读 v1 | 等预算比较及 API 思考预算计量偏差；同时记录实际 token、调用次数和时延。 | 预算公平性参考；P4–P7 | [LLM研究证据 E24](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 32 | [Lost in the Middle: How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9/)；Liu 等，2024；TACL | 证据位置和上下文长度可能影响利用效果；研究建议固定关键输入位置并做顺序置换测试。 | 提示组织/验证参考；P4–P5 | [LLM研究证据 E27](llm_architecture_research/01_research_evidence.md) |
| 33 | [Measuring Faithfulness in Chain-of-Thought Reasoning](https://arxiv.org/abs/2307.13702)；Lanham 等，2023；预印本 | 参考干预推理文本来测其对输出的因果作用；限制把 reason 字段视为内部原因的透明记录。 | 解释验证研究参考；非已完成实验 | [LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 34 | [Multi-Agent Reasoning Improves Compute Efficiency: Pareto-Optimal Test-Time Scaling](https://arxiv.org/abs/2605.01566v1)；Wunderlich 等，2026；所读预印本 | 保留多体可能改善计算—准确率取舍的正面证据；单体默认是任务判断，多体净收益需等预算验证。 | 方案比较的补充证据；非已实现模块 | [LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 35 | [MemMA: Coordinating the Memory Cycle through Multi-Agent Reasoning and In-Situ Self-Evolution](https://arxiv.org/abs/2603.18718v2)；Lin 等，2026；所读 v2 | 多角色协调记忆写入、检索与使用，probe 检查缺失/矛盾；v1 结构化账本优先用程序做完整性核验。 | 多角色记忆方案比较；未移植其多体流程 | [LLM研究证据 E26](llm_architecture_research/01_research_evidence.md) |

**5．LLM 疫情决策与预测的直接近邻（4 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 36 | [AI Agents as Policymakers in Simulated Epidemics](https://arxiv.org/abs/2601.04245v1)；Aoki、Ghaffarzadegan，2026；预印本 | 已有每周 LLM 政策、近期记忆、知识注入及 ensemble 比较；用于最近邻对比和拆分知识/多次调用收益。 | 相关工作/架构取舍；不能将组合本身称独创 | [LLM研究证据 E03](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 37 | [EpiWorld: Grounding LLM Policy Agents in Epidemiological World Models](https://arxiv.org/abs/2610.02744v1)；Memon 等，2026；所读 arXiv v1 | 世界模型、分层知识/经验和反事实 rollout 的近邻；参考适用域、经验失效与独立评估。 | 最近邻比较；主方案未引入世界模型 | [LLM研究证据 E04](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 38 | [Coordinated Pandemic Control with Large Language Model Agents as Policymaking Assistants](https://arxiv.org/abs/2601.09264v1)；Shi 等，2026；预印本 | 多地区智能体通过通信处理流动外部性；用于判断多体分工何时有真实任务依据。 | 最近邻比较；未移植多辖区协调 | [LLM研究证据 E05](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |
| 39 | [EpiEvolve: Self-Evolving Agents for Streaming Pandemic Forecasting under Regime Shifts](https://arxiv.org/abs/2606.05513v1)；Lu 等，2026；预印本 | 严格先预测、后揭示标签，再更新经验；参考反馈时间边界，同时区分预测标签与干预因果标签。 | 时间边界/创新定位参考；未移植预测反思系统 | [LLM研究证据 E25](llm_architecture_research/01_research_evidence.md)；[LLM验证与路线](llm_architecture_research/03_validation_and_roadmap.md) |

**6．回复、校准验证及后续研究补充（9 篇）**

| 编号 | 论文、作者与年份 | v1 具体参考了什么 | 用途与采用边界 | 本地记录 |
|---|---|---|---|---|
| 40 | [Reinforcement Learning for Optimization of COVID-19 Mitigation Policies](https://arxiv.org/abs/2010.10560)；Kompella 等，2020 首稿 | 基于个体模拟的疫情干预强化学习已有先例，支撑回复中的相关工作说明。 | 回复补查；不是新增实现依据 | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |
| 41 | [EpidemiOptim: A Toolbox for the Optimization of Control Policies in Epidemiological Models](https://arxiv.org/abs/2010.04452)；Colas 等，2020 首稿 | 疫情策略优化和多目标取舍已有工具与研究，限制笼统的首次优化主张。 | 回复补查；未引入该工具箱 | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |
| 42 | [Controlling COVID-19 via test-trace-quarantine](https://www.nature.com/articles/s41467-021-23276-9)；Kerr 等，2021；Nature Communications | 多观测校准与后续时期检验；区分使用后续历史输入的条件检验和截止日预测。 | 2026-10-20 校准调研；建议尚未实施 | [校准验证调研](abm_calibration_validation_research.md) |
| 43 | [Multi-source agent-based modeling to optimize influenza mitigation strategies in Hong Kong](https://www.nature.com/articles/s41467-026-74857-5)；Peng 等，2026；Nature Communications | 多来源观测、季节/历史条件、多目标校准、峰前留出与敏感性检验；用于审视 E0 证据强度。 | 2026-10-20 校准调研；未移植参数或流程 | [校准验证调研](abm_calibration_validation_research.md) |
| 44 | [Optimization of infectious disease intervention measures using reinforcement learning with UK COVID-19 epidemic data](https://www.nature.com/articles/s41598-026-39377-8)；Zhang 等，2026；Scientific Reports | 按日期重放历史干预再校准，并在重校准的香港场景评估策略迁移；区分校准、预测和模拟内控制证据。 | 2026-10-20 校准调研；未复现其研究 | [校准验证调研](abm_calibration_validation_research.md) |
| 45 | [System identifiability in a time-evolving agent-based model](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0290821)；Robin 等，2024；PLOS ONE | 曲线吻合不保证参数可识别；检查不同参数/检测假设是否得到相似观测却改变隐藏状态和策略排序。 | 2026-10-20 验证建议；非已完成分析 | [校准验证调研](abm_calibration_validation_research.md) |
| 46 | [Recommended reporting items for epidemic forecasting and prediction research: The EPIFORGE 2020 guidelines](https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1003793)；Pollett 等，2021；PLOS Medicine | 预测截止日、回顾/前瞻性质、验证、基线、时域、不确定性和适用范围的报告要求。 | 2026-10-20 报告规范参考；不是控制算法 | [校准验证调研](abm_calibration_validation_research.md) |
| 47 | [Practical considerations for measuring the effective reproductive number, Rt](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008409)；Gostic 等，2020；PLOS Computational Biology | R_t 定义、代际间隔与观测延迟；用于后续参数接受方案的依据，避免把拟合曲线等同全部传播证据。 | 回复后续建议；未新增在线 R_t 输入 | [回复证据及后续建议](rebuttal_v1_evidence_and_next_steps.md) |
| 48 | [Mediation analysis with time varying exposures and mediators](https://rss.onlinelibrary.wiley.com/doi/10.1111/rssb.12194)；VanderWeele、Tchetgen Tchetgen，2017 | 时变暴露、媒介与混杂下的中介效应识别限制；用于记忆影响动作保持期及结果的实验建议。 | 后续机制实验建议；尚未实施 | [记忆与保持期实验建议](memory_duration_experiment_design.md) |

**7．使用过的非论文资料（不计入上述 48 篇）**

| 资料 | v1 参考内容 | 本地记录 |
|---|---|---|
| [WHO，Considerations for implementing and adjusting public health and social measures in the context of COVID-19，2023](https://www.who.int/publications/i/item/considerations-in-adjusting-public-health-and-social-measures-in-the-context-of-COVID-19-interim-guidance) | 按当地情势与社会负担复核措施的原则；对应 PH-03，不提供本仿真最优阈值。 | [知识研究](llm_architecture_research/04_knowledge_and_sessions.md)、[知识卡](../cemas/control/knowledge/public_knowledge_v1.json) |
| [UKHSA，Data quality report: national flu and COVID-19 surveillance report](https://www.gov.uk/government/publications/sources-of-surveillance-data-for-influenza-covid-19-and-other-respiratory-viruses/data-quality-report-national-flu-and-covid-19-surveillance-report) | 检测政策、样本来源和报告制度影响趋势可比性；对应 PH-02。 | 同上 |
| [WHO，Sustaining lives and livelihoods: a decision framework for calibrating social and movement measures during the COVID-19 pandemic，2020](https://www.who.int/publications/i/item/9789240017948) | 本地研究以“WHO lives and livelihoods framework”登记，仅作为健康与经济负担权衡的背景，未进入现行外部知识卡。 | [知识研究 H04](llm_architecture_research/04_knowledge_and_sessions.md) |
| Covasim 官方校准教程 | 外部检测输入不能作为独立验证；拟合对象、随机重复和校准方法。 | [校准调研](abm_calibration_validation_research.md) |
| SB3 / SB3-contrib、Gymnasium、PyTorch 官方文档 | MaskablePPO 接口、终止与截断语义、输入尺度和模型保存加载。 | [P6 实施计划](control_phase6_implementation_plan.md) |
| DeepSeek / Qwen 官方 API 与 tokenizer 文档 | 请求参数、显式历史、token 计量、缓存和重试；属于工程接口资料。 | [P4 契约](control_phase4_contracts.md)、[知识与会话研究](llm_architecture_research/04_knowledge_and_sessions.md) |

**8．记录不足的两条检索线索**

| 线索 | 本地保留的阅读边界 | 处理 |
|---|---|---|
| Flaxman 等 | [研究证据的访问限制](llm_architecture_research/01_research_evidence.md)仅记载 Nature 页面摘要与元信息可读、正文受限，用作背景。 | 未完整登记题名，不能可靠指定具体篇目或声称全文采用，不计入 48 篇。 |
| Larremore 等关于报告延迟/筛查频率的研究 | [知识研究的检索记录](llm_architecture_research/04_knowledge_and_sessions.md)记载 Science PDF 访问失败，仅有检索摘要，未用于定量或核心设计。 | 未完整登记题名，不补猜具体论文，不计入 48 篇。 |

**9．仅见于上游继承文献库的条目（不计入 48 篇）**

根目录 [papers.bib](../papers.bib) 有 17 条记录，其中 Covasim 与 test-trace-quarantine 已列入第 1、42 项。其余 15 条如下。当前 v1 文档未给出它们的直接采用映射，因此仅登记原库题名与年份，不能据此声称 v1 构建时实际参考了全部条目。

| 原库年份 | 论文题名 |
|---|---|
| 2021 | Quantifying the role of naturally- and vaccine-derived neutralizing antibodies as a correlate of protection against COVID-19 variants |
| 2020 | Determining the optimal strategy for reopening schools, the impact of test and trace interventions, and the risk of occurrence of a second COVID-19 epidemic wave in the UK: a modelling study |
| 2021 | Estimating and mitigating the risk of COVID-19 epidemic rebound associated with reopening of international borders in Vietnam: a modelling study |
| 2020 | Modelling the impact of reducing control measures on the COVID-19 pandemic in a low transmission setting |
| 2021 | Role of masks, testing and contact tracing in preventing COVID-19 resurgences: a case study from New South Wales, Australia |
| 2021 | Modelling the potential impact of mask use in schools and society on COVID-19 control in the UK |
| 2020 | Schools are not islands: Balancing COVID-19 risk and educational benefits using structural and temporal countermeasures |
| 2020 | COVID-19 reopening strategies at the county level in the face of uncertainty: Multiple Models for Outbreak Decision Support |
| 2022 | Preventing a cluster from becoming a new wave in settings with zero community COVID-19 cases |
| 2021 | Modelling the impact of reopening schools in the UK in early 2021 in the presence of the alpha variant and with roll-out of vaccination against SARS-CoV-2 |
| 2021 | Partial lockdown on unvaccinated individuals promises breaking of fourth COVID-19 wave in Bavaria |
| 2021 | Returning to a normal life via COVID-19 vaccines in the United States: a large-scale Agent-Based simulation study |
| 2022 | An agent-based model to assess large-scale COVID-19 vaccination campaigns for the Italian territory: The case study of Lombardy region |
| 2022 | Estimation of local time-varying reproduction numbers in noisy surveillance data |
| 2022 | A simulation-deep reinforcement learning (SiRL) approach for epidemic control optimization |

上述年份忠实保留原库字段，未逐条校正为最新正式发表版本。原库还有重复 BibTeX key，本次仅整理清单，未修改上游文献库。

**10．引用时需要保留的边界**

- 引用 PPO、DDQN、action masking 时，可说明算法依据；引用 RAG/CoALA/CBR 时，应说明借鉴的具体机制，避免声称复现原方法。
- Generative Agents、ReAct、Reflexion、A-Mem、MemGPT、Voyager、Self-RAG、MemMA 等被用于比较和取舍，不代表 v1 同时实现这些系统。
- 记忆库加入训练后 RL/LLM 轨迹、保持期中介实验、额外校准验证仍以各自建议文档为准；本清单不将建议写成已完成结果。
- v1 的五维 324 动作、七日周期、检索维数、top-k、距离权重、奖励权重与校准搜索量等具体数值，应引用本项目协议和验证记录；不能只凭以上论文给出最优性背书。

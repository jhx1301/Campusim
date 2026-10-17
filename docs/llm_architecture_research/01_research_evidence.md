# LLM 决策模块：研究证据、最近邻与采用结论

检索与访问日期：**2026-10-17（America/Los_Angeles）**。这是面向架构取舍的定向研究，不是穷尽式系统综述。项目当前实现事实另见本目录的现状基线；本文件不将论文结果当成 CEMAS 实验结果。

证据标记：**[文献]** 作者报告的方法或结果；**[限制]** 原文限制或本次明确标注的适配限制；**[设计推断]** 根据任务边界作出的选择；**[待验证]** 必须由本项目实验确认。除特别说明，以下关键来源已打开全文并阅读所列方法、实验及限制位置；预印本的发表状态按所访问版本记录，不暗示已通过同行评审。

## 1. 检索记录与停止依据

| 轮次 | 范围、核心关键词 | 纳入与排除 | 对决策的影响 |
|---|---|---|---|
| 广度检索 A | `Covasim agent-based model intervention`; `epidemic POMDP reinforcement learning NPI`; `WHO adjusting public health social measures` | 优先模拟器原始论文、PMLR 原文、WHO 官网；未将新闻、论坛或综述中的数字当结论 | 确立部分观测、行动改变观测、资源与负担需共同评价 |
| 广度检索 B | `LLM epidemic intervention policy memory`; `AI Agents as Policymakers`; `EpiWorld`; `Coordinated Pandemic Control` | 纳入 E03–E05，阅读全文和附录；居民行为模拟与政府选档分开 | 推翻“LLM+知识+记忆+每周疫情决策本身新颖”的预设 |
| 机制检索 C | `case-based reasoning retrieve reuse revise retain`; `RAG`; `CoALA`; `ReAct`; `Reflexion`; `A-Mem`; `ReasoningBank`; `MemGPT`; `Voyager` | 追溯奠基论文并阅读新记忆方法；按任务与反馈来源比较 | 选择显式、可追溯的经验，不默认把自由文本反思视为已验证知识 |
| 可靠性检索 D | `unfaithful explanations chain of thought`; `ALCE citation`; `cannot self-correct reasoning`; `multiagent debate`; `scaling agent systems`; `Lost in the Middle` | 同时纳入支持与反证；使用论文方法和限制而非只读摘要 | 选择程序校验，审查器与辩论进入消融，不作为可靠性保证 |
| 补查 1 | `LLM memory negative transfer conflicting experiences 2026`; `multi agent equal token budget sequential planning` | 纳入 E22–E24；阅读方法、结果与评估限制 | 未改变主方案；加强错误记忆、误适配与实际 token 对齐的风险证据 |
| 补查 2 | `LLM epidemic memory partial`; `LLM agents delayed feedback memory`; `epidemic case-based reasoning interventions` | 纳入 E25 EpiEvolve、E26 MemMA；全文核对；其余只做线索，不用于性能判断 | 未改变主方案及核心风险判断；补齐延迟标签与多角色记忆的正面证据，并收窄创新表述 |

覆盖后连续两轮补查未改变“单决策器、每周独立请求、确定性公共记忆、冻结案例库、程序核验”的推荐，也未消除“外部记忆可能负迁移、反馈不等于因果标签”的核心风险。停止继续扩展相邻论文列表；将 CEMAS 选档增益、最佳检索规模、反思净收益、真实 API 成本留作实验假设。此停止依据不等于已证明没有其他近邻。

访问限制：部分 OpenReview PDF 被浏览器挑战拦截，改读同文 arXiv PDF 或会议原始 PDF；若干 arXiv 裸 PDF 返回内部错误，改读固定版本 HTML。PMC 部分页面出现验证码，未据此声称读完相应全文。Nature 的 Flaxman 页面可读摘要与元信息但正文出现访问限制，故只作背景线索，不用于本项目关键阈值设计。E05 的补充材料链接在 HTML 中为独立附件，本次没有核对完整附件；关于通信具体参数的结论只限主文。未下载模型、安装依赖、运行论文代码或调用付费模型。

## 2. 疫情决策与最近邻

### E01 — Covasim：模拟器机制证据

[Kerr et al., Covasim: An agent-based model of COVID-19 dynamics and interventions](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1009149)，PLOS Computational Biology，2021-07-26。阅读 §2 模型/干预、§3 结果、§4 讨论。

**[文献]** 个体仿真包含多层接触、疾病进程、检测、隔离、追踪等干预，并可表示报告延迟与失访；用途包括干预情景评估。**[限制]** 机制与参数需要本地校准，模拟器适用性不等于一个控制器的政策有效性。**[设计推断]** 案例必须记录执行与观测时间、接触/检测类动作的区别及资源背景；不能把隐藏感染曲线混入控制器记忆，也不能从原版 Covasim 推定 CEMAS 所有扩展机制。

### E02 — 部分观测下的 NPI 优化

[Peng et al., Using Reinforcement Learning for Multi-Objective Cluster-Level Optimization of Non-Pharmaceutical Interventions for Infectious Disease](https://proceedings.mlr.press/v225/peng23a/peng23a.pdf)，ML4H/PMLR 225，2023-12-10。阅读 §2–4、限制及附录。

**[文献]** 将接触者检测/隔离建模为 POMDP；用监督解码器估计感染概率、固定维度且置换不变的观察表示接 PPO，并蒸馏为决策树。报告在所建分支过程测试床上较基线最高改善 27%。**[限制]** 不观测真实感染；其训练解码器使用仿真标签；无检测时阈值最优性的证明依赖特定成本与动作假设。**[设计推断]** 检测同时影响信息质量和防控，需在案例适配中保留检测强度与缺失情况；不借用该论文阈值、不向 LLM 提供感染后验真值，也不把其最优性证明推广到 324 联合动作。

### E03 — 每周 LLM 政策、知识与记忆已存在

[Aoki & Ghaffarzadegan, AI Agents as Policymakers in Simulated Epidemics](https://arxiv.org/html/2601.04245v1)，预印本，2026-01-06。阅读 §2.1–2.3、§3–4、提示词附录。

**[文献]** GPT-5 nano 每七日选择一个业务限制强度；五个历史事件按新近性随机抽取。SEIR/带行为反馈 SEIRb × 基础/知识/十次独立调用平均/二者结合，每格十次仿真。知识总体有益，纯 ensemble 可比单体更差。**[限制]** 每周病例完全准确，知识匹配真实因果结构；单一模型、单一控制维度，无 CEMAS 式延迟账本与资源联合约束。**[设计推断]** 提供机制知识值得验证，但知识与多次调用收益必须分离；该论文直接排除“每周 LLM+记忆+知识”为独立创新点。

### E04 — EpiWorld：最强架构重合

[Memon et al., EpiWorld: Grounding LLM Policy Agents in Epidemiological World Models](https://arxiv.org/html/2610.02744v1)，预印本，2026-10-02。阅读 §3–5、Limitations、附录 I/K/L。

**[文献]** 延迟编码、图结构、动作条件世界模型配合协议约束/监测工具/经验三层库；以反事实 rollout 更新经验。包含真实美国数据、COVID/流感仿真，时空/干预 OOD、独立模拟器复核与无 LLM 对照。其跨感染情景经验迁移出现负收益，置信区间覆盖不足。

**[限制]** 真实数据没有反事实真值；未见动作组合依赖外推。文中“协议约束”仍有提案超界并转人工的情况，不能据此宣称硬保证。

**[设计推断]** 吸收经验适用域、失效版本与独立评估思想；不引入在线世界模型或仿真反事实工具。CEMAS 若将其作为新实验分支，须单独声明训练数据、成本与信息权限，不能隐含加入主方案。

### E05 — 多智能体的有效分工来自真实分布式任务

[Shi et al., Coordinated Pandemic Control with Large Language Model Agents as Policymaking Assistants](https://arxiv.org/html/2601.09264v1)，预印本，2026-01-14。阅读 Results、Methods、Discussion。

**[文献]** 每州一个 agent，交换风险与政策消息；通过 SEIQRD 和州际流动数据比较固定总流量的跨周重分配、空间流量抑制和筛查。评估五州及二十州，发现空间转移可伤害部分地区，时间分配更稳定。**[限制]** 仿真回顾评估；以流动为主，执行依从与行政约束简化；主文没有提供与等预算单一全局控制器的充分因果隔离。**[设计推断]** 这是多辖区外部性与分散决策的理由，不能自动转成单校园内“检测专家+封控专家”的必要性。

### E25 — EpiEvolve：延迟反馈、经验和情景检索也已存在

[Lu et al., EpiEvolve: Self-Evolving Agents for Streaming Pandemic Forecasting under Regime Shifts](https://arxiv.org/html/2606.05513v1)，预印本，2026-06-03。阅读 §3–5、Limitations。

**[文献]** 冻结暖启动训练后的模型；对 50 州、81 周的住院趋势进行五类预测。全周预测固定后才揭示标签，随后反思、更新分层经验和规则；基于可见变体文本/历史误差调整检索。报告准确率 0.629 对静态 0.561；去掉 reflection 同时关闭规则蒸馏，作者另作贡献分解。

**[限制]** 预测有事后正确标签，干预控制没有单个动作的事后因果标签；仅住院趋势分类，情景边界、提示词、预算敏感。**[设计推断]** 采用严格反馈可用时间与先预测后更新；不照搬“错误→策略教训”。将反思作为发展阶段的受控比较，不能借预测增益宣称本项目选档会改善。

## 3. 记忆、案例与推理机制

### E06 — 案例推理的完整循环

[Aamodt & Plaza, Case-Based Reasoning: Foundational Issues, Methodological Variations, and System Approaches](https://www.iiia.csic.es/~enric/papers/Aamodt_1994_Case.pdf)，AI Communications 7(1)，1994；作者稿标示 March，出版平台标示 May，版本固定用作者稿。阅读 §3–8。

**[文献]** 区分检索、复用、修订、保留，强调领域知识、适配与失败经验。**[限制]** 奠基框架不提供现代 LLM 的效果证明或通用最佳距离。**[设计推断]** 检索结果必须经过动作/资源/观察条件适配；保留失败和权衡，不只保存“好结果”；“找到了相似案例”只完成循环中的一环。

### E07 — few-shot 不等于权重训练

[Brown et al., Language Models are Few-Shot Learners](https://proceedings.neurips.cc/paper_files/paper/2020/file/1457c0d6bfcb4967418bfb8ac142f64a-Paper.pdf)，NeurIPS 2020。阅读 §2、§3、§5。

**[文献]** 在推理文本中放任务演示，模型权重不更新；不同任务效果差异大，并讨论污染与泛化问题。**[限制]** NLP 演示并非序列控制的最优策略训练。**[设计推断]** 案例库是外部持久化；本次检索注入是上下文学习；只有显式优化参数才是权重训练。论文必须用消融测案例是否改变选档及闭环效果，不能从有 few-shot 推导“学会正确档位”。

### E08 — RAG 的证据与边界

[Lewis et al., Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://papers.nips.cc/paper/2020/file/6b493230205f780e1bc26945df7481e5-Paper.pdf)，NeurIPS 2020。阅读 §2–4。

**[文献]** 神经检索器与生成器结合 Wikipedia 外部索引，在问答、事实核验和生成上评估；原方法含训练，测试 top-k 在开发数据上确定。**[限制]** 不证明任意相似度或案例 top-k 对控制有效，也不保证引用忠实。**[设计推断]** 采用来源可追溯的检索注入思想；本项目的冻结、确定性案例检索并非复现原 RAG 训练方法；top-k 与权重只在开发/验证选择。

### E09 — CoALA：区分信息性质

[Sumers et al., Cognitive Architectures for Language Agents](https://arxiv.org/html/2309.02427v3)，TMLR 2024，所读稿 2024-03-15。阅读 §4–7。

**[文献]** 将工作记忆、情景记忆、语义记忆、程序性记忆与内部/外部行动放在统一决策循环。工作记忆可由程序数据结构跨调用维护。**[限制]** 概念组织与案例分析，不是四种记忆都必须使用的实验定律。**[设计推断]** 当前公共输入及摘要是工作上下文，周级执行反馈是情景经验，有出处的机制条目是语义知识，校验/检索/模板规则是程序知识；不为“覆盖记忆类型”而让 LLM 自动改代码或规则。

### E10 — Generative Agents：可相信的叙述与控制效能不同

[Park et al., Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/html/2304.03442v2)，UIST 2023。阅读架构 §4、受控评估 §6、端到端评估 §7、讨论。

**[文献]** 经验流按新近性、重要性、相关性检索，反思生成更高层描述；25 个角色两天互动，消融考察行为可信度。**[限制]** 有记忆添饰与遗漏；指标并非疫情效用、因果正确性或可执行约束。**[设计推断]** 不采用 LLM 自评“重要性”作为病例真实性和选档质量的保证；可保留公开事件来源链，数值与时间摘要由程序生成。

### E11 — ReAct：外部反馈的作用

[Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/pdf/2210.03629)，ICLR 2023。阅读 §2–4、错误分析表2。

**[文献]** 交替生成推理、工具行动和观察；在问答、事实核验、ALFWorld/WebShop 评估。检索改善 grounding，但存在检索失败与重复行动；HotpotQA 未全面优于 CoT。**[限制]** 工具访问与可迭代环境是收益的重要条件。**[设计推断]** CEMAS 决策前允许的公共信息已固定，没必要增加自由工具探索；程序检索、程序核验提供外部依据，但不开放仿真未来试运行。

### E12 — Reflexion：反思依赖反馈质量

[Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning](https://papers.nips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf)，NeurIPS 2023。阅读 §3–5。

**[文献]** actor、evaluator、self-reflection 用轨迹与成功/失败反馈生成文本经验，通常只保留1–3条；评价包括游戏、问答、编码。**[限制]** 反馈来源/测试执行关键，存在局部最优与测试可靠性问题；不是通过梯度强化学习。**[设计推断]** “病例随后下降”不是同等级成功标签。默认无额外反思调用；可另测基于公共错误或确定性校验失败的有限修正，且不允许新增未经证实的因果规则。

### E13 — Voyager：可执行程序性记忆

[Wang et al., Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/html/2305.16291v2)，所读预印本版本 2023，首稿 2023-05-25。阅读 §2–4。

**[文献]** 自动课程、可执行代码技能库及环境/执行错误/自核验循环支持 Minecraft 探索和新世界迁移。**[限制]** 自核验也会误判，代码和任务存在幻觉，额外调用成本显著。**[设计推断]** 借鉴“经验复用须有可执行或可验证约束”；不让控制器产生干预代码，动作只能来自固定联合动作表；程序性规则由版本化代码管理。

### E14 — MemGPT：外部内存与上下文管理

[Packer et al., MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/html/2310.08560v2)，首稿 2023-10-12。阅读系统设计及会话/文档实验。

**[文献]** 通过层级内存、函数调用与上下文交换处理多会话聊天和长文档。**[限制]** 外部存储并未取消模型上下文容量或每次调用处理；不是疫情控制验证。**[设计推断]** 显式内存应与服务端会话、前缀缓存区分。每周从版本化公共记录重建上下文，能降低对隐含服务状态的依赖；性能与费用仍须按实际服务核验。

### E15 — A-Mem：自由记忆演化的得失

[Xu et al., A-Mem: Agentic Memory for LLM Agents](https://arxiv.org/html/2502.12110v11)，首稿 2025-02-17；所读固定版 v11，另有 [NeurIPS 2025 正文](https://papers.neurips.cc/paper_files/paper/2025/file/19909c36f51abc4856b4560aff3d36d6-Paper-Conference.pdf)。阅读 §3–4、§6。

**[文献]** 保存原内容/时间并由 LLM 产生标签、上下文、链接，进而更新旧条目；主要在 LoCoMo/DialSim 长会话问答评估。**[限制]** 组织质量受基础模型影响，改写后的语义不是独立事实。**[设计推断]** 不采用覆盖历史事实的自由改写；用不可变公共事实与显式 supersedes 修订链。学习型链接只作为可选研究分支。

### E16 — ReasoningBank：成功和失败均有价值

[Ouyang et al., ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory](https://arxiv.org/html/2509.25140v2)，首稿 2025-09-29；本次按 v2 预印本方法取证，另检索到 ICLR 2026 版本。阅读 §3–5、附录 E。

**[文献]** 自评成功/失败轨迹提炼 title/description/content，embedding top-k 检索并增量写入；MaTTS 通过更多轨迹提供对照，任务为网页与软件工程。**[限制]** judge 可误判，检索/合并较简单，未充分比较各种记忆结构。**[设计推断]** 借鉴同时保留失败与对照，拒绝把自评分当公共因果标签；CEMAS 应保存结构化事实与证据缺口，再验证是否需要 LLM 提炼。

### E17 — Self-RAG：不要把训练方法当作一段提示词

[Asai et al., Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://proceedings.iclr.cc/paper_files/paper/2024/file/25f7be9694d7b32d5cc670927b8091e1-Paper-Conference.pdf)，ICLR 2024。阅读 §3–4、附录实验。

**[文献]** 训练模型使用检索/相关性/支持度等特殊 reflection tokens，再以这些信号控制生成；在问答、核验和长回答上有收益。**[限制]** 不是黑盒模型加一句“请反思”就复现的方法，指标也不是控制效用。**[设计推断]** 借鉴“缺乏支持时不强行采用检索内容”；主方案以确定性适配门控和引用检查实现，不新增训练依赖。

### E22 — 经验相似可能导致错误模仿

[Xiong et al., How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior](https://aclanthology.org/2026.acl-long.27.pdf)，ACL 2026-07，pp.623–645。阅读 §3–5、Limitations、附录评价器设置。

**[文献]** 四类任务系统研究 addition/deletion；相似输入容易带来相似输出，全部写入可弱于固定记忆，可靠筛选更好。**[限制]** 严格评价器部分由真值模拟，研究主要限增删；可靠评价信号未必在线可得。**[设计推断]** 冻结案例事实并不意味着随机或低质量案例可用；质量审核必须区分数据有效与策略优越，避免只按文本相似排序和自动把在线测试结果升格为长期知识。

### E23 — 外部记忆仍可能遗忘和负迁移

[When Continual Learning Moves to Memory: A Study of Experience Reuse in LLM Agents](https://arxiv.org/html/2604.27003v1)，预印本，2026-04-29。阅读 §2–4、Limitations。

**[文献]** 在 ALFWorld/BabyAI 的任务 A→B 流中比较轨迹/抽象经验、粒度与检索频率；外部保存完好仍可因上下文竞争发生性能遗忘，难例尤其易负迁移。**[限制]** 两环境、各一个任务对、单一稀疏检索器、每条件两次运行，不能推成普遍定律。**[设计推断]** 需要反例/过时案例压力测试与每情景分组结果；本项目优先压缩可核查事实而非自由抽象的“政策教训”。

### E26 — MemMA：多角色记忆管理的正面证据

[Lin et al., MemMA: Coordinating the Memory Cycle through Multi-Agent Reasoning and In-Situ Self-Evolution](https://arxiv.org/html/2603.18718v2)，预印本，v2 2026-09-03。阅读 §3–5、§7。

**[文献]** Meta-Thinker、Memory Manager、Query Reasoner、Answer Agent 分工；合成 probe QA 在写入前寻找缺失与矛盾。主要 LoCoMo 实验，附加 LongMemEval-S 子集和 SWE-bench mini 结果。**[限制]** 依赖可从会话内容构造有答案的 probe、会话边界与额外调用；不能产生干预反事实标签。**[设计推断]** 这说明复杂非结构化记忆可能受益于分工；CEMAS 的字段/账本可确定计算，先以程序核验完成同类完整性检查，再测 LLM 分工的增量收益。

## 4. 核验、解释与单/多智能体证据

### E18 — CoT 可以合理化偏差

[Turpin et al., Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting](https://proceedings.neurips.cc/paper_files/paper/2023/file/ed3fea9033a80fea1376299fa7863f4a-Paper-Conference.pdf)，NeurIPS 2023。阅读实验、讨论及 Limitations。

**[文献]** 改变选项顺序等偏置可影响答案，而生成解释未披露这些影响。**[限制]** 实验可识别不忠实，不能证明通过检查的解释就完全忠实；模型与任务有时代边界。**[设计推断]** 决策记录应是公开证据、引用、动作和简短权衡的可核查承诺，不索取或公布完整内部思维链。干预证据/案例顺序的反事实测试只能提供行为忠实性迹象。

### E19 — ALCE：存在引用不等于引用支持

[Gao et al., Enabling Large Language Models to Generate Text with Citations](https://aclanthology.org/2023.emnlp-main.398.pdf)，EMNLP 2023。阅读 §3.3、§5–6、附录 E。

**[文献]** 将回答正确性与引用覆盖/引用相关性分开，使用 NLI 与人工评价；后补引用不一定获得良好支持。**[限制]** NLI 非真值，复杂联合证据或部分支持会被误判。**[设计推断]** 先查引用 ID、时间权限、数值复算、范围匹配，再独立人工或盲评文本蕴涵；引用检查通过只保证有限项目，不证明选档最优。

### E20 — 自我纠正的反馈与预算混杂

[Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/pdf/2310.01798)，ICLR 2024，所读稿 v2 2024-03-14。阅读 §3–7。

**[文献]** 在数学、常识、多跳问答等任务中，去掉外部正确性标签后自纠正常退化；同响应次数下辩论收益可能消失，初始提示不完整也会夸大二次纠正收益。**[限制]** 不涵盖所有新模型、外部工具反馈或风格修改。**[设计推断]** 主调用一次给全规则；只对确定的格式/引用错误作有限修正；审查器要证明超过等预算重采样/单体的净收益。

### E21 — 多智能体有收益，也会错误共识

[Du et al., Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/pdf/2305.14325)，ICML 2024（首稿 2023-05）。阅读 §2–5。

**[文献]** 多实例先独立回答后交换意见，在若干推理与事实任务改善结果。**[限制]** 原文明确额外生成成本、长辩论上下文困难，以及收敛到错误但自信的共识。**[设计推断]** 不把意见一致视为置信证据；如研究多角色，必须固定权限、冲突裁决、终止条件和总预算，并保留不采纳审查意见的规则。

### E24 — 等预算与任务结构决定多体价值

[Kim et al., Towards a Science of Scaling Agent Systems](https://arxiv.org/html/2512.08296v2)，预印本，v2 2025-12-17。阅读 §3–5 与实验附录。

**[文献]** 五种结构、三模型家族、四任务基准、180 配置，控制提示/工具/token；并行可分任务与顺序约束任务出现相反结果。**[限制]** 四个基准、有限结构，未逐模型优化提示；经验阈值不是跨任务定律。**[设计推断]** 本项目同一观察、单一联合动作、不需外部探索，优先统一上下文；不引用该论文数字预测 CEMAS 收益。

[Tran & Kiela, Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets](https://arxiv.org/html/2604.02460v1)，预印本，2026-04-02。阅读 §4–5、附录 C/G。

**[文献]** 对多跳 QA 比较五种多体方式与单体，揭示 API 声称思考预算与实际消耗不一致。**[限制]** 实验控制预算上限而非实际相同用量，只评文字 QA；理论依赖理想上下文使用，不能推出有限计算下单体普遍最优。**[设计推断]** 同时报告请求上限、实际输入/输出/可得 reasoning tokens、调用次数与时延；不可只用调用数替代成本配平。

### E27 — 长上下文的位置敏感

[Liu et al., Lost in the Middle: How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9.pdf)，TACL 2024，pp.157–173。阅读多文档 QA、key-value 检索与讨论。

**[文献]** 相关证据位置变化显著影响若干模型的检索/问答表现，中间位置常较弱。**[限制]** 不是所有新模型、所有文本任务的固定规律，也未比较 CEMAS 多轮 API。**[设计推断]** 控制 prompt 长度、把当前约束和关键公共数据固定放置；以顺序置换测试，不因上下文窗口足够大就传全量历史。

## 5. 关键问题的证据—取舍矩阵

下表是**设计推断**。引用给出采用的理由，不构成 CEMAS 能力证明。所有待验证效果进入验证方案。

| 关键问题 | 已有发现与支持证据 | 反证/限制 | 项目适配与采用结论 |
|---|---|---|---|
| 专家知识是否有用 | E03 的机制说明有价值；E09 区分知识性质 | E04/E25 也已有知识与记忆；现实机制不提供任务最优阈值 | 固定版本知识条目；明确来源、前提、可见字段与适用维度；禁止“官方建议=本仿真最优政策” |
| 短期记忆用什么形式 | E01/E02 说明延迟和行动依赖观察；E09 支持结构化工作记忆 | E10 的自然语言反思会添饰；长上下文未必可用 E27 | 保留最近若干周的公共数值、执行档位、持续天数、资源与缺失标记，程序计算趋势 |
| 长期案例的作用 | E06/E07/E08 支持演示和适配；E16 支持保留失败 | E22/E23 与 E04 显示相似经验也可有害 | 用案例比较情景、适用条件、执行动作和随后反馈；不把其作为最优动作标签或因果效应 |
| 选 top-k 的依据 | 原 RAG 在开发集选择 k；记忆需控制输入规模 | 固定 k、纯 cosine 没有任务最优性保证 | 硬兼容筛选后按公共状态距离与多样性排序；阈值、k、权重仅在开发/验证调整 |
| 是否自动生成经验 | E12/E16/E25 有反馈学习的正面结果 | 其正确性反馈或预测标签不同于 CEMAS 行动后变化 | 默认程序组装事实案例；延迟成熟与来源链必须确定；不新增反思调用 |
| 是否需要模型审查器 | E21/E26 显示审查与分工可能有价值 | E18/E20 指出合理化、自纠正失效；额外预算混杂 | 主流程程序核验；模型审查只作为等预算研究分支，不能拥有执行权 |
| 单体还是多体 | E24 支持按任务结构选择；E05 多体解决真实区域外部性 | 有正面多体证据，不能证明单体一定更优 | 选一个决策器；检测/教学/资源角色只是同一优化问题的维度，先避免额外通信 |
| 多轮还是独立请求 | E09/E14 支持显式内存；E27 提示上下文增长风险 | 未有本任务的直接优劣实验 | 每周重建独立请求，外部显式记忆跨周；服务端状态/缓存只作可选传输优化 |
| 解释如何可信 | E19 可查支持度；E18 指出解释并非透明思维 | 数值/ID合法不保证文本蕴涵；蕴涵不保证因果或动作质量 | 同时检验事实、引用、时间边界、适用条件及动作一致性，人工审查抽样并报告错误 |
| 是否学习世界模型 | E04 正面展示 action-conditioned rollout | 需要数据/训练/反事实校准，改变控制器信息工具和公平性 | 主方案不引入；如另立研究分支，统一预算/工具权限并在独立环境评估 |

## 6. 对论文定位的直接影响

**不能作为主要创新主张：** 把 LLM 用于每周疫情政策；专家知识+记忆；RAG/few-shot 案例；短期/长期双库；反思；多智能体辩论；协议工具+经验三层结构。这些分别已由 E03–E05、E06–E17、E25–E26 覆盖。

**可实施、但必须实证的方向：** 面向行动影响观测、结果延迟和资源约束的公共证据案例选择；把“相似”与“可迁移”明确分开；保持案例是关联观察，构建拒绝无依据因果归因的可核验决策记录；在统一接口和预算下检验这些机制是否改善健康—负担权衡及错误恢复。工程接口、公私隔离和日志完善本身主要是可信实验基础，不自动构成方法创新。

最近邻比较应单列 E03 每周政策记忆、E04 世界模型/技能经验、E05 多辖区协调、E25 延迟标签预测。推荐主方案的差别是研究假设，不是已经成立的优越性：没有反事实工具、无私有奖励反馈、同一 324 动作和公共观察、程序事实记忆、可拒绝/降级的案例使用。必须用无案例、随机/相似度案例、匹配检索、错误/冲突案例、无 LLM 选择器及等预算审查/多体等对照证明增量价值。

## 7. 保留的未知与最小判定方法

| 未知 | 原因和影响 | 当前默认 | 后续最小验证 |
|---|---|---|---|
| 案例能否帮助正确选档 | 现有论文多为问答/预测/不同仿真，不能迁移效果量 | 结构化案例是证据，允许不采纳 | 相同病例库、相同 token 上限下比较无案例/随机/相似度/兼容多样性检索，评估闭环指标 |
| 27世界×4策略是否覆盖足够 | 世界数不等于有效行动/资源/趋势支持 | 视为候选起点，先做公共特征和实际执行动作覆盖审计 | 报告空区域、同一策略重复率、各档位和资源紧约束覆盖；仅在开发集补缺 |
| 自然语言反思是否值得 | 没有动作因果标签，反思可能放大错误 | 关闭自动反思 | 先固定事实，再比较程序摘要与等预算、受证据约束反思；测事实错误、伪因果与闭环效用 |
| 短期窗口、k和距离 | 文献给原理但未给任务最优参数 | 使用架构文档规定的有限默认值 | 开发选择、验证冻结；测试不调参；记录每次检索及无匹配率 |
| 审查器/多体净收益 | 额外调用可能仅增加计算，且产生共识错误 | 关闭 | 同模型、同证据、同预算对照单次加长、两次独立采样、受限审查与分工角色 |
| 引用检查能保证什么 | ID/数值可精确检查，语义/因果无法完全程序判定 | 明确分层状态，失败不当作成功 | 合成错误注入、盲评、分歧仲裁；报告检查漏检/误检，避免只报通过率 |
| 可用上下文与真实成本 | 模型/服务能力会漂移，缓存不等于语义记忆 | 每周显式请求，缓存不参与正确性 | 真实 API 门禁单独核验 tokenizer、请求内容、重试隔离、usage 和缓存命中；本次未执行 |


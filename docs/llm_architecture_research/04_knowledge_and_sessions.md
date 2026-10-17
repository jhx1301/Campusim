# 专家知识、服务能力与会话决策

日期：2026-10-17。下列外部结论来自当天读取的官方页面；条目内容为概括，部署前须保存实际版本与内容hash。没有调用模型服务验证账户/端点能力。

## 1. 公共卫生证据及适配结论

| ID、来源与版本 | 已读范围、发现 | 限制及本项目采用结论 |
|---|---|---|
| H01 [WHO PHSM interim guidance](https://www.who.int/publications/i/item/considerations-in-adjusting-public-health-and-social-measures-in-the-context-of-COVID-19-interim-guidance)，2023-03-30，2023.1；2023-04-18 corrigenda | 官方Overview及previous versions：按本地情势定期复核措施；2023版移除按传播数值cut-off分级，重心转向发病/死亡和医疗影响 | 链接标题的搜索摘要曾显示2021，实页已是2023。下载PDF失败，未把未读表格当证据。CEMAS没有医疗负荷观察、无疫苗/再感染；只能迁移“结合适用条件与负担复核”的原则，不能移植WHO情势等级或阈值。 |
| H02 [CDC MMWR校园暴发报告](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)，2021-01-29，70(4):118–122 | 已读Preparations、Outbreak/Response、Screening、Discussion：检测、追踪、处置与活动调整并行，资源随响应扩充，观察依赖检测/报告 | 描述性单校多措施同时实施，没有分离单项因果效应；自报与外部检测存在漏报/延迟。只支持组合/资源/交付语义的知识卡；不推出E2必需、两周保持期或某S档最优。真实12,000学生不等于合成12,000总人口。 |
| H03 [UKHSA data quality report](https://www.gov.uk/government/publications/sources-of-surveillance-data-for-influenza-covid-19-and-other-respiratory-viruses/data-quality-report-national-flu-and-covid-19-surveillance-report)，2026-06-04更新 | 已读Laboratory surveillance、USD、strengths/limitations与数据质量：检测政策、样本来源和报告系统改变影响病例/positivity的可比性 | 其PCR样本阳性率定义与CEMAS按交付日诊断/当周检测之比不同。采用“测量过程变化可能混淆趋势”的警示，不直接称CEMAS proxy为阳性率或估计感染。 |
| H04 [WHO lives and livelihoods framework](https://www.who.int/publications/i/item/9789240017948)，2020 | 官方Overview：措施涉及不同人群、时点的健康与经济影响及不确定性 | 仅作知识选题与背景，不据此修改合成目标的四项权重；未深读全文，不承担关键数值结论。 |

现实建议、任务规则、源域经验分别放三类对象，不能合并成一个“医学真理”检索库。任务规则对合成任务具有规范效力；现实证据只限定可作的解释；源域公共经验只有描述性关联。发生冲突时先判断是否不同场景/定义/版本；不投票混合。确实冲突且同适用范围，保留双方ID和冲突码，禁止自动生成折中阈值。

## 2. 知识生产与冻结

1. 人工搜集官方原文/研究方法与限制，记录publisher/title/url/issued_on/retrieved_on/section；未知发布日期填null，不能用抓取日期代替。
2. 双人或人工复核来源与项目映射。筛除依赖住院、疫苗、口罩、个体风险等当前不存在的观察/动作的操作建议。保留排除理由。
3. 一条卡片仅表达一个规则或限定。原文为证据，程序字段为使用边界；不让运行时LLM重写官方知识。
4. 发布 `knowledge_bundle`：版本、每条canonical JSON SHA-256、来源登记、reviewed状态；私有构建记录保存来源存档hash（本次未下载全文）。公共卡片不含账户、世界或测试信息。
5. 同一批实验固定bundle；网站变化不自动更新运行中prompt。新版本重新做源域回归与独立验证，测试后不回填旧实验。
6. 每周程序按下列trigger注入规则；同ID按版本唯一。`conflict_group`仅为主题，不表示冲突；bundle另有人工审核的`conflict_pairs:[{left_id,right_id,note}]`（初始为空）。同适用范围的矛盾外部建议不进入默认决策bundle，保留在研究登记候选集，待人工裁定；运行时遇到非空未解决conflict_pairs直接阻止bundle加载。这样无需给现行八项输出枚举增加未定义的knowledge_conflict。任务事实与外部操作建议冲突时以合成任务为准，卡片只保留适用性警示。超过预算按优先级删可选卡片，永远保留任务语义与限制。

KnowledgeCard字段（全部必需；nullable处显式null）：

```text
id: str, version: str, kind: simulation_rule|real_guideline|research_finding
source: {publisher:str,title:str,url:str,issued_on:str|null,revision:str|null,
         retrieved_on:YYYY-MM-DD,section:str,evidence_type:str}
statement: str[1..300], preconditions: str[], limitations: str[]
public_fields: str[], action_dimensions: (T|S|C|E|A)[]
trigger: always|has_history|testing_changed|capacity_changed|case_conflict
priority: int[0..9], conflict_group: str|null
supersedes: str[], review_status: reviewed|candidate|excluded
```

来源/知识ID是输入依据，不是提示词指令。只允许`reviewed`卡进入实验；本次reviewed表示本研究已核读并映射，不代表未来发布bundle的人类双审或效果验收已完成。外部卡的preconditions必须限定为“合成任务中的解释性警示可迁移”，不授权执行现实政策；若操作建议需要医院/疫苗等不存在字段则排除。附带“请忽略规则”等来源字符串必须按资料处理，不能改变system权限。引用URL只供追溯；控制器不开浏览器。

## 3. 代表性知识条目与六条规则的处理

以下是可实施的初始bundle，完整对象和来源在 [knowledge_cards.json](examples/knowledge_cards.json)。`SIM-*`为现有公共任务规则的重述，外部来源只支持解释限制，不能取代协议。

| 卡片 | 具体表达 | 注入/映射/不适用边界 |
|---|---|---|
| SIM-01（保留原1） | 诊断/通知按交付日计；后续下降不能证明感染下降或动作因果作用。 | always；history/feedback；T/S/C及全部动作归因。不添加未知延迟分布。 |
| SIM-02（保留原2） | 联合有效周、实际检测通知、执行动作及持续天数读趋势；无效周不是稳定。 | always；history/week_valid/durations；全部维度。 |
| SIM-03（保留原3） | D/Tests是错位代理，0分母无效，也可能大于1；检测变化时不能仅按D排序。 | always；proxy/testing；T/S。H03提供测量警示，公式由任务规定。 |
| SIM-04（保留原4） | 按共同有限时域目标权衡四类公共负担，真实感染项仍未知；不预设某档最优。 | always；public cost/目标；全部维度；不把现实经济损失赋给ActivityDays。 |
| SIM-05（保留原5） | mask只约束S；T/C较高概率不增加外部容量，不保证执行量。 | always；resources/mask；T/S/C；无公开unmet时不声称需求饱和。 |
| SIM-06（保留原6） | 每周自由调整；无共同保持期/切换罚项，保持或换档均须依据当前证据。 | always；action/durations；全部；策略可自愿保持，但不能宣布新硬限制。 |
| PH-01 | 同时使用多项措施的校园报告不能识别每一档的独立效应；执行依赖资源。 | has_history；H02；T/S/C/E/A；不复制现实两周停课期。 |
| PH-02 | 检测政策/样本构成改变影响观测可比性，应同时看检测量与有效标记。 | testing_changed；H03；T/S；不移植医院样本阳性率。 |
| PH-03 | 公共卫生措施需结合当地情况与负担复核；WHO2023情势指标不直接映射本任务。 | always、低优先级；H01；E/A和权衡；无医疗负荷/死亡输入，不采用WHO分级。 |

`testing_changed`的确定定义：相邻有效完整周`abs(tests2-tests1)/max(tests1,1)>0.25`；仅为提醒阈值/待验证设计假设，不是升降档阈值。`capacity_changed`比较当前resources与最近有效周；`has_history`至少一有效周；`case_conflict`来自02章定义。初始外部卡最多3条，核心六条始终在system。无记忆与有记忆模式使用相同知识，专家消融单独删除PH卡；若消融六条须注明改变认识约束/任务提示，不能混称单纯知识增益。

原六条价值是防止语义错误，缺口是来源/适用性追踪、延迟跨窗口记录、具体案例差异、引用校验。补齐这些工程机制比堆叠长篇指南更直接。它们没有提供最优控制阈值；仍需实验决定哪种记忆改善选档。

## 4. 实际服务与能力边界

| 来源（2026-10-17读取） | 可确认 | 不能据此确认 |
|---|---|---|
| [DeepSeek multi-round](https://api-docs.deepseek.com/guides/multi_round_chat/) | 当前`/chat/completions`无状态；客户端逐次传历史；示例使用deepseek-flash | API不会永久记住前周；本地实际账户、路由/指纹、tokenizer未验收 |
| [DeepSeek cache](https://api-docs.deepseek.com/guides/kv_cache/) | 自动缓存匹配前缀，best-effort；usage有hit/miss；缓存会清除 | 命中不是必然，不减少语义上下文长度，不保证输出相同 |
| [DeepSeek 2026-09-10 release](https://api-docs.deepseek.com/news/news260910/)、[model listing](https://api-docs.deepseek.com/api/list-models/) | 官方存在V4.1-Flash及模型列表文档；与项目所写家族可对应 | 未查询真实认证模型列表；不能宣称生产端点返回版本已固定 |
| [Qwen multi-turn](https://www.alibabacloud.com/help/en/model-studio/multi-round-conversation)，2026-10-11更新 | Chat Completion/DashScope需显式传历史；历史增长需截断、摘要或检索 | 不等于Response式服务端状态；不能自动继承跨回合历史 |
| [Qwen3.5-plus模型页](https://www.alibabacloud.com/help/en/model-studio/qwen3-5-plus) | 官方列出2026-02-15快照及1,000,000 context、65,536 output | 公开最大长度不代替本项目本地计数/请求参数/服务usage验收 |
| [Qwen cache](https://www.alibabacloud.com/help/en/model-studio/context-cache) | 显式/隐式缓存与会话历史是不同功能，支持范围依模型/地区；隐式缓存不保证命中 | 本次未在支持名单中确认特定02-15快照的全部地区缓存能力；不能以qwen3.5-plus别名支持推断快照支持 |

DeepSeek部分pricing/thinking/Responses链接抓取失败；找到了官方release、model-list、multi-round和cache替代页面。Qwen当前文档指向Responses服务，但本项目transport只使用Chat Completions；本设计不依赖任何服务端状态，故无需猜测其保存期限/恢复能力。未来切换API必须另立能力矩阵与验收，不把服务端保存等同模型权重训练。

## 5. 会话方案的明确选择

| 方案 | 近期变化、状态与重放 | 代价/错误/公平性 | 决定 |
|---|---|---|---|
| 独立请求＋显式公共记忆 | 每次完整公共观察、程序摘要、冻结案例，hash可独立重放 | 当前观察重复传输但有固定上限；不会继承错误assistant结论 | **主方案** |
| 累积历史消息 | 保留语言连续性 | 输入大致按回合累计，总输入可二次增长；过去错误持续进入；污染隔离难 | 对照实验；不默认 |
| 滑窗对话/LLM摘要 | 长度可控 | 截断丢失，摘要可能错；额外调用预算；原始事实需要保留 | 程序摘要足够时无必要 |
| 服务端会话状态 | 可减少客户端存储传输 | 需验证存储语义、版本、TTL、fork、重试与导出；不保证少计token | 当前transport不使用 |
| 前缀缓存 | 相同system有机会重用计算 | 只是实现优化；记录hit/miss与实际usage，不以命中假设算收益 | 可被动使用，不成为正确性依赖 |

每周消息生命周期：`reset清pending/近期状态 -> decide(d)从公共输入组装system+user -> hash和计数 -> 同字节重试至多3次 -> 返回提案并保留待配对公共状态 -> observe([d,e])闭合案例 -> 丢弃本轮消息的控制用途 -> 下周重建`。assistant响应不会自动附入下周；终点只observe，不产生H日新请求。E4将来fork必须克隆公共pending/近期状态/检索版本和本地随机状态，不能共用可变会话。

请求成本记录`uncached_input,cached_input,output/reasoning,attempts,wall_ms,cache_mode,price_snapshot`；货币成本按同日同地区官方价格逐attempt计算，缺价格/usage填unknown，不估算成实测。比较多智能体须同时报总token和串行/并行延迟；公开上限不是实际消耗。

## 6. 本分支检索记录与停止判断

范围：WHO/CDC/GOV.UK原始指南与报告；DeepSeek/Alibaba服务文档；Springer/IFAAMAS/CCF正式渠道。关键词包括`PHSM adjusting measures`、`campus outbreak MMWR`、`testing policy positivity data quality`、`multi-round stateless`、`context cache snapshot`。

第一轮找出WHO旧摘要与当前版本差异、CDC多措施混淆，确定“不把指南变阈值”。补查1读UKHSA测量定义，补查2查报告延迟/筛查频率原始研究：Larremore Science PDF访问失败，仅有检索摘要，未用于定量或核心设计结论；没有改变采用判断。服务补查1确认stateless/cache区别；补查2查确切快照/地区支持，增加Qwen缓存不确定性，但不改变独立请求主方案。以上是有限、按问题停止的检索，不宣称穷尽2026文献。

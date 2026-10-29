# LLM反馈与持续规则记忆：统一设计

更新：2026-10-28。本文是新版唯一机制合同；[PLAN](PLAN%20(1).md)给出实施顺序与验收，[人工样例](llm_feedback_component_examples.json)给出设计输入输出。旧的嵌套案例窗口和逐事实规则证据协议已弃用，不提供迁移。

## 1. 数据流与任务

```text
历史快照 → 7天共同观察 → 112天自主控制
每周：公开观察 → 动作 → 真实执行周 → 独立案例 → 下一决策前周经验
每四自主周：前置参考周＋四自主周 → LLM规则判断 → 事务更新规则库
决策：公开状态＋固定知识＋近期摘要＋检索案例＋临时经验＋检索规则
训练结束：一致冻结学习库 → 独立只读评估
```

模型参数固定，学习来自跨回合累积的案例和规则。主配置both/llm/adaptive。LLM沿用与既有RL baseline相同的种子、快照、未来分支和资源场景。隐藏感染、私有reward、传播参数、seed、未来事件和完整审计不进入模型输入。

相对快照恢复点：day0–6观察，day7首次自主决策，day112末次自主决策，day119结束。每完成四个自主周在day35/63/91/119整理规则。观察期不生成算法案例。评分只汇总day7–118，归一化112天；119天完整账和控制账分别保留。时限结束仍执行终局整理，PPO/DDQN保留时间截断bootstrap。

## 2. 单周案例与统一周序列

`PublicEpisodeMemory.stage()`保存决策前公开观察，`accept()`在该真实周交付后立即产生一个闭合案例。案例使用`executed_week`；保留ID、revision、公开前态、状态、flags、描述及完整性元数据。分组通过学习库的`group_for()`查询。删除followup字段、等待接续周状态和一周后补r2的机制。revision表示同一执行周的记录版本，不表示结果成熟度。

`project_week_sequence()`是反馈和规则整理的唯一周序列投影。每条包含window_id、分组、case_id/revision、起止日、reference/autonomous角色、公开values及是否可计数。以分组和真实起止日去重。

- 周反馈：前一完整参考周＋当前自主周。
- 四周规则整理：前置参考周＋四个完整自主周。
- day35参考day0–6，整理day7–34；day63参考day28–34，整理day35–62。
- day119参考day84–90，整理day91–118；没有等待额外执行周的需求。

周记录只出现一次。比较只给相邻周差值及动作/容量/检测变化限制，不内嵌源事实对象。它是前后描述，不能当作反事实对照或动作的因果效果。

公开周字段复用`week_values()`。快照负日期历史继续保留；未知动作、容量、检测分项和负担为null，不当成零。参考周用于解释变化，永不计入规则支持/相悖次数。

## 3. 周经验与控制器生命周期

`FeedbackBackend.generate(packet)`接收`cemas-public-feedback-input-v3`。packet包含as_of_day、公开任务hash、weeks、comparisons、facts和固定知识。facts只为本次临时经验和动作审计提供引用，不进入规则存储。

响应为`cemas-public-feedback-result-v2`，每个自主window_id恰好一项：候选给finding、decision_check、applicability、limitations；只有前两者各含text/evidence_ids，applicability直接是字符串，limitations是1–3个字符串。也可用insufficient_evidence、no_new_insight或redundant_with_packet弃答。提示词给出两种最小JSON示例并要求逐字复制facts中的完整引用；例如通知字段是`W:…:cost.delivered_notifications`，不能省略`cost.`。

完整结构与引用检查通过才使用笔记；笔记只在本回合保存，最多展示两条近期项。未发送事实、经验和规则不能被动作响应引用。周经验是建议，不是原始观察或因果证明。

`reset()`清临时状态，不清学习库；`observe()`只保存公开周和待处理项；`decide()`预检后生成经验、执行到期规则整理、检索并请求动作；`finish_episode()`处理day119终局规则整理，不生成没有本回合消费者的额外周笔记。runner通过`drain_feedback_events()`在finally中落盘辅助审计。

## 4. 规则内容、判断与版本

`RuleDistiller.propose(evidence_bundle,current_rule_set)`复用现有请求基础设施。bundle为`cemas-public-rule-input-v3`，包含平铺五周、相邻比较、condition_catalog和固定知识；current_rule_set单独提供全部当前规则。请求不复制历史事实证据，也不维护另一份规则注册表。

每个自主周附`pre_decision_action`和`matched_condition_ids`，前者直接投影案例前态的current_action，后者由同一适用条件入口依据该周行动前公开状态生成；不重复发送整份历史观察。动作条件`kind=action`始终指决策前已在执行的动作，本周实际动作另见`values.executed_action`。例如决策前A=2、本周改为A=1，该周匹配的行动前动作条件仍是A=2；不能将本周选择的A=1替代它。所选全部条件都须适用于支持/相悖窗口，模型可对照该窗口的matched_condition_ids核对；不适用用ignore。

规则内容只有condition_ids、lesson、limitations；程序把所选条件定义随规则保存。规则另存任务身份、ID、内容版本、状态、更新时间和聚合统计。不保存逐条evidence、支持/相悖事实引用或removed_evidence，也不执行旧的规则来源失效检查。

`cemas-public-rule-patch-v3`只有schema_version和operations：

| 操作 | 完整字段 |
|---|---|
| ADD | op、content、increment、judgments |
| REVISE | op、target_id、base_version、content、increment、judgments |
| SUSPEND | op、target_id、base_version、reason |

content中的条件从本次condition_catalog选择；lesson、limitations中的文字、increment和reason均为非空单行字符串，limitations保留1–3条。仅在提示词建议lesson约180字、其余每项约120字以内，必要时可稍长；程序不按字符数拒绝、截断或改写。动作reason保留现有reason_max_chars配置和解析参数用于兼容及提示长度建议，tradeoff建议约80字；它们也不再是字符数接纳门禁。ActionProposal内部同步取消120字符限制，JSON结构、类型、引用、单行及非空约束保留。

judgments每项只含window_id和support/contradict/ignore。LLM判断在规则条件内，公开记录与lesson是否一致；不适用或不够判断用ignore。程序检查发送窗口、完整自主周、版本和重复，并拒绝条件明确不匹配的支持或相悖判断；ADD至少一个支持窗口。参考周仅供比较，完全不能出现在judgments中，包括ignore。提示词分别给出ADD/REVISE/SUSPEND和空operations的最小JSON示例，示例不构成第二份可执行schema。操作数量无固定上限，同一目标一批最多一次，整批解析成功才写入。

统计采用唯一窗口判断：

```text
support_count = support窗口数
contradiction_count = contradict窗口数
confidence = (support_count + 1) / (support_count + contradiction_count + 2)
```

ignore不计入分母；相同窗口重送不累加，改判替换旧判断。置信度仅为案例一致度，不是规则为真概率，不触发自动删除阈值。非暂停规则至少有两个不同完整自主周支持时成为active，否则为candidate。

统计更新、状态暂停不升内容版本。只有lesson、条件或限制改变才创建新版本；新版本不继承旧判断统计，只从显式提交的新判断开始。旧内容版本和旧统计保留。内容不变的REVISE用于累积新判断。

## 5. 持久化与检索

`LearningMemoryStore`使用`cemas-learning-memory-v2`，单连接、每回合一个事务。保存案例、规则版本、回合映射、完成记录及rule_updates。v1学习库明确拒绝并提示新建v2，不迁移、不覆写旧库。

rule_updates只包含rule_id、rule_version、opaque_group、case_id、case_revision、window_start、window_end、judgment；唯一键是规则内容版本＋分组＋起止日。它不保存案例正文。规则聚合统计由该表计算；解析无副作用，写入规则和判断在同一事务内完成。

案例检索沿用现有公开特征、NumericRetriever及同组至多一条限制，库容量不限。规则先排除暂停、任务不符、明确不适用及支持少于两个完整自主周的项。通过当前版本支持判断找到案例前态，复用build_case_query/query_similarity；matched优先，再按最高有效相似度降序、规则ID升序，最多六条。六条只是展示上限。

动作模型收到简洁规则内容、条件、限制、支持/相悖次数、置信度和适用状态。置信度不替代状态相似度，不改变合法动作或固定任务约束。

## 6. 训练恢复、冻结与请求

显式episode_id绑定具体快照、未来分支、资源和时域，不绑定列表位置。同ID同场景已完成则跳过；同ID改场景报冲突；有意重复用新ID。允许追加、重排、更换模型/模板/检索配置，实际配置写日志，不作强制恢复门禁。

案例、规则、判断和完成记录整回合提交，致命失败整回合回滚。完成表是唯一进度，不逐周恢复。冻结在完成边界用SQLite backup生成一致副本和hash manifest。正式评估只读，经历不写库；临时周经验随回合清空。

动作、周经验和规则共用transport、服务设置、官方tokenizer、bounded_request和审计。没有辅助小token预算、规则块上限或token裁剪；完整输入超服务配置硬上限时报错，输出截断不部分提交。每次请求仍至多三次、间隔2/4秒。连接/临时服务错误原样重发当前请求；响应校验失败改为原始完整输入加一条user纠错消息，要求重新返回完整JSON。

2026-10-29起，DeepSeek保持thinking/high，总生成上限max_output_tokens为131072，包含推理和最终回答；输入上限仍为131072。Qwen的secondary_max_output_tokens保持65536。正常完成立即返回，限额不是生成目标；三类请求复用同一供应商设置，不另设推理预算。

纠错只保留最近一次错误码、字段路径、要求及必要错误值，不发送完整旧答复或累积错误历史。原有校验点通过异常details提供首个错误，规则错误附操作位置、窗口和未满足条件；不新增错误码文案注册表。仅发送公开校验信息，SDK原始异常、凭证、私有信息和内部推理不进入纠错。错误编号不会因为出现于纠错中而进入合法引用registry。

纠错消息变化后重新计算完整官方输入token及实际消息hash；服务重试复用当前消息和计数。纠错后超输入上限时记录预检失败而不调用服务，不截断纠错或公共上下文。重试不重新检索、不生成额外周经验或规则请求、不重复stage。快照动作耗尽仍停止回合并回滚，辅助请求耗尽记为unavailable，正常空操作或弃答不视为失败。

llm_calls只计动作调用，feedback_events的provider_call计辅助调用；attempts、auxiliary_attempts、total_attempts分别报出。token、耗时及已有费用来源包含全部请求。每次调用审计保存实际消息、hash、输入计数及可选validation_error；动作成功收尾在当前调用审计追加后执行，最终决策证据引用最后一次实际请求的messages_sha256/input_tokens。纠错不增加事实，原公共context_hash和引用registry不变。提示词版本/hash升级，响应schema、条件ID和学习库schema不变，已有v2库可继续使用。

独立服务验收工具沿用同一纠错流程。生成报告的最终检查只核对记录完整性和一致性，不重复解析已通过的响应或复算输入；独立读取报告时仍完整验证，重建原始上下文并计数包含可选纠错消息的实际请求。

## 7. 入口与验收边界

使用`python -m examples.control_v1.learn_memory`的train/freeze/evaluate。train接收显式episodes、settings、library、output和校准artifact；freeze输出数据库及manifest；evaluate只读冻结库并支持val/test。指定解释器为`D:/programfile/miniconda3/envs/simulation/python.exe`。

验收覆盖单周案例、五周去重、终局无followup、判断幂等及改判、版本与公式、整批拒绝、六条检索、回合回滚、v1拒绝和冻结只读；继续验证119日/17窗/16决策及评分不回归。人工样例和离线transport测试不证明真实服务或控制收益。本次实现不自动启动长训练或付费调用。

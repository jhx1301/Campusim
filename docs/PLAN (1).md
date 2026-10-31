# 新版 Feedback 实施与验收合同

更新：2026-10-30。机制以[统一设计](llm_feedback_component_design.md)为准；[人工样例](llm_feedback_component_examples.json)只说明协议，不是实验结果。

## 1. 任务与时间

主配置为 `memory_mode=both`、`feedback_backend=llm`、`rule_memory=adaptive`。沿用历史快照任务：恢复后先共同执行7天基线，再自主控制112天，总119天、17个执行窗口、16次自主决策。LLM使用与既有RL baseline相同的种子、快照、未来分支和资源场景。

| 事件 | 相对恢复点时间 |
|---|---|
| 共同观察 | day0–6 |
| 第一个自主执行周 | day7–13 |
| 首条周经验 | day14 |
| 规则整理 | day35、63、91、119 |
| 最后自主执行周 | day112–118 |

观察周只作公开历史和参考周，不形成算法案例或规则支持窗口。保留快照负日期历史与未知字段的`null`语义。主评分只汇总day7–118，负担按112天归一化；完整119天与控制期分别对账。正常时限结束调用`finish_episode()`，RL维持时间截断bootstrap。140/168天延展仍指自主控制长度。

## 2. 单周案例与平铺输入

每个自主执行周交付后形成一个独立案例，保存决策前公开观察、`executed_week`、状态、描述和revision；回合分组由学习库映射管理。删除followup字段和等待下一周补齐案例的状态机，不再用revision表示追加接续窗。共同观察周不建算法案例。

唯一入口`project_week_sequence()`生成平铺周序列，复用公开周字段投影。周反馈使用“前一完整参考周＋当前自主周”；四周整理使用“前置参考周＋四个自主周”。同一`(opaque_group,start_day,end_day)`只出现一次。比较仅记录相邻周的公开数值差和限制，不内嵌源事实正文，不作因果归因。

例如day63输入day28–34作为参考，再加day35–41、42–48、49–55、56–62。day119输入day84–90加day91–118，不需要额外后续周。参考周不能参与规则统计。

周反馈输入为`cemas-public-feedback-input-v4`，结果为`cemas-public-feedback-result-v2`，按`window_id`关联。发送时保留weeks.values并提供由内部facts派生的reference_fields，不再发送重复facts对象。引用仍用window_id加冒号和字段名，包含完整cost.路径；临时笔记可引用这些已发送事实，但不复制进持久规则。下一次决策前生成经验，允许弃答，决策最多展示两条近期笔记。

## 3. 聚合规则与轻量判断记录

规则内容只含`condition_ids/lesson/limitations`；规则记录另有ID、内容版本、条件定义、任务身份、状态、支持次数、相悖次数、置信度和更新时间。删除规则逐条evidence、支持/相悖事实ID、removed_evidence及来源失效机制。

`RuleDistiller.propose(bundle,current_rule_set)`内部收到平铺周序列、固定知识、条件目录和全部当前规则；不补传历史规则证据正文，不分批。内部bundle为`cemas-public-rule-input-v3`，实际发送投影见第6节；输出仍为`cemas-public-rule-patch-v3`并保留schema_version。

| 操作 | 字段 |
|---|---|
| ADD | op、content、increment、judgments |
| REVISE | op、target_id、base_version、content、increment、judgments |
| SUSPEND | op、target_id、base_version、reason |

每个judgment只有`window_id`和`support/contradict/ignore`。LLM判断语义；条件不适用或不能判断用ignore。程序检查发送窗口、完整自主周、版本和同批重复，不自动推断干预收益。ADD至少有一个支持窗口，操作数量无固定上限，空operations合法，一项非法则整批拒绝。

```text
support_count = 当前版本不同窗口的support数量
contradiction_count = 当前版本不同窗口的contradict数量
confidence = (support_count + 1) / (support_count + contradiction_count + 2)
```

置信度仅表示案例一致度，不是规则为真的概率。统计更新和暂停不升内容版本；内容、条件或限制改变才创建新版本。新版本不继承旧统计，从本次明确提供的判断开始计算；旧版本和统计保留。ignore不计入分母；已有窗口改判时替换原判断，不再加一次。

`rule_updates`只存rule_id、rule_version、opaque_group、case_id、case_revision、window_start、window_end、judgment。唯一键为规则版本＋回合分组＋真实窗口。它是判断计数及检索来源，不保存案例或事实正文。规则解析无副作用，学习库在同一事务中写规则和判断，再生成聚合统计。非暂停规则在两个不同完整自主周支持后成为active，否则为candidate。

检索排除暂停、任务不符、条件不匹配及支持少于两个完整自主周的规则；从支持判断找到案例前态，复用既有公开特征和`query_similarity()`。matched优先，再按最高有效相似度和规则ID排序，每次最多六条；规则库总量不限。动作输入只展示规则内容、条件、限制和聚合统计。

## 4. 学习库、请求和恢复

学习库为`cemas-learning-memory-v2`。旧v1库明确拒绝，提示新建v2库；不迁移、不静默解释旧规则，不改旧文件。案例、规则、判断、回合映射和完成记录使用同一SQLite连接及回合事务。reset只清临时状态。

训练使用显式episode_id；同ID同场景完成则跳过，同ID换场景报冲突。重排、追加、模型/模板/检索配置变化可继续训练，实际配置记日志。完成记录是唯一进度来源。失败回合整体回滚；不做逐周恢复。冻结在已提交回合边界使用一致数据库副本及manifest，正式评估只读，临时经验仍可在回合内产生。

复用已有transport、官方tokenizer、重试、usage和审计。不另设辅助小预算，不按token删除周记录、规则或知识；超过服务配置硬上限明确报错，截断响应不接纳部分结果。快照非法主动作进入已有三次请求流程，耗尽后停止回合并回滚训练事务。

2026-10-29限额调整：DeepSeek保持thinking/high，总生成上限max_output_tokens提高到131072，动作、周反馈和规则维护共同使用；Qwen通过secondary_max_output_tokens保留65536。输入上限仍为131072。不限制推理与回答各自的份额，截断检测及纠错重试保持。

取消所有说明文字的硬字符上限，包括ActionProposal内部120字符检查；保留非空单行字符串。reason_max_chars字段和现有解析参数兼容保留，仅作提示长度建议。提示词用原80/120/180字数作大致建议，分别给普通动作、记忆动作、反馈、规则操作的最小JSON示例；applicability是字符串，备选可为空，引用逐字复制已提供编号。

规则输入的自主周增加pre_decision_action，与values.executed_action明确区分。动作条件仍指行动前状态；support/contradict须满足所选全部条件，可按matched_condition_ids核对。reference不能出现在judgments中，包括ignore。

响应校验失败后重试“原始完整输入＋一条最近错误的user纠错消息”，只含公开错误码、路径、要求及必要错误值；不回传完整旧答复、不堆叠错误、不重跑检索/周反馈/stage。连接/服务失败复用当前请求。纠错改变消息时重新官方计数，超限则预检失败、不伪造外部调用。仍最多三次、等待2/4秒，辅助耗尽仍为unavailable。

调用审计增加可选validation_error，记录实际发送的消息、hash及token。动作收尾在审计追加之后执行，最终决策证据使用最后一次调用的messages_sha256/input_tokens；原事实registry和context_hash保持不变。不增加校验框架、错误文案注册表或新迁移。

动作尝试与辅助尝试分开；token、耗时和费用来源覆盖全部请求。程序只在真实边界校验，内部使用解析对象；条件、字段投影和相似度各保留一处权威定义，不建重复注册表。

## 5. 实施顺序与验收

1. 移除案例followup状态机，接入单周案例和平铺周序列。
2. 升级v2学习库和rule_updates，接入判断、统计及内容版本更新。
3. 接入规则v3解析和支持场景检索，清理旧evidence规则逻辑。
4. 更新周反馈及动作上下文、审计、文档和人工样例。
5. 同步软长度建议、明确格式与时间语义、带错误的校验重试及逐次计数审计。提示词版本/hash升级，响应和学习库schema不变。
6. 验收时先跑定向测试，再跑受影响的记忆、runner、快照和学习恢复回归。

验收须覆盖：连续周不重复；四个整理时点正确；参考周不能支持规则；day119无followup；支持/相悖/ignore和重复/改判计数；统计不升版本、内容修订重算；三项以上操作及整批拒绝；超过六条规则保存与检索；v1库拒绝；失败回滚；冻结评估不写库；119日/17窗/16决策及控制评分不回归。删除旧协议专属测试，不删除仍适用的公开/私有隔离与执行边界测试。

补充验收：超原字符上限的合法说明经过解析、ActionProposal和日志；applicability对象、缺cost.引用、参考周ignore及行动前/本周动作混淆返回准确路径。第二次携带具体错误，第三次替换旧错误；连接重试消息不变；纠错输入超限零调用；实际token/hash和最终证据一致；纠错中的未注册ID仍不能引用。回放小型真实计时中的失败响应，仅做离线验证，不自动调用付费模型或改动快照身份。

使用`D:/programfile/miniconda3/envs/simulation/python.exe`。离线工程通过不代表真实模型控制收益，正式训练及科学评价不由本次改造自动启动。

## 6. 输入优化与16回合切换

- 仅发送层使用保序`prompt_json()`，不修改canonical hash或持久化序列化。动作memory置前且knowledge先于动态内容；周反馈task_rules置前。规则请求顶层依次为task_rules、current_rule_set、evidence_bundle，固定知识移出证据包；bundle仅含condition_catalog、weeks、comparisons。
- 三类请求复用知识投影，删除source/review_status；仅规则维护再省略知识卡version，其他字段及always优先、同类按ID排序保持。动作和周反馈的投影、提示版本不变，完整卡及来源仍本地保存。
- 规则发送层省略bundle的schema_version/public_task_sha256/as_of_day；每周省略case_id/revision/opaque_group及values内重复的start_day/end_day；规则省略public_task_sha256/updated_at_day/updated_in_episode/conditions/increment。条件定义集中在condition_catalog，规则保留content.condition_ids；保留规则ID、版本、内容、状态、聚合统计和暂停reason，以及周编号、角色、外层日期、公开值及有效性、support_window、行动前动作和匹配条件。内部完整对象、版本和事务均不变。
- 内部facts及原引用编号保留；wire周反馈只有一次周数值及reference_fields，不新建字段注册表。未知字段、无效值和未发送引用仍拒绝。临时笔记事实值、依赖及期限不变。
- 发送知识hash、K:registry、cited_evidence与context_hash对齐发送投影；内部packet_hash保留，实际消息hash/token取最终渲染。独立验收从已验证bundle恢复内部卡，核对投影后重建完整请求，不放宽来源或引用资格。
- 周反馈输入仍v4、提示仍v5；本次仅规则维护提示升级v6，保持输出patch v3、任务hash、学习库schema、模型强度、输出限额、反馈频率与规则维护不变；同步人工样例和审计说明。
- 离线验收覆盖稳定前缀、删除字段未发送、条件编号均可解析、周数值无损、投影不突变原对象、引用拒绝边界及纠错计数。知识和规则不变时，动态证据不影响evidence_bundle开始前的字节。以历史公开调用离线比较token和公共前缀，不当作真实命中提升。
- 三组外层监督进程在前16回合完成前暂停，Python训练子进程继续。隔离目录实施并验证；各组正常完成16且完成表确认后结束旧监督进程、冻结16回合副本，再从新版沿用原库与原清单续训17–32。若失败则保留审计，不把失败视为完成。最终产物标明前16旧协议、后16新协议，11/22仍high、33仍low；不额外启动验证或测试集。

上述16回合切换保留为既有运行约定，后半段使用规则提示v5。本次规则提示v6只供后续新启动的运行使用，不改历史审计、学习库、冻结副本或离线报告，不追加付费调用或训练。

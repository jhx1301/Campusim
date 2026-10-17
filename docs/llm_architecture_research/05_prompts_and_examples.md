# 完整提示词、输出结构与贯通示例

版本 `cemas-public-case-design-v1`，2026-10-17。主方案实际调用只有每周一次决策LLM（技术/解析重试至多3次）。近期摘要、案例生成、知识选择、检索、结构检查均由程序完成；没有LLM反思、经验写手、审查员或辩论调用。

## 1. 可直接检查的完整交付

下列JSON含完整文本与数值，未以省略号、短history或字符串mask代替实际消息。所有示例均为人工构造，不是模型结果；人工标记在消息外的walkthrough/manifest中，避免增加非任务输入。

| 文件 | 内容 |
|---|---|
| [decision_template.json](examples/decision_template.json) | 唯一完整system模板、固定六条规则、模板版本；`${name}`由程序渲染 |
| [public_task_snapshot.json](examples/public_task_snapshot.json) | 从当前协议白名单提取的动作/目标/资源/活动/年龄/时间规则 |
| [knowledge_cards.json](examples/knowledge_cards.json) | 9条有来源、版本、前提、限制、映射、触发器的知识卡；空冲突对表 |
| [none_messages.json](examples/none_messages.json) | 无显式记忆的完整system/user两消息（324位mask、四个完整周、全部公共率） |
| [both_messages.json](examples/both_messages.json) | 相同观察的完整近期摘要＋3个公共案例消息；与none使用同一system |
| [failure_messages.json](examples/failure_messages.json) | 查询IO暂时失败、案例为空的完整消息；状态unavailable可见 |
| [synthetic_cases.json](examples/synthetic_cases.json) | 三个完整PublicCase，前态、实际执行、7日后窗、来源公共hash、描述/限制 |
| [query_and_retrieval.json](examples/query_and_retrieval.json) | 38维查询、scale、趋势、逐例距离/得分、冲突对、选中顺序与动作适配 |
| [none_walkthrough.json](examples/none_walkthrough.json)、[both_walkthrough.json](examples/both_walkthrough.json)、[failure_walkthrough.json](examples/failure_walkthrough.json) | 人工五字段响应、预期共同执行、消息hash；token_count=null明确未计量 |
| [terminal_feedback.json](examples/terminal_feedback.json) | H110、day105开始的5日尾窗完整公共观察/反馈，以及不再决策的预期 |
| [manifest.json](examples/manifest.json) | 人工属性、基线HEAD、模板/任务/知识/文件hash |

[build_examples.py](examples/build_examples.py)是本目录的静态示例生成器，只读现有协议/模板并写本目录JSON，不导入引擎、不调用API、不推进仿真。它不是P5实现。修改原模板/协议后再次生成会改变hash；正式实现应使用冻结产物而不是静默追随HEAD。

## 2. 所有调用的消息契约

| 调用/步骤 | 输入权限、输出、次序 | 触发、预算、失败 |
|---|---|---|
| `decision`（唯一LLM调用） | 固定system＋动态user；输入仅精确O及公共派生/知识/案例；返回五字段JSON，再适配原ActionProposal | day0及每7日；input cap131072/output cap65536；通常1次，P4至多3次同消息、2/4秒间隔、timeout120；fatal不推进，耗尽共同回退 |
| `recent`（程序） | O的有效四周→02章RecentSummary | 每次decide；缺失保留valid标记，禁止推断稳定/感染 |
| `case_build`（程序） | pending O＋observe的实际执行和已封闭公共反馈→revision | 每次observe含终点；重复同内容幂等、乱序fatal；数值与描述固定模板生成 |
| `retrieve`（程序） | 公共pre-state→兼容过滤/数值排序/冲突/去重 | global/both；规则见02；无候选正常，IO暂时失败unavailable，完整性失败fatal |
| `knowledge_select`（程序） | O派生flags＋冻结卡片→允许卡片 | 六条始终在system；外部卡仅user；源冲突未解不发布bundle |
| `parse/evidence`（程序） | 原文＋裁剪后registry/flags→ParsedDecision | 拒绝结构/引用错误，走相同消息重试；主动作资源非法交共同resolver |

没有按模式增加额外隐藏调用；没有在线摘要、经验生成、反思、校正提示词。未采用组件不需要模型模板，03章中的审查/多角色只为未来实验设计，不能在未冻结其模板前运行。

## 3. system与user的具体构建

`decision_template.json.system`保留当前P4的完整动作参数、固定处置、共同目标/负担、人口预算、延迟和观察解释；替换末尾输出规范并增加显式资料说明。`expert_rules`仍是六条认识约束。程序从`public_task_snapshot.json`渲染所有`${...}`，不让LLM填参数。

全部system变量及其来源：

- `decision_interval_days,history_weeks,quarantine_days`：公共task投影；`age_bands`：公开固定年龄边界。
- `ranges,joint_count,T_levels,S_levels,C_levels,E_levels,A_levels`：公开动作投影；S采用ceil(request_ratio*N)，C按home/school/work/community顺序列概率与延迟。
- `clinical_ratio,tracing_ratio,recent_exclusion,sensitivity,loss_prob,report_delay`：公共资源/检测规则。
- `test_reference,notification_reference,lambda,weights,formula_version,objective_status`：共同目标公开定义，不含当前私有reward。
- `single_budget,community_budget,dual_budget,neither_budget`：公开活动预算。
- `reason_max_chars`：120；`expert_rules`：冻结核心规则。N/H/decision_day只来自user观察，不含在动态system里。

user模板是下面五个必需键，实际JSON字符串以UTF-8、排序键、紧凑分隔符序列化。文件中的每个值都已完整展开：

```text
{
  observation: public_observation_to_dict(O),
  public_rates: P4公共率公式(O),
  memory: {
    mode: none|short|global|both,
    recent: RecentSummary|null,
    knowledge: KnowledgeCard[],
    retrieval: RetrievalResult
  },
  evidence_registry: string[],
  required_uncertainty_codes: string[]
}
```

`observation`保持当前完整schema。`public_rates`保持P4字段和公式。core卡元数据可在user重复供溯源，其约束文本由受信system给出；动态PH卡、近期摘要、案例和registry只在user出现。无效history不能注册O引用；registry是有限、确定性的可引用集合，不要求复制每一个原始数值。`O:/history/3/cost`关联完整公共负担对象，依据日志保存原值，不由模型重抄。

short=recent有效/cases空；global=recent null/cases检索；none=recent null、retrieval empty＋disabled标记；both两者都有。原始四周观察、public_rates、知识和system跨模式相同。因此短期消融只测试显式整理的作用，不能称“无记忆”完全没有历史。

数据异常和裁剪时：先程序确定上下文，再按02章顺序删完整案例/低优先级PH卡/摘要，重建registry和required_flags，再官方计数、hash，才请求。重试不附加错误、assistant回答或额外反馈，避免改变调用信息条件。

## 4. 完整输出schema

严格JSON恰好五键，不接受额外正文、围栏、重复键、NaN/Infinity：

```text
{
  action: int[5],                         # T0..2,S0..3,C0..2,E0..2,A0..2；bool/float拒绝
  reason: str[1..120],                    # 非空单行
  evidence_ids: unique str[1..8],         # 仅本次registry
  alternative_actions: [                 # 0..2个，主动作不同，候选之间不重复
    {action:int[5], tradeoff:str[1..80], evidence_ids:unique str[1..4]}
  ],
  uncertainty_codes: unique enum[1..8]    # 必含程序required集合
}
```

八枚举固定为`partial_observability,no_history,testing_changed,capacity_changed,no_case,case_conflict,out_of_support,truncated_followup`。始终包含partial_observability；其它触发规则见02章4.4。它们不是校准概率或置信分数。

system要求动作满足mask；程序结构解析只查范围。主动作资源非法仍交共同resolver，保持现有全动作回退语义；备选mask非法标infeasible，不执行、不因此重试主提案。未知引用、未注册引用、裁剪后仍引用、缺required flag为解析失败，可用P4原预算重试。

适配保持`ActionProposal(ActionVector(parsed.action), reasoning=parsed.reason)`；后三键单独进入DecisionEvidence和runner日志。**现有P4 parser不接受此schema**；未来需新template/parser版本和协议中的LLM字段登记。原P4基线仍使用action/reason两字段；新memory消融统一五字段，避免把输出格式增益混入memory。

## 5. 三条贯通设计示例

### 正常决策与相互矛盾的源案例

同一人工观察在day28：四周交付诊断12、18、26、34；实际检测900、1000、1100、1200；当前[1,1,1,0,0]已连续执行28日；筛查容量600/日，S2合法、S3不合法。这些数字没有隐藏感染含义。

检索的101/207拥有相似pre-state、相同执行动作[1,1,1,0,0]，首窗诊断分别从32到20、35到46，满足预注册的公共方向冲突条件；不同源轨迹、pairwise state相似度通过门槛，因此两例共同保留。309对应[1,2,1,0,0]、600/日资源，首窗诊断33到28。查询只对前态算分，未按后效好坏排序。完整分数在query_and_retrieval.json，非手填。

人工响应选择[1,2,1,0,0]：当前公共诊断增加、筛查资源允许、案例提供该档的可执行参照；同时承认增加检测负担、各例后效不是因果。备选维持S1。这个选择用于展示信息如何参与决策，不是本研究声称的正确/最优动作。程序核验引用、格式、mask后交共同resolver；执行后才以feedback实际动作写case。相同O下none示例保留原始历史但没有recent/cases，展示输出接口和信息差异，不用人工动作差异充当记忆效果证据。

### 检索临时失败

failure_messages保持同一O/知识，查询捕获已知IO错误，status=unavailable、无案例、required含no_case。人工输出合法保持[1,1,1,0,0]且引用O/K，无C引用；这是有明确故障标记的正常决策，不是伪装有案例。若是库hash/版本/完整性不符，启动/运行fatal，不能进入此降级消息。

若输出三次结构/服务失败，controller返回None及llm_retry_exhausted；当前S1合法则共同保持全组合。若新容量仅允许S0，则回退保持T/C/E/A并把当前S降至S0；不能把失败请求的其它维度执行。反馈到达后照实保存回退后的实际组合。

### 末周公共反馈

terminal_feedback给H110，day105的待配对O包含77–83、84–90、91–97、98–104四个完整周；真实尾窗105–109为5日，增长无效且0填充，交付诊断7、检测480、通知22。observe在terminated判断前收到它，创建terminal_censored案例，window_days=5、followup=null、partial_window与truncated_followup；末窗不进入完整周检索、不补天、不再请求模型。

上一98–104案例如获得这个5日followup，可标closed_two但必须truncated_followup；不能称14日完整效果。H112的105–111末窗是完整7日，仍因无更晚followup而terminal_censored，但其首窗可进入默认源库检索。

## 6. 程序核查与信任边界

[verify_examples.py](examples/verify_examples.py)用项目真实公共dataclass构造器检查人工观察/反馈（仅加载types.py，不运行引擎），复核mask、计数/增长、引用路径、响应长度、required flags、文件hash、同system、终点时序和本目录链接。结果写入[verification.json](examples/verification.json)。这证明示例的结构/算术与当前公共类型一致，不证明LLM行为或闭环效果。

程序可以确认引用存在与其数值来源、候选格式、实际动作与请求分离、输入hash和时序。程序不能证明自然语言理由忠实、案例支持因果或最优策略。语义检查采用03章盲评/扰动/失败分类；不能把模型自评、长理由、第二模型一致或完整CoT当可信度证明。

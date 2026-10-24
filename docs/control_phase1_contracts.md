# CEMAS control v1：Phase 1 统一动作空间契约

> 2026-10-23：本文的旧校准、人口及验收数字为历史记录。当前唯一标准和运行入口以 [UW 控制接入](uw_control_integration.md) 为准；旧结果不作为 UW 验收。

本文件补记 2026-10-13 完成的 Phase 1 工程契约，原实现提交为 `0360a2f`（`Phase 1: implement action space encoding and resolution`）。动作语义版本为 `cemas-action-semantics-v1`，数据 schema 版本沿用 `cemas-control-schema-v1`。依据为[机器配置](control_protocol_v1.json)、[推荐协议 v1](llm_recommended_protocol_v1.md)及[Phase 0 契约](control_phase0_contracts.md)。本文件于 2026-10-14 补充，描述 Phase 1 交付边界；后续执行行为见[Phase 2 契约](control_phase2_contracts.md)。

## 动作表示与固定基线

`ActionVector.values` 固定顺序为 `[T,S,C,E,A]`，档位数量为 `[3,4,3,3,3]`，索引从 0 开始，共 324 个联合动作。该类型表示 policy maker 相对于固定运行基线选择的额外政策干预强度。所有维度的 level 0 均表示 `no_additional_intervention`。

固定基线属于 JSON 的 `environment_configuration.fixed_baseline`，引用相应维度 level 0 的有效参数；不进入 `PublicObservation`，不作为 controller 可见状态。因此 T0/C0 仍有例行检测/追踪行为，零档不表示模拟器完全没有这些行为。隔离和检疫为共同固定处置，不另设第六个维度。

JSON 的 `effective_parameters` 表示选定档位后包含基线的总有效设置，不能再次与基线相加。JSON 记录动作维度、每档语义、有效参数、单位及来源；具体 Covasim 参数和网络层映射由 Phase 2 定义。

`ActionVector` 为 frozen/slots dataclass；只接受长度 5 的普通整数 tuple/list，拒绝布尔、浮点和越界值。列表输入复制为不可变 tuple，供所有 controller、日志和执行历史共用。

## 五维动作及档位

T 统一描述病例相关检测和隔离/检疫检测强度，普通无症状主动筛查由 S 描述。下表为有效检测请求概率，实际检测量受运行时资源和对象资格约束。

| 档位 | 额外政策含义 | 有症状日概率 | 普通无症状日概率 | 症状检疫入口概率 | 无症状检疫入口概率 |
|---|---|---:|---:|---:|---:|
| T0 | 无额外检测，保持例行基线 | 0.08 | 0 | 0.25 | 0 |
| T1 | 低强度额外检测 | 0.14 | 0 | 0.50 | 0.03 |
| T2 | 高强度额外检测 | 0.22 | 0 | 0.80 | 0.08 |

S 描述每日主动周期筛查请求。`N` 为回合初始化时确定的公开登记人口，回合内固定；不是每日存活人数或隐藏病例数。

| 档位 | 含义 | 每日请求比例 | N=12,000 时请求人次 |
|---|---|---:|---:|
| S0 | 无主动筛查 | 0 | 0 |
| S1 | 低强度筛查 | 0.02N | 240 |
| S2 | 中强度筛查 | 0.05N | 600 |
| S3 | 高强度筛查 | 0.10N | 1,200 |

整数请求量按 `ceil(request_ratio × N)` 定义，请求量与实际执行量分开。

C 描述接触追踪强度，通过提高覆盖概率、缩短通知延迟体现。外部索引病例调查容量不由动作 level 选择。各格依次为覆盖概率、通知延迟（天）。

| 档位 | 额外政策含义 | 家庭/宿舍 | 学校 | 工作/机构 | 社区 |
|---|---|---|---|---|---|
| C0 | 无额外追踪，保持例行基线 | 0.60 / 0 | 0.20 / 3 | 0.18 / 3 | 0.15 / 4 |
| C1 | 低强度额外追踪 | 0.95 / 0 | 0.45 / 1 | 0.40 / 1 | 0.35 / 2 |
| C2 | 高强度额外追踪 | 1.00 / 0 | 0.80 / 0 | 0.70 / 0 | 0.55 / 1 |

E 只描述课堂教学限制；A 描述非课堂工作、公共空间和社区活动限制。两者均不限制家庭/宿舍接触；A 不限制课堂，E 不限制非课堂工作和社区活动。

| 档位 | 含义 | 有效传播乘数 | 活动限制等效比例 |
|---|---|---:|---:|
| E0 | 正常教学，无额外限制 | 1.00 | 0 |
| E1 | 部分线上教学 | 0.50 | 0.50 |
| E2 | 全面线上教学 | 0.00 | 1.00 |
| A0 | 正常非课堂活动，无额外限制 | 1.00 | 0 |
| A1 | 轻度活动限制 | 0.75 | 0.25 |
| A2 | 中度活动限制 | 0.50 | 0.50 |

上述数值是合成基准假设。T/C 沿用 legacy P0/P2/P4 配置，不是 Covasim 默认值或已校准结果；S/E/A 来自 v1 政策设计。活动比例与传播乘数为分别声明的抽象设置，不能将传播变化反推为实际负担。

## 编解码与 action table

```text
encode_action(action: ActionVector) -> int
decode_action(action_id: int) -> ActionVector
ACTION_TABLE: tuple[ActionVector, ...]
```

固定混合进制编码为：

```text
action_id = ((((T * 4 + S) * 3 + C) * 3 + E) * 3 + A)
          = 108T + 27S + 9C + 3E + A
```

T 为最高位、A 为最低位，编号范围为 0–323。`ACTION_TABLE` 按 `decode_action(0)` 至 `decode_action(323)` 生成，长度 324、不可变、可直接按 action_id 索引。表和编号均不随资源、controller 或场景改变。

例如 `[0,0,0,0,0] -> 0`、`[0,1,0,0,0] -> 27`、`[1,0,0,0,0] -> 108`、`[2,3,2,2,2] -> 323`。双向契约为：

```text
decode_action(encode_action(action)) == action
encode_action(decode_action(action_id)) == action_id
```

decode 拒绝布尔、浮点、非整数和越界编号并抛出异常；encode 只接受 `ActionVector`。两者及 action table 均不检查资源、不修改动作、不静默降级、不选择 fallback。

## 决策阶段合法性 mask

```text
legal_action_mask(
    resources: PublicResources,
    population: int,
    action_spec: Mapping[str, Any],
) -> tuple[bool, ...]
```

`action_spec` 必须显式传入已加载协议的 `protocol.definition["actions"]`，S 比例从其中读取，不在代码中另存默认比例。mask 的 324 个布尔值与 action_id 一一对应，唯一筛选规则为：

```text
S.request_ratio × N <= resources.screening_daily_capacity
```

使用十进制比例的精确分数比较，避免浮点误差改变容量边界；对整数容量，上述规则等价于向上取整后的请求量不超过容量。

| N=12,000 时筛查容量 | 可选择 S 档 | 合法联合动作数 |
|---:|---|---:|
| 0 | S0 | 81 |
| 240 | S0、S1 | 162 |
| 600 | S0、S1、S2 | 243 |
| 1,200 | S0、S1、S2、S3 | 324 |

T 临床容量、C 索引病例容量及实际候选人数属于每日运行时约束，由 Phase 2 executor 处理，不影响此 mask。mask 只回答哪些动作允许选择，不执行调整或 fallback。首版每 7 天可自由改变各维度，无共同最低保持期、升降幅度限制或隐藏感染/risk 护栏。

## ActionResolution schema 与 controller 边界

`ActionResolution` 为 frozen/slots dataclass，Phase 1 只定义和校验数据契约：

| 字段 | 类型及含义 |
|---|---|
| requested_action | `ActionVector \| None`；解析成功的请求，缺失/非法请求无法表示为向量时为空 |
| executed_action | `ActionVector`；最终交给执行器的动作 |
| requested_action_id | `int \| None`；与 requested_action 一致，请求为空时也为空 |
| executed_action_id | `int`；必须匹配 executed_action 的编码 |
| adjustment_reason | `str \| None`；动作调整原因 |
| fallback_reason | `str \| None`；请求失败/非法等回退原因 |

合法请求正常执行时 requested 与 executed 相同。执行动作与请求不同，必须记录调整或回退原因；缺失 requested_action 必须记录 fallback_reason；请求和执行相同时不能记录 adjustment_reason。原因字段若提供必须为非空文本，编号必须为范围内的普通整数且与向量一致。

Controller 接口保持 Phase 0 契约：`decide(PublicObservation) -> ActionProposal`。PPO/DDQN 的内部编号先解码成向量，再封装为 proposal；LLM、Threshold 等直接提出共享向量。Phase 1 没有实现具体 controller 或编号输出适配器。公共提案进入后续 validator/resolver，得到 ActionResolution，再交 executor；非法输出的捕获、资源变化后的调整和 fallback 算法均由 Phase 2 承担。

## 文件与验证记录

Phase 1 原实现提交涉及六个文件：

- `cemas/control/actions.py`：新增 codec、ACTION_TABLE 和 screening mask。
- `cemas/control/types.py`：说明 ActionVector 语义，新增 ActionResolution。
- `cemas/control/protocol.py`：新增动作语义、参数范围、等级单调性、编号规则及环境基线边界的静态校验。
- `cemas/control/__init__.py`：导出共享动作 API 与 schema。
- `docs/control_protocol_v1.json`：冻结动作描述、有效参数、来源及 Phase 2 映射边界。
- `tests/test_control_actions.py`：新增穷举往返、mask 边界、schema 和协议一致性测试。

2026-10-13 原阶段验收运行 `test_control_actions.py`、`test_control_contracts.py`、`test_control_protocol.py`、`test_control_environment_check.py`，使用 `-q -m "not online"`：**151 passed、1 warning**。这是 Phase 1 完成时的历史验证结果，不代表本次文档补充重新运行测试。

使用指定解释器 `E:/pytroch/anaconda3/envs/simulation/python.exe`，通过临时追加本机已有 `E:/pytroch/anaconda3/Lib/site-packages` 复用 pytest；未安装依赖。显式设置 `SCIRIS_BACKEND=agg` 并关闭第三方 pytest 插件自动加载。警告为既有 `tests/pytest.ini` 的 `env` 选项未识别；`compileall` 和 `git diff --check` 均通过。

Phase 1 没有修改传播核心或 `interventions.py`，没有实现执行器、resolver、reward、memory、LLM、PPO/DDQN 或实验流程。实现保存在 `feature/control-protocol-v1` 的独立提交中，Phase 0 和历史版本保留；本次契约文档作为后续文档补充，不改写原提交。

# CEMAS control v1：Phase 4 公共 LLM 控制器契约

> 2026-10-23：本文的旧校准、人口及验收数字为历史记录。当前唯一标准和运行入口以 [UW 控制接入](uw_control_integration.md) 为准；旧结果不作为 UW 验收。

本阶段实现 `llm_no_explicit_memory`，沿用 P3 的观察、动作、执行器、目标和 E0 门禁。配置数值以 [协议 JSON](control_protocol_v1.json) 为唯一来源；固定文案以 `cemas/control/prompts/public_v1.json` 为唯一来源。实施与实际验收记录分开登记。

时序适用范围：本文实际验收中的首周LLM调用、H112共16次决策及fatal停在7日等数字保留为P4历史证据。2026-10-20修订后，首周统一最低干预且无LLM调用，day7首次自主决策；当前H112含1个固定窗口和15个自主决策窗口。旧验收不代表新规则已通过；day0 provider探针仍是独立输入验收，不是生产回合调用。

## 1. 输入、接口与阶段边界

`build_public_messages(observation, prompt_config, *, memory_context=None)` 只接受精确的 `PublicObservation` 和不可变公共配置。runner 工厂白名单投影公共动作、资源、活动、目标、观察解释和固定检疫期限，不传完整协议、manifest、seed、beta、私有感染或奖励。N/H、容量和历史只从 observation 读取。

每次决策仅发送 system/user 两条消息。user 是规范化 JSON，恰含 `observation` 和 `public_rates`。最近四个完整周以 observation 的顺序、左填充和有效标记为准；`observe()` 只校验公共反馈类型，不积累历史。非空 `memory_context` 明确拒绝，记忆、检索、裁剪和压缩属于 P5。

年龄人数 `age_band_counts` 及其人口比例使用同一顺序。system 文案从协议的 `observation.age_bands_shared` 渲染五组区间，说明年龄向下取整且区间包含两个端点。`PublicPromptConfig` 要求边界为普通整数，形状、顺序及数值与现有 `AGE_BANDS` 一致；本轮不扩展年龄分组或观察 schema。模板版本保持 v1，内容变化由实际模板及消息 hash 标识。

活动预算由协议的 `activity` 段统一提供给 prompt、人口登记及后续执行成本统计。公开登记接口调整为 `build_population_registry(people, *, activity_config)`；旧调用需显式补充当前协议的 `definition["activity"]`，执行器和 E0 标定均采用此方式，不读取隐式默认协议、不保留第二套数值默认值。四项预算须为有限的普通数值且位于 `[0,1]`；单一学校/工作预算加社区预算、两倍双重身份预算加社区预算，以及其他人口社区预算均须为1，比较使用 `rel_tol=0, abs_tol=1e-12`，不自动归一化。默认协议数值不变。

`Controller.decide()` 返回 `ActionProposal | None`；`consume_failure_reason()` 默认 None，`drain_call_audits()` 默认空 tuple。LLM reset 清空失败原因及待交付审计，每次 decide 先清除旧失败原因。

| 接口 | 职责 |
|---|---|
| `runner.make_public_prompt_config(protocol, template_path=None)` | 白名单投影、加载固定模板，返回嵌套不可变的 PublicPromptConfig |
| `runner.make_llm_settings(protocol, provider, endpoint, api_key_env)` | 模型/预算/重试/采样参数取自协议；只接收凭据环境变量名，不接收密钥值 |
| `LLMSettings.input_tokenization_parameters()` | 从完整请求参数投影 model 和 extra_body，供 tokenizer 输入模式绑定；不包含输出预算或采样参数 |
| `runner.make_llm_controller(..., tokenizer_manifest)` | 组装生产transport、配置和本地计数器；SDK/tokenizer不在包导入时加载；旧tokenizer_acceptance参数兼容接受但不读取 |
| `LLMTransport(settings, client=None).complete(messages)` | 单次OpenAI兼容SDK请求；主模型thinking/effort/top_p，次模型enable_thinking；完整输出限制分别适配max_tokens/max_completion_tokens |
| `OfficialInputTokenCounter(resource_manifest, acceptance_path=None)` | 正常运行validate仅检查计数资源；计数及本批次服务身份检查；acceptance_path仅供显式validate_acceptance使用 |
| `runner.accept_llm_token_counter(transport, counter, config, observations, output_dir)` | 独立三种公开消息的候选计数验收，记录调用并生成匹配receipt；不推进实验episode |

`observations` 的键固定为 `day0/four_weeks/long_numeric`，值必须是精确公共观察类型；后两者都有四个有效周，long_numeric的数值payload更长。验收原文、usage、响应id/模型/指纹和本地计数逐次持久化；任何失败保留调用及failure.json，不生成accepted receipt。

## 2. 消息身份、解析和预算

模板、公共规则快照、最终消息分别使用排序键、紧凑分隔符、UTF-8 JSON 的 SHA-256。消息数组保持顺序，消息content字符串的实际字节参与hash；完整协议 hash 仅留在 runner 私有元数据。显式记忆及辅助请求的user内容由保序prompt_json()渲染，固定知识置于动态数据之前；canonical_json()/public_hash()的身份规则不变，普通无记忆动作入口不受影响。

响应只能是恰含 action/reason 的 JSON 对象。拒绝重复键、NaN/Infinity、围栏、额外正文和自动修补。action 是五个普通整数，范围由 ActionVector 检查；reason 是非空单行字符串，提示词建议约reason_max_chars（默认120）字以内但不再硬性计数，不截断或改写。配置字段和解析参数名保留兼容，ActionProposal内部也不再限制字符数。最小格式为`{"action":[0,0,0,0,0],"reason":"根据当前公开观察选择动作。"}`，实际动作须满足当前mask。非快照资源非法提案仍交共同resolver；快照主动作在请求成功前检查合法mask，非法进入响应校验重试。

完整输入保护上限131072；DeepSeek完整输出保护上限131072（max_output_tokens），Qwen保持65536（secondary_max_output_tokens），不单设推理预算。未配置secondary_max_output_tokens的旧配置继续沿用max_output_tokens。输出包含推理和最终回答；DeepSeek使用max_tokens，Qwen使用max_completion_tokens。上限是异常膨胀保护，不要求每次用满，修订依据见第7节。官方本地 tokenizer 必须包含模型对应关系、文件内容 hash、消息模板和加载库版本；正常运行不下载、不估算。初始消息只构造一次；校验纠错改变消息后重新官方计数并检查完整输入，连接/服务重试复用当前消息与计数。输入超限零调用。实际usage与本次实际请求的本地计数不一致或超限时终止。

当前离线适配为 `official_local_chat_template_v1` / `hf_apply_chat_template_v1`：显式 `tokenize=True, add_generation_prompt=True, return_dict=False, truncation=False, padding=False`。资源manifest包含 `adapter/provider/model/official_source/library_versions/files/chat_template_file/template_kwargs/input_tokenization_sha256`；files逐一锁原始字节hash，库版本锁transformers、tokenizers、jinja2、markupsafe。输入模式hash来自 `snapshot_sha256(settings.input_tokenization_parameters())`，只绑定请求的 `model` 和 `extra_body`：DeepSeek保留thinking开关和reasoning_effort，Qwen保留enable_thinking。输出预算、temperature、top_p、stream不参与此hash；仅改变输出预算、温度或top_p时可复用同一资源manifest和计数器实例，输入计数与资源身份保持不变。provider/model、模板及template_kwargs、文件和库版本仍受原检查约束。不接受覆写计数控制参数或未固定的加载资源。官方资源没有可核验消息模板、需要尚未实现的其他编码器或版本不符时直接阻止，不自行发明模板。

2026-10-27起只接受新字段；含 `request_parameters_sha256` 的旧manifest报 `tokenizer_manifest_upgrade_required`。升级时保留其他字段和所有资源文件，删除旧字段并根据实际运行的 `settings` 计算新字段。以下示例中的 `settings` 由现有 `runner.make_llm_settings(...)` 工厂按当前协议、provider和endpoint构造：

```python
import json
from pathlib import Path
from cemas.control.logging import snapshot_sha256

manifest_path = Path("path/to/resources.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
del manifest["request_parameters_sha256"]
manifest["input_tokenization_sha256"] = snapshot_sha256(
    settings.input_tokenization_parameters()
)
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

升级后新建 `OfficialInputTokenCounter(manifest_path)`；已加载实例仍禁止批次内manifest变化。升级会改变manifest及资源身份hash，历史验收报告和冻结产物不自动改写或重新签认。

正常运行不读取或要求 `tokenizer_acceptance.json`。资源完整性、输入预算和实际 usage 检查直接针对当前请求；本批次首个实际返回建立服务型号/指纹基准，后续变化时终止。开发验收仍可生成报告，通过显式 `validate_acceptance(settings)` 核对资源身份、endpoint、请求参数、三个case的消息/hash/usage与服务一致性；报告内容不设置正常运行的服务基准。hash用于完整性和关联，不代替官方资源来源核验或真实账户调用证据。

完整生成参数继续写入调用审计、运行元数据和开发验收报告。资源可复用不表示旧报告已验证新生成配置；输出预算、temperature或实际请求中的top_p变化后，显式验收仍因完整请求参数不匹配而拒绝旧报告。Qwen请求本身不使用top_p。

独立 provider 验收覆盖 day0、完整四周及长数值消息，保存每次完整消息、本地计数、实际 usage、模型与服务指纹。报告用于开发验证和留档，不作为使用程序的启动凭证。正常运行仍需要可用计数资源；mock通过不代表完成真实服务验收。

## 3. 调用、失败与共同回退

transport 单次请求，SDK 内部重试为0。controller 最多三次尝试，连续可重试失败恰好三次，间隔2/4秒；成功立即结束。重试覆盖临时连接/超时、408、限流429、临时5xx和严格解析失败。配置、鉴权、模型、参数、余额/硬配额、预算或计数器错误立即终止。先看结构化错误码再看HTTP状态，未知错误保留异常终止。

响应校验失败后的消息为原始完整输入加一条user纠错：仅包含最近一次错误码、字段路径、正确要求及必要错误值，要求重新返回完整JSON，不附整份旧答复、不累积历次错误。现有异常details在报错点提供首个错误，不新增并行错误注册表。纠错不得带SDK原始消息、凭证、私有信息或内部推理，也不扩大可引用证据集合。连接/临时服务失败原样重发当前请求；重试不重做检索、反馈或stage，纠错后输入超限只记预检失败，不记provider attempt。

耗尽返回None，失败原因`llm_retry_exhausted`。非快照runner将该原因传给step_proposal()，沿用保持当前组合、必要时只投影S的共同回退；快照任务停止回合并回滚本训练事务，不执行替代动作。None必须有失败原因；有效提案不得同时带失败原因。

错误码按供应商解释：Qwen的429 `insufficient_quota` / `Throttling.AllocationQuota`可能表示临时token限流；明确余额、欠费、硬额度或免费额度耗尽仍立即终止，不把包含quota的错误一律归为同一种。只在内存中读取用于区分的已知结构化描述，日志保存稳定码和通用脱敏描述。[Qwen官方错误码](https://www.alibabacloud.com/help/en/model-studio/error-code)、[限流说明](https://www.alibabacloud.com/help/en/model-studio/rate-limit)

## 4. runner、持久化和用途

runner 在 decide 成功或异常后都先交付/落盘已产生的调用审计，再推进环境或处理失败。fatal 不推进当周、不制造正常决策；manifest failed，保留之前轨迹。调用前失败没有伪造 attempt，预算/配置证据进入 failure.json。

决策异常与审计交付异常同时发生时，runner 保留并抛出原始决策异常，将次级故障作为脱敏附注及 `failure.json` / `summary.json` 的 `details.call_audit_error` 保存。该可选摘要仅含 `stage="call_audit_delivery"`、异常类型和固定描述，不保存原始异常文本；原有错误码、计数与消息 hash 保留。持续 snapshot/flush/close 故障在安全失败日志中仅记录操作和类型，复合故障后续清理附注也不保存原始异常文本。决策成功而审计失败仍抛出审计异常并停止当前周，Python 3.10 沿用既有附注兼容路径。

私有 `llm_calls.jsonl` 逐次保存日/序号/UTC时间、供应商及endpoint、请求和返回模型、响应id/指纹、完整消息及三种hash、计数器身份和输入量/预算、usage、最终原文、finish reason、耗时、稳定错误及可重试性，并增加默认空的validation_error。不得保存认证头、密钥或原始供应商异常文本。动作成功收尾在当前调用审计追加后执行，决策证据的messages_sha256/input_tokens取最后一次实际调用；公共context_hash和原引用registry不因纠错变化。DecisionRecord的llm_attempt_count仍只计动作请求，llm_succeeded口径不变。

离线 smoke 使用既有 smoke 世界；真实 prompt 开发使用40001–40009，仅 runner 管理 seed，内部仍走 scientific 环境和真实 E0 门禁。后续P6工程已接入源域A/B、pilot及训练/冻结工具，正式开发批次与共同冻结尚未完成；最终测试池保持关闭。

manifest的 `run_purpose` 保存runner用途；环境内部purpose为scientific。LLM元数据额外记录 `live_provider`、transport类型、模板/公共快照hash、settings和计数器身份。P4初始接入将生产transport限于prompt_development；后续P6允许其用于保留源域A/B的scientific用途和pilot源池，仍校验实际用途与seed，不能据此使用最终测试池。离线替身只能用于smoke；固定参照继续使用既有用途。不可重试失败不制造回退；调用前失败保留可用的三类hash、输入计数与预算。

薄入口为 `examples/control_v1/run_llm.py` 与 `smoke_llm.py`。真实入口显式要求endpoint、凭据变量名、资源manifest和真实E0产物；不要求或读取计数验收报告，旧报告参数仅兼容接受。模型名仍由协议提供。`--help`不会启动模拟或加载SDK/tokenizer。P3既有入口和历史产物保留。

## 5. 实际验收

2026-10-16，基线 `feature/control-protocol-v1@4ad20f5`，使用用户指定的 `E:/pytroch/anaconda3/envs/simulation/python.exe`（Python3.10.20）完成离线实现和验收。用户本轮明确选择先完成离线工作，真实provider/tokenizer验收暂缓；没有付费模型调用，也没有把替身计数登记为模型token量。

该解释器原先缺少pytest。pytest7.4.4及其依赖装入被Git忽略的 `results/control_v1_phase4/test_dependencies/`，未修改共享Python环境。SDK/tokenizer库原已存在，P4可选依赖声明及39项实际版本闭包分别为 `requirements-control-llm-v1.in`、`requirements-control-llm-v1.lock.txt`；P3历史环境快照未覆盖。

- 全部 `tests/test_control_*.py` 加 `test_cemas_import.py`、`test_campusLayer.py`：**472 passed**；证据为 `results/control_v1_phase4/regression_final_compat.xml`。错误码专项**17 passed**（`error_mapping_verified.xml`）；最后保留原决策计时口径、排除审计落盘时间后，runner定向回归**35 passed**（`runner_verified.xml`）。这些专项与全量测试有重合，不相加计算唯一测试数。
- 覆盖公共配置/三类hash、公共/私有隔离、唯一历史、严格parser、7999/8000/8001预算、缺失/不符/未验收计数器、精确重试及2/4秒等待、不同供应商参数与错误码、调用前失败零attempt、usage不一致、调用落盘顺序、S容量下降仅投影S、fatal和日志失败不推进当前周。P3固定参照及既有control回归继续通过。
- 真实本地Transformers/tokenizers/Jinja加载路径使用**合成词表**测试，显式验证完整两条消息、角色、模板和生成前缀；它不代表DeepSeek/Qwen的官方资源或服务计数验收。当前Transformers5.13默认返回字典，适配已显式 `return_dict=False`；不截断、不填充。
- 指定Python3.10没有 `BaseException.add_note()`，runner已兼容保存次级清理/日志故障到 `__notes__`，不掩盖原始异常；两种复合故障已纳入回归。DecisionRecord的elapsed_ms继续计量decide耗时，审计IO另属runner开销；单次调用耗时保留在LLMCallAudit中。
- `compileall`、`pip check`、`git diff --check`通过。pytest仍有既有 `env` 配置未识别警告，没有为消除此警告更改项目设置。

最终离线闭环位于 `results/control_v1_phase4/final_verified/`，全部显式标记 `live_provider=false`、`accepted_for_live=false`、`calibration_verified=false`。输入计数100是测试替身常量，不是估算值或真实模型计数。

| 离线场景 | 世界 | N/H | 结果 | 决策数 | 模拟调用数 |
|---|---:|---|---|---:|---:|
| retry后成功 | 90001 | 12000/112 | completed，112条日记录 | 16 | 17 |
| 三次耗尽后共同回退，后续成功 | 90002 | 12000/112 | completed，112条日记录；首周回退、下一周无旧失败状态 | 16 | 18 |
| 首周成功，下一次fatal | 90001 | 12000/112 | failed，停在7个日步；保留第二次调用，不伪造第二周决策 | 1 | 2 |

独立读取JSONL/CSV核对三类hash、每次消息数、重试消息一致、attempt/DecisionRecord对应、日/周/终点各项及reward，结果为 `results/control_v1_phase4/verification.json`，可复核脚本为同目录 `verify_offline.py`。较早运行和失败的测试尝试保留为本地诊断，表中只列最终final_verified闭环。

本轮真实计算的模板hash为 `ae7e4ab1b8be642d0b4f410d6e466c11e1a7fcaa89b2486aa29e890ace9243f1`；公共规则快照hash为 `00d2c7f2f551ac6038faf26ef4e94bf846c9a06c27e1c228c7dd313bf6e4265b`。messages hash按每次实际消息记录，不预填单一全局值。官方tokenizer资源hash和真实usage目前没有验收记录。

从仓库根目录复现（输出目录必须全新；Windows沙箱下pytest临时目录访问可能需要授权）：

```powershell
$python = 'E:/pytroch/anaconda3/envs/simulation/python.exe'
$env:SCIRIS_BACKEND = 'agg'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONPATH = (Join-Path $PWD 'results/control_v1_phase4/test_dependencies')
$tests = @(Get-ChildItem tests -Filter 'test_control_*.py' | ForEach-Object FullName)
& $python -m pytest @tests tests/test_cemas_import.py tests/test_campusLayer.py -q -m 'not online' --basetemp results/new_p4_pytest
& $python -m examples.control_v1.smoke_llm --case retry --seed 90001 --output results/new_p4_retry
& $python -m examples.control_v1.smoke_llm --case exhaust --seed 90002 --output results/new_p4_exhaust
& $python -m examples.control_v1.smoke_llm --case fatal --seed 90001 --output results/new_p4_fatal
& $python results/control_v1_phase4/verify_offline.py
```

独立核对脚本读取本轮保留的final_verified目录；新命令输出的新目录需显式纳入复核。下一步真实验收须准备对应模型官方资源及模板，记录全部资源/库版本/请求模式身份，再用源域公共消息调用三种case，匹配实际usage后生成receipt。随后 `run_llm.py`仍要求真实主窗E0及匹配独立报告。不能将本轮离线完成等同于真实LLM episode可用、P5 memory完成或后续统一冻结实验完成。

## 6. 三项修正的兼容性

2026-10-16 后续修正统一了活动预算来源、保留决策与审计的复合故障、补齐年龄区间说明。上节验收数字、hash及产物是修正前的历史记录；修正后的验证单独保存在 `results/phase4_fixes_20261016/`。本次没有安装新依赖或进行真实 provider/tokenizer 验收，默认预算、动作、奖励公式和七日周期保持不变。

E0 兼容性校验包含人口登记及标定源码的 hash。这两处源码修改后，已有 E0 产物预期被拒绝；本轮保留原产物、不扩展历史源码白名单、不重写 hash，也不重跑完整标定。后续科学运行前须重新生成并验收 E0；回归测试使用当次测试生成的独立小型产物。

使用指定的 `D:/programfile/miniconda3/envs/simulation/python.exe`（Python 3.11.14），全部 `tests/test_control_*.py` 加 `test_cemas_import.py`、`test_campusLayer.py` 的非 online 回归为 **571 passed、1 failed**，16.12秒。唯一失败仍是本机缺少 `tokenizers` 导致既有合成词表测试无法导入；未安装依赖，也未将此结果登记为全量通过。最终证据为 `results/control_v1_phase4` 之外独立的 `results/phase4_fixes_20261016/regression_verified.log` 和同名 XML。新增验收包含100名仅学校成员的七日 E2/A0=420、E0/A2=140活动限制人天及对应奖励、预算两入口校验、年龄区间说明与严格类型检查、单次和持续审计故障脱敏、Python3.10附注回退；`compileall` 与 `git diff --check` 通过。历史E0读取按预期拒绝，证据为同目录 `compatibility_and_prompt.json`。

## 7. 输入输出保护上限修订

2026-10-29，单回合真实计时中一次动作请求用尽65536个推理token，最终JSON尚未输出即截断，纠错重试后成功。按用户确认，DeepSeek总生成上限提高到131072，保留thinking/high；动作、周经验和规则维护共用该值。Qwen使用secondary_max_output_tokens保留65536。只调整生成限额，不改变输入模式、官方tokenizer资源、截断检查或重试语义；旧计时和验收文件保持原值，不将新限额视为已完成真实服务验证。

2026-10-16，按用户要求移除次模型单独的4096推理预算，将输入上限改为131072、完整输出上限改为65536。模型自主结束后立即返回，上限只拦截异常膨胀。当时reason≤120字是格式契约；2026-10-28修订后仅作为提示建议，硬字符限制取消，action/reason结构和非空单行要求保留。输出空间同时考虑模型推理，不能只按最终JSON长度设置。

本轮使用现有公共prompt构造器及离线测试的day0/four_weeks/long_numeric观察，测量两条完整消息的规范JSON体积；没有调用模型或安装依赖：

| 结构 | 字符数 | UTF-8字节数 |
|---|---:|---:|
| P4 day0 | 12358 | 16792 |
| P4 四个完整周 | 12612 | 17046 |
| P4 长数值观察 | 12896 | 17330 |
| P5结构预留示例 | 79849 | 84283 |

P5示例按六条案例各带完整P4公共观察/比例及两周公共反馈、另附四个短期周反馈展开，用于保守预留，尚非已实现的P5提示词。131072输入上限相对这些结构留有较大空间；上述字符/字节不是官方token计数，不用于真实调用门禁。证据保存在 `results/llm_budget_review_20261016/payload_sizes.json`；P5实现后须重新测量实际四种记忆模式的完整官方token量，正常输入应有明显余量，再按结构需要调整。未实测模型推理长度，65536是可配置的宽松保护默认值，不是已验证的推理需求或最优值。

[DeepSeek官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)允许max_tokens覆盖推理及回答，当前thinking/high默认上限为64K；[Qwen官方接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)说明Qwen的max_tokens仅限制回答，max_completion_tokens限制推理及回答总量，支持Qwen3.5-Plus。[所选Qwen快照的模型卡](https://www.alibabacloud.com/help/en/model-studio/qwen3-5-plus)列出65536输出上限。因此Qwen请求改用max_completion_tokens，不传max_tokens或thinking_budget。请求模式变化后原tokenizer验收身份不再匹配，真实provider/tokenizer验收仍须按新参数完成，不以文档能力说明代替账户实测。

指定simulation Python的本轮非online回归为 **572 passed、1 failed**，17.86秒；唯一失败仍为既有合成词表测试缺少tokenizers。证据为 `results/llm_budget_review_20261016/regression.log` 及同名XML。新增覆盖原8000上限以上输入可用、新上限前/等于/后边界、超限零调用；供应商完整输出参数、截断重试及共同回退回归通过。compileall与git diff --check通过。未安装依赖、未执行真实provider/tokenizer验收。

## 8. 2026-10-29：输入投影与审计

显式记忆动作提示v3、学习动作提示v4、辅助提示v5使用同一知识投影，模型输入不再包含source/review_status；内部KnowledgeCard和完整知识库hash不变。K:registry、cited_evidence与发送knowledge hash仅含实际发送字段，context_hash绑定同一次发送上下文。来源信息通过本地完整bundle追溯，不声称模型见过省略字段。

周反馈输入v4的发送内容保留weeks.values、增加每周reference_fields并去掉重复facts对象。内部facts、原编号及解析边界保持，引用用window_id+":"+reference_field，通知示例保留cost.delivered_notifications。内部packet_hash与实际messages_sha256含义不同：前者关联完整证据包，后者关联真正发送的消息文本。官方token计数仍针对最终实际请求；最新纠错改变输入时重新计数，错误编号不会扩大引用资格。

独立验收从当前已验证知识bundle按发送ID恢复内部卡，核对精简投影、选择和核心卡后重建并逐字比对消息；响应只使用重建后的发送registry解析。旧模板receipt明确不匹配，保留历史文件且不重新签认。离线重渲染报告不能替代服务缓存命中或控制效果验证。

## 9. 2026-10-30：规则维护发送投影v6

仅规则维护提示升级为`cemas-rule_distillation-prompt-v6`。system保留固定说明和返回格式；user按`task_rules / current_rule_set / evidence_bundle`发送，固定知识只在顶层出现一次，bundle仅保留`condition_catalog / weeks / comparisons`。全部当前规则排在动态证据之前；相同知识和规则下，改变本轮证据不改变bundle开始前的发送字节。

模型输入省略bundle的schema_version/public_task_sha256/as_of_day；周记录的case_id/revision/opaque_group和values内重复日期；规则的public_task_sha256/updated_at_day/updated_in_episode/conditions/旧increment；知识卡的version。规则条件定义集中在condition_catalog。规则ID、内容版本、内容、状态、聚合统计、暂停reason，以及周编号、角色、外层日期、公开值、有效性标志、support_window、行动前动作和匹配条件均保留。输出仍为patch v3，schema_version和新操作increment仍按原合同返回。

这些删除只作用于发送层。内部完整packet、规则对象、KnowledgeCard、packet_hash、解析和SQLite事务保持；模型实际看到的消息由现有审计记录，官方计数和纠错均基于最终消息。动作与周反馈的格式、版本及独立动作验收不变；历史运行、冻结库、报告不改写，不自动追加付费测试或训练。

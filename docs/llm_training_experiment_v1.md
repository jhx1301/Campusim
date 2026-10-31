# LLM 三种子学习库实验：准备与运行

更新：2026-10-29。准备命令本身不调用模型；三个种子各32回合已另行授权启动，输入优化按第7节在16回合边界切换。机制合同见[Feedback统一设计](llm_feedback_component_design.md)，实际回合清单和资源检查结果以生成的 `experiment.json` 为准。

## 1. 已确定的实验安排

- 调度种子为11、22、33，各自从空学习库开始，案例、规则及输出目录完全独立。
- 推理强度为11/high、22/high、33/low。种子33的动作、周经验和规则维护统一使用low；输入和总输出上限均保持131072。
- 第一阶段每个种子运行32回合，在16、32回合边界保存冻结副本。
- 第二阶段预先准备另外32回合；是否执行另行决定。执行时沿用原学习库，累计达到64回合，保存64回合冻结副本。
- 每个种子的64回合使用64个不同的 `world_seed`，因此前后两批历史世界不重复。不同种子之间允许使用相同世界。
- 模型参数固定，训练积累公开案例和聚合规则。主配置为 `memory_mode=both`、`feedback_backend=llm`、`rule_memory=adaptive`。
- 沿用已完成的RL baseline产物进行后续比较；本方案不安排baseline训练。

每回合恢复历史快照后，先执行7天统一基线观察，再自主控制112天。总执行119天、17个执行窗口、16次自主决策；观察期不生成算法案例。规则在相对恢复点day35、63、91、119整理，主评分只统计day7–118。

## 2. 场景如何选择

准备程序复用既有 `SnapshotEpisodePlan`，按每个调度种子的原始顺序遍历候选场景，只接受第一次出现的历史世界，收集64回合。选中场景的快照日期、未来分支和资源档位保持调度器给出的值，不另生成一套随机规则。

仍使用固定128个训练世界，以及第21、35、49、63天快照。调度器原有的后期零活动感染过滤继续生效；准备程序不重新运行世界、不修改快照。前32回合和后32回合各自的快照日期、资源档位分布写入准备报告。顺序筛选保证世界不重复，但不承诺各档位数量严格相等。

稳定的 `episode_id` 对应固定场景。续训文件是同一份64回合清单的累计前缀：16回合、32回合、64回合。第二阶段使用64回合文件时，既有完成记录会跳过前32回合，仅训练后32回合；不重新抽样，也不更改已完成回合的编号。

## 3. 服务设置与离线准备

生产设置入口为 [llm_training_settings_v1.json](llm_training_settings_v1.json)，仅保存服务地址、密钥环境变量名称、tokenizer路径和记忆模式，不保存密钥值。模型为DeepSeek `deepseek-flash`，保持thinking启用，输入上限131072、总输出上限131072；输出包含推理和最终回答。种子11、22沿用基础协议的high；准备程序默认以`--low-reasoning-seed 33`为种子33生成单独的low协议、服务设置和tokenizer manifest。官方tokenizer文件不变，low的模板参数和输入身份单独绑定，不覆盖原high资源。

`experiment.json`每个种子条目的`protocol_path`、`settings_path`和`request_parameters`是该组的实际配置，启动及后续冻结评估均应使用对应条目。顶层字段表示基础high配置。三组是混合设置的候选实验，不再是三个同设置重复；种子和推理强度同时变化，不能将组间效果差异单独归因于推理强度。

从仓库根目录执行以下命令只生成准备文件：

```powershell
$python = 'D:\programfile\miniconda3\envs\simulation\python.exe'
& $python -m examples.control_v1.prepare_learning `
    --settings docs/llm_training_settings_v1.json `
    --artifact results/e0_v5_iso0_w1trace/weekly_background_v1_local/control_anchor.json `
    --output results/llm_training_3seeds_v1
```

输出目录必须使用新路径。准备文件包含：

```text
results/llm_training_3seeds_v1/
  experiment.json
  settings.json
  seed11/
    episodes_001_016.json
    episodes_001_032.json
    episodes_001_064.json
  seed22/...
  seed33/...
```

种子33目录另含`low_reasoning/protocol.json`、`base_protocol.json`、`settings.json`及`tokenizer/`。修改推理强度不改变原有16/32/64回合清单和世界顺序。

每个种子的 `learning.sqlite`、`runs/` 和 `frozen_016.sqlite`、`frozen_032.sqlite`、`frozen_064.sqlite` 是计划中的运行产物路径。准备完成不代表这些学习库已经建立或训练已开始。冻结数据库同时生成对应的 `.manifest.json`。

离线准备核对现有校准产物、快照资源、正式tokenizer与当前请求配置的兼容性，并记录实际模型请求参数、场景分布和资源路径。资源检查通过仅说明本地准备完成，不能证明在线服务已接受新输出上限或控制效果达标。

本次准备同时移除了协议文件中新增的secondary输出限额重复校验；数值仍由既有`LLMSettings`在实际使用时检查。协议文件恢复为现有校准产物绑定的原字节，校准产物无需改写，也没有重新拟合。

固定历史快照及其原始身份记录保持不变。准备核对catalog中的校准、回放配方、元数据和文件存在性，并分别保存原catalog身份与当前源码身份。当前`snapshots.py`源码hash与最初生成快照时不同，报告如实记录`snapshot_source_hashes_match=false`；这不重新签发快照身份。大型pkl内容没有在本次准备中逐个重算hash，`snapshot_state_hashes_verified=false`明确表示该检查未执行。

## 4. 授权开训后如何启动

以下命令会真实调用付费服务，只有决定启动实验时才执行。每个种子内部顺序训练，三个种子可以并行；同一密钥可以供三个进程使用，学习库仍然彼此隔离。

先保证新进程可读取系统或用户环境变量 `DASHSCOPE_API_KEY`，不要把密钥写进命令、JSON或日志。单个种子的启动方式为：

```powershell
& examples/control_v1/train_learning_seed.ps1 `
    -Experiment results/llm_training_3seeds_v1/experiment.json `
    -Seed 11 -Until 32
```

该入口在16、32回合边界调用现有 `learn_memory train/freeze`。训练失败或冻结失败即停止，不自动进入下一阶段。动作三次请求均失败时，保留审计并回滚当前回合；已完成回合保留，重新运行同一清单会从完整回合边界恢复。

三个种子并行启动示例：

```powershell
$repo = (Get-Location).Path
$experiment = (Resolve-Path 'results/llm_training_3seeds_v1/experiment.json').Path
$launcher = Join-Path $repo 'examples/control_v1/train_learning_seed.ps1'

foreach ($seed in 11, 22, 33) {
    $seedOutput = Join-Path (Split-Path $experiment) "seed$seed"
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
        -WorkingDirectory $repo `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            ('"' + $launcher + '"'), '-Experiment', ('"' + $experiment + '"'),
            '-Seed', $seed, '-Until', 32) `
        -RedirectStandardOutput (Join-Path $seedOutput 'train_032_stdout.log') `
        -RedirectStandardError (Join-Path $seedOutput 'train_032_stderr.log') `
        -PassThru
}
```

需要追加后32回合时，对应种子使用相同的 `experiment.json` 和 `-Until 64`。继续写原 `learning.sqlite`，不覆盖32回合冻结副本。三个种子分别续训，不能把一个种子的学习库交给另一个种子。

## 5. 运行时需要留存的信息

每回合的既有运行目录保存实际配置、决策、公开执行记录及审计：

- `llm_calls.jsonl`：动作请求与重试、实际输入、用量、耗时和校验错误。
- `feedback_events.jsonl`：周反馈与规则维护的调用、用量、耗时及生成或不可用结果。
- `learning_run.json`、回合完成记录及冻结manifest：场景、配置、续训进度和库身份。

统计应区分动作请求、辅助请求及总请求数，包含失败重试的已报告用量。输出token包括推理；没有返回usage的请求单独计数，不能当成零用量。另检查单次输入最大值、输出截断、重试原因及耗尽次数。训练阶段不能以规则条数、支持次数或置信度上涨代替控制效果验证。

最近一回合真实测试耗时24.27分钟，使用的是65536总输出限额。按此估算，每种子32回合约12.9小时，三个种子串行约38.8小时；并行有望接近单个种子的耗时，但服务排队、重试和学习库增长会影响结果。当前131072总输出限额尚未真实重测，这些时间不包含验证、测试，也不是完成时限。

## 6. 冻结库选择与最终评价

先用同一套36回合验证集评价三个32回合冻结库，按平均控制成本最低选择库，保留三个库各自的验证结果。每组评价使用其训练时的推理强度和对应配置，最终选择的是“推理配置＋冻结库”的组合。验证只读冻结库，临时周经验只在当前评估回合内使用，不回写案例或规则。

是否评价16回合副本、是否统一追加到64回合，依据验证集和训练成本决定。三个32回合库完整验证需要108个评估回合；再评价三个16回合副本则合计216回合，不包含在训练耗时估算内。

正式测试在库和方案确定后执行：20个测试世界 × 4个快照日期 × 3档资源 × 2个未来分支，共480回合。不得用测试结果挑选库或决定追加训练。所有比较方法使用相同快照、未来分支、资源和共同观察流程。评价结果按112天控制期统计，同时保留全程账和观察期成本。

准备命令不启动训练或评估；实际训练的授权与输入协议切换见下一节。本轮不额外启动验证或测试集。

## 7. 第16回合输入协议切换

本轮已授权三个种子各完成前32回合。输入优化在隔离工作目录实施，不热改旧训练源码。先暂停外层PowerShell监督进程，保留Python子进程继续到16回合，防止监督进程自动启动旧版后半段；各组正常退出并由完成表确认16回合后，结束旧监督进程，保存并核对16回合冻结副本。若前半段失败，保留审计并按完整回合边界恢复，不把失败视为16回合完成。

新版离线验证通过后，沿用原学习库、稳定episode_id和原32回合清单，从新版代码目录继续17–32回合；已完成回合由完成表跳过。11/22使用high、33使用low，token限额、任务、观察、反馈频率和规则机制保持。切换记录应包括旧/新代码与提示版本、库路径和第17回合生效位置，不额外启动验证或测试集。

最终产物明确标注“前16回合旧输入协议、后16回合新版输入协议”，不能作为全程同协议重复实验描述。输入改动为固定知识前置、周反馈不重复发送facts数值、知识卡省略source/review_status；完整溯源仍在本地，历史日志不改写。离线报告记录重渲染前后token和公共前缀，真实缓存命中与费用从后续已授权调用审计读取，不承诺固定命中率提升。

本次运行的切换配置为`results/llm_input_optimization_v1/experiment_after16.json`，状态为同目录`switch_status.json`；每组后半段使用原学习库，新增审计写入其`runs_optimized/`，标准输出及错误写入`train_017_032_stdout.log`和`train_017_032_stderr.log`。各组在完成16回合且新版离线验证通过后分别续训，不必等待其他种子。原checkout源码在全部旧Python进程退出后才同步，避免旧进程惰性导入新版模块。

对每种子首个已完成回合的105次历史请求进行官方tokenizer离线重渲染：输入合计从1108421降至897326，减少19.04%；动作减少5.16%、周反馈56.55%、规则维护8.56%。这是特定公开样本的输入量对比，不包括新模型输出，也不是缓存命中率或费用节省保证。

## 8. 后续规则维护输入v6

后续新启动的运行使用规则提示`cemas-rule_distillation-prompt-v6`：固定知识、全部当前规则先发送，动态证据包仅含条件目录、五周记录和比较结果；任务hash、输入schema、案例定位、维护时间等程序字段及重复条件/日期不再发送，知识卡再省略version。完整字段合同见[统一设计第7节](llm_feedback_component_design.md#7-输入渲染与固定前缀)。动作和周反馈保持既有输入协议与提示版本，规则输出和学习库schema不变。

v6不追溯修改本轮前32回合的实际协议。原始审计、16/32回合冻结副本及上述离线报告保留，新的离线对比单独保存；真实缓存变化只能从后续获准运行的v6调用审计确认。本次实现与离线验证不启动新训练或付费调用。

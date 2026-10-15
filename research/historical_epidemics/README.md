# 历史疫情数据调研与验证资料

核查与整理日期：2026-10-15。本目录将公开历史聚合数据整理成统一观测长表、历史事件、人口和机构表，并提供 CEMAS 读取接口。完整选型分析见[主调研报告](reports/campus_epidemic_data_review.md)及其四个分册。

当前交付 **85 条来源目录、40 个观测数据集、2,007,056 条观测行**。观测行按“指标×人群×时间”计数，**不是感染人数或独立疫情数**。40个数据集来自8组一般观测提取和32个CSDH州/学校或学区文件；CSDH的32个文件不等于32个州。Florida文件的部分源年份存在疑点，已标记，不能直接用于日历对齐。

## 目录与维护入口

本任务的来源、报告、数据、准备代码和测试集中在本目录，可独立进行离线构建。它是独立的数据调研任务，与控制协议 v1 开发分开维护。

```text
historical_epidemics/
├── README.md                 # 唯一总入口与运行方法
├── sources/
│   ├── records.json          # 85条来源的唯一维护入口
│   ├── catalog.csv           # 从records.json生成，供筛选
│   ├── manual_context.json   # 人工核查的历史事件与人口输入
│   └── evidence/             # 原始调研证据与早期笔记
├── reports/                  # 主报告与四个专题分册
├── data/
│   ├── raw/                  # 原始下载，保持字节不变
│   ├── observations/         # 40个规范化观测表
│   ├── catalog.json          # 实际已整理数据集的机器目录
│   └── ...                   # 下载清单、上下文表、校验结果
├── scripts/                  # 获取、解析、规范化、构建与核验
└── tests/                    # 格式解析及数据准备测试
```

新增或订正来源时编辑 `sources/records.json`，补充事件或人口时编辑 `sources/manual_context.json`，随后运行 `build` 和 `verify`。`sources/catalog.csv` 是生成视图，不手工维护；`data/catalog.json` 是40个实际数据集的目录，与85条候选来源清单用途不同。报告和证据用于阅读、追溯，不再作为构建输入。`records.json` 的 `review_file` 路径相对本目录。

系统侧保留两个连接点：[读取接口](../../cemas/historical_data.py)和[接口兼容性测试](../../tests/test_historical_data.py)。调用接口不变；默认数据位置已指向本目录的 `data/`。单独复制本目录后仍可用准备脚本离线重建；CEMAS读取需要原项目环境。

## 数据入口

| 文件 | 内容 |
|---|---|
| [catalog.json](data/catalog.json) | 系统目录：数据集ID、文件、实际日期、指标、人群数量、SHA-256、许可和范围 |
| [dataset_index.csv](data/dataset_index.csv) | 可在Excel筛选的40个数据集索引，UTF-8 BOM |
| [sources/records.json](sources/records.json)、[CSV](sources/catalog.csv) | 85条广泛调研来源；保留公开、受限、仅图表、仅接触等访问说明，不能等同于85套已下载观测 |
| [download_manifest.json](data/download_manifest.json) | 每个原始下载的URL、获取时间、响应状态、字节数和SHA-256；包括获取失败与跳转记录 |
| `data/observations/*.csv.gz` | 分数据集压缩长表；每个值都带来源URL、字段/单元格定位及原始字符串 |
| [events.csv.gz](data/events.csv.gz) | 336,966条历史措施/教学状态记录，含15条逐项核查的校园/上海事件；大部分是CSDH按期状态，不能当作同等数量的独立政策变化 |
| [populations.csv.gz](data/populations.csv.gz) | 322,239条分母记录，含10条人工核查的机构/研究队列/普查分母；同一机构跨期重复记录不能相加 |
| [entities.csv.gz](data/entities.csv.gz) | 29,215个CSDH机构键、名称、学校/学区层级及原始NCES ID；不是个体成员表 |
| [quality_issues.csv.gz](data/quality_issues.csv.gz) | 8处隔离记录：7个原始日期逆序行和1个非数值病例单元格；原始文件保留以便复核 |
| [manual_context.json](sources/manual_context.json) | 逐条人工核查的历史事件/人口及原文定位，是生成上下文表的输入 |
| [verification_summary.json](data/verification_summary.json) | 对实际文件重新计算的校验结果；不是只检查清单存在 |

## 已整理的场景与范围

| 数据集ID | 已读取覆盖 | 数据类型与范围 | 措施、人口和ABM适用性 |
|---|---|---|---|
| `bigten_raw` | 2020-03-14—12-20；每校不同 | 14校原始不规则日期的累计病例、累计测试；含71个缺测测试值 | 需接同校公告和人口。可检查累计轨迹；不做每日差分，不使用前向填充表。[源](https://github.com/wadefagen/college-covid19-dataset) |
| `uw_madison_2020` | 2020-08-17—12-31，137日 | 学生/雇员校内阳性与测试；548行 | 可配本目录历史事件和分层人口；优先校园候选。缺同期实测接触网络。[官方日表](https://covidresponse.wisc.edu/dashboard-2020/) |
| `uw_madison_2021_spring` | **2020-08-07—2021-05-09**，276日 | 官方“2021春”页面的实际日表会追溯2020年；校内/校外、学生/雇员；1,656行 | 与2020快照重叠且可能有回填，保留两个版本，不相加。[原表](https://covidresponse.wisc.edu/dashboard-2021-jan-may/) |
| `tianjin_2014` | 2014-10-26—12-27，63日 | 一校一次暴发，发病日ILI，63行 | 可做短期症状曲线验证；不是4校三年、不是实验室确诊感染，无完整检测分母。[论文/S1](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184527) |
| `cambridge_2020` | 大学cohort周10/05—12/06；社区周09/21—12/27 | 9个论文Figure2c上区cohort周合计＋14个Cambridgeshire社区周，共23行；两人群分开 | 只转换聚合面板，不导入个体/样本工作表。大学值是特定图表cohort统计，不保证全校园完整病例；周区间不能转成每日真值。[论文与Source Data](https://www.nature.com/articles/s41467-021-27942-w) |
| `shanghai_2022` | 2022-03-19—06-26，100日 | 两个作者定义片区的有症状＋无症状报告病例；200行 | 有片区人口和3阶段历史事件；非校园，作者片区不等于单一行政区，无检测量。[作者CSV](https://github.com/junlingm/Shanghai-COVID-19-Mar-June-2022) |
| `nyc_daily` | 2020-02-29—2025-10-13 | 全市和5行政区的确诊、疑似病例、按入院日住院病例、死亡；49,296行 | 适合城市/社区多结局验证。不是大学数据；各指标日期含义不同，末7日原始非布尔标记保留。[官方数据](https://github.com/nychealth/coronavirus-data) |
| `italy_national` | 2020-02-24—2025-01-08 | 全国病例、累计死亡、在院/ICU存量、新ICU入院、累计检测/受检者；16,029行 | 适合全国聚合及医疗结局；早期检测字段缺失保留，原始修订不强行调平。[官方DPC](https://github.com/pcm-dpc/COVID-19) |
| `csdh_cases_*`，32份 | 原文件2020–21学年统计；每州/层级独立日期见catalog；Florida需复核 | 学校/学区新增、累计、active及14日窗口病例；保留学生/员工/合计/未知分类 | 以NCES键配教学、口罩和登记人数。报告周期、隐私抑制和日期疑点不同，不能无条件合并。[CSDH方法](https://www.covidschooldatahub.com/methods) |

## 在系统中直接使用

从仓库根目录执行；使用现有Python环境和pandas，没有新增依赖。

```python
import cemas as ce
from cemas.historical_data import list_datasets, load_observations, to_covasim_data

datasets = list_datasets()  # 40条，包含每个文件的日期/指标/校验值

long_table = load_observations(
    "uw_madison_2020",
    entity_id="university_uw_madison",
    population_group="students",
    observation_scope="on_campus_testing",
)

wide = to_covasim_data(
    "uw_madison_2020",
    entity_id="university_uw_madison",
    population_group="students",
    observation_scope="on_campus_testing",
    metric_map={
        "new_positive_tests": "observed_positive_tests",
        "new_tests": "new_tests",
    },
)
system_data = ce.load_data(wide, calculate=False, verbose=False)
# system_data为137日，包含来源表中的3704次阳性和136584次测试。
# observed_positive_tests是自定义观测列；只有确认定义匹配时才显式映射成new_diagnoses。
```

`to_covasim_data()`要求明确指定机构、人群、观测范围及指标映射，返回系统已有`load_data()`可接受的DataFrame。它不会补零、插日期、拆分周数、差分累计、重置累计基线或自动把阳性检测当感染/诊断。重复点、周区间和已标记的源日期疑点会拒绝自动对齐；完整原值仍可用`load_observations()`检查。文件校验默认开启。

上下文表是普通压缩CSV，可直接用已有pandas读取，再按机构键及**明确的时间范围和定义**连接：

```python
from pathlib import Path
import pandas as pd

base = Path("research/historical_epidemics/data")
events = pd.read_csv(base / "events.csv.gz", keep_default_na=False)
population = pd.read_csv(
    base / "populations.csv.gz",
    dtype={"entity_id": str, "raw_value": str},
    keep_default_na=False,
)
entities = pd.read_csv(base / "entities.csv.gz", dtype=str, keep_default_na=False)
```

学校与学区使用不同键，不能把一个学区病例复制到每所学校，也不能把学校和所属学区汇总相加。NCES数值ID按标准7位学区/12位学校补前导零，原始字符串保留。无NCES键时使用来源名称组合生成的稳定键，**不声称能够跨来源匹配**。学校病例、教学模式、口罩和人口文件的州覆盖不完全相同；没有匹配记录代表缺失，不能补作无措施或零人口。

## 字段与质量规则

观测列为`dataset_id,entity_id,population_group,observation_scope,date_start,date_end,time_basis,frequency,metric,value,unit,quality,source_id,source_url,source_locator,raw_value`。每个数据集的实际指标及定义见`catalog.json`。

- 日点保留原日期；区间保留起止。累计与active存量用原报告区间的终点，并在`source_locator`保留原区间。未将其解释成日新增。
- `value`为空时不是零。119,155条CSDH受抑制/区间记录保留原字符串，例如`16+`或`35 to 39`，不取中点、不展开为个人病例。普通缺测也保留，不凭其他表编造数值。
- `population_group=combined`是源合计，不能再加学生和员工。Wisconsin用源表`employees`，CSDH用`staff`，没有自动跨源认定相同人群。
- 人口表中的登记人数、受检队列、全市普查及员工计数定义分别保留；部分员工数为小数，不能未经字典核对就当独立自然人数或测试分母。跨期重复值不是独立人口。
- 事件表记录公告/回顾性历史事实或按期状态。未知公告/生效/结束日留空；“至少两周”不自动算成确定解除日。Wisconsin9/9公告、9/10暂停面授、9/14远程授课开始分别保存。
- 各序列保留来源许可说明。公开网页不自动等于公共领域；研究引用与再分发按原来源条件办理。

## 已发现并保留的具体差异

1. **Wisconsin2020日表与页脚不同**：137日日表学生合计为3,704阳性/136,584测试；同页页脚为3,711/136,826，差7/242。已逐单元格对照原HTML，未发现解析漏行；原因未由本次证据解释。没有缩放或补造缺失日以强行配平。
2. **Florida源年份疑点**：CSDH 2020–21包中Florida文件把部分1–5月区间写成2020年，包含2020-02-29。保留原日期并加`source_date_review_required`，不擅自改为2021年或重写闰日。该数据可读取检查，但相关系列不能自动导出为日历验证表。精确位置见原ZIP内`CSDH_FL_COVID_Schools.csv`。
3. **纽约原始标记**：末7日`INCOMPLETE=61030`，不是只含0/1。规范化后保留`source_incomplete_flag=61030`，本轮不推测编码含义；尾部观测不应当作最终完整值。
4. **获取状态**：Illinois K–8两个下载端返回403，Duke旧fall tracker实际跳转大学新闻主页。这些列为候选/访问问题，未冒充已整理的数据集。部分大型跨校CSV同样仍需完整获取。
5. **重复来源**：Big Ten内的UW片段与UW官网快照可能共享同批观测，两个UW快照还互相重叠；它们不能充当独立重复验证。Cambridge大学与社区也不合计为“大学病例”。

## 复现与校验

```powershell
# 从项目根目录运行。单独复制任务目录时，可在该目录使用 scripts/prepare_historical_epidemics.py。
# 完全离线：从已保存原始文件和结构化来源重建全部观测、上下文和目录
& 'D:/programfile/miniconda3/envs/simulation/python.exe' research/historical_epidemics/scripts/prepare_historical_epidemics.py build

# 完全离线：重算原始/规范化/上下文哈希，检查每行来源、日期、数值和行数
& 'D:/programfile/miniconda3/envs/simulation/python.exe' research/historical_epidemics/scripts/prepare_historical_epidemics.py verify

# 可选联网：只重取缺失/不匹配的公开文件；不会把访问失败写成已成功
& 'D:/programfile/miniconda3/envs/simulation/python.exe' research/historical_epidemics/scripts/prepare_historical_epidemics.py fetch

# 数据准备测试与系统兼容性检查
& 'D:/programfile/miniconda3/envs/simulation/python.exe' -m pytest research/historical_epidemics/tests tests/test_historical_data.py tests/test_cemas_import.py -q
```

构建仅依赖本目录的原始下载、`sources/records.json`、`sources/manual_context.json`与下载清单；准备脚本只用Python标准库。此前两套来源清单已合并；重复生成器和目录视图已移除，原始专题证据保存在 `sources/evidence/`。Notre Dame重建数据和控制协议保持原状。此交付不包含参数拟合、仿真结果或现实防控方案。

本目录的 `.gitattributes` 禁止对 `data/raw/` 自动转换换行，保证Git提交及克隆后的原始快照与下载清单中的SHA-256一致。

离线核验结果见 `data/verification_summary.json`；收拢前后数据一致性见 [consolidation_verification.json](sources/evidence/consolidation_verification.json)。真实Wisconsin表可通过现有`cemas.load_data()`导入；周区间、源日期疑点、缺测及抑制值的行为均有检查。

收拢验证：63个保留的数据及输入文件SHA-256一致，85条来源记录完整保留，41项相关测试通过。仅复制输入与脚本到临时目录、使用 `python -I -S` 禁用第三方包后，离线构建与核验仍通过，输出与收拢前一致。

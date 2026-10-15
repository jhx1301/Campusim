# 补充目录：校园存档、政策时间线与人口分母

核查日期：2026-10-15。与[总报告](campus_epidemic_data_review.md)配套阅读。下列“适用性”是本次调研判断；公开数据所支持的事实分别链接原始机构、数据编制者或论文。除明确写出实际读取的文件外，网页有下载入口不代表本轮已经下载完整文件。

## X01．University of Wisconsin–Madison 官方历史仪表板

- **范围与时间**：单所大学的学生和雇员，校内检测及部分校外报告。官方[学期存档索引](https://covidresponse.wisc.edu/dashboard/)列出 Fall 2020 至 Fall 2022；[2020 原始页面](https://covidresponse.wisc.edu/dashboard-2020/)直接保留 **2020-08-17—2020-12-31** 的每日表格。实际下载解析确认，[2021 春页面](https://covidresponse.wisc.edu/dashboard-2021-jan-may/)虽以Jan–May命名，其276日结果表追溯至 **2020-08-07—2021-05-09**。两个快照分别保存，不相加；其他学期首尾仍需分别核对。
- **数据类型与访问**：HTML 表格 `Testing Results By Day`，分学生/雇员给出阳性检测、总检测及阳性率；无需从图片反读。校内检测之外的病例另有图表；官方说明校外仅采集阳性者的 UW 身份，所以没有对应的校外总检测量。页面把部分校外结果按收到日期计数，不能与采样日期直接混用。[口径原文](https://covidresponse.wisc.edu/dashboard-2020/)
- **措施时间线**：与官方新闻拼接。**2020-09-09** 公告安排09-10起暂停相关面授、09-14起远程至少两周；两座宿舍检疫则当晚当地22:00开始。公告日与实施日分别进入事件表。[当日公告](https://news.wisc.edu/university-shifts-to-two-weeks-remote-instruction/)
- **人口与结构**：2020 秋注册学生 **45,540**，本科 **31,650**，研究生/特殊及专业学位学生 **13,890**；2020 教职员工 **23,917**。这些是机构登记分母，不等于每日实际在校、接受筛查的人数；学生雇员也不能未经去重就相加。[2021 年 1 月官方 Fact Sheet](https://profs.wisc.edu/wp-content/uploads/2021/09/UW-Madison-Fact-Sheet-2021.pdf)
- **额外口径核查**：2021 春仪表板给出的雇员分母为 **19,225**，与上面 Fact Sheet 的 **23,917** 不同；不能擅自假定两者可替换。该页面还保留隔离/检疫床位占用及疫苗概览，但概览快照不自动等于可下载的每日完整序列。[仪表板分母和占用说明](https://covidresponse.wisc.edu/dashboard-2021-jan-may/)
- **ABM 适用性：高，限于观测到的阳性检测与检测量。** 优点是官方原始日表、角色分层和明确的历史事件可以配套；不足是缺少同期公开接触网络和每日风险人口，校内/校外报告时钟不同。未发现校内住院日序列。值得优先作为单校历史验证候选。
- **已落地与差异**：本地[数据包](../README.md)保存两版规范化日表。2020版137日学生合计为3,704阳性/136,584测试，源页脚为3,711/136,826；逐单元检查未发现解析遗漏，差异原因未解释，不作数值配平。

## X02．UC Davis / Healthy Davis Together：校园—城市配对候选

- **范围与时间**：校园与 Davis/Yolo 社区是相关但不同的人群。UC Davis 官方对 Healthy Davis Together 研究的说明列出 **2020-11-18—2022-02-23** 社区检测统计窗口；这不是本轮取得的完整校园逐日文件。[研究及项目说明](https://www.ucdavis.edu/health/covid-19/news/healthy-davis-together-prevented-infections-hospitalizations-and-deaths)
- **数据类型与当前访问**：[现有大学 dashboard](https://campusready.ucdavis.edu/testing-response/dashboard)已主要展示**校园污水监测**，并外联 Healthy Central Valley Together 的周边城市污水数据。不要把目前页面误记为仍提供 2020—2022 临床病例 CSV。临床历史资料可追论文、项目报告与州/县门户，尚未在本轮确认完整校园日表下载。
- **措施时间线**：大学保留[疫情第一年时间线](https://www.ucdavis.edu/coronavirus/news/pandemic-1-year-getting-through-together)、[2021 秋返校规划](https://www.ucdavis.edu/coronavirus/news/fall-2021-campus-planning-update-chancellor-and-provost)、[2020-11-13 检测要求公告](https://www.ucdavis.edu/news/checking-chancellor-may-testing)、[取消常规检测要求公告](https://www.ucdavis.edu/news/covid-19-testing-no-longer-required)。这些是历史背景证据，不应将“公布规划”当成全部人员实际执行的日期。
- **人口与结构**：需配同年的大学统计和 Yolo/Davis 人口；无同期完整公开接触网络。大学明确校园阳性检测向州报告、可进入 Yolo 县统计，而其他提供者检出的结果可能按居住县进入统计。[数据归属说明](https://campusready.ucdavis.edu/testing-response/dashboard)
- **ABM 适用性：中。** 适合校园—社区多来源一致性研究与额外观测验证；若以病例曲线为目标，需先确认历史文件。优点是项目、政策、社区与污水背景丰富；不足是人群交叠、重复计数和观测类型变化。大学医院 CORDS 含受保护医疗信息，**不是匿名开放下载数据**，需要机构资格和数据使用协议。[UC Davis Health 访问说明](https://health.ucdavis.edu/data/covid-19.html)

## X03．New York Times 美国高校病例汇总

- **范围与时间**：2020-21 学年对 1,900 多所高校的滚动调查，**2020-07—2021-05**；最终更新 **2021-05-26**。[数据编制者方法说明](https://github.com/nytimes/covid-19-data/tree/master/colleges)
- **数据与下载**：[colleges.csv 直接入口](https://raw.githubusercontent.com/nytimes/covid-19-data/master/colleges/colleges.csv)，字段包含 `date,state,county,city,ipeds_id,college,cases,cases_2021,notes`。`date` 是最后更新日；`cases` 是累计报告病例，`cases_2021` 为 2021 年以来累计。
- **措施时间线/人口/网络**：不含措施、检测分母或接触网络；`ipeds_id` 可连接 IPEDS。同一校可能包含医院/医学院或多个校区，需读 `notes`。[README](https://raw.githubusercontent.com/nytimes/covid-19-data/master/colleges/README.md)
- **ABM 适用性：仅终点和覆盖范围核对，不适合作为逐日曲线验证。** 编制者明确**不发布历史病例时间序列**，也不建议直接跨校比较。不能通过 Git 历史快照差分宣称恢复了真实 daily cases。优点是范围广、机构标识清楚；不足是异质口径、漏报、累计快照及缺少检测量。学术使用需遵守署名及非商业许可。[许可说明](https://github.com/nytimes/covid-19-data/blob/master/LICENSE)

## P01．Oxford COVID-19 Government Response Tracker（OxCGRT）

- **范围/时间/数据**：国家和部分次国家层级，覆盖 **2020—2022**；[最终 v1 数据与文档](https://github.com/OxCGRT/covid-policy-dataset)含 CSV，建议从 `compact` 与带来源注释的 `fullwithnotes` 版本选用。不同地区覆盖完整性和指标版本不同。
- **措施时间线：有。** 包括学校关闭、检测、接触追踪、口罩、疫苗及其他政策，注释字段可回溯来源。[代码本](https://github.com/OxCGRT/covid-policy-dataset/blob/main/documentation_and_codebook.md)
- **ABM 用途与优缺点**：适合补充所在州/国家历史背景；不含校园病例、机构人口或接触网络。政策指数记录的是规则强度，**不能代表某所高校实际执行、依从性或效果**。`STATE_TOTAL`、`STATE_WIDE` 等辖区语义不同；疫苗状态差异也会改变指标含义。优点是结构统一、出处丰富；不足是校园粒度缺失。许可 CC BY 4.0。[方法与限制](https://github.com/OxCGRT/covid-policy-dataset)

## P02．UNESCO 全球学校关闭与复课数据

- **范围/时间/下载**：教育系统层面的国家/地区状态，**2020-02—2022-06**，官方页面提供[历史地图与数据入口](https://www.unesco.org/en/covid-19/education-response)，UIS 保留[Excel 下载及方法文件入口](https://covid19.uis.unesco.org/global-monitoring-school-closures-covid19/)。本轮确认入口，二进制文件未完整核验；部分旧下载链接经浏览工具不可取。
- **数据与措施时间线**：按日记录学校关闭、开放及授课状态；不含病例、阳性检测或住院。所引 2021-11-30 方法说明的关闭状态和受影响学生分母为 **ISCED 0–3（学前至高中）**，不能据此认定某所高校的复课日期。
- **ABM 用途与优缺点**：适合国家教育背景、学期情景核对；不等于某校实际到校率或高校独立决策。需要人口分母及本地教育部门/大学公告。优点是全球覆盖；不足是聚合层级较粗，不能单独校准或验证疫情曲线。[方法说明](https://www.unesco.org/sites/default/files/medias/fichiers/2022/10/en_methodological_note_-_unesco_map_on_covid-19_caused_school_closures_and_re-openings_rev_mp.pdf)

## P03．CoronaNet 政策事件数据库

- **范围/时间/访问**：[项目当前主页](https://coronanet-project.org/)说明主要覆盖 **2020-01—2021-12**，包含国家和大量省市政策事件；数据收集已结束，仍在清理整合。不要把旧主页残留的“每周更新”当作当前状态。[原始政策记录仓库](https://github.com/CoronaNetDataScience/corona_tscs)含按国 CSV、批量压缩数据和字段说明。
- **数据与措施时间线：有。** 区分 `date_announced`、`date_start`、`date_end`，并记录政策类型、对象、范围、来源链接；具体文件与国家的起止范围须以实际记录为准。[字段字典](https://github.com/CoronaNetDataScience/corona_tscs#coronanet_releasecsv-field-dictionary)
- **ABM 用途与优缺点**：适合补历史事件及其原始出处，无校级人口、接触网络或完整检测序列。相比综合指数，事件文本更便于核对公告与生效日期；不足是国家和地区采集不均、结束日期缺失以及修订记录可能重复。只能补背景，不能单独验证病例曲线。

## P04．HIT-COVID 历史公共卫生事件数据库

- **范围/时间/数据**：从 **2020-01-01** 起追溯国家、州省和部分地方政策；[作者维护仓库](https://github.com/HopkinsIDD/hit-covid)提供 `hit-covid-longdata.csv` 和 `hit-covid-completeness.csv`，可从[数据目录](https://github.com/HopkinsIDD/hit-covid/tree/master/data)下载。**最终覆盖结束日期和选定地区连续性，本轮未读取全表核定**。
- **措施时间线：有。** 记录政策变更日期、适用子人群、是否强制、来源 URL，并有独立完整性表。[原始论文与数据可得声明](https://pmc.ncbi.nlm.nih.gov/articles/PMC7453020/)
- **ABM 用途与优缺点**：适合核对隔离/检疫、检测和授课相关历史规则，需外接真实病例及人口。优点是来源记录和完整性标记；不足是志愿采集覆盖不均，记录时间、实施时间、修订时间需要区分。无同期校园接触网络，不能独立验证病例曲线。

## P05．Google COVID-19 Community Mobility Reports

- **范围/时间/下载**：2020 年起的国家、部分州省/县级聚合移动趋势，官方于 **2022-10-15** 停更并保留历史文件。[官方页面及 CSV 入口](https://www.google.com/covid19/mobility/)
- **数据与措施时间线**：工作场所、居住、交通、休闲等地点类别相对基线变化；不记录措施本身、病例、检测或住院。不含可识别个人的位置、接触或轨迹。[方法说明](https://support.google.com/covid19-mobility/answer/9824897?hl=en)
- **ABM 用途与优缺点**：可作为社区行为变化的外部一致性证据；**不是人数、到课率或接触网络，不能直接把某百分比变化当作校园接触率变化**。优点是可公开下载且覆盖广；不足是选择偏差、隐私抑制、基线与地点分类变化。无独立人口分母，不能单独验证传播输出。

## P06．NCES IPEDS：美国高校人口与结构分母

- **范围/时间/访问**：美国高校按学年/年度统计，可匹配 2019、2020、2021 等疫情学年；[官方 2020 全量数据文件页](https://nces.ed.gov/ipeds/datacenter/DataFiles.aspx?gotoReportId=7&year=2020)提供 ZIP/CSV 与字典。本轮检索索引可读，部分直接页面抓取超时；未核验全部下载文件。
- **数据类型**：`EF2020A` 为学生层级、全日/非全日、性别及族裔；`EF2020B` 为年龄；`EF2020A_DIST` 为远程教育状态，其他模块包含人力资源和机构特征。主键 `UNITID` 可与多校数据的 IPEDS ID 对接。[官方字段/文件目录](https://nces.ed.gov/ipeds/datacenter/DataFiles.aspx?gotoReportId=7&surveyNumber=2&year=2020)
- **ABM 用途与优缺点**：人口规模与人群结构补充，**不含病例、接触网络或逐日措施**。优点是机构标识稳定、分层清楚；不足是注册学生不等于当日到校或受检测群体，秋季人口和全年去重人口也不相同。注册人数不应直接替代校内筛查分母。

## P07．美国 Census / ACS：校园周边社区人口

- **范围/时间/访问**：可选择 **2019 或 2020 等历史年份**的 ACS 与 2020 Census，含州、县、城市、tract 等地理层级；可经官方整表下载及 API 取数。[ACS API 目录](https://www.census.gov/programs-surveys/acs/data/data-via-api.html)、[2020 历史版本和地理说明](https://www.census.gov/data/developers/data-sets/acs-5year.2020.html)
- **数据类型**：年龄、性别、家庭/住房及集体宿舍等；2020 Census DHC 包括大学学生住房等 group quarters。[DHC 官方说明](https://www.census.gov/data/tables/2023/dec/2020-census-dhc.html)
- **ABM 用途与优缺点**：适合大学所在县/社区的人口与结构分母，无疫情时间线、措施或实测接触网络。优点是标准地理编码便于连接卫生数据；不足是 ACS 五年估计是跨年窗口，并非某个疫情日快照，误差与地理边界版本需保留。**截至本轮官方页面，数据 API 查询要求 API key**；公开整表下载仍可作为替代。[当前 API 要求](https://www.census.gov/data/developers/data-sets/acs-5year.2020.html)

## 未列为开放下载数据：College Crisis Initiative（C2i）

C2i 的 2020—2021 高校教学模式/检测政策曾用于多项研究，但“论文分析了它”不代表该微观数据可自由取得。公开研究仓库明确说明 `campus_covid_status.csv` 使用受到许可限制，需取得 C2i 授权。[作者仓库访问声明](https://github.com/jkbren/campus-covid#college-crisis-initiative-c2i-data)

可公开引用的例子是 CDC 对 2021 春 **1,849 所高校**按教学模式区分检测协议的[汇总统计](https://stacks.cdc.gov/view/cdc/105173)。汇总图表不应冒充逐校逐日的完整政策数据库；本次将 C2i 放在受限线索中，不计为已经取得的公开验证数据。

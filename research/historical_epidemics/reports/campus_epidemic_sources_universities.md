# 高校历史疫情数据目录：公开统计、政策记录及可复现性核查

检索与访问核查日期：2026-10-15。范围以美国高校 COVID-19 历史资料为主，包含 **14 所高校来源和 2 个跨高校数据仓库，共 16 项**。一所高校的 dashboard、官方新闻和论文合并为一项，避免把同一批疫情数据重复计数。本文只收录公开汇总统计，不把论文开放代码、模拟输出或受限个体数据等同于公开实测数据。

系统整理阶段已将Big Ten原始表及Wisconsin官方日表保存并规范化，连同Cambridge聚合面板等进入[可直接读取的数据包](../README.md)。下文未取得文件的候选仍保持原访问限制；新的实际文件状态以数据包清单为准。

访问等级：**A**＝已读取机器表格并检查字段/日期；**B**＝官方仍提供历史数据或导出入口，但本次未完整导出；**C**＝可以阅读论文图表、官方逐期简报或历史说明；**D**＝发现历史入口，目前无法取得可验证的数据主体。等级描述的是本次可取得性，不代表研究质量。“措施时间线有”包括可以另接官方历史公告，未必已整理成日期 CSV。

## 1. 快速对照

| 编号 | 来源与范围 | 已核实覆盖期；粒度 | 数据类型与当前取得方式 | 措施时间线 | ABM 验证适用性 |
|---|---|---|---|---|---|
| U01 | Campus COVID Data，跨美国高校 | 仓库定位为 fall 2020；完整文件首尾日待核实；原始日/周报告混合 | 测试、病例，CSV；23.4 MB 主文件存在，完整读取未成功 | 另接大学官方公告；C2i 政策文件使用需授权 | 有条件，适合跨校汇总验证；不能直接假设全校口径一致 |
| U02 | College COVID-19 Dataset，14 所 Big Ten 高校 | 原始文件总体 **2020-03-14—12-20**；各校不同 | **A**：原始累积病例和测试 CSV；另有前向填充日表 | 无，另接官方公告 | 较适合建立 2020 秋季可复现的多校园基准；有采集与口径误差 |
| U03 | UIUC，Urbana-Champaign 校园 | 论文核心 **2020-08-15—12-23**；独立 CSV **2020-07-06—12-19** | **A/C**：累计测试、累计病例 CSV；官方聚合 dashboard、论文及补充材料 | 有，官方 Massmail Archive | 较强；检测分母清楚，人口及秋季时间背景丰富；公开个体接触网络未发现 |
| U04 | Ohio State，各校园/学生检测及 Ohio 背景数据 | 官网归档至 **2022 春季末**；常规检测始于 **2020-08-08**；日，低量时周 | **B**：官网历史 dashboard 与 Excel 下载入口；学生阳性、总测试、阳性率 | **有，同页给检测/返校/授课时间线** | 较强；注意学生数据和州住院容量不能混作校园结局 |
| U05 | Duke，在 Durham 的本科及研究生 | MMWR **2020-08-02—10-11**；另核实 **2021-01-18—24** 周简报 | **C**：分检测类别总数、阳性、累计曲线；官方周统计文章 | 有，论文及官方公告 | 较适合有限窗口的汇总验证；尚无已核实连续开放日 CSV |
| U06 | Cornell，Ithaca 校园 | 2020-08-25 启动日 dashboard；论文研究 fall 2020，后续有 2021 分析；完整日表首尾待核实 | **C/D**：官方历史说明、论文和 SI 中公开聚合；原检测记录不开放 | 有，官方重启说明、论文 | 有条件；公开模型代码不是实测原始数据 |
| U07 | Notre Dame，Indiana 中型寄宿大学 | MMWR **2020-08—10**，图示至 10 月；诊断病例日曲线、检测分类图 | **C**：CDC 图表及大学官方历史说明；旧 HERE dashboard 本次不可取 | 有，8/19 线上、9/2 起分阶段返课 | 较适合一段明确定义的历史事件验证；图表数字化需要记录误差 |
| U08 | Michigan，UHS/校园公开统计 | U02 中实际 **2020-03-14—12-19**；原报告频率不齐 | **A/B**：第三方保存 CSV；官方 Tableau 页可读说明，但本次未导出 | 有，官方公告可另接 | 有条件；早期 UHS 就诊人群与后期校园筛查人群应分段 |
| U09 | Yale，Yale Health 就诊及筛查人群 | 启动版明确 **2020 年 3 月初—7 月中**；周更新；后续完整历史范围待核实 | **C/D**：官方说明中病例/测试及有症状/无症状分层；旧 dashboard 本次不可取 | 有，2020 秋返校官方说明 | 有条件；退休者和家属也在早期分母内，不能当作在校学生总体 |
| U10 | Harvard，获准到校的学校成员 | **2020-09-03** 官方证实按日 dashboard；全序列首尾待核实 | **C/D**：日筛查数据的官方存在性证据；本次无完整导出 | 有，9 月自采检测转型和秋季远程教学公告 | 目前偏资料线索；恢复数据后才适合日级验证 |
| U11 | UC San Diego，学生及 general campus 员工 | 至少 fall 2020 起的临床统计有一手文献；相关研究 **2020-11—2021-11**；日 | **C/D**：临床病例/检测 dashboard 历史说明；校园密度指标；补充研究图表 | 有，Return to Learn 和论文 | 有条件，可结合汇总环境监测；当前开放临床 CSV 未核实 |
| U12 | Purdue，West Lafayette/Protect Purdue 检测 | U02 实际 **2020-08-01—12-09** | **A/C**：第三方保存累计测试/病例 CSV；官方疫情时间表 PDF | **有，官方 Pandemic Fact Sheet** | 有条件；仅使用已保存时段可复现；不能以 Fort Wayne 的报告替代 West Lafayette |
| U13 | CU Boulder，校内检测及 Boulder 周边 | 官方周报已核实 **2020-09-10、09-24**；整个 dashboard 首尾待核实 | **C**：周简报、检测/转诊总数、隔离床位；历史 dashboard 线索 | **有，9/23 生效的临时远程教学通知** | 适合总量/事件背景交叉检验；监测转诊不等于确诊病例 |
| U14 | UConn，Storrs、Stamford、校外学生与员工，排除 UConn Health | 2020-08-19 dashboard 启动；明确 2020 秋及 2021 春返校统计；完整日表范围待核实 | **C/D**：测试/阳性、住校与校外分层；旧 dashboard 本次不可取 | **有，完整校园通信归档及返校公告** | 有条件；校园范围和住校分母较清楚，需恢复连续表格 |
| U15 | Carnegie Mellon，Pittsburgh 校园 | 已核实 **2020 年 9 月** 日病例/周无症状检测说明；公告归档至 2023 | **C/D**：官方历史病例/检测 dashboard 说明；公告仍可读 | 有，2020 混合授课及检测说明 | 目前偏事件与数据线索；NOVID 的存在不代表公开接触网络 |
| U16 | Northeastern，Boston campus 检测计划 | 至少 **2020 年 8 月**；官方 8/24 公告说明日更新 | **C/D**：日检测 dashboard 外壳仍在；数据主体本次未读出 | **有，8/24 检测频率及返校分阶段检测公告** | 目前偏线索；若从学术仓库恢复表格可研究高频检测人群 |

## 2. 已实际读取的机器文件

2026-10-15 使用指定 Python 环境，只读获取公开 CSV；未添加依赖，未修改应用代码。以下统计直接来自文件解析，而非论文自述。三份文件都来自 U02，**它们不是三个独立的观测来源**。

| 文件 | 实际记录数 | 实际日期范围 | 已读字段与限制 |
|---|---:|---|---|
| [raw.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv) | 1,042 | 2020-03-14—2020-12-20 | `Country_Region, Date, Tests, Confirmed`；学校名称误用地理字段名；累计值、有测试量缺失 |
| [daily.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/daily.csv) | 2,188 | 2020-03-14—2020-12-20 | 同四字段；作者明确采用 forward-fill，所以“每天有一行”不等于“每天有实际观测” |
| [detailed/uiuc.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/detailed/uiuc.csv) | 167 | 2020-07-06—2020-12-19 | 19 字段，包括 `UIUC_Tests, UIUC_Confirmed, B10_Tests, B10_Confirmed, Illinois_Tests, Illinois_Confirmed, Illinois_Deaths, US_Tests, US_Confirmed, US_Deaths` 等；有州/全国背景累计数与派生百分比，不应误称 UIUC 住院或死亡数据 |

三个文件首末记录：`raw.csv` 首行为 Michigan 2020-03-14，末行为 Maryland 2020-12-20；`daily.csv` 末行为 Michigan State 2020-12-20；`uiuc.csv` 首日累计测试 99、确诊 0，末日累计测试 1,025,454、确诊 4,526。源文件和处理含义见[仓库 README](https://github.com/wadefagen/college-covid19-dataset)。

原始 CSV 的 14 所学校实际范围：

| 学校 | 首日 | 末日 |
|---|---|---|
| Illinois | 2020-07-06 | 2020-12-19 |
| Indiana | 2020-08-09 | 2020-12-13 |
| Iowa | 2020-08-24 | 2020-12-16 |
| Maryland | 2020-08-12 | 2020-12-20 |
| Michigan | 2020-03-14 | 2020-12-19 |
| Michigan State | 2020-08-02 | 2020-12-20 |
| Minnesota | 2020-08-20 | 2020-12-10 |
| Nebraska | 2020-08-13 | 2020-12-18 |
| Northwestern | 2020-03-19 | 2020-12-16 |
| Ohio State | 2020-08-13 | 2020-12-12 |
| Penn State | 2020-08-13 | 2020-12-17 |
| Purdue | 2020-08-01 | 2020-12-09 |
| Rutgers | 2020-05-30 | 2020-12-12 |
| UW-Madison | 2020-08-07 | 2020-12-19 |

范围由[同一原始文件](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv)按学校分组计算；不能把总体 3 月到 12 月的时间窗自动赋予每一所学校。未在本次审计中逐校重新核对所有累计指标的官方分母，因此后续应保留原始定义与修订记录。

另尝试读取 U01 的 `campus_covid_fall2020_full.csv` 与 `massachusetts_ihes.csv`，响应均在读取完成前中断；因此本报告没有给出这两份文件未经验证的行数、字段和完整日期范围。GitHub 文件页面和目录可正常确认其存在；这属于本次传输限制，不能据此断言作者已删除数据。

## 3. 各来源的可用信息、拼接办法与局限

### U01. Campus COVID Data：论文作者的跨高校汇编

- **来源与数据入口**：[作者仓库及说明](https://github.com/jkbren/campus-covid)、[data 目录](https://github.com/jkbren/campus-covid/tree/main/data)、[fall 2020 主 CSV 文件页](https://github.com/jkbren/campus-covid/blob/main/data/campus_covid_fall2020_full.csv)、[直接 CSV](https://raw.githubusercontent.com/jkbren/campus-covid/main/data/campus_covid_fall2020_full.csv)。数据源自高校 dashboards 的人工/众包收集；对该采集研究而言是作者发布源，对高校疫情统计而言是再汇编来源。
- **类型与覆盖**：病例、测试量，原始大学发布频率不一致。仓库另有 Massachusetts 专表、IPEDS、ACS 和县级 JHU 数据；完整文件首尾和缺失率尚待验证，不能把文件名当成每校完整覆盖证明。[仓库说明](https://raw.githubusercontent.com/jkbren/campus-covid/main/README.md)
- **背景与结构**：可通过学校标识连接官方校历和人口统计；C2i 的 `campus_covid_status.csv` 不在公开无条件使用范围，作者明确需另行取得 permission。没有公开个体接触边表的证据。[数据与许可说明](https://github.com/jkbren/campus-covid)
- **ABM 判断**：适合多校园病例/测试曲线的外部比较；优点是官方站点消失后的历史保存及人口辅助表，缺点是众包录入、自报病例、官方回填和异构口径。应先逐校核对，不能直接合并为统一观测过程。[作者限制声明](https://github.com/jkbren/campus-covid#limitations)

### U02. College COVID-19 Dataset：已核实可直接读取的 14 校 CSV

- **来源**：[项目 README、官方 dashboard 来源清单及 MPL-2.0 许可](https://github.com/wadefagen/college-covid19-dataset)。高校原始发布链接被保存在 README 中，当前保存文件属于独立研究者的衍生归档。
- **类型、时间与范围**：见第 2 节实际读取结果；`Tests` 和 `Confirmed` 表现为累计计数，学校之间的测试量和人群覆盖并不统一。无住院字段，无措施字段，无人口分层或接触网络。
- **ABM 判断**：优点是小体积、可机器读取、原始表与填充表分开；缺点是停止于 2020、采集无统一协议。累计数的差分应标注为“相邻发布日期间新增”，跨多日间隔不能分配为每日感染；forward-fill 日表不能产生独立的每日观测证据。

### U03. University of Illinois Urbana-Champaign：SHIELD 聚合数据与官方公告

- **一手背景和聚合入口**：[Nature Communications 原研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC9184485/)、[原官方数据短链](https://go.illinois.edu/COVIDTestingData)、[校内检测页面](https://covid19.illinois.edu/health-and-support/on-campus-covid-19-testing/)。原研究核心部署窗口为 **2020-08-15—12-23**，研究描述约 **50,000** 名学生、博士后及教职工的校园人群。论文说明公开的是 aggregate case/testing data，其他数据需申请；本次官网页面有超时，不能据旧论文保证当前原 dashboard 可导出。
- **可读取替代**：[U02 UIUC CSV](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/detailed/uiuc.csv)实际覆盖 **2020-07-06—12-19**，与论文窗口不同。数据中 `Illinois_Deaths` 是州级变量，不是校园死亡。
- **措施时间线**：[COVID-19 Massmail Archive](https://covid19.illinois.edu/more-information/massmail-announcements/)保存按日期的 testing、返校、假期、授课与疫苗相关公告；[2021-02-26 dashboard 更新说明](https://covid19.illinois.edu/updates/covid-19-data-dashboard-update/)有助识别发布口径变化。
- **ABM 判断**：较强的校园汇总验证候选；可同时检查测试分母、阳性及学期节点，人口覆盖有明确描述。限制是没有已核实的公开实测接触网络，第三方保存表没有全程人群分层，且高频重复测试人数不能直接视为人口数。

### U04. The Ohio State University：仍保留官方归档和导出入口

- **数据与人群**：[COVID-19 Dashboard (archived)](https://safeandhealthy.osu.edu/dashboard)确认 dashboard 更新到 **2021–22 学年结束/2022 春季末**，2022 夏季停止更新。同页保留 Excel 下载链接和 Tableau 移动版入口；本次可阅读页面及下载锚点，但尚未实际取得 Excel 文件内容，故为 B 级。
- **变量与粒度**：学生总测试、阳性及阳性率、24 小时值、7 日滚动指标；低量时可按周报。Ohio 的住院容量和州病例属于背景地域统计，不能当成学生住院数。人群解释见[Dashboard Measures and Interpretations](https://safeandhealthy.osu.edu/dashboard/measures-and-interpretations)。
- **措施时间线与人口分母**：归档同页给出 **2020-08-08** 常规学生筛查、**08-12** Columbus 入住、**08-25** 开学、**11-28** 改线上；2022 春筛查 **01-10—05-06**，对象按居住、社团和接种要求分组。变化的入组对象应作为观测范围元数据保存。[官方归档页](https://safeandhealthy.osu.edu/dashboard)
- **ABM 判断**：最值得继续取得官方 Excel 的候选之一；优点是数据与时间线同处官方归档，缺点是学生筛查选择性随时期变化、回填及小数保护。U02 仅保存 **2020-08-13—12-12**，不能替代全官方时间窗。

### U05. Duke：明确分检测类别的 2020 窗口和可延伸的周简报

- **一手资料**：[CDC MMWR，2020-08-02—10-11](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)。人群为居住在校园或 Durham 社区的 **10,265** 名本研学生，**排除 781 名运动员及校外远程学生**。公开总计 **68,913** 次测试、**84** 例阳性，分返校、常规筛查、接触后检测及有症状监测；公开的是表格及累计曲线，没有本次已核实的逐日 CSV。
- **后续官方数据线索**：[2021-01-18—24 周报](https://www.today.duke.edu/2021/01/82-test-positive-covid-jan-18-24)给学生及教职工筛查/诊断测试汇总，可逐期人工整理；不能只找到一周便声称已有完整 2021 周序列。
- **背景与结构**：MMWR 记载返校前隔离、8 月分批返校和 **9/20** 前的检测计划扩展；[2021-03-20 官方公告](https://coronavirus.duke.edu/2021/03/update-on-stay-in-place-sent-to-faculty-staff-and-graduate-professional-students/)明确 3/21 09:00 解除 stay-in-place 及恢复原春季授课模式。
- **ABM 判断**：对历史窗口的汇总观测过程验证较强；检测类别、分母和入组排除明确。缺点是窗口短、连续日观测缺失，公开接触追踪检测比例不等于公开接触网络；无校园住院序列。

### U06. Cornell：公开聚合与受限原始数据必须分开

- **历史 dashboard**：[官方 2020-08-25 启动报道](https://news.cornell.edu/stories/2020/08/cornell-launches-covid-19-testing-dashboard-alert-system)确认 Ithaca 校园每日测试与阳性、以及校园警示等级。旧入口 `https://covid.cornell.edu/testing/dashboard/` 的当前完整日数据本次未取到，不能把仍可读的旧新闻当作可用日表。
- **论文与补充资料**：[PNAS，Modeling for COVID-19 college reopening decisions](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764692/)及其 SI 有批准公开的秋季汇总、人口假设和学校重启背景。其 Data Availability 明确学生/员工监测数据受保护且未获公开；[group-testing 仓库](https://github.com/peter-i-frazier/group-testing)提供的是代码和模拟结果，不能冒称为公开实测逐日原始病例。
- **ABM 判断**：适合作为建模研究对照和批准公开聚合的有限验证；优点是场景与政策解释细，缺点是无法仅靠代码仓库复原全部真实观测，独立日序列验证仍需公开归档。没有已核实的公开实测接触网络。

### U07. Notre Dame：CDC 图表、人口和明确历史事件

- **一手数据**：[CDC MMWR，Response to a COVID-19 Outbreak ... Indiana, August 2020](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)公开 8 月诊断病例日曲线、8–10 月诊断/筛查测试图及病例总量；[Notre Dame 官方新闻](https://news.nd.edu/news/cdc-publishes-paper-describing-notre-dames-successful-response-to-early-surge-in-covid-19-cases-on-campus/)明确匿名 University A 就是该校。
- **范围与结构**：约 **12,000** 名学生，包括约 8,000 本科生，约 85% 本科生住校；论文给本研/教职工及住校/校外的聚合构成。没有公开个体接触网络。
- **措施与检测口径**：2020-08-10 开学，**8/19** 本科转线上，**9/2** 起逐步恢复；随疫情发展，无症状筛查及检测能力大幅变化。图 1 只含诊断性检测，图 2 才区分诊断和筛查，不能混接为同一个 daily cases 字段。[CDC 原报告](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)
- **ABM 判断**：适合历史事件窗口的总量、峰值和分组比例交叉验证；缺点是本次未确认开放 CSV，图表数字化需要保留误差。旧 [HERE dashboard](https://here.nd.edu/our-approach/dashboard/)本次访问失败；[8/28 返课官方说明](https://politicalscience.nd.edu/news-and-events/news/provost-miranda-evp-cullinan-message-on-resumption-of-in-person-instruction/)仍可读。

### U08. University of Michigan：可用第三方保存表与官方口径说明

- **数据入口**：[官方 ITS dashboard 说明](https://its.umich.edu/data/analytics/campus-health-reporting/covid-dashboards)、[Health Response dashboard](https://healthresponse.umich.edu/dashboard/)、[U02 原始 CSV](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv)。实际保存范围 **2020-03-14—12-19**；原始记录并非全部逐日。官方说明公共 Tableau 包含校园病例、测试、CSTP 及接种聚合；内部合规明细需登录。
- **背景**：[2020 年官方反应准则公告](https://news.umich.edu/u-m-publishes-guidelines-for-ongoing-covid-19-related-responses-and-strategies/)提供当期监测与学校运营背景；[2021-08 开学说明](https://news.engin.umich.edu/2021/08/reigniting-the-on-campus-experience/)可辅助解释后一学年返校，但不能套用到 2020 年。
- **ABM 判断**：有条件。优点是已存 CSV 和官方指标说明可相互检查；缺点是早期 UHS/临床检测与后期校园筛查观测对象变化，不能把一个累计序列视作全期全校普查。公开总人口可另接官方统计，但需区分 Ann Arbor 与 Dearborn、Flint；未发现公开实测接触网络和学生住院序列。

### U09. Yale：早期临床分层和秋季返校制度记录丰富

- **可核实内容**：[2020-07-27 官方 dashboard 启动说明](https://news.yale.edu/2020/07/27/dashboard-covid-19-testing-stats-yale-and-connecticut)明确启动版涵盖 **3 月初至 7 月中**、按周更新，病例/测试/阳性率区分有症状与无症状，以及学生、员工、家属、退休者。其 Connecticut 住院和死亡是州/县背景数据，非校园结局；外部医疗机构测试当时未计入。
- **政策和人群**：[2020-08-19 返校说明](https://news.yale.edu/2020/08/19/yale-prepares-welcome-students-fall-semester-2020)给出 8/24 起分批入住、哪些年级允许回校、返校隔离和在 New Haven 住校/校外本科生每周两次检测；因此全校注册人数并不是当期在场分母。
- **可用性与 ABM**：旧 [dashboard](https://covid19.yale.edu/dashboard)本次不可访问，完整后续机器序列待恢复，暂为 C/D。优点是官方人口构成与检测制度说明细；缺点是早期包含家属/退休者，临床人群与返校学生要分开。无已确认公开接触网络。

### U10. Harvard：官方历史存在性明确，当前数据主体未恢复

- **数据与政策证据**：[2020-09-03 官方 Gazette](https://news.harvard.edu/gazette/story/2020/09/self-administered-covid-19-tests-to-replace-observed-testing/)确认 Harvard COVID-19 Dashboard 当时按日更新筛查统计；明确次日起分阶段改为自采、非现场观察检测，目标人群为住校、校内工作或每周获准到校至少一定时数的成员，秋季多数课程远程。
- **数据访问**：[原大学 dashboard 入口](https://www.harvard.edu/coronavirus/harvard-university-wide-covid-19-testing-dashboard/)仅作为历史定位；本次未获得连续数据主体或可下载文件，完整首尾待核实。没有据此确认开放住院、人口分层或接触网络。
- **ABM 判断**：目前只适合作为进一步追索线索和政策背景；优点是检测政策变化有明确官方日期，缺点是原始序列保存情况不明，不能拿学校名下的全球 COVID 数据库替代 Harvard 校园观测。

### U11. UC San Diego：校园临床数据与环境监测须分开

- **临床统计与范围**：[UCSD 图书馆官方目录](https://ucsd.libguides.com/c.php?g=1007062&p=7535586)确认 Return to Learn dashboard 面向学生与 general campus 员工，包括 Scripps；[National Academies 原报告的示例框](https://www.nationalacademies.org/read/26005/chapter/2)记录其日病例/测试、校内/校外学生、学期累计、校园密度与隔离房间等指标。没有本次已核实的开放临床 CSV。
- **时间及取用**：历史 [Return to Learn dashboard](https://returntolearn.ucsd.edu/dashboard/index.html) 与后续 [Blink dashboard](https://blink.ucsd.edu/safety/resources/public-health/covid-19/dashboard.html)本次未成功读到主体；不保证当前还提供旧临床序列。研究 [Optimizing campus-wide COVID-19 test notifications](https://pmc.ncbi.nlm.nih.gov/articles/PMC10673837/)分析 **2020-11—2021-11**，但其环境时间序列特征需非商业研究申请，代码开放不等于全部实测数据开放。
- **政策与人口**：[2021 校园环境监测研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC8409724/)记录冬季返校/开学日期与历史仪表板；前述 National Academies 资料解释居住和线下课程比例指标。本文不收集个人定位或楼栋级传播链。
- **ABM 判断**：有条件，优势是多个聚合观测指标可以交叉检验；限制是临床与环境监测量纲不同、不同仪表板版本范围变动。无已验证公开实测接触边表。

### U12. Purdue：保存 CSV 配官方政策时间表

- **观测数据**：[U02 原始 CSV](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv)中 Purdue 实际覆盖 **2020-08-01—12-09**；累计 `Tests`、`Confirmed`，没有住院字段。[Protect Purdue dashboard](https://protect.purdue.edu/dashboard/)及 [timeline](https://protect.purdue.edu/timeline/)本次未成功取到主体。
- **官方措施记录**：[Purdue Pandemic Fact Sheet](https://www.purdue.edu/academics/faculty-affairs/documents/promotion-covid-timeline.pdf)为按影响领域的时间表；[2020-10-19 校务会议纪要](https://www.purdue.edu/senate/documents/meetings/2020-10-19-Minutes.pdf)记载春季返校检测计划等；[2020 秋季官方学院页面](https://engineering.purdue.edu/ChE/news/2020/coronavirus-information-for-purdue-che-students-staff-and-faculty)保存 West Lafayette 重开节点和当期公告入口。
- **ABM 判断**：适合对已保存的 2020 时段做聚合验证；优点是实际 CSV 可读、政策来源可接，缺点是后续疫情时段未在该文件保存、人群分层及接触网络缺失。Purdue Fort Wayne 是另一个校园，其 dashboard 关闭日期不能自动作为 West Lafayette 的日期证据。

### U13. CU Boulder：公开周报与生效日期明确的授课变化

- **数据内容与口径**：[2020-09-10 官方周更新](https://www.colorado.edu/today/2020/09/10/covid-19-campus-updates-sept-10-edition)解释校内监测/诊断测试及工作日更新，明确不包括所有校外医疗机构检测。[09-24 更新](https://www.colorado.edu/today/2020/09/24/covid-19-campus-updates-sept-24-edition)提供截至 9/23 监测检测 **22,955** 次、转诊 **906** 次，以及 9/24 隔离床位 **273/623**。转诊、床位使用和确诊是不同变量。
- **背景**：[2020-09-21 教务长通知](https://www.colorado.edu/academicaffairs/newsletter/provost/cu-boulder-instructional-personnel-temporary-shift-remote-instruction-begins)明确 **9/23 06:00** 起至至少 10/7 临时远程授课，部分实验课例外。公告日和生效日应分别保存。
- **可用性与 ABM**：历史 [dashboard](https://www.colorado.edu/covid-19-ready-dashboard)的完整数据首尾、CSV 和人群分层未核实，现可用的是官方周报聚合。适合峰值附近事件背景与总量交叉验证；若要连续逐日误差验证，现有取证仍不足。没有已确认公开接触网络。

### U14. University of Connecticut：多校区与住校状态的定义较清楚

- **数据范围**：[2020-08-19 官方启动说明](https://today.uconn.edu/2020/08/uconn-launches-covid-19-dashboard/)规定大学范围**排除 UConn Health**，包括 Storrs、Stamford 住校学生测试/阳性，校外学生病例，以及员工校内测试/阳性。[原 dashboard](https://coviddashboard.uconn.edu/covid-dashboard/)本次无法读取主体，连续覆盖日期待核实。
- **人口与措施**：[2020-08-14 返校报道](https://today.uconn.edu/2020/08/students-return-uconn-fall-2020-semester/)记约 **5,800** 人分批入住两校区、入校检测、至 8/31 开课前隔离；[2021-01-19 官方报告](https://today.uconn.edu/2021/01/uconns-covid-re-entry-tests-successful/)给秋季超过 **42,000** 次学生检测及春季返校与开课安排。[完整官方通信归档](https://uconn.edu/public-notification/coronavirus/covid-19-official-campus-communications-archive/)可补日期。
- **ABM 判断**：有条件，优点是住校/校外和医疗系统界限明确，可接返校人数；缺点是当前日序列未恢复、总测试含重复检测。没有已确认开放的个体接触网络；州级大学研究的移动接触指标不能自动视作 UConn 实测校园接触边表。

### U15. Carnegie Mellon：官方通信完整，历史 dashboard 数据未确认恢复

- **数据与背景**：[2020-09 官方 tracing/notification 说明](https://www.cmu.edu/coronavirus/news-and-communications/communications-archive/2020/september/contact-tracing-classroom-lab-notifications-novid.html)确认病例按日、无症状检测按周更新；[校园运营公告](https://www.cmu.edu/coronavirus/news-and-communications/communications-archive/2020/september/on-campus-service-postures.html)记述 Pittsburgh 校园混合授课、住宿学生返校 PCR 以及向校外本研学生扩展检测。
- **历史取用**：[官方 News & Communications](https://www.cmu.edu/coronavirus/news-and-communications/)保存后续通信，至少可核实到 2023 年的疫情运营更新；这不表示病例序列完整覆盖到 2023。dashboard 的开放原始文件和准确首尾尚待恢复。
- **ABM 判断**：目前偏背景与数据线索；优点是各类学校运营事件容易溯源，缺点是缺连续已取到的结果表、当期在场人口分母和公开住院统计。NOVID 的推广仅证明通知工具存在，不能据此声称有公开接触网络。

### U16. Northeastern：高频检测政策明确，但当前页面只读出外壳

- **数据与访问**：[Daily COVID-19 Dashboard](https://news.northeastern.edu/coronavirus/reopening/testing-dashboard/)页面仍存在，本次只能读到标题和网站导航，未读出数据图表或下载链接。[2020-08-24 官方公告](https://news.northeastern.edu/coronavirus/university-messages/northeastern-to-increase-coronavirus-testing-frequency-when-fall-semester-starts/)确认日更新、截至 8/20 的检测与结果汇总，完整系列范围待核实。
- **措施与人群**：同一公告明确 Boston campus 的学生在返校第 1、3、5 天检测、随后每三天一次；经常到校员工/承包商每周两次，较少到校者另有频率。因此全校总注册人数与检测计划入组人数不能混同。[官方原公告](https://news.northeastern.edu/coronavirus/university-messages/northeastern-to-increase-coronavirus-testing-frequency-when-fall-semester-starts/)
- **ABM 判断**：恢复连续观测表后具有研究价值，目前适合作为后续追索项；优点是制度日期与人群定义清楚，缺点是当前无本次可验证的完整日病例/测试文件、人口分层或接触网络。

## 4. 优先取用顺序与研究使用边界

本目录中最容易形成可复现起点的是 **U02 的真实 CSV**，以及 **U04 的官方历史 Excel/仪表板入口**；U03 可把 UIUC 保存表与官方 Massmail 时间线及论文人口范围配对。U05 和 U07 的数据类型更有限，但窗口、分母和政策生效日期清晰，适合补充总量和图表层面的历史验证。

这批高校资料通常支持校级或学生/员工分组的**聚合验证**，不能单靠病例曲线唯一识别接触网络或全部模型参数。为保证后续论文可复核，应保留：原始网址与获取日期、报告日期/采样日期的定义、观测人群、检测次数与受检人数区别、病例与阳性测试区别、累计数重置、缺失/回填、图表读取误差。仅把记录实际存在的校园政策当作历史背景，不从这些资料外推新的现实控制方案。

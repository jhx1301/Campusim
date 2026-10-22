# 校园与社区历史疫情数据：ABM 校准与验证调研

核查日期：**2026-10-15**。目标是为历史校园/社区模拟建立可追溯的观测与背景资料库。检索重点为高校，补充 K–12、历史流感和封闭社区，并覆盖地方卫生部门、政府开放数据及 CDC/WHO/ECDC。以下研究适用性与优先级是本次调研判断；来源事实由各行链接及分册原始出处支持。

**已交付可直接读取的数据包**：[入口与运行方法](../README.md)、[40个数据集索引](../data/dataset_index.csv)、[85条来源清单](../sources/catalog.csv)。规范化后的2,007,056条观测均保留来源与原始口径；配套人口和历史事件可按机构键连接，系统接口和离线核验已落实。观测行数不是感染人数。

## 1．主要结论与完整目录

**已有可立即作为研究起点的公开历史表格，但没有在本轮检索中确认一套同时包含高校完整病例、检测制度、真实同期接触网络与动态在校人口的开放数据。** 最可行的做法是以同一校园的病例/检测为主，配同校官方历史公告和当年人口，再以当地卫生数据作背景或额外验证。接触数据通常来自其他地点或年份，应独立用于结构层检查。

四分册共61个条目（Duke在两册重复，合计60组来源家族）：高校16条、学校论文及接触15条、公共卫生20条、校园补充与政策人口10条。早期58条调研记录与补充来源已经合并，以 [sources/records.json](../sources/records.json) 中的 **85条来源记录**统一维护；原始专题证据保留在 `sources/evidence/`，不再另外维护一套目录。来源条目、数据包和独立疫情的数量不同：同校官网、论文和保存仓库可能共享上游统计，政策、人口和仅接触资料也不能独立验证病例曲线。C2i保留为受限线索，没有冒充已取得的开放观测。

| 详表 | 覆盖内容 | 条目 |
|---|---|---|
| [高校分册](campus_epidemic_sources_universities.md) | UIUC、Ohio State、Duke、Cornell、Notre Dame、Michigan、Yale、Harvard、UCSD、Purdue、CU Boulder、UConn、CMU、Northeastern，以及两套跨校仓库 | U01–U16 |
| [学校论文、历史流感与接触分册](campus_epidemic_sources_studies_contacts.md) | CSDH、Illinois K–8、天津、大阪、宾州、伦敦、Queens、Duke、邮轮、1978寄宿学校；SocioPatterns、CNS、SMART | S01–S10、C01–C05 |
| [地方卫生、政府与国际数据库分册](campus_epidemic_sources_public_health.md) | NYC、NY州、Massachusetts、Ontario、UKHSA、ONS、香港、日本、NSW、意大利、新加坡、CDC、HHS、WHO、ECDC、FluNet、JHU、中国疾控 | PH01–PH20 |
| [校园补充、政策与人口分册](campus_epidemic_sources_context.md) | Wisconsin–Madison、UC Davis、NYT高校快照；OxCGRT、UNESCO、CoronaNet、HIT-COVID、Google Mobility、IPEDS、Census/ACS | X01–X03、P01–P07 |

每条详表均给出来源链接、适用人群/地域、覆盖窗口或尚未核实的边界、数据类型、历史措施有无、人口/接触信息及 ABM 优缺点。**“截至某日停更”“网页发布日”“实际文件末日”分别记载**；找不到证据的日期明确留待核实。

## 2．优先候选对照

“高”仅表示可支持对应尺度的某种观测验证，不表示足以识别全部模型参数。可得状态与研究价值独立评价。

| 来源与范围 | 已核覆盖时间 | 观测与获取形式 | 措施时间线 | ABM 用途、优点与主要不足 |
|---|---|---|---|---|
| **Big Ten 14 校保存数据，U02**；[仓库](https://github.com/wadefagen/college-covid19-dataset) | 总体 **2020-03-14—12-20**，各校不同 | 累计病例、累计检测；`raw.csv` 已实际解析，1,042 行 | 无；接同校公告 | **高：可复现的多校园汇总基准**。体量小、保留来源；口径不统一，存在缺测；`daily.csv` 前向填充不是真实每日新增 |
| **Wisconsin–Madison，X01**；[2020日表](https://covidresponse.wisc.edu/dashboard-2020/)、[2021春日表](https://covidresponse.wisc.edu/dashboard-2021-jan-may/) | 2020版 **2020-08-17—12-31**；春季页面实际日表 **2020-08-07—2021-05-09** | 已整理官方 HTML 日表；学生/员工阳性、检测量，春季另分校内/校外报告 | 有，可接官方9/9公告和后续说明 | **高：优先单校候选**。分组、分母和事件丰富；两个快照重叠、页脚与日表合计不同，校内/校外统计时钟需区分 |
| **UIUC，U03**；[CSV](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/detailed/uiuc.csv)、[论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9184485/) | 文件 **2020-07-06—12-19**；论文核心 **08-15—12-23** | 已解析167行、19字段；校园累计测试/病例，另有州/全国背景 | 有，[Massmail归档](https://covid19.illinois.edu/more-information/massmail-announcements/) | **高：检测与阳性联合核对**。有约5万人群背景；文件与论文时窗不同、无公开同期完整接触网络；州死亡字段不是校园死亡 |
| **Ohio State，U04**；[官方归档](https://safeandhealthy.osu.edu/dashboard) | 常规筛查从 **2020-08-08**；归档到 **2022春季末**，各表端点待读 | 阳性、测试、阳性率；官方保留 Excel 导出入口，本轮未取得完整工作簿 | **有，同页**记录筛查/入住/开学/转线上 | **高，但先核工作簿**。官方数据和事件同页；学生筛查对象随期变化，州住院容量不能当校园结局 |
| **Campus COVID Data，U01**；[作者数据目录](https://github.com/jkbren/campus-covid/tree/main/data) | 标为 **2020秋季**；逐校首末日期未核实 | 多校病例和测试 CSV；完整大文件读取中断 | 需配官方公告；C2i文件受限 | **中至高的候选，尚需文件核查**。多校及人口辅助表丰富；众包录入和官方回填可能不一致，不宣称已完成导入 |
| **Duke，U05/S08**；[CDC MMWR](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm) | **2020-08-02—10-11** | 10,265名学生、分原因检测/阳性总量与累计检测曲线；公开论文表图 | 有，返校和筛查变化 | **中：观测机制与总量验证**。分母及排除清楚；不是完整公开日病例CSV，后续官方周报也未整理成全期序列 |
| **Notre Dame，U07**；[CDC MMWR](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm) | **2020-08—10**，图表窗口各异 | 日诊断病例图、诊断/筛查测试图；约12,000学生的分组背景 | 有，8/19转线上、9/2分阶段返课 | **中：特定历史窗口**。事件与人群清楚；原始日表未核实，数字化需标误差，诊断病例与筛查阳性不能混接 |
| **CSDH，美国K–12，S01**；[下载资源](https://www.covidschooldatahub.com/data-resources) | **2020–21学年**，各州报告区间不同 | 病例CSV ZIP已读；教学模式、口罩政策、NCES ID及人口链接 | **有，独立配套文件** | **高：学校/学区综合候选**。拼接条件好；病例新增/现患/累计口径异质、隐私抑制、无实测同期网络 |
| **SHIELD Illinois K–8，S02**；[Illinois Data Bank](https://databank.illinois.edu/datasets/IDB-3705306) | **2021春—2022春**；CSV首末日未实核 | 116学区每周测试/阳性，学生员工人口；CSV+字典公开目录，文件端本轮403 | 论文有政策与校历背景 | **高的候选，下载需复核**。学校筛查和人口配套；参与覆盖变化，论文模拟终点不是文件观测末日 |
| **天津学校流感，S03**；[论文及附件](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184527) | 实读附件 **2014-10-26—12-27**，63日 | XLSX：发病日与ILI，**仅一校一次暴发** | 部分，正文/暴发图 | **中：中文场景短期验证**。确有日表；不是4校三年全数据，ILI不是确诊感染，缺完整检测分母 |
| **大阪学校H1N1，S04**；[论文与附表](https://pmc.ncbi.nlm.nih.gov/articles/PMC2866419/) | **2009-05-11—05-31** | 学校×发病日确诊汇总附表PDF，未完整转录 | 有，5/18—24停课范围 | **中：多校短窗**。发病日与事件明确；学校分母不全、窗口短、选择性检测 |
| **纽约市，PH01**；[官方日CSV](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/trends/data-by-day.csv) | **2020-02-29—2025-10-13**，该日表实际首末 | 日病例、住院、死亡；其他表有检测/年龄/社区分层 | 有监测变更；社会措施另接 | **高：城市/社区模型**。多指标且可下载；末期有不完整标记，检测表截止不同，不能直接代表某大学 |
| **UKHSA，PH05**；[官方历史ZIP](https://ukhsa-dashboard.data.gov.uk/covid-19-archive-data-download) | **2020起至旧平台退役前**，每指标末日不同 | 病例/检测/住院/死亡/疫苗；地区与年龄分层 | 方法/报告变化有；校园措施另接 | **高：地区模型和校园背景**。多尺度、可接ONS；官方明确部分2020-10地方数据缺失/插补 |
| **Ontario，PH04**；[官方CSV目录](https://data.ontario.ca/en/dataset/status-of-covid-19-cases-in-ontario) | 主Status **2020-01-26—2023-04-04**；PHU日变化至 **2024-06-04** | 病例、测试、住院/ICU存量等，CSV与字典 | 有口径变更；完整措施另接 | **高：省/PHU模型**。多结局；资源窗口不同，死亡回补及定义变化需要分段 |
| **WHO FluNet，PH18**；[官方CSV入口](https://www.who.int/tools/flunet/) | 系统 **1997上线**；每国首末周不同 | 周标本数、病毒检出与型别 | 无 | **辅助：流感季节外部验证**。长期覆盖；检出不是社区总感染，不能替代校内病例 |
| **SocioPatterns/CNS/SMART，C01–C05**；[小学例](https://sociopatterns.org/datasets/primary-school-temporal-network-data/)、[大学公开子集论文](https://www.nature.com/articles/s41597-019-0325-x) | 小学2009两日；其他2011–2013短窗；大学公开子集4周相对时间 | 匿名接触与班级/年级结构等；公开目录 | 无同期疫情措施 | **仅结构验证**。有人群与接触实测；没有同期病例，不能单独验证疫情或证明传播参数正确 |

其他高校、邮轮、历史寄宿学校及 CDC、WHO、ECDC、日本、澳洲、中国等数据的完整时间、入口和限制见四个分册，未因未列入优先表而省略。

## 3．可以组成什么样的资料包

以下是已找到对应来源的拼接设计。Wisconsin、Big Ten、天津、Cambridge聚合面板、上海、NYC、意大利及CSDH已形成规范化观测；人口和事件进入可连接的独立表。尚未取得的其他候选仍按访问状态标记。各表保留自己的观测对象和时钟，不把不同来源的计数直接相加。

| 历史场景包 | 疫情观测来源 | 措施/事件来源 | 人口、结构与社区补充 | 可达到的验证与缺口 |
|---|---|---|---|---|
| Wisconsin–Madison 2020秋/2021春 | X01官方日表；U02仅作历史保存版本核对 | [2020-09-09官方公告](https://news.wisc.edu/university-shifts-to-two-weeks-remote-instruction/)，及X01后续归档 | [2021 Fact Sheet](https://profs.wisc.edu/wp-content/uploads/2021/09/UW-Madison-Fact-Sheet-2021.pdf)、P06/P07、PH19 Dane County背景 | 校内阳性与检测、角色分组、事件前后历史一致性；缺同期公开真实网络及动态在校人数 |
| UIUC 2020秋 | U03已读CSV，结合原论文公开聚合 | [Massmail历史档案](https://covid19.illinois.edu/more-information/massmail-announcements/) | U03论文人口、P06 IPEDS、PH19 Champaign County | 校园检测/阳性联合核对；统计窗需取交集，县病例含校成员，不能算独立全体样本 |
| Ohio State 2020–2022 | U04官方Excel/归档，2020另有U02保存片段 | [同页官方时间线](https://safeandhealthy.osu.edu/dashboard) | P06机构人口、P07居住人口、PH19所在县 | 条件较完整；导出工作簿未实核，分校区和筛查对象须先固定 |
| Notre Dame 2020秋 | U07 CDC图表与聚合 | [MMWR](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)及[大学确认与历史说明](https://news.nd.edu/news/cdc-publishes-paper-describing-notre-dames-successful-response-to-early-surge-in-covid-19-cases-on-campus/) | 同文住校/本科/研究生等背景、P06 | 事件窗口和总量验证；图表读数误差、诊断/筛查两种观察过程仍需分开 |
| 美国K–12 2020–21 | S01 CSDH病例 | [CSDH教学模式/口罩文件](https://www.covidschooldatahub.com/data-resources) | 同平台NCES CCD及州Data Details，PH系列相应地区 | 按学校/学区、学生/员工验证；同主键便于拼接，但不同州观测定义不能自动统一 |
| Illinois K–8 2021–22 | S02周检测CSV与字典 | [原论文校历与政策背景](https://link.springer.com/article/10.1186/s12889-024-20623-5) | 同数据ElSi学生/员工人口；当地官方社区数据 | 周尺度多学区验证候选；须先实际读取字典和文件确认缺失及窗口 |
| 天津/大阪历史学校流感 | S03实读日ILI、S04发病日附表 | 各原论文中的历史事件 | 同研究学生规模/教育统计；PH18仅提供国家流感背景 | 学校短窗及跨病原研究；不能把流感检出与ILI当同一种病例定义 |
| 英国社区/大学所在地 | PH05地区病例/检测/住院 | 同大学官方公告；P01/P03/P04仅补地区规则 | PH06 ONS私人家庭抽样患病率及人口资料 | 多指标与抽样阳性率交叉验证；ONS私人家庭不代表机构宿舍，校园资料仍需另找 |
| 香港学校/高校外部背景 | PH07 CHP全港历史聚合 | [教育局2023-01-20函](https://www.edb.gov.hk/attachment/en/sch-admin/admin/about-sch/diseases-prevention/edb_20230120_eng.pdf)或[HKU具体公告](https://covid19.hku.hk/latest-announcement/) | 同期学校/大学年报和官方人口资料 | 城市背景和学校历史规则；教育局中小学函不能替代高校决定，CHP不是校内病例 |

**不要把公开接触网络当作缺失的“同一校园网络”。** 例如里昂2009小学接触与天津2014病例可分别支持结构与曲线检查，但两者不是同一群人的联合实测验证集。Copenhagen 公开子集只有相对时间，也无法与2020疫情政策日历按日连接。[各数据公开范围与限制](campus_epidemic_sources_studies_contacts.md)

## 4．已找到的历史事件证据示例

| 历史范围 | 已有可引用记录 | 原始出处与适用边界 |
|---|---|---|
| Wisconsin–Madison | 2020-09-09公告；09-10起暂停相关面授，09-14起远程至少两周；09-09当地22:00起两座宿舍检疫 | [当日大学公告](https://news.wisc.edu/university-shifts-to-two-weeks-remote-instruction/)；公告与生效日分开，非全体成员均住校 |
| Ohio State | 2020-08-08常规筛查、08-12 Columbus入住、08-25开学、11-28转线上 | [官方dashboard历史解释](https://safeandhealthy.osu.edu/dashboard)；不应把Columbus入住人数套给全校区 |
| Notre Dame | 2020-08-10开学、08-19本科转线上、09-02起逐步返课 | [CDC报告](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)；事件还伴随检测能力变化 |
| Yale | 2020-08-24起分批入住，允许返校年级、检疫及New Haven本科生检测制度有官方记录 | [2020-08-19官方说明](https://news.yale.edu/2020/08/19/yale-prepares-welcome-students-fall-semester-2020)；家属、退休者与在校学生统计范围不同 |
| CU Boulder | 2020-09-21公告，09-23 06:00起临时远程授课至至少10-07，部分实验课例外 | [教务长原通知](https://www.colorado.edu/academicaffairs/newsletter/provost/cu-boulder-instructional-personnel-temporary-shift-remote-instruction-begins)；公告日与生效日分别记载 |
| 大阪2009学校H1N1 | 2009-05-18—24学校关闭，正文列适用高中/初中等范围 | [原始报告及附表](https://pmc.ncbi.nlm.nih.gov/articles/PMC2866419/)；停课学校数不等于确诊报告学校数或学生分母 |
| 香港2023 | 01-30停止发隔离令，但学生返校前RAT要求暂维持至02-28 | [01-20教育局函](https://www.edb.gov.hk/attachment/en/sch-admin/admin/about-sch/diseases-prevention/edb_20230120_eng.pdf)；适用中小学/幼儿园等，不直接代表大学 |

这些记录支持历史条件重建。公告、计划、实际生效、撤销和检测制度变化应分别编码；没有依从性实测时，不把公布规则当作全员实际行为。[OxCGRT原始方法与限制](https://github.com/OxCGRT/covid-policy-dataset)

## 5．人口、接触与参数校准适用性

**人口规模可找到，但必须匹配病例的实际覆盖范围。** 已核实的例子包括 Wisconsin–Madison 登记学生45,540人、Duke研究入组10,265人、Notre Dame约12,000学生；这三种分母不是同一概念。Wisconsin官方 Fact Sheet 的雇员23,917人与春季dashboard的19,225人也不同，报告保留两者而不擅自替换。[Wisconsin人口](https://profs.wisc.edu/wp-content/uploads/2021/09/UW-Madison-Fact-Sheet-2021.pdf)、[dashboard分母](https://covidresponse.wisc.edu/dashboard-2021-jan-may/)、[Duke研究人群](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)、[Notre Dame研究人群](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm)

**结构信息通常比完整网络容易获得。** 高校可配当年IPEDS的年龄、本研、全日/非全日与远程教育信息；学校可配NCES ID、年级、教师员工与住校背景；社区可配Census/ACS。它们支持人群构成核对，但不能推出每人的真实接触边。[IPEDS历史文件](https://nces.ed.gov/ipeds/datacenter/DataFiles.aspx?gotoReportId=7&year=2020)、[CSDH方法](https://www.covidschooldatahub.com/methods)、[Census/ACS](https://www.census.gov/programs-surveys/acs/data/data-via-api.html)

**有病例曲线不等于所有参数都可校准。** 本调研认为：

- 有病例/阳性和检测量、明确受测群体及同期规则时，可支持对模型**可观测输出**的校准与留出时段验证；UIUC、Wisconsin和部分K–12资料比只有累计终点的快照更合适。
- 只有累计总量或论文几张图时，能核对终点、分组比例或特定窗口形状，不能宣称完成高精度逐日验证。NYT高校数据明确不发布历史时序。[NYT方法](https://raw.githubusercontent.com/nytimes/covid-19-data/master/colleges/README.md)
- 接触数据可约束或检验人口层/学校层的聚合结构；没有同步病例时，不足以验证疫情过程。
- 汇总病例同时受检测、报告和人群变化影响，不能由一条拟合曲线唯一辨认真实接触结构或全部传播参数。数据表必须与模型的相同观测量比较。
- 用于校准的数据与最终验证的数据应明确划分。多个数据库转载同一卫生机构统计时，应计作同一观测的不同版本，不能当作独立重复验证。

这些是数据使用边界与验证设计建议，不包含新的现实疫情措施设计或模型参数优化结果。

## 6．整理数据时必须保留的差异

| 易混淆项 | 本调研采用的处理原则 | 可核实实例 |
|---|---|---|
| 感染日、发病日、采样日、报告日 | 保留原始时钟；只有同口径同区间才比较 | 天津附件按发病日；NYC按事件类型日期；Wisconsin部分校外按收到结果日，见对应分册 |
| 病例人数、阳性检测次数、检测次数、受检人数 | 分列，检查去重与重复检测；测试量不当人口分母 | [Duke分类检测](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm) |
| 新增、累计、active、现患 | 不相加、不互换；累计差分保留回补与间隔 | [CSDH定义差异](https://www.covidschooldatahub.com/methods)、[1978寄宿学校卧床人数](https://www.reconverse.org/outbreaks/reference/influenza_england_1978_school.html) |
| 每日有行与每日有真实观测 | 前向填充/插值单独标记，不视作新观测 | [U02 README](https://github.com/wadefagen/college-covid19-dataset)明确说明填充 |
| 入院事件、在院人数、床位占用 | 按流量/存量分别匹配；不能互作替代 | [ECDC医院字典](https://www.ecdc.europa.eu/en/publications-data/download-data-hospital-and-icu-admission-rates-and-current-occupancy-covid-19)、PH02/PH13 |
| ILI/ARI、实验室确诊、污水、抽样阳性率 | 作为不同观测类型，分别评价；不能拼成单一daily cases | S03、S05、X02、PH06、PH18 |
| 缺测、隐私抑制、真实零 | 分别编码；缺失不填作零病例 | [CSDH方法及各州Data Details](https://www.covidschooldatahub.com/methods) |
| 网站停更与文件仍公开 | 记录文件可取状态与最后观测日期 | PH01 NYC、PH19 JHU、P05 Google Mobility |
| 公开代码、仿真输出、实测数据 | 查看Data Availability，分别登记 | [Cornell原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764692/)说明实测原始监测记录不开放 |
| 校园、医院系统和所在城市 | 保存适用范围；社区含校园者不重复相加 | U11 UCSD、X02 UC Davis及PH系列；UC Davis Health CORDS受协议限制 |

已整理的数据采用统一长表，保留`source_id/source_url/source_locator/raw_value`、机构与人群、观测范围、指标、时间依据、区间、单位及质量标记；原始下载和规范文件均记录SHA-256。人口与历史事件各自带来源URL，没有从病例反推或编造缺失信息。其余目录候选尚未全部转成统一观测表，状态见[数据包说明](../README.md)。

## 7．本轮核查与仍存在的获取缺口

- **实际文件核查与落地**：保留公开原始文件及下载清单；8组一般提取加32份CSDH病例文件形成40个数据集。CSDH教学、口罩与分母另行整理；Cambridge只规范化指定聚合面板。所有输出逐行保留出处，没有将公开代码或模拟结果冒充实测病例。
- **官方HTML表核查**：Wisconsin两版已解析并逐单元核对；2020版学生137日日表合计3,704阳性/136,584测试，与原网页页脚差7/242，未人为补平。春季页面实际追溯至2020-08-07，按跨年日期保存。
- **源质量问题**：8处日期逆序/非数值单元格隔离；119,155条CSDH受抑制/区间值保留原字符串和缺失数值；Florida部分年份疑点单独标记，不自动修年或用于日历导出。详见数据包质量说明。
- **目录/报告核查**：其余按详表区分有下载入口、仅论文图表、受限或本轮无法读取。Ohio State Excel、Illinois K–8下载、部分退休大学dashboard及超大跨校CSV仍有获取/全量核查缺口；没有据此虚报字段或日期。
- **时效核查**：CDC旧日表链接本轮为404，周表访问不稳定；ECDC ERVISS当前GitHub下载更新暂停；香港CSV超时。相关替代入口和官方说明已写入PH分册。
- **可复核性**：四分册交叉核对学校范围、重复来源、数字分母和日期类型；数据包提供离线构建、哈希/逐行校验、CEMAS长表读取及显式宽表适配，并进行了真实数据导入与相关测试。仅新增调研、数据整理和读取模块，没有修改传播模型、依赖、控制协议或原有Notre Dame重建数据。

对当前校园ABM研究，资料准备的首选是 **Wisconsin官方日表或UIUC保存CSV配官方历史公告**；多校园验证可用U02按校筛选；扩大到学校场景时，**CSDH**最接近病例、教学模式与人口标识可配套的一站式来源。若研究流感或希望纳入中国学校历史事件，**天津S1附件**是已核实能直接读取的短窗口材料。各选项的适用范围及限制已在上述目录保留。

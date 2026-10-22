# 公开历史疫情数据调研：地方卫生部门、政府门户与国际监测系统

核查日期：2026-10-15。此文件收录 **20 个数据源/监测系列**，以公开汇总数据为主，作为校园模型的社区背景、外部输入或更大范围模型的验证资料。除另行说明，**均不是单个校园的真实感染者全集，也没有个人接触网络**。

后续已将NYC、意大利全国及额外的上海作者片区序列保存并规范化，实际日期、字段、质量标记与系统读取方法见[数据包](../README.md)。其余目录的下载限制仍分别保留，没有声称已完整导入20组监测源。

“适合 ABM”是研究用途判断：高表示有较细地域及多个观测指标；中表示适合区域总量/外部背景验证；辅助表示仅能验证部分观测输出。该判断不表示能从汇总病例唯一识别模型参数。以下日期优先采用官方明确的历史窗口；未逐条下载计算的首末观测日已注明，**发布日期、最后更新日不冒充观测截止日**。网页确认有下载入口与实际完成全量下载分别表述。

## 一、地方/城市与国家政府数据

### PH01 — 美国纽约市 NYC Health：官方 COVID-19 CSV 历史仓库

- **范围与覆盖**：纽约市及行政区、部分 ZIP/社区、年龄等分层。直接读取 `trends/data-by-day.csv` 确认事件日为 **2020-02-29—2025-10-13**，末期有 `INCOMPLETE` 标记；README 所写 **2020-03-17—2025-10-15** 是另一历史展示窗口，不能冒充该CSV首末日。仓库于 **2026-05-21 归档**，历史仍公开。[原始CSV](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/trends/data-by-day.csv)、[官方README](https://github.com/nychealth/coronavirus-data)
- **类型/获取**：按事件日的病例、住院、死亡；检测量/阳性率、年龄和种族等表及历史更改说明。CSV 可直接获取，例如 [data-by-day.csv](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/trends/data-by-day.csv)；[目录和字段说明](https://github.com/nychealth/coronavirus-data/tree/master/trends)。同一仓库不同表具有不同截止时间，不能将 2025-10-15 套给检测量表。
- **措施时间线**：有**监测规则变更日志**，不是完整社会措施时间线。2023-06-01 起，因阴性结果报告要求改变，多个检测率和阳性率表停止更新；2023-05-11 后实验室仅须报阳性。其 README 还记录早期检测限制和抗原检测引入。[官方技术说明](https://github.com/nychealth/coronavirus-data#update-on-june-1-2023)
- **ABM适用性：高，城市/社区验证；校园背景**。优点是多输出、多地域、事件日和报告日区别清楚。限制是住址不等于感染地点，家庭自测不完整，群体设施病例可能影响社区趋势；缺学校成员分母和接触关系。[口径限制](https://github.com/nychealth/coronavirus-data#key-technical-notes)

### PH02 — 美国纽约州 Health Data NY：医院级历史住院与床位

- **范围与覆盖**：纽约州各报告医院。官方日数据表 **2025-10-07 归档**，页面预览最后可见观测为 2025-10-06；**首条观测日未在本轮核实**，页面建档日 2021-10-15 不应当作首个住院观测日。[官方数据及字典](https://health.data.ny.gov/Health/New-York-State-Statewide-COVID-19-Hospitalizations/jw46-jpb7/data_preview)
- **类型/获取**：医院日住院存量、新入院、出院、死亡、ICU、床位；后期区分因 COVID 入院与伴随阳性。Socrata 导出 CSV/API，可从页面 Export 或 [CSV导出](https://health.data.ny.gov/api/views/jw46-jpb7/rows.csv?accessType=DOWNLOAD) 获取；本轮核实元数据和预览，未完成全量下载。
- **措施时间线**：主要是**报表制度变更**：2023-10-13 起部分年龄、插管等字段不再更新；2025-10 从日到周报告，官方页链接继任周表。[变更说明](https://health.data.ny.gov/Health/New-York-State-Statewide-COVID-19-Hospitalizations/jw46-jpb7/data_preview)
- **ABM适用性：中，医疗结局验证**。医院地域和年龄字段有价值；但医院服务人群不等于医院所在县人口，年龄字段存在停更，不能把住院存量当新增住院事件，也不能直接当校园病例。

### PH03 — 美国 Massachusetts DPH：病例、检测和住院归档

- **范围与覆盖**：州级及部分县、市镇和人群分类。归档按 **2020–2021、2022–2023、2023–2024、2024–2025、2025–2026** 分组，早期为日/周报，后期为呼吸道季。具体文件首末日期需逐表读出。[官方归档索引](https://www.mass.gov/lists/archive-of-covid-19-data-in-massachusetts)
- **类型/获取**：历史病例、检测、阳性率、住院、死亡及人口学/地理分层；官方提供 Excel 数据与 PDF 报告。旧时段目录与后期工作簿组织不同，不能视为统一 schema。[官方数据说明及新旧衔接](https://www.mass.gov/news/department-of-public-health-launches-new-viral-respiratory-illness-dashboards)
- **措施时间线**：病例表不附完整措施；可拼接州档案馆 **MEMA COVID-19 Response Command Center situation reports**，其中有措施和事件背景。[州档案馆报告集](https://digitalarchives.sec.state.ma.us/uncategorised/SO_23861e77-279d-4cc0-8edf-9943628b2db4/)
- **ABM适用性：高，州内社区及大学所在地背景**。多指标和市镇尺度有利于大学与社区联动验证；但不能把市镇总病例作为大学成员病例。官方明确不同时期的数据元素、组织方式发生变化；后期自测遗漏削弱病例可比性。[归档口径提示](https://www.mass.gov/lists/archive-of-covid-19-data-in-massachusetts)

### PH04 — 加拿大 Ontario：Status of COVID-19 cases 与 PHU 数据

- **范围与覆盖**：安大略省及 Public Health Unit。**Status 主 CSV 为 2020-01-26—2023-04-04**；PHU 每日变化文件为 **2020-03-24—2024-06-04**；新口径累计死亡文件为 **2020-04-01—2024-11-07**，三者不是同一观察窗口。[官方目录、资源日期和字典](https://data.ontario.ca/en/dataset/status-of-covid-19-cases-in-ontario)
- **类型/获取**：每日检测量、累计检测、检测结果、病例转归、当前住院/ICU/呼吸机、长期照护病例/死亡、PHU 新增；CSV 与 XLSX 字典。[加拿大联邦门户镜像目录](https://open.canada.ca/data/en/dataset/f4f86e54-872d-43f8-8a86-3892fd3cb5e6)
- **措施时间线**：含**监测变化说明**：主系列 2023-04-13 停止；死亡统计在 2022-03-11、2022-12-01 改口径，2023-11-30 回补历史；完整检测资格/返校政策须另接省政府公告。上述停更日期不等于每个文件最后一行日期。[官方方法与停更说明](https://data.ontario.ca/en/dataset/status-of-covid-19-cases-in-ontario)
- **ABM适用性：高，省/PHU级；校园背景**。病例、检测和医院指标可共同解释观测变化；缺点是文件多且死亡口径有断点，数据库会清理回补。PHU 范围较大学园，不能单凭 PHU 表校验校内传播结构。

### PH05 — 英国 UKHSA：旧 Coronavirus Dashboard 全量存档

- **范围与覆盖**：英国各国及不同指标支持的地区、UTLA/LTLA、年龄等。覆盖疫情早期 **2020 年至旧 dashboard 退役前**；**每个指标末日不同，未把 2024-03-12 存档发布日当观测末日**。[官方存档页](https://ukhsa-dashboard.data.gov.uk/covid-19-archive-data-download)、[存档上线公告](https://ukhsa-dashboard.data.gov.uk/whats-new/covid-19-archive-data-download-added-to-the-dashboard)
- **类型/获取**：病例、死亡、Healthcare、Testing、Vaccination；可按类别下载 ZIP，全部约 1.4 GB。新平台另有 [官方 JSON API 示例和年龄/性别筛选说明](https://ukhsa-dashboard.data.gov.uk/access-our-data/examples)；旧 API 地址不应当作长期唯一入口。
- **措施时间线**：存档本身主要是观测数据；检测政策与全国措施需接官方历史报告。数据页强烈建议按 specimen date/death date 而非 publish date 分析。[官方解释与完整性说明](https://ukhsa-dashboard.data.gov.uk/covid-19-archive-data-download)
- **ABM适用性：高，地区/年龄验证；与校园所在地拼接**。多指标和 LTLA 细尺度是优点；**2020-10 部分 LTLA 数据缺失或插补、2021-02 部分 UTLA 年龄疫苗数据缺失**，官方也无法完全验证存档与退役前最新版一致，必须保留这些标记。[缺失表清单](https://ukhsa-dashboard.data.gov.uk/covid-19-archive-data-download)

### PH06 — 英国 ONS：COVID-19 Infection Survey（CIS）

- **范围与覆盖**：私人住宅家庭抽样调查，英格兰估计从 **2020-04-27** 开始；各组成国加入时间不同。最终周报 **2023-03-24 发布**，最终参考周英格兰/威尔士/苏格兰为 **2023-03-07—03-13**，北爱尔兰为 **03-01—03-07**。[首期调查说明](https://blog.ons.gov.uk/2020/05/14/new-survey-results-provide-first-snapshot-of-the-current-number-of-covid-19-infections-in-england/)、[最终周报](https://backup.ons.gov.uk/wp-content/uploads/sites/3/2023/03/Coronavirus-COVID-19-Infection-Survey-UK-24-March-2023.pdf)
- **类型/获取**：感染阳性比例及区间、地区/年龄/学年组；历次数据集提供 XLSX。此处是**抽样患病率估计**，不是常规报告的每日新增病例。[历史数据集入口](https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/conditionsanddiseases/datasets/coronaviruscovid19infectionsurveydata)、[最终结果与数据入口](https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/conditionsanddiseases/bulletins/coronaviruscovid19infectionsurveypilot/24march2023)
- **措施时间线**：无完整措施时间线；有方法和调查变更说明，2023 年 3 月中旬暂停采样。[官方监测项目说明](https://www.gov.uk/government/publications/covid-19-surveillance/covid-19-surveillance)
- **ABM适用性：高，社区患病率外部验证；大学生年龄组背景**。相较就诊检测数据，抽样设计能提供独立证据；但排除机构性场所，**不能代表宿舍/校园总体**，模型输出必须先转换成可与调查比较的家庭人群阳性比例和年龄范围。

### PH07 — 香港 CHP / DATA.GOV.HK：COVID-19 历史数据组

- **范围与覆盖**：全港汇总 COVID-19 数据；门户明确数据源文件最后更新为 **2023-03-19**。疫情早期至该日的各表起始日不同，本轮未逐表确认首日。[政府门户与数据字典](https://data.gov.hk/en-data/dataset/hk-dh-chpsebcddr-novel-infectious-agent)
- **类型/获取**：病例与本地疫情汇总 CSV、检测统计等；例如 [reported cases CSV](https://www.chp.gov.hk/files/misc/latest_situation_of_reported_cases_covid_19_eng.csv) 与 [检测统计 PDF](https://www.chp.gov.hk/files/pdf/statistics_on_covid_19_testing.pdf)。门户标记 API 可用；本轮 CSV 请求超时，故**确认官方资源登记，未确认完整下载成功**。只需汇总表，无须使用其楼宇/交通清单。
- **措施时间线**：可精确拼接教育局 **2023-01-20** 函：1/30 停发隔离令，但学生每日返校前 RAT 暂维持至 2/28。该函范围为中小学/幼儿园等，**不能直接套到高校**。[教育局原函](https://www.edb.gov.hk/attachment/en/sch-admin/admin/about-sch/diseases-prevention/edb_20230120_eng.pdf)；高校可另接 [HKU 教学与校园安排公告](https://covid19.hku.hk/latest-announcement/)。
- **ABM适用性：中至高，城市背景及历史观测规则重建**。优点是中英文官方资源、措施可外联；限制是报表和检测制度变化大，汇总病例不含校园成员分母、非完整感染数或接触网络。

### PH08 — 日本 MHLW：旧全数报告开放数据

- **范围与覆盖**：全国与都道府县；**2020 年疫情早期—2023-05-07/08 的旧全数报告阶段**，具体文件报告日与数据日有差别。5/8 后转为周度定点报告，不能简单拼成同一个每日确诊序列。[官方历史与制度切换页](https://www.mhlw.go.jp/stf/covid-19/kokunainohasseijoukyou.html)
- **类型/获取**：[每日新增阳性 CSV](https://covid19.mhlw.go.jp/public/opendata/newly_confirmed_cases_daily.csv)、[需住院治疗等人数 CSV](https://covid19.mhlw.go.jp/public/opendata/requiring_inpatient_care_etc_daily.csv)、[累计死亡 CSV](https://covid19.mhlw.go.jp/public/opendata/deaths_cumulative_daily.csv)，PCR人数/件数也在 [官方开放数据页](https://www.mhlw.go.jp/stf/covid-19/open-data.html)。本轮点击前三个资源得到二进制 CSV 内容类型，浏览器解析器不展示行，未核算首末行。
- **措施时间线**：开放页有统计来源变更及日期解释，特别是 **2022-09-28 后部分 PCR 日期口径偏移一天、9/27 显示零**；2023-05-08 五类化及定点切换有官方说明。[PCR口径注释](https://www.mhlw.go.jp/stf/covid-19/open-data.html)、[切换说明](https://www.mhlw.go.jp/content/10900000/001108598.pdf)
- **ABM适用性：中，县级/国家和医疗结局；大学社区背景**。数据标准、机器可读是优点；“需住院治疗等”不可自动解释为实际住院存量，PCR人数与件数需区分，缺个体网络和大学成员分母。

### PH09 — 澳大利亚 NSW Health / Data.NSW：本地病例历史

- **范围与覆盖**：新南威尔士州 postcode、LGA、LHD；门户 **2020-03-29 建档**，**2023-10-20 起停止更新**。建档日不代表首例观测；旧位置病例文件于 **2022-02-07 停止**，新 aggregated 文件另有窗口。[官方数据集及各资源停更说明](https://data.nsw.gov.au/data/en/dataset/covid-19-cases-by-location)
- **类型/获取**：按通知日期和居住地域的确诊病例，资源为 CSV/Data API。官方已作隐私聚合/抑制，缺失地域的病例不进入该表；单表没有保证同步检测总量和住院。[官方字段/限制](https://data.nsw.gov.au/data/en/dataset/covid-19-cases-by-location)
- **措施时间线**：主病例表无完整措施；可接 [NSW 呼吸道监测报告档案](https://www.health.nsw.gov.au/Infectious/covid-19/Pages/reports.aspx) 补监测背景与住院/检测指标。
- **ABM适用性：高，地方社区曲线；校园外部背景**。细地域和日通知日期便于匹配大学所在 LGA；缺点是居住地不等于感染地、通知日不是感染日、时序会修订，2022 前后文件和病例检测制度改变。

### PH10 — 意大利 Protezione Civile：官方区域/省 CSV、JSON

- **范围与覆盖**：全国、region、province；已直接读取官方首日文件 **2020-02-24**，全国 `latest.csv` 当前观测日期为 **2025-01-08T17:00:00**。本轮未逐行核算所有地区表端点，不能把全国末日套给每个文件，也不能把 README 仍写的“每日更新”认定为截至 2026 仍逐日提供新观测。[官方首日文件](https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-andamento-nazionale/dpc-covid19-ita-andamento-nazionale-20200224.csv)、[全国latest文件](https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-andamento-nazionale/dpc-covid19-ita-andamento-nazionale-latest.csv)、[官方仓库](https://github.com/pcm-dpc/COVID-19)
- **类型/获取**：病例、检测、住院/ICU/死亡等（地区级与省级字段不相同）。[全国全历史 CSV](https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-andamento-nazionale/dpc-covid19-ita-andamento-nazionale.csv)、[地区全历史 CSV](https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-regioni/dpc-covid19-ita-regioni.csv)、[官方字段字典](https://github.com/pcm-dpc/COVID-19/blob/master/dati-andamento-covid19-italia.md)。
- **措施时间线**：仓库提供措施区域的 GeoJSON/Shapefile 与元数据，可作部分措施范围拼接；不是全部学校政策。[措施区域数据说明](https://github.com/pcm-dpc/COVID-19/blob/master/dati-aree-covid19_EN.md)、[更改日志](https://github.com/pcm-dpc/COVID-19/blob/master/CHANGELOG_EN.md)
- **ABM适用性：高，地区级多输出验证**。机器可读、多尺度且有备注；省级并不拥有地区级全部医疗指标，年龄/接触结构须另补，累计值差分需处理回补。

### PH11 — 新加坡 MOH / data.gov.sg：COVID-19 Weekly Stats

- **范围与覆盖**：全国。门户摘要标为 **2023-01—2024-01**，但病例和入院资源预览最早可见 **2023-W09**；本轮未逐行验证其全部 52 周端点，**不能仅凭月份摘要判定含 2023 年 1 月病例**。[病例资源](https://data.gov.sg/datasets/d_11e68bba3b3c76733475a72d09759eeb/view)
- **类型/获取**：估计感染数 `est_count`、新住院/ICU入院、平均在院和ICU床位使用等 CSV/API。病例与入院两个已核实资源最后更新 **2024-06-06**。[新入院和ICU资源](https://data.gov.sg/datasets/d_98e8d8ba612a748413c439550c3c6942/view)、[病例API](https://data.gov.sg/api/action/datastore_search?resource_id=d_11e68bba3b3c76733475a72d09759eeb)
- **措施时间线**：这些统计 CSV 不附措施。人口分母、年龄和检测估计方法需另接 MOH/SingStat；数据页只有 `est_count` 时不能当实验室确诊人数。
- **ABM适用性：中，国家总量/医疗结局验证**。体量小、公开CSV可复核；周尺度和全国范围无法定位校园或社区网络，短历史窗口与估计口径需写入研究限制。

## 二、美国联邦公共卫生数据

### PH12 — CDC：Weekly United States COVID-19 Cases and Deaths by State（归档）

- **范围与覆盖**：美国各州/辖区疫情期至 **2023-05-10** 的汇总病例和死亡，周序列。CDC 明确新汇总上报 **2023-05-11 停止**，2023-06-01 最终校正历史；本轮未独立核实导出表的首周。[官方数据说明](https://data.cdc.gov/d/pwn4-m3yp/visualization)
- **类型/获取**：周病例/死亡、部分累计值；Socrata 目录与 Export/API。当前页面抓取和 JSON API 在本轮工具中未稳定返回数据，因此列为**官方历史入口已确认、下载需复核**。[目录页](https://data.cdc.gov/Case-Surveillance/Weekly-United-States-COVID-19-Cases-and-Deaths-by-/pwn4-m3yp)
- **措施时间线**：无州措施序列，但联邦报告变更可用 [CDC MMWR 2023监测变化报告](https://www.cdc.gov/mmwr/volumes/72/wr/mm7219e1.htm)。旧日表 `9mfq-cb36` 在本轮直接访问为 404，不应承诺该旧链接仍可下载。
- **ABM适用性：中，州级宏观复核**。优点是权威跨州汇总；弱点是尺度粗且随报告节律/口径变化。校园验证应优先当地/大学序列；不要把 CDC 与其上游州报告当独立观测。

### PH13 — HHS / HealthData.gov：州级医院利用历史时序

- **范围与覆盖**：美国州/辖区，官方说明历史追溯 **2020-01-01**；数据最后更新 **2024-05-03**，**该更新日不保证每州最后观测均为此日**。[HHS官方目录](https://healthdata.gov/dataset/COVID-19-Reported-Patient-Impact-and-Hospital-Capa/6xf2-c3ie/data)、[联邦目录方法说明](https://catalog.data.gov/dataset/covid-19-reported-patient-impact-and-hospital-capacity-by-state-timeseries)
- **类型/获取**：日级医院利用、COVID入院、在院/ICU等，CSV/Socrata；主目录包含 timeseries 链接和 [官方归档入口](https://healthdata.gov/d/4cnb-m4rz)。本轮确认目录，未下载所有州全部记录。
- **措施时间线**：有数据流切换：2022-12-15 前后 TeleTracking/NHSN 等来源转换；2024-05-01 后自愿报告由 CDC 系列承接。[官方来源说明](https://catalog.data.gov/dataset/covid-19-reported-patient-impact-and-hospital-capacity-by-state-timeseries)
- **ABM适用性：中至高，地区住院结局验证**。长日序列比单一病例序列多一个观测维度；但早期缺报、医院报告覆盖、住院原因及入院/在院定义需逐字段核对，不能直接与校园病例人数配对当统一人群。

### PH14 — CDC COVID-NET / RESP-NET：人群监测住院率

- **范围与覆盖**：COVID-NET 自 **2020-03-01** 起；当前 RESP-NET 是选定地区医院的人群监测，**不是全美所有医院普查**。当前官方页描述 14 州、最多194县、约12%美国人口，历史覆盖随期别改变。[当前RESP-NET与分母说明](https://www.cdc.gov/resp-net/dashboard/index.html)、[早期COVID-NET官方报告](https://archive.cdc.gov/www_cdc_gov/coronavirus/2019-ncov/covid-data/covidview/past-reports/08072020.html)
- **类型/获取**：实验室证实相关住院率，可按周/月/累计、年龄、性别、种族、site过滤；图表有表格视图。历史 COVID Data Tracker 存档可见 CSV 下载功能；当前 PowerBI 的完整批量导出本轮未验证。[仪表盘入口及操作](https://www.cdc.gov/resp-net/dashboard/index.html)、[历史指标和下载记录](https://stacks.cdc.gov/view/cdc/128705/cdc_128705_DS1.pdf)
- **措施时间线**：无完整措施；官方提供 surveillance/nowcast 方法。当前最近三周使用 nowcast，不能与最终观测率混为一类。[官方方法说明](https://www.cdc.gov/resp-net/dashboard/index.html)
- **ABM适用性：高，匹配覆盖区的年龄分层住院验证；其他地区为辅助**。提供明确监测分母与年龄层；但检测由临床医师决定，住院率未校正漏测，覆盖区变化需匹配历史分母，无校园身份。

## 三、国际和跨国数据库

### PH15 — WHO COVID-19 Dashboard：病例、死亡与住院下载

- **范围与覆盖**：国家/地区，病例/死亡监测从 **2019-12-31** 起；每日粒度主要适用于疫情早期，**2023-08 起 WHO 不再要求每日上报**，当前另提供周数据。住院、ICU和年龄死亡起止依国家而异。[WHO官方数据页及来源](https://data.who.int/dashboards/covid19/data)
- **类型/获取**：日/周新增病例与死亡、周新住院/ICU、月年龄死亡及疫苗历史；页面有各自 Download。不能假定所有国家都有住院或年龄明细。[官方下载与数据解释](https://data.who.int/dashboards/covid19/data)
- **措施时间线**：主要是上报/来源转换说明；2024 年另有分目标组疫苗政策数据，不等于全部检测、隔离或教学措施。措施需外联官方事件/政策库。
- **ABM适用性：中，国家级背景或跨地区结果复核**。全球范围、标准入口是优点；病例按**报告日**、住院按入院日期，国家检测/报告制度不同，部分国家转为哨点，校园/小社区验证不足。[官方口径](https://data.who.int/dashboards/covid19/data)

### PH16 — ECDC：Archived COVID-19 datasets

- **范围与覆盖**：EU/EEA为主，早期另有全球数据。全球日病例/死亡历史截止 **2020-12-14**，全球周系列截止 **2022-06-20**；EU/EEA病例/死亡与住院系列最终含 **2023-W47**，**2023-12-01 停更**。各国家起始日不同。[归档总目录](https://www.ecdc.europa.eu/en/covid-19/data)、[病例周率档案](https://www.ecdc.europa.eu/en/publications-data/data-national-14-day-notification-rate-covid-19)
- **类型/获取**：周检测量/阳性率、病例/死亡、日或周住院/ICU入院与存量、疫苗等；CSV/XLSX/JSON。可从 [开放数据文件目录](https://opendata.ecdc.europa.eu/covid19/) 定位原文件。[检测数据说明](https://www.ecdc.europa.eu/en/publications-data/covid-19-testing)、[住院数据及字典](https://www.ecdc.europa.eu/en/publications-data/download-data-hospital-and-icu-admission-rates-and-current-occupancy-covid-19)
- **措施时间线**：归档另含 **country response measures**，但不一定含高校措施；可通过总目录获得。检测分国家和地方的历史版本截止不同，subnational历史资源到 2022-09-11，不应与后来国家表混同。[归档索引](https://www.ecdc.europa.eu/en/covid-19/data)、[检测档案](https://www.ecdc.europa.eu/en/publications-data/covid-19-testing)
- **ABM适用性：中至高，区域/国家多指标历史验证**。下载格式丰富，死亡/住院/检测可拼接；限制是国家差异及部分网页抓取来源，跨国家比较或跨统计制度拼接需核对字典，粒度通常不足单校园。

### PH17 — ECDC / WHO Europe ERVISS：多呼吸道病毒周数据

- **范围与覆盖**：欧洲多国，流感、SARS-CoV-2、RSV等；各文件和国家历史窗口不同，本轮**未核实各表最早观测周**。[官方GitHub仓库](https://github.com/EU-ECDC/Respiratory_viruses_weekly_data)
- **类型/获取**：CSV文件与快照，包括初级医疗ILI/ARI、哨点检测阳性率、住院/严重结局等数据系列，实际字段依文件。[官方data目录](https://github.com/EU-ECDC/Respiratory_viruses_weekly_data/tree/main/data)
- **措施时间线/状态**：无完整措施时间线。当前官方告示：ERVISS 于 **2026-06-26** 在 TESSy→EpiPulse Cases 迁移后恢复发布，但因国家数据不一致正在排查，**GitHub下载数据更新暂停**。历史文件可用不等于下载源当前每周更新。[官方重要告示](https://github.com/EU-ECDC/Respiratory_viruses_weekly_data#important-notice)
- **ABM适用性：中，历史多病毒季节性/观测输出验证**。优点是共享结构与可追溯快照；限制是覆盖率、检测方法、监测制度与国家分母不同。ILI/ARI不是实验室确诊，部分国家咨询率分母不是每十万人，必须看官方方法。[官方一般说明](https://github.com/EU-ECDC/Respiratory_viruses_weekly_data)

### PH18 — WHO FluNet：长期流感病毒学监测

- **范围与覆盖**：全球国家/地区；系统 **1997 年上线**，不代表每国都从该年完整上报，各国实际首末周应从CSV核实；周度更新。[WHO FluNet官方页](https://www.who.int/tools/flunet/)
- **类型/获取**：检测标本和病毒检出/型别等周度病毒学数据；官网提供**全量CSV、CSV字典和筛选下载**。[官方全量下载入口](https://www.who.int/tools/flunet/)
- **措施时间线**：没有教学/隔离/检疫时间线，需接当地官方报告；未承诺内含住院、校园身份或接触网络。
- **ABM适用性：辅助至中，历史流感季节曲线和检测观测验证**。长历史、多国家和亚型信息是优点；采样来自监测实验室，不能将检出数当社区总感染事件。为校园流感模型提供外部季节背景，不能替代学校内部疫情曲线。

### PH19 — Johns Hopkins CSSE：全球/美国县 COVID-19 历史仓库

- **范围与覆盖**：全球国家/部分一级行政区，美国州/县；已直接读取全球累计病例CSV表头，日期列为 **2020-01-22—2023-03-09**；**2023-03-10 采集停止并归档**。其他文件边界应分别读表头核实。[原始全球病例CSV](https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv)、[官方停更声明](https://github.com/CSSEGISandData/COVID-19)
- **类型/获取**：累计病例/死亡和日快照；[全球病例CSV](https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv)、[美国县病例CSV](https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_US.csv)、[美国县死亡CSV及人口列](https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_deaths_US.csv)、[字段说明](https://github.com/CSSEGISandData/COVID-19/blob/master/csse_covid_19_data/README.md)。
- **措施时间线**：不含结构化措施，官方README提供长期使用过的数据来源名单与修改说明。它虽由大学维护，**不是 Johns Hopkins 校园疫情数据**。
- **ABM适用性：中，县/地区背景与历史复现**。格式稳定、使用广、便于与校园所在县拼接；测试、年龄、住院不统一，依上游公开数据，累计差分受修订影响，与WHO/CDC等非独立。其大学来源身份不能提高对校内传播验证的适用性。[官方来源清单](https://github.com/CSSEGISandData/COVID-19#covid-19-data-repository-by-the-center-for-systems-science-and-engineering-csse-at-johns-hopkins-university)

### PH20 — 中国疾控中心：全国新冠感染疫情情况（2022末—2023等历史报告）

- **范围与覆盖**：全国汇总（相关报告明示不含港澳台），非校园。已核实 **2023-01-25 报告**展示 **2022-12-09—2023-01-23** 的核酸阳性/阳性率，以及发热门诊、在院/重症/死亡等历史曲线；**2023-02-08 报告**延伸至 2/6。[政府保存的1/25报告PDF](https://eu.china-mission.gov.cn/chn/kjhz/kjdt/202301/P020230127830978025396.pdf)、[中国疾控2/8报告](https://www.chinacdc.cn/jksj/xgbdyq/202411/t20241112_302575.html)
- **类型/获取**：HTML/PDF文字、图表、关键点数值；本轮未发现与上述图表对应的官方逐日CSV。可作为已公布关键日期/峰值的验证证据，图像数字化所得数值必须标“重建估计”，不能标官方原始表。
- **措施时间线**：1/25报告明确说明 **2022-12-08 后不再全员核酸，转愿检尽检并对部分重点人群定期检测**，并说明检测量下降。[官方历史报告](https://eu.china-mission.gov.cn/chn/kjhz/kjdt/202301/P020230127830978025396.pdf)；卫健委自 **2022-12-25** 不再发布每日疫情信息，可用 [省卫健委转载国家卫健委说明](https://wjw.xinjiang.gov.cn/hfpc/fkxxfytzgg/202212/50577d9699644a999a88e33b62913390.shtml) 核验。
- **ABM适用性：辅助，全国总量和观测制度背景**。优点是官方明确公开检测、医疗曲线及其变化；限制是全国尺度、图表多于数表、观察过程突变，不适合作为大学日病例校准数据，不能把检测阳性数等同全部感染数。

## 四、可直接组合的研究资料包与边界

| 组合 | 观测结果 | 可补历史背景 | 适合的验证范围 | 主要缺口 |
|---|---|---|---|---|
| 美国大学公开dashboard + 当地NYC/MA/县序列 + 同期人口资料 | 校园阳性 + 社区病例/住院/检测 | 大学返校/教学公告 + 当地官方报告 | 校园曲线及社区背景分别验证 | 校园成员在社区病例中可能重复，校内接触网络通常另缺 |
| 英国校园/城市资料 + UKHSA地区存档 + ONS CIS | 地区病例/检测/住院 + 家庭人群患病率 | 官方监测方法、学校/高校公告 | 城市、年龄层和抽样阳性比例 | CIS私人家庭不覆盖全部宿舍，2020-10存档缺失/插补 |
| 香港CHP历史汇总 + 教育局函/具体大学公告 | 全港疫情与检测 | 学校RAT/隔离政策、具体大学教学变化 | 城市背景及已记录学校事件 | 中小学政策与高校范围必须区分；病例汇总不含大学分母 |
| Ontario Status + PHU文件 +医院表 | 检测、病例、住院和死亡 | 官方口径变更与省/学校历史公告 | PHU/省级或大学外部背景 | 文件窗口、死亡定义和检测资格不一致 |
| WHO/ECDC/FluNet等国家序列 +当地独立学校资料 | 国家/地区背景、流感检出 | 另接官方学校和卫生事件记录 | 大范围背景、季节曲线和外部一致性 | 不能用国家拟合优良证明校园接触结构正确 |

上述组合为**对公开数据用途的研究判断**，不是已完成拼表的数据产品。人口规模与年龄分布应采用同一地理边界、同一历史年份的官方人口资料；接触网络不能由病例汇总表补出。验证时保留病例/阳性检测/患病率/入院/在院之间的区别，并明确地理、人口、日期口径和实际监测制度。

## 五、获取与证据核查结论

- 已逐项核查官方网页/仓库、方法说明或官方资源登记；仅对明确读取到的观测窗口给出精确边界。**没有声称所有下载入口均已完成全量拉取**。
- 优先可操作来源：NYC GitHub、Ontario CSV、UKHSA ZIP、MHLW CSV、意大利官方GitHub、NSW CSV；WHO/ECDC/FluNet用于补国家/季节背景，ONS CIS用于独立患病率验证。
- 显著可访问性风险已单独标出：CDC旧日表404、CDC周表本轮工具访问不稳定、香港CSV超时、ERVISS GitHub下载更新暂停。它们不能被写成“已成功下载且当前完整更新”。
- 本文件没有抓取或保存任何可识别个人的病例、位置或接触记录；没有修改模拟代码或运行模型。

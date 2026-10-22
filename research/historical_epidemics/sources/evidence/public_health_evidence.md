# 公共卫生与社区历史数据：来源证据

核查日期：2026-10-15。范围为社区、地区、国家及政策辅助来源，校园专属数据另表。共16条。适用性、人口拼接可行性和优缺点中的分析性判断不应误当原始数据自带字段。

“已实读”指本次浏览直接读到原始文件或表头/末行；“目录核实”仅核实官方说明及下载入口，没有证明全量文件已成功取回。浏览工具返回内部错误不能证明源站失效。

推荐优先从PH01 NYC、PH09意大利DPC、PH10 RKI、PH11法国构建社区历史结果；PH08 ONS提供家庭社区流行率的额外验证；PH15/PH16补政策来源。聚合疫情表均不含个体接触网络。

## PH01 NYC DOHMH Coronavirus Data（官方归档）

- 范围/覆盖：美国纽约市社区；市/5区/部分MODZCTA，非校园专属。事件序列自2020-02-29；cases-by-day.csv实读至2025-10-13；发布页范围至2025-10-15；仓库2026-05-21归档。其他分表端点需分别确认。
- 类型/粒度：每日确诊/可能病例、住院、死亡、检测阳性率；周年龄/种族分层；地理分层；日×市/区；周×年龄等；邮区粒度依分表。
- 获取核实：公开GitHub CSV及README；本次实读病例CSV及文档。
- 措施：部分：README记录检测/口径变化；返校、隔离等需另接纽约州/市历史命令或学校公告。
- ABM：高：社区轨迹和大学所在地外部背景；年龄分层可作额外检验。不是校园内部病例数据。
- 优点：官方CSV、事件日期明确、多结局及分层、Git版本可冻结。局限：家庭自测漏报、不同结局时间滞后、小数抑制及人口口径；低检测时期病例不等于感染。

证据：[仓库README](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/README.md)注明发布页2020-03-17—2025-10-15，GitHub标2026-05-21归档；[trends说明](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/trends/Readme.md)说明日期/分层；[病例CSV](https://raw.githubusercontent.com/nychealth/coronavirus-data/master/trends/cases-by-day.csv)末行实读10/13/2025。事件序列起点与网页发布起点不同。

## PH02 CDC Weekly United States COVID-19 Cases and Deaths by State（归档）

- 范围/覆盖：美国州/辖区；非校园专属。官方目录标示2020-01-22至2023-05-10；已停更。目录元数据2026年刷新不代表新增病例覆盖。
- 类型/粒度：周新增及累计病例/死亡；确认/可能分类依字段；周×州/辖区。
- 获取核实：CDC Socrata pwn4-m3yp及HHS目录；已核对官方目录说明，本次未实读完整CSV。
- 措施：无完整措施表；可接OxCGRT州级数据和地方命令。
- ABM：中：州级趋势/背景强度；空间过粗，不足以单独验证校园ABM
- 优点：官方、跨州统一入口、长历史。局限：报告日口径、回补/修订、州际定义差异；周数据不能还原真实逐日感染；CSV下载尚待实读确认。

证据：[HHS镜像目录](https://healthdata.gov/CDC/Weekly-United-States-COVID-19-Cases-and-Deaths-by-/hiqp-x67x)搜索索引保留Temporal Applicability 2020-01-22/2023-05-10和archived标记；[CDC目录](https://data.cdc.gov/Case-Surveillance/Weekly-United-States-COVID-19-Cases-and-Deaths-by-/pwn4-m3yp)当前浏览正文仅壳页。该证据等级为目录说明核实，未实读CSV；不能据工具内部错误认定API已失效。

## PH03 CDC COVID-19 Case Surveillance Public Use Data with Geography

- 范围/覆盖：美国病例记录；州/县居住地及人口学，非校园专属。自2020-01；2024-07-05版本，2024-07-01终止新增病例监测报告；最后事件月份未实读核实
- 类型/粒度：19项匿名病例字段；case_month、州/县、年龄组、性别、种族/族裔、严重程度/结局等；记录级，但时间降为月（case_month）；地理字段可能抑制。
- 获取核实：公开Socrata n8mc-b4w4/HHS Data Hub；字段及版本通过官方目录/预览核实，未下载全量。
- 措施：无；需外接政策档案。
- ABM：中：分层结局/病例构成验证；低：逐日校园传播曲线
- 优点：公开微观字段及官方隐私/完整度文档。局限：大量Unknown/Missing/NA及抑制；时间仅月；个案报告不等于全部感染；不能把受限33字段版本说成公开。

证据：[CDC目录](https://data.cdc.gov/Case-Surveillance/COVID-19-Case-Surveillance-Public-Use-Data-with-Ge/n8mc-b4w4)索引给出2024-07-05版本；[官方预览](https://data.cdc.gov/d/n8mc-b4w4/visualization)显示case_month，证实时间为月。[HHS Data Hub](https://datahub.hhs.gov/CDC/COVID-19-Case-Surveillance-Public-Use-Data-with-Ge/x3vt-t6rt)说明公开19字段、公开无地理12字段、受限33字段是不同版本。停止新增报告2024-07-01见data.gov目录索引；最后事件月份仍未核实。不能将month表用于逐日波形。

## PH04 HHS COVID-19 Reported Patient Impact and Hospital Capacity by Facility（归档）

- 范围/覆盖：美国报告医院，机构所在地；非居民辖区或校园总体。官方说明2020-07-31起；2024-05-03后停更（数据页最后数据更新2024-05-02）；最后collection_week未实读确认
- 类型/粒度：周住院新入院/占床、ICU、成人/儿科、报告覆盖天数等；医院×周（日指标7日sum/avg/coverage）。
- 获取核实：官方data.gov目录提供CSV/JSON/XML下载；HealthData.gov uqq2-txqb及档案t7zc-4t6g；本次核对目录，未实读全量CSV。
- 措施：部分：官方说明报告制度终止；其他措施需外接。
- ABM：中至高：社区重症负担验证的第二结局；单校园重症常太少
- 优点：独立于病例检测的结局；覆盖天数可评估缺报。局限：小于4的sum/avg抑制为-999999；不填补缺报；医院转诊/服务范围偏差；部分机构类型排除。

证据：[data.gov官方目录](https://catalog.data.gov/dataset/covid-19-reported-patient-impact-and-hospital-capacity-by-facility-df0bc)说明2020-07-31起、2024-05-03后停更、周sum/avg/coverage、值<4抑制为-999999且不插补缺报；列出CSV下载。元数据July 2025更新时间不代表疫情事件数据到2025。

## PH05 WHO COVID-19 Dashboard Downloadable Statistical Releases

- 范围/覆盖：全球国家/地区；非校园专属。病例/死亡自2020年初；目前入口仍发布周历史序列，各国最新日期不同；2023-08起不再要求逐日报告。住院和年龄表各国覆盖另异。
- 类型/粒度：日报告病例/死亡、周病例/死亡、周住院/ICU、月年龄死亡、2021—2024历史疫苗表；国家/地区×日/周/月，取决指标。
- 获取核实：官方页面列机器可读下载；页面/定义已核对，本次未实读下载文件。
- 措施：部分：含2024疫苗政策（至Q3）；无完整检测/学校/隔离政策；需外接OxCGRT/CoronaNet。
- ABM：中：跨国背景和外部一致性；低：单校园定量验证
- 优点：权威、广覆盖、多结局、CC BY 4.0。局限：病例为向WHO报告日而非感染/发病日；国家缺报和监测转型明显；住院表可能含偶然阳性入院。

证据：[WHO下载与定义页](https://data.who.int/dashboards/covid19/data)列日/周病例死亡、周住院ICU、月年龄死亡，明说2023-08起不再要求日报；病例按报告日期，住院按入院日期；住院可能转哨点，国别完整性不同。[病例页](https://data.who.int/dashboards/covid19/cases)提供2020年初至现有周历史。直接下载在本次浏览工具返回内部错误，仅确认官方有下载入口。

## PH06 ECDC COVID-19 Archived Datasets + Response Measures

- 范围/覆盖：EU/EEA国家，部分历史次国家数据；非校园专属。多表2020年起；检测/住院等最终周2023-W47，2023-12-01停止更新；次国家检测历史至2022-09-11，2022-W37停收次国家病例；措施档案至2022-09。
- 类型/粒度：病例/死亡、检测量/阳性率、住院/ICU入院及占床、年龄分层、国家措施CSV；国家×日/周；部分次国家历史×周；措施事件起止日。
- 获取核实：官方档案页面及CSV/XLSX/JSON/XML链接；文档核对，CSV未全量实读。
- 措施：有（独立response-measures CSV，国家级；未穷尽地方措施）。
- ABM：中至高：欧洲社区/地区趋势与检测强度校验；国家尺度不代替校园验证
- 优点：多结局可拼接、官方数据字典、政策配套。局限：PCR/抗原及跨国定义差异；地方政策可能早于国家；多数据集停更时间不同。

证据：[档案目录](https://www.ecdc.europa.eu/en/covid-19/data)明说旧表停更。[检测说明](https://www.ecdc.europa.eu/en/publications-data/covid-19-testing)及[住院说明](https://www.ecdc.europa.eu/en/publications-data/download-data-hospital-and-icu-admission-rates-and-current-occupancy-covid-19)均明说2023-W47为最后周、12/1停止更新；检测页另明说次国家历史至2022-09-11。[措施页](https://www.ecdc.europa.eu/en/publications-data/download-data-response-measures-covid-19)保留CSV及局限，国家措施档案到2022-09，不是学校实际执行记录。

## PH07 UKHSA Data Dashboard及旧Coronavirus Dashboard历史入口

- 范围/覆盖：英国/英格兰及可用地区，地理覆盖依指标；非校园专属。历史指标含2020年（官方API示例PCR检测2020-02-08）；旧面板2023-12-21被新面板替代；每指标精确起止需查询，不能统一声称覆盖英国全期
- 类型/粒度：病例、PCR检测、阳性率、住院、死亡、疫苗等依指标；日/周×国家/地区/年龄等，依metric提供。
- 获取核实：新API、逐图下载、CSV/JSON bulk ZIP；已核对开发文档/下载页，未批量取回所有历史指标。
- 措施：部分：指标文档记录方法；学校/检测政策需接GOV.UK公告或OxCGRT。
- ABM：高（先确认目标地方历史指标）：社区/大学所在地背景和住院结局
- 优点：官方API字段明确，可按年龄/地区查询。局限：API可返回200+空数组，不能只按状态码判定可用；不同国家/时期/指标覆盖不一致；自愿检测偏差。

证据：[UKHSA API示例](https://ukhsa-dashboard.data.gov.uk/access-our-data/examples)展示2020-02-08 PCR检测、geography_code/age/sex字段，警告不存在的指标组合可能200+空数组；[bulk download](https://ukhsa-dashboard.data.gov.uk/bulk-downloads)有CSV/JSON ZIP；[官方迁移公告](https://ukhsa.blog.gov.uk/2023/12/21/ukhsa-data-dashboard-takes-over-from-the-coronavirus-covid-19-dashboard/)确认旧面板12/21/2023替换。未声称每个指标都有完整英国地方历史。

## PH08 ONS Coronavirus Infection Survey（CIS，历史）

- 范围/覆盖：英国私人家庭居民；排除医院、养老院及其他集体居住场所，不能直接代表大学宿舍。英格兰现场调查2020-04-26起，官方估计序列2020-04-27起；威尔士2020-06-29、北爱2020-07-26、苏格兰2020-09-21起。最终报告2023-03-24，最后参考周英/威/苏至2023-03-13、北爱至03-07。
- 类型/粒度：抽样PCR阳性流行率/估计人数及可信区间；地区/年龄；部分发生率与单岁分析；周为主×英国各构成国/地区/年龄；公开汇总Excel。
- 获取核实：ONS最终报告、relateddata及年度XLSX；页面/文档核对，未实读全部工作表。
- 措施：部分：2022-08转远程采样等方法变化；无完整干预措施表。
- ABM：高：家庭社区感染流行率的独立验证，减轻常规检测选择偏差；校园宿舍适用性低
- 优点：代表性抽样、区间估计、不同于报告病例的观测渠道。局限：模型平滑/修订和调查非响应；集体居住排除；最后采样窗潜在选择偏差；流行率不是每日新感染。

证据：[ONS最后报告](https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/conditionsanddiseases/bulletins/coronaviruscovid19infectionsurveypilot/24march2023)明确最后发布2023-03-24、各构成国起点和最后参考周；估计序列自2020-04-27。该页面明确范围为私人家庭，排除其他集体居住场所，并讨论2022-08远程采样变化及最后测试窗偏差。[年度数据入口](https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/conditionsanddiseases/datasets/coronaviruscovid19infectionsurveydata)有2020—2023 XLSX。宿舍外推限制是由其覆盖定义作出的适用性判断。

## PH09 意大利Protezione Civile DPC COVID-19

- 范围/覆盖：意大利全国/大区/省；非校园专属。2020-02-24起；latest全国CSV本次实读日期2025-01-08；README仍保留旧日更说明，不能据此称持续更新
- 类型/粒度：每日新增阳性、累计病例/死亡、居家隔离人数、住院/ICU占床、ICU新入院、检测/受检人数及PCR/抗原分类；日×全国/大区；省级主要病例。
- 获取核实：官方GitHub CSV/JSON+数据字典+勘误notes；已实读latest CSV。
- 措施：部分：疫情紧急状态背景、早期限制区域geojson和notes；完整学校/检测/隔离需接政府法令/OxCGRT。
- ABM：高：大区/省社区轨迹及多结局校验
- 优点：官方稳定仓库、多结局/测试字段、明确区域说明。局限：居家隔离为状态人数不是隔离实施政策日期；省级缺结局；报告修订和抗原纳入造成口径变化。

证据：[DPC数据字典](https://github.com/pcm-dpc/COVID-19/blob/master/dati-andamento-covid19-italia.md)给出20200224首文件；[latest CSV](https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-andamento-nazionale/dpc-covid19-ita-andamento-nazionale-latest.csv)实读为2025-01-08T17:00:00，含住院、ICU、隔离状态人数、测试及新阳性。README旧日更承诺不能证明2026仍更新。

## PH10 德国RKI SARS-CoV-2 Infektionen in Deutschland

- 范围/覆盖：德国县/柏林12区×人口学病例组；非校园专属。疫情历史病例（2020年起，精确首日未实读核实）；仓库仍发布完整当前快照并有历史快照档案。不能将快照更新日当感染末日。
- 类型/粒度：病例、死亡、康复；报告日Meldedatum、参考发病日Refdatum及是否真实已知发病；年龄/性别/县ID；病例组而非个体；县×日期×年龄组×性别。
- 获取核实：官方GitHub CSV及Zenodo版本化；README/字段已核对，未实读庞大CSV。
- 措施：无完整措施表；接各州法规/OxCGRT。
- ABM：高：社区年龄/地区/发病时序验证；15–34组不足以单独分出大学生
- 优点：明确发病日标志、人口分层、快照与修订可追踪。局限：自愿检测与漏报；报告日/未知发病日不可混淆；计数及NeuerFall修订规则需遵循；当前快照并非当时所知数据。

证据：[RKI README](https://raw.githubusercontent.com/robert-koch-institut/SARS-CoV-2-Infektionen_in_Deutschland/main/Readme.md)明说一行为病例组非个案，列Meldedatum/Refdatum/IstErkrankungsbeginn、年龄、性别、AGS；当前日快照覆盖此前全部上报数据并替换昨日文件，历史另归档。当前更新状态按文档说明；CSV首末日期未实读。

## PH11 法国Santé publique France / data.gouv.fr SI-DEP + SI-VIC

- 范围/覆盖：法国全国/大区/省，部分IRIS历史；非校园专属。SI-DEP从2020-05部署，旧目录2022-05-18停更并迁新格式；新测试目录2023-06-30最后更新。SI-VIC住院历史含2020年，精确首日未实读；声明日表2023-03停止，入院日表延至2023-06，2023-07制度转型。
- 类型/粒度：受检/阳性、发病/阳性率、年龄/性别；住院/ICU、新入院/死亡、年龄组，部分可分因COVID住院与伴随感染；日/周×国家/地区/省/年龄；部分IRIS分月文件。
- 获取核实：官方CSV+方法PDF；已核对旧/新目录与下载资源清单，未实读全量CSV。
- 措施：部分：文档明确检测去重、地域/人口分母更新、报告制度变化；学校措施需外接。
- ABM：高：地方社区多结局校验及检测观测；不能直接还原校园接触
- 优点：检测量与住院可拼接；方法变更记录具体。局限：旧目录只到2022-05，不应误报2023覆盖；2023-04住院口径/频率变化；SI-VIC死亡不直接证明死因为COVID。

证据：[旧SI-DEP页](https://www.data.gouv.fr/datasets/old-donnees-relatives-aux-resultats-des-tests-virologiques-covid-19)明说2022-05-18停更，测试系统2020-05-13部署，保留去重等变更；[新SI-DEP页](https://www.data.gouv.fr/datasets/donnees-de-laboratoires-pour-le-depistage-a-compter-du-18-05-2022-si-dep)最后更新2023-06-30，IRIS历史按月，2022-07地理/人口参考更新；[SI-VIC页](https://www.data.gouv.fr/datasets/donnees-hospitalieres-relatives-a-lepidemie-de-covid-19)记录2023-04改入院日/每周二五，2023-07制度终止及死亡归因局限。

## PH12 Johns Hopkins CSSE COVID-19（历史归档）

- 范围/覆盖：全球国家/部分省州及美国县；非校园专属。global confirmed CSV表头实读2020-01-22至2023-03-09；项目2023-03-10停止收集报告
- 类型/粒度：病例/死亡累计日序列；部分历史康复；美国死亡表有人口字段；日×国家/部分次国家/美国县（依文件）。
- 获取核实：公开GitHub CSV、原始来源名单及errata；已实读global confirmed表头。
- 措施：无措施时间线；仅数据异常/修订日志。
- ABM：中至高：地区背景和粗尺度轨迹；建议优先同辖区原始卫生部门作主验证
- 优点：格式成熟、跨国覆盖、冻结易复现。局限：多来源混合/回补、累计差分可为负；无测试分母及校园分层；跨源不等于独立验证。

证据：[CSSE README](https://github.com/CSSEGISandData/COVID-19)宣布2023-03-10停止收集；[global confirmed CSV](https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv)首末日期表头实读为1/22/20和3/9/23。这些是累计通报数，差分后的负值可能是修订，不能改写为负感染。

## PH13 The New York Times COVID-19 US Data（历史归档）

- 范围/覆盖：美国全国/州/县；另有校园与监狱独立目录。us.csv实读2020-01-21至2023-03-23；2023-03-24宣布停止日病例死亡更新
- 类型/粒度：每日累计病例/死亡、异常日与滚动均值；另有校园累计快照；日×全国/州/县；校园目录频率单独核对。
- 获取核实：公开GitHub CSV及说明；已实读US CSV首尾；CC BY-NC 4.0，需署名。
- 措施：无完整措施表；异常记录不是政策措施。
- ABM：高：校园所在地县级社区背景；校园目录另评
- 优点：县级长序列、FIPS明确、异常文档较丰富。局限：确认/可能定义不同；地理例外和回补；无测试分母；与JHU/官方病例往往同源。

证据：[NYT README](https://raw.githubusercontent.com/nytimes/covid-19-data/master/README.md)宣布3/24/2023停更，说明FIPS、确认/可能定义与非标准地理例外，以及CC BY-NC许可；[us.csv](https://raw.githubusercontent.com/nytimes/covid-19-data/master/us.csv)末行为2023-03-23。校园/监狱目录另有不同采集频率，不随此日表自动推断。

## PH14 The COVID Tracking Project（历史）

- 范围/覆盖：美国州/领地及全国；非校园专属。2020年至2021-03-07（各州指标首日不同）；该日后不再采集
- 类型/粒度：病例、PCR/抗原检测、住院/ICU/呼吸机、死亡；州元数据/原始来源与说明；另有种族/养老院资料；日×州/全国。
- 获取核实：公开CSV/API及定义、数据日志；已核对官方项目API/总表说明，未实读完整下载。
- 措施：部分：州数据说明可记录测试/报告口径变化；不是完整返校/隔离时间线。
- ABM：中至高：早期波次多结局/检测观测；空间粗，不直接验证校园内传播
- 优点：早期测试/住院字段丰富、保留州来源和定义。局限：tests计人/标本/检测事件口径混合；缺失严重度不同；仅覆盖疫情早期；非官方整理。

证据：[项目数据页](https://covidtracking.com/data/)明说3/7/2021后停止采集；[数据汇总页](https://covidtracking.com/about-data/data-summary/)和[API定义](https://covidtracking.com/data/api/)列州/全国检测与住院指标、state info及来源，区分people/specimens/encounters。网站可打开并列下载，未全量下载。

## PH15 Oxford COVID-19 Government Response Tracker（OxCGRT最终版）

- 范围/覆盖：185国家辖区及部分次国家/城市（compact含210次国家辖区）；不是校园实施记录。2020、2021、2022年；2023-06发布最终v1；已结束实时更新
- 类型/粒度：24政策指标、学校/工作关闭、检测、接触追踪、疫苗等；日政策强度及原始备注；日×国家/部分次国家；TOTAL/WIDE/GOV辖区区分。
- 获取核实：公开GitHub 27 CSV及codebook；compact/fullwithnotes/raw多版本；CC BY 4.0。
- 措施：有：建议fullwithnotes查原始依据；学校关闭指标不等同单校教学安排。
- ABM：高（背景措施标注）；不能单独作病例验证，也不能将政策指数直接当实际接触率
- 优点：跨地统一编码、来源备注、州级可配校园。局限：编码的是发布政策而非执行/遵从；取最严格政策时要看地理flag；次国家覆盖不齐；2023后需其他档案。

证据：[最终版README](https://github.com/OxCGRT/covid-policy-dataset)说明2020—2022、2023-06最终v1、185国家及210次国家compact、27 CSV和24指标；明说指数不能证明有效执行。[codebook](https://github.com/OxCGRT/covid-policy-dataset/blob/main/documentation_and_codebook.md)可核学校关闭、检测等指标、地理flags及vaccination状态版本，务必保留fullwithnotes来源。

## PH16 CoronaNet Research Project（已完成采集）

- 范围/覆盖：195国家及数百次国家单位；部分国家系统收集省/市政策。官网称主要覆盖2020-01至2021-12；部分更早事件自2019-12-31；政策强度得分仅2020-01-01至2021-05-01（与事件表不同）
- 类型/粒度：政策事件、宣布/实施/结束日期、发起者/对象、说明和来源URL；政策强度分数另表；事件×国家/省/市；部分日面板。
- 获取核实：官网资料入口、codebook、CoronaNetR公开API说明；本次核对入口/文档，未批量核验当前全部下载文件。
- 措施：有：返校/学校限制、检测、检疫等分类；结束日有缺失，需回原始文件核对。
- ABM：高（历史背景和具体措施来源追溯）；不是病例验证数据
- 优点：政策事件日期细、保留来源和对象、比单一指数更便于整理证据。局限：跨国完整性不均、政策结束日缺失、事件与强度表时段不同；官网旧模块仍有2020更新时间文字，应以具体版本为准。

证据：[官网](https://coronanet-project.org/)明说采集完成、主要2020-01—2021-12，事件表与强度分数的时段不同；事件带来源、对象、时间。[CoronaNetR](https://github.com/CoronaNetDataScience/CoronaNetR)文档显示date_announced/date_start/date_end并明说许多end date缺失。官网不同模块有旧更新文字，不能不加区分称持续周更。[ICPSR V1档案](https://www.openicpsr.org/openicpsr/project/120342/version/V1/view)为早期冻结版本，不冒充最终完整版本。

## 拼接与验证注意点

1. 校园所在地县/市疫情可作为校园周边背景，但校园学生本身可能已计入居民报告；不能把“校园+县病例”直接相加。
2. 病例报告、阳性测试、感染发生、阳性流行率、入院流量和占床存量是不同观测量。应在数据字典中分别保存日期类型、单位、时间窗、分母和报告覆盖。
3. 一个病例数据在JHU、NYT、CDC和地方卫生部门重复出现，不是四份独立验证；可把住院或抽样流行率作为额外结局。
4. 保存文件版本、获取日期、数据覆盖末日及原始政策链接；不要用元数据刷新日期代替疫情覆盖日期。
5. 本轮未重建真实联系人、未下载受限微观数据；人口分母/行政区拼接应在目标场景确定后核对官方相同年份和边界资料。


# 早期调研笔记（历史证据）

本文件保留2026-10-15早期58项调研时的判断和取证边界，文内获取状态是当时记录，后续整理结果以[任务入口](../../README.md)、[统一来源记录](../records.json)及下载清单为准。例如Duke旧tracker后来实测跳转新闻主页，未取得历史表。这里不作为另一套维护清单，也不作为构建输入；原始专题JSON中的字段已核对并入统一记录，Duke早期访问说明保存在 `access_at_initial_review`。

**校园与社区历史疫情公开数据调研**

核查日期：2026-10-15。研究目的：历史疫情重建和ABM校准、验证。范围优先高校，扩展到中小学、家庭/社区、邮轮/舰船，以及人口、接触、历史措施辅助资料。以COVID-19为主，另覆盖流感、麻疹、诺如病毒等历史基准。

本目录共收录 **58 项来源/候选**。这不是同等数量的“完整、可立即下载的疫情数据集”：部分是可读CSV/XLSX，部分仅有官方表格或图，部分仅提供网络/人口/政策，还有少量需恢复归档的线索。每项的获取状态分别记录。

原先生成的逐项目录、CSV和JSON已合并为[统一来源记录](../records.json)与[生成的可筛选清单](../catalog.csv)。CSV为UTF-8 BOM，方便Excel读取中文；JSON保留来源链接数组。各专题 `*_evidence.md` 提供额外证据。

**最值得先做的选择**

高校病例验证优先选 **Cambridge 2020、Duke 2020、Campus COVID Dataset中观测连续的学校**；需要尽快拿到一个日频CSV时，**Big Ten raw.csv** 可作起点，但应保留其累计/非每日观测属性。单一来源很少同时具备真实个体接触、病例和措施记录。以下“适用性”均为本调研基于公开字段和获取状态所作的研究判断。

| 来源 | 已核实覆盖 | 可用疫情信息 | 措施/背景 | 适用性与取舍 |
|---|---|---|---|---|
| [Cambridge论文和源数据](https://www.nature.com/articles/s41467-021-27942-w) / [XLSX](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-021-27942-w/MediaObjects/41467_2021_27942_MOESM7_ESM.xlsx) | 2020-10-05—12-06学期；部分周统计更宽 | XLSX已实读：周阳性病例、测序样本和部分分组；检测量另接官方周报 | 论文及官方筛查周报可拼接 | 高校优先；完整个体metadata/接触网络受限 |
| [Duke官方秋季归档](https://coronavirus.duke.edu/covid-testing-old/fall-2020-duke-covid-testing-tracker/) / [MMWR](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm) | 2020-08-02—11-20 | 周检测、阳性、隔离/检疫及累计 | 官方通报可拼扩容、住宿和教学变化 | 多结局好；HTML需整理，未确认统一CSV |
| [Campus COVID Dataset](https://github.com/jkbren/campus-covid) / [正式论文](https://journals.plos.org/digitalhealth/article?id=10.1371/journal.pdig.0000065) | 主集2020秋；MA 56校另有2021春 | 1,448校：971有时序，477仅累计；附人口/县背景连接表 | 教学模式文件C2i授权受限，另查校方公告 | 多校筛选优先；原dashboard口径不统一 |
| [Big Ten整理仓库](https://github.com/wadefagen/college-covid19-dataset) / [raw.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv) | 总范围2020-03-14—12-20，各校不同 | 原始不规则日期的累计检测/阳性 | 无，需回原校方来源 | 易取得；daily.csv为前向填充，不能当真实日新增 |
| [Cornell 2021秋研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC9118068/) | 2021-08-23—12-31 | 日病例图、阳性率和监测分组 | 有12月聚集限制、考试线上、离校检测日期 | 校园历史背景强；底层逐日CSV尚未取得 |
| [Notre Dame MMWR](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm) | 2020-08—10 | 日病例图、检测类型、住宿分组、隔离/检疫汇总 | 校方公告与CDC可互证 | 短期爆发案例好；日数多需图提取 |
| [Stanford历史页](https://healthalerts.stanford.edu/covid-19/stanford-covid-dashboards/stanford-covid-historical-dashboards) | 病例2020-03至2023-05中；分项目不同 | 学生/职工分表、病例、检测、隔离 | 有项目终止和方法日期 | 定义清楚；Tableau底表导出本次未核实 |
| [1978英国寄宿男校](https://reconverse.r-universe.dev/outbreaks/doc/manual.html) | 1978-01-22—02-04数字化序列 | 每日卧床/康复期状态人数、763男生分母 | 原报告描述隔离、疫情经过 | 经典学校基准；不是daily incidence或累计已康复，序列短 |
| [Derbyshire 2001诺如学校](https://reconverse.r-universe.dev/datasets) | 2001夏季，22个相对日 | 492名儿童班级、症状及缺勤表 | 有相对日清洁/停课记录 | 同群结构和症状兼有；病种机制不同且日历日未核 |
| [Tomsk 2015/16](https://zenodo.org/records/2992179) / [论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC6613079/) | 2015/16流感季；2016接触日记 | 日记接触、社区ARI/流感周曲线 | 同季真实停课及其他事件 | 可拼行为与社区结局；并非逐人配对感染，曲线底表待核 |
| [NYC卫生局](https://github.com/nychealth/coronavirus-data) | 日病例CSV 2020-02-29—2025-10-13 | 病例、检测、住院、死亡、年龄/地理分层 | 部分方法变化；完整措施另接 | 社区优先；不是校园数据，家庭自测漏报 |
| [意大利DPC](https://github.com/pcm-dpc/COVID-19) | 2020-02-24起，latest实读2025-01-08 | 日病例、检测、隔离状态、住院/ICU/死亡 | 部分方法记录；完整措施另接 | 多结局强；不是每省都有全部字段 |
| [上海作者CSV](https://github.com/junlingm/Shanghai-COVID-19-Mar-June-2022) / [论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10194905/) | 实读2022-03-19—06-26 | 作者两个片区的确诊+无症状逐日报告 | 论文列03-28、04-01、04-04历史节点 | 中文场景的直接CSV；片区不是简单行政区，无检测分母 |
| [ONS Infection Survey](https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/conditionsanddiseases/datasets/coronaviruscovid19infectionsurveydata) | 英格兰估计2020-04-27起，至2023-03；各构成国不同 | 抽样阳性流行率、年龄/地区及区间 | 方法调整可查；无完整措施表 | 独立社区观测渠道；排除集体居住，不能代表大学宿舍 |
| [Diamond Princess官方报告](https://id-info.jihs.go.jp/niid/en/2019-ncov-e/9417-covid-dp-fe-02.html) | 2020年1—2月；本表已知发病日子集02-06—17 | 发病表、PCR、年龄、乘客/船员 | 检疫/检测对象变化日期详细 | 封闭场景对照；离船使分母变化，非高校年龄结构 |

**人口、结构、接触和措施分别能补什么**

| 需要补充的信息 | 可用来源 | 可以支持的判断 | 必须保留的边界 |
|---|---|---|---|
| 美国高校人数、学生层次、职工及机构特征 | [IPEDS官方按年CSV与字典](https://nces.ed.gov/IPEDS/use-the-data) | 同期学校人口结构/注册分母 | 年度注册数≠实际驻校数≠筛查队列 |
| 社区年龄/家庭/集体居住 | [Census/ACS API](https://www.census.gov/programs-surveys/acs/data/data-via-api.html) | 与州县地理码匹配人口、住房和年龄分母 | 5年产品是多年度估计；年份和边界要一致 |
| 学校班级接触 | [SocioPatterns小学](https://sociopatterns.org/datasets/primary-school-temporal-network-data/) / [高中2013](https://sociopatterns.org/datasets/high-school-contact-and-friendship-networks/) | 20秒邻近、班级混合、网络抽样检查 | 无同群真实病例，短期校内数据，不可称完整疫情验证 |
| 大学生全天邻近及多层网络 | [Copenhagen公开4周子集](https://figshare.com/articles/dataset/The_Copenhagen_Networks_Study_interaction_data/7267433/1) | 大学新生接触/通信结构 | 起始日匿名，仅相对时间，无病例；完整GPS/问卷不在该子集 |
| 一般人口按年龄/场所接触 | [POLYMOD作者CSV](https://zenodo.org/records/1215899) | 接触统计和外部参照 | 2005/06欧洲抽样日记，不是2020高校实测网络 |
| 检测/学校关闭/其他措施背景 | [OxCGRT最终版](https://github.com/OxCGRT/covid-policy-dataset) / [CoronaNet](https://coronanet-project.org/) | 按地区、日/事件查政策编码和原始依据 | 政策发布≠执行/遵从，国家学校关闭≠每所大学教学安排 |
| 国家停课/复课历史 | [UNESCO](https://www.unesco.org/en/covid-19/education-response) | 2020-02—2022-06教育系统背景 | 下载尚待取回核实；单校安排应以校历/校方公告为准 |
| 社区活动变化 | [Google历史Mobility](https://www.google.com/covid19/mobility/) | 地区日活动的辅助对照 | 相对访问百分比≠真实接触边或接触率；2022-10-15停更 |

**可落地的多源拼接方案**

1. **Cambridge 2020**：以公开Source Data XLSX中的同一学期周阳性病例及样本/分组统计作为观测主表；检测量另接[官方筛查周报](https://www.cam.ac.uk/sites/www.cam.ac.uk/files/documents/uoc_screening_report_week_8_-_2020-11-29.pdf)，并用周报和论文记录的筛查变化作事件背景。校园人口/学院结构来自同一论文；周边社区只能接相应地区的[UKHSA历史指标](https://ukhsa-dashboard.data.gov.uk/bulk-downloads)。这可验证周病例和部分分组，公开资料不足以恢复全员真实接触网。

2. **Duke 2020**：以[官方秋季HTML归档](https://coronavirus.duke.edu/covid-testing-old/fall-2020-duke-covid-testing-tracker/)及逐周通报整理病例、检测、隔离和检疫；以[CDC论文](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)限定10,265名学生监测队列和采集方法。2021年[03-13—03-21 stay-in-place公告](https://coronavirus.duke.edu/2021/03/stay-in-place-for-duke-undergraduate-students-effective-at-midnight-saturday-march-13/)是另一时期，需要另找完整2021周序列，不能直接拼进2020验证窗口。

3. **UIUC或其他美国高校2020秋**：从[Campus COVID](https://github.com/jkbren/campus-covid)或[Big Ten raw.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv)选择有病例、检测且记录连续的学校；接[IPEDS](https://nces.ed.gov/IPEDS/use-the-data)同期人口、校方Massmail/学期日历，以及[NYT县级](https://github.com/nytimes/covid-19-data)或原地方卫生部门记录作社区背景。UIUC历史措施入口可查[Massmail档案](https://covid19.illinois.edu/more-information/massmail-announcements/)。不同仓库如都转载同一dashboard，不能算两份独立验证证据。

4. **非COVID学校独立基准**：以[Derbyshire个体表](https://reconverse.r-universe.dev/datasets)的班级/症状/缺勤和相对日停课记录，或[Hagelloch病例与家庭班级资料](https://search.r-project.org/CRAN/refmans/surveillance/html/hagelloch.html)做同群结构的验证。两者均应按原病种和观测定义解释。若使用1978卧床序列，则模拟输出也应映射到卧床/康复期状态，后者不是累计已康复人数。

5. **中国社区历史基准**：以[上海已实读CSV](https://raw.githubusercontent.com/junlingm/Shanghai-COVID-19-Mar-June-2022/main/Shanghai-COVID-19-Mar-Jun-2022.csv)及[同一论文的片区人口/历史事件](https://pmc.ncbi.nlm.nih.gov/articles/PMC10194905/)构成小而可复核的对照；[香港CHP](https://data.gov.hk/en-data/dataset/hk-dh-chpsebcddr-novel-infectious-agent)则可另做病例、检测、隔离状态的社区案例。公开资料不足以把上述社区曲线直接变成任意中国大学的校内病例真值。

以上拼接是研究数据组织建议，不是已完成的底表清洗，也不表示这些来源已经按同一人口、时间和口径合并。

**已核实的历史事件例子**

| 场景 | 日期与性质 | 原始依据与口径 |
|---|---|---|
| Duke | 2020-09-20监测扩容完成 | [官方10月检测周报](https://today.duke.edu/2020/10/covid-19-test-update-sept-26-oct-2)；检测能力变化会改变病例发现 |
| Duke | 2021-03-13午夜—03-21 09:00本科stay-in-place、教学线上 | [官方公告](https://coronavirus.duke.edu/2021/03/stay-in-place-for-duke-undergraduate-students-effective-at-midnight-saturday-march-13/)；不同于2020数据窗口 |
| Notre Dame | 2020-08-18公告，08-19本科转线上；09-02起分步恢复 | [CDC MMWR](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm) / [校方公告](https://global.nd.edu/news-events/news/notre-dame-enacts-two-weeks-of-remote-instruction/)；区分宣布与实施 |
| Cornell | 2021-12-10限制线下互动；12-14考试转线上等 | [研究论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9118068/)；需按学生/职工适用对象记录 |
| MIT | 2022-03-14起optional testing阶段 | [官方摘要页](https://covidapps.mit.edu/dashboard)；摘要入口与PDF内日期边界有1日差异需保留 |
| UIUC | 2023-02-10强制检测和校内SHIELD项目结束 | [官方历史页](https://covid19.illinois.edu/on-campus-covid-19-testing-data-dashboard/)；项目结束≠校园感染归零 |
| 香港 | 2023-01-19宣布，自01-30取消隔离令、改变病例报告范围 | [政府原公告](https://www.info.gov.hk/gia/general/202301/19/P2023011900678.htm)；前后序列不可视为同一观测制度 |
| 上海作者片区 | 2022-03-28东片区、04-01西片区封控；04-04全市PCR筛查 | [论文Materials及参考原始通报](https://pmc.ncbi.nlm.nih.gov/articles/PMC10194905/)；边界按作者定义 |
| 中国内地 | 2022-12-08检测对象由全人群转向有意愿者/高风险者 | [中国CDC本份报告](https://weekly.chinacdc.cn/fileCCDCW/cms/news/info/upload/ca53f5fd-37be-4ae0-9a27-384e0abe280d.pdf)；不能将检测阳性数当感染总数 |

**解释和使用边界**

下列判断是用于数据质量评估的方法建议：

- `infection_date`、`onset_date`、`specimen_date`、`report_date`和网页发布日期必须分开。大部分公开daily cases描述报告、采样或发病，并不观察真正感染时刻。
- 测试次数、独立受检人数、阳性标本、独立病例、累计病例和当前隔离人数是不同观测量。医院新入院、占床、ICU也不能混合。适用性评价要求把模型输出映射到对应观测量。
- 周数据、前向填充、移动平均、累计差分和图形数字化都应保留处理标志；缺报、抑制值和空白不应自动填0。病例序列中的回补也不代表当天感染上升。
- 人口分母按同期“在校/住宿/筛查合资格/实际受检”选择，保留定义和适用人群。大学病例常包含在县病例内，二者不能简单相加。
- 接触网络必须注明是否与病例同群、同期、同地。SocioPatterns/POLYMOD/CNS等能检验接触模块；与别校疫情拼接属于建模假设，不能声称恢复了那次疫情的真实网络。
- 参数校准和模型验证应分开数据窗口、分组、场景或独立观测渠道。报告病例/NYT/JHU若同源，不是独立证据；ONS家庭抽样等独立渠道也有适用人群限制。
- 源代码许可不自动等于数据许可；需按具体数据版本注明署名、非商业/共享条件或账户/授权要求。目录本次没有注册账户或申请受限数据。

**本次核验的完成范围**

逐项核对一手官方页面、作者仓库或论文；部分直接下载并检查表头/首尾/工作表，其他明确标成“文档/目录已核实、文件未实读”或“图/归档待获取”。源站迁移、重定向、浏览工具不能加载与数据永久消失分开记录。没有全量下载所有大文件、没有恢复所有Tableau/旧嵌入图，也没有将所有PDF数字化。

检索中也遇到论文明确“不公开原始校园数据”的情况，未把“可联系作者申请”视作已经公开。详细反例与链接见[campus_us_evidence.md](campus_us_evidence.md)。本报告不保证检索穷尽；它保留了继续扩展学校和地方卫生资料的入口，并将当前可取用资料与尚需恢复的线索分开。

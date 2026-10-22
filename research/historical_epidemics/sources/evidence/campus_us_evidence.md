# 美国高校疫情历史数据核验笔记

核验日期：2026-10-15（Asia/Shanghai）。面向历史数据与既有模型的观测对照。此处“适合 ABM”只评价公开观测与场景背景的完整性，并不表示存在可识别个体传播链、接触网络或无偏的真实感染数。原 `campus_us_sources.json` 字段已并入[统一来源记录](../records.json)，本文件保留初次取证笔记，后续获取状态以统一记录与下载清单为准。

本次认真区分三类情况：直接读到机器数据；官方确实保留历史入口但嵌入图/下载未成功核；原仪表板灭失或内容被替换，只能用论文/公告/作者快照。

## US-CAMPUS-01 Campus COVID Dataset

- [作者 GitHub README](https://github.com/jkbren/campus-covid) 明确数据主要从各校 dashboard 人工录入，也说明自报、人工误差和历史修订风险；链接 IPEDS、ACS、JHU 县级附表。
- [作者 data 目录](https://github.com/jkbren/campus-covid/tree/main/data) 实见 campus_covid_fall2020_full.csv、campus_covid_ipeds.csv、campus_covid_census.csv、campus_covid_jhu_county.csv.gz、massachusetts_ihes.csv、massachusetts_ihes_cumulative.csv。
- [正式 PLOS 论文](https://journals.plos.org/digitalhealth/article?id=10.1371/journal.pdig.0000065) Figure 1 确认 1,448 所，971 所有学期时序、477 所仅累计；主要秋季 2020-08—12。Massachusetts 部分有 56 校覆盖秋2020及春2021。Supporting Information 说明 positive_tests / total_tests 的日/周记录模板；周报记在首次 collection date；仅累计则写在 notes 中。
- 关键权限：README 的 C2i 段明确 campus_covid_status.csv 需 College Crisis Initiative 授权；不能将“仓库公开”推成“政策数据全都开放”。教学模式分组也不等于校园所有措施的逐日完整日历。
- CSV 下载链接存在，但本子任务用 Python urllib 实读大表出现 RemoteDisconnected/Timeout；因此不报告未经核验的总行数、每校首尾。可复用 root 若已下载的本地核验结果。

## US-CAMPUS-02 Big Ten / wadefagen

- [README](https://github.com/wadefagen/college-covid19-dataset) 列 14 校原始官方链接，并明确 daily.csv 是前向填充。
- [raw.csv](https://raw.githubusercontent.com/wadefagen/college-covid19-dataset/master/data/raw.csv) 经网页工具直接读取内容：字段 Country_Region, Date, Tests, Confirmed。Country_Region 实为学校名。开头 Michigan,2020-03-14，末行 Maryland,2020-12-20。Illinois 可见2020-07-06—2020-12-19；各校不同。
- 数值呈累计（如 Illinois 首日 Tests=99、Confirmed=0，2020-12-19 为 1,025,454 与 4,526）；需要按原采集间隔解释，不能把累计当日新增。daily.csv 的日行数增加不产生真实每日观测。
- 适合少量2020秋季学校的汇总轨迹核对；无人口/政策/接触边。

## US-CAMPUS-03 Duke

- [Fall 2020 tracker archive](https://coronavirus.duke.edu/covid-testing-old/fall-2020-duke-covid-testing-tracker/) 当前仍有官方 HTML 表：2020-08-02—11-20，学生/教师职工；测试、阳性、隔离、解除、预防性检疫、解除检疫；按监测/症状或追踪/入校分项。注释明示早期7月运动员未计入。
- [2020-09-26—10-02 周报](https://today.duke.edu/2020/10/covid-19-test-update-sept-26-oct-2) 当前可读，包含本科/研究生/教师职工阳性、居住校内校外、检测类别、隔离与检疫、释放数。此周运动员已计入监测类别；不可直接和研究的非运动员样本相混。
- [CDC MMWR](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm) 研究 2020-08-02—10-11，学生队列10,265；背景包括2020-09-20完成监测扩容、宿舍单人间与入校流程。只在历史背景层面引用，不复述实验流程。
- [2021 官方 Testing & Reporting 归档](https://coronavirus.duke.edu/category/testing-reporting/page/2/) 含2021春每周记录；[stay-in-place 原始通知](https://coronavirus.duke.edu/2021/03/stay-in-place-for-duke-undergraduate-students-effective-at-midnight-saturday-march-13/) 写2021-03-13午夜—03-21 09:00，本科课程线上。
- 主 https://coronavirus.duke.edu/covid-testing/ 本次实际打开重定向 https://today.duke.edu/；不要只给旧主链接当作可用数据库。未见统一 CSV。

## US-CAMPUS-04 UIUC / SHIELD

- [官方历史入口](https://covid19.illinois.edu/on-campus-covid-19-testing-data-dashboard/) 明载2023-02-10结束强制COVID检测和供应该dashboard的Urbana项目，并保留 [SHIELD archive](https://go.illinois.edu/COVIDTestingData) 链接；嵌入图数据本次未取出，下载CSV能力未核。
- [Massmail Archive](https://covid19.illinois.edu/more-information/massmail-announcements/) 保留2020起大量带日期原始通知，适合措施时间线补全。
- [2020-09-02原始通知](https://massmail.illinois.edu/massmail/1405637420.html) 是本科生活动限制的直接证据；[官方新闻](https://news.illinois.edu/media-alert-news-conference-to-discuss-universitys-plan-to-correct-upward-trend-of-positive-covid-19-cases/) 同日记录背景。不要把公告日或计划中的转线上当已执行事件。
- 2020时序可先用 Big Ten 快照；在未成功导出归档前，不宣称已经取得2020—2023完整日CSV。

## US-CAMPUS-05 Stanford

- [官方 historical dashboards](https://healthalerts.stanford.edu/covid-19/stanford-covid-dashboards/stanford-covid-historical-dashboards) 定义非常清楚：累计病例自2020-03；数据至2023-05中；2023-05-11结束每周更新；教师职工博士后Color项目2020-08-26—2023-03-24；采样日入账而非发布日期。
- 同页分学生/教师职工博士后；有检测、阳性、接种、Health Check、在校园隔离定义。重复测试次数不等于受检人数；职工图不包括外部检测；已知累计病例与测试图来源范围不同。
- Tableau链接实际点击在本次工具内失败，因此只认定入口与定义已验证，不声称CSV已可下载。官网提供 alternate formats 联系方式，但本任务未对外联系。
- [Health Alerts](https://healthalerts.stanford.edu/covid-19) 可接历史announcements；其现行政策不能回填成2020政策。

## US-CAMPUS-06 Cornell

- [官方2020-08-25新闻](https://news.cornell.edu/stories/2020/08/cornell-launches-covid-19-testing-dashboard-alert-system) 确认日测试和阳性dashboard当日推出。
- [开放研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC9118068/) Figure 为2021秋日病例及关键事件；表与Methods列本科15,503、研究生2,873、雇员2,803参加至少周一次监测，后两者只为各自群体一部分，不能相加后当全校人口。
- 同研究结果覆盖2021-08-23—12-31；明确12-10限制线下互动，12-14禁止聚会/考试线上/离校检测；报告11-28—12-31病例无住院报告。这是一个时期的汇总，不是完整住院时序。
- 原 https://covid.cornell.edu/testing/dashboard/ 本次工具访问失败；IRP页面存在但部分为内部页面，不可据其标题推定公开个体数据。当前可用的是论文图/表，不是已获得CSV。

## US-CAMPUS-07 Notre Dame

- [CDC MMWR](https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm) Figure 1为8月日病例/诊断阳性率，Figure 2为8—10月日检测类别与病例；给约12,000学生/8,000本科/85%本科住校，以及阶段检疫隔离汇总。
- 同来源给08-10开学、08-19本科转线上、09-02低年级恢复面授；[08-18校方原始公告](https://global.nd.edu/news-events/news/notre-dame-enacts-two-weeks-of-remote-instruction/) 是发布日，不能把实施日抹成同一天。
- [08-28恢复通知](https://politicalscience.nd.edu/news-and-events/news/provost-miranda-evp-cullinan-message-on-resumption-of-in-person-instruction/) 仍可读，可补教学校历。旧 https://here.nd.edu/our-approach/dashboard/fall-2020-data/ 本次不能访问。
- 高价值背景；底数目前主要图表，未核到CSV；公开的是接触追踪汇总而非课表/座位/接触网络。

## US-CAMPUS-08 MIT

- [官方 Covid Apps 当前摘要入口](https://covidapps.mit.edu/dashboard) 明载 required 2021-08-15—2022-03-13 与 optional 2022-03-14—06-30 两份PDF。
- [required PDF](https://bpb-us-e1.wpmucdn.com/sites.mit.edu/dist/c/347/files/2020/09/Covid-Dashboard-Required-Testing-Snapshot.pdf) 被搜索索引可读：学生/雇员/affiliate测试、阳性、阳性率、独立受检人数，月级图。文件内部标题08-16—03-12与入口相差一日，必须保留口径差异；直接PDF打开本次失败，不冒充本地已保存。
- [2021-02-09官方说明](https://news.mit.edu/2021/fall-semester-covid-19-testing-0209) 解释当年日dashboard、身份分组和密接/校外居住汇总；[2020-08-24官方说明](https://news.mit.edu/2020/covid-testing-reopening-0824) 确认dashboard日系列始于08-17及返校阶段。
- 当前持久可用粒度为摘要；不能从当年“每日更新”推出现今逐日CSV仍公开。

## US-CAMPUS-09 UCSD

- [开放mSystems原文](https://journals.asm.org/doi/10.1128/msystems.00793-21) 给建筑尺度污水/诊断病例/隔离人数对照；明确一段日对照2020-11-23—2021-01-01；2020秋约9700住校学生和4000在校职工；污水研究覆盖7614居民/239栋。
- 原文Figure 2说明2021-01-01冬季入住开始、01-04开学；历史多观测可帮助区分模型输出与测量信号。
- [Return to Learn dashboard](https://returntolearn.ucsd.edu/dashboard/index.html) 本次工具不可访问；原文未据此证明公开CSV已下。污水汇水区不是人际接触网络；污水浓度也不是daily incident cases。
- 本调研仅评价数据范围与获取，不复制实验室流程或据此提出新现实措施。

## US-CAMPUS-10 University of Idaho

- [Scientific Reports原文](https://www.nature.com/articles/s41598-023-34625-7) Study system / Sample collection 写2020-08-18—2021-06-04；为隐私以采样周代日期；校园/社区的定义依检测由学校支付与否，不等同地理边界。
- 同一来源Table1列校历、检测、假期和线上教学。人口背景约9300本科、2700研究生、900教师、1500职工；3161住宿学生（含1603 Greek住宿）；Moscow约26000。
- 二次复核：原文明确使用 including，因此3161为文中 on-campus housing 总人数，其中1603住在24处兄弟会/姐妹会集体住宅；两数不能相加。这里的3161也不应窄译为普通学生宿舍人数。
- Figure1有校园/社区病例与阳性率；Supplementary Tables XLSX链接实际存在，但本次点击未读到文件，因此不声称已有全体病例/测试周底表。为汇总轨迹调查无需获取或分析病原序列。
- 优点是校园与社区同研究；不足是受检选择偏差、周粒度、缺公开接触边。

## US-CAMPUS-11 DePaul

- [官方archive](https://resources.depaul.edu/coronavirus/resources/covid-19-dashboard/Pages/archive.aspx) 仍列2020-08—12、2021上半年、2021下半年、2022-01起四个Looker/Data Studio分期链接。
- 原文明确仅报告具有校园暴露风险的已报告病例，可能含访客/租户；不包括未在校园活动者、未报告者、2020-08前病例。不能与全校感染率等同。
- 页面用“present”不能证明2026仍更新；最后真实日期和底图粒度/CSV待核。作为有明确选择范围的补充候选。

## US-CAMPUS-12 UC Davis

- [旧检测dashboard地址当前实际内容](https://campusready.ucdavis.edu/testing-response/dashboard) 已是校园污水页面；定义为N/PMMoV、7日移动均值、周更新。图表起止与直接下载未核。
- 同页2022-07-14说明：校园kiosk/Student Health结果进入州/县系统，外部检测归属居住县；校园与Yolo重复，不能相加。
- [2021-10官方新闻](https://www.ucdavis.edu/news/arc-isnt-only-place-to-get-your-covid-19-test) 可证明当年有每周测试/阳性/阳性率和接种dashboard；不能据此宣称这些旧图现在仍可读。
- 目前将它列为补充污水与历史临床线索，低于直接有原始病例CSV的校园。

## US-CAMPUS-13 BU 与 US-CAMPUS-14 Northeastern（归档待恢复）

- [BU旧dashboard](https://www.bu.edu/healthway/community-dashboard/) 本次实开重定向Chief Health Office。[2020-08-17官方上线说明](https://www.bu.edu/articles/2020/bu-launches-covid-19-dashboard/) 与 [2020-10-14—20官方周报](https://www.bu.edu/articles/2020/boston-university-weekly-covid-report-oct-14-20/) 仍可读；用于背景或手工周报整理，不当即用CSV。
- [Northeastern旧dashboard](https://news.northeastern.edu/coronavirus/reopening/testing-dashboard/) 本次只有标题/导航无可提取数据。[2020-08-21官方上线说明](https://news.northeastern.edu/coronavirus/university-messages/here-are-the-results-of-northeasterns-first-4-days-of-coronavirus-testing-and-here-is-how-to-keep-track-from-now-on/) 可确认Boston校园、08-17起检测与每日更新；[官方公告库](https://news.northeastern.edu/coronavirus/university-messages/) 可拼时间线。
- 两校都可优先尝试Campus COVID Dataset保留快照，而非将“历史上存在dashboard”误当“当前数据可下载”。学生自建页面只作额外线索，本JSON未把其当官方来源。

## 未纳入可公开即用名单的一个重要反例

[Connecticut高校2020—2021研究](https://www.medrxiv.org/content/10.1101/2021.08.11.21261732v1.full) 的Data Availability明确写：town级政府数据公开，但高校汇总weekly campus testing data **not publicly available**。不能因论文开放、或链接州open data，就声称研究的校园周测试底表公开。可用政府town数据做社区背景，但校园底表另需申请。


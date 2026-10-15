# 学校疫情论文补充数据与历史接触数据目录

核查日期：2026-10-15。这里整理 15 个数据源家族：10 个含疫情观测或汇总结果，5 个仅含历史接触观测。一个疫情的多篇论文合并为一条，不能当作独立验证事件。优先级与 ABM 适用性是本次调研判断，论文或网站提供的事实均在相应条目中标注来源。

系统整理阶段已将CSDH病例的32份有效CSV、配套教学/口罩/人口，以及天津附件转成可读取数据；实际文件、日期疑点和异常定位见[数据包说明](../README.md)。下文访问标记同时保留检索阶段的证据边界，未把其余公开目录虚报为已下载。

访问标记：**文件实核**表示本次实际读取了文件及表头；**公开目录**表示已核实公开文件目录和说明，但未逐文件读取；**论文汇总**表示公开论文图表可以使用，未核实完整原始数据开放。仅公开目录和论文图表的来源不应在项目中标记成“已经下载”。本目录不整理个人轨迹或个体传播链。

## 快速比较

|编号|数据源与场景|已核覆盖窗口|类型|措施时间线|ABM 验证用途|访问|
|---|---|---|---|---|---|---|
|S01|COVID-19 School Data Hub；美国 K-12 学校/学区|2020–21 学年；各州周期不同|学生/员工病例、教学模式、口罩政策|有独立文件|较强；需逐州统一观测定义|病例 ZIP 文件实核|
|S02|SHIELD Illinois；116 个小学/初中学区|2021 年春季至 2022 年春季|每周检测、阳性、学生/员工人口|论文有政策与校历背景|较强；公开聚合数据与人口配套|公开 CSV 目录；下载端本次 403|
|S03|天津汉沽 4 校流感监测研究|研究 2012-09–2014-12；实核附件仅 2014-10-26–12-27|一校一次暴发的日发病 ILI|部分，正文与暴发图表|适合短窗口病例曲线检验|XLSX 文件实核|
|S04|日本大阪学校 H1N1|2009-05-11–05-31|学校 × 发病日确诊计数|有，停课日期明确|适合多校聚合曲线|公开附表 PDF 目录|
|S05|美国宾州小学—家庭 H1N1|2009 年 4–5 月；访谈至 06-02|ARI/ILI 发病曲线、年级/家庭汇总|有，停课与复课|可作学校—家庭场景检验|论文汇总；未核实原始矩阵开放|
|S06|英国伦敦学校 H1N1|2009-04-15–05-15 调查窗口|发病曲线、年级与师生分类|有，校历/停课/历史事件|可用聚合曲线；短小、选择性检测|公开论文 PDF|
|S07|纽约 Queens 高中 H1N1|初报 2009-04-20–04-24；后续研究至 05-08|日发病确诊计数、ILI 调查汇总|有，停课与检测变动|辅助历史暴发检验|公开 CDC 图文；NEJM 附录列出|
|S08|Duke 大学 COVID-19 研究报告|2020-08-02–10-11|按检测原因的测试/阳性总量|有，返校与检测扩展节点|更适合观测口径与总量检查|公开论文汇总，非完整日病例序列|
|S09|Diamond Princess；邮轮，非校园|2020 年 2–3 月早期疫情|日病例/死亡 CSV、年龄汇总|有，可配 CDC/日本官方报告|适合封闭群体聚合外部检验|公开 GitHub 数据目录|
|S10|英国寄宿学校流感|1978-01-22–02-04，共 14 日|每日卧床人数、康复期人数|仅原报告背景|适合基础历史基准，观测量是现患|公开 R 数据及原始图|
|C01|SocioPatterns 里昂小学|2009-10-01–10-02|接触、班级、性别|无疫情措施；有作息|只能检验接触结构|公开下载目录|
|C02|SocioPatterns 马赛预科班|2011 年 12 月 4 个观测日；2012 年 11 月 7 个观测日|接触、班级、性别|无疫情措施|只能检验接触结构|公开下载目录|
|C03|SocioPatterns 马赛预科班多模态|2013-12-02–12-06|传感器/接触日记/友谊/班级|无疫情措施|只能检验接触测量与结构|公开下载目录及论文附件|
|C04|Copenhagen Networks Study；大学新生|连续 4 周，相对时间，绝对起点未发布|近距离蓝牙与其他社交网络|无疫情措施|只能检验大学接触结构|2019 公开子集；非整个 CNS|
|C05|Pittsburgh SMART；8 所 K-12|方法称 2011-10–2012-04，各校典型上课日|匿名接触网络与学校/年级结构|无疫情措施|只能检验接触结构|公开附件 ZIP 目录|

## 含疫情观测的来源

### S01. COVID-19 School Data Hub（CSDH，美国 K-12）

- **来源与文件：**[数据资源页](https://www.covidschooldatahub.com/data-resources)、[方法说明](https://www.covidschooldatahub.com/methods)、[病例 CSV ZIP](https://assets.ctfassets.net/9fbw4onh0qc1/Iz122B08nXi5KAj7Ibxqs/134dc4172e422bae944910a7893e1477/CSDH_COVID-19_Data_CSV.zip)。源自州卫生/教育部门 dashboard、报告及数据请求，保留学校或学区粒度；不是所有州都有病例数据。病例包版本为 2021-12-13，覆盖 2020–21 学年，各州报告周期不同。[资源与方法](https://www.covidschooldatahub.com/methods)
- **字段与实核：**本次在内存实际读取 6,797,127 字节 ZIP，含 32 个 CSV 文件，学校级和学区级文件合计，不能称作 32 个州。前三个文件表头均含 `NCESSchoolID`、`NCESDistrictID`、`TimePeriodStart/End`，及新增、累计、两周窗口、active 病例分列，部分区分学生和员工；字段存在不表示该州每列都有值。[病例文件](https://assets.ctfassets.net/9fbw4onh0qc1/Iz122B08nXi5KAj7Ibxqs/134dc4172e422bae944910a7893e1477/CSDH_COVID-19_Data_CSV.zip)
- **背景与人口：**[教学模式 CSV ZIP](https://assets.ctfassets.net/9fbw4onh0qc1/3JXV9ahOubLLnh9aHTHgKv/6e3c8a2baf1f2e0517edd9e454ee5c74/CSDH_District_Files_-_CSV.zip)、[口罩政策 CSV ZIP](https://assets.ctfassets.net/9fbw4onh0qc1/5CvsELupAMEAjAASxlDEcU/dad40bde6fd21bf8587a75920d6c5f41/Masking_Data_CSV.zip) 可按 NCES ID 配对；站点同时提供 2020–21 NCES CCD 人口/学校信息和社区病例率。州级 Data Details 记录定义、人数与缺失。[目录](https://www.covidschooldatahub.com/data-resources)
- **判断：**本组最值得优先整理的学校疫情源。优点是病例、历史教学模式、政策和机构标识同平台；缺点是州间统计口径、报告频率及隐私抑制差异明显，没有真实接触网络，住院不属于这套学校病例核心数据。应保留州级原始定义，不能把 active counts 当作 daily incidence。

### S02. SHIELD Illinois 小学/初中每周检测数据

- **来源：**[Illinois Data Bank 数据页](https://databank.illinois.edu/datasets/IDB-3705306)，DOI [10.13012/B2IDB-3705306_V1](https://doi.org/10.13012/B2IDB-3705306_V1)；[论文](https://doi.org/10.1186/s12889-024-20623-5)。目录公开 `k8_SHIELDdata.csv`（192 KB）及数据字典（1.37 KB），CC BY，2024-10-16 发布版本。目录已核实，本次文件端返回 403，未核实 CSV 实际首末日。[仓库](https://databank.illinois.edu/datasets/IDB-3705306)
- **窗口与内容：**研究涉及 116 个小学/初中学区，SHIELD Illinois 提供周检测数据，排除 Chicago Public Schools；学生/员工人口来自 ElSi。论文校期为 2021-01-05–05-30、2021-08-22–12-22、2022-01-04–05-28；论文另述保留验证期延至 2022-06-21，不能把这个模型终点自动当作 CSV 最后观测日。[论文方法](https://link.springer.com/article/10.1186/s12889-024-20623-5)
- **背景与判断：**有历史州口罩要求、周检测、校历和疫苗背景，没有实测接触网络。优点是重复检测与人口分组配套；适合检验模型的周阳性与分组负担。局限是自愿参与、覆盖变化及社区输入混杂，校历和模型设定需区分观测记录。下一步应先读公开数据字典，确认检测次数与独立人数。[数据描述与字典](https://databank.illinois.edu/datasets/IDB-3705306)

### S03. 天津汉沽学校流感监测与一校一次疫情附件

- **来源：**Xu 等（2017），[论文 DOI 10.1371/journal.pone.0184527](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184527)，[S1 XLSX 下载](https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0184527.s001&type=supplementary)。研究总体为 2012-09-01–2014-12-31 的 3 所小学、1 所中学，约 6,000 名学生；假期不全纳入观测。[论文方法](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184527)
- **实际文件边界：**虽然 Data Availability 说相关数据见正文和附件，S1 的说明明确是“一所学校一次暴发”。本次实读 9,614 字节 XLSX，唯一非空工作表为 63 行日观测加表头，字段 `Onset date`、`ILI`，日期 2014-10-26–2014-12-27。不能宣称已取得 4 校三年完整原始序列。[S1 文件](https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0184527.s001&type=supplementary)
- **背景与判断：**正文和暴发图记录发现与处置背景，包括病例居家/隔离、环境与通风等历史措施；没有完整独立措施 CSV。适合日 ILI 曲线和总量检验，优点是中国校园、一手日数据、发病日定义清楚；局限为 ILI 不等于全部实验室确诊感染，附件短、缺少班级网络与完整检测分母。[论文及 Supporting Information](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184527)

### S04. 日本大阪多学校 H1N1，2009 年

- **来源：**Kawaguchi 等，[论文 DOI 10.3201/eid1510.091029](https://pmc.ncbi.nlm.nih.gov/articles/PMC2866419/)，附录 `09-1029_appT-s1.pdf` 在论文 Supplementary Material 内。附表明确给出 2009-05-11–05-31 学校与发病日期的确诊计数。本次核实公开附表链接，未逐单元格转录。[附表入口](https://pmc.ncbi.nlm.nih.gov/articles/PMC2866419/#supplementary-materials)
- **措施与结构：**大阪府 270 所高中、526 所初中于 05-18–05-24 停课，部分其他教育机构跟随，正文记录历史用药、居家要求与媒体事件。学校数是停课范围，不能当作每所学校人口分母；精确在校人数需另找同期教育统计。[原报告](https://pmc.ncbi.nlm.nih.gov/articles/PMC2866419/)
- **判断：**适合检验多校聚合发病曲线与历史节点，优点是按发病日且措施日明确；局限是 21 天窗口、学校人口不全、检测覆盖变化，停课与其他行为变化同期发生，不能只凭曲线作单一措施因果归因。

### S05. 宾州小学—家庭 H1N1，同一疫情的两篇互补研究

- **来源：**[CDC/宾州调查论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC3738229/) 与 [Cauchemez 等 PNAS，DOI 10.1073/pnas.1008895108](https://pmc.ncbi.nlm.nih.gov/articles/PMC3041067/)。后者有按发病日及人群类型的汇总曲线、年级/班级/家庭背景；观察涉及 2009 年 4–5 月，访谈为 05-16–21 和 05-26–06-02。[PNAS 调查描述](https://pmc.ncbi.nlm.nih.gov/articles/PMC3041067/)
- **背景与结构：**公开报告记录 05-14 开始的 7 天学校关闭与复课；PNAS 描述 370 名学生、899 名家庭成员的访谈信息。两篇使用 ARI 与 ILI 不同定义及分析样本，不能直接累加病例或混成一种观测。[调查报告](https://pmc.ncbi.nlm.nih.gov/articles/PMC3738229/)、[PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC3041067/)
- **访问与判断：**正文与 SI 方法/汇总表公开；本次未核实全部原始发病日记录或原始关系矩阵开放下载，故列为论文汇总型。优点是学校—家庭双场景与明确历史节点；缺点为回忆调查、症状定义、非全员检测。可用于按日/年级/角色的聚合输出检查，不应宣称有完整公开传播链真值。

### S06. 伦敦学校 H1N1，2009 年 4–5 月

- **来源：**Calatayud 等，[DOI 10.1017/S0950268809991191](https://doi.org/10.1017/S0950268809991191)、[作者机构开放 PDF](https://orca.cardiff.ac.uk/id/eprint/22061/1/Calatayud%202010.pdf)。调查人口为 1,177 名学生所在混合学校及员工/相关家庭，调查范围 04-15–05-15；图表含按发病日期、人群与年级的分组信息。[论文](https://orca.cardiff.ac.uk/id/eprint/22061/1/Calatayud%202010.pdf)
- **背景与判断：**复活节停课 04-15–20，疫情停课 05-02–10，其他历史处置节点亦注明。适合短期学校聚合曲线检查，优点为背景详细、学校分母明确；缺点是病例少、检测选择性、不同症状分组的数据来源不一致。本次只确认公开论文 PDF，未确认独立机器可读原始病例序列；只采用聚合曲线与汇总表。[论文方法与局限](https://orca.cardiff.ac.uk/id/eprint/22061/1/Calatayud%202010.pdf)

### S07. 纽约 Queens 高中 H1N1，2009 年

- **来源：**[CDC MMWR 初报](https://www.cdc.gov/mmwr/preview/mmwrhtml/mm58d0430a1.htm)、[NEJM 后续论文 DOI 10.1056/NEJMoa0906089](https://www.nejm.org/doi/full/10.1056/NEJMoa0906089)。MMWR 图及替代文本公开 04-20–04-24 的 44 个确诊病例日发病计数；学校总规模为 2,686 名学生、228 名员工。[CDC](https://www.cdc.gov/mmwr/preview/mmwrhtml/mm58d0430a1.htm)
- **窗口与背景：**后续论文调查确诊报告延至 05-08，并列 Supplementary Appendix，但本次未逐文件核实。CDC 记录 04-27 学校未复开、04-26 开始网络 ILI 调查与检测扩展。[CDC 初报](https://www.cdc.gov/mmwr/preview/mmwrhtml/mm58d0430a1.htm)、[NEJM](https://www.nejm.org/doi/full/10.1056/NEJMoa0906089)
- **判断：**公开短期曲线与人口分母便利；缺点是最初 5 天仅检测确诊子集，不能替代完整校内感染序列。初报与后续论文属同一事件，应选定版本并标记统计截止日；住院仅有早期总量，不是连续住院日序列。

### S08. Duke 大学 2020 年秋季检测研究

- **来源与窗口：**[CDC MMWR，DOI 10.15585/mmwr.mm6946e1](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)，2020-08-02–10-11。表 2 提供入校、无症状监测、症状与接触调查等检测类别的测试和阳性总量；10,265 名学生、68,913 次检测、84 个阳性病例，明确排除特定运动员群体及 Durham 之外远程学生。[原报告](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)
- **背景与判断：**记录 08-11–15 返校与 09-20 监测扩展到目标频率，以及宿舍、隔离与校园协议背景。优势是检测观察机制和样本范围清晰，适合校验检测分类总量；缺点是本文不是完整日病例数据集，图 A 为累计处理标本量而非病例曲线，无实测接触网络。历史 dashboard 需另行核实，不能由论文提到 tracker 就认定其历史文件仍可下载。[报告](https://www.cdc.gov/mmwr/volumes/69/wr/mm6946e1.htm)

### S09. Diamond Princess：邮轮封闭社区，非校园

- **来源：**Russell 等，[论文/数据与代码声明](https://pmc.ncbi.nlm.nih.gov/articles/PMC7118348/)、[作者 GitHub](https://github.com/thimotei/cCFRDiamondPrincess)、[数据目录](https://github.com/thimotei/cCFRDiamondPrincess/tree/master/data)。`up_to_date.csv` 页面可核实字段 `date,new_cases,new_deaths`、49 行文件；另有其他数据版本。覆盖 2020 年 2–3 月早期疫情，本次未读到 CSV 全部日期，精确起止不得据文件名猜测。[文件页](https://github.com/thimotei/cCFRDiamondPrincess/blob/master/data/up_to_date.csv)
- **背景与结构：**约 3,711 名乘客/船员；[CDC 调查](https://www.cdc.gov/mmwr/volumes/69/wr/mm6911e2.htm) 区分港口整体隔离与 02-05 开始乘客客舱隔离，提供船员分类和早期症状曲线，需查看页面所列勘误。日测试量和年龄结构需回接原始日本官方报告，不能从病例 CSV 假定已包含。[作者仓库背景](https://github.com/thimotei/cCFRDiamondPrincess)
- **判断：**有日病例与死亡、边界较明确，适合封闭群体的聚合外部检验；年龄与生活环境和校园显著不同，检测先后、离船与后续住院会改变在险分母，不宜直接迁移为校园数据。公开目录已核实，CSV 全内容未下载核验。

### S10. 1978 年英国寄宿学校流感基准

- **来源与数据：**[原始 BMJ 报告档案](https://pmc.ncbi.nlm.nih.gov/articles/PMC1603269/)、[R outbreaks 维护者数据说明](https://www.reconverse.org/outbreaks/reference/influenza_england_1978_school.html)。数据 14 日，1978-01-22–02-04，字段 `date,in_bed,convalescent`；学校 763 名男生，512 人曾患病。维护者明确指出原图数字化及不同来源之间数字可能略有差异。[数据文档](https://www.reconverse.org/outbreaks/reference/influenza_england_1978_school.html)
- **判断：**容易获取，适合作为简洁的历史总体输出基准；每日卧床和康复期人数是**当日状态人数/现患**，不是新增感染或新增确诊。没有实测接触网络和完整措施时间线，现代大学泛化能力弱；原报告提供背景，R 数据是后续整理，引用时两者都应注明。

## 仅含接触的来源：不能独立验证疫情曲线

### C01. SocioPatterns 里昂小学接触

- **来源：**[数据目录与下载](https://sociopatterns.org/datasets/primary-school-temporal-network-data/)、[原论文 DOI 10.1371/journal.pone.0023176](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0023176)。2009-10-01–02，232 名儿童与 10 名教师、10 班，20 秒接触记录及班级/性别元数据；数据页载明 CC BY-NC-SA 条件。[论文与采集说明](https://sociopatterns.org/assets/papers/plos_one_11b.pdf)
- **判断：**有学校作息与午餐背景，适合接触结构、班级混合和日程层的经验检查；无同步病例、无检测序列、无疫情措施时间线。仅 2 天、校外未测，不能把它与另一所学校的病例按个人 ID 连接，也不能声称验证了真实感染过程。目录可访问，未下载个体记录。

### C02. SocioPatterns 马赛 2011/2012 年动态接触

- **来源：**[目录](https://sociopatterns.org/datasets/high-school-dynamic-contact-networks/)、[原论文 DOI 10.1371/journal.pone.0107878](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0107878)。2011 年 12 月 4 个观测日、3 班 118 名学生；2012 年 11 月 7 个观测日、5 班 180 名学生；接触分辨率 20 秒，有班级和性别。目录提供两年的文件及元数据，CC BY-NC-SA。[原论文](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0107878)
- **范围与判断：**虽叫 high school，实际是法国高中内 **classes préparatoires，高中毕业后预科教育**，不可直接当普通 K-12。无病例和疫情措施；适合比较班级/年度接触结构，缺点是单校、短期、校外未测。公开目录已核实。

### C03. SocioPatterns 马赛 2013 年多模态接触

- **来源：**[数据目录](https://sociopatterns.org/datasets/high-school-contact-and-friendship-networks/)、[原论文 DOI 10.1371/journal.pone.0136497](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0136497)。2013-12-02–06，9 个预科班的 327/379 名学生参与传感器研究；有接触日记、友谊调查与部分线上社交关系，不同模态样本不相同，全部参与者至少 18 岁。[论文方法](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0136497)
- **判断：**可比较测量偏差和班级聚合接触统计；无同步病例、无公共卫生措施时间线，不能用于疫情曲线验证。限制为自报缺失、传感器只测参与者及校园范围；友谊边不等于面对面接触。数据页与论文附件均公开，注意数据页 CC BY-NC-SA 与具体附件许可。此处仅列目录，不整理个人关系。

### C04. Copenhagen Networks Study（CNS）公开大学子集

- **来源：**[Scientific Data DOI 10.1038/s41597-019-0325-x](https://www.nature.com/articles/s41597-019-0325-x)、[作者开放 PDF](https://www.sapiezynski.com/papers/sapiezynski2019interaction.pdf)、[Figshare DOI 10.6084/m9.figshare.7267433](https://doi.org/10.6084/m9.figshare.7267433)。2019 年发布超过 700 名 DTU 新生连续 4 周的近距离蓝牙（5 分钟）、通信与社交网络子集；只提供相对时间，起点为学期内一个星期日，绝对日期有意不发布。[数据论文](https://www.sapiezynski.com/papers/sapiezynski2019interaction.pdf)
- **判断：**适合大学接触与日内/周内规律的结构检验，**无同步病例与措施时间线**。公开子集不等于完整 CNS/Social Fabric 数据；后者论文可能需申请，不能混称全部开放。蓝牙是接近代理，缺失随时段和个体变化。本次确认论文开放声明与 DOI，Figshare 文件端在本工具中未成功读取，未核实全部文件下载。[公开范围说明](https://www.sapiezynski.com/papers/sapiezynski2019interaction.pdf)

### C05. Pittsburgh SMART，8 所 K-12 学校

- **来源：**Guclu 等，[DOI 10.1371/journal.pone.0151139](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0151139)，[S1 网络文件 ZIP](https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0151139.s001&type=supplementary)。1,828 名学生、8 校，提供不同格式的匿名接触网络；方法称采集于 2011-10–2012-04，各校典型上课日，正文导言另写 2012–2013 学年，存在内部年份不一致，应以附件元数据进一步确认。[论文方法与 S1](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0151139)
- **判断：**覆盖小学至高中、公共与 charter 学校，有班级/年级结构，适合结构层外部比较；没有同步疫情曲线或疫情措施。部分学校仅抽取班级，传感器定义与 SocioPatterns 不同，不可直接混合边记录或视作同一种接触；各校仅典型日，泛化到长期有限。公开 ZIP 目录已核实，未读取全部原始文件。

## 对齐与拼接时的最低数据约定

1. **同一学校/学区匹配：**CSDH 优先按 NCES ID 与相同学年的 CCD 连接，保留学校级和学区级标识；学区病例不能复制成每所学校病例。历史大学和匿名学校论文若无稳定机构 ID，应只做场景级聚合比较，不推断对应具体个人。
2. **时间字段拆开：**分别记录发病日、采样日、报告日和统计区间。日序列与周序列可以按共同区间聚合；周数不能靠插值构造日观测。CNS 相对时间不与现实措施日历强行对齐。
3. **观察量保留：**确诊病例、positive tests、ILI/ARI、active counts、卧床现患与住院分别保留；重复检测次数不等于受检人数。以上可作为不同观测层，不能直接相加。
4. **观测与背景分别溯源：**保留病例 URL、人口 URL、措施 URL、适用人群、时间范围、版本与核查日期。论文中的模型假设、模拟反事实与真实观测分别标记；复合措施同期实施时不从单条病例曲线直接归因。
5. **仅接触数据的用途：**C01–C05 只能提供聚合接触统计或结构比较。另一地点、年份或病原的病例不会使它们成为一套“真实同步网络—感染”验证集；场景不匹配应作为可迁移性限制报告。

后续已保存相关公开原始文件，并对CSDH和天津进行全量规范化；缺测、抑制范围和源日期问题均保留或隔离。没有整理个人轨迹、个体传播链或同步网络—感染记录，没有新增依赖或改动传播模型。

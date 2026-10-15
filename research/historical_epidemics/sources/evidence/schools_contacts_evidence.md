# 学校、非美国高校及封闭场景证据表

核查日期：2026-10-15。以下仅用研究团队、出版方或官方公共卫生机构来源。`access`区分实际文件下载、网页列出下载以及本次访问受限；403不等于源数据已删除。ABM适用性是研究用途判断，并非原始数据声明。

## UK-CAM-2020 — 剑桥大学2020秋季筛查＋校园/社区疫情配套数据

证据分工：论文 Methods 的 Study setting/Participants and samples 支持人口、时间、检测资格；Results/Fig.2c 支持病例曲线；Data availability 明确扩展metadata受限。官网筛查故事支持隔周到每周的变化。实际读取Source Data后确认 Figure2c 有未测序/QC失败字段，Figure4b/4c 是病例年级/课程计数，不能当全校分母。

- **范围：** 英国 University of Cambridge；校园学生员工，并有Cambridgeshire社区对照
- **覆盖：** 核心2020-10-05至2020-12-06；部分Source Data社区序列/病例周覆盖2020-09至12月
- **数据/粒度：** 周阳性病例（含未测序/测序失败）；样本采集日；学院、年级、课程类型分层；官方筛查周报
- **获取/许可：** Source Data XLSX实际HTTP200下载并用openpyxl读取（76,651字节，14 sheets）；论文CC BY 4.0。扩展个体元数据/接触追踪须申请；旧官网索引本次403
- **措施：** 有：2020-10-05学期筛查起；最初隔周筛查、第7周全体可每周筛查；2020-11-05全国封锁；局部宿舍隔离有学期周描述，确切日需补充材料核对
- **人口/结构：** 约23,000学生、12,600员工、31学院；15,561学生符合宿舍筛查资格。年级/课程/household结构见论文，公开Source Data仅部分汇总
- **网络：** 论文使用同群同期间household及接触追踪；完整个体网络未公开，不能声称下载即可重建
- **ABM用途：** 强：适合学院/年级分层校园ABM的周病例和校园/社区外部输入验证；公开资料不足以逐人验证传播树
- **优点：** 同一学期病例、检测方式、人口与措施可互补；数值XLSX可直接复用
- **限制：** 周粒度；志愿筛查且频率改变；测序病例有选择性；年级/课程统计不可当全校人口分母；完整追踪受限

来源：

1. [来源 1](https://www.nature.com/articles/s41467-021-27942-w)
2. [来源 2](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-021-27942-w/MediaObjects/41467_2021_27942_MOESM7_ESM.xlsx)
3. [来源 3](https://github.com/COG-UK/camb-uni-phylo/)
4. [来源 4](https://doi.org/10.5281/zenodo.5643354)
5. [来源 5](https://www.cam.ac.uk/stories/screeningprogramme)
6. [来源 6](https://www.cam.ac.uk/sites/www.cam.ac.uk/files/documents/uoc_screening_report_week_8_-_2020-11-29.pdf)

## UK-BOARD-1978 — 1978英格兰寄宿男校流感暴发

证据分工：原BMJ短报告支持年龄、分母、宿舍、开学/返课规则及最终512患病；outbreaks维护者manual支持14×3数据；2024重新分析论文明确卧床/康复属于每日现患量、数字化版本略有差异。日发病不可直接用该量代替。

- **范围：** 英格兰北部单所寄宿男校
- **覆盖：** 1978-01至02；常用数字化序列14日（1978-01-22至02-04）
- **数据/粒度：** 每日卧床人数、康复期（convalescent）状态人数；后者不是累计已康复人数；最终患病512/763；返校与居住分组背景
- **获取/许可：** 维护者outbreaks R包/R-universe列出14×3数据，可导出CSV/XLSX；本次CSV请求403，下载未完成。CRAN 1.9.0 GPL>=2，开发版MIT，须固定版本
- **措施：** 有：1978-01-10开学；症状后卧床、退烧36小时后起床、再2–4天返课；630名1977-10已接种（原BMJ）
- **人口/结构：** 763男生10–18岁，30非全寄宿；113人junior house，其余10个约60人house；约130接触成人
- **网络：** 无实测接触网络，只有宿舍/年龄结构
- **ABM用途：** 中强：适合小型寄宿校园的观测模型与最终attack rate验证
- **优点：** 封闭程度高；已知总分母与总患病；经典可复现基准
- **限制：** 图形数字化误差；症状病例且卧床量不等于感染量；14日短序列无法独立识别大量ABM参数

来源：

1. [来源 1](https://math.unm.edu/~sulsky/mathcamp/Anon_InfluenzaBoardingSchool_BMJ_1978.pdf)
2. [来源 2](https://reconverse.r-universe.dev/outbreaks/doc/manual.html)
3. [来源 3](https://reconverse.r-universe.dev/datasets)
4. [来源 4](https://pmc.ncbi.nlm.nih.gov/articles/PMC11576841/)

## UK-DERBY-NORO-2001 — 2001 Derbyshire小学/幼儿园诺如病毒

证据分工：outbreaks维护者manual支持5个字段、492/186、清洁和停课相对日。数据作者O'Neill/Marks论文DOI已用PubMed核实为10.1002/sim.2090；不是2091。R-universe官方数据目录提供CSV/XLSX格式入口，但本次直接请求403，不能标为已下载。

- **范围：** 英国单所小学及幼儿园；非呼吸道病种
- **覆盖：** 2001年夏季，共22个相对日；确切日历日期未核实
- **数据/粒度：** 492儿童：class、day_absent、start_illness、end_illness、day_vomiting；可聚合日发病与缺勤
- **获取/许可：** 作者提供给outbreaks维护者；R-universe列出492×5，可CSV/XLSX；本次CSV403，未完成下载。许可按outbreaks具体版本确认
- **措施：** 有：第13/14日清洁，第18/19日停课，第20/21日再清洁；第22日最后症状
- **人口/结构：** 492名儿童，186因胃肠道症状缺勤；班级分组
- **网络：** 无实测网络；班级可作分层约束，同一儿童有症状和班级字段
- **ABM用途：** 强：适合班级分层学校ABM的日发病、病程、缺勤验证；病种机制需匹配
- **优点：** 全校人口个体表，包含未患病儿童；措施相对日明确
- **限制：** 症状/缺勤不是逐人实验室确诊；日历日期缺失；不宜直接拿诺如病毒机制验证呼吸道传播

来源：

1. [来源 1](https://reconverse.r-universe.dev/outbreaks/doc/manual.html)
2. [来源 2](https://reconverse.r-universe.dev/datasets)
3. [来源 3](https://github.com/reconverse/outbreaks)
4. [来源 4](https://doi.org/10.1002/sim.2090)
5. [来源 5](https://pubmed.ncbi.nlm.nih.gov/15818725/)

## NET-SOCIO-PRIMARY — SocioPatterns法国小学接触网络

证据分工：官方数据页支持20秒格式/班级性别/许可与文件；原PLOS论文Methods支持2009-10-01/02、232儿童+10教师、参与率、10班与白天观测边界。病例不存在，论文停课比较来自模拟。

- **范围：** 法国里昂单所小学，6–12岁儿童和教师；纯接触数据
- **覆盖：** 2009-10-01及10-02，仅校内白天
- **数据/粒度：** 20秒RFID面对面接触列表；班级与性别metadata；课程/午餐/休息时间背景
- **获取/许可：** 官方csv.gz实际HTTP200（476,062字节）；metadata公开；数据CC BY-NC-SA 3.0
- **措施：** 无历史疫情措施时间线；论文中的停课是模拟情景
- **人口/结构：** 232儿童＋10教师；全校241儿童、10班/5年级；儿童96%参与
- **网络：** 有，同群同期间高分辨率接触；无配套真实感染观测
- **ABM用途：** 仅网络/行为层校准，不能单独作为疫情结果验证集
- **优点：** 参与率高；明确班级、师生、校内作息
- **限制：** 仅两日；无校外/体育课接触；面对面距离代理非传染事件；无真实疫情曲线

来源：

1. [来源 1](https://sociopatterns.org/datasets/primary-school-temporal-network-data/)
2. [来源 2](https://sociopatterns.org/assets/data/primaryschool.csv.gz)
3. [来源 3](https://sociopatterns.org/assets/data/primaryschool_metadata.txt)
4. [来源 4](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0023176)

## NET-SOCIO-HIGH-1112 — SocioPatterns法国高中2011/2012接触网络

证据分工：官方数据页直接支持2011/2012日期范围、3班/5班、20秒、UNIX/相对时间与性别班级。不要把网页写的7 days误写成连续7日：其描述为周一至下一周周二，涉及7个上学日。

- **范围：** 法国马赛单所高中部分班级；纯接触数据
- **覆盖：** 2011-12共4日/3班；2012-11共7个上学日/5班（周一至下一周周二）
- **数据/粒度：** 20秒接触列表；班级/性别metadata
- **获取/许可：** 官方2011及2012 csv.gz实际HTTP200（90,561和155,267字节）；CC BY-NC-SA 3.0
- **措施：** 无真实疫情措施时间线
- **人口/结构：** 3班/5班；具体参与人数应由metadata统计，本次未核实
- **网络：** 实测时变接触；无同群疫情序列
- **ABM用途：** 仅网络与班级混合模式校准；不属于独立疫情验证数据
- **优点：** 可比较不同年份/班级范围；有性别班级
- **限制：** 短期且仅部分班级；无全校/家庭网络、无感染结局

来源：

1. [来源 1](https://sociopatterns.org/datasets/high-school-dynamic-contact-networks/)
2. [来源 2](https://sociopatterns.org/assets/data/highschool_2011.csv.gz)
3. [来源 3](https://sociopatterns.org/assets/data/highschool_2012.csv.gz)
4. [来源 4](https://sociopatterns.org/assets/data/highschool_2011_metadata.txt)
5. [来源 5](https://sociopatterns.org/assets/data/highschool_2012_metadata.txt)

## NET-SOCIO-HIGH-2013 — SocioPatterns法国高中2013多层接触/友谊

证据分工：官方数据页说明4类关系文件与metadata；原PLOS Methods/Results支持2013-12-02/06与327/379、120日记/135友谊问卷/156 Facebook。四网络节点覆盖不一致，外接疫情无法声称逐人匹配。

- **范围：** 法国马赛9个高中班；纯接触/关系数据
- **覆盖：** 2013-12-02至12-06；接触日记12-05
- **数据/粒度：** 20秒RFID接触、接触日记、友谊问卷、部分Facebook关系；班级/性别
- **获取/许可：** 官方proximity csv.gz实际HTTP200（653,252字节），另4文件公开；官方数据页CC BY-NC-SA（链接版本本次未核对）
- **措施：** 无历史疫情措施时间线
- **人口/结构：** 379学生中327佩戴传感器（86.3%）；120日记/135友谊问卷/156 Facebook，非同样完整样本
- **网络：** 有同期间多测量渠道；无感染结局
- **ABM用途：** 适合ABM接触生成器、网络缺失/抽样误差检验；不能单独验证疫情曲线
- **优点：** 多层关系与传感器同时测量，具有班级结构
- **限制：** 不同层参与率不同；仅校内5日；好友不等于可传播接触

来源：

1. [来源 1](https://sociopatterns.org/datasets/high-school-contact-and-friendship-networks/)
2. [来源 2](https://sociopatterns.org/assets/data/HighSchool2013_proximity_net.csv.gz)
3. [来源 3](https://sociopatterns.org/assets/data/HighSchool2013_metadata.txt)
4. [来源 4](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0136497)

## NET-CNS-DTU — Copenhagen Networks Study公开交互数据

证据分工：Figshare官方v1支持94.56MB、700多学生/4周及MIT；Data Descriptor支持蓝牙5分钟、性别、CSV。其Privacy部分明确仅相对时间，起点为学期周日；未公开绝对日。第三方声称CC BY4.0与官方MIT冲突，采用官方。

- **范围：** 丹麦DTU大学新生；纯接触/通信数据
- **覆盖：** 学期中连续4周，从周日开始；为隐私不公开实际起始日，仅相对时间
- **数据/粒度：** Bluetooth RSSI邻近、电话时间/时长、SMS时刻、Facebook友谊、性别；CSV
- **获取/许可：** Figshare v1页面已打开，显示94.56MB Download all，官方许可MIT；本次未下载整包；勿引用第三方所称CC BY
- **措施：** 无；实际日期未公开，不能与COVID政策按日直接拼接
- **人口/结构：** 700多名大学新生；性别公开；完整GPS/问卷/其他研究期数据不等同此公开子集
- **网络：** 同群4周多层网络；无真实感染结果
- **ABM用途：** 适合大学宿舍/校园网络结构与昼夜周末节律校准；非疫情结果验证
- **优点：** 校园样本较大、24小时多层网络
- **限制：** 蓝牙是距离代理；未含病史/病例；非全大学；相对日期限制政策拼接

来源：

1. [来源 1](https://figshare.com/articles/dataset/The_Copenhagen_Networks_Study_interaction_data/7267433/1)
2. [来源 2](https://doi.org/10.6084/m9.figshare.7267433)
3. [来源 3](https://www.nature.com/articles/s41597-019-0325-x)
4. [来源 4](https://backend.orbit.dtu.dk/ws/portalfiles/portal/202079683/s41597_019_0325_x.pdf)

## NET-BBC-HASLEMERE — BBC Pandemic Haslemere社区接触

证据分工：作者README定义DataS1的50m内距离、ID与DataS2时间；LSHTM项目页支持2017-10-12起72小时；原作者说明公开3日469志愿者且夜间去除。虚拟疫情结果是模拟，不能作为真实感染观测。README许可措辞是all code GPLv3，数据再分发许可仍待核实。

- **范围：** 英国Haslemere成人志愿者社区；纯接触数据，节目疫情是虚拟模拟
- **覆盖：** 2017-10-12至10-14，每日07:00–23:00
- **数据/粒度：** 匿名两人距离（50m内、米精度）、用户ID、时间索引转换CSV
- **获取/许可：** 作者GitHub已打开，列出Kissler_DataS1.csv及DataS2.csv；README只明确代码GPLv3，数据独立许可未核实；本次未全量下载
- **措施：** 无真实疫情措施时间线
- **人口/结构：** 469志愿者；公开接触表无详细个体人口属性；不是全镇人口
- **网络：** 有，3日实测邻近网络；无实际感染结果
- **ABM用途：** 适合社区活动/网络模块校准和代码复现实验；不能当历史疫情验证
- **优点：** 包含社区而非仅校园；连续3日时间结构
- **限制：** GPS邻近并非面对面接触；夜间及未参与者缺失；志愿者选择偏差；无真实病例

来源：

1. [来源 1](https://github.com/skissler/haslemere)
2. [来源 2](https://github.com/skissler/haslemere/blob/master/Kissler_DataS1.csv)
3. [来源 3](https://github.com/skissler/haslemere/blob/master/Kissler_DataS2.csv)
4. [来源 4](https://datacompass.lshtm.ac.uk/id/eprint/2319/)
5. [来源 5](https://www.lshtm.ac.uk/newsevents/news/2018/school-teams-bbc-map-pandemic-spread)

## MOB-BBC-UK — BBC Pandemic英国全国流动OD公开数据

证据分工：作者README直接支持LAD OD汇总、首24小时、43,291、就业与年龄分层、隐私仅LAD；项目年份见作者论文。它与Haslemere是不同公开数据产品，不要用28,947接触问卷样本数代替mobility 43,291。

- **范围：** 英国全国地方行政区LAD间流动，非校园疫情
- **覆盖：** 2017/18项目；每用户首次24小时位置汇总；准确招募起止日在论文，本次未核实
- **数据/粒度：** LAD origin-destination flux矩阵；按就业/教育/18岁以下分层、全国年龄分层；R代码
- **获取/许可：** 作者BBCPandemic/BBCMobility公开仓库已打开，flux等目录可见；仓库GPL-3.0；完整原始GPS未开放
- **措施：** 无真实疫情措施时间线
- **人口/结构：** 43,291用户进入最终mobility数据集；年龄、employment/education/under18等聚合分层
- **网络：** 无逐人接触网，仅区域间流动
- **ABM用途：** 辅助社区ABM的地区间输入/流动校准，不能独立验证感染曲线
- **优点：** 全国覆盖；与2011 census工作通勤对照；人口分层
- **限制：** 公开仅LAD尺度；每人首日，不是2020行为；不能从OD恢复真实个体接触

来源：

1. [来源 1](https://github.com/BBCPandemic/BBCMobility)
2. [来源 2](https://www.medrxiv.org/content/10.1101/2021.02.19.21252079v1)

## RU-TOMSK-2016 — Tomsk流感季学校停课接触日记＋社区周监测

证据分工：Zenodo API metadata明确2016日记、开放且CC BY4.0；论文Results/Table1支持450/7009与181停课日样本，Fig3为地区周ARI/估计流感/关闭指标，Methods说明两学校家庭样本。地区周疫情和日记虽同季，非同一被试的感染结局。

- **范围：** 俄罗斯Tomsk，两所学校及家庭接触样本；疫情验证范围为地区/社区
- **覆盖：** 2015–2016流感季；接触日记2016，普通上学日与被动停课日
- **数据/粒度：** 450名参与者的日记共报告7,009次接触，含接触对象年龄/场所/关系；论文社区ARI/流感周曲线、学校/班级关闭周数据
- **获取/许可：** Zenodo API确认CC BY4.0且ZIP实际HTTP200（607,128字节）；论文补充PDF公开；病例/关闭曲线全部原始数值是否在ZIP未核实
- **措施：** 有历史分层停课规则与2016-02-08至02-16额外地区措施；并有2015秋疫苗与学校假期背景
- **人口/结构：** 450人（259学生、191成人）；181报告停课日；包含学生家庭，非全市随机样本
- **网络：** 有日记接触；与地区疫情同季但不是逐人配对感染/传播树
- **ABM用途：** 强辅助：可同时校准学校/家庭接触变化并以社区周曲线验证；需明确群体尺度不同
- **优点：** 真实停课期间行为测量，可避免把假期行为等同停课；开放原始日记
- **限制：** 学校家庭样本选择性；地区流感发病为ARI×阳性比例的估计，非逐例实验室确诊；无全市实测网络

来源：

1. [来源 1](https://zenodo.org/records/2992179)
2. [来源 2](https://zenodo.org/api/records/2992179/files/Dataset.zip/content)
3. [来源 3](https://www.contact-patterns.org/data)
4. [来源 4](https://pmc.ncbi.nlm.nih.gov/articles/PMC6613079/)

## SCHOOL-OUTBREAKS-YUAN — 全球35次学校COVID暴发/风险因素补充CSV

证据分工：PubMed摘要支持35次暴发、纳入发表时段；PMC Supporting information明确DataS1 (13.6KB CSV)及全部数据在补充数据中。尚未取得该文件，具体每行列与完整日期需随后核实；只把它作为事件级汇编与原报告检索入口。

- **范围：** 多国幼儿园/小学/中学暴发汇编，非高校单校队列
- **覆盖：** 纳入文献发表于2020-01至2021-07；具体暴发日期逐条查CSV和原报告
- **数据/粒度：** 35次暴发的index/secondary cases、contacts/SAR及学校类别、监测/措施等风险因素
- **获取/许可：** PubMed/PMC索引确认Data S1 13.6KB CSV和Data availability全在supplement；本次附件下载未完成；精确附件URL和许可未核实
- **措施：** 部分：措施/监测等分类变量，不能当逐日措施实施时间线
- **人口/结构：** 学校类别、接触人数等事件级分母，详细人口结构依原始报告
- **网络：** 无逐人实测网络
- **ABM用途：** 适合多事件attack rate/SAR分布的外部检验和继续追踪原报告；不适合拟合日曲线
- **优点：** 可快速拓展大量学校暴发一手来源；已有结构化CSV
- **限制：** 文献发表/报告偏倚；异质性和检测定义不一；不提供统一个体数据

来源：

1. [来源 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC9111692/)
2. [来源 2](https://pubmed.ncbi.nlm.nih.gov/35146922/)
3. [来源 3](https://doi.org/10.1111/irv.12968)

## SHIP-DIAMOND-2020 — Diamond Princess官方NIID/MHLW暴发报告

证据分工：官方迁移至JIHS后的NIID 20 Feb update各表/章节支持所有日期、分母与检测变化；Table2是163个已知发病日病例，不能当全体病例。官方621阳性specimens与619病例不同，重复测试不可混淆；日发病表范围是02-06至17，标题/图写6–20，使用表的实际日期。

- **范围：** 日本横滨隔离邮轮；非校园，乘客/船员封闭场景
- **覆盖：** 2020-01/02，NIID 20 Feb update含02-06至17日可读发病表；其他报告覆盖更早发病
- **数据/粒度：** 每日发病（已知onset子集）、PCR样本/阳性、年龄分布、乘客/船员、同舱病例、船上人数；非住院每日序列
- **获取/许可：** 日本JIHS迁移后的官方NIID HTML已打开，表格可直接转表；未发现完整公开line list；官方copyright/使用条款需依网站
- **措施：** 强：02-05至19初始检疫；02-11转全乘客系统PCR、先高龄后低龄；随后船员；阳性离船/同舱隔离重算规则
- **人口/结构：** 3,711人；年龄×症状表；乘客/船员与同舱结构
- **网络：** 无实测完整网络；仅舱室/船员结构及同舱暴露
- **ABM用途：** 强闭合场景对照：可验证报告/检测机制与分组曲线；与校园人口年龄结构差异大
- **优点：** 分母明确、政策与检测改变日期清楚；大量官方历史信息
- **限制：** 检测样本与受检人/病例不同且存在重复检测；onset缺失；乘客离船导致分母变化；病例报告数不等于感染日

来源：

1. [来源 1](https://id-info.jihs.go.jp/niid/en/2019-ncov-e/9417-covid-dp-fe-02.html)
2. [来源 2](https://www.cdc.gov/mmwr/volumes/69/wr/mm6912e3.htm)
3. [来源 3](https://pmc.ncbi.nlm.nih.gov/articles/PMC7078829/)

## US-HI-SCHOOL-H1N1 — 2009 Hawaii K–12学校/家庭H1N1暴发

证据分工：CDC MMWR直接支持353人/两个campus、10学生+1教师+5家庭、5月1–17发病、5月13通知/14新闻稿、未停课与6月4随访。16例包含家庭病例，不能除以353计算全体attack rate；学生attack rate仅10/353。

- **范围：** 美国Oahu单所学校两个校园＋家庭接触，非高校
- **覆盖：** 发病2009-05-01至05-17，病例确认05-12至26，主动随访至06-04；缺勤图自04月
- **数据/粒度：** 16确诊发病日图；每日缺勤；年级/家庭/性别/症状分布；0住院/死亡
- **获取/许可：** CDC官方MMWR HTML已打开；HTML表可转表，图需提数；未找到公开个体line list
- **措施：** 有：05-12调查、05-13家长信/校方会议、05-14新闻稿；明确学校未停课；06-04计划暑期结束
- **人口/结构：** 353走读学生，K–8 235、9–12 118；病例10学生/1教师/5家庭接触；共享图书馆食堂及校车背景
- **网络：** 无完整实测网络，有班级/设施/家庭结构叙述
- **ABM用途：** 中：小型学校+家庭ABM的外部验证；适合同时核对发病与缺勤观测定义
- **优点：** 人口、事件日期和未停课事实明确；低攻击率对照
- **限制：** 仅16例且可能漏诊；缺勤原因未收集，不能把缺勤当感染；图形数字化

来源：

1. [来源 1](https://www.cdc.gov/mmwr/preview/mmwrhtml/mm5851a3.htm)
2. [来源 2](https://stacks.cdc.gov/view/cdc/28926/cdc_28926_DS1.pdf)

## SHIP-USS-TR-2020 — USS Theodore Roosevelt航空母舰COVID暴发

证据分工：Kasper等NEJM原研究摘要/全文搜索索引支持4779/1271、03-11症状起、03-23首次阳性与03-27到关岛；CDC官方science update PDF提供图及研究范围/结局摘要，非原始数值表。NEJM附录抓取失败，无公开line list证据。

- **范围：** 美国海军航母/关岛隔离；非校园，年轻成人封闭工作居住场景
- **覆盖：** 回溯症状2020-03-11至05-18；阳性确认03-23至05-18
- **数据/粒度：** 症状确诊/疑似发病日图、性别/crew type分层图、确诊/疑似/无症状分布；总住院/ICU/死亡结局
- **获取/许可：** NEJM一手论文搜索索引和CDC官方文献汇编已核实；NEJM网页/附录本次抓取失败；无开放个体数据证明，图需数字化
- **措施：** 有：03-23首次阳性/识别暴发、03-27抵关岛，转酒店检疫和阳性隔离；详细个体转移日未公开
- **人口/结构：** 4,779 crew；1,271确诊＋60疑似；年轻健康成人为主，性别及crew type分组
- **网络：** 无可下载完整接触网络；不能把舰员名单或接触追踪当公开
- **ABM用途：** 中：年轻成人聚居场景的发病/最终attack rate外部检验，非直接校园真值
- **优点：** 群体分母及随访结局完整度高；有无症状筛查
- **限制：** 军队群体外推有限；早期记录质量、病例定义改变；只有图与汇总

来源：

1. [来源 1](https://www.nejm.org/doi/full/10.1056/NEJMoa2019375)
2. [来源 2](https://stacks.cdc.gov/view/cdc/97653/cdc_97653_DS1.pdf)

## 其他核实过但未列入主JSON的线索

- **2009纽约Queens高中H1N1初报**：CDC官方[MMWR](https://www.cdc.gov/mmwr/preview/mmwrhtml/mm5817a6.htm)公开44例每日onset（4月20–24日分别1/2/10/28/3），分母2,686学生+228员工，4月27停课。有[Lessler等完整研究](https://www.nejm.org/doi/pdf/10.1056/NEJMoa0906089?articleTools=true)与supplement线索，但本次未取得补充表。初报44例不代表完整暴发，适合作检索线索而非首选完整基准。
- **Salathé等2010美国高中**：[PMC/PNAS原研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC3009790/)说明788人、94%覆盖及单日接触，PMC索引列出7.1MB sd02.txt和9.1KB sd03.txt。原研究提及与最近流感季缺勤比较；本次未能打开附件定义，不能认定接触日与缺勤疫情同一时期逐人配对。可进一步核实，不将其当完整同群病例网络。
- **Flu Watch**：[原队列说明](https://pmc.ncbi.nlm.nih.gov/articles/PMC5837336/)明确数据当时非open access，欢迎战略合作。不能列作即取即用公开数据；历史论文状态不证明2026申请政策未变。
- **Oxford大学旧Early Alert测试统计**：旧网页本次未成功抓取，尚未证实可访问的完整历史下载；不要将Oxford全国政策tracker误称Oxford大学校园病例。

## 实际文件验证日志（未向项目安装依赖）

在用户指定simulation Python环境使用标准库urllib，已存在openpyxl读取XLSX；下载在内存中校验，未保存病例/接触原始文件。

|文件|结果|
|---|---|
|Cambridge Source Data MOESM7 XLSX|HTTP200；76,651字节；14 sheets；Figure2c周病例、Figure4b/4c分组计数|
|SocioPatterns primaryschool.csv.gz|HTTP200；476,062字节|
|SocioPatterns highschool_2011.csv.gz|HTTP200；90,561字节|
|SocioPatterns highschool_2012.csv.gz|HTTP200；155,267字节|
|SocioPatterns HighSchool2013_proximity_net.csv.gz|HTTP200；653,252字节|
|Zenodo Tomsk Dataset.zip|HTTP200；607,128字节；API许可cc-by-4.0|
|R-universe 1978/Derbyshire CSV endpoints|本次HTTP403；官方目录仍列出相应数据与导出格式|

不应将“阳性tests”“阳性persons”“有症状新发”“卧床现患”“缺勤”互换；下载状态仅代表本次核查。


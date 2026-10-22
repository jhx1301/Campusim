# 非COVID公共卫生来源补充证据

核查日期：2026-10-15；PH17—PH18，不修改已有来源表。

## PH17 CDC FluView / ILINet / FluSurv-NET

[官方互动入口](https://www.cdc.gov/fluview/overview/fluview-interactive.html)列门诊/病毒/住院历史应用。[ILINet操作PDF](https://gis.cdc.gov/grasp/fluview/FluViewPhase2QuickReferenceGuide.pdf)第8页明确Custom Download按数据源、地区、流感季导出CSV，并说明州数据须逐季获辖区批准；[住院应用PDF](https://gis.cdc.gov/GRASP/Fluview/FluViewPhase3QuickReferenceGuide.pdf)说明Download Data生成含CSV的ZIP。[CDC作者的历史研究](https://stacks.cdc.gov/view/cdc/41501/cdc_41501_DS1.pdf)确认ILINet体系始于1997–98季。住院起始年、2025–26季改全年、catchment、人口分母与抽样见[官方FluSurv-NET方法](https://www.cdc.gov/fluview/overview/influenza-hospitalization-surveillance.html)。本轮核实界面/文件说明，未真实导出全量CSV。

重要区别：ILI比例分母为门诊就诊量；FluSurv-NET住院率分母为指定catchment居民。不可把州ILI比例解释为居民感染率，亦不可把监测县住院率说成整个州的完全统计。

## PH18 WHO FluNet / FluID

[RespiMart当前官方说明](https://www.who.int/tools/RespiMart)明确FluNet自1997、FluID自2009。[FluNet页](https://www.who.int/tools/flunet/)说明国家级周病毒学汇总并列完整CSV及字典；[当前监测输出页](https://www.who.int/teams/global-influenza-programme/surveillance-and-monitoring/influenza-surveillance-outputs)同时列FluNet、FluID CSV和历史比较图。[FluID官方说明](https://www.who.int/teams/global-influenza-programme/surveillance-and-monitoring/fluid)说明定性/定量数据；[2010年官方flyer](https://cdn.who.int/media/docs/default-source/influenza/fluid_flyer.pdf?sfvrsn=a273cb6b_5)解释每周、ILI/ARI/SARI/肺炎、可选年龄和分母。旧flyer用于解释字段意图，不能保证现各国文件齐备。本轮FluNet下载链接被浏览器以不支持text/csv解析拒绝，未验证全文件内容，不应写成API失效。

重要区别：FluNet检出标本、FluID的ILI/SARI哨点与全国总感染/实验室确诊住院是不同观测量；两者都不含校园个体接触网络或完整措施时间线。


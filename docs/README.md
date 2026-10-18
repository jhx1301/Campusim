# Covasim docs

## CEMAS v1 开发文档

接续当前开发或交给新的 Codex 对话，请先读 [CEMAS v1 当前工作阅读索引](CEMAS_READING_INDEX.md)：当前进度、阅读顺序和下一阶段 Phase 3 的实施范围集中在这一份文档中。

日常开发从工程计划进入，再查看对应阶段的接口契约。

| 文档 | 用途 |
|---|---|
| [软件工程实现计划](cemas_v1_implementation_plan.md) | Phase 0–7 的工作范围、接口、产物和验收顺序 |
| [推荐实施协议](llm_recommended_protocol_v1.md) | 动作、观察、资源、实验与统计规则；第14节集中列出实施检查和待产物 |
| [机器可读协议](control_protocol_v1.json) | 实现及验证使用的协议数值、枚举与配置 |
| [Phase 0 契约](control_phase0_contracts.md) | 公共接口、schema 及公共/私有信息边界 |
| [Phase 1 契约](control_phase1_contracts.md) | 324 动作编解码、合法 mask 和动作解析 |
| [Phase 2 契约](control_phase2_contracts.md) | 联合动作执行、公共 ledger/观察和私有指标 |
| [Phase 6 构建计划](control_phase6_implementation_plan.md) | Baseline、源域开发与共同冻结的实施范围 |
| [Phase 6 实施契约](control_phase6_contracts.md) | 当前接口、命令、实际验收与未完成前置项 |

研究背景和旧版论文材料保存在 `archive/`：

- [LLM 基线与泛化研究方案](archive/llm_baseline_generalization_plan.md)：研究问题和设计理由，实施规则以现行协议为准。
- [旧版论文技术补充](archive/technical_supplement_llm_policy_agent.tex)：保留旧 P0–P4 方法与完整提示词，供历史结果和论文复现查阅。

## Tutorials

Please see the `tutorials` subfolder.

## Everything else

This folder includes source code for building the docs. Users are unlikely to need to do this themselves. Instead, view the Covasim docs at https://docs.covasim.org.

To build the docs, follow these steps:

1.  Make sure dependencies are installed::
    ```
    pip install -r requirements.txt
    ```

2.  Make the documents; there are many build options. In most cases, running `./build_docs` (to rerun the tutorials; takes 2 min) or `./build_docs never` (does not rebuild the tutorials; takes 15 s) is best. Alternatively, one can call `make html` directly.

3.  The built documents will be in `./_build/html`.

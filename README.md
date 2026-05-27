# Campusim —— 基于LLM的校园疫情管控Agent

Campusim 是一个基于智能体的校园疫情模拟器，源自 [Covasim](https://github.com/institutefordiseasemodeling/covasim) v3.1.7。本项目在其基础上扩展了**大学校园传播模型**与**LLM（大语言模型）驱动的政策决策系统**，通过智能体模拟疫情在宿舍、教室、实验室、办公室、社区等多层网络中的传播，并由 LLM 根据实时疫情状态动态选择最优干预策略。

## 核心特性

- **校园多层接触网络** —— 构建了宿舍（Dorm）、本科生教室（Undergrad Classroom）、研究生教室（Grad Classroom）、实验室/办公室（Office/Lab）、助教/教职工（TA/Faculty）、社区（Community）六层接触网络，部分层支持动态更新
- **三类校园干预措施** —— 定期无症状筛查（`campus_periodic_screening`）、线上教学（`campus_online_teaching`）、LLM政策智能体（`campus_policy_agent`）
- **LLM政策选择系统** —— 支持接入任意 OpenAI 兼容 API（DeepSeek、Qwen 等），根据疫情状态自动选择干预强度（P0-P4五级政策），含集成投票、安全护栏、决策约束等机制
- **消融实验框架** —— 完整的实验管理、决策日志、结果可视化流水线
- **兼容 Covasim 生态** —— 保留原 Covasim 全部功能，可直接使用其分析、校准、绘图工具

## 项目架构

```
covasim-main/
├── covasim/                    # 核心包
│   ├── sim.py                  # Sim 模拟引擎
│   ├── people.py               # 智能体（Person）及人群状态管理
│   ├── population.py           # 人群生成，含CampusClassroomLayer/CampusLabLayer
│   ├── parameters.py           # 参数默认值，含校园相关参数
│   ├── interventions.py        # 干预措施（含三个校园干预类）
│   ├── llm_policy.py           # LLM政策选择核心模块
│   ├── base.py                 # 基础类
│   ├── defaults.py             # 默认配色与绘图设置
│   ├── utils.py / misc.py      # 工具函数
│   ├── plotting.py             # 绘图模块
│   ├── analysis.py             # 分析器（TransTree、Fit等）
│   ├── immunity.py             # 免疫与变异株模型
│   └── run.py                  # 多模拟并行运行
├── examples/                   # 示例与实验脚本
│   ├── t19_campus_simple_demo.py       # 基础校园Demo
│   ├── t20_campus_llm_demo.py          # LLM政策选择Demo
│   ├── t17_campus_llm_thesis_experiments.py  # 消融实验批量运行
│   ├── t21_campus_thesis_defense_demo.py     # 答辩演示
│   ├── run_sim.py                       # 自定义运行入口
│   └── ...
├── tests/                      # 测试文件
├── data/                       # 疫情数据与人口数据
├── setup.py                    # 安装配置
└── requirements.txt            # 依赖列表
```

### 校园接触网络

当 `pop_type="campus"` 时，启动六层接触网络：

| 层标识 | 名称 | 动态更新 | 默认β | 说明 |
|--------|------|----------|-------|------|
| `d` | 宿舍(Dorm) | 否 | 2.0 | 同一宿舍楼的近距离接触 |
| `clu` | 本科生教室 | **是** | 1.0 | 按课程表动态生成课堂接触 |
| `clg` | 研究生教室 | **是** | 1.0 | 研究生课程动态接触 |
| `of` | 办公室/实验室 | **是** | 0.8 | 教职工与研究生的办公接触 |
| `ta` | 助教/教职工 | 否 | 1.2 | 教职工间学术接触 |
| `cm` | 社区 | **是** | 0.35 | 校园日常随机接触 |

### LLM 政策选择流程

```
Sim.run() → 到达决策间隔(dt)
         → campus_policy_agent.apply()
         → extract_campus_policy_state()    # 提取疫情状态
         → build_user_payload()              # 构建LLM提示
         → QwenPolicyClient.query()          # 调用LLM
         → parse_policy_response()           # 解析决策JSON
         → apply_policy_transition_constraint() # 施加过渡约束
         → 重写各层beta值、检测/筛查/追踪参数
         → 继续模拟
```

**五级政策目录（P0-P4）：**

| 级别 | 名称 | 教室β | 实验室β | 宿舍β | 检测力度 | 筛查力度 |
|------|------|-------|---------|--------|----------|----------|
| P0 | 正常 | 1.0× | 1.0× | 1.0× | 无 | 无 |
| P1 | 警戒 | 0.9× | 0.9× | 1.0× | 症状检测 | 无 |
| P2 | 中度干预 | 0.6× | 0.8× | 1.2× | 症状+密接 | 10%/天 |
| P3 | 严格干预 | 0.3× | 0.6× | 1.0× | 症状+密接 | 20%/天 |
| P4 | 紧急 | 0.0× | 0.4× | 1.0× | 全面检测 | 30%/天 |

**安全护栏：** 政策每次最多变化±1级（防止剧烈震荡）、ICU超负荷强制加重干预、最短持有间隔防止频繁切换。

## 快速开始

### 环境要求

- Python 3.9-3.11（64位）
- 推荐使用虚拟环境（Anaconda / venv）

### 安装

```bash
# 克隆仓库
git clone https://github.com/jhx1301/Campusim.git
cd Campusim

# 安装依赖
pip install -e .
```

### 配置 LLM API（可选）

如需使用 LLM 政策选择功能，设置环境变量：

```bash
# 使用 DeepSeek（默认）
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-v4-flash"

# 或使用其他兼容OpenAI接口的服务
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://your-api-endpoint"
export LLM_MODEL="your-model-name"
```

## 使用示例

### 基础校园模拟

```python
import covasim as cv

sim = cv.Sim(pop_type="campus", pop_size=5000, n_days=90)
sim.run()
sim.plot()
```

### 加入干预措施

```python
import covasim as cv

# 创建症状检测 + 定期筛查
screening = cv.campus_periodic_screening(
    start_day=7,
    daily_capacity=200,
    screen_groups={'course': 0.1, 'dorm': 0.05}
)

sim = cv.Sim(pop_type="campus", pop_size=5000, n_days=90, interventions=[screening])
sim.run()
sim.plot()
```

### LLM 政策智能体

```python
import covasim as cv
from covasim.llm_policy import QwenPolicyClient

# 创建LLM客户端
client = QwenPolicyClient(
    api_key="your-api-key",
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash"
)

# 创建政策智能体干预
agent = cv.campus_policy_agent(
    start_day=7,
    interval=7,              # 每7天决策一次
    decision_fn=client.make_decision,
    verbose=True
)

sim = cv.Sim(pop_type="campus", pop_size=5000, n_days=90, interventions=[agent])
sim.run()
sim.plot()
```

### 运行实验脚本

```bash
# LLM Demo（含中文日志）
python examples/t20_campus_llm_demo.py

# 批量消融实验
python examples/t17_campus_llm_thesis_experiments.py

# 答辩演示
python examples/t21_campus_thesis_defense_demo.py
```

## 核心模块说明

### `llm_policy.py` —— LLM政策决策

| 函数/类 | 说明 |
|---------|------|
| `make_default_policy_catalog()` | 定义P0-P4五级政策的具体参数 |
| `build_system_prompt()` | 构建包含流行病学原理的系统提示 |
| `build_user_payload()` | 根据当前模拟状态构建用户消息 |
| `extract_campus_policy_state()` | 提取关键疫情指标（发病率、各层传播、隔离数等） |
| `parse_policy_response()` | 解析LLM的JSON输出为结构化决策 |
| `QwenPolicyClient` | OpenAI兼容的API客户端 |
| `apply_policy_transition_constraint()` | 限制政策变化幅度 |
| `compute_policy_oscillation_score()` | 计算政策震荡指数 |
| `evaluate_policy_benchmark()` | 多维度政策评分 |

### `interventions.py` —— 校园干预类

| 类 | 说明 |
|----|------|
| `campus_periodic_screening` | 按人群分组（课程/实验室/宿舍）进行无症状筛查 |
| `campus_online_teaching` | 关闭线下课堂，增加宿舍接触，模拟封校 |
| `campus_policy_agent` | LLM驱动的每周策略编排器，核心贡献 |

## 致谢

本项目基于 [Covasim](https://github.com/institutefordiseasemodeling/covasim) (Institute for Disease Modeling) 开发，遵循原始许可协议。感谢原作者的杰出工作。

## 许可

本项目继承了 Covasim 的 MIT License，详见 [LICENSE](LICENSE) 文件。

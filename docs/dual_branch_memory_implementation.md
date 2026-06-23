# 双分支记忆检索与压缩机制 — 实现文档

> 版本：v1.0  
> 实现日期：2026-06-23  
> 对应计划：`deep-spinning-mccarthy.md` (Plan v3)

---

## 目录

1. [问题背景](#一问题背景)
2. [架构总览](#二架构总览)
3. [文件改动清单](#三文件改动清单)
4. [各文件详细改动](#四各文件详细改动)
5. [关键设计决策](#五关键设计决策)
6. [数据流与运行时行为](#六数据流与运行时行为)
7. [冷启动处理](#七冷启动处理)
8. [运行方式](#八运行方式)
9. [验证状态](#九验证状态)
10. [参数速查表](#十参数速查表)

---

## 一、问题背景

### 1.1 消融实验发现

2×2 消融实验（专家知识 × 记忆）结果显示：

| 配置 | expert knowledge | memory | 效果 |
|------|:---:|:---:|------|
| `ablation_no_expert_no_memory` | ✗ | ✗ | 基线 |
| `ablation_memory_only` | ✗ | ✓ | 略差 |
| **`ablation_expert_only`** | **✓** | **✗** | **最优** |
| `ablation_expert_and_memory` | ✓ | ✓ | 不如 expert_only |

**结论**：现有 `_build_recent_policy_memory()` 提供的平铺历史记忆不仅无帮助，还会误导 LLM。

### 1.2 问题根因

原记忆机制是"过去 N 周做了什么决策 + 效果数字"的原始堆砌：

- 缺乏**结构化趋势归纳**：LLM 需自行从多周数据中提取方向
- 缺乏**历史经验对照**：无法参考"类似情况下不同策略的效果"
- 信息密度低、噪声高，干扰 LLM 的专家知识判断

### 1.3 解决方案

实现**双分支记忆**机制：

1. **短期轨迹压缩**：将最近 N 周决策周期压缩为结构化摘要（策略路径、疫情趋势、调整稳定性）
2. **相似情景检索**：从历史经验库中检索"当前状态下不同策略的效果"，按策略分组呈现

---

## 二、架构总览

### 2.1 决策日数据流

```
决策日 t 的完整流程：

Phase 0 ─ finalize_pending_entry()           → episode store
           补全上一条 pending 记忆的执行反馈

Phase 1 ─ extract_campus_policy_state()
           提取截至 t-1 日的疫情状态 + r_eff_realtime

Phase 2 ─ 双分支记忆
  ├─ get_recent_completed_entries()           → episode store（始终执行）
  ├─ build_trend_context()                    始终执行（存入 SQLite）
  ├─ compress_short_term_trajectory()         仅 enable_memory_context=True
  │   └─ 策略路径 + 疫情趋势 + 稳定性 → summary_text
  └─ retrieve_similar_scenarios()             仅 enable_memory_context=True 且 global_store 存在
      └─ 4 分量相似度 → Top-K → 按策略分组 → summary_text

Phase 3-6 ─ build_user_payload() → LLM API → 约束 + 护栏 → applied_policy

Phase 7 ─ create_pending_entry()              → episode store
           保存当前状态 + 执行策略 + 预计算向量
```

### 2.2 双 Store 架构

```
build_collect 阶段：
┌─────────────────────────────┐
│  MemoryStore (可写)          │ ← 仅写入，不检索
│  enable_memory_context=False │    LLM 行为等同 expert_only
└─────────────────────────────┘
              │
              ▼ 冻结后
eval 阶段：
┌─────────────────────────────┐    ┌─────────────────────────────┐
│  global_memory_store (只读)  │    │  episode_store (可写, 内存)  │
│  冻结库：相似情景检索         │    │  per-seed：短期记忆 + 写入   │
└─────────────────────────────┘    └─────────────────────────────┘
              │                                │
              └──── 共享 EmbeddingProvider ─────┘
```

### 2.3 三种运行模式

| 模式 | `memory_store` | `global_memory_store` | `enable_memory_context` | LLM 行为 |
|------|:---:|:---:|:---:|------|
| `none` | None | None | — | 纯 expert_only |
| `build_collect` | 可写库 | None | False | expert_only + 写库 |
| `eval` | episode 内存库 | 只读冻结库 | True | 完整双分支记忆 |

---

## 三、文件改动清单

| 文件 | 类型 | 行数变化 | 说明 |
|------|:---:|:---:|------|
| `requirements.txt` | 修改 | +1 | 添加 `sentence-transformers` |
| `covasim/llm_memory.py` | **新建** | +1060 | 核心：存储、向量、压缩、检索 |
| `covasim/llm_policy.py` | 修改 | +70 | r_eff 实时计算、payload 双版本 |
| `covasim/interventions.py` | 修改 | +90 | agent 集成、两阶段写入 |
| `examples/t17_campus_llm_thesis_experiments.py` | 修改 | +100 | 实验策略、两阶段流程 |
| `tests/test_llm_memory.py` | **新建** | +290 | 22 个单元/冒烟测试 |

---

## 四、各文件详细改动

### 4.1 `requirements.txt`

```diff
  numpy
  numba
  pandas
  scipy<1.16.0
  statsmodels
  matplotlib
  sciris>=2.0.4
  openai>=1.0.0
+ sentence-transformers
```

用于 `S_text` 文本相似度分量，模型为 `paraphrase-multilingual-MiniLM-L12-v2`（384 维，~120MB）。

---

### 4.2 `covasim/llm_policy.py`

#### 4.2.1 `_extract_r_eff_realtime()` — 新增

**位置**：`_window_finite_mean()` 之后（约 line 947）

**动机**：`sim.results['r_eff']` 仅在仿真结束后 `compute_results()` 中计算。决策发生在仿真运行中，此时 `r_eff.values` 全为零。

**Fallback 链**：

```
1. sim.results['r_eff'] 有非零值？
   → source="results"（兼容测试 / 已完成仿真）

2. sim.people 有足够 recovered/dead？
   → source="realtime"（实时计算）
   → 公式：r_eff = mean_infectious_duration × (new_inf - n_imports) / n_infectious

3. 都不满足
   → source="unavailable"，值全零
```

**返回结构**：

```python
{
    "r_eff_mean": float,       # 窗口内均值
    "r_eff_current": float,    # 最近一日值
    "r_eff_trend": "up" | "down" | "flat",
    "source": "results" | "realtime" | "unavailable",
}
```

#### 4.2.2 `extract_campus_policy_state()` — 追加字段

**位置**：`intervention_burden_last_7d` 之后

```python
# r_eff 实时字段
r_eff_info = _extract_r_eff_realtime(sim, end_day, window)
state["r_eff_mean"] = r_eff_info["r_eff_mean"]
state["r_eff_current"] = r_eff_info["r_eff_current"]
state["r_eff_trend"] = r_eff_info["r_eff_trend"]
state["r_eff_source"] = r_eff_info["source"]
state["past_7d_summary"]["r_eff_current"] = r_eff_info["r_eff_mean"]

# 内部字段（_ 前缀，不发送给 LLM）
state["_scaled_pop"] = scaled_pop_size
```

`_scaled_pop` 供 `build_state_vector()` 计算 `diagnoses_per_1000`，通过 `_` 前缀确保 `build_user_payload()` 自动排除。

#### 4.2.3 `build_system_prompt()` — 追加记忆字段说明

**位置**：prompt 末尾，`SYSTEM_KNOWLEDGE_RULES` 之前

```python
"short_term_trajectory_summary describes recent policy evolution, "
"infection trend, growth ratio, and the observed feedback pattern "
"after the latest policy adjustment."

"similar_scenarios_summary describes historical situations with similar "
"epidemic states, grouped by the policy that was executed, showing "
"the observed outcomes for each policy choice."
```

#### 4.2.4 `build_user_payload()` — 双版本 payload

**改动前**：直接把完整 `state` dict 传给 LLM。

**改动后**：

```python
_EXCLUDE_KEYS = {"short_term_trajectory", "similar_scenarios", "_scaled_pop"}

llm_state = {
    k: v for k, v in state.items()
    if k not in _EXCLUDE_KEYS and not k.startswith("_")
}

# 注入摘要文本（非完整 JSON）
if state.get("short_term_trajectory"):
    llm_state["short_term_trajectory_summary"] = trajectory["summary_text"]
if state.get("similar_scenarios"):
    llm_state["similar_scenarios_summary"] = scenarios["summary_text"]
```

**设计意图**：
- 排除完整结构化记忆数据（控制 token 数）
- 排除 `_` 前缀内部字段
- 仅注入自然语言摘要

#### 4.2.5 `build_full_state_snapshot()` — 新增

```python
def build_full_state_snapshot(state):
    """深拷贝完整 state 用于 record 保存（含记忆数据）"""
    import copy
    return copy.deepcopy(state)
```

用于 `record["state_snapshot"]`，与发送给 LLM 的精简 payload 分离。

---

### 4.3 `covasim/llm_memory.py`（新建）

核心模块，包含双分支记忆的全部组件。

#### 4.3.1 SQLite Schema

```sql
-- 仿真运行元数据
CREATE TABLE simulations (
    simulation_id   TEXT PRIMARY KEY,
    rand_seed       INTEGER,
    scenario        TEXT,
    strategy        TEXT,
    pop_size        INTEGER,
    n_days          INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- 记忆条目主表（两阶段写入核心）
CREATE TABLE memory_entries (
    entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id   TEXT NOT NULL,
    decision_day    INTEGER NOT NULL,
    decision_date   TEXT,
    pop_size        INTEGER NOT NULL,

    -- 反馈状态
    feedback_status  TEXT DEFAULT 'pending',   -- pending | complete | partial
    feedback_start_day INTEGER,
    feedback_end_day   INTEGER,
    finalized_at       TEXT,

    -- 疫情标量指标（决策前状态）
    new_infections_per_1000  REAL,
    new_diagnoses_per_1000   REAL,
    r_eff_value              REAL,
    r_eff_trend              TEXT,
    r_eff_source             TEXT,
    growth_ratio             REAL,
    tests_per_1000           REAL,
    quarantined_per_1000     REAL,
    teaching_restriction     INTEGER,
    online_teaching          INTEGER,

    -- 趋势标签
    infection_trend  TEXT,
    diagnosis_trend  TEXT,
    risk_trend       TEXT,

    -- 分层传播占比（JSON）
    layer_contributions       TEXT,
    layer_transmission_trends TEXT,

    -- 策略信息
    policy_requested TEXT,      -- LLM 原始输出
    policy_executed  TEXT,      -- 护栏后实际执行
    policy_rank      INTEGER,
    risk_level       TEXT,

    -- 执行反馈（JSON，延迟写入）
    execution_feedback TEXT,

    -- 状态描述文本（用于 S_text）
    state_summary_text TEXT,

    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (simulation_id) REFERENCES simulations(simulation_id)
);

-- 预计算向量
CREATE TABLE memory_vectors (
    entry_id      INTEGER PRIMARY KEY,
    state_vector  TEXT,    -- JSON array, dim=8
    layer_vector  TEXT,    -- JSON array, dim=4
    trend_context TEXT,    -- JSON object, m 周期时间序列
    text_embedding TEXT,   -- JSON array, dim=384
    FOREIGN KEY (entry_id) REFERENCES memory_entries(entry_id)
);
```

#### 4.3.2 `EmbeddingProvider`

```python
class EmbeddingProvider:
    """延迟加载的 sentence-transformers 包装器"""

    def __init__(self, model_name="paraphrase-multilingual-MiniLM-L12-v2"):
        self._model = None  # 延迟到首次 encode() 时加载

    def encode(self, text: str) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model.encode([text])[0]  # 384 维
```

多个 `MemoryStore` 实例共享同一个 `EmbeddingProvider`，避免重复加载模型。

#### 4.3.3 `MemoryStore` 核心 API

```python
class MemoryStore:
    def __init__(self, db_path, read_only=False, embedding_provider=None):
        """
        db_path: SQLite 数据库路径（":memory:" 为内存库）
        read_only: True 时禁止写入（eval 阶段冻结库）
        embedding_provider: 共享的 EmbeddingProvider 实例
        """

    # --- 仿真管理 ---
    def register_simulation(self, simulation_id, rand_seed, scenario,
                            strategy, pop_size, n_days) -> None
    def get_all_simulation_ids(self) -> list[str]

    # --- 两阶段写入 ---
    def create_pending_entry(self, simulation_id, decision_day,
                             entry_data, state_vector, layer_vector,
                             trend_context, text_embedding) -> int
        """阶段一：保存决策前状态 + 执行策略，feedback_status='pending'"""

    def finalize_pending_entry(self, simulation_id, current_day,
                               sim, policy_catalog, window_days=7) -> int
        """阶段二：为最近 pending 条目补全执行反馈
           → feedback_status = 'complete' | 'partial'"""

    # --- 短期记忆读取 ---
    def get_recent_completed_entries(self, simulation_id, n,
                                     before_day=None) -> list[dict]
        """当前仿真最近 n 条 completed/partial 条目，时间升序"""

    # --- 全局相似情景检索 ---
    def get_candidate_entries_with_vectors(self, feedback_status='complete',
            exclude_simulation_id=None, exclude_entry_ids=None,
            before_day=None) -> list[dict]
        """历史候选条目 + 预计算向量"""

    def hydrate_entries(self, entry_ids: list[int]) -> list[dict]
        """Top-K 确定后延迟读取策略和反馈详情"""

    # --- 向量计算 ---
    def compute_text_embedding(self, text) -> np.ndarray

    # --- 生命周期 ---
    def close(self) -> None
```

**`read_only=True` 行为**：
- `create_pending_entry` / `finalize_pending_entry` → 抛出 `ReadOnlyError`
- `get_recent_completed_entries` / `get_candidate_entries_with_vectors` → 正常
- `compute_text_embedding` → 正常（检索需要编码当前查询）

#### 4.3.4 向量构建器

**`build_state_vector(state)` — 8 维**

| 维度 | 来源 | 归一化范围 |
|:---:|------|:---:|
| 0 | `new_infections_per_1000` | [0, 50] |
| 1 | `new_diagnoses_per_1000` | [0, 30] |
| 2 | `r_eff_mean` | [0, 4] |
| 3 | `growth_ratio` | [0, 3] |
| 4 | `tests_per_1000` | [0, 150] |
| 5 | `quarantined_per_1000` | [0, 80] |
| 6 | `teaching_restriction` | [0, 4] |
| 7 | `online_teaching` | {0, 1} |

归一化：`max(0, min(1, (v - lo) / (hi - lo)))`

**`build_layer_vector(state)` — 4 维**

| 维度 | 语义层 | 计算 |
|:---:|------|------|
| 0 | dorm | `d / total` |
| 1 | classroom | `(clu + clg) / total` |
| 2 | office_lab | `(of + ta) / total` |
| 3 | community | `cm / total` |

若 `total == 0`，返回全零向量。

**`build_trend_context(recent_entries, current_state, window=3)` — m 周期时间序列**

7 个指标的时间序列，每个长度为 `window`（默认 3）：
- `new_infections_per_1000`
- `new_diagnoses_per_1000`
- `r_eff`
- `dorm_share`, `classroom_share`, `office_lab_share`, `community_share`

#### 4.3.5 四个相似度分量

| 分量 | 函数 | 方法 | 选择理由 |
|------|------|------|---------|
| `S_state` | `state_distance_similarity()` | 归一化欧氏距离 | 严重程度向量的绝对值距离比方向更重要 |
| `S_layer` | `cosine_similarity()` | 余弦相似度 | 传播占比是结构性比例 |
| `S_trend` | `compute_trend_similarity()` | Pearson 相关（7 指标均值） | 时间序列趋势匹配 |
| `S_text` | `cosine_similarity()` | sentence-transformers 余弦 | 语义相似度 |

**`S_state` 公式**：

```python
dist = ||a - b||₂
max_dist = √d
similarity = max(0, 1 - dist / max_dist)
```

**`S_trend` 公式**：

```python
pearson_r = corrcoef(x, y)[0,1]
similarity = (r + 1) / 2   # 映射到 [0, 1]
```

**缺失分量处理**：

```python
def combine_similarity(parts, lambdas):
    """仅对非 None 分量加权，权重重新归一化"""
    valid = {k: v for k, v in parts.items() if v is not None}
    denom = sum(lambdas[k] for k in valid)
    return sum(lambdas[k] * valid[k] for k in valid) / denom
```

默认权重：

```python
{"state": 0.30, "layer": 0.25, "trend": 0.20, "text": 0.25}
```

#### 4.3.6 短期轨迹压缩

**入口**：

```python
def compress_short_term_trajectory(
    recent_entries: list[dict],
    current_state: dict,
    policy_catalog: dict,
) -> dict
```

**返回结构**：

```python
{
    "n_periods": int,
    "strategy_path": {
        "label": "maintaining" | "escalating" | "de_escalating" | "fluctuating",
        "rank_sequence": [int],
        "policy_sequence": [str],
    },
    "epidemic_trend": {
        "label": "sustained_relief" | "continued_growth" | "fluctuating",
        "infection_direction": "up" | "down" | "flat",
        "r_eff_direction": "up" | "down" | "flat",
        "growth_ratio_current": float,
    },
    "adjustment_stability": {
        "label": "no_recent_change" | "insufficient_observation"
               | "consistent_improvement" | "no_rebound"
               | "mixed_feedback" | "rebound_observed",
        "last_change_day": int | None,
        "last_change_direction": "upgrade" | "downgrade" | None,
        "observation_periods": int,
    },
    "summary_text": str,
}
```

**三个子压缩器**：

**(a) 策略路径 `compute_strategy_path_label`**

| 条件 | 标签 |
|------|------|
| 所有 rank 相同 | `maintaining` |
| 单调非降且至少一个 > 0 | `escalating` |
| 单调非升且至少一个 < 0 | `de_escalating` |
| 有升有降 | `fluctuating` |

**(b) 疫情趋势 `compute_epidemic_trend`**

| 条件 | 标签 |
|------|------|
| `up_count >= ceil(n/2)` | `continued_growth` |
| `down_count >= ceil(n/2)` | `sustained_relief` |
| 其他 | `fluctuating` |

**(c) 调整稳定性 `compute_adjustment_stability`**

算法：
1. 反向扫描找最近策略变化位置
2. 无变化 → `no_recent_change`
3. 变化后观察周期数 < 2 → `insufficient_observation`
4. 逐周期判断反馈方向（改善 / 反弹 / 持平）

**互斥优先级（从高到低）**：

| 优先级 | 条件 | 标签 |
|:---:|------|------|
| 1 | `all(improved)` | `consistent_improvement` |
| 2 | `any(rebounded) and any(improved)` | `mixed_feedback` |
| 3 | `any(rebounded)` | `rebound_observed` |
| 4 | `otherwise` | `no_rebound` |

**`no_rebound` 方向感知渲染**：

| `last_change_direction` | 中文渲染 |
|:---:|------|
| `upgrade` | 未观察到继续恶化 |
| `downgrade` | 未观察到反弹 |

**自然语言摘要模板**（约 80-120 字）：

```
近{n}周策略{path_label_cn}({policy_seq})。
疫情趋势{trend_label_cn}（感染{inf_dir}，R_eff {r_dir}，增长率{ratio}）。
最近一次{change_dir}（第{day}天）：{stability_label_cn}。
```

#### 4.3.7 相似情景检索

**入口**：

```python
def retrieve_similar_scenarios(
    current_state: dict,
    current_trend_context: dict,
    memory_store: MemoryStore,
    top_k: int = 6,
    cases_per_group: int = 2,
    lambdas: dict = None,
    exclude_entry_ids: list[int] | None = None,
) -> dict
```

**流程**：

```
1. 构建当前向量：build_state_vector() + build_layer_vector()
2. 编码当前文本 → current_text_emb
3. 获取候选（feedback_status='complete'）
4. 逐候选计算 4 分量 + 综合相似度
5. Top-K 排序
6. hydrate_entries() — 仅在确定 Top-K 后读取策略和反馈
7. 按 policy_executed 分组
8. 每组保留 ≤ cases_per_group 条最高相似度案例
9. 渲染 summary_text
```

**返回结构**：

```python
{
    "retrieved_count": int,
    "policy_groups": {
        "P2_moderate": {
            "count": int,
            "similarity_range": [float, float],
            "cases": [
                {
                    "similarity": float,
                    "risk_level": str,
                    "dominant_layer": str,
                    "infection_trend_at_time": str,
                    "infections_per_1000": float,
                    "growth_ratio": float,
                    "layer_contributions": dict,
                    "policy_executed": str,
                    "execution_feedback": {
                        "infection_change": float,
                        "tests_sum": float,
                        "mean_quarantined": float,
                        "teaching_restriction": int,
                        "online_teaching": bool,
                    }
                },
            ]
        },
    },
    "summary_text": str,
}
```

**摘要模板**（约 150-250 token）：

```
历史相似情景（共{N}例）:
[P2_moderate, {count}例, 相似度{range}]:
  · 案例1(相似度{s:.2f}): 风险{risk}, 主导层{layer}, 感染{inf}‰, 增长率{gr}。
    执行后: 感染变化{delta}, 隔离{quar}人。
  · 案例2(相似度{s:.2f}): ...
```

#### 4.3.8 `build_pending_memory_entry()`

```python
def build_pending_memory_entry(state: dict, record: dict, sim) -> dict
```

**关键字段映射**：

| entry 字段 | 来源 | 说明 |
|-----------|------|------|
| `policy_requested` | `record["model_policy_proposed"]` | LLM 原始输出（护栏前） |
| `policy_executed` | `record["applied_policy"]` | 护栏/约束后实际执行 |
| `execution_feedback` | `None` | 留给 finalize 补全 |
| `feedback_status` | `"pending"` | 固定值 |

---

### 4.4 `covasim/interventions.py`

#### 4.4.1 新增 import

```python
from . import llm_memory as cvlm
```

#### 4.4.2 `campus_policy_agent.__init__()` — 新增参数

```python
def __init__(self, ...,
    # --- 双分支记忆参数 ---
    memory_store=None,              # episode store（可写）
    global_memory_store=None,       # 冻结库（只读）
    enable_memory_context=True,     # 是否注入 LLM 上下文
    short_term_window=4,            # 短期记忆窗口
    similar_top_k=6,                # 全局检索 Top-K
    similar_cases_per_group=2,      # 每组保留案例数
    similarity_lambdas=None,        # 4 分量权重
    trend_context_window=3,         # 趋势上下文长度 m
    **kwargs
):
```

新增实例变量：

```python
self.simulation_id = None
```

#### 4.4.3 `initialize()` — 注册仿真

```python
# 在 sub_interventions 初始化之后
if self.memory_store is not None and not self.memory_store.read_only:
    import uuid
    self.simulation_id = f"{sim.label}_{sim['rand_seed']}_{uuid.uuid4().hex[:8]}"
    self.memory_store.register_simulation(
        self.simulation_id, sim['rand_seed'],
        scenario=str(sim.label), strategy=str(getattr(self, 'label', '')),
        pop_size=sim['pop_size'], n_days=sim['n_days'])
```

#### 4.4.4 `_run_decision_cycle()` — 完整重写

```python
def _run_decision_cycle(self, sim):
    # ═══ Phase 0：补全上一条 pending 记忆 ═══
    if self.memory_store is not None and not self.memory_store.read_only:
        self.memory_store.finalize_pending_entry(...)

    # ═══ Phase 1：提取当前状态 ═══
    state = cvlp.extract_campus_policy_state(...)

    # ═══ Phase 2：双分支记忆 ═══
    current_trend_context = None
    if self.memory_store is not None:
        recent = self.memory_store.get_recent_completed_entries(...)
        current_trend_context = cvlm.build_trend_context(recent, state, ...)

        if self.enable_memory_context:
            compressed = cvlm.compress_short_term_trajectory(recent, state, ...)
            state["short_term_trajectory"] = compressed

            if self.global_memory_store is not None:
                similar = cvlm.retrieve_similar_scenarios(
                    state, current_trend_context, self.global_memory_store, ...)
                state["similar_scenarios"] = similar

    # ═══ Phase 3-6：LLM 决策（现有逻辑不变）═══
    user_payload = cvlp.build_user_payload(state, self.policy_catalog)
    full_state_snapshot = cvlp.build_full_state_snapshot(state)
    record = {..., 'state_snapshot': full_state_snapshot, ...}

    try:
        response = self._request_decision(state)
        # 约束 + 护栏 → applied_policy
        self._set_policy(applied_policy, sim.t)
    except Exception:
        self._set_policy(fallback_policy, sim.t)

    # ═══ Phase 7：创建当前 pending 记忆 ═══
    if self.memory_store is not None and not self.memory_store.read_only:
        entry_data = cvlm.build_pending_memory_entry(state, record, sim)
        sv = cvlm.build_state_vector(state)
        lv = cvlm.build_layer_vector(state)
        te = self.memory_store.compute_text_embedding(
            cvlm.build_state_description_text(state))
        self.memory_store.create_pending_entry(
            self.simulation_id, sim.t, entry_data, sv, lv,
            current_trend_context, te)
```

所有记忆操作用 `try/except` 包裹，失败不中断决策流程。

#### 4.4.5 `finalize()` — 补全最后 pending

```python
def finalize(self, sim):
    super().finalize(sim)
    for interv in self.sub_interventions:
        ...
    self.sub_interventions = []

    # 补全最后一条 pending（观察天数可能不足 → partial）
    if self.memory_store is not None and not self.memory_store.read_only:
        try:
            self.memory_store.finalize_pending_entry(
                self.simulation_id, current_day=sim.npts,
                sim=sim, policy_catalog=self.policy_catalog,
                window_days=self.state_window_days)
        except Exception:
            pass  # Non-fatal
```

---

### 4.5 `examples/t17_campus_llm_thesis_experiments.py`

#### 4.5.1 新增 import

```python
import covasim.llm_memory as cvlm
```

#### 4.5.2 策略列表更新

```python
ABLATION_STRATEGIES = [
    "ablation_no_expert_no_memory",
    "ablation_memory_only",
    "ablation_expert_only",
    "ablation_expert_and_memory",
    "llm_dual_memory",           # 新增
]

API_STRATEGIES = {
    ...,
    "llm_dual_memory",           # 新增
}

STRATEGY_COLORS = {
    ...,
    "llm_dual_memory": "#e7298a",  # 新增
}
```

#### 4.5.3 argparse 新增参数

```python
parser.add_argument("--memory-mode",
    choices=["none", "build_collect", "eval"], default="none")
parser.add_argument("--memory-build-db", default=None)
parser.add_argument("--memory-eval-db", default=None)
parser.add_argument("--memory-build-seeds", type=int, default=5)
```

#### 4.5.4 `make_policy_agent()` — 新增签名 + 分支

```python
def make_policy_agent(args, strategy_name, outdir=None,
                      memory_store=None, global_memory_store=None,
                      enable_memory_context=True):
    ...
    if strategy_name == "llm_dual_memory":
        return cv.campus_policy_agent(
            ...,
            memory_store=memory_store,
            global_memory_store=global_memory_store,
            enable_memory_context=enable_memory_context,
            short_term_window=4,
            similar_top_k=6,
            similar_cases_per_group=2,
            trend_context_window=3,
            **common,
        )
```

#### 4.5.5 `run_strategy_once()` — 透传 memory 参数

```python
def run_strategy_once(args, config, scenario_name, strategy_name, seed, outdir,
                      memory_store=None, global_memory_store=None,
                      enable_memory_context=True) -> cv.Sim:
    ...
    agent = make_policy_agent(args, strategy_name, outdir,
                              memory_store=memory_store,
                              global_memory_store=global_memory_store,
                              enable_memory_context=enable_memory_context)
```

#### 4.5.6 `run_runs()` — per-seed episode store

```python
def run_runs(args, config, scenario_names, strategies, seeds, outdir, label,
             memory_store=None, global_memory_store=None,
             enable_memory_context=True, embedding_provider=None):
    for scenario_name, strategy_name, seed in product(...):
        # eval 模式：每个 seed 创建独立 episode store
        episode_store = None
        actual_memory_store = memory_store
        if global_memory_store is not None and strategy_name == "llm_dual_memory":
            episode_store = cvlm.MemoryStore(
                db_path=":memory:", read_only=False,
                embedding_provider=embedding_provider)
            actual_memory_store = episode_store

        sim = run_strategy_once(...,
            memory_store=actual_memory_store,
            global_memory_store=global_memory_store,
            enable_memory_context=enable_memory_context)

        if episode_store is not None:
            episode_store.close()
```

#### 4.5.7 两阶段入口函数

```python
def _run_memory_build_collect(args, config, scenario_names, seeds, outdir):
    """阶段一：收集记忆条目，不启用检索"""
    build_db_path = args.memory_build_db or str(outdir / "memory_build.db")
    embedding_provider = cvlm.EmbeddingProvider()
    build_store = cvlm.MemoryStore(db_path=build_db_path, read_only=False,
                                    embedding_provider=embedding_provider)

    result = run_runs(args, config, scenario_names, ["llm_dual_memory"], seeds,
                      outdir, label="memory_build_collect",
                      memory_store=build_store,
                      global_memory_store=None,
                      enable_memory_context=False,
                      embedding_provider=embedding_provider)

    build_store.close()
    return result


def _run_memory_eval(args, config, scenario_names, seeds, outdir):
    """阶段二：使用冻结库 + 完整双分支检索"""
    frozen_db_path = args.memory_eval_db or str(outdir / "memory_build.db")
    embedding_provider = cvlm.EmbeddingProvider()
    global_store = cvlm.MemoryStore(db_path=frozen_db_path, read_only=True,
                                     embedding_provider=embedding_provider)

    result = run_runs(args, config, scenario_names,
                      ["baseline_no_policy", "ablation_expert_only", "llm_dual_memory"],
                      seeds, outdir, label="memory_eval",
                      memory_store=None,  # per-seed episode store
                      global_memory_store=global_store,
                      enable_memory_context=True,
                      embedding_provider=embedding_provider)

    global_store.close()
    return result
```

#### 4.5.8 `run_memory_ablation()` 分发

```python
def run_memory_ablation(args, config, outdir):
    memory_mode = getattr(args, "memory_mode", "none")

    if memory_mode == "build_collect":
        return _run_memory_build_collect(args, config, scenario_names, seeds, outdir)
    elif memory_mode == "eval":
        return _run_memory_eval(args, config, scenario_names, seeds, outdir)

    # 标准消融（排除 llm_dual_memory）
    strategies = [s for s in strategies if s != "llm_dual_memory"]
    return run_runs(args, config, scenario_names, strategies, seeds, outdir, "memory_ablation")
```

---

### 4.6 `tests/test_llm_memory.py`（新建）

22 个单元/冒烟测试：

| 测试类 | 数量 | 覆盖范围 |
|--------|:---:|------|
| `TestMemoryStore` | 3 | 创建注册、两阶段写入、read_only 拦截 |
| `TestVectorBuilders` | 7 | 8 维 state 向量、4 维 layer 向量、空 layer、距离相似度、余弦相似度、Pearson 相似度、缺失分量归一化 |
| `TestTrendContext` | 3 | 基本构建、空输入、趋势相似度 |
| `TestTrajectoryCompression` | 4 | 基本压缩、空输入、escalating 标签、maintaining 标签 |
| `TestBuildPendingEntry` | 1 | pending 条目字段映射 |
| `TestStateDescription` | 1 | 状态描述文本生成 |
| `TestEmbeddingProvider` | 2 | 延迟加载验证、编码（需 `TEST_EMBEDDING_MODEL=1`） |

---

## 五、关键设计决策

### 5.1 两阶段写入（防信息泄露）

```
决策日 t  ：create_pending_entry(状态_t, 策略_t)
           → feedback_status = "pending"
           → execution_feedback = None

决策日 t+7：finalize_pending_entry()
           → 从 sim.results 计算 [t, t+6] 窗口的反馈
           → feedback_status = "complete" | "partial"
```

**保障**：当前决策只能看到已完成反馈的历史条目（`feedback_status IN ('complete', 'partial')`），不会看到当前周期的 pending 条目。

### 5.2 build_collect / eval 分离（实验公平性）

**问题**：所有 seed 共享增长中的记忆库 → seed 1 无历史，seed 3 有 seed 1+2 的经验 → 实验条件不一致。

**方案**：

| 阶段 | 目标 | enable_memory_context | 行为 |
|------|------|:---:|------|
| build_collect | 收集"原始历史经验" | False | LLM 等同 expert_only，策略分布不受记忆影响 |
| eval | 评估双分支记忆效果 | True | 所有 seed 共享同一冻结库，实验条件一致 |

### 5.3 S_state 选择距离而非余弦

严重程度向量 `[0.1, 0.1, ...]`（低风险）与 `[0.9, 0.9, ...]`（高风险）的余弦相似度可能很高（方向一致），但实际严重程度差异巨大。归一化欧氏距离更能反映绝对差异。

### 5.4 稳定性标签互斥优先级

消除了 `mixed_feedback` 与 `rebound_observed` 的规则重叠：

```python
if all(improved):
    → "consistent_improvement"
elif any(rebounded) and any(improved):
    → "mixed_feedback"         # 优先于 rebound_observed
elif any(rebounded):
    → "rebound_observed"
else:
    → "no_rebound"
```

### 5.5 `_scaled_pop` 内部字段命名约定

以 `_` 前缀标识内部字段，`build_user_payload()` 自动排除所有 `_` 前缀字段，确保不发送给 LLM。

### 5.6 记忆操作容错

所有 `_run_decision_cycle()` 中的记忆操作用 `try/except` 包裹：

```python
try:
    self.memory_store.finalize_pending_entry(...)
except Exception:
    pass  # Non-fatal: 记忆写入失败不应中断决策流程
```

---

## 六、数据流与运行时行为

### 6.1 双 Store 操作分配

| 操作 | 条件 | 使用的 Store | 原因 |
|------|------|:---:|------|
| `finalize_pending_entry` | `memory_store` 非 None | episode | 补全当前仿真的 pending |
| `get_recent_completed_entries` | `memory_store` 非 None | episode | 当前仿真的短期记忆 |
| `build_trend_context` | `memory_store` 非 None | 内存计算 | 存入 memory_vectors |
| `compress_short_term_trajectory` | `enable_memory_context=True` | 内存计算 | 注入 LLM 上下文 |
| `retrieve_similar_scenarios` | `enable_memory_context=True` 且 `global_memory_store` 非 None | **global** | 全局检索 |
| `create_pending_entry` | `memory_store` 非 None | episode | 新记忆写入 |
| `compute_text_embedding` | 写入 pending 时 | 共享 Provider | 避免重复加载 |

### 6.2 `exclude_entry_ids` 在不同模式下的行为

| 模式 | `global_memory_store` | `exclude_entry_ids` |
|------|:---:|------|
| build_collect | None | 不启用相似检索，不涉及 |
| eval | 冻结库实例 | 传 None（episode 和 global 库 ID 空间隔离） |

### 6.3 仿真运行时数据可用性

在 `sim.step()` 中，执行顺序为：

```
1. people.update_states_pre(t)    — 状态更新、flows 累计
2. people.update_contacts()
3. ★ interventions.apply(sim)     — 决策在此发生
4. people.update_states_post()    — 诊断、隔离更新
5. 传播计算                        — 新感染产生
6. results 写入                    — results[key][t] += count
7. t += 1
```

**含义**：决策时刻，`sim.results[key][0:t]` 包含截至前一天的完整数据，`[t]` 尚未包含今天的传播结果。代码通过 `end_day = decision_day - 1` 处理。

---

## 七、冷启动处理

| 决策次数 | 短期记忆 | 相似情景 | 系统行为 |
|:---:|------|------|------|
| 第 1 次 | 0 条 → `n_periods=0` | 0 例 → `retrieved_count=0` | 两个摘要为空 |
| 第 2-4 次 | 1-3 条 | 取决于冻结库 | 部分工作，`S_trend=None` 时权重重归一化 |
| 第 5 次+ | 满窗口 n=4 | 满 m=3 | 正常工作状态 |
| build_collect | `enable_memory_context=False` | 不检索 | LLM 等同 expert_only |

---

## 八、运行方式

### 8.1 标准消融（无记忆库）

```bash
python examples/t17_campus_llm_thesis_experiments.py \
    --preset quick --experiment memory --use-api
```

### 8.2 两阶段双分支记忆

```bash
# 阶段一：构建记忆库（不启用检索）
python examples/t17_campus_llm_thesis_experiments.py \
    --preset quick --experiment memory --use-api \
    --memory-mode build_collect \
    --memory-build-db examples/figures/campus_llm_thesis_experiments/memory_build.db

# 阶段二：评估（冻结库 + 完整双分支检索）
python examples/t17_campus_llm_thesis_experiments.py \
    --preset quick --experiment memory --use-api \
    --memory-mode eval \
    --memory-eval-db examples/figures/campus_llm_thesis_experiments/memory_build.db
```

### 8.3 运行测试

```bash
# llm_memory 单元测试
python -m pytest tests/test_llm_memory.py -v

# 含 embedding 模型测试
TEST_EMBEDDING_MODEL=1 python -m pytest tests/test_llm_memory.py -v
```

---

## 九、验证状态

| 检查项 | 状态 | 说明 |
|--------|:---:|------|
| `llm_memory.py` 模块导入 | ✅ | |
| `llm_policy.py` 模块导入 | ✅ | |
| `interventions.py` 模块导入 | ✅ | |
| `t17` 脚本语法 | ✅ | `py_compile` 通过 |
| `test_llm_memory.py` 22 个测试 | ✅ | 21 passed, 1 skipped |
| `test_extract_campus_policy_state_schema` | ✅ | r_eff fallback 修复 |
| `test_campus_llm_policy.py` 其他 8 个 | ⚠️ | 预存问题，非本次引入 |

**预存问题说明**：

| 失败测试 | 原因 |
|---------|------|
| `test_apply_policy_transition_constraint` | 测试期望对称 ±1 约束，代码实现非对称（仅降级步进限制，升级不受限） |
| `test_build_system_prompt_...debias_rules` | 测试期望的 `SYSTEM_KNOWLEDGE_RULES` 内容与实际不一致 |
| `campus_policy_agent_*` 系列 | 依赖上述 transition constraint 行为 |
| `test_qwen_policy_client_online_example_state` | 缺少测试夹具文件 `campus_policy_state_example.json` |

---

## 十、参数速查表

### Agent 参数

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `memory_store` | None | episode MemoryStore（可写） |
| `global_memory_store` | None | 全局 MemoryStore（eval 只读） |
| `enable_memory_context` | True | 是否注入记忆到 LLM 上下文 |
| `short_term_window` | 4 | 短期记忆读取最近 N 个 completed 周期 |
| `trend_context_window` | 3 | 趋势上下文时间序列长度 m |
| `similar_top_k` | 6 | 全局相似情景检索 Top-K |
| `similar_cases_per_group` | 2 | 每个策略组最多保留案例数 |
| `similarity_lambdas` | `{state:0.30, layer:0.25, trend:0.20, text:0.25}` | 4 分量权重 |

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `--memory-mode` | none | none / build_collect / eval |
| `--memory-build-db` | auto | 构建阶段数据库路径 |
| `--memory-eval-db` | auto | 评估阶段冻结数据库路径 |
| `--memory-build-seeds` | 5 | 构建阶段 seed 数量 |

### 归一化预设范围

| 特征 | 范围 | 单位 |
|------|:---:|:---:|
| new_infections | [0, 50] | per 1000 |
| new_diagnoses | [0, 30] | per 1000 |
| r_eff | [0, 4] | — |
| growth_ratio | [0, 3] | — |
| tests | [0, 150] | per 1000 |
| quarantined | [0, 80] | per 1000 |
| teaching_restriction | [0, 4] | 整数等级 |
| online_teaching | {0, 1} | 布尔 |

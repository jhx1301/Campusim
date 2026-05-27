"""
校园疫情传播仿真系统 —— 毕业答辩演示
========================================
"""

import os
import sys
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("COVASIM_VERBOSE", "0")

import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Noto Sans SC"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as pl
import numpy as np

import covasim as cv
import covasim.llm_policy as cvlp


# ============================================================
# 校园疫情仿真基本配置
# ============================================================
POP_SIZE = 3000           # 校园总人数
POP_INFECTED = 30         # 初始感染者人数
N_DAYS = 42               # 仿真天数（6周，6次决策周期）
RAND_SEED = 42            # 随机种子，保证结果可复现
DECISION_INTERVAL = 7     # 决策间隔（天），智能体每周评估一次疫情态势

# ============================================================
# LLM决策智能体配置
# ============================================================
# API 配置
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL)
MODEL = cvlp.DEFAULT_QWEN_MODEL


# ============================================================
# 构建仿真
# ============================================================

def build_agent_sim():
    """构建带LLM决策智能体的仿真。"""
    agent = cv.campus_policy_agent(
        start_day=0,
        decision_interval_days=DECISION_INTERVAL,  # 每周决策一次
        initial_policy="P0_normal",                 # 初始策略: 正常
        api_key=API_KEY,                            # LLM API 密钥
        base_url=BASE_URL,                          # API 地址
        model=MODEL,                                # 模型名称
        temperature=0.2,                            # 生成温度
        max_tokens=cvlp.DEFAULT_MAX_TOKENS,          # 最大输出 token
        use_theory_prompt=True,                     # 启用领域知识提示
        memory_weeks=4,                             # 保留4周历史记忆
        min_policy_hold_intervals=1,                # 策略至少维持1个周期
        defer_first_decision_until_interval=True,   # 积累一周数据后再决策
        label="llm_agent",
    )
    return cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=POP_SIZE,
            pop_infected=POP_INFECTED,
            n_days=N_DAYS,
            rand_seed=RAND_SEED,
        ),
        interventions=[agent],
        label="agent_sim",
    )





def print_section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_decision_detail(record, index):
    """打印单次LLM决策的详细信息。"""
    state = record.get("state_snapshot", {})
    summary = state.get("past_7d_summary", {})

    print(f"\n  ┌─ 第 {index} 次决策 "
          f"（第 {record.get('decision_day', '?')} 天）─────────")
    print(f"  │ 当前策略: {record.get('current_policy_before', 'N/A')}")

    print(f"  │ ── 疫情态势 ──")
    print(f"  │   近7日新增感染:  {summary.get('new_infections_sum', 'N/A'):>6} 人")
    print(f"  │   感染趋势:        {summary.get('new_infections_trend', 'N/A')}")
    print(f"  │   诊断趋势:        {summary.get('new_diagnoses_trend', 'N/A')}")
    print(f"  │   风险评估:        {summary.get('estimated_risk_trend', 'N/A')}")
    growth = state.get("growth_ratio_7d_vs_prev_7d", "N/A")
    if isinstance(growth, (int, float)):
        print(f"  │   7日增长率:       {growth:.2f}")
    else:
        print(f"  │   7日增长率:       {growth}")

    print(f"  │ ── LLM决策结果 ──")
    print(f"  │   提议策略:  {record.get('model_policy_proposed', 'N/A')}")
    print(f"  │   执行策略:  {record.get('applied_policy', 'N/A')}")
    print(f"  │   风险等级:  {record.get('risk_level', 'N/A')}")
    reason = record.get('reason', 'N/A')
    if isinstance(reason, str) and len(reason) > 80:
        reason = reason[:80] + "..."
    print(f"  │   决策理由:  {reason}")

    if record.get("fallback_used"):
        print(f"  │   [回退] {record.get('error_type', '')}")
    if record.get("guardrail_adjusted"):
        print(f"  │   [护栏调整] {record.get('guardrail_reason', '')}")
    print(f"  └{'─' * 46}")


def print_agent_metrics(sim):
    """打印智能体仿真的关键指标。"""
    res = sim.results
    cum_inf = res["cum_infections"][-1]
    cum_diag = res["cum_diagnoses"][-1]
    peak_quar = np.max(res["n_quarantined"].values)
    final_r_eff = res["r_eff"][-1]

    print(f"\n  累计感染:    {cum_inf:>8.0f} 人")
    print(f"  累计确诊:    {cum_diag:>8.0f} 人")
    print(f"  峰值隔离:    {peak_quar:>8.0f} 人")
    print(f"  最终 R_eff:  {final_r_eff:>8.3f}")


# ============================================================
# 接触层每日新增感染动画
# ============================================================

def build_layer_daily_data(sim):
    """从 infection_log 计算每日每层新增感染数。"""
    n_days = len(sim.tvec)
    # 合并 clu + clg → 课堂
    layer_names = ["宿舍", "课堂", "实验室", "教职工办公", "公共空间"]
    raw_keys = ["d", ["clu", "clg"], "of", "ta", "cm"]

    day_counts = defaultdict(lambda: np.zeros(n_days, dtype=int))
    for entry in sim.people.infection_log:
        layer = entry["layer"]
        day = int(entry["date"])
        if 0 <= day < n_days:
            day_counts[layer][day] += 1

    merged = []
    for keys in raw_keys:
        if isinstance(keys, list):
            arr = sum(day_counts[k] for k in keys)
        else:
            arr = day_counts[keys]
        merged.append(arr)

    # 只保留有传播的层
    active_idx = [i for i, arr in enumerate(merged) if arr.sum() > 0]
    names = [layer_names[i] for i in active_idx]
    data = [merged[i] for i in active_idx]
    return names, data


def show_figures(sim):
    """两个窗口同时弹出: 图1=每日新增感染折线图(静态), 图2=接触层柱状图(动画)。"""

    # ================================================================
    # 共享数据
    # ================================================================
    layer_names, layer_data = build_layer_daily_data(sim)
    n_layers = len(layer_names)
    n_days = len(sim.tvec)
    dates = sim.datevec
    daily_total = np.array([sum(d[t] for d in layer_data) for t in range(n_days)])
    avg7 = np.convolve(daily_total, np.ones(7)/7, mode='same')
    r_eff_vals = sim.results["r_eff"].values

    agent = sim["interventions"][0] if sim["interventions"] else None
    trace = getattr(agent, "policy_trace", []) if agent else []
    policy_by_day = {}
    decision_days = set()
    for t in trace:
        policy_by_day[t["day"]] = t.get("policy_id", "")
        decision_days.add(t["day"])
    decision_days = sorted(decision_days)

    policy_labels = {"P0_normal": "P0 正常", "P1_guarded": "P1 警戒",
                     "P2_moderate": "P2 中度", "P3_strong": "P3 强力",
                     "P4_emergency": "P4 紧急"}
    policy_colors = {"P0_normal": "#4CAF50", "P1_guarded": "#FFC107",
                     "P2_moderate": "#FF9800", "P3_strong": "#F44336",
                     "P4_emergency": "#9C27B0"}
    layer_colors = ["#D96C5F", "#2D936C", "#F2A65A", "#4F7CAC", "#9B59B6"]

    # ================================================================
    # 图1: 静态折线图（每日新增感染 + R_eff）
    # ================================================================
    fig1, ax1 = pl.subplots(figsize=(14, 6))

    ax1.bar(dates, daily_total, color="#D0D0D0", width=0.8, label="每日新增感染")
    ax1.plot(dates, avg7, color="#2D936C", lw=2.5, label="7日移动平均")

    ax1_reff = ax1.twinx()
    ax1_reff.plot(dates, r_eff_vals, color="#4F7CAC", lw=1.8, alpha=0.8, label="R_eff")
    ax1_reff.axhline(y=1.0, color="#4F7CAC", ls="--", lw=1, alpha=0.3)
    ax1_reff.set_ylabel("R_eff", fontsize=12, color="#4F7CAC")
    ax1_reff.set_ylim(0, max(3.0, np.max(r_eff_vals) * 1.2))

    for dd in decision_days:
        ax1.axvline(x=dates[min(dd, len(dates)-1)], color="#F2A65A",
                    ls=":", lw=1.5, alpha=0.5)

    ax1.set_title("每日新增感染趋势 + 有效再生数 R_eff", fontsize=16, fontweight="bold")
    ax1.set_xlabel("日期", fontsize=12)
    ax1.set_ylabel("新增感染人数", fontsize=12)
    ax1.set_xlim(dates[0], dates[-1])
    ax1.set_ylim(0, max(daily_total.max(), 5) * 1.2)
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper right", fontsize=9)
    fig1.tight_layout()

    # ================================================================
    # 图2: 接触层柱状图动画
    # ================================================================
    fig2, ax2 = pl.subplots(figsize=(13, 7))
    x_pos = np.arange(n_layers)

    bars = ax2.bar(x_pos, [d[0] for d in layer_data],
                   color=layer_colors[:n_layers], width=0.6)

    time_text = ax2.text(0.02, 0.95, "", transform=ax2.transAxes,
                         fontsize=18, fontweight="bold", va="top")
    total_text = ax2.text(0.02, 0.88, "", transform=ax2.transAxes,
                          fontsize=13, va="top")
    policy_text = ax2.text(0.98, 0.95, "", transform=ax2.transAxes,
                           fontsize=12, ha="right", va="top",
                           color="#2D936C", fontweight="bold")

    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(layer_names, fontsize=13)
    ax2.set_ylabel("当日新增感染人数", fontsize=13)
    ymax = max(d.max() for d in layer_data) * 1.3
    ax2.set_ylim(0, max(ymax, 5))
    ax2.set_title("各接触层每日新增感染 —— 智能体决策下的传播动态",
                  fontsize=16, fontweight="bold")
    ax2.grid(alpha=0.2, axis="y")

    cum_line, = ax2.plot([], [], lw=3, color="black", alpha=0.3, label="当日总计")
    ax2.legend(loc="upper right", fontsize=10)

    value_texts = []
    for i, (bar, d) in enumerate(zip(bars, layer_data)):
        vt = ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                      f"{d[0]}", ha="center", va="bottom",
                      fontsize=12, fontweight="bold",
                      color=layer_colors[i % len(layer_colors)])
        value_texts.append(vt)

    fig2.tight_layout()

    # ================================================================
    # 同时弹出两个窗口，动画驱动 fig2，fig1 保持静态
    # ================================================================
    pl.ion()
    fig1.show()
    fig2.show()

    while pl.fignum_exists(fig2.number):
        for day in range(n_days):
            if not pl.fignum_exists(fig2.number):
                break

            for i, (bar, d) in enumerate(zip(bars, layer_data)):
                bar.set_height(d[day])
                value_texts[i].set_y(d[day])
                value_texts[i].set_text(f"{d[day]}")

            time_text.set_text(f"第 {day} 天  ({n_days - 1 - day} 天后结束)")
            total_text.set_text(f"当日总计: {daily_total[day]} 人")

            w = 15
            xs = dates[max(0, day - w):day + 1]
            ys = daily_total[max(0, day - w):day + 1]
            cum_line.set_data(xs, ys)

            cur = None
            for d in sorted(policy_by_day, reverse=True):
                if d <= day:
                    cur = policy_by_day[d]
                    break
            if cur:
                policy_text.set_text(f"策略: {policy_labels.get(cur, cur)}")
                policy_text.set_color(policy_colors.get(cur, "#2D936C"))

            fig2.canvas.draw_idle()
            fig1.canvas.draw_idle()
            pl.pause(0.8)

    pl.ioff()
    pl.show()


# ============================================================
# 主程序
# ============================================================

def main():
    if not API_KEY:
        print("=" * 60)
        print("  错误: 未设置 DASHSCOPE_API_KEY 环境变量")
        print("  请先设置: set DASHSCOPE_API_KEY=your_key")
        print("=" * 60)
        return 1

    print_section("校园疫情传播仿真系统 —— 答辩演示")
    print(f"  校园人数: {POP_SIZE}  |  初始感染: {POP_INFECTED}  |  "
          f"仿真天数: {N_DAYS}  |  决策间隔: {DECISION_INTERVAL} 天")
    print(f"  LLM模型: {MODEL}")

    # ---- 运行仿真 ----
    print_section("运行智能体决策仿真（调用 LLM API）")
    sim = build_agent_sim()

    try:
        sim.run()
    except Exception as e:
        print(f"\n  运行失败: {e}")
        print("  请检查: 1) API Key 是否正确  2) 网络连接  3) API 账户余额")
        return 1

    # ---- 决策详情 ----
    agent = sim["interventions"][0]
    decision_history = getattr(agent, "decision_history", [])

    if decision_history:
        print_section("LLM 决策详细记录")
        for i, record in enumerate(decision_history, 1):
            print_decision_detail(record, i)

        api_calls = sum(1 for d in decision_history if not d.get("fallback_used"))
        fallbacks = sum(1 for d in decision_history if d.get("fallback_used"))
        guardrails = sum(1 for d in decision_history if d.get("guardrail_adjusted"))
        print(f"\n  总决策: {len(decision_history)}  |  "
              f"API调用: {api_calls}  |  "
              f"回退: {fallbacks}  |  "
              f"护栏调整: {guardrails}")
    else:
        print("  (仿真天数不足，未触发决策)")

    # ---- 策略时间线 ----
    trace = getattr(agent, "policy_trace", [])
    if trace:
        print_section("策略时间线")
        names = {"P0_normal": "P0 正常", "P1_guarded": "P1 警戒",
                 "P2_moderate": "P2 中度", "P3_strong": "P3 强力",
                 "P4_emergency": "P4 紧急"}
        parts = []
        cur = None
        for e in trace:
            pid = e.get("policy_id", "?")
            if pid != cur:
                parts.append(f"第{e.get('day', 0)}天 → {names.get(pid, pid)}")
                cur = pid
        print("  " + "  |  ".join(parts))

    # ---- 最终指标 ----
    print_section("最终指标")
    print_agent_metrics(sim)

    # ---- 双窗口：静态折线图 + 接触层动画 ----
    print_section("弹窗图表")
    print("  窗口1: 每日新增感染趋势 + R_eff (静态)")
    print("  窗口2: 各接触层每日新增感染堆叠柱状图 (动画)")
    print("  关闭动画窗口后程序结束...")
    show_figures(sim)

    print_section("演示完成")
    print()


if __name__ == "__main__":
    main()

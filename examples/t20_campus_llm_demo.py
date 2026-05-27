"""
校园疫情传播仿真系统 —— LLM智能决策Demo演示
==================================================
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime

os.environ.setdefault("COVASIM_VERBOSE", "0")

# 解决 Windows GBK 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Noto Sans SC"]
matplotlib.rcParams["axes.unicode_minus"] = False
import pylab as pl

import covasim as cv
import covasim.llm_policy as cvlp
import numpy as np


# ============================================================
# 配置参数
# ============================================================
POP_SIZE = 4000          # 校园总人数
POP_INFECTED = 30        # 初始感染人数
N_DAYS = 28              # 仿真天数 (4周)
RAND_SEED = 42           # 随机种子
DECISION_INTERVAL = 7    # 决策间隔 (每周一次)

OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_demo"

# DeepSeek API 配置
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL)
MODEL = cvlp.DEFAULT_QWEN_MODEL

# 颜色
COLOR_BASELINE = "#D96C5F"
COLOR_LLM = "#2D936C"


def print_section(title):
    """打印分隔标题。"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_subsection(title):
    """打印子标题。"""
    print(f"\n  ── {title} ──")


def print_decision_detail(record, index):
    """打印单次LLM决策的详细信息。"""
    print(f"\n  ┌─ 第 {index} 次决策 ─────────────────────────────")
    print(f"  │ 决策日期:     {record.get('decision_date', 'N/A')} (第 {record.get('decision_day', '?')} 天)")
    print(f"  │ 当前策略:     {record.get('current_policy_before', 'N/A')}")

    state = record.get("state_snapshot", {})
    if state:
        summary = state.get("past_7d_summary", {})
        print(f"  │ ── 当前疫情状态 ──")
        print(f"  │   近7日新增感染:   {summary.get('new_infections_sum', 'N/A')}")
        print(f"  │   新增感染趋势:    {summary.get('new_infections_trend', 'N/A')}")
        print(f"  │   有效再生数R_eff: {summary.get('r_eff_current', 'N/A')}")
        print(f"  │   风险趋势评估:    {summary.get('estimated_risk_trend', 'N/A')}")
        growth = state.get('growth_ratio_7d_vs_prev_7d', 'N/A')
        print(f"  │   7日增长率:       {growth}")
        layer_trends = state.get("layer_transmission_trends", {})
        if layer_trends:
            print(f"  │   各层传播趋势:")
            for layer_name, trend_info in layer_trends.items():
                print(f"  │     · {layer_name}: {trend_info.get('trend', '?')} "
                      f"(当前{trend_info.get('current_7d', 0):.0f}, "
                      f"前值{trend_info.get('prev_7d', 0):.0f})")

    print(f"  │ ── LLM决策结果 ──")
    proposed = record.get("model_policy_proposed", "N/A")
    applied = record.get("applied_policy", "N/A")
    risk = record.get("risk_level", "N/A")
    reason = record.get("reason", "N/A")
    print(f"  │   LLM提议策略:   {proposed}")
    print(f"  │   最终执行策略:  {applied}")
    print(f"  │   风险等级:      {risk}")
    print(f"  │   决策理由:      {reason}")

    if record.get("fallback_used"):
        print(f"  │   注意: 使用了回退策略 (错误: {record.get('error_type', 'N/A')})")
    if record.get("guardrail_adjusted"):
        print(f"  │   注意: 策略被护栏调整 (原因: {record.get('guardrail_reason', 'N/A')})")

    print(f"  └──────────────────────────────────────────")


def print_sim_metrics(sim, label):
    """打印仿真关键指标。"""
    res = sim.results
    cum_inf = res["cum_infections"][-1]
    cum_diag = res["cum_diagnoses"][-1]
    cum_tests = res["cum_tests"][-1]
    peak_quar = np.max(res["n_quarantined"].values)
    mean_quar = np.mean(res["n_quarantined"].values)
    final_r_eff = res["r_eff"][-1]

    print(f"\n  【{label}】")
    print(f"    累计感染:       {cum_inf:>8.0f} 人")
    print(f"    累计确诊:       {cum_diag:>8.0f} 人")
    print(f"    累计检测:       {cum_tests:>8.0f} 次")
    print(f"    峰值隔离:       {peak_quar:>8.0f} 人")
    print(f"    平均隔离:       {mean_quar:>8.1f} 人")
    print(f"    最终R_eff:      {final_r_eff:>8.3f}")


def print_policy_timeline(sim, label):
    """打印策略时间线。"""
    agent = sim["interventions"][0] if sim["interventions"] else None
    if agent is None:
        return
    trace = getattr(agent, "policy_trace", [])
    if not trace:
        return

    print(f"\n  【{label} - 策略时间线】")
    policy_names = {
        "P0_normal": "P0: 正常",
        "P1_guarded": "P1: 警戒",
        "P2_moderate": "P2: 中度",
        "P3_strong": "P3: 强力",
        "P4_emergency": "P4: 紧急",
    }
    current_policy = None
    timeline_parts = []
    for entry in trace:
        pid = entry.get("policy_id", "?")
        day = entry.get("day", 0)
        if pid != current_policy:
            timeline_parts.append(f"第{day}天→{policy_names.get(pid, pid)}")
            current_policy = pid
    print(f"    {' | '.join(timeline_parts)}")


# ============================================================
# 仿真构建函数
# ============================================================

def build_baseline_sim():
    """构建无干预基线仿真。"""
    return cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=POP_SIZE,
            pop_infected=POP_INFECTED,
            n_days=N_DAYS,
            rand_seed=RAND_SEED,
        ),
        label="baseline_no_policy",
    )


def build_llm_sim(log_path):
    """构建LLM智能决策仿真（调用真实API）。"""
    agent = cv.campus_policy_agent(
        start_day=0,
        decision_interval_days=DECISION_INTERVAL,
        initial_policy="P0_normal",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.2,
        max_tokens=cvlp.DEFAULT_MAX_TOKENS,
        use_theory_prompt=True,
        memory_weeks=4,
        ensemble_size=1,
        min_policy_hold_intervals=2,
        enable_burden_guardrail=True,
        defer_first_decision_until_interval=True,
        log_path=log_path,
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
        label="llm_single_memory",
    )


# ============================================================
# 绘图函数（弹窗输出）
# ============================================================

def show_policy_timeline_plot(sim_llm, decision_history):
    """图1: LLM策略等级变化阶梯图（独立大图）。"""
    dates = sim_llm.datevec
    llm_agent = sim_llm["interventions"][0]

    decision_days = sorted(set(
        d.get("decision_day") for d in decision_history
        if d.get("decision_day") is not None
    ))

    fig, ax = pl.subplots(figsize=(14, 5))

    trace = getattr(llm_agent, "policy_trace", [])
    if trace:
        trace_days = [t["day"] for t in trace]
        # 将天数转换为日期，确保与axvline的坐标一致
        trace_x = [dates[min(d, len(dates) - 1)] for d in trace_days]
        trace_ranks = [cvlp.get_policy_rank(t["policy_id"], llm_agent.policy_catalog)
                       for t in trace]
        ax.step(trace_x, trace_ranks, where="post",
                color=COLOR_LLM, lw=3)

        # 标注策略切换点
        policy_labels = {0: "P0: 正常", 1: "P1: 警戒", 2: "P2: 中度",
                         3: "P3: 强力", 4: "P4: 紧急"}
        for i in range(len(trace)):
            if i == 0 or trace_ranks[i] != trace_ranks[i - 1]:
                ax.annotate(
                    policy_labels.get(trace_ranks[i], "?"),
                    xy=(trace_x[i], trace_ranks[i]),
                    xytext=(trace_x[i], trace_ranks[i] + 0.3),
                    fontsize=11, fontweight="bold", color=COLOR_LLM,
                    ha="center",
                    arrowprops=dict(arrowstyle="->", color=COLOR_LLM, lw=1.2),
                )

    # 标记决策日
    for dd in decision_days:
        ax.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                   ls="--", lw=1.5, alpha=0.7)

    ax.set_title("LLM智能决策 —— 策略等级变化", fontsize=15, fontweight="bold")
    ax.set_xlabel("日期")
    ax.set_ylabel("策略等级")
    ax.set_yticks([0, 1, 2, 3, 4])
    ax.set_yticklabels(["P0: 正常", "P1: 警戒", "P2: 中度", "P3: 强力", "P4: 紧急"])
    ax.set_ylim(-0.3, 4.5)
    ax.grid(alpha=0.3, axis="y")
    ax.set_xlim(dates[0], dates[-1])
    fig.autofmt_xdate()
    fig.tight_layout()
    pl.show()


def show_comparison_plot(sim_baseline, sim_llm, decision_history):
    """图2: Baseline vs LLM 四面板对比图。"""
    dates = sim_baseline.datevec

    decision_days = sorted(set(
        d.get("decision_day") for d in decision_history
        if d.get("decision_day") is not None
    ))

    fig, axes = pl.subplots(2, 2, figsize=(14, 10))

    # 图1: 每日新增感染
    ax1 = axes[0, 0]
    new_inf_base = sim_baseline.results["new_infections"].values
    new_inf_llm = sim_llm.results["new_infections"].values
    # 原始每日值（细线）
    ax1.plot(dates, new_inf_base, color=COLOR_BASELINE, lw=0.8, alpha=0.5)
    ax1.plot(dates, new_inf_llm, color=COLOR_LLM, lw=0.8, alpha=0.5)
    # 7日移动平均（粗线）
    ma_base = np.convolve(new_inf_base, np.ones(7)/7, mode='same')
    ma_llm = np.convolve(new_inf_llm, np.ones(7)/7, mode='same')
    ax1.plot(dates, ma_base, label="无干预基线 (7日均)", color=COLOR_BASELINE, lw=2.5)
    ax1.plot(dates, ma_llm, label="LLM智能决策 (7日均)", color=COLOR_LLM, lw=2.5)
    for dd in decision_days:
        ax1.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax1.set_title("每日新增感染人数（细线=每日值，粗线=7日移动平均）")
    ax1.set_ylabel("人数/天")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    # 图2: 累计感染
    ax2 = axes[0, 1]
    ax2.plot(dates, sim_baseline.results["cum_infections"].values,
             label="无干预基线", color=COLOR_BASELINE, lw=2)
    ax2.plot(dates, sim_llm.results["cum_infections"].values,
             label="LLM智能决策", color=COLOR_LLM, lw=2)
    for dd in decision_days:
        ax2.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax2.set_title("累计感染人数")
    ax2.set_ylabel("人数")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    # 图3: 有效再生数 R_eff
    ax3 = axes[1, 0]
    ax3.plot(dates, sim_baseline.results["r_eff"].values,
             label="无干预基线", color=COLOR_BASELINE, lw=2)
    ax3.plot(dates, sim_llm.results["r_eff"].values,
             label="LLM智能决策", color=COLOR_LLM, lw=2)
    ax3.axhline(y=1.0, color="black", ls="--", lw=1, alpha=0.4, label="R_eff = 1.0")
    for dd in decision_days:
        ax3.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax3.set_title("有效再生数 R_eff")
    ax3.set_xlabel("日期")
    ax3.set_ylabel("R_eff")
    ax3.legend(fontsize=9)
    ax3.grid(alpha=0.3)

    # 图4: 每日隔离人数
    ax4 = axes[1, 1]
    ax4.plot(dates, sim_baseline.results["n_quarantined"].values,
             label="无干预基线", color=COLOR_BASELINE, lw=2)
    ax4.plot(dates, sim_llm.results["n_quarantined"].values,
             label="LLM智能决策", color=COLOR_LLM, lw=2)
    for dd in decision_days:
        ax4.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax4.set_title("每日隔离人数")
    ax4.set_xlabel("日期")
    ax4.set_ylabel("人数")
    ax4.legend(fontsize=9)
    ax4.grid(alpha=0.3)

    fig.suptitle("校园疫情传播仿真 —— LLM智能决策 vs 无干预基线",
                 fontsize=15, fontweight="bold", y=0.98)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    pl.show()


def show_final_metrics_bar(sim_baseline, sim_llm):
    """图3: 最终关键指标对比柱状图。"""
    metrics = [
        ("累计感染", sim_baseline.results["cum_infections"][-1],
         sim_llm.results["cum_infections"][-1]),
        ("累计检测", sim_baseline.results["cum_tests"][-1],
         sim_llm.results["cum_tests"][-1]),
        ("峰值隔离", np.max(sim_baseline.results["n_quarantined"].values),
         np.max(sim_llm.results["n_quarantined"].values)),
        ("最终R_eff", sim_baseline.results["r_eff"][-1],
         sim_llm.results["r_eff"][-1]),
    ]

    fig, axes = pl.subplots(1, 4, figsize=(16, 5))

    for i, (name, base_val, llm_val) in enumerate(metrics):
        ax = axes[i]
        bars = ax.bar(["无干预基线", "LLM智能决策"], [base_val, llm_val],
                      color=[COLOR_BASELINE, COLOR_LLM], width=0.5)
        ax.set_title(name, fontsize=13, fontweight="bold")
        ax.grid(alpha=0.3, axis="y")
        # 数值标签
        for bar, val in zip(bars, [base_val, llm_val]):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{val:.1f}", ha="center", va="bottom",
                    fontsize=11, fontweight="bold")

        # 对累计感染额外标注减少比例
        if name == "累计感染" and base_val > 0:
            reduction = (base_val - llm_val) / base_val * 100
            ax.set_ylabel("人数")
            ax.text(0.5, 0.05, f"↓ {reduction:.1f}%",
                    transform=ax.transAxes, ha="center",
                    fontsize=12, color=COLOR_LLM, fontweight="bold")

    fig.suptitle("校园疫情传播仿真 —— 关键指标对比",
                 fontsize=15, fontweight="bold", y=1.01)
    fig.tight_layout()
    pl.show()


# ============================================================
# 主程序
# ============================================================

def main():
    # ── 检查API Key ──
    if not API_KEY:
        print("=" * 70)
        print("  错误: 未设置 DASHSCOPE_API_KEY 环境变量")
        print("")
        print("  请先设置API Key:")
        print("    Windows CMD:  set DASHSCOPE_API_KEY=your_key")
        print("    Windows PS:   $env:DASHSCOPE_API_KEY='your_key'")
        print("    Linux/Mac:    export DASHSCOPE_API_KEY=your_key")
        print("")
        print("  获取API Key: https://api.deepseek.com")
        print("=" * 70)
        return 1

    print_section("校园疫情传播仿真系统 —— LLM智能决策Demo")
    print(f"  启动时间:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  校园人数:    {POP_SIZE}")
    print(f"  初始感染:    {POP_INFECTED}")
    print(f"  仿真天数:    {N_DAYS} 天 (4周)")
    print(f"  决策间隔:    每 {DECISION_INTERVAL} 天一次")
    print(f"  随机种子:    {RAND_SEED}")
    print(f"  LLM模型:     {MODEL}")
    print(f"  API地址:     {BASE_URL}")

    # ── 策略1: 无干预基线 ──
    print_section("策略1: 无干预基线 (Baseline)")
    print("  不采取任何干预措施，作为对照基准。")
    sim_baseline = build_baseline_sim()
    sim_baseline.run()
    print_sim_metrics(sim_baseline, "无干预基线")

    # ── 策略2: LLM智能决策 ──
    print_section("策略2: LLM智能决策 (LLM Policy)")
    print("  使用大语言模型分析疫情状态，智能选择防控策略。")
    print("  正在调用DeepSeek API进行决策...")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    log_path = str(OUTDIR / "llm_decision_log.jsonl")
    sim_llm = build_llm_sim(log_path)

    try:
        sim_llm.run()
    except Exception as e:
        print(f"\n  ❌ LLM仿真运行失败: {e}")
        print("  请检查:")
        print("    1. API Key是否正确")
        print("    2. 网络连接是否正常")
        print("    3. API账户是否有余额")
        return 1

    print_sim_metrics(sim_llm, "LLM智能决策")
    print_policy_timeline(sim_llm, "LLM智能决策")

    # ── LLM决策详情 ──
    llm_agent = sim_llm["interventions"][0]
    decision_history = getattr(llm_agent, "decision_history", [])

    if decision_history:
        print_section("LLM决策详细记录")
        for i, record in enumerate(decision_history, 1):
            print_decision_detail(record, i)

        print_subsection("决策统计")
        api_calls = sum(1 for d in decision_history if not d.get("fallback_used"))
        fallbacks = sum(1 for d in decision_history if d.get("fallback_used"))
        guardrails = sum(1 for d in decision_history if d.get("guardrail_adjusted"))
        print(f"    总决策次数:     {len(decision_history)}")
        print(f"    成功API调用:    {api_calls}")
        print(f"    Fallback次数:   {fallbacks}")
        print(f"    护栏调整次数:   {guardrails}")
    else:
        print("\n  ⚠ 未记录到LLM决策（仿真天数可能不足）")

    # ── 策略对比 ──
    print_section("两种策略最终对比")
    baseline_inf = sim_baseline.results["cum_infections"][-1]
    llm_inf = sim_llm.results["cum_infections"][-1]
    reduction = (baseline_inf - llm_inf) / baseline_inf * 100

    print(f"\n  {'策略':<16s} {'累计感染':>8s} {'累计检测':>8s} {'峰值隔离':>8s} {'最终R_eff':>10s}")
    print(f"  {'-' * 55}")
    for name, sim in [("无干预基线", sim_baseline), ("LLM智能决策", sim_llm)]:
        print(f"  {name:<16s} {sim.results['cum_infections'][-1]:>8.0f} "
              f"{sim.results['cum_tests'][-1]:>8.0f} "
              f"{np.max(sim.results['n_quarantined'].values):>8.0f} "
              f"{sim.results['r_eff'][-1]:>10.3f}")

    print(f"\n  LLM智能决策相较于无干预基线:")
    print(f"    累计感染减少: {baseline_inf - llm_inf:.0f} 人 ({reduction:.1f}%)")

    # ── 弹出图表窗口 ──
    print_section("弹出图表窗口")
    print("  关闭每个图表窗口后将继续弹出下一个...")

    print_subsection("图1: LLM策略等级变化")
    show_policy_timeline_plot(sim_llm, decision_history)

    print_subsection("图2: Baseline vs LLM 对比")
    show_comparison_plot(sim_baseline, sim_llm, decision_history)

    print_subsection("图3: 关键指标对比柱状图")
    show_final_metrics_bar(sim_baseline, sim_llm)

    print_section("LLM智能决策Demo运行完成")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  决策日志: {log_path}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

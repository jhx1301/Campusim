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

# 策略显示名称
STRATEGY_LABELS = {
    "baseline_no_policy": "无干预基线",
    "baseline_threshold": "阈值规则策略",
    "llm_single_memory": "LLM智能决策",
}
STRATEGY_COLORS = {
    "baseline_no_policy": "#D96C5F",
    "baseline_threshold": "#4F7CAC",
    "llm_single_memory": "#2D936C",
}


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

    # 如果有fallback或guardrail调整，高亮显示
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


def build_threshold_sim():
    """构建阈值规则策略仿真。"""
    def threshold_decision(state, policy_catalog):
        summary = state.get("past_7d_summary", {})
        burden = state.get("intervention_burden_last_7d", {})
        infections = float(summary.get("new_infections_sum", 0.0))
        r_eff = float(summary.get("r_eff_current", 0.0))
        quarantined = float(burden.get("mean_quarantined_per_1000", 0.0))

        if infections >= 70 or r_eff >= 1.25:
            pid, risk = "P4_emergency", "critical"
        elif infections >= 40 or r_eff >= 1.10:
            pid, risk = "P3_strong", "high"
        elif infections >= 18 or r_eff >= 1.00:
            pid, risk = "P2_moderate", "medium"
        elif quarantined >= 18:
            pid, risk = "P1_guarded", "medium"
        else:
            pid, risk = "P1_guarded", "low"
        return {"policy_id": pid, "risk_level": risk, "reason": "阈值规则输出"}

    agent = cv.campus_policy_agent(
        start_day=0,
        decision_interval_days=DECISION_INTERVAL,
        initial_policy="P0_normal",
        decision_fn=threshold_decision,
        use_theory_prompt=False,
        memory_weeks=0,
        min_policy_hold_intervals=1,
        enable_burden_guardrail=True,
        defer_first_decision_until_interval=True,
        label="threshold_agent",
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
        label="baseline_threshold",
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


def save_comparison_plot(sim_baseline, sim_threshold, sim_llm, decision_history, outdir):
    """生成三种策略的对比图。"""
    outdir.mkdir(parents=True, exist_ok=True)

    sims = {
        "baseline_no_policy": sim_baseline,
        "baseline_threshold": sim_threshold,
        "llm_single_memory": sim_llm,
    }

    dates = sim_baseline.datevec
    # 标记决策日
    decision_days = sorted(set(
        d.get("decision_day") for d in decision_history if d.get("decision_day") is not None
    ))

    fig = pl.figure(figsize=(16, 12))

    # 图1: 每日新增感染
    ax1 = fig.add_subplot(2, 3, 1)
    for key, sim in sims.items():
        ax1.plot(dates, sim.results["new_infections"].values,
                 label=STRATEGY_LABELS[key], color=STRATEGY_COLORS[key], lw=2)
    for dd in decision_days:
        ax1.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax1.set_title("每日新增感染人数")
    ax1.set_ylabel("人数/天")
    ax1.legend(fontsize=7)
    ax1.grid(alpha=0.3)

    # 图2: 累计感染
    ax2 = fig.add_subplot(2, 3, 2)
    for key, sim in sims.items():
        ax2.plot(dates, sim.results["cum_infections"].values,
                 label=STRATEGY_LABELS[key], color=STRATEGY_COLORS[key], lw=2)
    for dd in decision_days:
        ax2.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax2.set_title("累计感染人数")
    ax2.set_ylabel("人数")
    ax2.legend(fontsize=7)
    ax2.grid(alpha=0.3)

    # 图3: 有效再生数
    ax3 = fig.add_subplot(2, 3, 3)
    for key, sim in sims.items():
        ax3.plot(dates, sim.results["r_eff"].values,
                 label=STRATEGY_LABELS[key], color=STRATEGY_COLORS[key], lw=2)
    ax3.axhline(y=1.0, color="black", ls="--", lw=1, alpha=0.4, label="R_eff=1.0")
    for dd in decision_days:
        ax3.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax3.set_title("有效再生数 R_eff")
    ax3.set_ylabel("R_eff")
    ax3.legend(fontsize=7)
    ax3.grid(alpha=0.3)

    # 图4: 隔离人数
    ax4 = fig.add_subplot(2, 3, 4)
    for key, sim in sims.items():
        ax4.plot(dates, sim.results["n_quarantined"].values,
                 label=STRATEGY_LABELS[key], color=STRATEGY_COLORS[key], lw=2)
    for dd in decision_days:
        ax4.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                    ls=":", lw=1, alpha=0.6)
    ax4.set_title("每日隔离人数")
    ax4.set_xlabel("日期")
    ax4.set_ylabel("人数")
    ax4.legend(fontsize=7)
    ax4.grid(alpha=0.3)

    # 图5: LLM策略等级变化
    ax5 = fig.add_subplot(2, 3, 5)
    llm_agent = sim_llm["interventions"][0]
    if getattr(llm_agent, "policy_trace", None):
        trace = llm_agent.policy_trace
        trace_days = [t["day"] for t in trace]
        trace_ranks = [cvlp.get_policy_rank(t["policy_id"], llm_agent.policy_catalog)
                       for t in trace]
        ax5.step(trace_days, trace_ranks, where="post",
                 color=STRATEGY_COLORS["llm_single_memory"], lw=2.5)
        ax5.set_title("LLM策略等级变化")
        ax5.set_xlabel("日期")
        ax5.set_ylabel("策略等级")
        ax5.set_yticks([0, 1, 2, 3, 4])
        ax5.set_yticklabels(["P0:正常", "P1:警戒", "P2:中度", "P3:强力", "P4:紧急"])
        ax5.grid(alpha=0.3)
        for dd in decision_days:
            ax5.axvline(x=dates[min(dd, len(dates) - 1)], color="#F2A65A",
                        ls=":", lw=1.5, alpha=0.7)

    # 图6: 各策略最终指标柱状图
    ax6 = fig.add_subplot(2, 3, 6)
    labels = [STRATEGY_LABELS[k] for k in sims]
    cum_infs = [sims[k].results["cum_infections"][-1] for k in sims]
    colors = [STRATEGY_COLORS[k] for k in sims]
    bars = ax6.bar(labels, cum_infs, color=colors)
    ax6.set_title("最终累计感染人数对比")
    ax6.set_ylabel("累计感染人数")
    ax6.tick_params(axis="x", rotation=10)
    for bar, val in zip(bars, cum_infs):
        ax6.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 5,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax6.grid(alpha=0.3, axis="y")

    fig.suptitle("校园疫情传播仿真 —— LLM智能决策 vs 基线策略对比",
                 fontsize=16, fontweight="bold", y=0.98)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.94])

    fig_path = outdir / "campus_llm_demo.png"
    fig.savefig(fig_path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    return fig_path


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

    print_section("🏫 校园疫情传播仿真系统 —— LLM智能决策Demo")
    print(f"  启动时间:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  校园人数:    {POP_SIZE}")
    print(f"  初始感染:    {POP_INFECTED}")
    print(f"  仿真天数:    {N_DAYS} 天 (4周)")
    print(f"  决策间隔:    每 {DECISION_INTERVAL} 天一次")
    print(f"  随机种子:    {RAND_SEED}")
    print(f"  LLM模型:     {MODEL}")
    print(f"  API地址:     {BASE_URL}")

    # ── 运行三种策略的仿真 ──

    # 策略1: 无干预基线
    print_section("▶ 策略1: 无干预基线 (Baseline)")
    print("  不采取任何干预措施，作为对照基准。")
    sim_baseline = build_baseline_sim()
    sim_baseline.run()
    print_sim_metrics(sim_baseline, "无干预基线")

    # 策略2: 阈值规则
    print_section("▶ 策略2: 阈值规则策略 (Threshold)")
    print("  根据感染人数和R_eff的固定阈值自动切换策略等级。")
    sim_threshold = build_threshold_sim()
    sim_threshold.run()
    print_sim_metrics(sim_threshold, "阈值规则策略")
    print_policy_timeline(sim_threshold, "阈值规则策略")

    # 策略3: LLM智能决策
    print_section("▶ 策略3: LLM智能决策 (LLM Policy)")
    print("  使用大语言模型分析疫情状态，智能选择防控策略。")
    print("  正在调用DeepSeek API进行决策...")

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
        print_section("📋 LLM决策详细记录")
        for i, record in enumerate(decision_history, 1):
            print_decision_detail(record, i)

        # 统计
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

    # ── 三种策略对比 ──
    print_section("📊 三种策略最终对比")
    sims_data = [
        ("无干预基线", sim_baseline),
        ("阈值规则策略", sim_threshold),
        ("LLM智能决策", sim_llm),
    ]
    print(f"\n  {'策略':<16s} {'累计感染':>8s} {'累计检测':>8s} {'峰值隔离':>8s} {'最终R_eff':>10s}")
    print(f"  {'-' * 55}")
    baseline_inf = None
    for name, sim in sims_data:
        cum_inf = sim.results["cum_infections"][-1]
        if baseline_inf is None:
            baseline_inf = cum_inf
        avoided = baseline_inf - cum_inf
        reduction = (avoided / baseline_inf * 100) if baseline_inf > 0 else 0
        cum_tests = sim.results["cum_tests"][-1]
        peak_quar = np.max(sim.results["n_quarantined"].values)
        r_eff = sim.results["r_eff"][-1]
        print(f"  {name:<16s} {cum_inf:>8.0f} {cum_tests:>8.0f} {peak_quar:>8.0f} {r_eff:>10.3f}")

    print(f"\n  LLM策略相较于无干预:")
    llm_inf = sim_llm.results["cum_infections"][-1]
    llm_reduction = (baseline_inf - llm_inf) / baseline_inf * 100
    print(f"    累计感染减少: {baseline_inf - llm_inf:.0f} 人 ({llm_reduction:.1f}%)")

    # ── 生成图片 ──
    print_section("📈 生成对比图表")
    fig_path = save_comparison_plot(
        sim_baseline, sim_threshold, sim_llm, decision_history, OUTDIR
    )
    print(f"\n    图片已保存: {fig_path}")
    print(f"    决策日志:   {log_path}")

    print_section("✅ LLM智能决策Demo运行完成")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  结果目录: {OUTDIR}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

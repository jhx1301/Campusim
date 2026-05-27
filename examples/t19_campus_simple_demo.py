"""
校园疫情传播仿真系统 —— 基础Demo演示
=========================================
"""

import os
import sys


if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import numpy as np
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Noto Sans SC"]
matplotlib.rcParams["axes.unicode_minus"] = False
import pylab as pl
from datetime import datetime


# ============================================================
# 配置参数
# ============================================================
POP_SIZE = 5000          # 校园总人数
POP_INFECTED = 30        # 初始感染人数
N_DAYS = 60              # 仿真天数
RAND_SEED = 42           # 随机种子


def build_baseline_sim():
    """构建无干预的基线仿真。"""
    return cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=POP_SIZE,
            pop_infected=POP_INFECTED,
            n_days=N_DAYS,
            rand_seed=RAND_SEED,
        ),
        label="baseline",
    )


def build_intervention_sim():
    """构建带完整干预措施的仿真。"""
    # 症状检测: 对有症状者进行检测
    tp = cv.test_prob(
        symp_prob=0.12,
        asymp_prob=0.0,
        symp_quar_prob=0.40,
        asymp_quar_prob=0.0,
        start_day=3,
        label="symptomatic_testing",
    )

    # 校园定期筛查: 对不同人群按不同周期进行无症状筛查
    screen = cv.campus_periodic_screening(
        group_cycles=dict(
            teacher=3,    # 教师每3天
            lab=3,        # 实验室人员每3天
            dorm=5,       # 宿舍每5天
            course=7,     # 课程每7天
            id_bucket=10, # 其他人每10天
        ),
        daily_capacity=600,
        start_day=5,
        exclude_recent_days=2,
        test_delay=1,
        label="campus_screening",
    )

    # 接触追踪
    ct = cv.contact_tracing(
        trace_probs=dict(
            d=0.95, clu=0.90, clg=0.90,
            of=0.90, ta=0.80, cm=0.0,
        ),
        trace_time=dict(
            d=0, clu=1, clg=1, of=1, ta=1, cm=0,
        ),
        start_day=5,
        label="campus_tracing",
    )

    # 线上教学: 第25天起切换为线上教学
    online = cv.campus_online_teaching(
        start_day=25,
        end_day=45,
        dorm_change=1.20,
        community_change=0.60,
        lab_mode="reduce",
        lab_change=0.50,
        office_mode="reduce",
        office_change=0.70,
        label="online_teaching",
    )

    return cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=POP_SIZE,
            pop_infected=POP_INFECTED,
            n_days=N_DAYS,
            rand_seed=RAND_SEED,
        ),
        interventions=[tp, screen, ct, online],
        label="with_interventions",
    )


def print_section(title):
    """打印分隔标题。"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_metrics(sim, label):
    """打印仿真关键指标。"""
    res = sim.results
    cum_inf = res["cum_infections"][-1]
    cum_diag = res["cum_diagnoses"][-1]
    cum_tests = res["cum_tests"][-1]
    peak_quar = np.max(res["n_quarantined"].values)
    mean_quar = np.mean(res["n_quarantined"].values)
    final_r_eff = res["r_eff"][-1]
    peak_inf_day = np.argmax(res["new_infections"].values)
    peak_inf_val = np.max(res["new_infections"].values)

    print(f"\n  【{label}】")
    print(f"    累计感染人数:        {cum_inf:>8.0f} 人")
    print(f"    累计确诊人数:        {cum_diag:>8.0f} 人")
    print(f"    累计检测次数:        {cum_tests:>8.0f} 次")
    print(f"    峰值隔离人数:        {peak_quar:>8.0f} 人")
    print(f"    平均隔离人数:        {mean_quar:>8.1f} 人")
    print(f"    最终有效再生数 R_eff: {final_r_eff:>8.3f}")
    print(f"    峰值新增感染:        {peak_inf_val:>8.0f} 人 (第 {peak_inf_day} 天)")


def print_layer_transmission(sim, label):
    """打印各接触层传播统计。"""
    layers = ["d", "clu", "clg", "of", "ta", "cm"]
    layer_names = {"d": "宿舍", "clu": "本科课堂", "clg": "研究生课堂",
                   "of": "实验室", "ta": "教职工办公", "cm": "社区"}
    counts = {layer: 0 for layer in layers}
    for entry in sim.people.infection_log:
        layer = entry["layer"]
        if layer in counts:
            counts[layer] += 1

    print(f"\n  【{label} - 各层传播事件】")
    for layer in layers:
        bar = "█" * int(counts[layer] / max(1, max(counts.values())) * 30)
        print(f"    {layer_names[layer]:8s} ({layer:3s}): {counts[layer]:>5d}  {bar}")


def show_comparison_plot(sim_baseline, sim_interv):
    """生成并弹出基线 vs 干预的对比图窗口。"""

    dates = sim_baseline.datevec
    fig = pl.figure(figsize=(14, 10))

    # 图1: 每日新增感染
    ax1 = fig.add_subplot(2, 2, 1)
    new_inf_base = sim_baseline.results["new_infections"].values
    new_inf_interv = sim_interv.results["new_infections"].values
    # 原始每日值（细线）
    ax1.plot(dates, new_inf_base, color="#D96C5F", lw=0.8, alpha=0.5)
    ax1.plot(dates, new_inf_interv, color="#2D936C", lw=0.8, alpha=0.5)
    # 7日移动平均（粗线）
    ma_base = np.convolve(new_inf_base, np.ones(7)/7, mode='same')
    ma_interv = np.convolve(new_inf_interv, np.ones(7)/7, mode='same')
    ax1.plot(dates, ma_base, label="无干预 (基线)", color="#D96C5F", lw=2.5)
    ax1.plot(dates, ma_interv, label="有干预", color="#2D936C", lw=2.5)
    ax1.axvspan(dates[25], dates[44], color="#d9edf7", alpha=0.4, label="线上教学期间")
    ax1.set_title("每日新增感染人数（细线=每日值，粗线=7日移动平均）")
    ax1.set_ylabel("人数/天")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    # 图2: 累计感染
    ax2 = fig.add_subplot(2, 2, 2)
    ax2.plot(dates, sim_baseline.results["cum_infections"].values,
             label="无干预 (基线)", color="#D96C5F", lw=2)
    ax2.plot(dates, sim_interv.results["cum_infections"].values,
             label="有干预", color="#2D936C", lw=2)
    ax2.axvspan(dates[25], dates[44], color="#d9edf7", alpha=0.4)
    ax2.set_title("累计感染人数")
    ax2.set_ylabel("人数")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    # 图3: 隔离人数
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.plot(dates, sim_baseline.results["n_quarantined"].values,
             label="无干预 (基线)", color="#D96C5F", lw=2)
    ax3.plot(dates, sim_interv.results["n_quarantined"].values,
             label="有干预", color="#2D936C", lw=2)
    ax3.axvspan(dates[25], dates[44], color="#d9edf7", alpha=0.4)
    ax3.set_title("每日隔离人数")
    ax3.set_xlabel("日期")
    ax3.set_ylabel("人数")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3)

    # 图4: 有效再生数 R_eff
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.plot(dates, sim_baseline.results["r_eff"].values,
             label="无干预 (基线)", color="#D96C5F", lw=2)
    ax4.plot(dates, sim_interv.results["r_eff"].values,
             label="有干预", color="#2D936C", lw=2)
    ax4.axhline(y=1.0, color="black", ls="--", lw=1, alpha=0.5, label="R_eff = 1.0")
    ax4.axvspan(dates[25], dates[44], color="#d9edf7", alpha=0.4)
    ax4.set_title("有效再生数 R_eff")
    ax4.set_xlabel("日期")
    ax4.set_ylabel("R_eff")
    ax4.legend(fontsize=8)
    ax4.grid(alpha=0.3)

    fig.suptitle("校园疫情传播仿真 —— 基础干预效果对比",
                 fontsize=16, fontweight="bold", y=0.98)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    pl.show()


def main():
    print_section("校园疫情传播仿真系统 —— 基础Demo")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  校园人数: {POP_SIZE}")
    print(f"  初始感染: {POP_INFECTED}")
    print(f"  仿真天数: {N_DAYS}")
    print(f"  随机种子: {RAND_SEED}")

    # ---- 基线仿真（无干预） ----
    print_section("运行基线仿真（无任何干预措施）")
    sim_baseline = build_baseline_sim()
    sim_baseline.run()
    print_metrics(sim_baseline, "基线 (无干预)")

    # ---- 干预仿真 ----
    print_section("运行干预仿真（检测 + 筛查 + 追踪 + 线上教学）")
    sim_interv = build_intervention_sim()
    sim_interv.run()
    print_metrics(sim_interv, "干预组 (完整干预)")

    # ---- 对比分析 ----
    print_section("干预效果对比分析")
    cum_inf_base = sim_baseline.results["cum_infections"][-1]
    cum_inf_interv = sim_interv.results["cum_infections"][-1]
    reduction = (cum_inf_base - cum_inf_interv) / cum_inf_base * 100
    peak_base = np.max(sim_baseline.results["new_infections"].values)
    peak_interv = np.max(sim_interv.results["new_infections"].values)
    peak_reduction = (peak_base - peak_interv) / peak_base * 100

    print(f"\n    累计感染:  {cum_inf_base:.0f} → {cum_inf_interv:.0f}  (减少 {reduction:.1f}%)")
    print(f"    峰值新增:  {peak_base:.0f} → {peak_interv:.0f}  (减少 {peak_reduction:.1f}%)")
    print(f"    累计检测:  {sim_interv.results['cum_tests'][-1]:.0f} 次")

    # 各层传播统计
    print_layer_transmission(sim_interv, "干预组")

    # ---- 弹出对比图表 ----
    print_section("弹出对比图表窗口")
    print("  关闭图表窗口后程序将继续...")
    show_comparison_plot(sim_baseline, sim_interv)

    print_section("基础Demo运行完成")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


if __name__ == "__main__":
    main()

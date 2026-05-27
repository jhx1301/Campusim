"""
SEIR 仓室 + 接触层传播 动画 Demo
  - 图1: 四根柱子 S/E/I/R 随时间变化
  - 图2: 各接触层每日新增感染柱状图
"""

import os, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import numpy as np
from collections import defaultdict
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as pl
import matplotlib.animation as anim

# ========== 运行仿真 ==========
sim = cv.Sim(
    pars=dict(
        pop_type="campus", pop_size=5000,
        pop_infected=30, n_days=120, rand_seed=42,
    ),
    interventions=[
        cv.campus_periodic_screening(
            group_cycles=dict(teacher=3, lab=3, dorm=5, course=7, id_bucket=10),
            daily_capacity=600, start_day=5,
        ),
        cv.campus_online_teaching(
            start_day=25, end_day=45,
            dorm_change=1.20, community_change=0.60,
            lab_mode="reduce", lab_change=0.50,
        ),
    ],
)
sim.run()

# ========== 共享数据 ==========
days = sim.tvec
n_days = len(days)


# ================================================================
#  图1: SEIR 仓室动画
# ================================================================
def build_layer_daily_data(sim):
    """从 infection_log 计算每日每层新增感染数。"""
    # 合并 clu + clg → 课堂, 改名 cm → 公共空间
    layer_names = ["宿舍", "课堂", "实验室", "教职工办公", "公共空间"]
    raw_keys = ["d", ["clu", "clg"], "of", "ta", "cm"]

    day_counts = defaultdict(lambda: np.zeros(n_days, dtype=int))
    for entry in sim.people.infection_log:
        layer = entry["layer"]
        day = int(entry["date"])
        if 0 <= day < n_days:
            day_counts[layer][day] += 1

    # 合并层
    merged = []
    for i, keys in enumerate(raw_keys):
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


def show_seir_animation(sim):
    S = sim.results["n_susceptible"].values
    E = sim.results["n_preinfectious"].values
    I = sim.results["n_infectious"].values
    R = sim.results["n_recovered"].values

    fig, ax = pl.subplots(figsize=(12, 7))

    compartments = ["易感 S", "潜伏 E", "传染 I", "康复 R"]
    colors = ["#2D936C", "#F2A65A", "#D96C5F", "#4F7CAC"]
    data = [S, E, I, R]
    x_pos = np.arange(4)

    bars = ax.bar(x_pos, [d[0] for d in data], color=colors, width=0.6)

    time_text = ax.text(0.02, 0.95, "", transform=ax.transAxes,
                        fontsize=18, fontweight="bold", va="top")
    reff_text = ax.text(0.02, 0.88, "", transform=ax.transAxes,
                        fontsize=13, va="top")

    ax.set_xticks(x_pos)
    ax.set_xticklabels(compartments, fontsize=13)
    ax.set_ylabel("人数", fontsize=13)
    ax.set_ylim(0, sim.n * 1.05)
    ax.set_title("SEIR 仓室模型 —— 随时间变化", fontsize=16, fontweight="bold")
    ax.grid(alpha=0.2, axis="y")

    value_texts = []
    for i, bar in enumerate(bars):
        vt = ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f"{data[i][0]:.0f}", ha="center", va="bottom",
                     fontsize=12, fontweight="bold", color=colors[i])
        value_texts.append(vt)

    def animate(frame):
        day = frame
        for i, (bar, d) in enumerate(zip(bars, data)):
            bar.set_height(d[day])
            value_texts[i].set_y(d[day])
            value_texts[i].set_text(f"{d[day]:.0f}")

        time_text.set_text(f"第 {day} 天  ({n_days - 1 - day} 天后结束)")
        reff = sim.results["r_eff"].values[day]
        reff_text.set_text(f"R_eff = {reff:.3f}")

        if reff < 1.0:
            ax.set_facecolor("#f0fff0")
        else:
            ax.set_facecolor("#fff5f5")

        return [bars, time_text, reff_text, *value_texts]

    ani = anim.FuncAnimation(
        fig, animate, frames=n_days,
        interval=300, blit=False, repeat=True,
    )
    pl.tight_layout()
    pl.show()


# ================================================================
#  图2: 接触层每日新增感染动画
# ================================================================
def show_layer_animation(sim):
    """各接触层每日新增感染——堆叠柱状图动画。"""
    layer_names, layer_data = build_layer_daily_data(sim)
    n_layers = len(layer_names)

    # 对应每个层的颜色
    layer_colors = ["#D96C5F", "#2D936C", "#F2A65A", "#4F7CAC", "#9B59B6", "#E67E22"]

    fig, ax = pl.subplots(figsize=(13, 7))
    x_pos = np.arange(n_layers)

    # 初始柱子
    bars = ax.bar(x_pos, [d[0] for d in layer_data],
                  color=layer_colors[:n_layers], width=0.6)

    time_text = ax.text(0.02, 0.95, "", transform=ax.transAxes,
                        fontsize=18, fontweight="bold", va="top")
    total_text = ax.text(0.02, 0.88, "", transform=ax.transAxes,
                         fontsize=13, va="top")

    ax.set_xticks(x_pos)
    ax.set_xticklabels(layer_names, fontsize=13)
    ax.set_ylabel("当日新增感染人数", fontsize=13)
    ymax = max(d.max() for d in layer_data) * 1.3
    ax.set_ylim(0, max(ymax, 5))
    ax.set_title("各接触层每日新增感染", fontsize=16, fontweight="bold")
    ax.grid(alpha=0.2, axis="y")

    value_texts = []
    for i, (bar, d) in enumerate(zip(bars, layer_data)):
        vt = ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f"{d[0]}", ha="center", va="bottom",
                     fontsize=12, fontweight="bold",
                     color=layer_colors[i % len(layer_colors)])
        value_texts.append(vt)

    # 累计曲线（半透明背景线）
    cum_line, = ax.plot([], [], lw=3, color="black", alpha=0.3, label="当日总计")
    ax.legend(loc="upper right", fontsize=10)

    def animate(frame):
        day = frame
        for i, (bar, d) in enumerate(zip(bars, layer_data)):
            bar.set_height(d[day])
            value_texts[i].set_y(d[day])
            value_texts[i].set_text(f"{d[day]}")

        time_text.set_text(f"第 {day} 天  ({n_days - 1 - day} 天后结束)")
        daily_total = sum(d[day] for d in layer_data)
        total_text.set_text(f"当日总计: {daily_total} 人")

        # 累计折线（最近15天窗口）
        window = 15
        x_dates = sim.datevec[max(0, day - window):day + 1]
        y_totals = [sum(d[t] for d in layer_data)
                    for t in range(max(0, day - window), day + 1)]
        cum_line.set_data(x_dates, y_totals)
        cum_line.set_xdata(x_dates)
        cum_line.set_ydata(y_totals)
        ax.set_xlim(-0.5, n_layers - 0.5)

        # 线上教学期间高亮
        if 25 <= day <= 45:
            ax.set_facecolor("#fffbe6")
        else:
            ax.set_facecolor("white")

        return [bars, time_text, total_text, *value_texts, cum_line]

    ani = anim.FuncAnimation(
        fig, animate, frames=n_days,
        interval=350, blit=False, repeat=True,
    )
    pl.tight_layout()
    pl.show()


# ========== 主程序: 依次播放两个动画 ==========
if __name__ == "__main__":
    print("\n>>> 图1: SEIR 仓室动画 — 关闭窗口后继续...")
    show_seir_animation(sim)

    print(">>> 图2: 接触层传播动画 — 关闭窗口后继续...")
    show_layer_animation(sim)

    print("动画播放完毕。")

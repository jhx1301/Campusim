#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
校园疫情模拟 — 多层接触网络结构图
Multi-layer Contact Network Structure for Campus Epidemic Simulation

用途：生成论文中展示4层校园接触网络（宿舍/教室/实验室/公共空间）的示意图，
      每层 6~8 个节点，按各自连接规则生成边。

用法：python tools/plot_multilayer_network.py
输出：tools/fig/multilayer_network.pdf 和 .png
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# ── 中文字体 ──────────────────────────────────────────────
plt.rcParams["font.sans-serif"] = [
    "SimHei", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

# ── 配色 ──────────────────────────────────────────────────
C_STUDENT = "#4472C4"      # 蓝 — 学生
C_TEACHER = "#C00000"      # 红 — 教师
C_PERSON  = "#70AD47"      # 绿 — 公共空间人员
C_EDGE    = "#888888"      # 边
C_CLUSTER_BG = "#F2F2F2"   # 聚类背景

RNG = np.random.default_rng(42)

# ╔══════════════════════════════════════════════════════════╗
# ║                    网络生成函数                           ║
# ╚══════════════════════════════════════════════════════════╝

def make_dormitory(n_students=4):
    """宿舍层：微观结构聚类，簇内全连接。单一宿舍簇。"""
    members = list(range(n_students))
    edges = []
    for i in range(n_students):
        for j in range(i + 1, n_students):
            edges.append((members[i], members[j]))
    node_colors = [C_STUDENT] * n_students
    return edges, node_colors


def make_classroom(n_students=6, n_teachers=1, k_ts=4.0, k_ss=6.0):
    """教室层：固定班级 + 动态师生/生生边。"""
    teacher_ids = list(range(n_teachers))
    student_ids = list(range(n_teachers, n_teachers + n_students))
    edges = []

    # 师生边
    for t in teacher_ids:
        n_conn = RNG.poisson(k_ts)
        n_conn = max(1, min(n_conn, n_students))
        targets = RNG.choice(student_ids, n_conn, replace=False)
        for s in targets:
            edges.append((t, s))

    # 生生边
    n_ss = max(round(n_students * k_ss / 2), 1)
    for _ in range(n_ss):
        s1, s2 = RNG.choice(student_ids, 2, replace=False)
        if (s1, s2) not in edges and (s2, s1) not in edges:
            edges.append((s1, s2))

    node_colors = [C_TEACHER] * n_teachers + [C_STUDENT] * n_students
    return edges, node_colors, teacher_ids, student_ids, n_teachers + n_students


def make_lab(n_students=4, n_teachers=1, k_ts=3.0, k_ls=2.5):
    """实验室/办公室层：单一课题组 + 动态师生/生生边。"""
    teacher_ids = list(range(n_teachers))
    student_ids = list(range(n_teachers, n_teachers + n_students))
    edges = []

    for t in teacher_ids:
        n_ts = RNG.poisson(k_ts)
        n_ts = max(1, min(n_ts, n_students))
        targets = RNG.choice(student_ids, n_ts, replace=False)
        for s in targets:
            edges.append((t, s))

    n_ss = max(round(n_students * k_ls / 2), 1)
    for _ in range(n_ss):
        s1, s2 = RNG.choice(student_ids, 2, replace=False)
        if (s1, s2) not in edges and (s2, s1) not in edges:
            edges.append((s1, s2))

    node_colors = [C_TEACHER] * n_teachers + [C_STUDENT] * n_students
    return edges, node_colors, teacher_ids, student_ids, n_teachers + n_students


def make_common(n_people=8, avg_contacts=3):
    """公共空间层：全人群随机边。"""
    edges = []
    for i in range(n_people):
        n_conn = RNG.poisson(avg_contacts)
        n_conn = max(0, min(n_conn, n_people - 1))
        candidates = [j for j in range(n_people) if j != i]
        targets = RNG.choice(candidates, n_conn, replace=False)
        for j in targets:
            e = (min(i, j), max(i, j))
            if e not in edges:
                edges.append(e)
    node_colors = [C_PERSON] * n_people
    return edges, node_colors, n_people


# ╔══════════════════════════════════════════════════════════╗
# ║                    手工布局函数                           ║
# ╚══════════════════════════════════════════════════════════╝

def circ_positions(n, radius=1.2, start_angle=-np.pi / 2):
    angles = start_angle + 2 * np.pi * np.arange(n) / n
    return np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])


def single_cluster_positions(n, radius=0.85):
    """单簇居中圆形排列。"""
    positions = {}
    pts = circ_positions(n, radius=radius)
    for i in range(n):
        positions[i] = (pts[i, 0], pts[i, 1])
    return positions


def hub_spoke_positions(teacher_ids, student_ids, spoke_radius=1.3):
    """Hub-spoke：教师居中，学生围圆。"""
    positions = {}
    for i, t in enumerate(teacher_ids):
        offset = 0.25 * (i - (len(teacher_ids) - 1) / 2) if len(teacher_ids) > 1 else 0.0
        positions[t] = (offset, 0.0)
    spokes = circ_positions(len(student_ids), radius=spoke_radius)
    for i, s in enumerate(student_ids):
        positions[s] = (spokes[i, 0], spokes[i, 1])
    return positions




# ╔══════════════════════════════════════════════════════════╗
# ║                    绘制函数                               ║
# ╚══════════════════════════════════════════════════════════╝

def draw_panel(ax, positions, edges, node_colors, title, node_size=420):
    for u, v in edges:
        x1, y1 = positions[u]
        x2, y2 = positions[v]
        ax.plot([x1, x2], [y1, y2], "-", color=C_EDGE, alpha=0.5, linewidth=1.2, zorder=1)

    xs = [positions[i][0] for i in range(len(positions))]
    ys = [positions[i][1] for i in range(len(positions))]
    ax.scatter(xs, ys, c=node_colors, s=node_size, zorder=3,
               edgecolors="white", linewidths=0.9)

    ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-1.8, 1.8)
    ax.set_ylim(-1.8, 1.8)


def draw_cluster_bg(ax, positions, padding=0.55):
    """为单簇绘制浅色背景圆。"""
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    cx, cy = np.mean(xs), np.mean(ys)
    r = max(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) for x, y in zip(xs, ys)) + padding
    ax.add_patch(plt.Circle((cx, cy), r, color=C_CLUSTER_BG, alpha=0.5, zorder=0, ec="none"))


# ╔══════════════════════════════════════════════════════════╗
# ║                       主流程                             ║
# ╚══════════════════════════════════════════════════════════╝

def main():
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 9.5))
    axes = axes.flatten()

    # ── (a) 宿舍层：4人单簇，全连接 ────────────────────────
    edges, node_colors = make_dormitory(n_students=4)
    pos = single_cluster_positions(4, radius=0.85)
    draw_cluster_bg(axes[0], pos)
    draw_panel(axes[0], pos, edges, node_colors,
               "(a) 宿舍层 (Dormitory)\n微观结构聚类 · 簇内全连接")

    # ── (b) 教室层：1师+6生，Hub-Spoke ─────────────────────
    edges, node_colors, tids, sids, n = make_classroom(
        n_students=6, n_teachers=1, k_ts=4.0, k_ss=5.0)
    pos = hub_spoke_positions(tids, sids, spoke_radius=1.3)
    draw_panel(axes[1], pos, edges, node_colors,
               "(b) 教室层 (Classroom)\nHub-Spoke + 生生随机边")

    # ── (c) 实验室层：1师+4生，单组 Hub-Spoke ──────────────
    edges, node_colors, tids, sids, n = make_lab(
        n_students=4, n_teachers=1, k_ts=3.0, k_ls=2.5)
    pos = hub_spoke_positions(tids, sids, spoke_radius=1.1)
    draw_panel(axes[2], pos, edges, node_colors,
               "(c) 实验室/办公室层 (Lab / Office)\nHub-Spoke + 组内生-生边")

    # ── (d) 公共空间层：8人均匀圆周排列，随机边 ────────────
    edges, node_colors, _ = make_common(n_people=8, avg_contacts=3)
    pos = {i: (c[0], c[1]) for i, c in enumerate(circ_positions(8, radius=1.3))}
    draw_panel(axes[3], pos, edges, node_colors,
               "(d) 公共空间层 (Common Space)\n全人群随机边 · Poisson 度分布")

    # ── 共享图例 ──────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor=C_STUDENT, edgecolor="white", label="学生 Student"),
        mpatches.Patch(facecolor=C_TEACHER, edgecolor="white", label="教师 Teacher"),
        mpatches.Patch(facecolor=C_PERSON,  edgecolor="white", label="人员 Person"),
    ]
    fig.legend(handles=legend_elements, loc="lower center", ncol=3,
               frameon=True, fontsize=10, columnspacing=2.0, handlelength=1.5)

    fig.suptitle("校园疫情模拟 — 多层接触网络结构",
                 fontsize=14, fontweight="bold", y=1.01)

    plt.tight_layout(rect=[0, 0.06, 1, 0.97])

    # ── 输出 ──────────────────────────────────────────────
    out_dir = Path(__file__).resolve().parent / "fig"
    out_dir.mkdir(exist_ok=True)

    for fmt in ["pdf", "png"]:
        fpath = out_dir / f"multilayer_network.{fmt}"
        fig.savefig(str(fpath), dpi=300, bbox_inches="tight", facecolor="white")
        print(f"Saved: {fpath}")

    plt.close(fig)
    print("Done.")


if __name__ == "__main__":
    main()

"""Pairwise ablation plots with ±1 std confidence bands."""
import pandas as pd
import numpy as np
import pylab as pl
from pathlib import Path

OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_thesis_experiments"
COLORS = {
    "ablation_no_expert_no_memory": "#d6604d",
    "ablation_memory_only": "#4393c3",
    "ablation_expert_only": "#9970ab",
}
LABELS = {
    "ablation_no_expert_no_memory": "No Expert, No Memory",
    "ablation_memory_only": "Memory Only",
    "ablation_expert_only": "Expert Only",
}

daily = pd.read_csv(OUTDIR / "memory_daily_metrics.csv")

pairs = [
    ("ablation_no_expert_no_memory", "ablation_memory_only", "memory_effect"),
    ("ablation_no_expert_no_memory", "ablation_expert_only", "expert_effect"),
]

for scenario_name in ["medium", "high"]:
    daily_sc = daily[daily["scenario"] == scenario_name].copy()
    if daily_sc.empty:
        continue
    for s1, s2, tag in pairs:
        subset = daily_sc[daily_sc["strategy"].isin([s1, s2])].copy()

        fig = pl.figure(figsize=(13, 8))
        ax1 = fig.add_subplot(2, 1, 1)
        ax2 = fig.add_subplot(2, 1, 2)
        for s in [s1, s2]:
            sdata = subset[subset["strategy"] == s]
            days = sorted(sdata["day"].unique())
            cum_mean, cum_std = [], []
            new_mean, new_std = [], []
            for d in days:
                vals = sdata[sdata["day"] == d]
                cum_mean.append(vals["cum_infections"].mean())
                cum_std.append(vals["cum_infections"].std(ddof=0))
                new_mean.append(vals["new_infections"].mean())
                new_std.append(vals["new_infections"].std(ddof=0))
            days = np.array(days)
            cum_mean, cum_std = np.array(cum_mean), np.array(cum_std)
            new_mean, new_std = np.array(new_mean), np.array(new_std)

            label = LABELS.get(s, s)
            color = COLORS.get(s, "#666")
            ax1.plot(days, cum_mean, label=label, color=color, lw=2.5)
            ax1.fill_between(days, cum_mean - cum_std, cum_mean + cum_std, color=color, alpha=0.15)
            ax2.plot(days, new_mean, label=label, color=color, lw=2.0, alpha=0.9)
            ax2.fill_between(days, new_mean - new_std, new_mean + new_std, color=color, alpha=0.12)

        ax1.set_title(f"{scenario_name}: {LABELS[s1]} vs {LABELS[s2]}")
        ax1.set_ylabel("Cumulative infections")
        ax1.grid(alpha=0.3)
        ax1.legend(frameon=False)
        ax2.set_title("Raw daily new infections")
        ax2.set_xlabel("Day")
        ax2.set_ylabel("New infections/day")
        ax2.grid(alpha=0.3)
        ax2.legend(frameon=False)
        fig.tight_layout()
        path = OUTDIR / f"memory_{tag}_{scenario_name}.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        pl.close(fig)
        print(f"Saved: {path}")

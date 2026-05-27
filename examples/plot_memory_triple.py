"""Three-way comparison with ±1 std confidence bands."""
import pandas as pd
import numpy as np
import pylab as pl
from pathlib import Path

OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_thesis_experiments"
STRATEGIES = ["ablation_memory_only", "ablation_expert_only", "ablation_expert_and_memory"]
COLORS = ["#4393c3", "#9970ab", "#1b9e77"]
LABELS = ["Memory Only", "Expert Only", "Expert + Memory"]

daily = pd.read_csv(OUTDIR / "memory_daily_metrics.csv")

for scenario_name in ["medium", "high"]:
    daily_sc = daily[daily["scenario"] == scenario_name].copy()
    if daily_sc.empty:
        continue
    subset = daily_sc[daily_sc["strategy"].isin(STRATEGIES)].copy()

    fig = pl.figure(figsize=(13, 8))
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)
    for s, c, lb in zip(STRATEGIES, COLORS, LABELS):
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
        days_arr = np.array(days)
        cum_mean, cum_std = np.array(cum_mean), np.array(cum_std)
        new_mean, new_std = np.array(new_mean), np.array(new_std)

        ax1.plot(days_arr, cum_mean, label=lb, color=c, lw=2.5)
        ax1.fill_between(days_arr, cum_mean - cum_std, cum_mean + cum_std, color=c, alpha=0.14)
        ax2.plot(days_arr, new_mean, label=lb, color=c, lw=2.0, alpha=0.9)
        ax2.fill_between(days_arr, new_mean - new_std, new_mean + new_std, color=c, alpha=0.12)

    ax1.set_title(f"{scenario_name}: Memory Only vs Expert Only vs Expert+Memory")
    ax1.set_ylabel("Cumulative infections")
    ax1.grid(alpha=0.3)
    ax1.legend(frameon=False)
    ax2.set_title("Raw daily new infections")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("New infections/day")
    ax2.grid(alpha=0.3)
    ax2.legend(frameon=False)
    fig.tight_layout()
    path = OUTDIR / f"memory_triple_{scenario_name}.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    pl.close(fig)
    print(f"Saved: {path}")

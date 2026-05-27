"""Generate unsmoothed (raw daily) infection curves from existing memory ablation CSV."""
import pandas as pd
import numpy as np
import pylab as pl
from pathlib import Path

OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_thesis_experiments"
STRATEGY_COLORS = {
    "baseline_no_policy": "#d6604d",
    "ablation_no_expert_no_memory": "#d6604d",
    "ablation_memory_only": "#4393c3",
    "ablation_expert_only": "#9970ab",
    "ablation_expert_and_memory": "#1b9e77",
}


def _color_for(strategy: str) -> str:
    return STRATEGY_COLORS.get(strategy, "#666666")


daily = pd.read_csv(OUTDIR / "memory_daily_metrics.csv")

for scenario_name in ["medium", "high"]:
    daily_plot = daily[daily["scenario"] == scenario_name].copy()
    if daily_plot.empty:
        continue

    daily_mean = (
        daily_plot.groupby(["strategy", "day"], as_index=False)
        .agg(
            cum_infections=("cum_infections", "mean"),
            new_infections=("new_infections", "mean"),
        )
        .reset_index(drop=True)
    )

    fig = pl.figure(figsize=(13, 8))
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)
    for strategy_name, group in daily_mean.groupby("strategy", sort=False):
        ax1.plot(group["day"], group["cum_infections"], label=strategy_name, color=_color_for(strategy_name), lw=2.2)
        ax2.plot(group["day"], group["new_infections"], label=strategy_name, color=_color_for(strategy_name), lw=1.8, alpha=0.85)
    ax1.set_title(f"memory ablation: cumulative infections ({scenario_name}) — raw")
    ax1.set_xlabel("Day")
    ax1.set_ylabel("Cumulative infections")
    ax1.grid(alpha=0.3)
    ax2.set_title("Raw daily new infections (no smoothing)")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("New infections/day")
    ax2.grid(alpha=0.3)
    ax1.legend(frameon=False)
    fig.tight_layout()
    path = OUTDIR / f"memory_infection_curves_raw_{scenario_name}.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    pl.close(fig)
    print(f"Saved: {path}")

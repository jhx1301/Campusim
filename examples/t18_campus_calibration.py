"""
Campus model calibration to University of Notre Dame Fall 2020 outbreak data.

The University of Notre Dame experienced a well-documented COVID-19 outbreak in
August 2020 when students returned to campus (~12,000 students). The outbreak
had two distinct phases:

  Phase 1 (Aug 3-18): Natural epidemic growth before major interventions.
    Daily cases rose from 0 to ~89/day. The university detected the surge and
    imposed online-only classes, closed public spaces, and ramped up testing
    starting Aug 18.

  Phase 2 (Aug 19 onwards): Cases declined sharply as interventions took effect.

This script calibrates the campus transmission model to Phase 1 only, then
projects what would have happened without interventions. The gap between the
model projection and the observed data estimates the intervention effect.

Reference:
    Fox et al., "Rapid control of a university COVID-19 outbreak through
    aggressive public health measures" (MMWR / PLOS Pathogens, 2021).

Usage:
    python examples/t18_campus_calibration.py                     # quick (50 trials)
    python examples/t18_campus_calibration.py --n-trials 200      # thorough
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import numpy as np
import pylab as pl

HERE = Path(__file__).resolve().parent
DATA_EARLY = HERE.parent / "data" / "notre_dame_2020_early.csv"
DATA_FULL = HERE.parent / "data" / "notre_dame_2020_campus.csv"
DEFAULT_OUTDIR = HERE / "figures" / "campus_calibration"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate campus model to Notre Dame data.")
    parser.add_argument("--n-trials", type=int, default=50, help="Optuna trials.")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


def build_beta_layer(calib_pars: dict) -> dict:
    """Build a full beta_layer dict from calibrated scalar parameters."""
    return {
        "d": float(calib_pars["beta_layer_d"]),
        "clu": float(calib_pars["beta_layer_cl"]),
        "clg": float(calib_pars["beta_layer_cl"]),
        "of": float(calib_pars["beta_layer_cl"]) * 0.8,
        "ta": float(calib_pars["beta_layer_cl"]) * 1.2,
        "cm": float(calib_pars["beta_layer_cm"]),
    }


def make_sim_and_run(datafile: str, calib_pars: dict, n_days: int = 16) -> cv.Sim:
    """Create and run a campus sim with the given parameters."""
    pars = dict(
        pop_type="campus",
        pop_size=12_000,
        pop_infected=30,
        n_days=n_days,
        start_day="2020-08-03",
        beta=float(calib_pars["beta"]),
        beta_layer=build_beta_layer(calib_pars),
        rescale=False,
        verbose=0,
    )

    interventions = [
        cv.test_num(
            daily_tests="data",
            symp_test=80,
            quar_test=30,
            sensitivity=0.95,
        ),
    ]

    sim = cv.Sim(pars=pars, datafile=datafile, interventions=interventions, label="trial")
    sim.run()
    return sim


def compute_mismatch(sim, data) -> float:
    """Compute weighted mismatch between model and data.

    Weights: cum_diagnoses has higher weight to prioritize matching the total
    outbreak size, while new_diagnoses captures the daily curve shape.
    """
    weights = {"cum_diagnoses": 5.0, "new_diagnoses": 3.0}
    total = 0.0

    for key, weight in weights.items():
        sim_vals = getattr(sim.results[key], "values", None)
        if sim_vals is None or key not in data.columns:
            continue
        # Align dates
        sim_dates = list(sim.results["date"])
        data_vals = []
        sim_matched = []
        for date_val, data_val in data[key].items():
            if date_val in sim_dates:
                idx = sim_dates.index(date_val)
                sim_matched.append(sim_vals[idx])
                data_vals.append(data_val)
        if not sim_matched:
            continue
        sim_arr = np.array(sim_matched, dtype=float)
        data_arr = np.array(data_vals, dtype=float)
        mse = np.mean((sim_arr - data_arr) ** 2)
        total += weight * mse

    return float(total)


def run_calibration(datafile: str, n_trials: int = 50) -> dict:
    """Calibrate campus model to data using Optuna directly (no file-based storage).

    The loss function has two components:
      1. diagnosis_mismatch: weighted MSE between model and observed diagnoses
      2. r_eff_penalty: penalizes R_eff outside a plausible range

    This prevents the optimizer from matching diagnoses by inflating infections
    and relying on low ascertainment to compensate, which would produce an
    epidemiologically implausible R_eff.
    """
    import optuna

    R_EFF_TARGET = (1.5, 3.5)  # Acceptable range for campus with masks/distancing
    R_EFF_PENALTY_WEIGHT = 500.0  # Weight of R_eff penalty relative to diagnosis mismatch

    def objective(trial):
        calib_pars = {
            "beta": trial.suggest_float("beta", 0.005, 0.04),
            "beta_layer_d": trial.suggest_float("beta_layer_d", 1.0, 4.0),
            "beta_layer_cl": trial.suggest_float("beta_layer_cl", 0.3, 1.5),
            "beta_layer_cm": trial.suggest_float("beta_layer_cm", 0.1, 0.5),
        }
        try:
            sim = make_sim_and_run(datafile, calib_pars)
            mismatch = compute_mismatch(sim, sim.data)

            # R_eff penalty: penalize if outside the target range
            r_eff = sim.results["r_eff"].values
            valid = r_eff[np.isfinite(r_eff) & (r_eff > 0)]
            if len(valid) >= 5:
                early_r = float(valid[3:10].mean())  # Days 3-9, skip burn-in
                if early_r < R_EFF_TARGET[0]:
                    r_eff_penalty = R_EFF_PENALTY_WEIGHT * (R_EFF_TARGET[0] - early_r) ** 2
                elif early_r > R_EFF_TARGET[1]:
                    r_eff_penalty = R_EFF_PENALTY_WEIGHT * (early_r - R_EFF_TARGET[1]) ** 2
                else:
                    r_eff_penalty = 0.0
                loss = mismatch + r_eff_penalty
            else:
                loss = float("inf")
        except Exception:
            return float("inf")
        return loss

    # Use in-memory storage to avoid SQLite file locking on Windows
    study = optuna.create_study(
        study_name="campus_calib",
        storage="sqlite:///:memory:",
        direction="minimize",
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    return {
        "best_pars": study.best_params,
        "best_mismatch": study.best_value,
        "n_trials": len(study.trials),
    }


def run_with_pars(datafile: str, best_pars: dict, n_days: int) -> cv.Sim:
    """Run a single sim with the given parameters and return it."""
    return make_sim_and_run(datafile, best_pars, n_days=n_days)


def run_counterfactual(datafile_full: str, best_pars: dict) -> cv.Sim:
    """Run calibrated model for full 44-day period (no post-Aug-18 interventions)."""
    return make_sim_and_run(datafile_full, best_pars, n_days=44)


def make_plots(before_sim, after_sim, cf_sim, calib_result, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)

    data_early = before_sim.data
    data_full = cf_sim.data

    # ---- Plot 1: Before/after calibration fit to early data ----
    fig = pl.figure(figsize=(14, 5))
    ax1 = fig.add_subplot(1, 2, 1)
    ax1.plot(before_sim.results["date"], before_sim.results["cum_diagnoses"].values,
             label="Default params", color="#d6604d", lw=2)
    ax1.plot(after_sim.results["date"], after_sim.results["cum_diagnoses"].values,
             label="Calibrated params", color="#1b9e77", lw=2)
    ax1.scatter(data_early.index, data_early["cum_diagnoses"].values,
                label="Notre Dame (early)", color="black", s=20, zorder=5)
    ax1.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5, label="Intervention start")
    ax1.set_title("Calibration Fit (Early Phase, Aug 3-18)")
    ax1.set_xlabel("Date")
    ax1.legend(frameon=False)
    ax1.grid(alpha=0.3)
    fig.autofmt_xdate()

    ax2 = fig.add_subplot(1, 2, 2)
    ax2.plot(before_sim.results["date"], before_sim.results["new_diagnoses"].values,
             label="Default params", color="#d6604d", lw=2)
    ax2.plot(after_sim.results["date"], after_sim.results["new_diagnoses"].values,
             label="Calibrated params", color="#1b9e77", lw=2)
    ax2.scatter(data_early.index, data_early["new_diagnoses"].values,
                label="Notre Dame (early)", color="black", s=20, zorder=5)
    ax2.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5, label="Intervention start")
    ax2.set_title("Daily Diagnoses Fit (Early Phase)")
    ax2.set_xlabel("Date")
    ax2.legend(frameon=False)
    ax2.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    path = outdir / "01_calibration_fit_early.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    print(f"  Saved {path}")

    # ---- Plot 2: Counterfactual projection vs full data ----
    fig = pl.figure(figsize=(14, 5))
    ax1 = fig.add_subplot(1, 2, 1)
    ax1.plot(cf_sim.results["date"], cf_sim.results["cum_diagnoses"].values,
             label="Model projection (no intervention)", color="#d6604d", lw=2.5)
    ax1.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5, label="Intervention start (Aug 18)")
    ax1.scatter(data_full.index, data_full["cum_diagnoses"].values,
                label="Notre Dame observed", color="black", s=15, zorder=5, alpha=0.8)

    # Fill between model and data to show averted cases
    model_cum = cf_sim.results["cum_diagnoses"].values
    data_cum = data_full["cum_diagnoses"].values
    n_dates = min(len(model_cum), len(data_cum))
    ax1.fill_between(
        cf_sim.results["date"][:n_dates],
        model_cum[:n_dates],
        data_cum[:n_dates],
        alpha=0.2, color="#1b9e77", label="Estimated cases averted by interventions",
    )
    ax1.set_title("Counterfactual: What If No Interventions After Aug 18?")
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Cumulative Diagnoses")
    ax1.legend(frameon=False)
    ax1.grid(alpha=0.3)
    fig.autofmt_xdate()

    ax2 = fig.add_subplot(1, 2, 2)
    ax2.plot(cf_sim.results["date"], cf_sim.results["new_diagnoses"].values,
             label="Model projection (no intervention)", color="#d6604d", lw=2)
    ax2.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5, label="Intervention start (Aug 18)")
    ax2.scatter(data_full.index, data_full["new_diagnoses"].values,
                label="Notre Dame observed", color="black", s=15, zorder=5, alpha=0.8)
    ax2.set_title("Daily Diagnoses: Model vs Observed")
    ax2.set_xlabel("Date")
    ax2.legend(frameon=False)
    ax2.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    path = outdir / "02_counterfactual_projection.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    print(f"  Saved {path}")

    # ---- Plot 3: Infections vs diagnoses (ascertainment) ----
    fig = pl.figure(figsize=(12, 5))
    ax1 = fig.add_subplot(1, 2, 1)
    ax1.plot(cf_sim.results["date"], cf_sim.results["cum_infections"].values,
             label="Cum. infections (model)", color="#d6604d", lw=2)
    ax1.plot(cf_sim.results["date"], cf_sim.results["cum_diagnoses"].values,
             label="Cum. diagnoses (model)", color="#1b9e77", lw=2)
    ax1.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5)
    ax1.scatter(data_full.index, data_full["cum_diagnoses"].values,
                label="Notre Dame observed", color="black", s=15, zorder=5, alpha=0.8)
    ax1.set_title("True Infections vs Observed Diagnoses")
    ax1.legend(frameon=False)
    ax1.grid(alpha=0.3)
    fig.autofmt_xdate()

    ax2 = fig.add_subplot(1, 2, 2)
    new_inf = cf_sim.results["new_infections"].values
    new_diag = cf_sim.results["new_diagnoses"].values
    ax2.plot(cf_sim.results["date"], new_inf,
             label="New infections (model)", color="#d6604d", lw=1.5, alpha=0.7)
    ax2.plot(cf_sim.results["date"], new_diag,
             label="New diagnoses (model)", color="#1b9e77", lw=1.5)
    ax2.scatter(data_full.index, data_full["new_diagnoses"].values,
                label="Notre Dame observed", color="black", s=15, zorder=5, alpha=0.8)
    ax2.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5)
    ascertainment = new_diag.sum() / max(1, new_inf.sum()) * 100
    ax2.set_title(f"Daily: Ascertainment Rate = {ascertainment:.1f}%")
    ax2.legend(frameon=False)
    ax2.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    path = outdir / "03_infections_vs_diagnoses.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    print(f"  Saved {path}")

    # ---- Plot 4: Layer transmission composition ----
    infection_log = getattr(getattr(cf_sim, "people", None), "infection_log", [])
    if infection_log:
        layer_counts = {}
        for entry in infection_log:
            layer = entry.get("layer")
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
        if layer_counts:
            fig = pl.figure(figsize=(8, 5))
            layer_names = {
                "d": "Dormitory",
                "clu": "Class-UG",
                "clg": "Class-Grad",
                "of": "Lab/Office",
                "ta": "Staff",
                "cm": "Common Areas",
            }
            layers = sorted(layer_counts.keys())
            counts = [layer_counts[l] for l in layers]
            total = sum(counts)
            labels = [layer_names.get(l, l) for l in layers]
            colors = ["#d73027", "#fc8d59", "#fee090", "#91bfdb", "#4575b4", "#a6d96a"]
            bars = pl.bar(labels, [c / total * 100 for c in counts], color=colors[:len(layers)])
            pl.title("Transmission Share by Contact Layer (Calibrated Model)")
            pl.xlabel("Layer")
            pl.ylabel("Share of total transmissions (%)")
            for bar, count in zip(bars, counts):
                pl.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{count}\n({count / total * 100:.1f}%)", ha="center", fontsize=8)
            fig.tight_layout()
            path = outdir / "04_layer_transmission.png"
            fig.savefig(path, dpi=200, bbox_inches="tight")
            pl.close(fig)
            print(f"  Saved {path}")


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    if not DATA_EARLY.exists():
        print(f"ERROR: Early-phase data file not found: {DATA_EARLY}")
        return 1
    if not DATA_FULL.exists():
        print(f"ERROR: Full data file not found: {DATA_FULL}")
        return 1

    print("=" * 60)
    print("Campus Model Calibration to Notre Dame Fall 2020 Outbreak")
    print("=" * 60)
    print(f"Calibration data: {DATA_EARLY} (early phase, Aug 3-18)")
    print(f"Full data:        {DATA_FULL} (full outbreak, Aug 3-Sep 15)")
    print(f"Trials: {args.n_trials}")
    print(f"Output: {outdir}")
    print()

    # ---- Default parameters for "before" comparison ----
    default_pars = dict(
        beta=0.016,
        beta_layer_d=2.0,
        beta_layer_cl=1.0,
        beta_layer_cm=0.35,
    )

    # ---- Step 0: Run with default parameters (before calibration) ----
    print("Step 0: Running with default parameters...")
    sim_before = make_sim_and_run(str(DATA_EARLY), default_pars)
    mismatch_before = compute_mismatch(sim_before, sim_before.data)
    print(f"  Default mismatch: {mismatch_before:.4f}")

    # ---- Step 1: Calibrate ----
    print(f"\nStep 1: Calibrating ({args.n_trials} Optuna trials)...")
    calib_result = run_calibration(str(DATA_EARLY), n_trials=args.n_trials)

    best_pars = calib_result["best_pars"]
    print(f"\nBest parameters found:")
    for key, value in best_pars.items():
        print(f"  {key}: {value:.4f}")
    print(f"  mismatch: {calib_result['best_mismatch']:.4f}")

    # ---- Step 2: Run with best parameters ----
    print("\nStep 2: Running with calibrated parameters...")
    sim_after = make_sim_and_run(str(DATA_EARLY), best_pars)
    mismatch_after_calib = compute_mismatch(sim_after, sim_after.data)
    improvement = (mismatch_before - mismatch_after_calib) / mismatch_before * 100
    print(f"  Calibrated mismatch: {mismatch_after_calib:.4f}")
    print(f"  Improvement:         {improvement:.1f}%")

    # ---- Step 3: Counterfactual projection ----
    print("\nStep 3: Counterfactual projection (full 44 days, no interventions)...")
    cf_sim = run_counterfactual(str(DATA_FULL), best_pars)

    data_full = cf_sim.data
    print(f"\nCounterfactual model outcomes (full 44 days, no interventions):")
    print(f"  Cum. infections:  {cf_sim.results['cum_infections'][-1]:.0f}")
    print(f"  Cum. diagnoses:   {cf_sim.results['cum_diagnoses'][-1]:.0f}")
    print(f"  Peak new diag:    {cf_sim.results['new_diagnoses'].values.max():.0f}")
    print(f"  Peak day:         {np.argmax(cf_sim.results['new_diagnoses'].values)}")

    new_inf = cf_sim.results["new_infections"].values
    new_diag = cf_sim.results["new_diagnoses"].values
    ascertainment = new_diag.sum() / max(1, new_inf.sum()) * 100
    print(f"  Ascertainment:    {ascertainment:.1f}%")

    # Diagnoses averted by interventions
    data_cum_diag = data_full["cum_diagnoses"].values[-1] if "cum_diagnoses" in data_full.columns else float("nan")
    model_cum_diag = cf_sim.results["cum_diagnoses"][-1]
    print(f"  Data cum. diag:   {data_cum_diag:.0f}")
    if not np.isnan(data_cum_diag):
        averted = model_cum_diag - data_cum_diag
        pct = averted / max(1, model_cum_diag) * 100
        print(f"  Est. diagnoses averted by interventions: {averted:.0f} ({pct:.1f}%)")

    # Layer transmission share
    infection_log = getattr(getattr(cf_sim, "people", None), "infection_log", [])
    if infection_log:
        layer_counts = {}
        for entry in infection_log:
            layer = entry.get("layer")
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
        if layer_counts:
            total = sum(layer_counts.values())
            print(f"\nLayer transmission shares ({total} total events):")
            layer_names = {"d": "Dormitory", "clu": "Class-UG", "clg": "Class-Grad",
                           "of": "Lab/Office", "ta": "Staff", "cm": "Common"}
            for layer in sorted(layer_counts.keys()):
                count = layer_counts[layer]
                print(f"  {layer_names.get(layer, layer)}: {count} ({count / total * 100:.1f}%)")

    # ---- Save results ----
    best_path = outdir / "best_pars.json"
    best_path.write_text(json.dumps(best_pars, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "default_pars": default_pars,
        "best_pars": best_pars,
        "mismatch_before": float(mismatch_before),
        "mismatch_after": float(mismatch_after_calib),
        "improvement_pct": float(improvement),
        "counterfactual_cum_diagnoses": float(model_cum_diag),
        "observed_cum_diagnoses": float(data_cum_diag),
        "estimated_diagnoses_averted": float(model_cum_diag - data_cum_diag) if not np.isnan(data_cum_diag) else None,
        "ascertainment_pct": float(ascertainment),
    }
    summary_path = outdir / "calibration_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSaved to {outdir}")

    if not args.no_plots:
        print("\nGenerating plots...")
        make_plots(sim_before, sim_after, cf_sim, calib_result, outdir)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

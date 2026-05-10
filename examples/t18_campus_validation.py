"""
Thesis: Campus model validation against University of Notre Dame Fall 2020 outbreak.

This script calibrates the campus model to the Notre Dame outbreak data and
generates all figures and metrics needed for the thesis validation section.

Output:
    examples/figures/campus_validation/
        validation_report.md          - Complete thesis section text
        fig_calibration_fit.png       - Before/after calibration fit
        fig_counterfactual.png        - Counterfactual projection
        fig_layer_transmission.png    - Transmission by contact layer
        fig_parameter_evolution.png   - Parameter convergence during calibration
        fig_doubling_time.png         - Doubling time estimation
        calibration_results.json      - All numerical results
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
import pandas as pd
import pylab as pl

HERE = Path(__file__).resolve().parent
DATA_EARLY = HERE.parent / "data" / "notre_dame_2020_early.csv"
DATA_FULL = HERE.parent / "data" / "notre_dame_2020_campus.csv"
OUTDIR = HERE / "figures" / "campus_validation"

# ============================================================
# Configuration
# ============================================================
N_TRIALS = 80
POP_SIZE = 12_000
R_EFF_TARGET = (1.5, 3.5)
R_EFF_PENALTY_WEIGHT = 500.0

pl.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "legend.fontsize": 9,
    "figure.dpi": 150,
})


def build_beta_layer(calib_pars):
    cl = float(calib_pars["beta_layer_cl"])
    return {
        "d": float(calib_pars["beta_layer_d"]),
        "clu": cl, "clg": cl,
        "of": cl * 0.8, "ta": cl * 1.2,
        "cm": float(calib_pars["beta_layer_cm"]),
    }


def make_sim(datafile, calib_pars, n_days=16):
    pars = dict(
        pop_type="campus", pop_size=POP_SIZE, pop_infected=30,
        n_days=n_days, start_day="2020-08-03",
        beta=float(calib_pars["beta"]),
        beta_layer=build_beta_layer(calib_pars),
        rescale=False, verbose=0,
    )
    interventions = [
        cv.test_num(daily_tests="data", symp_test=80, quar_test=30, sensitivity=0.95),
    ]
    return cv.Sim(pars=pars, datafile=str(datafile), interventions=interventions, label="sim")


def mismatch_with_data(sim):
    weights = {"cum_diagnoses": 5.0, "new_diagnoses": 3.0}
    total = 0.0
    data = sim.data
    sim_dates = list(sim.results["date"])
    for key, weight in weights.items():
        sim_vals = getattr(sim.results[key], "values", None)
        if sim_vals is None or key not in data.columns:
            continue
        sim_matched, data_matched = [], []
        for date_val, data_val in data[key].items():
            if date_val in sim_dates:
                sim_matched.append(sim_vals[sim_dates.index(date_val)])
                data_matched.append(data_val)
        if sim_matched:
            total += weight * np.mean((np.array(sim_matched) - np.array(data_matched)) ** 2)
    return float(total)


def compute_r_eff(sim):
    r = sim.results["r_eff"].values
    valid = r[np.isfinite(r) & (r > 0)]
    return float(valid[3:10].mean()) if len(valid) >= 10 else float("nan")


def compute_doubling_time(sim):
    cum = sim.results["cum_infections"].values
    for start, end in [(3, 8), (4, 10), (5, 12)]:
        if cum[end] > cum[start] * 1.5:
            growth_rate = np.log(cum[end] / cum[start]) / (end - start)
            if growth_rate > 0:
                return float(np.log(2) / growth_rate)
    return float("nan")


def count_layer_transmissions(sim):
    log = getattr(getattr(sim, "people", None), "infection_log", [])
    counts = {}
    for entry in log:
        layer = entry.get("layer", "other")
        counts[layer] = counts.get(layer, 0) + 1
    return counts


SENSITIVITY_VARIANTS = {
    "baseline":      {"label": "Baseline",           "perturb": {}},
    "beta_low":      {"label": "beta -20%",          "perturb": {"beta": 0.80}},
    "beta_high":     {"label": "beta +20%",          "perturb": {"beta": 1.20}},
    "dorm_low":      {"label": "beta_d -20%",        "perturb": {"beta_layer_d": 0.80}},
    "dorm_high":     {"label": "beta_d +20%",        "perturb": {"beta_layer_d": 1.20}},
    "class_low":     {"label": "beta_cl -20%",       "perturb": {"beta_layer_cl": 0.80}},
    "class_high":    {"label": "beta_cl +20%",        "perturb": {"beta_layer_cl": 1.20}},
    "common_low":    {"label": "beta_cm -20%",       "perturb": {"beta_layer_cm": 0.80}},
    "common_high":   {"label": "beta_cm +20%",        "perturb": {"beta_layer_cm": 1.20}},
}
SENSITIVITY_SEEDS = 20
SENSITIVITY_NDAYS = 16

LAYER_GROUP_LABELS = {
    "d": "Dormitory", "clu": "Classroom UG", "clg": "Classroom Grad",
    "of": "Lab/Office", "ta": "Staff", "cm": "Common Spaces",
}


def perturb_pars(best_pars: dict, perturb: dict) -> dict:
    result = dict(best_pars)
    for key, scale in perturb.items():
        result[key] = float(best_pars[key]) * scale
    return result


def make_sensitivity_sim(calib_pars: dict, seed: int):
    pars = dict(
        pop_type="campus", pop_size=POP_SIZE, pop_infected=30,
        n_days=SENSITIVITY_NDAYS, start_day="2020-08-03",
        beta=float(calib_pars["beta"]),
        beta_layer=build_beta_layer(calib_pars),
        rescale=False, verbose=0, rand_seed=int(seed),
    )
    return cv.Sim(pars=pars, label=f"seed{seed}")


def compute_early_r_eff(sim):
    r = sim.results["r_eff"].values
    valid = r[np.isfinite(r) & (r > 0)]
    return float(valid[3:10].mean()) if len(valid) >= 10 else float("nan")


def compute_layer_shares(sim):
    counts = count_layer_transmissions(sim)
    total = float(sum(v for k, v in counts.items() if k != "seed_infection"))
    if total == 0:
        return {}
    groups = {
        "dorm": ("d",),
        "classroom": ("clu", "clg"),
        "office": ("of", "ta"),
        "common": ("cm",),
    }
    shares = {}
    for gname, layers in groups.items():
        gtotal = sum(counts.get(layer, 0) for layer in layers)
        shares[gname] = float(gtotal / total * 100)
    return shares


def run_sensitivity(best_pars: dict, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"\n{'='*60}")
    print("SENSITIVITY ANALYSIS: Transmission Dynamics Robustness")
    print(f"{'='*60}")
    print(f"Variants: {len(SENSITIVITY_VARIANTS)}  |  Seeds per variant: {SENSITIVITY_SEEDS}")
    print(f"Total runs: {len(SENSITIVITY_VARIANTS) * SENSITIVITY_SEEDS}")

    for variant_name, variant in SENSITIVITY_VARIANTS.items():
        label = variant["label"]
        cp = perturb_pars(best_pars, variant["perturb"])
        for seed in range(1, SENSITIVITY_SEEDS + 1):
            sim = make_sensitivity_sim(cp, seed)
            sim.run()
            row = {
                "variant": variant_name,
                "label": label,
                "seed": seed,
                "doubling_time": compute_doubling_time(sim),
                "early_r_eff": compute_early_r_eff(sim),
                "cum_infections_day16": float(sim.results["cum_infections"][-1]),
                "peak_new_infections": float(sim.results["new_infections"].values.max()),
            }
            shares = compute_layer_shares(sim)
            for k, v in shares.items():
                row[f"share_{k}"] = v
            rows.append(row)
        mean_dt = np.mean([r["doubling_time"] for r in rows[-SENSITIVITY_SEEDS:]])
        print(f"  {label:20s}  doubling_time = {mean_dt:.2f} days")

    df = pd.DataFrame(rows)
    df.to_csv(outdir / "sensitivity_run_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"\n  [OK] sensitivity_run_metrics.csv ({len(df)} rows)")

    # Aggregate
    metric_cols = [c for c in df.columns if c not in ("variant", "label", "seed")]
    agg = df.groupby(["variant", "label"], sort=False).agg(
        **{f"{col}_mean": (col, "mean") for col in metric_cols},
        **{f"{col}_std": (col, "std") for col in metric_cols},
    ).reset_index()
    agg.to_csv(outdir / "sensitivity_summary.csv", index=False, encoding="utf-8-sig")
    print(f"  [OK] sensitivity_summary.csv")

    # Tornado: doubling time
    baseline_dt = agg[agg["variant"] == "baseline"]["doubling_time_mean"].values[0]
    tornado_data = []
    for param_key, low_key, high_key in [
        ("beta", "beta_low", "beta_high"),
        ("beta_layer_d", "dorm_low", "dorm_high"),
        ("beta_layer_cl", "class_low", "class_high"),
        ("beta_layer_cm", "common_low", "common_high"),
    ]:
        low_val = agg[agg["variant"] == low_key]["doubling_time_mean"].values[0]
        high_val = agg[agg["variant"] == high_key]["doubling_time_mean"].values[0]
        tornado_data.append((param_key, low_val, high_val))

    fig, axes = pl.subplots(1, 2, figsize=(13, 5.5))

    ax = axes[0]
    param_labels = [d[0] for d in tornado_data]
    y_pos = range(len(param_labels))
    for i, (param, low, high) in enumerate(tornado_data):
        # Low value (parameter -20%)
        low_left = min(low, baseline_dt)
        ax.barh(i, abs(low - baseline_dt), left=low_left, height=0.5,
                color="#4393c3", alpha=0.85, label="-20%" if i == 0 else "")
        # High value (parameter +20%)
        high_left = min(high, baseline_dt)
        ax.barh(i, abs(high - baseline_dt), left=high_left, height=0.5,
                color="#d6604d", alpha=0.85, label="+20%" if i == 0 else "")
        ax.plot([low, high], [i, i], "k-", lw=1.5)
        ax.plot(baseline_dt, i, "ko", markersize=8)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(param_labels, fontsize=10)
    ax.axvline(x=baseline_dt, color="gray", ls="--", alpha=0.5, lw=1.5)
    ax.set_xlabel("Doubling time (days)")
    ax.set_title(f"(a) Doubling Time (baseline = {baseline_dt:.1f} days)")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=0.3)

    ax = axes[1]
    baseline_r = agg[agg["variant"] == "baseline"]["early_r_eff_mean"].values[0]
    tornado_r = []
    for param_key, low_key, high_key in [
        ("beta", "beta_low", "beta_high"),
        ("beta_layer_d", "dorm_low", "dorm_high"),
        ("beta_layer_cl", "class_low", "class_high"),
        ("beta_layer_cm", "common_low", "common_high"),
    ]:
        low_val = agg[agg["variant"] == low_key]["early_r_eff_mean"].values[0]
        high_val = agg[agg["variant"] == high_key]["early_r_eff_mean"].values[0]
        tornado_r.append((param_key, low_val, high_val))
    for i, (param, low, high) in enumerate(tornado_r):
        # Low value (parameter -20%)
        low_left = min(low, baseline_r)
        ax.barh(i, abs(low - baseline_r), left=low_left, height=0.5,
                color="#4393c3", alpha=0.85, label="-20%" if i == 0 else "")
        # High value (parameter +20%)
        high_left = min(high, baseline_r)
        ax.barh(i, abs(high - baseline_r), left=high_left, height=0.5,
                color="#d6604d", alpha=0.85, label="+20%" if i == 0 else "")
        ax.plot([low, high], [i, i], "k-", lw=1.5)
        ax.plot(baseline_r, i, "ko", markersize=8)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(param_labels, fontsize=10)
    ax.axvline(x=baseline_r, color="gray", ls="--", alpha=0.5, lw=1.5)
    ax.set_xlabel("Early R_eff (day 3-10)")
    ax.set_title(f"(b) Early R_eff (baseline = {baseline_r:.2f})")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=0.3)

    fig.suptitle("Figure X-S1: Parameter Sensitivity — Tornado Plots (±20% perturbation, 20 seeds)",
                 fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(outdir / "fig_sensitivity_tornado.png", dpi=250, bbox_inches="tight")
    pl.close(fig)
    print(f"  [OK] fig_sensitivity_tornado.png")

    # Layer share stability plot
    share_cols = [c for c in metric_cols if c.startswith("share_")]
    if share_cols:
        fig, ax = pl.subplots(figsize=(10, 5))
        x = np.arange(len(SENSITIVITY_VARIANTS))
        group_labels_short = {"dorm": "Dormitory", "classroom": "Classroom", "office": "Office/Lab", "common": "Common"}
        colors = ["#d73027", "#fc8d59", "#91bfdb", "#4575b4"]
        bottom = np.zeros(len(SENSITIVITY_VARIANTS))
        for idx, (col, gname) in enumerate(zip(
            ["share_dorm", "share_classroom", "share_office", "share_common"],
            ["dorm", "classroom", "office", "common"],
        )):
            vals = [agg[agg["variant"] == v][f"{col}_mean"].values[0] for v in SENSITIVITY_VARIANTS]
            ax.bar(x, vals, bottom=bottom, color=colors[idx], alpha=0.85, label=group_labels_short[gname], edgecolor="white", lw=0.5)
            bottom += np.array(vals)
        ax.set_xticks(x)
        ax.set_xticklabels([v["label"] for v in SENSITIVITY_VARIANTS.values()], rotation=30, ha="right", fontsize=9)
        ax.set_ylabel("Transmission share (%)")
        ax.set_title("Layer Transmission Share Stability Under Parameter Perturbation", fontsize=13)
        ax.legend(frameon=False, fontsize=9, loc="upper right")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / "fig_sensitivity_layers.png", dpi=250, bbox_inches="tight")
        pl.close(fig)
        print(f"  [OK] fig_sensitivity_layers.png")

    return df, agg
def run_calibration():
    import optuna

    default_pars = {"beta": 0.016, "beta_layer_d": 2.0, "beta_layer_cl": 1.0, "beta_layer_cm": 0.35}

    def objective(trial):
        cp = {
            "beta": trial.suggest_float("beta", 0.005, 0.04),
            "beta_layer_d": trial.suggest_float("beta_layer_d", 1.0, 4.0),
            "beta_layer_cl": trial.suggest_float("beta_layer_cl", 0.3, 1.5),
            "beta_layer_cm": trial.suggest_float("beta_layer_cm", 0.1, 0.5),
        }
        try:
            sim = make_sim(DATA_EARLY, cp)
            sim.run()
            mismatch = mismatch_with_data(sim)
            r_eff = compute_r_eff(sim)
            if np.isfinite(r_eff):
                if r_eff < R_EFF_TARGET[0]:
                    penalty = R_EFF_PENALTY_WEIGHT * (R_EFF_TARGET[0] - r_eff) ** 2
                elif r_eff > R_EFF_TARGET[1]:
                    penalty = R_EFF_PENALTY_WEIGHT * (r_eff - R_EFF_TARGET[1]) ** 2
                else:
                    penalty = 0.0
                return mismatch + penalty
            return float("inf")
        except Exception:
            return float("inf")

    study = optuna.create_study(
        study_name="campus_validation",
        storage="sqlite:///:memory:",
        direction="minimize",
    )
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=True)

    best_pars = study.best_params
    return default_pars, best_pars, study


# ============================================================
# Step 2: Generate all figures
# ============================================================
def generate_figures(default_pars, best_pars, study):
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # Run sims (n_days=15: Aug 3 + 15 = Aug 18, matches calibration data)
    sim_default = make_sim(DATA_EARLY, default_pars, n_days=15)
    sim_default.run()
    sim_best = make_sim(DATA_EARLY, best_pars, n_days=15)
    sim_best.run()
    sim_counterfactual = make_sim(DATA_FULL, best_pars, n_days=44)
    sim_counterfactual.run()

    mismatch_before = mismatch_with_data(sim_default)
    mismatch_after = mismatch_with_data(sim_best)
    r_eff_default = compute_r_eff(sim_default)
    r_eff_best = compute_r_eff(sim_best)
    dt_best = compute_doubling_time(sim_best)

    data_early = sim_default.data
    data_full = sim_counterfactual.data

    # ---- Figure 1: Calibration fit ----
    fig, axes = pl.subplots(1, 2, figsize=(14, 5.5))
    ax = axes[0]
    ax.plot(sim_default.results["date"], sim_default.results["cum_diagnoses"].values,
            label="Default parameters", color="#d6604d", lw=2.2)
    ax.plot(sim_best.results["date"], sim_best.results["cum_diagnoses"].values,
            label="Calibrated parameters", color="#1b9e77", lw=2.5)
    ax.scatter(data_early.index, data_early["cum_diagnoses"].values,
               label="Notre Dame (observed)", color="black", s=30, zorder=5, alpha=0.85)
    ax.set_title("(a) Cumulative Diagnoses Fit")
    ax.set_xlabel("Date"); ax.set_ylabel("Cumulative diagnoses")
    ax.legend(frameon=False); ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    ax = axes[1]
    ax.plot(sim_default.results["date"], sim_default.results["new_diagnoses"].values,
            label="Default parameters", color="#d6604d", lw=2.2)
    ax.plot(sim_best.results["date"], sim_best.results["new_diagnoses"].values,
            label="Calibrated parameters", color="#1b9e77", lw=2.5)
    ax.scatter(data_early.index, data_early["new_diagnoses"].values,
               label="Notre Dame (observed)", color="black", s=30, zorder=5, alpha=0.85)
    ax.set_title("(b) Daily New Diagnoses Fit")
    ax.set_xlabel("Date"); ax.set_ylabel("New diagnoses per day")
    ax.legend(frameon=False); ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    fig.suptitle("Figure X-1: Campus Model Calibration to Notre Dame Early Outbreak (Aug 3-18, 2020)",
                 fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTDIR / "fig_calibration_fit.png", dpi=250, bbox_inches="tight")
    pl.close(fig)
    print("  [OK] fig_calibration_fit.png")

    # ---- Figure 2: Counterfactual projection ----
    fig, axes = pl.subplots(1, 2, figsize=(14, 5.5))

    ax = axes[0]
    model_cum = sim_counterfactual.results["cum_diagnoses"].values
    data_cum = data_full["cum_diagnoses"].values
    n = min(len(model_cum), len(data_cum))
    ax.plot(sim_counterfactual.results["date"], model_cum,
            label="Model projection (baseline measures only)", color="#d6604d", lw=2.5)
    ax.scatter(data_full.index, data_cum, label="Notre Dame (observed)",
               color="black", s=20, zorder=5, alpha=0.8)
    ax.fill_between(sim_counterfactual.results["date"][:n], model_cum[:n], data_cum[:n],
                    alpha=0.25, color="#1b9e77",
                    label="Cases averted by escalation (Aug 18)")
    ax.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5)
    ax.set_title("(a) Cumulative Diagnoses")
    ax.set_xlabel("Date"); ax.set_ylabel("Cumulative diagnoses")
    ax.legend(frameon=False, loc="upper left"); ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    ax = axes[1]
    model_new = sim_counterfactual.results["new_diagnoses"].values
    data_new = data_full["new_diagnoses"].values
    ax.plot(sim_counterfactual.results["date"], model_new,
            label="Model projection (baseline measures only)", color="#d6604d", lw=2.2)
    ax.scatter(data_full.index, data_new, label="Notre Dame (observed)",
               color="black", s=20, zorder=5, alpha=0.8)
    ax.axvline(x=data_early.index[-1], color="gray", ls="--", alpha=0.5)
    ax.set_title("(b) Daily New Diagnoses")
    ax.set_xlabel("Date"); ax.set_ylabel("New diagnoses per day")
    ax.legend(frameon=False); ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    fig.suptitle("Figure X-2: Counterfactual Analysis — Estimated Impact of Intervention Escalation",
                 fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTDIR / "fig_counterfactual.png", dpi=250, bbox_inches="tight")
    pl.close(fig)
    print("  [OK] fig_counterfactual.png")

    # ---- Figure 3: Layer transmission ----
    layer_counts = count_layer_transmissions(sim_counterfactual)
    layer_names = {"d": "Dormitory", "clu": "Classroom UG", "clg": "Classroom Grad",
                   "of": "Lab/Office", "ta": "Staff", "cm": "Common Spaces"}
    if layer_counts:
        total = sum(v for k, v in layer_counts.items() if k != "seed_infection")
        fig, ax = pl.subplots(figsize=(9, 5.5))
        ordered = sorted(
            [(k, v) for k, v in layer_counts.items() if k != "seed_infection"],
            key=lambda x: x[1], reverse=True,
        )
        labels = [layer_names.get(k, k) for k, _ in ordered]
        counts = [v for _, v in ordered]
        colors = ["#d73027", "#fc8d59", "#a6d96a", "#91bfdb", "#fee090", "#4575b4"]
        bars = ax.bar(labels, [c / total * 100 for c in counts], color=colors[:len(ordered)],
                      edgecolor="white", linewidth=0.8)
        ax.set_title("Transmission Share by Contact Layer (Calibrated Model)", fontsize=13)
        ax.set_ylabel("Share of total transmissions (%)")
        for bar, c in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8,
                    f"{c / total * 100:.1f}%\n({c})", ha="center", fontsize=8.5)
        ax.set_ylim(0, max(c / total * 100 for c in counts) * 1.2)
        ax.grid(axis="y", alpha=0.3)
        fig.suptitle("Figure X-3: Transmission Contribution by Contact Layer",
                     fontsize=14, y=1.02)
        fig.tight_layout()
        fig.savefig(OUTDIR / "fig_layer_transmission.png", dpi=250, bbox_inches="tight")
        pl.close(fig)
        print("  [OK] fig_layer_transmission.png")

    # ---- Figure 4: R_eff and Doubling Time ----
    fig, axes = pl.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    r = sim_best.results["r_eff"].values
    valid_r = r[np.isfinite(r) & (r > 0)]
    days = np.arange(len(valid_r))
    ax.plot(days, valid_r, color="#1b9e77", lw=2.2, marker="o", markersize=5, label="R_eff (calibrated)")
    ax.axhline(y=3.5, color="#d6604d", ls="--", alpha=0.6, label="Upper bound (3.5)")
    ax.axhline(y=1.5, color="#4393c3", ls="--", alpha=0.6, label="Lower bound (1.5)")
    ax.fill_between(days, 1.5, 3.5, alpha=0.08, color="green")
    ax.set_title(f"(a) Effective Reproduction Number (early R_eff = {float(valid_r[3:10].mean()):.2f})")
    ax.set_xlabel("Simulation day"); ax.set_ylabel("R_eff")
    ax.legend(frameon=False, fontsize=8); ax.grid(alpha=0.3)

    ax = axes[1]
    cum = sim_best.results["cum_infections"].values
    ax.plot(cum, color="#1b9e77", lw=2.2, label="Cumulative infections")
    fit_mask = (cum >= 20) & (cum <= 1500)
    if fit_mask.sum() >= 3:
        x_fit = np.arange(len(cum))[fit_mask]
        y_fit = np.log(cum[fit_mask])
        slope, intercept = np.polyfit(x_fit, y_fit, 1)
        y_pred = np.exp(intercept + slope * x_fit)
        ax.scatter(x_fit, cum[fit_mask], color="#d6604d", s=30, zorder=5, label="Exponential fit region")
        ax.plot(x_fit, y_pred, color="#d6604d", ls="--", lw=2, label=f"Fit: doubling = {np.log(2)/slope:.1f} days")
    ax.set_title("(b) Early Growth and Doubling Time Estimation")
    ax.set_xlabel("Simulation day"); ax.set_ylabel("Cumulative infections")
    ax.legend(frameon=False); ax.grid(alpha=0.3)

    fig.suptitle("Figure X-4: Epidemic Dynamics Validation", fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTDIR / "fig_doubling_time.png", dpi=250, bbox_inches="tight")
    pl.close(fig)
    print("  [OK] fig_doubling_time.png")

    # ---- Figure 5: Parameter convergence ----
    if study and len(study.trials) > 0:
        fig, axes = pl.subplots(2, 2, figsize=(12, 8))
        param_names = ["beta", "beta_layer_d", "beta_layer_cl", "beta_layer_cm"]
        param_labels = ["beta (transmission rate)", "beta_layer_d (dormitory)",
                        "beta_layer_cl (classroom)", "beta_layer_cm (common spaces)"]
        for ax, pname, plabel in zip(axes.flat, param_names, param_labels):
            values = [t.params[pname] for t in study.trials if t.value is not None]
            best_vals = [min(values[:i+1], key=lambda v: abs(v - study.best_params[pname]))
                         if i < len(values) else study.best_params[pname] for i in range(len(values))]
            ax.plot(values, alpha=0.35, color="#999999", lw=0.8, label="Trial value")
            ax.plot(best_vals, color="#1b9e77", lw=2.2, label="Running best")
            ax.axhline(y=study.best_params[pname], color="#d6604d", ls=":", lw=1.5, label=f"Final = {study.best_params[pname]:.3f}")
            ax.set_title(plabel)
            ax.set_xlabel("Trial"); ax.legend(frameon=False, fontsize=7.5)
            ax.grid(alpha=0.3)
        fig.suptitle("Figure X-5: Parameter Convergence During Calibration", fontsize=14, y=1.02)
        fig.tight_layout()
        fig.savefig(OUTDIR / "fig_parameter_evolution.png", dpi=250, bbox_inches="tight")
        pl.close(fig)
        print("  [OK] fig_parameter_evolution.png")

    return {
        "default_pars": default_pars,
        "best_pars": best_pars,
        "mismatch_before": float(mismatch_before),
        "mismatch_after": float(mismatch_after),
        "improvement_pct": float((mismatch_before - mismatch_after) / mismatch_before * 100),
        "r_eff_default": float(r_eff_default),
        "r_eff_best": float(r_eff_best),
        "doubling_time_days": float(dt_best) if np.isfinite(dt_best) else None,
        "counterfactual_cum_diagnoses": float(sim_counterfactual.results["cum_diagnoses"][-1]),
        "observed_cum_diagnoses": float(data_full["cum_diagnoses"].values[-1]),
        "counterfactual_cum_infections": float(sim_counterfactual.results["cum_infections"][-1]),
        "peak_new_diagnoses_model": float(sim_counterfactual.results["new_diagnoses"].values.max()),
        "peak_new_diagnoses_data": float(data_full["new_diagnoses"].values.max()),
        "ascertainment_pct": float(
            sim_counterfactual.results["new_diagnoses"].values.sum()
            / max(1, sim_counterfactual.results["new_infections"].values.sum()) * 100
        ),
        "layer_transmission": {
            layer_names.get(k, k): int(v) for k, v in layer_counts.items()
        } if layer_counts else {},
        "daily_transmission_potential": sum(
            c * best_pars["beta"] * w for c, w in [
                (5, best_pars["beta_layer_d"]),
                (25, best_pars["beta_layer_cl"]),
                (12, best_pars["beta_layer_cl"]),
                (6, best_pars["beta_layer_cl"] * 0.8),
                (3, best_pars["beta_layer_cl"] * 1.2),
                (12, best_pars["beta_layer_cm"]),
            ]
        ),
    }


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Campus model validation + sensitivity analysis.")
    parser.add_argument("--sensitivity", action="store_true", help="Run sensitivity analysis after calibration.")
    args = parser.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("CAMPUS MODEL VALIDATION — Notre Dame Fall 2020")
    print("=" * 65)
    print(f"Population: {POP_SIZE}  |  Trials: {N_TRIALS}")
    print(f"R_eff target: {R_EFF_TARGET}  |  Penalty weight: {R_EFF_PENALTY_WEIGHT}")
    print(f"Output: {OUTDIR}")
    print()

    # Use cached calibration if available
    cache_path = OUTDIR / "calibration_results.json"
    if cache_path.exists():
        print("Loading cached calibration results...")
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        best_pars = cached["best_pars"]
        default_pars = cached["default_pars"]
        study = None
        print(f"  beta = {best_pars['beta']:.4f}")
        print(f"  beta_layer_d = {best_pars['beta_layer_d']:.4f}")
        print(f"  beta_layer_cl = {best_pars['beta_layer_cl']:.4f}")
        print(f"  beta_layer_cm = {best_pars['beta_layer_cm']:.4f}")
    else:
        print("Calibrating...")
        default_pars, best_pars, study = run_calibration()
        print(f"\nBest parameters:")
        for k, v in best_pars.items():
            print(f"  {k}: {v:.4f}")
        print(f"  Best trial value: {study.best_value:.2f}")

    if args.sensitivity:
        run_sensitivity(best_pars, OUTDIR)
        print(f"\nAll sensitivity outputs saved to: {OUTDIR}")
        return 0

    # Generate figures + results
    print("\nGenerating figures...")
    if study is None:
        print("  Skipped (cached calibration, no study object for convergence plot)")
        results = generate_figures(default_pars, best_pars, None)
    else:
        results = generate_figures(default_pars, best_pars, study)

    # Save results
    results_path = OUTDIR / "calibration_results.json"
    results_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n  [OK] calibration_results.json")
    print(f"\nResults summary:")
    print(f"  Mismatch:       {results['mismatch_before']:.1f} -> {results['mismatch_after']:.1f}")
    print(f"                  ({results['improvement_pct']:.1f}% improvement)")
    print(f"  R_eff:          {results['r_eff_default']:.2f} -> {results['r_eff_best']:.2f}")
    print(f"  Doubling time:  {results['doubling_time_days']:.1f} days")
    print(f"  Cum diagnoses:  {results['counterfactual_cum_diagnoses']:.0f} (model) vs {results['observed_cum_diagnoses']:.0f} (observed)")
    print(f"  Cases averted:  {results['counterfactual_cum_diagnoses'] - results['observed_cum_diagnoses']:.0f}")
    print(f"  Ascertainment:  {results['ascertainment_pct']:.1f}%")

    print(f"\nAll outputs saved to: {OUTDIR}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

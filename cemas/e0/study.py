"""Independent UW E0 scan, fit, and simulation-consistency artifacts.

The one-standard-error sets describe a stochastic loss profile. They are not
parameter confidence intervals, and W1 is an in-sample consistency check.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import sys
from time import monotonic
import traceback

import numpy as np

from .simulation import run_e0_world


ARTIFACT_SCHEMA = "cemas-uw-e0-study-v1"
METRICS = ("cumulative", "weekly")
GROUPS = ("students", "employees")
ROOT = Path(__file__).resolve().parents[2]


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _write_json(path, value):
    path.write_text(_json_text(value) + "\n", encoding="utf-8")


def _sha256(value):
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def align_world(world, shift):
    """Delay positive results and their actual test denominators together.

    The initial reporting queue is empty. Delayed results outside W1 remain in
    ``out_of_window`` rather than disappearing from the artifact.
    """
    if isinstance(shift, bool) or not isinstance(shift, int) or shift not in (0, 1, 2):
        raise ValueError("Reporting alignment must be 0, 1, or 2 days")
    days = len(world["dates"])
    if days <= shift:
        raise ValueError("Reporting alignment must be shorter than the window")
    result = {"dates": list(world["dates"]), "alignment": shift, "groups": {}}
    tail_dates = [(date.fromisoformat(world["dates"][-1]) + timedelta(days=i + 1)).isoformat()
                  for i in range(shift)]
    result["out_of_window"] = {"dates": tail_dates, "groups": {}}
    for group in GROUPS:
        result["groups"][group] = {}
        result["out_of_window"]["groups"][group] = {}
        for field in ("positive", "tests"):
            values = list(world["groups"][group][field])
            if len(values) != days:
                raise ValueError(f"{group}.{field} length differs from dates")
            result["groups"][group][field] = ([0] * shift + values)[:days]
            result["out_of_window"]["groups"][group][field] = values[-shift:] if shift else []
    requested = list(world["requested_tests"])
    result["requested_tests"] = ([0] * shift + requested)[:days]
    result["out_of_window"]["requested_tests"] = requested[-shift:] if shift else []
    return result


def calibration_loss(model, observed, metric="cumulative"):
    """Normalized loss for one world, before averaging across worlds.

    The squared residuals are summed before normalization. The weekly metric
    uses complete, non-overlapping seven-day blocks; W1 is 21 days, so every
    alignment contributes exactly three blocks.
    """
    model = np.asarray(model, dtype=float)
    observed = np.asarray(observed, dtype=float)
    if model.ndim != 1 or model.shape != observed.shape or not len(model):
        raise ValueError("Model and observed counts must be matching nonempty daily arrays")
    if not np.isfinite(model).all() or not np.isfinite(observed).all():
        raise ValueError("Loss inputs must be finite")
    denominator = float(observed.sum()) ** 2
    if denominator <= 0:
        raise ValueError("Observed total must be positive for normalized E0 loss")
    if metric == "cumulative":
        residual = np.cumsum(model) - np.cumsum(observed)
    elif metric == "weekly":
        if len(model) % 7:
            raise ValueError("Weekly loss requires complete seven-day blocks")
        residual = model.reshape(-1, 7).sum(axis=1) - observed.reshape(-1, 7).sum(axis=1)
    else:
        raise ValueError(f"Unknown E0 loss metric: {metric}")
    return float(np.sum(residual ** 2) / denominator)


def _total(groups, field):
    return np.asarray(groups["students"][field]) + np.asarray(groups["employees"][field])


def _world_losses(world, observed, alignments):
    losses = []
    for alignment in alignments:
        model = _total(align_world(world, alignment)["groups"], "positive")
        losses.append({"alignment": alignment, **{
            metric: calibration_loss(model, observed, metric) for metric in METRICS}})
    return losses


def summarize_profile(rows):
    """Summarize beta/world-loss rows using the best point's standard error."""
    if not rows:
        raise ValueError("An E0 profile requires at least one beta point")
    points = []
    for row in sorted(rows, key=lambda item: item["beta"]):
        losses = np.asarray(row["world_losses"], dtype=float)
        if losses.ndim != 1 or len(losses) < 2 or not np.isfinite(losses).all():
            raise ValueError("Each profile point requires at least two finite world losses")
        points.append({"beta": float(row["beta"]), "mean_loss": float(losses.mean()),
                       "se_loss": float(losses.std(ddof=1) / np.sqrt(len(losses))),
                       "worlds": len(losses), "world_losses": losses.tolist()})
    best_index = min(range(len(points)), key=lambda i: points[i]["mean_loss"])
    best = points[best_index]
    threshold = best["mean_loss"] + best["se_loss"]
    for point in points:
        point["in_one_se"] = bool(point["mean_loss"] <= threshold)
    one_se = [point["beta"] for point in points if point["in_one_se"]]
    means = np.array([point["mean_loss"] for point in points])
    increasing = len(means) > 1 and bool(np.all(np.diff(means) >= 0))
    decreasing = len(means) > 1 and bool(np.all(np.diff(means) <= 0))
    boundary = best_index in (0, len(points) - 1)
    monotonic = "flat" if increasing and decreasing else (
        "increasing" if increasing else "decreasing" if decreasing else None)
    covers_grid = len(one_se) == len(points)
    touches_boundary = bool(one_se and (min(one_se) <= points[0]["beta"]
                                        or max(one_se) >= points[-1]["beta"]))
    reason = None
    if covers_grid:
        reason = "one_se_set_covers_grid"
    elif boundary:
        reason = "best_point_on_boundary"
    elif monotonic is not None:
        reason = f"monotonic_{monotonic}"
    return {"points": points, "best_beta": best["beta"], "best_loss": best["mean_loss"],
            "best_se": best["se_loss"], "one_se_threshold": threshold,
            "one_se_betas": one_se, "one_se_range": [min(one_se), max(one_se)],
            "one_se_rule": "best_point_mean_plus_one_standard_error",
            "one_se_interpretation": "descriptive_stochastic_loss_set_not_parameter_confidence_interval",
            "one_se_touches_boundary": touches_boundary,
            "boundary_best": boundary, "monotonic": monotonic, "covers_grid": covers_grid,
            "identifiable": reason is None, "non_identifiable_reason": reason,
            "boundary_direction": ("lower" if best_index == 0 else "upper") if boundary else None}


def refinement_grid(coarse_betas, profiles, factor=4):
    """Union the one-SE ranges plus one coarse neighbor on either side."""
    coarse = np.asarray(coarse_betas, dtype=float)
    if isinstance(factor, bool) or not isinstance(factor, int) or factor < 1:
        raise ValueError("refinement_factor must be a positive integer")
    if len(coarse) < 2 or not np.all(np.diff(coarse) > 0):
        raise ValueError("Coarse beta grid must be increasing with at least two points")
    if not np.allclose(np.diff(coarse), coarse[1] - coarse[0]):
        raise ValueError("Coarse beta grid must be uniform")
    indices = set()
    for profile in profiles:
        candidates = profile["one_se_betas"]
        low = max(0, int(np.argmin(abs(coarse - min(candidates)))) - 1)
        high = min(len(coarse) - 1, int(np.argmin(abs(coarse - max(candidates)))) + 1)
        indices.update(range(low * factor, high * factor + 1))
    step = (coarse[1] - coarse[0]) / factor
    return [round(float(coarse[0] + index * step), 12) for index in sorted(indices)]


def _profiles(records, alignments):
    result = []
    for alignment in alignments:
        for metric in METRICS:
            rows = {}
            for record in records:
                loss = next(item[metric] for item in record["losses"]
                            if item["alignment"] == alignment)
                rows.setdefault(record["beta"], []).append(loss)
            result.append({"alignment": alignment, "metric": metric,
                           **summarize_profile([{"beta": beta, "world_losses": values}
                                                for beta, values in rows.items()])})
    return result


def _world_job(config, data, beta, seed, case):
    return run_e0_world(config, data, beta, seed,
                        initial_infections=case["initial_infections"], symp_test=case["symp_test"])


def _run_stage(config, data, case, stage, betas, seeds, workers, stream, executor=None):
    """Flush every completed world before computing any aggregate artifacts."""
    if not betas or not seeds:
        raise ValueError("E0 stages require at least one beta point and one world")
    records = []
    observed = _total(data["groups"], "positive")
    last_progress = monotonic()

    def save(world):
        nonlocal last_progress
        record = {"case": case["name"], "stage": stage, "beta": world["beta"],
                  "seed": world["seed"], "world": world,
                  "losses": _world_losses(world, observed, config["alignments"])}
        stream.write(_json_text(record) + "\n")
        stream.flush()
        records.append(record)
        if monotonic() - last_progress >= 30:
            print(f"E0 {case['name']} {stage}: {len(records)}/{len(betas) * len(seeds)} worlds", flush=True)
            last_progress = monotonic()

    print(f"E0 {case['name']} {stage}: {len(betas)} beta points x {len(seeds)} worlds", flush=True)
    if workers == 1:
        for beta in betas:
            for seed in seeds:
                save(_world_job(config, data, beta, seed, case))
    else:
        futures = [executor.submit(_world_job, config, data, beta, seed, case)
                   for beta in betas for seed in seeds]
        first_failure = None
        for future in as_completed(futures):
            if future.cancelled():
                continue
            try:
                save(future.result())
            except Exception as exc:
                if first_failure is None:
                    first_failure = exc
                    for pending in futures:
                        pending.cancel()
        if first_failure is not None:
            raise first_failure
    records.sort(key=lambda item: (item["beta"], item["seed"]))
    print(f"E0 {case['name']} {stage}: completed {len(records)} worlds", flush=True)
    return records


def _quantiles(values):
    values = np.asarray(values, dtype=float)
    result = {}
    for probability, label in ((0.05, "q05"), (0.5, "q50"), (0.95, "q95")):
        # Avoid all-NaN warnings for 0-test dates and undefined engine R_eff.
        result[label] = [float(np.quantile(column[np.isfinite(column)], probability))
                         if np.isfinite(column).any() else None for column in values.T]
    return result


def _band_metrics(curve, observed):
    low = np.array([np.nan if value is None else value for value in curve["q05"]])
    high = np.array([np.nan if value is None else value for value in curve["q95"]])
    observed = np.asarray(observed, dtype=float)
    valid = np.isfinite(low) & np.isfinite(high) & np.isfinite(observed)
    return {"coverage": float(np.mean((low[valid] <= observed[valid]) & (observed[valid] <= high[valid])))
            if valid.any() else None,
            "mean_width": float(np.mean(high[valid] - low[valid])) if valid.any() else None,
            "evaluated_days_or_weeks": int(valid.sum())}


def _weekly_blocks(values):
    values = np.asarray(values, dtype=float)
    if values.shape[-1] % 7:
        raise ValueError("Weekly summaries require complete seven-day blocks")
    return values.reshape(*values.shape[:-1], -1, 7).sum(axis=-1)


def _observation_summary(data):
    groups = {group: {key: list(values) for key, values in data["groups"][group].items()}
              for group in GROUPS}
    groups["total"] = {field: _total(groups, field).tolist() for field in ("positive", "tests")}
    for values in groups.values():
        values["cumulative_positive"] = np.cumsum(values["positive"]).tolist()
        values["positivity"] = [positive / tests if tests else None
                                for positive, tests in zip(values["positive"], values["tests"])]
    return groups


def _evaluation(records, profile, coarse_profile, data):
    worlds = [record["world"] for record in records if record["beta"] == profile["best_beta"]]
    if not worlds:
        raise ValueError("No evaluation worlds were recorded for the selected beta")
    aligned = [align_world(world, profile["alignment"]) for world in worlds]
    observed = _observation_summary(data)
    total_actual = np.array([_total(world["groups"], "tests").sum() for world in aligned])
    target_total = sum(observed["total"]["tests"])
    groups = {}
    for group in (*GROUPS, "total"):
        positives = np.array([_total(world["groups"], "positive") if group == "total"
                              else world["groups"][group]["positive"] for world in aligned], dtype=float)
        tests = np.array([_total(world["groups"], "tests") if group == "total"
                         else world["groups"][group]["tests"] for world in aligned], dtype=float)
        rates = np.divide(positives, tests, out=np.full_like(positives, np.nan), where=tests > 0)
        cumulative = positives.cumsum(axis=1)
        weekly = _weekly_blocks(positives)
        curves = {"positive_daily": _quantiles(positives), "positive_cumulative": _quantiles(cumulative),
                  "tests_daily": _quantiles(tests), "positivity_daily": _quantiles(rates),
                  "positive_weekly": _quantiles(weekly)}
        obs_daily = np.asarray(observed[group]["positive"], dtype=float)
        obs_weekly = _weekly_blocks(obs_daily)
        share = np.divide(tests.sum(axis=1), total_actual, out=np.full(len(worlds), np.nan),
                          where=total_actual > 0)
        groups[group] = {**curves,
            "daily_residual": (np.asarray(curves["positive_daily"]["q50"]) - obs_daily).tolist(),
            "weekly_residual": (np.asarray(curves["positive_weekly"]["q50"]) - obs_weekly).tolist(),
            "metrics": {"daily": _band_metrics(curves["positive_daily"], obs_daily),
                        "cumulative": _band_metrics(curves["positive_cumulative"], obs_daily.cumsum()),
                        "weekly": _band_metrics(curves["positive_weekly"], obs_weekly)},
            "allocation": {"requested_total": sum(aligned[0]["requested_tests"]),
                           "actual_total": _quantiles(tests.sum(axis=1)[:, None]),
                           "actual_test_share": _quantiles(share[:, None]),
                           "target_test_share": sum(observed[group]["tests"]) / target_total}}
    tail = {"dates": aligned[0]["out_of_window"]["dates"], "groups": {}}
    for group in GROUPS:
        tail["groups"][group] = {field: _quantiles([world["out_of_window"]["groups"][group][field]
                                                     for world in aligned])
                                  for field in ("positive", "tests")}
    tail["requested_tests"] = aligned[0]["out_of_window"]["requested_tests"]
    losses = [next(item[profile["metric"]] for item in record["losses"]
                   if item["alignment"] == profile["alignment"])
              for record in records if record["beta"] == profile["best_beta"]]
    median = groups["total"]["positive_daily"]["q50"]
    peak = int(np.argmax(median))
    identifiable = profile["identifiable"] and coarse_profile["identifiable"]
    comparison_models = [_total(world["groups"], "positive")[7:] for world in aligned]
    comparison_observed = np.asarray(observed["total"]["positive"])[7:]
    comparison = {
        "comparison_dates": data["dates"][7:],
        "interpretation": "W1_internal_comparison_beta_fitted_on_all_21_days_not_holdout_validation",
        "comparison_daily_mse": float(np.mean([np.mean((model - comparison_observed) ** 2)
                                               for model in comparison_models])),
        "comparison_cumulative_mse": float(np.mean([np.mean(np.cumsum(model - comparison_observed) ** 2)
                                                    for model in comparison_models])),
        "comparison_normalized_cumulative_loss": float(np.mean([
            calibration_loss(model, comparison_observed) for model in comparison_models])),
        "comparison_normalized_weekly_loss": float(np.mean([
            calibration_loss(model, comparison_observed, "weekly") for model in comparison_models]))}
    return {"alignment": profile["alignment"], "selection_metric": profile["metric"],
            "beta": profile["best_beta"], "worlds": len(worlds), "fit_identifiable": identifiable,
            "fit_non_identifiable_reason": profile.get("non_identifiable_reason")
            or coarse_profile.get("non_identifiable_reason"),
            "evaluation_loss": {"mean": float(np.mean(losses)),
                                "se": float(np.std(losses, ddof=1) / np.sqrt(len(losses)))},
            "groups": groups, "out_of_window": tail, "baseline_comparison": comparison,
            "r_eff": _quantiles([[np.nan if value is None else value for value in world["r_eff"]]
                                  for world in worlds]),
            "requested_tests_daily": aligned[0]["requested_tests"],
            "diagnostics": {"median_curve_peak_date": data["dates"][peak],
                            "median_curve_peak_count": median[peak],
                            "best_beta_above_004": profile["best_beta"] > 0.04,
                            "high_beta_requires_review": profile["best_beta"] > 0.04,
                            "r_eff_interpretation": "engine_effective_reproduction_number_not_implicit_R0",
                            "implicit_R0_review": "not_estimated; high beta is not automatically accepted",
                            "evidence_level": "W1_in_sample_parameter_anchor_and_consistency_check"}}


def _baselines(data):
    """Fit both descriptive baselines on the first week; compare the remaining days."""
    positive = _total(data["groups"], "positive").astype(float)
    tests = _total(data["groups"], "tests").astype(float)
    fit_days = int(data.get("baseline_days", 7))
    if fit_days < 4 or fit_days >= len(positive) - 1:
        raise ValueError("baseline_days must leave comparison days")
    if tests[:fit_days].sum() <= 0:
        raise ValueError("Baseline initialization requires tests in the first week")
    persistence = float(positive[:fit_days].sum() / tests[:fit_days].sum())
    valid = tests[:fit_days] > 0
    if valid.sum() < 2:
        raise ValueError("Growth baseline requires two tested days in the first week")
    x = np.arange(fit_days)[valid]
    y = np.log((positive[:fit_days][valid] + 0.5) / (tests[:fit_days][valid] + 1))
    slope, intercept = np.polyfit(x, y, 1)
    growth_rates = np.exp(np.clip(intercept + slope * np.arange(len(tests)), -700, 0))
    predicted = {"persistence": persistence * tests, "fixed_growth": growth_rates * tests}
    result = {"fit_dates": data["dates"][:fit_days], "comparison_dates": data["dates"][fit_days:],
              "interpretation": "W1_internal_descriptive_comparison_not_predictive_validation",
              "testing_input": "observed daily tests, shared by both baselines",
              "growth_definition": "OLS log((positive+0.5)/(tests+1)) on tested days in the first week; rate clamped to [0,1]"}
    for name, values in predicted.items():
        residual = values[fit_days:] - positive[fit_days:]
        result[name] = {"positive_daily": values.tolist(), "positive_cumulative": values.cumsum().tolist(),
                        "comparison_daily_mse": float(np.mean(residual ** 2)),
                        "comparison_cumulative_mse": float(np.mean(np.cumsum(residual) ** 2)),
                        "comparison_normalized_cumulative_loss": calibration_loss(values[fit_days:], positive[fit_days:]),
                        "comparison_normalized_weekly_loss": calibration_loss(values[fit_days:], positive[fit_days:], "weekly")}
    result["persistence"]["constant_positivity"] = persistence
    result["fixed_growth"].update({"log_rate_intercept": float(intercept), "daily_log_rate_slope": float(slope)})
    return result


def _source_manifest():
    files = [Path(__file__), ROOT / "cemas" / "e0" / "simulation.py",
             ROOT / "cemas" / "e0" / "data.py",
             ROOT / "cemas" / "historical_data.py"]
    files.extend((ROOT / "covasim").glob("*.py"))
    hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(set(files)) if path.is_file()}
    packages = {}
    for name in ("numpy", "scipy", "pandas", "numba", "sciris"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    environment = {"python": sys.version, "platform": platform.platform(), "packages": packages}
    return {"source_sha256": hashes, "source_bundle_sha256": _sha256(hashes),
            "environment": environment, "environment_sha256": _sha256(environment)}


def _report(summary):
    lines = ["# UW E0 simulation calibration", "",
             f"Window: {summary['window']['start']} to {summary['window']['end']} "
             f"({len(summary['dates'])} days).",
             f"Display default: alignment {summary['primary']['alignment']}, "
             f"{summary['primary']['metric']} loss; it is not a validated reporting clock.",
             "Each output-date offset is fitted independently; no offset is declared the true clock.",
             "W1 is an in-sample parameter anchor and consistency check.",
             "Simulation bands are 5/50/95 percentiles across independent evaluation worlds.",
             "The one-SE beta set is a best-point descriptive set and is not a parameter confidence interval.",
             "The weekly loss uses three complete seven-day blocks from the W1 start.", "",
             "| Case | Align | Loss | Display | Beta | Identifiable | Evaluation loss | Daily coverage | Mean daily width |",
             "|---|---:|---|---|---|---:|---:|---:|---:|"]
    for case in summary["cases"]:
        for evaluation in case["evaluations"]:
            metrics = evaluation["groups"]["total"]["metrics"]["daily"]
            coverage = "null" if metrics["coverage"] is None else f"{metrics['coverage']:.3f}"
            width = "null" if metrics["mean_width"] is None else f"{metrics['mean_width']:.3f}"
            lines.append(f"| {case['name']} | {evaluation['alignment']} | {evaluation['selection_metric']} | "
                         f"{'default' if evaluation.get('is_primary') else ''} | {evaluation['beta']:.6g} | "
                         f"{evaluation['fit_identifiable']} | {evaluation['evaluation_loss']['mean']:.6g} | "
                         f"{coverage} | {width} |")
    lines.extend(["", "Days after the first week are an internal descriptive comparison "
                      "(both baselines initialized on the first week):", "",
                  "| Method | Daily MSE | Normalized cumulative loss | Normalized weekly loss |",
                  "|---|---:|---:|---:|"])
    for name in ("persistence", "fixed_growth"):
        baseline = summary["baselines"][name]
        lines.append(f"| {name} | {baseline['comparison_daily_mse']:.6g} | "
                     f"{baseline['comparison_normalized_cumulative_loss']:.6g} | "
                     f"{baseline['comparison_normalized_weekly_loss']:.6g} |")
    for case in summary["cases"]:
        if case["name"] == "main":
            for evaluation in case["evaluations"]:
                if evaluation.get("is_primary"):
                    comparison = evaluation["baseline_comparison"]
                    lines.append(f"| main {evaluation['selection_metric']} | "
                                 f"{comparison['comparison_daily_mse']:.6g} | "
                                 f"{comparison['comparison_normalized_cumulative_loss']:.6g} | "
                                 f"{comparison['comparison_normalized_weekly_loss']:.6g} |")
    lines.extend(["", "Sensitivity cases independently reselect beta; they are not merely another score at the main optimum.",
                  "Boundary, monotonic, or full-grid one-SE profiles remain flagged as unidentifiable; the beta domain is never expanded.",
                  "The empty initial reporting queue is an assumption. Shifted results beyond W1 are retained in out_of_window.",
                  "Positive fractions with zero actual tests are undefined (JSON null), not zero.",
                  "Employee curves have limited information and are descriptive. Test weights do not guarantee exact group allocation.",
                  "The simulation detects infectious individuals; pre-infectious PCR detection is not represented.",
                  "No out-of-sample, external, predictive, or causal validation is claimed.", ""])
    return "\n".join(lines)


def run_e0_study(config, data, output_dir, *, workers=1, scenarios=None):
    """Run the frozen E0 procedure into a new, exclusively created directory."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if len(data["dates"]) != config["window_days"]:
        raise ValueError("E0 data length does not match config.window")
    for key in ("alignments", "primary_alignment", "primary_metric", "coarse_points",
                "refinement_factor", "beta_range", "scan_seeds", "fit_seeds", "evaluation_seeds"):
        if key not in config:
            raise ValueError(f"config.{key} is required")
    data = dict(data)
    data.setdefault("baseline_days", config.get("baseline_days", 7))

    cases = [{"name": "main", "initial_infections": config["initial_infections"],
              "symp_test": config["testing"]["symp_test"]}]
    cases.extend({"name": sensitivity["name"],
                  "initial_infections": sensitivity.get("initial_infections", config["initial_infections"]),
                  "symp_test": sensitivity.get("symp_test", config["testing"]["symp_test"])}
                 for sensitivity in config.get("sensitivities", []))
    if scenarios is not None:
        selected = set(scenarios)
        unknown = selected - {case["name"] for case in cases}
        if unknown or not selected:
            raise ValueError(f"Unknown or empty E0 scenario selection: {sorted(unknown)}")
        cases = [case for case in cases if case["name"] in selected]

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    primary = {"alignment": config["primary_alignment"], "metric": config["primary_metric"]}
    manifest = {"schema_version": ARTIFACT_SCHEMA, "method_version": config["method_version"],
                "status": "running", "started_at": _utc_now(), "config": config,
                "config_sha256": config.get("config_sha256", _sha256(config)),
                "data_provenance": data["provenance"], "data_sha256": data.get("sha256"),
                "window": config["window"], "primary": primary,
                "selected_cases": [case["name"] for case in cases],
                "workers": workers, **_source_manifest()}
    summary = {"schema_version": ARTIFACT_SCHEMA, "method_version": config["method_version"],
               "status": "running", "window": config["window"], "dates": list(data["dates"]),
               "primary": primary, "observed": _observation_summary(data), "cases": []}
    active_case = active_stage = None
    try:
        _write_json(output / "config.json", config)
        _write_json(output / "manifest.json", manifest)
        summary["baselines"] = _baselines(data)
        coarse = [round(float(beta), 12)
                  for beta in np.linspace(*config["beta_range"], config["coarse_points"])]
        with ExitStack() as resources:
            executor = resources.enter_context(ProcessPoolExecutor(max_workers=workers)) if workers > 1 else None
            scan_stream = resources.enter_context((output / "worlds_scan.jsonl").open("x", encoding="utf-8"))
            fit_stream = resources.enter_context((output / "worlds_fit.jsonl").open("x", encoding="utf-8"))
            evaluation_stream = resources.enter_context((output / "worlds_evaluation.jsonl").open("x", encoding="utf-8"))
            for case in cases:
                active_case = case["name"]
                active_stage = "scan"
                scan = _run_stage(config, data, case, "scan", coarse, config["scan_seeds"], workers, scan_stream, executor)
                scan_profiles = _profiles(scan, config["alignments"])
                fine = refinement_grid(coarse, scan_profiles, config["refinement_factor"])
                active_stage = "fit"
                fit = _run_stage(config, data, case, "fit", fine, config["fit_seeds"], workers, fit_stream, executor)
                fit_profiles = _profiles(fit, config["alignments"])
                # Keep the coarse domain diagnosis even when an interior fine point wins.
                for profile, coarse_profile in zip(fit_profiles, scan_profiles):
                    profile["coarse_identifiable"] = coarse_profile["identifiable"]
                selected_betas = sorted({profile["best_beta"] for profile in fit_profiles})
                active_stage = "evaluation"
                evaluation = _run_stage(config, data, case, "evaluation", selected_betas,
                                        config["evaluation_seeds"], workers, evaluation_stream, executor)
                evaluations = [_evaluation(evaluation, profile, coarse_profile, data)
                               for profile, coarse_profile in zip(fit_profiles, scan_profiles)]
                for item in evaluations:
                    item["is_primary"] = (item["alignment"] == primary["alignment"]
                                          and item["selection_metric"] == primary["metric"])
                result = {**case, "fine_betas": fine, "profiles": {"scan": scan_profiles, "fit": fit_profiles},
                          "evaluations": evaluations}
                summary["cases"].append(result)
                summary["status"] = "running"
                _write_json(output / "summary.json", summary)
                _write_json(output / "profiles.json", [{"name": item["name"], **item["profiles"]}
                                                      for item in summary["cases"]])
        summary["status"] = "complete"
        summary["finished_at"] = _utc_now()
        manifest.update({"status": "complete", "finished_at": _utc_now()})
        manifest["artifacts"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in output.glob("worlds_*.jsonl")}
        _write_json(output / "summary.json", summary)
        (output / "report.md").write_text(_report(summary), encoding="utf-8")
        _write_json(output / "manifest.json", manifest)
        return summary
    except BaseException as exc:
        manifest.update({"status": "failed", "finished_at": _utc_now()})
        failure = {"case": active_case, "stage": active_stage, "exception": type(exc).__name__,
                   "message": str(exc), "traceback": traceback.format_exc(), "failed_at": _utc_now()}
        _write_json(output / "failure.json", failure)
        _write_json(output / "manifest.json", manifest)
        raise

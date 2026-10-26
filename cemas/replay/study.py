"""Execute the frozen UW historical replay experiment independently of control."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import monotonic
import traceback

import numpy as np

from ..control.protocol import load_protocol
from ..e0.artifacts import load_calibration_artifact
from ..e0.data import ROOT, load_e0_config, load_e0_data
from ..e0.study import align_world, calibration_loss
from .simulation import run_replay_world, schedule_multipliers


WINDOWS = {"W1": (0, 21), "W2": (21, 40), "W3": (40, 75)}


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    indent=2) + "\n", encoding="utf-8")


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def slice_data(data, end):
    return {**data, "dates": list(data["dates"][:end]), "groups": {
        group: {field: list(values[:end]) for field, values in fields.items()}
        for group, fields in data["groups"].items()}}


def load_replay_data(config):
    """Reuse the E0 table reader with the independently archived 75-day table."""
    data = load_e0_data(dict(config, window={"start": "2020-08-17", "end": "2020-10-30"},
                            data_path=str(ROOT / "data/uw_madison_2020_replay.csv"),
                            provenance_path=str(ROOT / "data/uw_madison_2020_replay.provenance.json")))
    if len(data["dates"]) != 75:
        raise ValueError("Historical replay requires exactly 75 observed days")
    return data


def w2_loss(world, data):
    """Align the whole series once, then restart cumulative residuals on 9/7."""
    aligned = align_world(world, 1)
    model = np.asarray(aligned["groups"]["students"]["positive"])[21:40] + np.asarray(
        aligned["groups"]["employees"]["positive"])[21:40]
    observed = np.asarray(data["groups"]["students"]["positive"])[21:40] + np.asarray(
        data["groups"]["employees"]["positive"])[21:40]
    return calibration_loss(model, observed, "cumulative")


def select_c(records, h):
    """Use fit-world W2 losses only; exact ties favor the larger retained share."""
    points = []
    cs = sorted({r["c"] for r in records if r["h"] == h})
    for c in cs:
        values = [r["loss"] for r in sorted(records, key=lambda r: r["seed"])
                  if r["h"] == h and r["c"] == c]
        loss = np.asarray(values, dtype=float)
        if len(loss) < 2 or not np.isfinite(loss).all():
            raise ValueError("Every community candidate requires at least two finite fit losses")
        points.append({"c": c, "mean_loss": float(loss.mean()),
                       "se_loss": float(loss.std(ddof=1) / np.sqrt(len(loss))),
                       "world_losses": values, "worlds": len(values)})
    if not points:
        raise ValueError("No fit candidates for this fixed dormitory assumption")
    best = min(points, key=lambda row: (row["mean_loss"], -row["c"]))
    threshold = best["mean_loss"] + best["se_loss"]
    one_se = [p["c"] for p in points if p["mean_loss"] <= threshold]
    boundary = best["c"] in (0, 1)
    ambiguous = len(one_se) > 1
    return {"h": h, "best_c": best["c"], "best_loss": best["mean_loss"],
            "best_se": best["se_loss"], "rows": points, "one_se_cs": one_se,
            "one_se_threshold": threshold, "boundary_best": boundary,
            "identifiable": not (boundary or ambiguous),
            "identifiability_note": ("boundary_best" if boundary else
                                     "multiple_candidates_within_best_standard_error" if ambiguous else None),
            "recovery_order_inconsistent": best["c"] > .5,
            "interpretation": "effective_parameter_conditional_on_fixed_dormitory_assumption",
            "one_se_interpretation": "stochastic_loss_diagnostic_not_parameter_confidence_interval"}


def _w1_signature(world):
    return {"dates": world["dates"][:21], "groups": {
        group: {field: values[:21] for field, values in fields.items()}
        for group, fields in world["groups"].items()},
        "roles": world["roles"], "requested_tests": world["requested_tests"][:21],
        "group_test_weights": world["group_test_weights"]}


def _references(anchor_path, beta):
    references = {}
    for stage in ("fit", "evaluation"):
        with (anchor_path.parent / f"worlds_{stage}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if record["case"] == "main" and record["beta"] == beta:
                    references[record["seed"]] = _w1_signature(record["world"])
    return references


def _job(config, data, beta, spec):
    return run_replay_world(config, data, beta, spec["seed"],
                            c=spec["c"], h=spec["h"], recovery=spec["recovery"])


def _run_stage(pool, config, data, beta, specs, output, stage, references):
    """Persist every completed or failed world without replacing failed seeds."""
    results, failures = [], []
    started = monotonic()
    futures = {pool.submit(_job, config, data, beta, spec): spec for spec in specs}
    with (output / f"worlds_{stage}.jsonl").open("x", encoding="utf-8") as stream, (
            output / f"failures_{stage}.jsonl").open("x", encoding="utf-8") as failed:
        for future in as_completed(futures):
            spec = futures[future]
            try:
                world = future.result()
                if _w1_signature(world) != references[spec["seed"]]:
                    raise RuntimeError("First 21 days differ from the original selected E0 world")
                record = {**spec, "world": world, "w1_exact_match": True}
                if stage == "fit":
                    record["loss"] = w2_loss(world, data)
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                results.append(record)
            except Exception as exc:
                record = {**spec, "error": str(exc), "traceback": traceback.format_exc()}
                failed.write(json.dumps(record, ensure_ascii=False) + "\n")
                failed.flush()
                failures.append(record)
            completed = len(results) + len(failures)
            if completed % 20 == 0 or completed == len(specs):
                print(f"{stage}: {completed}/{len(specs)} worlds; failures={len(failures)}; "
                      f"elapsed={monotonic() - started:.1f}s", flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} failed {stage} worlds; see failures_{stage}.jsonl")
    return sorted(results, key=lambda row: (row["h"], row["c"], row["recovery"], row["seed"]))


def run_replay_study(anchor_path, output, *, workers=4, experiment_path=None):
    """Run all prespecified worlds; the anchor and existing E0 evidence are read-only."""
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    experiment_path = Path(experiment_path or ROOT / "docs/uw2020_replay_config_v2.json").resolve()
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    anchor_path, output = Path(anchor_path).resolve(), Path(output).resolve()
    config = load_e0_config(ROOT / "docs/e0_protocol_v2.json")
    protocol = load_protocol(config["base_protocol_path"])
    anchor = load_calibration_artifact(anchor_path, protocol)
    w1, data = load_e0_data(config), load_replay_data(config)
    if slice_data(data, 21)["groups"] != {g: {f: list(v) for f, v in fs.items()}
                                          for g, fs in w1["groups"].items()}:
        raise ValueError("Continuous observations differ from the frozen E0 W1 table")
    fit_seeds, evaluation_seeds = experiment["fit_seeds"], experiment["evaluation_seeds"]
    if (fit_seeds != list(range(12101, 12121))
            or evaluation_seeds != list(range(12201, 12241))
            or experiment["c_grid"] != [round(i * .05, 2) for i in range(21)]
            or experiment["h_values"] != [1.15, 1.0, 1.25]
            or experiment["recovery_values"] != [.25, .5, .75]
            or experiment["fixed_c"] != .2 or experiment["alignment"] != 1):
        raise ValueError("Experiment configuration differs from the approved v2 design")
    references = _references(anchor_path, anchor.beta)
    if not set(fit_seeds + evaluation_seeds).issubset(references):
        raise ValueError("Original E0 evidence lacks the selected beta/seed reference worlds")
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "config.json", experiment)
    sources = {**dict(anchor.payload["compatibility"]["source_sha256"]), **{
        p.relative_to(ROOT).as_posix(): _file_hash(p)
        for p in [*[p for p in sorted((ROOT / "cemas/replay").glob("*.py"))
                     if p.name != "reporting.py"],
                  ROOT / "examples/control_v1/uw2020_replay.py",
                  ROOT / "tools/build_uw_e0_data.py", ROOT / "tools/verify_uw_replay.py"]}}
    manifest = {"schema_version": "cemas-uw-historical-replay-v2", "status": "running",
                "started_at": _now(), "anchor_path": str(anchor_path),
                "anchor_file_sha256": _file_hash(anchor_path), "anchor_payload_sha256": anchor.sha256,
                "beta": anchor.beta, "e0_config_sha256": config["config_sha256"],
                "data_sha256": data["sha256"], "data_provenance": data["provenance"],
                "experiment_config_sha256": _file_hash(experiment_path),
                "source_sha256": sources,
                "runtime": {"python": anchor.payload["compatibility"]["runtime"]["python"],
                            "packages": dict(anchor.payload["compatibility"]["runtime"]["packages"])},
                "workers": workers, "parameters": config,
                "plan_sha256": _file_hash(ROOT / experiment["plan"]),
                "scope": "historical_environment_replay_without_control_executor",
                "stop_rationale": "Complete rise, restrictions, decline and partial recovery through 10/30; later interventions and Thanksgiving movement excluded"}
    _write_json(output / "manifest.json", manifest)
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            fixed_specs = [{"name": f"h{h:g}_fixed_w2", "kind": "fixed", "h": h,
                            "c": .2, "recovery": .5, "seed": seed}
                           for h in experiment["h_values"] for seed in evaluation_seeds]
            fixed = _run_stage(pool, config, slice_data(data, 40), anchor.beta, fixed_specs,
                               output, "fixed_w2", references)
            fit_specs = [{"name": f"h{h:g}_fit_c{c:g}", "kind": "fit", "h": h,
                          "c": c, "recovery": .5, "seed": seed}
                         for h in experiment["h_values"] for c in experiment["c_grid"]
                         for seed in fit_seeds]
            fit = _run_stage(pool, config, slice_data(data, 40), anchor.beta, fit_specs,
                             output, "fit", references)
            profiles = [select_c(fit, h) for h in experiment["h_values"]]
            _write_json(output / "profiles.json", profiles)
            evaluation_specs = []
            for profile in profiles:
                h, c = profile["h"], profile["best_c"]
                for kind, chosen_c, recovery in [("fixed", .2, .5),
                                                 ("calibrated", c, .5),
                                                 ("sensitivity", c, .25),
                                                 ("sensitivity", c, .75)]:
                    name = f"h{h:g}_{kind}_r{recovery:g}"
                    evaluation_specs.extend({"name": name, "kind": kind, "h": h,
                                             "c": chosen_c, "recovery": recovery, "seed": seed}
                                            for seed in evaluation_seeds)
            evaluation = _run_stage(pool, config, data, anchor.beta, evaluation_specs,
                                    output, "evaluation", references)
        from .reporting import summarize_worlds, write_report

        reporting_path = ROOT / "cemas/replay/reporting.py"
        manifest["reporting_source_sha256"] = _file_hash(reporting_path)
        scenarios = []
        for name in dict.fromkeys(spec["name"] for spec in evaluation_specs):
            records = [r for r in evaluation if r["name"] == name]
            spec = {k: records[0][k] for k in ("name", "kind", "h", "c", "recovery")}
            scenarios.append({**spec, "worlds": len(records),
                              "metrics": summarize_worlds([r["world"] for r in records], data)})
        fixed_summaries = []
        for h in experiment["h_values"]:
            records = [r for r in fixed if r["h"] == h]
            fixed_summaries.append({"name": f"h{h:g}_fixed_w2", "kind": "fixed", "h": h,
                                    "c": .2, "recovery": .5, "worlds": len(records),
                                    "metrics": summarize_worlds([r["world"] for r in records],
                                                                slice_data(data, 40))})
        all_records = fixed + fit + evaluation
        # Prefixes must also match across short/full runs for the same evaluation world.
        for short in fixed:
            long = next(r for r in evaluation if r["kind"] == "fixed"
                        and r["h"] == short["h"] and r["seed"] == short["seed"])
            if any(short["world"]["groups"][g][f] != long["world"]["groups"][g][f][:40]
                   for g in ("students", "employees") for f in ("positive", "tests")):
                raise RuntimeError("Short/full fixed replay prefixes differ")
        compatibility = {"anchor_file_sha256": manifest["anchor_file_sha256"],
                         "bound_sources_unchanged": True,
                         "original_source_sha256": dict(anchor.payload["compatibility"]["source_sha256"]),
                         "w1_reference_files": {f"worlds_{stage}.jsonl": _file_hash(
                             anchor_path.parent / f"worlds_{stage}.jsonl") for stage in ("fit", "evaluation")},
                         "w1_worlds_checked": len(all_records), "w1_exact_matches": len(all_records),
                         "w1_fields": ["daily_group_positive", "daily_group_actual_tests", "roles",
                                       "requested_tests", "group_test_weights"],
                         "short_full_40day_prefixes_checked": len(fixed),
                         "schedule_boundaries": {str(h): {day: schedule_multipliers(day, .2, h, .5)
                             for day in ("2020-09-06", "2020-09-07", "2020-09-09", "2020-09-10",
                                         "2020-09-25", "2020-09-26")}
                             for h in experiment["h_values"]}}
        # Detect source edits or evidence changes during the experiment.
        for name, digest in sources.items():
            if _file_hash(ROOT / name) != digest:
                raise RuntimeError(f"Source changed during replay: {name}")
        if _file_hash(anchor_path) != manifest["anchor_file_sha256"]:
            raise RuntimeError("E0 anchor changed during replay")
        load_calibration_artifact(anchor_path, protocol)
        _write_json(output / "compatibility.json", compatibility)
        summary = {"status": "complete", "beta": anchor.beta, "anchor_path": str(anchor_path),
                   "anchor_sha256": anchor.sha256, "profiles": profiles,
                   "scenarios": scenarios, "fixed_w2": fixed_summaries,
                   "worlds_completed": len(all_records), "failed_worlds": 0,
                   "compatibility": compatibility, "finished_at": _now()}
        _write_json(output / "summary.json", summary)
        write_report(output, summary, profiles, data)
        if _file_hash(reporting_path) != manifest["reporting_source_sha256"]:
            raise RuntimeError("Reporting source changed while generating metrics")
        manifest.update(status="complete", finished_at=_now(), worlds_completed=len(all_records),
                        artifacts={p.relative_to(output).as_posix(): _file_hash(p)
                                   for p in sorted(output.rglob("*")) if p.is_file()
                                   and p.name != "manifest.json"})
        _write_json(output / "manifest.json", manifest)
        return summary
    except BaseException as exc:
        manifest.update(status="failed", finished_at=_now(), error=str(exc))
        _write_json(output / "manifest.json", manifest)
        raise

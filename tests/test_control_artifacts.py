"""Artifact identities and release rejection gates; no scientific data is produced."""
from copy import deepcopy
from dataclasses import replace
import csv
import json
from pathlib import Path

import pytest

from cemas.control.artifacts import (BASELINE_SCHEMA, RELEASE_SCHEMA, _horizon_evidence,
    _read_reference, _source_evaluation, _source_trajectories, _training_report,
    file_sha256, get_baseline_artifact, save_baseline_artifact, validate_phase6_release)
from cemas.control.logging import resolved_snapshot
from cemas.control.protocol import load_protocol, source_grid
from cemas.control.rewards import V1RewardCalculator
from cemas.control.training import horizon_report


@pytest.fixture
def protocol():
    return load_protocol(Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resolved_snapshot(value)), encoding="utf-8")


def threshold_parameters(protocol):
    return {"thresholds": protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"],
            "hysteresis": .75}


def test_baseline_roundtrip_binds_code_and_e0_file_separately(tmp_path, protocol):
    # A synthetic envelope tests identity plumbing; it cannot pass E0/release validation.
    calibration = tmp_path / "synthetic_e0.json"
    write_json(calibration, {"sha256": "a" * 64, "payload": {"synthetic_unit_test": True}})
    artifact = save_baseline_artifact(tmp_path / "threshold", protocol, "threshold",
        parameters=threshold_parameters(protocol), calibration_artifact=calibration)
    metadata = get_baseline_artifact(artifact, protocol)
    assert metadata["schema_version"] == BASELINE_SCHEMA
    assert metadata["calibration_artifact_sha256"] == "a" * 64
    assert metadata["calibration_artifact_file"]["sha256"] == file_sha256(calibration)
    assert metadata["artifact_sha256"] == file_sha256(artifact)
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["source_code_sha256"] = "b" * 64
    write_json(artifact, document)
    with pytest.raises(ValueError, match="source code"):
        get_baseline_artifact(artifact, protocol)


def test_baseline_checks_actual_weight_file_without_importing_a_trainer(tmp_path, protocol):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"synthetic unit-test weights")
    artifact = save_baseline_artifact(tmp_path / "model", protocol, "ddqn", weights_path=weights,
        training={"train_seed": 11, "steps": 2048})
    assert get_baseline_artifact(artifact, protocol)["weights_path"] == str(weights)
    weights.write_bytes(b"changed")
    with pytest.raises(ValueError, match="weights hash"):
        get_baseline_artifact(artifact, protocol)


def test_objective_registration_status_does_not_change_baseline_task(tmp_path, protocol):
    artifact = save_baseline_artifact(tmp_path / "threshold", protocol, "threshold", parameters=threshold_parameters(protocol))
    document = json.loads(protocol.source_path.read_text(encoding="utf-8"))
    document["objective"]["status"] = "frozen"
    frozen = tmp_path / "frozen_protocol.json"
    write_json(frozen, document)
    assert get_baseline_artifact(artifact, load_protocol(frozen))["method"] == "threshold"


def test_reference_hash_requires_the_actual_file(tmp_path):
    report = tmp_path / "report.json"
    write_json(report, {"status": "completed"})
    reference = {"path": report.name, "sha256": file_sha256(report)}
    assert _read_reference(reference, tmp_path)[1]["status"] == "completed"
    write_json(report, {"status": "fixture"})
    with pytest.raises(ValueError, match="hash mismatch"):
        _read_reference(reference, tmp_path)


def synthetic_evaluation(tmp_path, protocol):
    """Isolated runner-sidecar fixtures; never passed to a full release."""
    records = []
    bounds = protocol.definition["seeds"]["validation_A"]
    for seed in range(bounds["start_inclusive"], bounds["end_inclusive"] + 1):
        directory = tmp_path / str(seed)
        condition = source_grid(protocol, "validation_A", seed)
        summary = {"status": "completed", "population": protocol.population, "execution_days": protocol.execution_days,
                   "elapsed_days": protocol.execution_days, "daily_weekly_terminal_reconciled": True,
                   "reward_configuration": resolved_snapshot(V1RewardCalculator(protocol, protocol.population, protocol.execution_days).configuration),
                   "positive_cost": 1., "reward_breakdown": {"normalized": [0, 0, 0, 0, .25]},
                   "private_metrics": {"terminal_active_infections": 0}}
        manifest = {"status": "completed", "purpose": "scientific", "run_purpose": "scientific", "mode": "evaluation",
                    "world_seed": seed, "controller_type": "minimum", "calibration_verified": True,
                    "calibration": {"artifact_sha256": "a" * 64, "beta_scale": condition["beta_scale"]}}
        write_json(directory / "manifest.json", manifest)
        write_json(directory / "summary.json", summary)
        with (directory / "private_daily.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("day", "new_infections"))
            writer.writerows((day, 0) for day in range(protocol.execution_days))
        with (directory / "public_daily.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("day", "screening_daily_capacity"))
            writer.writerow((0, int(protocol.population * condition["screening_capacity_ratio"])))
        records.append({"world_seed": seed, "summary": summary, "output_dir": str(directory), "last_window_infections": 0})
    return {"purpose": "source_development", "pool": "validation_A", "records": records,
            "mean_positive_cost": 1., "mean_normalized_activity": .25}


@pytest.mark.parametrize("change", ["fixture", "wrong_pool", "duplicate_world", "summary", "method", "calibration", "daily", "capacity", "mean"])
def test_evaluation_rejects_mixed_or_unbacked_source_scores(tmp_path, protocol, change):
    report = synthetic_evaluation(tmp_path, protocol)
    # Check the sidecar plumbing before independently corrupting one boundary.
    _source_evaluation(report, protocol, "a" * 64, "minimum", pool="validation_A")
    directory = Path(report["records"][0]["output_dir"])
    if change == "fixture":
        report["purpose"] = "fixture"
    elif change == "wrong_pool":
        report["pool"] = "validation_B"
    elif change == "duplicate_world":
        report["records"][-1] = report["records"][0]
    elif change == "summary":
        report["records"][0]["summary"]["positive_cost"] = 9.
    elif change in ("method", "calibration"):
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if change == "method":
            manifest["controller_type"] = "threshold"
        else:
            manifest["calibration"]["artifact_sha256"] = "b" * 64
        write_json(directory / "manifest.json", manifest)
    elif change == "daily":
        report["records"][0]["last_window_infections"] = 999
    elif change == "capacity":
        (directory / "public_daily.csv").write_text("day,screening_daily_capacity\n0,1\n", encoding="utf-8")
    elif change == "mean":
        report["mean_positive_cost"] = 2.
    with pytest.raises(ValueError):
        _source_evaluation(report, protocol, "a" * 64, "minimum", pool="validation_A")


def selected_b_records(protocol):
    bounds = protocol.definition["seeds"]["validation_B"]
    result = {}
    for method in protocol.definition["controllers"]["methods"]:
        seeds = protocol.definition["source"]["train_seed_values"] if method in ("maskable_ppo", "double_dqn") else (None,)
        result[method] = [{"world_seed": world, "train_seed": seed,
            "summary": {"status": "completed", "execution_days": protocol.execution_days, "population": protocol.population,
                        "private_metrics": {"terminal_active_infections": 0}}, "last_window_infections": 0}
            for seed in seeds for world in range(bounds["start_inclusive"], bounds["end_inclusive"] + 1)]
    return result


def test_horizon_rechecks_final_models_and_allows_explicit_168_limit(protocol):
    protocol = replace(protocol, execution_days=168)
    records = selected_b_records(protocol)
    for row in records["maskable_ppo"][:11]:
        row["last_window_infections"] = .003 * protocol.population
    report = horizon_report(protocol, records)
    assert report["finite_horizon_limitation"] is True
    assert report["methods"]["maskable_ppo"]["episodes"] == 54
    _horizon_evidence(report, records, protocol)
    hidden = deepcopy(report)
    hidden["finite_horizon_limitation"] = False
    with pytest.raises(ValueError, match="finite-horizon"):
        _horizon_evidence(hidden, records, protocol)
    hidden = deepcopy(report)
    hidden["selected_records"]["maskable_ppo"][0]["world_seed"] = 50001
    with pytest.raises(ValueError, match="final selected"):
        _horizon_evidence(hidden, records, protocol)


def test_horizon_112_cannot_be_frozen_when_four_of_eighteen_are_affected(protocol):
    records = selected_b_records(protocol)
    for row in records["minimum"][:4]:
        row["summary"]["private_metrics"]["terminal_active_infections"] = .006 * protocol.population
    report = horizon_report(protocol, records)
    assert report["requires_extension"] is True
    with pytest.raises(ValueError, match="needs redevelopment"):
        _horizon_evidence(report, records, protocol)


def test_status_flags_cannot_publish_engineering_or_fixture_evidence(tmp_path):
    release = tmp_path / "release.json"
    for document in ({"schema_version": RELEASE_SCHEMA, "incomplete": [], "purpose": "fixture", "sensitivity_frozen": True},
                     {"schema_version": RELEASE_SCHEMA, "incomplete": ["source_development"], "purpose": "source_development"}):
        write_json(release, document)
        with pytest.raises(ValueError, match="incomplete, synthetic"):
            validate_phase6_release(release)


@pytest.mark.parametrize("change", [None, "fixture", "seed_loss", "curve", "extension"])
def test_budget_gate_recomputes_three_seed_A_only_extension(protocol, change):
    seeds = protocol.definition["source"]["train_seed_values"]
    rows = {str(seed): [{"step": step, "validation_A": {"mean_positive_cost": 2.}}
                       for step in (2048, 4096, 6144, 8192)] for seed in seeds}
    report = {"status": "completed", "purpose": "source_development", "method": "ppo", "checkpoints": rows,
              "actual_training": {str(seed): {} for seed in seeds},
              "selected_models": [{"train_seed": seed} for seed in seeds], "available_budget_ceiling": 32768,
              "budget_decisions": [{"current_budget": 8192, "next_budget": 8192,
                                    "resource_ceiling": 32768, "relative_improvement": 0.}]}
    if change == "fixture":
        report["purpose"] = "fixture"
    elif change == "seed_loss":
        del report["checkpoints"]["22"]
    elif change == "curve":
        report["checkpoints"]["33"].pop()
    elif change == "extension":
        report["budget_decisions"][0].update(next_budget=16384, relative_improvement=.1)
    if change is None:
        _training_report(report, protocol, "ppo")
    else:
        with pytest.raises(ValueError):
            _training_report(report, protocol, "ppo")


def test_source_registration_requires_actual_hashed_runner_outputs(tmp_path, protocol):
    with pytest.raises(ValueError, match="audited runner"):
        _source_trajectories({"trajectories": [{"seed": 30001, "policy": "minimum"}]}, protocol, "a" * 64)
    directory = tmp_path / "source"
    write_json(directory / "manifest.json", {"status": "completed", "purpose": "smoke"})
    write_json(directory / "summary.json", {"status": "completed"})
    write_json(directory / "public_transitions.json", {"synthetic_fixture": True})
    entry = {"run_dir": str(directory), "seed": 30001, "policy": "minimum", "world": {"beta_scale": .9}}
    for filename, name in (("manifest.json", "run_manifest_sha256"), ("summary.json", "run_summary_sha256"),
                           ("public_transitions.json", "public_transitions_sha256")):
        entry[name] = file_sha256(directory / filename)
    with pytest.raises(ValueError, match="actual completed collection"):
        _source_trajectories({"trajectories": [entry]}, protocol, "a" * 64)

"""Frozen v2 policies can be evaluated under the v3 observation-week handoff."""

import json
from types import SimpleNamespace

import pytest

from cemas.control.artifacts import get_baseline_artifact, save_baseline_artifact
from cemas.control.controllers import load_baseline_controller, ThresholdController
from cemas.control.logging import snapshot_sha256
from cemas.control.runner import run_episode
from test_snapshot_training import protocol, small_world


def legacy_artifact(tmp_path, protocol, method="threshold", calibration=None):
    weights = tmp_path / "archived.pt"
    weights.write_bytes(b"fixture archived weights")
    artifact = save_baseline_artifact(tmp_path / "artifact", protocol, method,
        parameters={"thresholds": protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"]}
                   if method == "threshold" else None,
        weights_path=weights if method != "threshold" else None,
        calibration_artifact=calibration)
    document = json.loads(artifact.read_text(encoding="utf-8"))
    task = document["task"]
    task.update(execution_days=112, initial_baseline_days=0)
    task.pop("scoring_start_day")
    settings = task["snapshot_training"]
    settings.pop("observation_days")
    settings.pop("control_days")
    settings.update(schema_version="uw-snapshot-training-v2", execution_days=112)
    document.update(task_sha256=snapshot_sha256(task), reference_horizon=112,
                    source_code_sha256="b" * 64)
    artifact.write_text(json.dumps(document), encoding="utf-8")
    return artifact, document, weights


@pytest.mark.parametrize("method", ["threshold", "ppo", "ddqn"])
def test_transfer_keeps_training_identity_and_checks_archived_files(protocol, tmp_path, method):
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"sha256": "a" * 64}), encoding="utf-8")
    artifact, original, weights = legacy_artifact(tmp_path, protocol, method, calibration)
    before = artifact.read_bytes()
    metadata = get_baseline_artifact(artifact, protocol)
    assert metadata["task"] == original["task"]
    assert metadata["task_sha256"] == original["task_sha256"]
    assert metadata["source_code_sha256"] == "b" * 64
    assert metadata["reference_horizon"] == 112
    compatibility = metadata["evaluation_compatibility"]
    assert compatibility["mode"] == "frozen_snapshot_policy_transfer"
    assert compatibility["execution_days"] == 119
    assert compatibility["task_sha256"] != original["task_sha256"]
    assert compatibility["source_code_sha256"] != original["source_code_sha256"]
    assert artifact.read_bytes() == before
    if method != "threshold":
        weights.write_bytes(b"changed weights")
        with pytest.raises(ValueError, match="weights hash"):
            get_baseline_artifact(artifact, protocol)
    else:
        calibration.write_text(json.dumps({"sha256": "c" * 64}), encoding="utf-8")
        with pytest.raises(ValueError, match="hash mismatch"):
            get_baseline_artifact(artifact, protocol)


@pytest.mark.parametrize("change", ["objective", "actions", "population", "replay", "encoding", "task_hash"])
def test_transfer_rejects_unrelated_incompatibilities(protocol, tmp_path, change):
    artifact, document, _ = legacy_artifact(tmp_path, protocol)
    if change == "objective":
        document["task"]["objective"]["lambda"] += 1
    elif change == "actions":
        document["task"]["actions"]["T"][0]["level"] = 9
    elif change == "population":
        document["task"]["population"] += 1
    elif change == "replay":
        document["task"]["snapshot_training"]["replay_parameters"]["c"] = .9
    elif change == "encoding":
        document["rl_encoding"] = "old-259-dimensional-encoding"
    if change != "task_hash":
        document["task_sha256"] = snapshot_sha256(document["task"])
    else:
        document["task_sha256"] = "0" * 64
    artifact.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        get_baseline_artifact(artifact, protocol)


def test_same_task_still_requires_matching_source(protocol, tmp_path):
    artifact = save_baseline_artifact(tmp_path / "artifact", protocol, "threshold",
        parameters={"thresholds": protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"]})
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["source_code_sha256"] = "b" * 64
    artifact.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source code"):
        get_baseline_artifact(artifact, protocol)


@pytest.mark.parametrize("calibration_matches", [True, False])
def test_transferred_policy_runs_new_handoff_and_checks_e0(small_world, tmp_path, monkeypatch, calibration_matches):
    from cemas.e0 import artifacts
    protocol, paths = small_world
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"sha256": "a" * 64}), encoding="utf-8")
    artifact, original, _ = legacy_artifact(tmp_path, protocol, calibration=calibration)
    controller, metadata = load_baseline_controller(protocol, artifact)
    monkeypatch.setattr(artifacts, "load_calibration_artifact", lambda *a, **kw:
                        SimpleNamespace(beta=.038583333332, sha256=("a" if calibration_matches else "c") * 64))
    days = []
    decide = ThresholdController.decide

    def record(self, observation):
        days.append(observation.decision_day)
        return decide(self, observation)

    monkeypatch.setattr(ThresholdController, "decide", record)
    options = {"snapshot_path": paths[1], "future_seed": 321, "calibration_artifact": str(calibration)}
    if not calibration_matches:
        with pytest.raises(ValueError, match="E0 identities"):
            run_episode(protocol, controller, tmp_path / "run", 20101,
                        purpose="scientific", scenario_options=options)
        assert days == []
        return
    result = run_episode(protocol, controller, tmp_path / "run", 20101,
                         purpose="scientific", scenario_options=options)
    assert days == list(range(7, 119, 7))
    assert result.summary["execution_days"] == 119
    assert result.summary["decision_count"] == 16
    assert result.summary["control_period"]["execution_days"] == 112
    manifest = json.loads((result.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["baseline"]["task"] == original["task"]
    assert manifest["baseline"]["reference_horizon"] == 112
    assert manifest["baseline"]["evaluation_compatibility"] == metadata["evaluation_compatibility"]

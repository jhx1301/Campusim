"""UW evidence export, rejection boundaries and real control integration."""

import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from cemas.control.protocol import load_protocol
from cemas.e0 import artifacts, study
from cemas.e0.data import ROOT, load_e0_config, load_e0_data


def _world(config, data, beta, seed, **kwargs):
    groups = {group: {"positive": np.rint(np.array(values["positive"]) * beta / .06).astype(int).tolist(),
                       "tests": list(values["tests"])} for group, values in data["groups"].items()}
    return {"beta": beta, "seed": seed, "dates": list(data["dates"]), "groups": groups,
            "requested_tests": (np.array(groups["students"]["tests"]) + groups["employees"]["tests"]).tolist(),
            "r_eff": [2.] * len(data["dates"]), "population": config["population"],
            "roles": {**config["target_roles"], **config["target_groups"]},
            "resolved_parameters": {"pop_infected": config["initial_infections"]}}


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    config = load_e0_config(ROOT / "docs/e0_protocol_v2.json")
    protocol = load_protocol(ROOT / "docs/control_protocol_v1.json")
    output = tmp_path_factory.mktemp("uw_evidence") / "study"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(study, "run_e0_world", _world)
        study.run_e0_study(config, load_e0_data(config), output, scenarios=["main"])
    anchor = artifacts.export_control_anchor(output, protocol)
    return protocol, output, anchor


def test_main_anchor_roundtrip_and_immutable_payload(completed):
    protocol, root, anchor = completed
    artifact = artifacts.load_calibration_artifact(anchor, protocol)
    assert .04 < artifact.beta < .08
    assert artifact.payload["selection"] == {"case": "main", "alignment": 1, "metric": "cumulative"}
    assert artifact.payload["evaluation_worlds"] == 40
    assert artifacts.load_calibration_artifact(root / artifacts.ARTIFACT_FILENAME, protocol).sha256 == artifact.sha256
    with pytest.raises(TypeError):
        artifact.payload["beta"] = .01
    with pytest.raises(FileExistsError):
        artifacts.export_control_anchor(root, protocol)


@pytest.mark.parametrize("name", ["manifest.json", "summary.json", "config.json",
                                 "worlds_scan.jsonl", "worlds_fit.jsonl", "worlds_evaluation.jsonl"])
def test_modified_evidence_is_rejected(completed, tmp_path, name):
    protocol, root, _ = completed
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    with (moved / name).open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="evidence changed"):
        artifacts.load_calibration_artifact(moved / artifacts.ARTIFACT_FILENAME, protocol)


@pytest.mark.parametrize("change", ["schema", "sensitivity", "beta", "beta_in_range", "missing_evidence", "model"])
def test_old_or_incompatible_anchor_is_rejected(completed, tmp_path, change):
    protocol, root, anchor = completed
    moved = tmp_path / "study"
    shutil.copytree(root, moved)
    envelope = json.loads(anchor.read_text(encoding="utf-8"))
    p = envelope["payload"]
    if change == "schema":
        p["schema_version"] = "cemas-e0-artifact-v1"
    elif change == "sensitivity":
        p["selection"]["case"] = "i0_100"
    elif change == "beta":
        p["beta"] = .5
    elif change == "beta_in_range":
        p["beta"] = .041
    elif change == "missing_evidence":
        p["study_sha256"].pop("worlds_evaluation.jsonl")
    else:
        p["compatibility"]["base_model"]["pop_size"] = 12000
    envelope["sha256"] = artifacts._digest(p)
    (moved / artifacts.ARTIFACT_FILENAME).write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible or incomplete"):
        artifacts.load_calibration_artifact(moved / artifacts.ARTIFACT_FILENAME, protocol)


def test_export_rejects_summary_selection_changed_after_run(completed, tmp_path):
    protocol, root, _ = completed
    moved = tmp_path / "study"
    shutil.copytree(root, moved, ignore=shutil.ignore_patterns(artifacts.ARTIFACT_FILENAME))
    summary = json.loads((moved / "summary.json").read_text())
    next(e for e in summary["cases"][0]["evaluations"] if e["is_primary"])["beta"] = .01
    (moved / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="raw main evaluation"):
        artifacts.export_control_anchor(moved, protocol)


def test_anchor_relocation_and_data_override(completed, tmp_path):
    protocol, root, _ = completed
    moved = tmp_path / "study"
    shutil.copytree(root, moved)
    data = tmp_path / "uw.csv"
    shutil.copyfile(ROOT / "data/uw_madison_2020_w1.csv", data)
    assert artifacts.load_calibration_artifact(moved / artifacts.ARTIFACT_FILENAME, protocol, data_path=data).beta > .04
    data.write_text("wrong bytes", encoding="utf-8")
    with pytest.raises(ValueError):
        artifacts.load_calibration_artifact(moved / artifacts.ARTIFACT_FILENAME, protocol, data_path=data)


def test_uw_anchor_runs_real_scientific_control_and_training_plan(completed, tmp_path):
    from cemas.control.controllers import MinimumController
    from cemas.control.runner import run_episode, memory_source_compatibility
    from cemas.control.training import TrainingEpisodePlan

    protocol, _, anchor = completed
    verified = artifacts.load_calibration_artifact(anchor, protocol)
    plan = TrainingEpisodePlan(protocol, 11, anchor)
    episode = plan()
    assert episode["scenario_options"]["calibration_artifact"] == str(anchor)
    source = memory_source_compatibility(protocol, anchor)
    assert source["calibration_artifact_sha256"] == verified.sha256
    result = run_episode(protocol, MinimumController(), tmp_path / "control", 20001,
                         purpose="scientific", scenario_options={"execution_days": 2,
                             "calibration_artifact": anchor, "beta_scale": 1.12})
    assert result.summary["elapsed_days"] == 2
    manifest = json.loads((tmp_path / "control/manifest.json").read_text(encoding="utf-8"))
    assert manifest["resolved_config"]["engine"]["pop_size"] == 69457
    assert manifest["resolved_config"]["engine"]["campus_age_counts"] == [31650, 13890, 23917]
    assert manifest["calibration_verified"] is True
    assert manifest["calibration"]["artifact_sha256"] == verified.sha256
    assert manifest["calibration"]["beta"] == pytest.approx(verified.beta * 1.12)
    assert len(manifest["registration"]["student_indices"]) == 45540
    assert len(manifest["registration"]["teacher_indices"]) == 1150
    assert len(manifest["registration"]["staff_indices"]) == 22767


def test_e0_cli_preserves_stage_failure_and_refuses_existing_output(tmp_path, monkeypatch):
    from examples.control_v1 import e0_study

    def fail(*args, **kwargs):
        raise RuntimeError("world stopped")

    monkeypatch.setattr(study, "run_e0_world", fail)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="world stopped"):
        e0_study.main(["--output", str(output), "--scenarios", "main"])
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "scan" and failure["case"] == "main"
    assert not (output / artifacts.ARTIFACT_FILENAME).exists()
    with pytest.raises(FileExistsError):
        e0_study.main(["--output", str(output)])


def test_sensitivity_only_cli_cannot_promote_its_beta(tmp_path, monkeypatch):
    from examples.control_v1 import e0_study

    def forbidden(*args):
        raise AssertionError("Sensitivity output must not become the control anchor")

    monkeypatch.setattr(study, "run_e0_study", lambda *a, **kw: {
        "status": "complete", "cases": [{"name": "i0_10"}]})
    monkeypatch.setattr(artifacts, "export_control_anchor", forbidden)
    assert e0_study.main(["--output", str(tmp_path / "sensitivity"), "--scenarios", "i0_10"]) == 0

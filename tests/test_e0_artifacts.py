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
    assert .005 < artifact.beta < .16
    assert artifact.payload["selection"] == {"case": "main", "alignment": 1,
                                             "metric": "weekly"}
    assert artifact.payload["evaluation_worlds"] == 40
    assert artifact.payload["compatibility"]["base_model"]["campus_background"] == {
        "employee_cm": .1, "employee_ta": .5}
    assert "cemas/control/background.py" in artifact.payload["compatibility"]["source_sha256"]
    assert artifacts.load_calibration_artifact(root / artifacts.ARTIFACT_FILENAME, protocol).sha256 == artifact.sha256
    with pytest.raises(TypeError):
        artifact.payload["beta"] = .01
    with pytest.raises(FileExistsError):
        artifacts.export_control_anchor(root, protocol)


@pytest.fixture(scope="module")
def legacy_background_anchor(completed, tmp_path_factory):
    """Represent the former control identity while retaining frozen E0 evidence."""
    from cemas.e0.migration import ADDED_SOURCES

    protocol, source, anchor = completed
    root = tmp_path_factory.mktemp("legacy_background") / "study"
    shutil.copytree(source, root)
    envelope = json.loads(anchor.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    base = payload["compatibility"]["base_model"]
    base["beta_layer"]["ta"] /= base.pop("campus_background")["employee_ta"]
    for name in ADDED_SOURCES:
        payload["compatibility"]["source_sha256"].pop(name)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name in ADDED_SOURCES:
        manifest["source_sha256"].pop(name, None)
    # The legacy simulation implementation had a different recorded identity.
    manifest["source_sha256"]["cemas/e0/simulation.py"] = "a" * 64
    payload["compatibility"]["source_sha256"]["cemas/e0/simulation.py"] = "a" * 64
    manifest["source_bundle_sha256"] = study._sha256(manifest["source_sha256"])
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    payload["study_sha256"]["manifest.json"] = artifacts._file_hash(root / "manifest.json")
    envelope["sha256"] = artifacts._digest(payload)
    path = root / artifacts.ARTIFACT_FILENAME
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return protocol, path


def _migration_world(config, data, beta, seed):
    from cemas.control.scenarios import base_model_configuration

    world = _world(config, data, beta, seed)
    base = base_model_configuration(load_protocol(config["base_protocol_path"]))
    world["campus_background"] = base["campus_background"]
    world["resolved_parameters"].update({key: base[key] for key in
                                         ("beta_layer", "iso_factor", "quar_factor")})
    return world


@pytest.fixture(scope="module")
def migrated_background(legacy_background_anchor, tmp_path_factory):
    from cemas.e0 import migration

    protocol, source = legacy_background_anchor
    before = {p.name: p.read_bytes() for p in source.parent.iterdir() if p.is_file()}
    output = tmp_path_factory.mktemp("background_migration") / "result"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(migration, "run_e0_world", _migration_world)
        anchor = migration.migrate_background_anchor(source, output, protocol)
    assert before == {p.name: p.read_bytes() for p in source.parent.iterdir() if p.is_file()}
    return protocol, source, anchor


def test_background_migration_roundtrip_relocation_and_original_rejection(migrated_background, tmp_path):
    from cemas.e0 import migration

    protocol, source, anchor = migrated_background
    with pytest.raises(ValueError, match="incompatible"):
        artifacts.load_calibration_artifact(source, protocol)
    original = json.loads(source.read_text(encoding="utf-8"))["payload"]
    verified = artifacts.load_calibration_artifact(anchor, protocol)
    assert verified.beta == original["beta"]
    assert dict(verified.payload["study_sha256"]) == original["study_sha256"]
    moved = tmp_path / "relocated"
    shutil.copytree(anchor.parent, moved)
    assert artifacts.load_calibration_artifact(moved / anchor.name, protocol).sha256 == verified.sha256
    with pytest.raises(FileExistsError):
        migration.migrate_background_anchor(source, anchor.parent, protocol)


@pytest.mark.parametrize("name", ["source_control_anchor.json", "migration.json", "worlds_migration.jsonl"])
def test_background_migration_changed_evidence_rejected(migrated_background, tmp_path, name):
    protocol, _, anchor = migrated_background
    moved = tmp_path / "changed"
    shutil.copytree(anchor.parent, moved)
    with (moved / name).open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="migration evidence changed"):
        artifacts.load_calibration_artifact(moved / anchor.name, protocol)


def test_background_migration_cannot_be_disguised_as_fresh_export(migrated_background, tmp_path):
    protocol, _, anchor = migrated_background
    moved = tmp_path / "stripped"
    shutil.copytree(anchor.parent, moved)
    envelope = json.loads(anchor.read_text(encoding="utf-8"))
    envelope["payload"].pop("migration")
    envelope["sha256"] = artifacts._digest(envelope["payload"])
    (moved / anchor.name).write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="Study source changed"):
        artifacts.load_calibration_artifact(moved / anchor.name, protocol)


@pytest.mark.parametrize("change", ["duplicate_seed", "trajectory", "report_count"])
def test_background_migration_verifies_content_beyond_hashes(migrated_background, tmp_path, change):
    from cemas.e0 import migration

    protocol, _, anchor = migrated_background
    moved = tmp_path / "changed"
    shutil.copytree(anchor.parent, moved)
    name = migration.REPORT if change == "report_count" else migration.WORLDS
    if change == "report_count":
        report = json.loads((moved / name).read_text(encoding="utf-8"))
        report["matched_worlds"] -= 1
        (moved / name).write_text(json.dumps(report), encoding="utf-8")
    else:
        rows = [json.loads(line) for line in (moved / name).read_text(encoding="utf-8").splitlines()]
        if change == "duplicate_seed":
            rows[-1] = rows[0]
        else:
            rows[0]["groups"]["students"]["positive"][0] += 1
        (moved / name).write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    envelope = json.loads((moved / anchor.name).read_text(encoding="utf-8"))
    envelope["payload"]["migration"]["files"][name] = artifacts._file_hash(moved / name)
    envelope["sha256"] = artifacts._digest(envelope["payload"])
    (moved / anchor.name).write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="report|coverage|differs from original"):
        artifacts.load_calibration_artifact(moved / anchor.name, protocol)


@pytest.mark.parametrize("change", ["model", "engine_source"])
def test_background_migration_rejects_unrelated_changes(legacy_background_anchor, tmp_path, change):
    from cemas.e0 import migration

    protocol, source = legacy_background_anchor
    root = tmp_path / "source"
    shutil.copytree(source.parent, root)
    envelope = json.loads(source.read_text(encoding="utf-8"))
    compatibility = envelope["payload"]["compatibility"]
    if change == "model":
        compatibility["base_model"]["beta_layer"]["cm"] *= .5
    else:
        compatibility["source_sha256"]["covasim/sim.py"] = "0" * 64
    envelope["sha256"] = artifacts._digest(envelope["payload"])
    (root / source.name).write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="only permits|outside.*scope"):
        migration.migrate_background_anchor(root / source.name, tmp_path / "output", protocol)
    assert not (tmp_path / "output").exists()


def test_background_migration_trajectory_failure_never_exports(legacy_background_anchor, tmp_path, monkeypatch):
    from cemas.e0 import migration

    protocol, source = legacy_background_anchor

    def changed(*args):
        world = _migration_world(*args)
        world["groups"]["students"]["positive"][0] += 1
        return world

    monkeypatch.setattr(migration, "run_e0_world", changed)
    output = tmp_path / "failed"
    with pytest.raises(ValueError, match="differs from original"):
        migration.migrate_background_anchor(source, output, protocol)
    assert not (output / artifacts.ARTIFACT_FILENAME).exists()
    assert json.loads((output / "migration_failure.json").read_text())["status"] == "failed"


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


@pytest.mark.parametrize("change", ["schema", "sensitivity", "beta", "beta_in_range", "missing_evidence", "model", "roles"])
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
    elif change == "roles":
        p["compatibility"]["base_model"]["campus_teacher_ratio"] = 1150 / 69457
        p["compatibility"]["base_model"]["campus_staff_ratio"] = 22767 / 69457
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
    assert manifest["resolved_config"]["engine"]["campus_k_ts"] == 3
    assert manifest["calibration_verified"] is True
    assert manifest["campus_background"] == {"employee_cm": .1, "employee_ta": .5}
    assert manifest["resolved_config"]["engine"]["beta_layer"]["ta"] == pytest.approx(.6)
    assert manifest["calibration"]["artifact_sha256"] == verified.sha256
    assert manifest["calibration"]["beta"] == pytest.approx(verified.beta * 1.12)
    assert len(manifest["registration"]["student_indices"]) == 45540
    assert len(manifest["registration"]["teacher_indices"]) == 2321
    assert len(manifest["registration"]["staff_indices"]) == 21596


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

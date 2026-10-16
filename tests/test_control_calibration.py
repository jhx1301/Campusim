"""E0 data, loss, shared configuration and artifact gates on small fixtures."""

import json
from pathlib import Path

import pytest

from cemas.control import calibration as cal
from cemas.control.protocol import load_protocol
from cemas.control.scenarios import (
    base_model_configuration, build_scenario, configuration_sha256,
    population_configuration, resolve_campus_parameters,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/control_protocol_v1.json"
DATA = ROOT / "data/notre_dame_2020_early.csv"


@pytest.fixture
def protocol(tmp_path):
    definition = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    definition["engine"].update(pop_size=100, pop_infected=3)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    return load_protocol(path)


def fake_run(protocol, beta, seed, window, data, *, through_holdout=False):
    days = 16 if window == "primary" or through_holdout else 12
    return {"world_seed": seed, "diagnoses": tuple(beta * 100 + (seed % 3) + day for day in range(days)),
            "population": {"population": protocol.population}, "roles": {},
            "resolved_parameters": {"pop_size": protocol.population, "beta": beta}}


@pytest.fixture
def fitted(protocol, tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "_run_calibration", fake_run)
    artifact = cal.fit_beta(protocol, DATA)
    path = cal.save_calibration_artifact(artifact, tmp_path / "fit")
    return artifact, path


def test_loss_averages_world_errors_before_averaging_curves():
    # The mean curve fits exactly; each world still has nonzero error.
    assert cal.normalized_diagnosis_mse([[0, 2], [2, 0]], [1, 1]) == .25
    with pytest.raises(ValueError):
        cal.normalized_diagnosis_mse([[float("nan")]], [0])


def test_data_rejects_gaps_duplicate_dates_and_invalid_counts(tmp_path):
    path = tmp_path / "data.csv"
    for text in (
        "date,new_diagnoses,new_tests\n2020-08-03,0,2\n2020-08-05,1,2\n",
        "date,new_diagnoses,new_tests\n2020-08-03,0,2\n2020-08-03,1,2\n",
        "date,new_diagnoses,new_tests\n2020-08-03,nan,2\n",
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            cal.read_calibration_data(path)


def test_parameter_resolver_is_detached_and_preserves_shared_population(protocol):
    first = resolve_campus_parameters(protocol, 1, beta=.01, execution_days=16)
    second = resolve_campus_parameters(protocol, 2, beta=.02, execution_days=112)
    keys = population_configuration(protocol)
    for key in keys:
        assert cal.resolved_snapshot(first[key]) == cal.resolved_snapshot(second[key])
    first["beta_layer"]["clu"] = 0
    assert second["beta_layer"]["clu"] == 1
    assert protocol.definition["engine"]["beta_layer"]["clu"] == 1


def test_e0_and_control_share_population_without_control_interventions(protocol):
    control = build_scenario(protocol, 91230, population=100, execution_days=16, initial_infections=3)
    sim = cal.make_calibration_sim(protocol, .016, 10001, data=DATA)
    assert sim.initialized and sim.t == 0 and not sim.results_ready
    assert sim.npts == 16
    assert sim["interventions"][0].test_delay == 0
    assert len(sim["interventions"]) == 1
    assert not sim["analyzers"]
    for key in population_configuration(protocol):
        assert cal.resolved_snapshot(sim[key]) == cal.resolved_snapshot(control.sim[key])


def test_real_small_calibration_world_executes_exactly_the_requested_days(protocol):
    run = cal._run_calibration(protocol, .016, 10001, "primary", cal.read_calibration_data(DATA))
    assert len(run["diagnoses"]) == 16
    assert run["resolved_parameters"]["n_days"] == 15
    assert run["population"]["population"] == 100


def test_fit_evidence_and_independent_report_are_both_required(protocol, fitted, monkeypatch):
    artifact, path = fitted
    assert len(artifact.payload["trials"]) == 100
    assert tuple(artifact.payload["fit_seeds"]) == (10001, 10002, 10003)
    assert artifact.payload["n_days"] == 15
    assert artifact.payload["calibration_spec"]["primary_demography"] == "shared_v1_engine_population"
    assert cal.load_calibration_artifact(path, protocol, require_evaluation=False).beta == artifact.beta
    with pytest.raises(ValueError, match="artifact|incomplete"):
        cal.load_calibration_artifact(path, protocol)
    report = cal.evaluate_beta(artifact)
    assert len(report.payload["evaluation_seeds"]) == 20
    assert report.payload["evaluation_window"] == ("2020-08-03", "2020-08-18")
    cal.save_fit_report(report, path.parent)
    assert cal.load_calibration_artifact(path, protocol).sha256 == artifact.sha256
    with pytest.raises(FileExistsError):
        cal.save_calibration_artifact(artifact, path.parent)
    with pytest.raises(ValueError, match="independent"):
        cal.evaluate_beta(artifact, [10001])


def test_legacy_tampered_and_wrong_population_artifacts_are_rejected(protocol, fitted, tmp_path):
    artifact, path = fitted
    legacy = tmp_path / "old.json"
    legacy.write_text('{"beta": 0.016, "beta_layer_d": 2}', encoding="utf-8")
    with pytest.raises(ValueError):
        cal.load_calibration_artifact(legacy, protocol)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["beta"] = .03
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError):
        cal.load_calibration_artifact(path, protocol, require_evaluation=False)
    path.write_text(json.dumps({"sha256": artifact.sha256,
                               "payload": cal.resolved_snapshot(artifact.payload)}), encoding="utf-8")
    definition = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    changed = tmp_path / "changed.json"
    definition["engine"].update(pop_size=100, pop_infected=3, campus_teacher_ratio=.09)
    changed.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        cal.load_calibration_artifact(path, load_protocol(changed), require_evaluation=False)


def test_control_horizon_and_reward_changes_do_not_invalidate_e0(protocol, fitted, tmp_path):
    artifact, path = fitted
    definition = json.loads(protocol.source_path.read_text(encoding="utf-8"))
    definition["engine"].update(execution_days=140, n_days=139)
    definition["objective"]["lambda"] = 2
    revised = tmp_path / "revised.json"
    revised.write_text(json.dumps(definition), encoding="utf-8")
    updated = load_protocol(revised)
    assert configuration_sha256(base_model_configuration(protocol)) == configuration_sha256(base_model_configuration(updated))
    assert cal.load_calibration_artifact(path, updated, require_evaluation=False).beta == artifact.beta


def test_auxiliary_holdout_runs_from_the_fit_start(protocol, tmp_path, monkeypatch):
    calls = []
    def recorder(*args, **kwargs):
        calls.append((args[2], kwargs.get("through_holdout", False)))
        return fake_run(*args, **kwargs)
    monkeypatch.setattr(cal, "_run_calibration", recorder)
    artifact = cal.fit_beta(protocol, DATA, window="exploratory")
    report = cal.evaluate_beta(artifact)
    assert report.payload["evaluation_window"] == ("2020-08-15", "2020-08-18")
    assert report.payload["execution_start"] == "2020-08-03"
    assert report.payload["continuous_from_fit_start"]
    assert len(report.payload["observed"]) == 4
    assert all(continued for _, continued in calls[-20:])
    path = cal.save_calibration_artifact(artifact, tmp_path / "aux")
    cal.save_fit_report(report, path.parent)
    with pytest.raises(ValueError, match="primary"):
        cal.load_calibration_artifact(path, protocol)


def test_failed_fit_preserves_trials_without_producing_a_calibrated_artifact(protocol, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("injected simulation failure")
    monkeypatch.setattr(cal, "_run_calibration", fail)
    with pytest.raises(cal.CalibrationFitError) as caught:
        cal.fit_beta(protocol, DATA)
    assert len(caught.value.trial_records) == 1
    assert caught.value.trial_records[0]["state"] == "FAIL"


@pytest.mark.parametrize("field", ["mean_diagnoses", "diagnoses_band", "mean_mae", "per_world",
                                    "continuous_from_fit_start", "execution_start"])
def test_report_gate_rejects_self_inconsistent_statistics_even_with_recomputed_hash(protocol, fitted, field):
    artifact, path = fitted
    payload = cal.resolved_snapshot(cal.evaluate_beta(artifact).payload)
    if field == "mean_diagnoses":
        payload[field][0] += 1
    elif field == "diagnoses_band":
        payload[field][0][0] += 1
    elif field == "mean_mae":
        payload[field] += 1
    elif field == "per_world":
        payload[field][0]["rmse"] += 1
    elif field == "execution_start":
        payload[field] = "2020-08-15"
    else:
        payload[field] = True
    report_path = path.with_name("fit_report.json")
    report_path.write_text(json.dumps({"payload": payload, "sha256": cal._digest(payload)}), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        cal.load_calibration_artifact(path, protocol)


def test_evaluation_can_use_current_compatible_protocol_after_source_file_moves(protocol, fitted, tmp_path):
    artifact, _ = fitted
    new_path = tmp_path / "moved_protocol.json"
    new_path.write_bytes(protocol.source_path.read_bytes())
    protocol.source_path.unlink()
    report = cal.evaluate_beta(artifact, protocol=load_protocol(new_path))
    assert len(report.payload["evaluation_seeds"]) == 20

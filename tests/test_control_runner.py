"""Small-population checks of the complete reference and audit boundary."""

import csv
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cemas.control.actions import legal_action_mask
from cemas.control.controllers import MinimumController, MaximumFeasibleController
from cemas.control.logging import RunLogger
from cemas.control.protocol import load_protocol
from cemas.control.runner import run_episode
from cemas.control.types import ActionVector, PublicObservation, PublicPopulation, PublicResources, PublicWeekFeedback


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_PATH)


@pytest.mark.parametrize("capacity,expected", [(0, 0), (2, 1), (5, 2), (10, 3)])
def test_fixed_references_use_public_mask_and_preserve_zero_baseline(protocol, capacity, expected):
    resources = PublicResources(2, capacity, 1)
    population = PublicPopulation(100, (0, 100, 0, 0, 0), 100, 0)
    observation = PublicObservation(0, 112, 2, population, resources, ActionVector((0, 0, 0, 0, 0)),
                                    (0, 0, 0, 0, 0), legal_action_mask(resources, 100, protocol.definition["actions"]))
    assert MinimumController().decide(observation).action.values == (0, 0, 0, 0, 0)
    assert MaximumFeasibleController().decide(observation).action.values == (2, expected, 2, 2, 2)


class ObservedMinimum(MinimumController):
    def __init__(self):
        self.days = []
        self.feedback = []
        self.resets = 0

    def reset(self):
        self.resets += 1

    def decide(self, observation):
        assert type(observation) is PublicObservation
        self.days.append(observation.decision_day)
        return super().decide(observation)

    def observe(self, feedback):
        assert type(feedback) is PublicWeekFeedback
        self.feedback.append((feedback.week.start_day, feedback.week.end_day))


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_complete_small_reference_reconciles_tail_and_keeps_truth_private(protocol, tmp_path):
    controller = ObservedMinimum()
    output = tmp_path / "minimum"
    result = run_episode(protocol, controller, output, 90001,
                         scenario_options={"population": 40, "execution_days": 9, "initial_infections": 2})
    assert result.status == "completed" and controller.resets == 1
    assert controller.days == [7] and controller.feedback == [(0, 6), (7, 8)]
    public = _read_csv(output / "public_daily.csv")
    private = _read_csv(output / "private_daily.csv")
    weekly = _read_csv(output / "private_weekly_rewards.csv")
    summary = json.loads((output / "summary.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(public) == len(private) == 9 and len(weekly) == 2
    assert sum(int(row["new_infections"]) for row in private) + 2 == summary["private_metrics"]["cumulative_infections"]
    assert sum(float(row["reward"]) for row in weekly) == pytest.approx(summary["total_reward"])
    assert sum(int(row["clinical_tests"]) for row in public) == summary["public_cost"]["clinical_tests"]
    assert summary["daily_weekly_terminal_reconciled"]
    assert manifest["status"] == "completed" and manifest["purpose"] == "smoke"
    assert manifest["calibration_verified"] is False
    assert "dur" in manifest["resolved_config"]["engine"]
    assert "prognoses" in manifest["resolved_config"]["engine"]
    assert manifest["reward_configuration"]["execution_days"] == 9
    decisions = [json.loads(line) for line in (output / "decisions.jsonl").read_text().splitlines()]
    assert [record["decision_day"] for record in decisions] == [0, 7]
    for record in decisions:
        assert not {"reward", "world_seed", "private_metrics", "beta"} & record["observation"].keys()
    with pytest.raises(FileExistsError):
        run_episode(protocol, MinimumController(), output, 90001)


def test_runner_preserves_failure_after_a_completed_window(protocol, tmp_path):
    class BrokenController(MinimumController):
        def decide(self, observation):
            if observation.decision_day:
                raise RuntimeError("controller failed after first window")
            return super().decide(observation)

    output = tmp_path / "broken"
    with pytest.raises(RuntimeError, match="controller failed"):
        run_episode(protocol, BrokenController(), output, 90002,
                    scenario_options={"population": 30, "execution_days": 9, "initial_infections": 1})
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((output / "summary.json").read_text())["status"] == "failed"
    assert len(_read_csv(output / "public_daily.csv")) == 7
    assert len(_read_csv(output / "private_weekly_rewards.csv")) == 1
    assert (output / "failure.json").exists()


def test_logging_failure_after_environment_completion_is_not_success(protocol, tmp_path, monkeypatch):
    write_json = RunLogger._write_json

    def fail_completed_summary(self, filename, payload):
        if filename == "summary.json" and payload.get("status") == "completed":
            raise OSError("simulated summary write failure")
        return write_json(self, filename, payload)

    monkeypatch.setattr(RunLogger, "_write_json", fail_completed_summary)
    output = tmp_path / "disk-failure"
    with pytest.raises(OSError, match="summary write failure"):
        run_episode(protocol, MinimumController(), output, 90001,
                    scenario_options={"population": 25, "execution_days": 2, "initial_infections": 1})
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    assert len(_read_csv(output / "public_daily.csv")) == 2


def test_runner_refuses_final_test_world_before_creating_directory(protocol, tmp_path):
    with pytest.raises(ValueError, match="final-test"):
        run_episode(protocol, MinimumController(), tmp_path / "forbidden", 50001)
    assert not (tmp_path / "forbidden").exists()


@pytest.mark.parametrize("purpose,seed", [("smoke", 20001), ("smoke", 91231), ("scientific", 90001), ("scientific", 10001)])
def test_runner_enforces_purpose_seed_pool_before_running(protocol, tmp_path, purpose, seed):
    with pytest.raises(ValueError, match="seeds"):
        run_episode(protocol, MinimumController(), tmp_path / "wrong-pool", seed, purpose=purpose)
    assert not (tmp_path / "wrong-pool").exists()


def test_cli_modules_are_inert_on_import_and_help_needs_no_simulation(monkeypatch):
    import cemas.control.runner as runner

    def forbidden(*args, **kwargs):
        raise AssertionError("import unexpectedly started a run")

    monkeypatch.setattr(runner, "run_episode", forbidden)
    for name in ("smoke", "calibrate", "evaluate_calibration", "run_references", "run_llm", "smoke_llm"):
        module = importlib.import_module(f"examples.control_v1.{name}")
        with pytest.raises(SystemExit) as exit_info:
            module.main(["--help"])
        assert exit_info.value.code == 0


@pytest.mark.parametrize("split,seed,scale,capacity", [
    ("A", 20001, .9, .02), ("A", 20005, 1, .05), ("B", 20103, .9, .05),
])
@pytest.mark.parametrize("data_path", [None, "data/relocated.csv"])
def test_reference_cli_verifies_e0_and_maps_source_worlds(tmp_path, monkeypatch, split, seed, scale, capacity, data_path):
    from examples.control_v1 import run_references
    import cemas.control.calibration as calibration
    import cemas.control.runner as runner

    verified = []
    calls = []
    artifact = tmp_path / "artifact.json"

    expected_data = None if data_path is None else Path(data_path)

    def load(path, protocol, *, require_evaluation, data_path):
        assert require_evaluation is True
        assert data_path == expected_data
        verified.append(path)

    def run(protocol, controller, output_dir, world_seed, **kwargs):
        assert verified == [artifact]
        calls.append((controller.controller_type, world_seed, kwargs))
        return SimpleNamespace(status="completed", output_dir=output_dir)

    monkeypatch.setattr(calibration, "load_calibration_artifact", load)
    monkeypatch.setattr(runner, "run_episode", run)
    args = ["--artifact", str(artifact), "--output", str(tmp_path / "runs"),
            "--validation-split", split, "--seed", str(seed)]
    if data_path is not None:
        args.extend(["--data", data_path])
    assert run_references.main(args) == 0
    assert [call[0] for call in calls] == ["minimum", "maximum_feasible"]
    for _, world_seed, kwargs in calls:
        assert world_seed == seed and kwargs["purpose"] == "scientific"
        assert kwargs["scenario_options"] == {"calibration_artifact": artifact,
                                               "calibration_data_path": expected_data,
                                               "beta_scale": scale, "screening_capacity_ratio": capacity}


def test_reference_cli_rejects_final_seed_before_loading_evidence(tmp_path, monkeypatch):
    from examples.control_v1 import run_references
    import cemas.control.calibration as calibration

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid seed must fail before artifact loading")

    monkeypatch.setattr(calibration, "load_calibration_artifact", forbidden)
    with pytest.raises(SystemExit) as error:
        run_references.main(["--artifact", str(tmp_path / "artifact.json"), "--output",
                             str(tmp_path / "runs"), "--seed", "50001"])
    assert error.value.code == 2 and not (tmp_path / "runs").exists()


def test_calibrate_cli_preserves_incomplete_trial_evidence(tmp_path, monkeypatch):
    from examples.control_v1 import calibrate
    import cemas.control.calibration as calibration

    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        error = RuntimeError("fit stopped")
        error.trial_records = ({"number": 0, "state": "FAIL"},)
        raise error

    monkeypatch.setattr(calibration, "fit_beta", fail)
    output = tmp_path / "failed-fit"
    with pytest.raises(RuntimeError, match="fit stopped"):
        calibrate.main(["--output", str(output)])
    failure = json.loads((output / "failure.json").read_text())
    assert failure["status"] == "failed" and failure["trial_records"][0]["state"] == "FAIL"
    assert not (output / "artifact.json").exists()
    with pytest.raises(FileExistsError):
        calibrate.main(["--output", str(output)])
    assert len(calls) == 1

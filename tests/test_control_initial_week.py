"""Common first-week behavior and the accounting/identity boundary."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from cemas.control.actions import decode_action
from cemas.control.artifacts import (get_baseline_artifact,
                                     save_baseline_artifact, training_budget)
from cemas.control.controllers import (MaximumFeasibleController, MinimumController,
                                      ThresholdController, UniformLegalController)
from cemas.control.environment import WeeklyControlEnvironment
from cemas.control.logging import snapshot_sha256
from cemas.control.protocol import load_protocol, ProtocolValidationError
from cemas.control.runner import make_public_prompt_config, run_episode
from cemas.control.training import train_controller
from cemas.control.types import ActionProposal


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_PATH)


@pytest.mark.parametrize("method", ["minimum", "maximum_feasible", "threshold", "random"])
def test_all_collection_policies_share_actual_initial_week_and_first_observation(protocol, tmp_path, method):
    controller = {"minimum": MinimumController, "maximum_feasible": MaximumFeasibleController,
                  "random": UniformLegalController,
                  "threshold": lambda: ThresholdController(protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"])}[method]()
    decide, observations, transitions = controller.decide, [], []

    def counted(observation):
        observations.append(observation)
        return decide(observation)

    controller.decide = counted
    output = tmp_path / method
    result = run_episode(protocol, controller, output, 90001,
        scenario_options={"population": 40, "initial_infections": 2, "execution_days": 9},
        public_transition_sink=lambda before, feedback: transitions.append((before, feedback)))
    assert [item.decision_day for item in observations] == [7]
    assert observations[0].week_valid == (False, False, False, True)
    assert observations[0].history[-1] == transitions[0][1].week
    assert transitions[0][1].week.executed_action == decode_action(0)
    assert transitions[0][0].decision_day == 0
    records = [json.loads(line) for line in (output / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["decision_source"] for row in records] == ["protocol_fixed", "controller"]
    assert not records[0]["fallback_used"] and records[0]["llm_attempt_count"] == 0
    assert records[0]["llm_succeeded"] is None
    assert result.summary["fixed_window_count"] == 1
    assert result.summary["execution_window_count"] == 2
    assert result.summary["autonomous_decision_count"] == result.summary["decision_count"] == 1
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["initial_baseline_days"] == 7


@pytest.mark.parametrize("horizon,decisions", [(2, 0), (7, 0), (112, 15)])
def test_horizon_includes_fixed_week_without_extending_it(protocol, tmp_path, horizon, decisions):
    class CountMinimum(MinimumController):
        def decide(self, observation):
            self.days.append(observation.decision_day)
            return super().decide(observation)

    controller = CountMinimum()
    controller.days = []
    result = run_episode(protocol, controller, tmp_path / str(horizon), 90001,
        scenario_options={"population": 30, "initial_infections": 1, "execution_days": horizon})
    assert controller.days == list(range(7, horizon, 7))
    assert result.summary["elapsed_days"] == horizon
    assert result.summary["decision_count"] == decisions
    assert result.summary["execution_window_count"] == decisions + 1


@pytest.mark.parametrize("proposal", [None, ActionProposal(decode_action(323))])
def test_environment_rejects_nonminimum_day_zero_without_advancing(protocol, proposal):
    environment = WeeklyControlEnvironment(protocol, scenario_options={"population": 30,
        "initial_infections": 1, "execution_days": 8})
    try:
        environment.reset(90001)
        with pytest.raises(ValueError, match="day0"):
            environment.step_proposal(proposal)
        assert environment.audit_snapshot().elapsed_days == 0
        first = environment.advance_initial_week()
        assert first[0].decision_day == 7
        with pytest.raises(RuntimeError, match="already"):
            environment.advance_initial_week()
        environment.step_proposal(ActionProposal(decode_action(108)))
        assert environment.audit_snapshot().windows[-1].resolution.executed_action == decode_action(108)
    finally:
        environment.close()


def test_training_budget_accounts_for_fixed_autoreset_and_partial_initial_failure(tmp_path):
    events = [
        {"event": "initializing", "world_seed": 1, "scenario_options": {}},
        {"event": "initialized", "world_seed": 1},
        {"event": "fixed_window", "world_seed": 1, "elapsed_days": 7, "positive_cost": .2},
        {"event": "transition", "world_seed": 1, "elapsed_days": 8, "positive_cost": .3},
        {"event": "completed", "world_seed": 1},
        {"event": "initializing", "world_seed": 2, "scenario_options": {}},
        {"event": "initialized", "world_seed": 2},
        {"event": "fixed_window", "world_seed": 2, "elapsed_days": 7, "positive_cost": .4},
        {"event": "closed", "world_seed": 2, "elapsed_days": 7},
        {"event": "initializing", "world_seed": 3, "scenario_options": {}},
        {"event": "initialized", "world_seed": 3},
        {"event": "failed", "world_seed": 3, "elapsed_days": 2},
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in events), encoding="utf-8")
    budget = training_budget(path)
    assert budget["transitions"] == budget["autonomous_decisions"] == 1
    assert budget["fixed_windows"] == 2 and budget["simulated_days"] == 17
    assert budget["fixed_window_positive_cost"] == pytest.approx(.6)
    assert budget["autonomous_positive_cost"] == pytest.approx(.3)
    assert budget["initialized_unstepped_worlds"] == [2, 3]
    assert budget["worlds"][-1]["failed"]


@pytest.mark.parametrize("method", ["threshold", "ddqn", "ppo"])
def test_old_task_cannot_be_relabelled_as_current_artifact(protocol, tmp_path, method):
    weights = tmp_path / "weights"
    weights.write_bytes(b"offline task identity fixture")
    parameters = {"thresholds": protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"]}
    path = save_baseline_artifact(tmp_path / method, protocol, method,
        parameters=parameters if method == "threshold" else None,
        weights_path=weights if method != "threshold" else None)
    assert get_baseline_artifact(path, protocol)["task"]["initial_baseline_days"] == 7
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["task"].pop("initial_baseline_days")
    payload["task_sha256"] = snapshot_sha256(payload["task"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="task"):
        get_baseline_artifact(path, protocol)


def test_old_threshold_semantics_and_parameters_are_rejected(protocol, tmp_path):
    thresholds = protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"]
    path = save_baseline_artifact(tmp_path, protocol, "threshold", parameters={"thresholds": thresholds})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["algorithm_semantics"] = "public-two-week-hysteresis-v1"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="semantics"):
        get_baseline_artifact(path, protocol)
    with pytest.raises(TypeError, match="hysteresis"):
        save_baseline_artifact(tmp_path / "old", protocol, "threshold",
                               parameters={"thresholds": thresholds, "hysteresis": .5})


def test_initial_rule_is_public_and_fixed_and_short_training_is_rejected(protocol, tmp_path):
    assert make_public_prompt_config(protocol).public_spec["task"]["initial_baseline_days"] == 7
    short = replace(protocol, execution_days=7)
    with pytest.raises(ValueError, match="autonomous"):
        train_controller(short, "ppo", tmp_path / "train", "missing-e0")
    assert not (tmp_path / "train").exists()
    definition = json.loads(protocol.source_path.read_text(encoding="utf-8"))
    definition["engine"]["initial_baseline_days"] = 0
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ProtocolValidationError, match="initial_baseline_days"):
        load_protocol(path)


def test_initial_step_failure_preserves_partial_daily_evidence_without_controller_call(protocol, tmp_path, monkeypatch):
    import covasim as cv

    original = cv.Sim.step
    calls = []

    def fail_after_one_day(sim):
        if calls:
            raise RuntimeError("initial week interrupted")
        calls.append(True)
        return original(sim)

    class NoDecisions(MinimumController):
        def decide(self, observation):
            raise AssertionError("initial week must not call a controller")

    monkeypatch.setattr(cv.Sim, "step", fail_after_one_day)
    output = tmp_path / "initial-failure"
    with pytest.raises(RuntimeError, match="initial week interrupted"):
        run_episode(protocol, NoDecisions(), output, 90001,
            scenario_options={"population": 30, "initial_infections": 1, "execution_days": 9})
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["elapsed_days"] == 1
    assert manifest["initial_baseline_days"] == 7
    assert (output / "decisions.jsonl").read_text(encoding="utf-8") == ""
    assert len((output / "public_daily.csv").read_text(encoding="utf-8").splitlines()) == 2


def test_public_case_identity_rejects_old_first_week_semantics(protocol):
    from cemas.control.llm import PublicPromptConfig
    from cemas.control.logging import resolved_snapshot
    from cemas.control.memory import public_task_hash

    current = make_public_prompt_config(protocol)
    spec = resolved_snapshot(current.public_spec)
    spec["task"]["initial_baseline_days"] = 0
    previous = PublicPromptConfig(current.template, spec, current.reason_max_chars)
    assert public_task_hash(current, 112) != public_task_hash(previous, 112)


def test_e0_population_and_base_model_identity_ignores_control_timing(protocol):
    from cemas.control.scenarios import base_model_configuration, population_configuration
    from cemas.control.logging import resolved_snapshot

    definition = resolved_snapshot(protocol.definition)
    definition["engine"]["initial_baseline_days"] = 0
    previous = replace(protocol, definition=definition)
    assert base_model_configuration(previous) == base_model_configuration(protocol)
    assert population_configuration(previous) == population_configuration(protocol)

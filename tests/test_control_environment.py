"""Weekly lifecycle, information boundaries, and day/window/terminal accounting."""

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import numpy as np
import pytest

from cemas.control.actions import decode_action
from cemas.control.environment import WeeklyControlEnvironment
from cemas.control.execution import NotificationEvent
from cemas.control.logging import hash_observation
from cemas.control.protocol import load_protocol
from cemas.control.types import ActionProposal, PrivateMetrics, PublicInfo


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_PATH)


def make_environment(protocol, horizon=10, mode="evaluation", **options):
    return WeeklyControlEnvironment(
        protocol, mode=mode,
        scenario_options={"population": 80, "execution_days": horizon,
                          "initial_infections": 2, **options},
    )


def finish(environment, *, proposal=False):
    results = []
    while True:
        result = (environment.step_proposal(ActionProposal(decode_action(0))) if proposal
                  else environment.step(0))
        results.append(result)
        if result[2]:
            return results


@pytest.mark.parametrize("horizon", [2, 7, 8, 15, 112])
def test_day_zero_tail_terminal_and_additive_accounting(protocol, horizon, monkeypatch):
    environment = make_environment(protocol, horizon)
    observation, info = environment.reset(91240)
    assert observation.decision_day == 0
    assert observation.week_valid == (False,) * 4
    assert observation.action_duration_days == (0,) * 5
    assert info == PublicInfo()
    bundle = environment._bundle
    finalize = bundle.sim.finalize
    calls = []

    def counted_finalize(*args, **kwargs):
        calls.append(True)
        return finalize(*args, **kwargs)

    monkeypatch.setattr(bundle.sim, "finalize", counted_finalize)
    results = finish(environment)
    audit = environment.audit_snapshot()
    assert len(results) == (horizon + 6) // 7
    assert len(audit.public_daily) == len(audit.private_daily) == horizon
    assert audit.status == "completed" and audit.finalize_attempted
    assert len(calls) == 1 and bundle.sim.t == horizon - 1
    assert results[-1][0].decision_day == horizon
    assert results[-1][0].action_duration_days == (horizon,) * 5
    assert sum(results[-1][0].week_valid) == min(4, horizon // 7)
    assert all(result[1] == 0.0 and result[3] is False for result in results)
    assert results[-1][4].feedback.week.end_day == horizon - 1
    assert results[-1][4].feedback.week.start_day == ((horizon - 1) // 7) * 7
    assert audit.terminal_metrics.cumulative_infections == (
        2 + sum(day.new_infections for day in audit.private_daily))
    assert audit.terminal_metrics.new_infections == sum(
        window.private_metrics.new_infections for window in audit.windows)
    for field in fields(audit.public_daily[0].cost):
        assert sum(getattr(day.cost, field.name) for day in audit.public_daily) == pytest.approx(
            sum(getattr(window.feedback.week.cost, field.name) for window in audit.windows))
    with pytest.raises(RuntimeError, match="non-running"):
        environment.step(0)
    environment.close()
    environment.close()
    assert environment.audit_snapshot() == audit
    assert len(calls) == 1 and environment._bundle is None


def test_id_and_proposal_training_and_evaluation_have_identical_worlds(protocol):
    evaluation = make_environment(protocol, 8)
    evaluation.reset(91241)
    evaluation_results = finish(evaluation)
    training = make_environment(protocol, 8, mode="training")
    training.reset(91241)
    training_results = finish(training, proposal=True)
    evaluation_audit, training_audit = evaluation.audit_snapshot(), training.audit_snapshot()
    assert evaluation_audit.public_daily == training_audit.public_daily
    assert evaluation_audit.private_daily == training_audit.private_daily
    assert evaluation_audit.windows == training_audit.windows
    for evaluated, trained, window in zip(evaluation_results, training_results, training_audit.windows):
        assert evaluated[0] == trained[0]
        assert evaluated[4] == trained[4]
        assert evaluated[1] == 0.0 and trained[1] == window.reward
        assert trained[1] == -sum(window.reward_breakdown.weighted)


@pytest.mark.parametrize("invalid_id", [True, 1.5, -1, 324, np.int64(0)])
def test_invalid_ids_use_shared_fallback_without_coercion(protocol, invalid_id):
    environment = make_environment(protocol, 2)
    environment.reset(91242)
    _, _, terminated, _, info = environment.step(invalid_id)
    assert terminated
    assert info.resolution.requested_action is None
    assert info.resolution.fallback_reason == "invalid_action_id"
    assert info.resolution.executed_action == decode_action(0)


def test_illegal_screening_preserves_request_and_both_entries_resolve_once(protocol, monkeypatch):
    import cemas.control.environment as environment_module

    original = environment_module.resolve_action
    calls = []

    def counted_resolve(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(environment_module, "resolve_action", counted_resolve)
    environment = make_environment(protocol, 8, screening_capacity_ratio=.02)
    environment.reset(91243)
    result = environment.step(323)
    assert result[4].resolution.requested_action == decode_action(323)
    assert result[4].resolution.fallback_reason == "screening_capacity_exceeded"
    environment.step_proposal(None, fallback_reason="controller_unavailable")
    assert len(calls) == 2


def test_close_aborts_without_finalize_and_reset_drops_previous_state(protocol, monkeypatch):
    environment = make_environment(protocol, 15)
    environment.reset(91244)
    environment.step(0)
    bundle = environment._bundle

    def forbidden_finalize(*args, **kwargs):
        raise AssertionError("an aborted episode must not finalize")

    monkeypatch.setattr(bundle.sim, "finalize", forbidden_finalize)
    old_snapshot = environment.audit_snapshot()
    environment.close()
    assert environment.audit_snapshot().status == "aborted"
    assert not environment.audit_snapshot().finalize_attempted
    assert old_snapshot.status == "running" and len(old_snapshot.public_daily) == 7
    observation, _ = environment.reset(91244)
    assert observation.decision_day == 0 and observation.action_duration_days == (0,) * 5
    assert environment.audit_snapshot().public_daily == ()
    environment.step(0)
    assert environment.audit_snapshot().public_daily == old_snapshot.public_daily


def test_terminal_pending_events_are_not_delivered_or_flushed(protocol):
    environment = make_environment(protocol, 2)
    environment.reset(91245)
    bundle = environment._bundle
    bundle.executor._pending_notifications[10].append(NotificationEvent(0, 1, "cm", 0, 10, 14))
    bundle.sim.people.date_diagnosed[1] = 10
    environment.step(0)
    audit = environment.audit_snapshot()
    assert audit.pending_notifications == 1
    assert audit.pending_diagnoses >= 1
    assert sum(day.cost.delivered_notifications for day in audit.public_daily) == 0
    assert audit.elapsed_days == 2
    environment.close()
    assert environment.audit_snapshot().pending_notifications == 1


@pytest.mark.parametrize("failure_stage", ["step", "finalize", "reconcile"])
def test_failure_never_becomes_completed_and_close_never_retries(protocol, monkeypatch, failure_stage):
    environment = make_environment(protocol, 2)
    environment.reset(91246)
    bundle = environment._bundle
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("injected failure")

    if failure_stage == "reconcile":
        monkeypatch.setattr(environment, "_reconcile", fail)
    else:
        monkeypatch.setattr(bundle.sim, failure_stage, fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        environment.step(0)
    audit = environment.audit_snapshot()
    assert audit.status == "failed"
    assert audit.finalize_attempted == (failure_stage != "step")
    assert "injected failure" in audit.error
    environment.close()
    environment.close()
    assert len(calls) == 1 and environment.audit_snapshot().status == "failed"
    with pytest.raises(RuntimeError):
        environment.step(0)


def test_public_info_and_runner_snapshot_have_separate_immutable_boundaries(protocol):
    environment = make_environment(protocol, 2)
    observation, info = environment.reset(91247)
    assert {field.name for field in fields(info)} == {"resolution", "feedback"}
    private = PrivateMetrics(0, 0, 0, 2, 2, 0, 2)
    with pytest.raises(TypeError):
        PublicInfo(feedback=private)
    before = hash_observation(observation)
    environment._bundle.sim["beta"] = 1.0
    environment._bundle.sim["rand_seed"] = 123
    assert hash_observation(environment._observation()) == before
    audit = environment.audit_snapshot()
    assert audit.manifest["world_seed"] == 91247
    assert audit.manifest["calibration_verified"] is False
    assert "dur" in audit.manifest["resolved_config"]["engine"]
    assert len(audit.manifest["population_config_sha256"]) == 64
    assert len(audit.manifest["base_model_config_sha256"]) == 64
    with pytest.raises(TypeError):
        audit.manifest["world_seed"] = 1
    with pytest.raises(FrozenInstanceError):
        audit.elapsed_days = 99
    assert not any(hasattr(info, name) for name in ("reward", "seed", "sim", "private_metrics"))


@pytest.mark.parametrize("options", [
    {"beta": .016},
    {"calibration_artifact": "missing.json", "population": 80},
    {"calibration_artifact": "missing.json", "initial_infections": 2},
    {"calibration_artifact": "missing.json", "beta_scale": float("nan")},
])
def test_scientific_gate_rejects_unverified_or_incompatible_options_before_build(protocol, monkeypatch, options):
    import cemas.control.environment as environment_module

    def forbidden_build(*args, **kwargs):
        raise AssertionError("invalid scientific configuration must fail before initialization")

    monkeypatch.setattr(environment_module, "build_scenario", forbidden_build)
    environment = WeeklyControlEnvironment(protocol, purpose="scientific", scenario_options=options)
    with pytest.raises(ValueError):
        environment.reset(91248)
    assert environment.audit_snapshot().status == "failed"

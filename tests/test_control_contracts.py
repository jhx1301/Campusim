"""Phase 0 interface/schema checks; no controller or simulation algorithms."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone
import inspect
import json
import subprocess
import sys

import pytest

from cemas.control import (
    ActionDecoder, ActionProposal, ActionVector, Controller, DecisionRecord,
    ExecutedAction, PrivateMetrics, PublicCost, PublicObservation,
    PublicPopulation, PublicResources, PublicWeekFeedback, PublicWeeklyRecord,
    RewardCalculator, hash_observation, public_observation_to_dict,
)


def public_observation(**changes):
    observation = PublicObservation(
        decision_day=0, execution_days=112, initial_infections=30,
        population=PublicPopulation(12000, (0, 7200, 2400, 1800, 600), 8500, 1700, 900),
        resources=PublicResources(240, 600, 120),
        current_action=ActionVector((0, 0, 0, 0, 0)),
        action_duration_days=(0, 0, 0, 0, 0),
        legal_action_mask=(True,) * 324,
    )
    return replace(observation, **changes)


def test_abstract_interfaces_are_frozen_without_concrete_algorithms():
    assert Controller.__abstractmethods__ == {"reset", "decide", "observe"}
    assert ActionDecoder.__abstractmethods__ == {"decode"}
    assert RewardCalculator.__abstractmethods__ == {"compute"}
    assert list(inspect.signature(Controller.decide).parameters) == ["self", "observation"]
    assert list(inspect.signature(Controller.observe).parameters) == ["self", "feedback"]
    assert list(inspect.signature(RewardCalculator.compute).parameters) == [
        "self", "private_metrics", "public_cost", "action_history",
    ]
    for interface in (Controller, ActionDecoder, RewardCalculator):
        with pytest.raises(TypeError):
            interface()


@pytest.mark.parametrize("values", [
    (0, 0, 0, 0), (0, 0, 0, 0, 0, 0), (3, 0, 0, 0, 0),
    (0, 4, 0, 0, 0), (0, 0, -1, 0, 0), (0, 0, 0, 3, 0),
    (0, 0, 0, 0, 3), (True, 0, 0, 0, 0), (0.0, 0, 0, 0, 0),
])
def test_action_vector_rejects_wrong_shape_and_nonordinary_integers(values):
    with pytest.raises(ValueError):
        ActionVector(values)


def test_action_vector_copies_mutable_input_and_proposals_share_one_type():
    values = [2, 3, 2, 2, 2]
    action = ActionVector(values)
    values[0] = 0
    assert action.values == (2, 3, 2, 2, 2)
    assert ActionProposal(action, "采用当前合法组合").action is action
    with pytest.raises(FrozenInstanceError):
        action.values = (0, 0, 0, 0, 0)
    with pytest.raises(TypeError):
        ActionProposal([0, 0, 0, 0, 0])


@pytest.mark.parametrize("reason", ["", " ", "两行\n说明", "两行\r说明"])
def test_reasoning_has_the_v1_public_explanation_limits(reason):
    with pytest.raises(ValueError):
        ActionProposal(ActionVector((0, 0, 0, 0, 0)), reason)


def test_public_schema_is_an_explicit_allow_list_and_rejects_private_payloads():
    observation = public_observation()
    expected_fields = {
        "decision_day", "execution_days", "initial_infections", "population",
        "resources", "current_action", "action_duration_days", "legal_action_mask",
        "history", "week_valid", "previous_day_known_isolated",
        "previous_day_known_quarantined", "previous_day_known_union", "snapshot_day",
    }
    assert {field.name for field in fields(PublicObservation)} == expected_fields
    private = PrivateMetrics(0, 6, 100, 30, 130, 25, 80)
    for name in ("simulator", "new_infections", "r_eff", "infection_log",
                 "future_events", "world_seed", "episode_id", "private_metrics"):
        with pytest.raises(TypeError):
            replace(observation, **{name: private})
    with pytest.raises(TypeError):
        replace(observation, population=private)
    with pytest.raises(TypeError):
        PublicWeekFeedback(private)
    with pytest.raises(TypeError):
        replace(PublicWeeklyRecord(), cost=private)
    with pytest.raises(TypeError):
        public_observation_to_dict(private)


def test_public_hash_is_stable_and_independent_of_private_analysis():
    observation = public_observation()
    before = hash_observation(observation)
    private = PrivateMetrics(0, 6, 10, 30, 40, 5, 20)
    changed_private = replace(private, new_infections=200, cumulative_infections=230)
    assert private != changed_private
    assert hash_observation(replace(observation)) == before
    assert hash_observation(replace(observation, resources=PublicResources(240, 1200, 120))) != before
    payload = public_observation_to_dict(observation)
    # The optional takeover date is omitted from the legacy day0 wire format.
    assert set(payload) == {field.name for field in fields(PublicObservation)} - {"snapshot_day"}
    assert json.loads(json.dumps(payload))["current_action"]["values"] == [0, 0, 0, 0, 0]
    assert observation.week_valid == (False,) * 4
    with pytest.raises(FrozenInstanceError):
        observation.decision_day = 7


def test_equal_numeric_public_inputs_have_equal_hashes():
    observation = public_observation()
    week = PublicWeeklyRecord(growth=-0.0, diagnosis_test_proxy=0,
                              cost=PublicCost(school_restriction_person_days=-0.0))
    equal = replace(observation, history=(week,) * 4)
    assert equal == observation
    assert hash_observation(equal) == hash_observation(observation)
    payload = public_observation_to_dict(equal)
    assert type(payload["history"][0]["growth"]) is float
    assert payload["history"][0]["growth"] == 0.0
    assert "-0.0" not in json.dumps(payload)


def test_history_rejects_future_delivery_and_requires_left_padding():
    week = PublicWeeklyRecord(start_day=0, end_day=6, delivered_diagnoses=3)
    empty = PublicWeeklyRecord()
    observation = public_observation(
        decision_day=7, history=(empty, empty, empty, week),
        week_valid=(False, False, False, True),
    )
    assert observation.history[-1].delivered_diagnoses == 3
    with pytest.raises(ValueError, match="completed"):
        replace(observation, history=(empty, empty, empty, replace(week, start_day=1, end_day=7)))
    with pytest.raises(ValueError, match="left"):
        replace(observation, history=(week, empty, empty, empty), week_valid=(True, False, False, False))
    with pytest.raises(ValueError, match="zero-filled"):
        replace(observation, history=(empty, empty, week, week))
    with pytest.raises(ValueError):
        replace(observation, legal_action_mask=(False,) * 324)
    with pytest.raises(ValueError):
        replace(observation, legal_action_mask=(1,) * 324)


def test_feedback_supports_a_closed_terminal_tail_but_not_a_future_previous_week():
    week = PublicWeeklyRecord(start_day=7, end_day=9)
    previous = PublicWeeklyRecord(start_day=0, end_day=6)
    assert PublicWeekFeedback(week, previous).week.end_day == 9
    with pytest.raises(ValueError):
        PublicWeekFeedback(week, week)
    with pytest.raises(ValueError):
        PublicWeekFeedback(PublicWeeklyRecord(start_day=0, end_day=7))


def test_counts_costs_and_private_metrics_reject_invalid_measurements():
    with pytest.raises(ValueError):
        PublicPopulation(12000, (0, 7200, 2400, 1800, 0), 8500, 1700, 900)
    with pytest.raises(ValueError):
        PublicCost(clinical_tests=True)
    with pytest.raises(ValueError):
        PublicCost(isolation_person_days=5, quarantine_person_days=3, union_person_days=9)
    with pytest.raises(ValueError):
        PublicCost(school_restriction_person_days=float("nan"))
    with pytest.raises(ValueError):
        PrivateMetrics(0, 6, -1, 30, 29, 0, 0)
    with pytest.raises(ValueError):
        PublicWeeklyRecord(growth=1, growth_valid=False)
    with pytest.raises(ValueError):
        PublicWeeklyRecord(diagnosis_test_proxy=1, proxy_valid=False)
    with pytest.raises(TypeError):
        ExecutedAction(0, 6, [0, 0, 0, 0, 0])


def test_decision_record_serializes_proposal_execution_and_optional_memory_ids():
    observation = public_observation()
    action = ActionVector((0, 0, 0, 0, 0))
    record = DecisionRecord(
        observation_hash=hash_observation(observation), decision_day=0,
        decision_time=datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc),
        controller_type="llm", action_proposal=ActionProposal(action, "保持当前组合"),
        executed_action=action, reasoning="保持当前组合",
    )
    payload = record.to_dict()
    assert payload["action_proposal"]["action"]["values"] == [0, 0, 0, 0, 0]
    assert payload["retrieved_case_ids"] == []
    assert payload["decision_time"].endswith("+00:00")
    assert payload["reasoning"] == "保持当前组合"
    fallback = replace(record, action_proposal=None, fallback_used=True,
                       fallback_reason="controller_error", reasoning=None)
    assert fallback.to_dict()["action_proposal"] is None
    assert replace(record, retrieved_case_ids=(2, 7)).to_dict()["retrieved_case_ids"] == [2, 7]
    assert replace(record, controller_type="uniform_legal_independent_rng").controller_type == "uniform_legal_independent_rng"
    with pytest.raises(ValueError):
        replace(record, decision_time=datetime(2026, 10, 13))
    with pytest.raises(ValueError):
        replace(record, fallback_used=True)
    with pytest.raises(ValueError):
        replace(record, retrieved_case_ids=(True,))
    with pytest.raises(TypeError):
        replace(record, action_proposal=PrivateMetrics(0, 0, 0, 30, 30, 0, 30))
    with pytest.raises(TypeError):
        public_observation_to_dict(record)


def test_control_import_does_not_load_future_algorithm_dependencies():
    code = (
        "import cemas.control; import sys; "
        "assert not ({'torch','gymnasium','stable_baselines3','sb3_contrib',"
        "'sentence_transformers'} & set(sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

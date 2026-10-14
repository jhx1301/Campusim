"""Delivered-only ledger, observation boundary and fixed numeric encoding tests."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import inspect
from math import log2

import numpy as np
import pytest

from cemas.control.ledger import PublicLedger, PublicLedgerAnalyzer
from cemas.control.logging import hash_observation, public_observation_to_dict
from cemas.control.observation import (
    OBSERVATION_ENCODING_VERSION, OBSERVATION_FEATURE_NAMES,
    build_observation, encode_observation,
)
from cemas.control.types import (
    ActionVector, PrivateMetrics, PublicCost, PublicDailyRecord, PublicPopulation,
    PublicResources, PublicWeeklyRecord,
)


ACTION = ActionVector((0, 0, 0, 0, 0))
RESOURCES = PublicResources(2, 5, 1)
POPULATION = PublicPopulation(100, (10, 40, 20, 20, 10), 60, 30, 10)


def daily(day, **changes):
    record = PublicDailyRecord(
        day, 1, PublicCost(2, 1, 1, 2, 3, 4, 12, 3, 2),
        ACTION, RESOURCES, 2, 3, 4,
    )
    return replace(record, **changes)


def ledger(days):
    return PublicLedger(tuple(daily(day) for day in range(days)))


def observation(records, day, **changes):
    arguments = dict(
        public_ledger=records, public_population=POPULATION, current_action=ACTION,
        resources=RESOURCES, decision_day=day, execution_days=112, initial_infections=3,
        action_duration_days=(records.action_duration_days(day, ACTION)
                              if type(records) is PublicLedger else (0,) * 5),
        legal_action_mask=(True,) * 324,
    )
    arguments.update(changes)
    return build_observation(**arguments)


def feature(observation_value, name):
    return encode_observation(observation_value)[OBSERVATION_FEATURE_NAMES.index(name)]


def test_public_daily_records_and_snapshots_are_immutable_and_detached():
    records = ledger(1)
    before = records.snapshot()
    records.append(daily(1))
    assert type(before) is tuple
    assert len(before) == 1 and len(records.snapshot()) == 2
    with pytest.raises(FrozenInstanceError):
        before[0].day = 100
    with pytest.raises(FrozenInstanceError):
        before[0].cost.clinical_tests = 200
    with pytest.raises(AttributeError):
        records.simulator = object()
    assert PublicLedger.__slots__ == ("_records",)


@pytest.mark.parametrize("record", [
    daily(1), daily(3), {"day": 0}, PrivateMetrics(0, 0, 0, 3, 3, 0, 3),
])
def test_public_ledger_rejects_gaps_untyped_records_and_private_payloads(record):
    with pytest.raises((ValueError, TypeError)):
        PublicLedger().append(record)


def test_ledger_constructor_requires_immutable_input_and_rejects_duplicate_days():
    with pytest.raises(TypeError):
        PublicLedger([daily(0)])
    records = ledger(1)
    with pytest.raises(ValueError, match="contiguous"):
        records.append(daily(0))


@pytest.mark.parametrize("start,end", [(-1, 0), (0, -1), (2, 1), (0, 7), (True, 1), (0, 1.0)])
def test_aggregation_requires_closed_one_to_seven_day_windows(start, end):
    with pytest.raises(ValueError):
        ledger(14).aggregate_week(start, end)


def test_weekly_aggregation_uses_executed_cost_and_delivered_events():
    records = ledger(14)
    first = records.aggregate_week(0, 6)
    assert first.delivered_diagnoses == 7
    assert first.cost == PublicCost(14, 7, 7, 14, 21, 28, 84, 21, 14)
    assert first.executed_action == ACTION and first.resources == RESOURCES
    assert not first.growth_valid and first.growth == 0
    assert first.proxy_valid and first.diagnosis_test_proxy == 7 / 21
    second = records.aggregate_week(7, 13)
    assert second.growth_valid and second.growth == 0


def test_growth_requires_two_complete_weeks_and_uses_delivered_diagnoses():
    records = PublicLedger(tuple(daily(day, delivered_diagnoses=1 if day < 7 else 2)
                                 for day in range(17)))
    assert records.aggregate_week(7, 13).growth == pytest.approx(log2(15 / 8))
    partial = records.aggregate_week(14, 16)
    assert not partial.growth_valid and partial.growth == 0
    feedback = records.feedback(14, 16)
    assert feedback.week == partial and feedback.previous_week.start_day == 7
    assert records.feedback(0, 6).previous_week is None


def test_proxy_keeps_report_time_misalignment_and_zero_test_validity():
    records = PublicLedger(tuple(daily(day, delivered_diagnoses=5,
                                      cost=replace(daily(day).cost, clinical_tests=1, screening_tests=0))
                                 for day in range(7)))
    week = records.aggregate_week(0, 6)
    assert week.diagnosis_test_proxy == 5
    no_tests = PublicLedger(tuple(replace(record,
                                         cost=replace(record.cost, clinical_tests=0, screening_tests=0))
                                 for record in records.snapshot()))
    assert no_tests.aggregate_week(0, 6).diagnosis_test_proxy == 0
    assert not no_tests.aggregate_week(0, 6).proxy_valid


@pytest.mark.parametrize("change", [
    {"executed_action": ActionVector((1, 0, 0, 0, 0))},
    {"resources": PublicResources(2, 2, 1)},
])
def test_mixed_week_does_not_silently_discard_action_or_resource_changes(change):
    records = PublicLedger(tuple(daily(day, **change) if day == 6 else daily(day)
                                 for day in range(7)))
    with pytest.raises(ValueError, match="mix"):
        records.aggregate_week(0, 6)
    with pytest.raises(ValueError, match="mix"):
        observation(records, 7)


@pytest.mark.parametrize("day,valid,starts", [
    (0, (False, False, False, False), []),
    (7, (False, False, False, True), [0]),
    (28, (True, True, True, True), [0, 7, 14, 21]),
    (35, (True, True, True, True), [7, 14, 21, 28]),
    (37, (True, True, True, True), [7, 14, 21, 28]),
])
def test_observation_has_four_complete_day_zero_anchored_weeks(day, valid, starts):
    value = observation(ledger(day), day)
    assert value.week_valid == valid
    assert [week.start_day for week, present in zip(value.history, valid) if present] == starts
    assert all(week == PublicWeeklyRecord()
               for week, present in zip(value.history, valid) if not present)
    assert value.previous_day_known_union == (4 if day else 0)
    assert value.action_duration_days == (day,) * 5


def test_incomplete_public_day_is_an_error_even_before_first_complete_week():
    with pytest.raises(ValueError, match="completed public records"):
        observation(ledger(5), 6)
    with pytest.raises(ValueError, match="completed public records"):
        ledger(6).aggregate_week(0, 6)


def test_duration_tracks_each_actual_level_and_ignores_future_execution():
    changed = ActionVector((1, 0, 0, 1, 0))
    records = PublicLedger(tuple(daily(day, executed_action=changed if day >= 3 else ACTION)
                                 for day in range(12)))
    assert records.action_duration_days(7, changed) == (4, 7, 7, 4, 7)
    assert records.action_duration_days(0, changed) == (0,) * 5


def test_future_delivered_records_cannot_change_observation_hash_or_encoding():
    past = ledger(7)
    future = PublicLedger(past.snapshot())
    for day in range(7, 21):
        future.append(daily(day, delivered_diagnoses=999,
                            resources=PublicResources(1, 0, 0),
                            executed_action=ActionVector((2, 3, 2, 2, 2))))
    before, after = observation(past, 7), observation(future, 7)
    assert before == after
    assert hash_observation(before) == hash_observation(after)
    assert np.array_equal(encode_observation(before), encode_observation(after))


def test_public_builder_and_encoder_offer_no_simulator_or_private_input():
    assert set(inspect.signature(build_observation).parameters) == {
        "public_ledger", "public_population", "current_action", "resources", "decision_day",
        "execution_days", "initial_infections", "action_duration_days", "legal_action_mask",
    }
    private = PrivateMetrics(0, 6, 99, 3, 102, 77, 88)
    with pytest.raises(TypeError):
        observation(private, 7, action_duration_days=(7,) * 5)
    with pytest.raises(TypeError):
        encode_observation(private)
    value = observation(ledger(7), 7)
    before = encode_observation(value).copy()
    hidden_world = {"private": private, "beta": 0.01, "future_queue": [10], "world_seed": 11}
    hidden_world.update(private=replace(private, new_infections=999), beta=0.99,
                        future_queue=[100, 101], world_seed=99, infection_log=[1, 2, 3])
    rebuilt = observation(PublicLedger(ledger(7).snapshot()), 7)
    assert public_observation_to_dict(value) == public_observation_to_dict(rebuilt)
    assert hash_observation(value) == hash_observation(rebuilt)
    assert np.array_equal(before, encode_observation(rebuilt))


def test_numeric_encoding_has_frozen_names_dtype_and_separate_mask():
    value = observation(ledger(7), 7)
    encoded = encode_observation(value)
    assert OBSERVATION_ENCODING_VERSION == "cemas-public-observation-float32-v1"
    assert len(OBSERVATION_FEATURE_NAMES) == len(set(OBSERVATION_FEATURE_NAMES)) == 198
    assert encoded.shape == (198,) and encoded.dtype == np.float32
    assert np.isfinite(encoded).all()
    altered_mask = replace(value, legal_action_mask=(True,) + (False,) * 323)
    assert np.array_equal(encoded, encode_observation(altered_mask))
    assert hash_observation(value) != hash_observation(altered_mask)
    assert OBSERVATION_FEATURE_NAMES[0] == "context.decision_day_over_horizon"
    assert OBSERVATION_FEATURE_NAMES[-1] == "history.3.week_valid"


def test_invalid_week_entire_feature_block_is_zero_including_action_and_targets():
    zero = encode_observation(observation(ledger(0), 0))
    assert np.array_equal(zero[42:], np.zeros(156, dtype=np.float32))
    one_week = encode_observation(observation(ledger(7), 7))
    assert np.array_equal(one_week[42:159], np.zeros(117, dtype=np.float32))
    assert one_week[-1] == 1


def test_numeric_features_use_protocol_fixed_scales_and_one_hot_order():
    current = ActionVector((2, 3, 1, 0, 2))
    value = observation(ledger(14), 14, current_action=current,
                        action_duration_days=(0, 0, 0, 14, 0))
    assert feature(value, "context.decision_day_over_horizon") == pytest.approx(14 / 112)
    assert feature(value, "context.execution_days") == 112
    assert feature(value, "context.population") == 100
    assert feature(value, "context.initial_infections_over_population") == pytest.approx(0.03)
    assert feature(value, "context.age_band_1_over_population") == pytest.approx(0.4)
    assert feature(value, "context.action_duration.E_over_horizon") == pytest.approx(14 / 112)
    for dimension, selected in zip(("T", "S", "C", "E", "A"), current.values):
        names = [name for name in OBSERVATION_FEATURE_NAMES if name.startswith(f"context.action.{dimension}.")]
        assert sum(feature(value, name) for name in names) == 1
        assert feature(value, f"context.action.{dimension}.{selected}") == 1
    assert feature(value, "history.3.delivered_diagnoses_over_population") == pytest.approx(0.07)
    assert feature(value, "history.3.clinical_tests_over_7_population") == pytest.approx(0.02)
    assert feature(value, "history.3.school_restriction_person_days_over_7_school_population") == pytest.approx(0.2)
    assert feature(value, "history.3.proxy_valid") == 1
    assert feature(value, "history.3.growth_valid") == 1
    assert feature(value, "history.2.growth_valid") == 0


def test_no_target_populations_encode_zero_activity_and_explicit_validity():
    no_targets = PublicPopulation(100, POPULATION.age_band_counts, 0, 0)
    value = observation(ledger(7), 7, public_population=no_targets)
    assert feature(value, "context.school_target_valid") == 0
    assert feature(value, "context.work_target_valid") == 0
    assert feature(value, "history.3.school_target_valid") == 0
    assert feature(value, "history.3.work_target_valid") == 0
    assert feature(value, "history.3.community_target_valid") == 1
    assert feature(value, "history.3.school_restriction_person_days_over_7_school_population") == 0
    assert feature(value, "history.3.work_restriction_person_days_over_7_work_population") == 0


def test_counts_and_proxy_larger_than_population_are_not_clipped():
    records = PublicLedger(tuple(daily(day, delivered_diagnoses=200,
                                      cost=replace(daily(day).cost, clinical_tests=300, screening_tests=0,
                                                   delivered_notifications=400))
                                 for day in range(7)))
    value = observation(records, 7)
    assert feature(value, "history.3.delivered_diagnoses_over_population") == 14
    assert feature(value, "history.3.clinical_tests_over_7_population") == 3
    assert feature(value, "history.3.delivered_notifications_over_7_population") == 4


class FakeExecutor:
    label = "fake-joint-executor"

    def finish_day(self, sim):
        return daily(sim.day)


class FakeSim(dict):
    day = 0


def test_analyzer_binds_simulator_executor_and_resets_ledger_on_reinitialize():
    original = FakeExecutor()
    actual = deepcopy(original)
    analyzer = PublicLedgerAnalyzer(original)
    sim = FakeSim(interventions=[actual])
    analyzer.initialize(sim)
    assert analyzer._executor is actual
    analyzer.apply(sim)
    sim.day = 1
    analyzer.apply(sim)
    assert len(analyzer.ledger.snapshot()) == 2
    analyzer.initialize(sim)
    assert analyzer.ledger.snapshot() == ()
    assert analyzer.initialized and not analyzer.finalized


def test_analyzer_rejects_missing_duplicate_or_uninitialized_executor():
    executor = FakeExecutor()
    analyzer = PublicLedgerAnalyzer(executor)
    with pytest.raises(RuntimeError):
        analyzer.apply(FakeSim(interventions=[executor]))
    for interventions in ([], [executor, deepcopy(executor)]):
        with pytest.raises(ValueError, match="exactly one"):
            analyzer.initialize(FakeSim(interventions=interventions))
    with pytest.raises(TypeError):
        PublicLedgerAnalyzer(object())

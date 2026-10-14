"""Public-only observation construction and a stable, fixed-scale numeric encoding."""

from __future__ import annotations

from math import log2

import numpy as np

from .ledger import PublicLedger
from .types import (
    ACTION_ORDER, ACTION_SIZES, HISTORY_WEEKS, ActionVector, PublicObservation,
    PublicPopulation, PublicResources, PublicWeeklyRecord,
)


OBSERVATION_ENCODING_VERSION = "cemas-public-observation-float32-v1"
_ACTION_FEATURES = tuple(f"action.{name}.{level}"
                         for name, size in zip(ACTION_ORDER, ACTION_SIZES)
                         for level in range(size))
_CONTEXT_FEATURES = (
    "decision_day_over_horizon", "execution_days", "initial_infections_over_population",
    "population", *(f"age_band_{index}_over_population" for index in range(5)),
    "school_population_over_population", "work_population_over_population",
    "school_work_population_over_population", "school_target_valid", "work_target_valid",
    "community_target_valid", *_ACTION_FEATURES,
    *(f"action_duration.{name}_over_horizon" for name in ACTION_ORDER),
    "clinical_daily_capacity_over_population", "screening_daily_capacity_over_population",
    "tracing_daily_index_capacity_over_population", "previous_day_known_isolated_over_population",
    "previous_day_known_quarantined_over_population", "previous_day_known_union_over_population",
)
_WEEK_FEATURES = (
    "start_day_over_horizon", "end_day_over_horizon", "delivered_diagnoses_over_population",
    "clinical_tests_over_7_population", "screening_tests_over_7_population",
    "delivered_notifications_over_7_population", "isolation_person_days_over_7_population",
    "quarantine_person_days_over_7_population", "union_person_days_over_7_population",
    "school_restriction_person_days_over_7_school_population",
    "work_restriction_person_days_over_7_work_population",
    "community_restriction_person_days_over_7_population", *_ACTION_FEATURES,
    "clinical_daily_capacity_over_population", "screening_daily_capacity_over_population",
    "tracing_daily_index_capacity_over_population", "growth_over_log2_population_plus_1",
    "growth_valid", "diagnosis_test_proxy", "proxy_valid", "school_target_valid",
    "work_target_valid", "community_target_valid", "week_valid",
)
OBSERVATION_FEATURE_NAMES = (
    *(f"context.{name}" for name in _CONTEXT_FEATURES),
    *(f"history.{index}.{name}" for index in range(HISTORY_WEEKS) for name in _WEEK_FEATURES),
)


def build_observation(
    public_ledger: PublicLedger,
    public_population: PublicPopulation,
    current_action: ActionVector,
    resources: PublicResources,
    decision_day: int,
    *,
    execution_days: int,
    initial_infections: int,
    action_duration_days: tuple[int, int, int, int, int],
    legal_action_mask: tuple[bool, ...],
) -> PublicObservation:
    """Read only completed public days; future records are not part of the snapshot."""
    if type(public_ledger) is not PublicLedger:
        raise TypeError("public_ledger must be PublicLedger")
    history, week_valid = public_ledger.full_history(decision_day)
    previous = public_ledger.snapshot()[decision_day - 1] if decision_day else None
    return PublicObservation(
        decision_day=decision_day, execution_days=execution_days,
        initial_infections=initial_infections, population=public_population,
        resources=resources, current_action=current_action,
        action_duration_days=action_duration_days, legal_action_mask=legal_action_mask,
        history=history, week_valid=week_valid,
        previous_day_known_isolated=previous.known_isolated if previous else 0,
        previous_day_known_quarantined=previous.known_quarantined if previous else 0,
        previous_day_known_union=previous.known_union if previous else 0,
    )


def _one_hot(action: ActionVector) -> tuple[int, ...]:
    return tuple(int(level == selected)
                 for selected, size in zip(action.values, ACTION_SIZES)
                 for level in range(size))


def _resource_features(resources: PublicResources, population: int) -> tuple[float, ...]:
    return (resources.clinical_daily_capacity / population,
            resources.screening_daily_capacity / population,
            resources.tracing_daily_index_capacity / population)


def _week_features(week: PublicWeeklyRecord, population: PublicPopulation,
                   horizon: int) -> tuple[float, ...]:
    n = population.population
    school, work = population.school_population, population.work_population
    cost = week.cost
    return (
        week.start_day / horizon, week.end_day / horizon, week.delivered_diagnoses / n,
        cost.clinical_tests / (7 * n), cost.screening_tests / (7 * n),
        cost.delivered_notifications / (7 * n), cost.isolation_person_days / (7 * n),
        cost.quarantine_person_days / (7 * n), cost.union_person_days / (7 * n),
        cost.school_restriction_person_days / (7 * school) if school else 0.0,
        cost.work_restriction_person_days / (7 * work) if work else 0.0,
        cost.community_restriction_person_days / (7 * n), *_one_hot(week.executed_action),
        *_resource_features(week.resources, n), week.growth / log2(n + 1),
        float(week.growth_valid), week.diagnosis_test_proxy, float(week.proxy_valid),
        float(school > 0), float(work > 0), 1.0, 1.0,
    )


def encode_observation(observation: PublicObservation) -> np.ndarray:
    """Return the v1 ordered float32 vector; the action mask remains a separate input.

    The announced horizon and registered population are included as raw public
    task constants. Counts, capacities and activity burdens use only fixed task
    scales; no clipping or data-fitted normalization occurs.
    """
    if type(observation) is not PublicObservation:
        raise TypeError("observation must be PublicObservation")
    population = observation.population
    n, horizon = population.population, observation.execution_days
    features = [
        observation.decision_day / horizon, horizon, observation.initial_infections / n, n,
        *(value / n for value in population.age_band_counts),
        population.school_population / n, population.work_population / n,
        population.school_work_population / n, float(population.school_population > 0),
        float(population.work_population > 0), 1.0, *_one_hot(observation.current_action),
        *(value / horizon for value in observation.action_duration_days),
        *_resource_features(observation.resources, n),
        observation.previous_day_known_isolated / n,
        observation.previous_day_known_quarantined / n,
        observation.previous_day_known_union / n,
    ]
    for week, valid in zip(observation.history, observation.week_valid):
        features.extend(_week_features(week, population, horizon)
                        if valid else (0.0,) * len(_WEEK_FEATURES))
    result = np.asarray(features, dtype=np.float32)
    if not np.isfinite(result).all():
        raise ValueError("public measurements must fit finite float32 features")
    return result

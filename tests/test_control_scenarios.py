"""Fixed registration and simulator construction boundaries."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import covasim as cv
import numpy as np
import pytest

from cemas.control.protocol import load_protocol
from cemas.control.scenarios import build_population_registry, build_scenario


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_PATH)


def registered_people():
    return SimpleNamespace(
        age=np.array([16.9, 17.1, 24.9, 31.9, 61.3, 99.9]),
        class_groups_ug=[dict(students=np.array([0, 1]), teachers=np.array([2]))],
        class_groups_gr=[dict(students=np.array([1]), teachers=np.array([2]))],
        lab_groups=[dict(students=np.array([1]), teachers=np.array([3]))],
    )


def test_persistent_rosters_partition_population_and_fix_nominal_budgets(protocol):
    people = registered_people()
    registry = build_population_registry(people, activity_config=protocol.definition["activity"])
    assert registry.school_indices == (0, 1, 2)
    assert registry.work_indices == (1, 3)
    assert registry.screening_groups == ((0, 1, 2), (3,), (4, 5))
    assert registry.public_population.age_band_counts == (1, 1, 1, 1, 2)
    assert registry.public_population.school_work_population == 1
    np.testing.assert_allclose(registry.school_weights, [.8, .4, .8, 0, 0, 0])
    np.testing.assert_allclose(registry.work_weights, [0, .4, 0, .8, 0, 0])
    np.testing.assert_allclose(registry.community_weights, [.2, .2, .2, .2, 1, 1])
    np.testing.assert_allclose(
        registry.school_weights + registry.work_weights + registry.community_weights, 1,
    )
    # The registry keeps its reset-time membership even if live groups later change.
    people.class_groups_ug.clear()
    assert registry.school_indices == (0, 1, 2)
    with pytest.raises(FrozenInstanceError):
        registry.school_indices = ()
    with pytest.raises(ValueError):
        registry.school_weights[0] = 0
    with pytest.raises(TypeError):
        registry.layer_groups["school"] = ()


def test_registry_uses_configured_budgets_for_all_membership_groups(protocol):
    activity = dict(protocol.definition["activity"])
    activity.update(daily_budget_school_or_work=.6, daily_budget_community=.4,
                    dual_school_work_each=.3, neither_school_nor_work_community=1)
    registry = build_population_registry(registered_people(), activity_config=activity)
    np.testing.assert_array_equal(registry.school_weights, [.6, .3, .6, 0, 0, 0])
    np.testing.assert_array_equal(registry.work_weights, [0, .3, 0, .6, 0, 0])
    np.testing.assert_array_equal(registry.community_weights, [.4, .4, .4, .4, 1, 1])


ACTIVITY_BUDGET_KEYS = (
    "daily_budget_school_or_work", "daily_budget_community", "dual_school_work_each",
    "neither_school_nor_work_community",
)


@pytest.mark.parametrize("key", ACTIVITY_BUDGET_KEYS)
def test_registry_requires_each_activity_budget(protocol, key):
    activity = dict(protocol.definition["activity"])
    del activity[key]
    with pytest.raises(ValueError, match="activity"):
        build_population_registry(registered_people(), activity_config=activity)


@pytest.mark.parametrize("activity", [None, [], "activity"])
def test_registry_rejects_nonmapping_activity(activity):
    with pytest.raises(ValueError, match="activity"):
        build_population_registry(registered_people(), activity_config=activity)


@pytest.mark.parametrize("key", ACTIVITY_BUDGET_KEYS)
@pytest.mark.parametrize("value", [True, "0.2", -.1, 1.1, float("nan"), float("inf")])
def test_registry_rejects_invalid_activity_budget_values(protocol, key, value):
    activity = dict(protocol.definition["activity"])
    activity[key] = value
    with pytest.raises(ValueError, match="activity"):
        build_population_registry(registered_people(), activity_config=activity)


@pytest.mark.parametrize("key,value", [
    ("daily_budget_school_or_work", .7), ("dual_school_work_each", .35),
    ("neither_school_nor_work_community", .9),
    ("daily_budget_school_or_work", .8 + 5e-10),
    ("dual_school_work_each", .4 + 5e-10),
    ("neither_school_nor_work_community", 1 - 5e-10),
])
def test_registry_rejects_activity_budgets_that_do_not_conserve_one_day(protocol, key, value):
    activity = dict(protocol.definition["activity"])
    activity[key] = value
    with pytest.raises(ValueError, match="activity"):
        build_population_registry(registered_people(), activity_config=activity)


def test_registry_preserves_activity_budgets_within_absolute_sum_tolerance(protocol):
    activity = dict(protocol.definition["activity"])
    activity["daily_budget_school_or_work"] += 5e-13
    registry = build_population_registry(registered_people(), activity_config=activity)
    assert registry.school_weights[0] == activity["daily_budget_school_or_work"]
    assert registry.community_weights[0] == activity["daily_budget_community"]
    assert registry.school_weights[0] + registry.community_weights[0] > 1


@pytest.mark.parametrize("bad_age", [-1, 100, float("nan"), float("inf")])
def test_registry_rejects_unrepresentable_ages(protocol, bad_age):
    people = registered_people()
    people.age[0] = bad_age
    with pytest.raises(ValueError):
        build_population_registry(people, activity_config=protocol.definition["activity"])


def test_registry_requires_rosters_and_valid_indices(protocol):
    with pytest.raises(ValueError):
        build_population_registry(SimpleNamespace(age=np.array([20.])),
                                  activity_config=protocol.definition["activity"])
    people = registered_people()
    people.lab_groups[0]["teachers"] = np.array([6])
    with pytest.raises(ValueError):
        build_population_registry(people, activity_config=protocol.definition["activity"])


def assert_same_nested(actual, expected):
    if isinstance(actual, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(actual, dict):
        assert actual.keys() == expected.keys()
        for key in actual:
            assert_same_nested(actual[key], expected[key])
    elif isinstance(actual, (list, tuple)):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_same_nested(left, right)
    else:
        assert actual == expected


def test_registration_metadata_preserves_contacts_and_random_draws():
    ages = np.concatenate((np.full(120, 20.), np.full(50, 27.), np.full(70, 45.)))
    sexes = np.arange(len(ages)) % 2
    arguments = dict(pop_size=len(ages), ages=ages, sexes=sexes, contacts={})
    cv.set_seed(90001)
    legacy = cv.make_campus_contacts(**arguments)
    legacy_next_draw = np.random.random(5)
    cv.set_seed(90001)
    metadata = {}
    with_metadata = cv.make_campus_contacts(**arguments, registry_metadata=metadata)
    next_draw = np.random.random(5)
    assert len(legacy) == len(with_metadata) == 6
    assert_same_nested(with_metadata, legacy)
    np.testing.assert_array_equal(next_draw, legacy_next_draw)
    assert set(metadata) == {"student_indices", "teacher_indices", "staff_indices"}
    assert len(metadata["student_indices"]) == 170
    assert len(metadata["teacher_indices"]) == round(len(ages) * .08)
    assert len(metadata["staff_indices"]) == round(len(ages) * .12)
    assert set(metadata["teacher_indices"]).isdisjoint(metadata["staff_indices"])


def test_scene_defaults_are_explicit_smoke_and_adapters_are_mounted(protocol):
    bundle = build_scenario(protocol, 90001, population=300, execution_days=7,
                            initial_infections=6)
    assert bundle.sim.initialized and bundle.sim.t == 0
    assert bundle.sim["pop_type"] == "campus"
    assert bundle.sim.npts == 7
    assert bundle.sim["pop_scale"] == 1 and bundle.sim["rescale"] is False
    assert bundle.sim["use_waning"] is False
    assert bundle.private_metadata["purpose"] == "smoke"
    assert bundle.private_metadata["beta_provenance"] == "protocol_smoke_beta"
    assert bundle.private_metadata["calibration_verified"] is False
    assert bundle.private_metadata["protocol_sha256"] == protocol.source_sha256
    assert bundle.executor is bundle.sim["interventions"][0]
    assert bundle.public_analyzer is bundle.sim["analyzers"][0]
    assert bundle.private_analyzer is bundle.sim["analyzers"][1]
    assert bundle.executor.resources.clinical_daily_capacity == 6
    assert bundle.executor.resources.screening_daily_capacity == 15
    assert bundle.executor.resources.tracing_daily_index_capacity == 3
    assert bundle.registry.public_population.population == 300
    # Population generation caps the configured staff target by the remaining
    # non-student/non-teacher pool; metadata exposes the actual draw.
    assert len(bundle.private_metadata["registration"]["staff_indices"]) <= 36
    assert not hasattr(bundle.registry.public_population, "staff_indices")
    assert bundle.sim["iso_factor"] == dict(d=.3, clu=.1, clg=.1, of=.1, ta=.2, cm=.1)
    assert bundle.sim["quar_factor"] == dict(d=.6, clu=.2, clg=.2, of=.2, ta=.4, cm=.2)


def test_capacity_rounding_matches_discrete_screening_requests(protocol):
    bundle = build_scenario(protocol, 90002, population=101, execution_days=2,
                            initial_infections=0, screening_capacity_ratio=.07)
    resources = bundle.executor.resources
    assert resources.clinical_daily_capacity == 3
    assert resources.screening_daily_capacity == 8
    assert resources.tracing_daily_index_capacity == 2


def test_scientific_scene_requires_explicit_beta_and_keeps_provenance(protocol):
    with pytest.raises(ValueError, match="explicit calibration beta"):
        build_scenario(protocol, 90001, purpose="scientific")
    bundle = build_scenario(protocol, 90001, population=100, execution_days=2,
                            initial_infections=1, beta=.012, purpose="scientific")
    assert bundle.sim["beta"] == .012
    assert bundle.private_metadata["beta_provenance"] == "caller_explicit_beta"
    # The builder does not assert that the caller's artifact has been verified.
    assert bundle.private_metadata["calibration_verified"] is False


@pytest.mark.parametrize("overrides", [
    {"population": True}, {"population": 0}, {"execution_days": 1},
    {"initial_infections": -1}, {"population": 4, "initial_infections": 5},
    {"beta": float("nan")}, {"beta": True}, {"screening_capacity_ratio": -1},
    {"screening_capacity_ratio": float("inf")}, {"purpose": "experiment"},
])
def test_scene_rejects_invalid_overrides(protocol, overrides):
    with pytest.raises(ValueError):
        build_scenario(protocol, 90001, **overrides)


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.5])
def test_scene_rejects_noninteger_or_out_of_range_world_seeds(protocol, seed):
    with pytest.raises(ValueError):
        build_scenario(protocol, seed)

"""Historical replay intervention boundaries and E0 compatibility."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from cemas.e0.data import load_e0_config, load_e0_data
from cemas.e0.simulation import run_e0_world
from cemas.replay.simulation import (HistoricalMeasures, population_assignment_hash,
                                     run_replay_world, schedule_multipliers)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("day,expected", [
    ("2020-09-06", (1, 1, 1)),
    ("2020-09-07", (.2, 1, 1)),
    ("2020-09-09", (.2, 1, 1)),
    ("2020-09-10", (.2, 0, 1.15)),
    ("2020-09-25", (.2, 0, 1.15)),
    ("2020-09-26", (.5, .5, 1)),
])
def test_schedule_boundary_dates(day, expected):
    multipliers = schedule_multipliers(day)
    assert (multipliers["cm"], multipliers["clu"], multipliers["d"]) == expected
    assert multipliers["clg"] == multipliers["clu"]


class FakeSim(dict):
    pass


@pytest.mark.parametrize("h", [1.0, 1.15, 1.25])
def test_edge_scope_daily_regeneration_and_exact_dorm_restoration(h):
    sim = FakeSim(start_day="2020-08-17", dynam_layer={"cm": 1, "d": 0},
                  beta_layer={"clu": 1.3, "clg": 0.8, "of": 0.9, "ta": 1.2})
    sim.n = 5
    layer = {"p1": np.array([0, 0, 2, 3]), "p2": np.array([1, 2, 3, 4]),
             "beta": np.array([0.7, 1.0, 1.3, 1.8])}
    sim.people = SimpleNamespace(student_level=np.array([0, 0, 1, 2, 2]),
                                 campus_registry_metadata={
                                     "student_indices": np.array([0, 1]),
                                     "teacher_indices": np.array([2]),
                                     "staff_indices": np.array([3, 4])},
                                 contacts={"d": deepcopy(layer), "cm": deepcopy(layer)})
    dorm = sim.people.contacts["d"]
    measures = HistoricalMeasures(h=h)
    measures.initialize(sim)
    initial_rng = np.random.get_state()
    for day in ("2020-09-06", "2020-09-07", "2020-09-09", "2020-09-10",
                "2020-09-11", "2020-09-25", "2020-09-26", "2020-09-27"):
        sim.t = (date.fromisoformat(day) - date(2020, 8, 17)).days
        cm = sim.people.contacts["cm"]
        # Simulate the actual cm Layer.update(): new endpoints, all betas one.
        cm["p1"] = np.array([0, 0, 2, 3]) if sim.t % 2 else np.array([2, 0, 2, 0])
        cm["p2"] = np.array([1, 2, 3, 4])
        cm["beta"] = np.ones(4)
        measures.apply(sim)
        expected = schedule_multipliers(day, h=h)
        cm_mask = (sim.people.student_level[cm["p1"]] == 0) | (sim.people.student_level[cm["p2"]] == 0)
        assert np.array_equal(cm["beta"][cm_mask], np.full(cm_mask.sum(), expected["cm"]))
        assert np.array_equal(cm["beta"][~cm_mask], np.ones((~cm_mask).sum()))
        assert np.array_equal(dorm["beta"][:2], layer["beta"][:2] * expected["d"])
        assert np.array_equal(dorm["beta"][2:], layer["beta"][2:])
        assert sim["beta_layer"]["clu"] == 1.3 * expected["clu"]
        assert sim["beta_layer"]["clg"] == .8 * expected["clg"]
        assert sim["beta_layer"]["of"] == .9
        assert sim["beta_layer"]["ta"] == 1.2
        # An accidental duplicate invocation must not multiply twice.
        before = cm["beta"].copy()
        measures.apply(sim)
        assert np.array_equal(before, cm["beta"])
        assert np.array_equal(dorm["p1"], layer["p1"])
        assert np.array_equal(dorm["p2"], layer["p2"])
    assert measures.audit(sim)["dorm_weights_restored"]
    after_rng = np.random.get_state()
    assert initial_rng[0] == after_rng[0]
    assert np.array_equal(initial_rng[1], after_rng[1])
    assert initial_rng[2:] == after_rng[2:]


def _small_input():
    config = load_e0_config(ROOT / "docs/e0_protocol_v2.json")
    data = load_e0_data(config)
    config = dict(config, population=500, initial_infections=2,
                  target_groups={"students": 400, "employees": 100},
                  target_roles={"undergraduate_students": 330, "non_undergraduate_students": 70,
                                "teachers": 10, "staff": 90},
                  engine_overrides={
                      "campus_age_data": [[17, 23, .66], [24, 30, .14], [31, 65, .20]],
                      "campus_age_counts": [330, 70, 100],
                      "campus_teacher_ratio": .02, "campus_staff_ratio": .18},
                  config_sha256="0" * 64)
    w1 = {"dates": list(data["dates"]), "groups": {
        "students": {"positive": list(data["groups"]["students"]["positive"]), "tests": [100] * 21},
        "employees": {"positive": list(data["groups"]["employees"]["positive"]), "tests": [20] * 21}}}
    long = {"dates": [(date(2020, 8, 17) + timedelta(days=i)).isoformat() for i in range(75)],
            "groups": {group: {field: list(values) + [500 if field == "tests" else 0] * 54
                                for field, values in fields.items()}
                       for group, fields in w1["groups"].items()}}
    return config, w1, long


def test_long_world_preserves_w1_daily_e0_behavior_and_frozen_weights(monkeypatch):
    import covasim as cv

    original = cv.Sim
    instances = []

    def capture_sim(*args, **kwargs):
        sim = original(*args, **kwargs)
        instances.append(sim)
        return sim

    monkeypatch.setattr(cv, "Sim", capture_sim)
    config, w1, long = _small_input()
    baseline = run_e0_world(config, w1, .056666666665, 12201)
    world = run_replay_world(config, long, .056666666665, 12201, w1_data=w1)
    for result in (baseline, world):
        assert result["campus_background"] == {"employee_cm": .1, "employee_ta": .5}
        assert result["resolved_parameters"]["beta_layer"]["ta"] == pytest.approx(.6)
    for sim in instances:
        assert sim["beta_layer"]["ta"] == pytest.approx(.6)
    # The recorded resolved background must not become the final historical policy.
    assert world["resolved_parameters"]["beta_layer"] == baseline["resolved_parameters"]["beta_layer"]
    assert world["roles"] == baseline["roles"]
    assert world["group_test_weights"] == baseline["group_test_weights"]
    assert world["requested_tests"][:21] == baseline["requested_tests"]
    for group in ("students", "employees"):
        for field in ("positive", "tests"):
            assert world["groups"][group][field][:21] == baseline["groups"][group][field]
    assert len(world["dates"]) == 75
    assert world["replay"]["dorm_weights_restored"]
    assert world["replay"]["dorm_topology_initial_sha256"] == world["replay"]["dorm_topology_final_sha256"]
    assert world["replay"]["population_assignment_sha256"] == population_assignment_hash(instances[0].people)
    assert np.array_equal(instances[0].people.student_level, instances[1].people.student_level)
    for key in ("student_indices", "teacher_indices", "staff_indices"):
        assert np.array_equal(instances[0].people.campus_registry_metadata[key],
                              instances[1].people.campus_registry_metadata[key])


def test_replay_rejects_mismatched_w1_weights_and_incomplete_series():
    config, w1, long = _small_input()
    changed = deepcopy(w1)
    changed["groups"]["students"]["tests"][0] += 1
    with pytest.raises(ValueError, match="Frozen W1"):
        run_replay_world(config, long, .02, 1, w1_data=changed)
    long["groups"]["students"]["tests"].pop()
    with pytest.raises(ValueError, match="per day"):
        run_replay_world(config, long, .02, 1)

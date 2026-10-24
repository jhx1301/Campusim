"""Run one UW E0 world without the control executor.

The world installs the observed daily test schedule and a role-weighted test
subtarget.  It records aggregate positives/tests plus the same quantities split
between students and the remaining campus population, which is the diagnostic
group split used by the E0 study.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import numpy as np

from ..control.protocol import load_protocol
from ..control.scenarios import resolve_campus_parameters

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("students", "employees")


@lru_cache(maxsize=4)
def _protocol(path):
    return load_protocol(path)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _role_test_analyzer(cv):
    """Build a read-only analyzer that counts actual tests by role."""

    class RoleTestAnalyzer(cv.Analyzer):
        def __init__(self):
            super().__init__(label="e0-role-tests")
            self.students = None
            self.employees = None
            self.student_tests = []
            self.employee_tests = []

        def initialize(self, sim=None):
            super().initialize(sim)
            metadata = sim.people.campus_registry_metadata
            self.students = np.asarray(metadata["student_indices"], dtype=np.int64)
            self.employees = np.setdiff1d(np.arange(sim.n, dtype=np.int64), self.students)

        def apply(self, sim):
            tested = sim.people.date_tested == sim.t
            self.student_tests.append(int(np.count_nonzero(tested[self.students])))
            self.employee_tests.append(int(np.count_nonzero(tested[self.employees])))

    return RoleTestAnalyzer()


def _group_weights(config, data):
    student_tests = float(sum(data["groups"]["students"]["tests"]))
    employee_tests = float(sum(data["groups"]["employees"]["tests"]))
    total_tests = student_tests + employee_tests
    if total_tests <= 0:
        raise ValueError("E0 data require a positive total test count")
    population = float(config["population"])
    student_share = float(config["target_groups"]["students"]) / population
    employee_share = float(config["target_groups"]["employees"]) / population
    if student_share <= 0 or employee_share <= 0:
        raise ValueError("E0 target groups must be positive")
    return {
        "students": (student_tests / total_tests) / student_share,
        "employees": (employee_tests / total_tests) / employee_share,
    }


def _subtarget_factory(weights):
    state = {"vals": None}

    def subtarget(sim):
        if state["vals"] is None:
            students = np.asarray(sim.people.campus_registry_metadata["student_indices"],
                                  dtype=np.int64)
            values = np.full(sim.n, weights["employees"], dtype=float)
            values[students] = weights["students"]
            state["vals"] = values
        return {"inds": np.arange(sim.n, dtype=np.int64), "vals": state["vals"]}

    return subtarget


def run_e0_world(config, data, beta, seed, *, initial_infections=None, symp_test=None):
    """Return one simulated daily series; no fitted quantity is read back."""
    if isinstance(beta, bool) or not isinstance(beta, (int, float)) or not np.isfinite(beta) or beta <= 0:
        raise ValueError("beta must be a finite positive number")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if len(data["dates"]) != config["window_days"]:
        raise ValueError("E0 data length does not match config.window")

    import covasim as cv

    protocol = _protocol(config["base_protocol_path"])
    initial = config["initial_infections"] if initial_infections is None else initial_infections
    symp = config["testing"]["symp_test"] if symp_test is None else symp_test
    if type(initial) is not int or initial < 0:
        raise ValueError("initial_infections must be a nonnegative integer")
    if isinstance(symp, bool) or not isinstance(symp, (int, float)) or symp <= 0:
        raise ValueError("symp_test must be positive")

    testing = dict(config["testing"])
    testing["symp_test"] = symp
    if testing["test_delay"] != 0:
        raise ValueError("E0 group diagnoses require test_delay=0")

    days = len(data["dates"])
    pars = resolve_campus_parameters(protocol, seed, beta=float(beta),
                                     population=config["population"],
                                     initial_infections=initial,
                                     execution_days=days)
    pars.update(config["engine_overrides"])
    pars["start_day"] = data["dates"][0]

    tests = [int(a) + int(b) for a, b in zip(data["groups"]["students"]["tests"],
                                              data["groups"]["employees"]["tests"])]
    if len(tests) != days:
        raise ValueError("E0 daily tests do not match the window")
    weights = _group_weights(config, data)
    analyzer = _role_test_analyzer(cv)
    intervention = cv.test_num(daily_tests=tests, subtarget=_subtarget_factory(weights), **testing)
    sim = cv.Sim(pars=pars, interventions=[intervention], analyzers=[analyzer])
    sim.initialize()
    if sim.npts != days:
        raise RuntimeError("E0 world did not initialize the requested number of days")
    metadata = sim.people.campus_registry_metadata
    levels = np.asarray(sim.people.student_level)
    realized_roles = {
        "undergraduate_students": int(np.count_nonzero(levels == 0)),
        "non_undergraduate_students": int(np.count_nonzero(levels == 1)),
        "teachers": int(len(np.asarray(metadata["teacher_indices"], dtype=np.int64))),
        "staff": int(len(np.asarray(metadata["staff_indices"], dtype=np.int64))),
    }
    expected_roles = config.get("target_roles")
    if expected_roles is not None:
        expected = {key: int(expected_roles[key]) for key in realized_roles}
        if realized_roles != expected:
            raise RuntimeError(f"E0 realized population does not match target_roles: "
                               f"{realized_roles} != {expected}")
    for _ in range(sim.npts):
        sim.step()
    sim.finalize(verbose=0)

    diagnoses = np.asarray(sim.results["new_diagnoses"], dtype=float)
    requested = np.asarray(sim.results["new_tests"], dtype=float)
    if len(diagnoses) != days or len(requested) != days:
        raise RuntimeError("E0 engine results did not cover every day")

    metadata = sim.people.campus_registry_metadata
    students = np.asarray(metadata["student_indices"], dtype=np.int64)
    employees = np.setdiff1d(np.arange(sim.n, dtype=np.int64), students)
    date_diagnosed = np.asarray(sim.people.date_diagnosed, dtype=float)
    student_positive = np.array([np.count_nonzero(date_diagnosed[students] == day)
                                 for day in range(days)], dtype=int)
    employee_positive = np.array([np.count_nonzero(date_diagnosed[employees] == day)
                                  for day in range(days)], dtype=int)
    if not np.array_equal(student_positive + employee_positive, diagnoses.astype(int)):
        raise RuntimeError("E0 group diagnoses do not reconcile with new_diagnoses")

    student_tests = np.asarray(sim["analyzers"][0].student_tests, dtype=int)
    employee_tests = np.asarray(sim["analyzers"][0].employee_tests, dtype=int)
    if len(student_tests) != days or len(employee_tests) != days:
        raise RuntimeError(f"E0 role test analyzer did not cover every day: "
                           f"{len(student_tests)}/{len(employee_tests)} vs {days}")
    if not np.array_equal(student_tests + employee_tests, requested.astype(int)):
        requested_vs_actual = {"requested": requested.astype(int).tolist(),
                               "actual": (student_tests + employee_tests).tolist()}
    else:
        requested_vs_actual = None

    r_eff = []
    if "r_eff" in sim.results:
        for value in np.asarray(sim.results["r_eff"], dtype=float):
            r_eff.append(float(value) if np.isfinite(value) else None)

    actual_total = int((student_tests + employee_tests).sum())
    student_actual = int(student_tests.sum())
    world = {
        "beta": float(beta),
        "seed": seed,
        "dates": list(data["dates"]),
        "groups": {
            "students": {"positive": student_positive.tolist(), "tests": student_tests.tolist()},
            "employees": {"positive": employee_positive.tolist(), "tests": employee_tests.tolist()},
        },
        "requested_tests": requested.astype(int).tolist(),
        "requested_vs_actual": requested_vs_actual,
        "r_eff": r_eff,
        "population": int(sim["pop_size"]),
        "roles": {
            "students": int(len(students)),
            **realized_roles,
            "employees": int(len(employees)),
        },
        "group_test_weights": {key: float(value) for key, value in weights.items()},
        "actual_test_share": {
            "students": (student_actual / actual_total) if actual_total else None,
            "employees": ((actual_total - student_actual) / actual_total) if actual_total else None,
        },
        "resolved_parameters": _jsonable({
            key: pars[key] for key in
            ("pop_type", "pop_size", "pop_infected", "beta", "start_day", "n_days",
             "campus_age_data", "campus_teacher_ratio", "campus_staff_ratio")
            if key in pars
        }),
        "config_sha256": config["config_sha256"],
    }
    return world

"""Replay historical measures while keeping the calibrated E0 world fixed."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib

import covasim as cv
import numpy as np

from ..control.scenarios import resolve_campus_parameters
from ..control.background import background_multipliers, employee_community
from ..e0.simulation import (_group_weights, _jsonable, _protocol,
                             _role_test_analyzer, _subtarget_factory)


START = date(2020, 8, 17)
RESTRICTIONS = date(2020, 9, 7)
CLASS_PAUSE = date(2020, 9, 10)
RECOVERY = date(2020, 9, 26)
END = date(2020, 10, 30)


def schedule_multipliers(day, c=0.2, h=1.15, recovery=0.5):
    """Return multipliers relative to E0; cm/d apply to UG-incident edges."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    if day < RESTRICTIONS:
        return {"cm": 1.0, "clu": 1.0, "clg": 1.0, "d": 1.0}
    if day < CLASS_PAUSE:
        return {"cm": c, "clu": 1.0, "clg": 1.0, "d": 1.0}
    if day < RECOVERY:
        return {"cm": c, "clu": 0.0, "clg": 0.0, "d": h}
    return {"cm": recovery, "clu": recovery, "clg": recovery, "d": 1.0}


def _topology_hash(layer):
    digest = hashlib.sha256()
    for key in ("p1", "p2"):
        digest.update(np.ascontiguousarray(layer[key]).tobytes())
    return digest.hexdigest()


def population_assignment_hash(people):
    """Fingerprint each person's fixed student level and registered role."""
    digest = hashlib.sha256()
    arrays = {"student_level": people.student_level,
              **{name: people.campus_registry_metadata[name] for name in
                 ("student_indices", "teacher_indices", "staff_indices")}}
    for name, values in arrays.items():
        array = np.asarray(values, dtype="<i8")
        digest.update(name.encode("ascii"))
        digest.update(len(array).to_bytes(8, "little"))
        digest.update(array.tobytes())
    return digest.hexdigest()


class HistoricalMeasures(cv.Intervention):
    """Apply after daily contact regeneration, before transmission calculation."""

    def __init__(self, c=0.2, h=1.15, recovery=0.5, c_emp_base=1.0,
                 c_emp_policy=1.0, ta_base=1.0, ta_policy=1.0, of_policy=1.0,
                 c_nonug_policy=1.0, d_nonug_policy=1.0):
        super().__init__(label="uw2020-historical-measures", do_plot=False)
        for name, value, maximum in (("c", c, 1), ("h", h, None),
                                     ("recovery", recovery, 1),
                                     ("c_emp_base", c_emp_base, 1),
                                     ("c_emp_policy", c_emp_policy, 1),
                                     ("ta_base", ta_base, 1), ("ta_policy", ta_policy, 1),
                                     ("of_policy", of_policy, 1),
                                     ("c_nonug_policy", c_nonug_policy, 1),
                                     ("d_nonug_policy", d_nonug_policy, 1)):
            if (type(value) not in (int, float) or not np.isfinite(value)
                    or value < 0 or (maximum is not None and value > maximum)):
                raise ValueError(f"{name} must be finite and within the replay range")
        if h <= 0:
            raise ValueError("h must be positive")
        self.c, self.h, self.recovery = float(c), float(h), float(recovery)
        self.c_emp_base = float(c_emp_base)
        self.c_emp_policy = float(c_emp_policy)
        self.ta_base = float(ta_base)
        self.ta_policy = float(ta_policy)
        self.of_policy = float(of_policy)
        self.c_nonug_policy = float(c_nonug_policy)
        self.d_nonug_policy = float(d_nonug_policy)
        self.last_applied_day = None
        self.background = employee_community(cv, self.c_emp_base)

    def initialize(self, sim=None):
        super().initialize(sim)
        self.background.initialize(sim)
        if sim["dynam_layer"]["d"] or not sim["dynam_layer"]["cm"]:
            raise ValueError("Historical replay requires static d and daily dynamic cm")
        self.start_day = date.fromisoformat(str(sim["start_day"]))
        self.undergraduate = np.asarray(sim.people.student_level) == 0
        self.non_undergraduate = np.asarray(sim.people.student_level) == 1
        students = np.asarray(sim.people.campus_registry_metadata["student_indices"], dtype=np.int64)
        self.employees = np.setdiff1d(np.arange(sim.n, dtype=np.int64), students)
        dorm = sim.people.contacts["d"]
        self.dorm_baseline = dorm["beta"].copy()
        self.dorm_mask = self.undergraduate[dorm["p1"]] | self.undergraduate[dorm["p2"]]
        self.nonug_dorm_mask = (self.non_undergraduate[dorm["p1"]]
                                | self.non_undergraduate[dorm["p2"]])
        self.dorm_topology_sha256 = _topology_hash(dorm)
        self.class_baseline = {key: sim["beta_layer"][key] for key in ("clu", "clg")}
        self.of_baseline = sim["beta_layer"]["of"]
        self.ta_baseline = sim["beta_layer"]["ta"]

    def apply(self, sim):
        if self.last_applied_day == sim.t:
            return
        self.last_applied_day = sim.t
        day = self.start_day + timedelta(days=int(sim.t))
        restricted = RESTRICTIONS <= day < RECOVERY
        recovered = day >= RECOVERY
        c_value = self.c if restricted else (self.recovery if recovered else 1.0)
        c_nonug_value = self.c_nonug_policy if restricted else 1.0
        c_emp_value = self.c_emp_policy if restricted else 1.0
        paused = CLASS_PAUSE <= day < RECOVERY
        ta_value = self.ta_base * (self.ta_policy if paused else 1.0)
        of_value = self.of_policy if paused else 1.0
        if day < CLASS_PAUSE:
            class_value, dorm_value = 1.0, 1.0
        elif day < RECOVERY:
            class_value, dorm_value = 0.0, self.h
        else:
            class_value, dorm_value = self.recovery, 1.0

        community = sim.people.contacts["cm"]
        community["beta"][:] = 1.0
        ug_mask = self.undergraduate[community["p1"]] | self.undergraduate[community["p2"]]
        nonug_mask = (self.non_undergraduate[community["p1"]]
                      | self.non_undergraduate[community["p2"]])
        employee_mask = (np.isin(community["p1"], self.employees)
                         | np.isin(community["p2"], self.employees))
        factor = np.ones(len(community["beta"]), dtype=float)
        factor[ug_mask] *= c_value
        factor[nonug_mask] *= c_nonug_value
        factor[employee_mask] *= c_emp_value
        community["beta"] *= factor
        self.background.apply(sim)
        for key, baseline in self.class_baseline.items():
            sim["beta_layer"][key] = baseline * class_value
        sim["beta_layer"]["of"] = self.of_baseline * of_value
        sim["beta_layer"]["ta"] = self.ta_baseline * ta_value
        dorm = sim.people.contacts["d"]
        dorm["beta"][:] = self.dorm_baseline
        dorm["beta"][self.dorm_mask] = self.dorm_baseline[self.dorm_mask] * dorm_value
        if paused:
            dorm["beta"][self.nonug_dorm_mask] *= self.d_nonug_policy

    def audit(self, sim):
        final_topology = _topology_hash(sim.people.contacts["d"])
        if final_topology != self.dorm_topology_sha256:
            raise RuntimeError("Historical replay changed the dormitory topology")
        return {"dorm_topology_initial_sha256": self.dorm_topology_sha256,
                "dorm_topology_final_sha256": final_topology,
                "dorm_undergraduate_edges": int(self.dorm_mask.sum()),
                "dorm_weights_restored": bool(np.array_equal(
                    sim.people.contacts["d"]["beta"], self.dorm_baseline))}


def _w1_input(data, w1_data):
    dates = [str(day) for day in data["dates"]]
    expected = [(START + timedelta(days=i)).isoformat() for i in range(len(dates))]
    if not 21 <= len(dates) <= 75 or dates != expected:
        raise ValueError("Replay dates must be contiguous from 2020-08-17, covering 21 to 75 days")
    first = {"dates": dates[:21], "groups": {
        group: {field: list(data["groups"][group][field][:21]) for field in ("positive", "tests")}
        for group in ("students", "employees")}}
    if w1_data is not None:
        if (list(w1_data["dates"]) != first["dates"] or any(
                list(w1_data["groups"][group][field]) != first["groups"][group][field]
                for group in first["groups"] for field in ("positive", "tests"))):
            raise ValueError("Frozen W1 data must match the first 21 replay days")
        return w1_data
    return first


def build_replay_sim(config, data, beta, seed, *, c=0.2, h=1.15, recovery=0.5,
                     c_emp_policy=1.0, ta_policy=1.0, of_policy=1.0,
                     c_nonug_policy=1.0, d_nonug_policy=1.0, w1_data=None):
    """Initialize a historical world; callers may stop before any day boundary."""
    if type(beta) not in (int, float) or not np.isfinite(beta) or beta <= 0:
        raise ValueError("beta must be a finite positive number")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    frozen_w1 = _w1_input(data, w1_data)
    days = len(data["dates"])
    for group in ("students", "employees"):
        for field in ("positive", "tests"):
            values = data["groups"][group][field]
            if len(values) != days or any(type(value) not in (int, np.int64, np.int32)
                                          or value < 0 for value in values):
                raise ValueError(f"Replay {group}.{field} must contain one nonnegative integer per day")
    testing = dict(config["testing"])
    if testing["test_delay"] != 0:
        raise ValueError("Replay group diagnoses require test_delay=0")
    protocol = _protocol(config["base_protocol_path"])
    background = background_multipliers(config)
    pars = resolve_campus_parameters(protocol, seed, beta=float(beta),
                                     population=config["population"],
                                     initial_infections=config["initial_infections"],
                                     execution_days=days, background=background)
    pars.update(config["engine_overrides"])
    pars["start_day"] = data["dates"][0]
    tests = [int(a) + int(b) for a, b in zip(data["groups"]["students"]["tests"],
                                              data["groups"]["employees"]["tests"])]
    weights = _group_weights(config, frozen_w1)
    analyzer = _role_test_analyzer(cv)
    testing_intervention = cv.test_num(daily_tests=tests, subtarget=_subtarget_factory(weights), **testing)
    measures = HistoricalMeasures(c, h, recovery,
                                  c_emp_base=background["employee_cm"],
                                  c_emp_policy=c_emp_policy,
                                  ta_policy=ta_policy,
                                  of_policy=of_policy,
                                  c_nonug_policy=c_nonug_policy,
                                  d_nonug_policy=d_nonug_policy)
    interventions = [testing_intervention]
    trace_setting = config.get("replay_contact_tracing", {})
    if trace_setting.get("enabled"):
        interventions.append(cv.contact_tracing(
            trace_probs=dict(trace_setting["trace_probs"]),
            trace_time=int(trace_setting["trace_time"]),
            start_day=trace_setting["start_day"],
            end_day=trace_setting.get("end_day"),
            quar_period=int(trace_setting["quar_period"]),
            presumptive=False, do_plot=False, label="uw2020-contact-tracing"))
    interventions.append(measures)
    sim = cv.Sim(pars=pars, interventions=interventions, analyzers=[analyzer])
    sim.initialize()
    if sim.npts != days:
        raise RuntimeError("Replay world did not initialize the requested number of days")
    # Covasim copies intervention/analyzer instances when initializing a Sim.
    measures = next(item for item in sim["interventions"]
                    if isinstance(item, HistoricalMeasures))
    analyzer = sim["analyzers"][0]
    metadata = sim.people.campus_registry_metadata
    levels = np.asarray(sim.people.student_level)
    realized_roles = {
        "undergraduate_students": int(np.count_nonzero(levels == 0)),
        "non_undergraduate_students": int(np.count_nonzero(levels == 1)),
        "teachers": int(len(np.asarray(metadata["teacher_indices"], dtype=np.int64))),
        "staff": int(len(np.asarray(metadata["staff_indices"], dtype=np.int64))),
    }
    if config.get("target_roles") is not None and realized_roles != config["target_roles"]:
        raise RuntimeError(f"Replay population roles differ from frozen E0: {realized_roles}")
    return sim, measures, analyzer, weights, realized_roles


def run_replay_world(config, data, beta, seed, *, c=0.2, h=1.15, recovery=0.5,
                     c_emp_policy=1.0, ta_policy=1.0, of_policy=1.0,
                     c_nonug_policy=1.0, d_nonug_policy=1.0, w1_data=None):
    """Run one continuous world with W1-only frozen testing allocation weights."""
    sim, measures, analyzer, weights, realized_roles = build_replay_sim(
        config, data, beta, seed, c=c, h=h, recovery=recovery, c_emp_policy=c_emp_policy,
        ta_policy=ta_policy, of_policy=of_policy, c_nonug_policy=c_nonug_policy,
        d_nonug_policy=d_nonug_policy, w1_data=w1_data)
    days = len(data["dates"])
    pars = dict(sim.pars, beta_layer=dict(sim["beta_layer"]))
    background = background_multipliers(config)
    metadata = sim.people.campus_registry_metadata
    for _ in range(sim.npts):
        sim.step()
    audit = measures.audit(sim)
    sim.finalize(verbose=0)

    students = np.asarray(metadata["student_indices"], dtype=np.int64)
    employees = np.setdiff1d(np.arange(sim.n, dtype=np.int64), students)
    date_diagnosed = np.asarray(sim.people.date_diagnosed, dtype=float)
    groups = {}
    for name, inds, actual_tests in (("students", students, analyzer.student_tests),
                                     ("employees", employees, analyzer.employee_tests)):
        positive = [int(np.count_nonzero(date_diagnosed[inds] == day)) for day in range(days)]
        groups[name] = {"positive": positive, "tests": [int(n) for n in actual_tests]}
    diagnoses = np.asarray(sim.results["new_diagnoses"], dtype=int)
    if not np.array_equal(np.asarray(groups["students"]["positive"]) +
                          np.asarray(groups["employees"]["positive"]), diagnoses):
        raise RuntimeError("Replay group diagnoses do not reconcile with new_diagnoses")
    actual = np.asarray(groups["students"]["tests"]) + np.asarray(groups["employees"]["tests"])
    if len(actual) != days:
        raise RuntimeError("Replay role test analyzer did not cover every day")
    requested = np.asarray(sim.results["new_tests"], dtype=int)
    difference = None if np.array_equal(actual, requested) else {
        "requested": requested.tolist(), "actual": actual.tolist()}
    total_tests = int(actual.sum())
    return {
        "beta": float(beta), "seed": seed, "dates": list(data["dates"]), "groups": groups,
        "requested_tests": requested.tolist(), "requested_vs_actual": difference,
        "r_eff": [float(value) if np.isfinite(value) else None
                  for value in np.asarray(sim.results["r_eff"], dtype=float)],
        "population": int(sim["pop_size"]),
        "roles": {"students": len(students), **realized_roles, "employees": len(employees)},
        "group_test_weights": {key: float(value) for key, value in weights.items()},
        "actual_test_share": {name: (sum(values["tests"]) / total_tests if total_tests else None)
                              for name, values in groups.items()},
        "resolved_parameters": _jsonable({key: pars[key] for key in
            ("pop_type", "pop_size", "pop_infected", "beta", "start_day", "n_days",
             "campus_age_data", "campus_teacher_ratio", "campus_staff_ratio",
             "beta_layer", "iso_factor", "quar_factor") if key in pars}),
        "campus_background": background,
        "config_sha256": config["config_sha256"],
        "replay": {"c": float(c), "h": float(h), "recovery": float(recovery),
                   "testing_weight_window": ["2020-08-17", "2020-09-06"],
                   "population_assignment_sha256": population_assignment_hash(sim.people), **audit},
    }

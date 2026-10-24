"""Load the frozen UW E0 configuration and its derived daily calibration table.

The table is a derived artifact of ``research/historical_epidemics``.  This
module never refits or imputes it: dates must be contiguous, zero-test days
stay zero, and the provenance hash must match the checked-in bytes.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ("date", "student_positive_tests", "student_tests",
           "employee_positive_tests", "employee_tests")
GROUPS = ("students", "employees")
PROTOCOL_ID = "cemas-uw-e0-v1"


class E0ConfigError(ValueError):
    """The E0 configuration or derived data is invalid."""


def _required(mapping, key, location):
    if not isinstance(mapping, dict) or key not in mapping:
        raise E0ConfigError(f"Missing {location}.{key}")
    return mapping[key]


def _integer(value, location, minimum=0):
    if type(value) is not int or value < minimum:
        raise E0ConfigError(f"{location} must be an integer >= {minimum}")
    return value


def _number(value, location, *, positive=False, maximum=None):
    if type(value) not in (int, float):
        raise E0ConfigError(f"{location} must be a finite number")
    if not (value > 0 if positive else value >= 0):
        raise E0ConfigError(f"{location} must be a finite {'positive' if positive else 'nonnegative'} number")
    if maximum is not None and value > maximum:
        raise E0ConfigError(f"{location} must not exceed {maximum}")
    return float(value)


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        raise E0ConfigError(f"{location} must be nonempty text")
    return value


def _iso_date(value, location):
    if not isinstance(value, str):
        raise E0ConfigError(f"{location} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise E0ConfigError(f"{location} must be an ISO date") from exc


def _seed_list(value, location):
    if not isinstance(value, list) or not value:
        raise E0ConfigError(f"{location} must be a nonempty list")
    seeds = [_integer(seed, location, minimum=0) for seed in value]
    if len(set(seeds)) != len(seeds):
        raise E0ConfigError(f"{location} contains duplicate seeds")
    return seeds


def _check_disjoint(seed_lists):
    seen = {}
    for name, seeds in seed_lists.items():
        for seed in seeds:
            if seed in seen:
                raise E0ConfigError(f"Seed {seed} is reused by {name} and {seen[seed]}")
            seen[seed] = name
    return seen


def _validate_engine_overrides(value, population):
    if not isinstance(value, dict) or not value:
        raise E0ConfigError("engine_overrides must be a nonempty object")
    for key, item in value.items():
        if not isinstance(key, str) or not key.startswith("campus_"):
            raise E0ConfigError("engine_overrides may only contain campus_* keys")
        if key == "campus_age_data":
            if not isinstance(item, list) or not item:
                raise E0ConfigError("engine_overrides.campus_age_data must be a nonempty list")
            total = 0.0
            previous_max = -1
            for index, row in enumerate(item):
                if not isinstance(row, list) or len(row) != 3:
                    raise E0ConfigError(f"engine_overrides.campus_age_data[{index}] must be [min,max,probability]")
                low, high, probability = row
                if type(low) is not int or type(high) is not int or low < 0 or high <= low:
                    raise E0ConfigError(f"engine_overrides.campus_age_data[{index}] has invalid bounds")
                if low <= previous_max:
                    raise E0ConfigError("engine_overrides.campus_age_data bins must be ordered and disjoint")
                previous_max = high
                total += _number(probability, f"engine_overrides.campus_age_data[{index}].probability",
                                 maximum=1)
            if abs(total - 1.0) > 1e-12:
                raise E0ConfigError("engine_overrides.campus_age_data probabilities must sum to 1")
        elif key == "campus_age_counts":
            if not isinstance(item, list) or not item:
                raise E0ConfigError("engine_overrides.campus_age_counts must be a nonempty list")
            if any(type(count) is not int or count < 0 for count in item):
                raise E0ConfigError("engine_overrides.campus_age_counts must contain nonnegative integers")
        elif key in ("campus_teacher_ratio", "campus_staff_ratio"):
            ratio = _number(item, f"engine_overrides.{key}", maximum=1)
            if ratio <= 0:
                raise E0ConfigError(f"engine_overrides.{key} must be positive")
        else:
            _number(item, f"engine_overrides.{key}") if isinstance(item, (int, float)) else None
    counts = value.get("campus_age_counts")
    if counts is not None:
        if sum(counts) != population:
            raise E0ConfigError("engine_overrides.campus_age_counts must sum to config.population")
        age_data = value.get("campus_age_data")
        if age_data is not None and len(counts) != len(age_data):
            raise E0ConfigError("engine_overrides.campus_age_counts must match campus_age_data bins")
    teacher = value.get("campus_teacher_ratio", 0.0)
    staff = value.get("campus_staff_ratio", 0.0)
    if teacher + staff > 1:
        raise E0ConfigError("engine_overrides teacher and staff ratios must not exceed 1")


def validate_e0_config(config, path):
    """Validate and resolve one E0 configuration file."""
    if not isinstance(config, dict):
        raise E0ConfigError("E0 configuration must be a JSON object")
    if _required(config, "protocol_id", "config") != PROTOCOL_ID:
        raise E0ConfigError(f"protocol_id must be {PROTOCOL_ID}")
    _text(_required(config, "method_version", "config"), "config.method_version")

    window = _required(config, "window", "config")
    start = _iso_date(_required(window, "start", "config.window"), "config.window.start")
    end = _iso_date(_required(window, "end", "config.window"), "config.window.end")
    if start > end:
        raise E0ConfigError("config.window.start must not be later than end")

    population = _integer(_required(config, "population", "config"), "config.population", minimum=1)
    target_groups = _required(config, "target_groups", "config")
    students = _integer(_required(target_groups, "students", "config.target_groups"),
                        "config.target_groups.students", minimum=1)
    employees = _integer(_required(target_groups, "employees", "config.target_groups"),
                         "config.target_groups.employees", minimum=1)
    if students + employees != population:
        raise E0ConfigError("config.target_groups must sum to config.population")
    initial = _integer(_required(config, "initial_infections", "config"),
                       "config.initial_infections", minimum=0)
    if initial > population:
        raise E0ConfigError("config.initial_infections must not exceed config.population")

    _validate_engine_overrides(_required(config, "engine_overrides", "config"), population)

    target_roles = _required(config, "target_roles", "config")
    if not isinstance(target_roles, dict):
        raise E0ConfigError("config.target_roles must be an object")
    undergraduate = _integer(_required(target_roles, "undergraduate_students", "config.target_roles"),
                             "config.target_roles.undergraduate_students", minimum=0)
    non_undergraduate = _integer(_required(target_roles, "non_undergraduate_students",
                                           "config.target_roles"),
                                 "config.target_roles.non_undergraduate_students", minimum=0)
    teachers = _integer(_required(target_roles, "teachers", "config.target_roles"),
                        "config.target_roles.teachers", minimum=0)
    staff = _integer(_required(target_roles, "staff", "config.target_roles"),
                     "config.target_roles.staff", minimum=0)
    if undergraduate + non_undergraduate != students:
        raise E0ConfigError("config.target_roles students must match config.target_groups.students")
    if teachers + staff != employees:
        raise E0ConfigError("config.target_roles employees must match config.target_groups.employees")

    testing = _required(config, "testing", "config")
    _number(_required(testing, "symp_test", "config.testing"), "config.testing.symp_test", positive=True)
    _number(_required(testing, "quar_test", "config.testing"), "config.testing.quar_test")
    _number(_required(testing, "sensitivity", "config.testing"), "config.testing.sensitivity",
            positive=True, maximum=1)
    _number(_required(testing, "loss_prob", "config.testing"), "config.testing.loss_prob", maximum=1)
    _integer(_required(testing, "test_delay", "config.testing"), "config.testing.test_delay", minimum=0)

    beta_range = _required(config, "beta_range", "config")
    if not isinstance(beta_range, list) or len(beta_range) != 2:
        raise E0ConfigError("config.beta_range must be [low, high]")
    low = _number(beta_range[0], "config.beta_range.low", positive=True)
    high = _number(beta_range[1], "config.beta_range.high", positive=True)
    if low >= high:
        raise E0ConfigError("config.beta_range must increase")

    coarse_points = _integer(_required(config, "coarse_points", "config"),
                             "config.coarse_points", minimum=5)
    refinement = _integer(_required(config, "refinement_factor", "config"),
                          "config.refinement_factor", minimum=2)
    alignments = _required(config, "alignments", "config")
    if (not isinstance(alignments, list) or not alignments
            or any(type(item) is not int or item not in (0, 1, 2) for item in alignments)
            or len(set(alignments)) != len(alignments)):
        raise E0ConfigError("config.alignments must be a unique nonempty subset of 0, 1, 2")
    primary_alignment = _integer(_required(config, "primary_alignment", "config"),
                                 "config.primary_alignment", minimum=0)
    if primary_alignment not in alignments:
        raise E0ConfigError("config.primary_alignment must be in config.alignments")
    primary_metric = _required(config, "primary_metric", "config")
    if primary_metric not in ("cumulative", "weekly"):
        raise E0ConfigError("config.primary_metric must be cumulative or weekly")

    days = (end - start).days + 1
    baseline_days = _integer(_required(config, "baseline_days", "config"),
                             "config.baseline_days", minimum=4)
    if baseline_days >= days - 2:
        raise E0ConfigError("config.baseline_days must leave comparison days")

    scan_seeds = _seed_list(_required(config, "scan_seeds", "config"), "config.scan_seeds")
    fit_seeds = _seed_list(_required(config, "fit_seeds", "config"), "config.fit_seeds")
    evaluation_seeds = _seed_list(_required(config, "evaluation_seeds", "config"),
                                  "config.evaluation_seeds")
    used = _check_disjoint({"scan": scan_seeds, "fit": fit_seeds, "evaluation": evaluation_seeds})

    sensitivities = _required(config, "sensitivities", "config")
    if not isinstance(sensitivities, list):
        raise E0ConfigError("config.sensitivities must be a list")
    names = {"main"}
    for index, item in enumerate(sensitivities):
        if not isinstance(item, dict):
            raise E0ConfigError(f"config.sensitivities[{index}] must be an object")
        name = _text(_required(item, "name", f"config.sensitivities[{index}]"),
                     f"config.sensitivities[{index}].name")
        if name in names:
            raise E0ConfigError(f"config.sensitivities[{index}].name is duplicated")
        names.add(name)
        if "symp_test" in item:
            _number(item["symp_test"], f"config.sensitivities[{index}].symp_test", positive=True)
        if "initial_infections" in item:
            _integer(item["initial_infections"], f"config.sensitivities[{index}].initial_infections",
                     minimum=0)
        if "symp_test" not in item and "initial_infections" not in item:
            raise E0ConfigError(f"config.sensitivities[{index}] must override symp_test or initial_infections")

    base_path = _resolve(_required(config, "base_protocol", "config"), "config.base_protocol")
    data_path = _resolve(_required(config, "data_path", "config"), "config.data_path")
    provenance_path = _resolve(_required(config, "provenance_path", "config"),
                               "config.provenance_path")

    resolved = dict(config)
    resolved.update({
        "config_path": str(path),
        "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "base_protocol_path": str(base_path),
        "data_path": str(data_path),
        "provenance_path": str(provenance_path),
        "window_days": days,
        "seed_count": len(used),
    })
    return resolved


def _resolve(value, location):
    _text(value, location)
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise E0ConfigError(f"{location} must stay inside the project root")
    if not path.exists():
        raise E0ConfigError(f"{location} does not exist: {value}")
    return path


def load_e0_config(path):
    """Read and validate one E0 JSON configuration."""
    path = Path(path).resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E0ConfigError(f"Cannot read E0 configuration: {exc}") from exc
    return validate_e0_config(config, path)


def load_e0_data(config):
    """Read the derived W1 table and verify its provenance."""
    path = Path(config["data_path"])
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    except UnicodeDecodeError as exc:
        raise E0ConfigError("E0 data must be UTF-8 text") from exc
    if not rows:
        raise E0ConfigError("E0 data are empty")
    if tuple(rows[0].keys()) != COLUMNS:
        raise E0ConfigError(f"E0 data require columns {COLUMNS}")

    start = date.fromisoformat(config["window"]["start"])
    end = date.fromisoformat(config["window"]["end"])
    dates, students_positive, students_tests, employees_positive, employees_tests = [], [], [], [], []
    previous = None
    for index, row in enumerate(rows, start=2):
        try:
            day = date.fromisoformat(row["date"])
            values = [float(row[name]) for name in COLUMNS[1:]]
        except (KeyError, TypeError, ValueError) as exc:
            raise E0ConfigError(f"Invalid E0 data row {index}") from exc
        if previous is not None and (day - previous).days != 1:
            raise E0ConfigError("E0 data dates must be unique, ordered and contiguous")
        if any(not value.is_integer() for value in (values[0], values[2])):
            raise E0ConfigError("E0 positive counts must be integer counts")
        if any(value < 0 for value in values):
            raise E0ConfigError("E0 counts must be nonnegative")
        if (values[1] == 0 and values[0] > 0) or (values[3] == 0 and values[2] > 0):
            raise E0ConfigError("E0 positive counts require a positive test denominator")
        dates.append(day.isoformat())
        students_positive.append(int(values[0]))
        students_tests.append(_plain(values[1]))
        employees_positive.append(int(values[2]))
        employees_tests.append(_plain(values[3]))
        previous = day
    if dates[0] != start.isoformat() or dates[-1] != end.isoformat():
        raise E0ConfigError("E0 data do not match config.window")

    total_positive = sum(students_positive) + sum(employees_positive)
    total_tests = sum(students_tests) + sum(employees_tests)
    if total_tests <= 0:
        raise E0ConfigError("E0 data require a positive total test count")

    provenance = {}
    provenance_path = Path(config["provenance_path"])
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise E0ConfigError("E0 provenance is not valid JSON") from exc
        if provenance.get("derived_sha256") != digest:
            raise E0ConfigError("E0 provenance hash does not match the data file")
        if provenance.get("window") != [start.isoformat(), end.isoformat()]:
            raise E0ConfigError("E0 provenance window does not match the configuration")
        expected = provenance.get("groups", {})
        actual = {
            "students": {"positive": sum(students_positive), "tests": sum(students_tests)},
            "employees": {"positive": sum(employees_positive), "tests": sum(employees_tests)},
        }
        for group in GROUPS:
            for field in ("positive", "tests"):
                if group in expected and expected[group].get(field) != actual[group][field]:
                    raise E0ConfigError(f"E0 provenance {group}.{field} does not match the data")
        if provenance.get("totals", {}).get("positive") not in (None, total_positive):
            raise E0ConfigError("E0 provenance total positive count does not match the data")
        if provenance.get("totals", {}).get("tests") not in (None, total_tests):
            raise E0ConfigError("E0 provenance total test count does not match the data")

    return {
        "dates": tuple(dates),
        "groups": {
            "students": {"positive": tuple(students_positive), "tests": tuple(students_tests)},
            "employees": {"positive": tuple(employees_positive), "tests": tuple(employees_tests)},
        },
        "provenance": provenance,
        "sha256": digest,
        "data_path": str(path),
        "totals": {"positive": total_positive, "tests": total_tests},
    }


def _plain(value):
    return int(value) if float(value).is_integer() else float(value)

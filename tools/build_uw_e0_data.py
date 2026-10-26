"""Build the frozen UW–Madison E0 calibration tables from normalized observations.

The builder only selects, pivots and checks the published dashboard series.  It
does not impute, forward-fill, difference cumulative values, or move dates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cemas.historical_data import list_datasets, load_observations

ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "uw_madison_2020"
ENTITY_ID = "university_uw_madison"
SCOPE = "on_campus_testing"
COLUMNS = ("date", "student_positive_tests", "student_tests",
           "employee_positive_tests", "employee_tests")
GROUPS = ("students", "employees")
WINDOWS = {
    "w1": ("2020-08-17", "2020-09-06"),
    "w2w3": ("2020-09-26", "2020-10-30"),
    "replay": ("2020-08-17", "2020-10-30"),
}
EXPECTED_W1 = {
    "rows": 21,
    "groups": {"students": {"positive": 584, "tests": 16677},
               "employees": {"positive": 5, "tests": 1637}},
    "totals": {"positive": 589, "tests": 18314},
}
REPLAY_WINDOWS = {
    "w1": ("2020-08-17", "2020-09-06", 21, 584, 16677, 5, 1637),
    "w2": ("2020-09-07", "2020-09-25", 19, 1393, 20457, 11, 1706),
    "w3": ("2020-09-26", "2020-10-30", 35, 463, 39110, 76, 4661),
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_sha():
    for entry in list_datasets():
        if entry["id"] == DATASET_ID:
            return entry["sha256"]
    raise ValueError(f"Dataset {DATASET_ID} is not in the catalog")


def _window_frame(frame, start, end):
    dates = pd.to_datetime(frame["date_start"])
    selected = frame[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    selected = selected[selected["population_group"].isin(GROUPS)]
    selected = selected[selected["observation_scope"] == SCOPE]
    selected = selected[selected["metric"].isin(("new_positive_tests", "new_tests"))]
    selected = selected[selected["frequency"] == "daily"]
    selected = selected[selected["time_basis"] == "dashboard_date"]
    if selected.empty:
        raise ValueError(f"No observed rows in {start}..{end}")
    if (selected["date_start"] != selected["date_end"]).any():
        raise ValueError("E0 calibration data must use single-day rows")
    if selected["value"].isna().any():
        raise ValueError("E0 calibration data must not contain missing values")
    selected = selected.assign(date=pd.to_datetime(selected["date_start"]).dt.strftime("%Y-%m-%d"),
                               number=selected["value"])
    if selected.duplicated(["date", "population_group", "metric"]).any():
        raise ValueError("Duplicate daily observations in the selected E0 series")
    if (selected["number"] < 0).any():
        raise ValueError("E0 calibration data must be nonnegative")
    wide = selected.pivot_table(index="date", columns=["population_group", "metric"],
                                values="number", aggfunc="first")
    expected_columns = [(group, metric) for group in GROUPS
                        for metric in ("new_positive_tests", "new_tests")]
    missing = [column for column in expected_columns if column not in wide.columns]
    if missing:
        raise ValueError(f"Missing E0 series: {missing}")
    if wide[expected_columns].isna().any().any():
        raise ValueError("E0 series contain missing days")
    wide = wide[expected_columns].sort_index()
    expected_dates = pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
    if wide.index.tolist() != expected_dates:
        raise ValueError("E0 series must cover every date in the requested window")
    rows = []
    for day, values in wide.iterrows():
        student_positive = values[("students", "new_positive_tests")]
        student_tests = values[("students", "new_tests")]
        employee_positive = values[("employees", "new_positive_tests")]
        employee_tests = values[("employees", "new_tests")]
        for positive, tests, label in (
                (student_positive, student_tests, "students"),
                (employee_positive, employee_tests, "employees")):
            if tests == 0 and positive != 0:
                raise ValueError(f"Zero {label} tests with positive results on {day}")
            if not float(positive).is_integer():
                raise ValueError(f"Non-integer {label} positive count on {day}")
        rows.append({
            "date": day,
            "student_positive_tests": int(student_positive),
            "student_tests": int(student_tests) if float(student_tests).is_integer() else float(student_tests),
            "employee_positive_tests": int(employee_positive),
            "employee_tests": int(employee_tests) if float(employee_tests).is_integer() else float(employee_tests),
        })
    return rows


def _totals(rows):
    return {
        "groups": {
            "students": {"positive": sum(row["student_positive_tests"] for row in rows),
                         "tests": sum(row["student_tests"] for row in rows)},
            "employees": {"positive": sum(row["employee_positive_tests"] for row in rows),
                          "tests": sum(row["employee_tests"] for row in rows)},
        },
        "totals": {
            "positive": sum(row["student_positive_tests"] + row["employee_positive_tests"] for row in rows),
            "tests": sum(row["student_tests"] + row["employee_tests"] for row in rows),
        },
    }


def _write(path, text, force):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; pass --force to overwrite")
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def build(name, frame, output, provenance, force):
    start, end = WINDOWS[name]
    rows = _window_frame(frame, start, end)
    totals = _totals(rows)
    if name == "w1":
        if len(rows) != EXPECTED_W1["rows"]:
            raise ValueError(f"W1 expected {EXPECTED_W1['rows']} rows, got {len(rows)}")
        for group in GROUPS:
            for field in ("positive", "tests"):
                if totals["groups"][group][field] != EXPECTED_W1["groups"][group][field]:
                    raise ValueError(f"W1 {group}.{field} does not match the frozen total")
        if totals["totals"] != EXPECTED_W1["totals"]:
            raise ValueError("W1 totals do not match the frozen totals")
    window_totals = {}
    if name == "replay":
        for window, (first, last, days, sp, st, ep, et) in REPLAY_WINDOWS.items():
            window_rows = [row for row in rows if first <= row["date"] <= last]
            summary = _totals(window_rows)
            if len(window_rows) != days or summary["groups"] != {
                    "students": {"positive": sp, "tests": st},
                    "employees": {"positive": ep, "tests": et}}:
                raise ValueError(f"Replay {window} does not match the published window totals")
            window_totals[window] = {"window": [first, last], "rows": days, **summary}

    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(str(row[column]) for column in COLUMNS))
    text = "\n".join(lines) + "\n"
    _write(output, text, force)
    derived_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    raw_path = ROOT / "research" / "historical_epidemics" / "data" / "raw" / "uw_madison_2020.html"
    provenance_payload = {
        "schema_version": "cemas-uw-e0-data-v1",
        "dataset_id": DATASET_ID,
        "source_observations_file": "research/historical_epidemics/data/observations/uw_madison_2020.csv.gz",
        "source_observations_sha256": _catalog_sha(),
        "source_raw_file": "research/historical_epidemics/data/raw/uw_madison_2020.html",
        "source_raw_sha256": _sha256(raw_path) if raw_path.exists() else None,
        "entity_id": ENTITY_ID,
        "observation_scope": SCOPE,
        "metrics": ["new_positive_tests", "new_tests"],
        "window": [start, end],
        "rows": len(rows),
        **totals,
        "assumptions": [
            "Counts are on-campus testing only; off-campus positives and denominators are not included.",
            "The daily date is the dashboard receipt date, not the specimen collection date.",
            "The 2020-09-16 90-day repeat-positive exclusion is assumed to apply to the whole published series.",
            "Zero-test days remain zero; no imputation, forward fill or cumulative differencing is applied.",
            "W1 ends on 2020-09-06, before the 2020-09-07 undergraduate movement restriction.",
        ],
        "derived_file": str(output.relative_to(ROOT)).replace("\\", "/"),
        "derived_sha256": derived_sha,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "builder": "tools/build_uw_e0_data.py",
        "builder_version": "cemas-uw-e0-data-v1",
    }
    if name == "replay":
        sources = ROOT / "data" / "uw_madison_2020_replay.sources.json"
        provenance_payload.update({
            "windows": window_totals,
            "intervention_sources_file": str(sources.relative_to(ROOT)).replace("\\", "/"),
            "intervention_sources_sha256": _sha256(sources),
        })
    _write(provenance, json.dumps(provenance_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", force)
    return {"name": name, "rows": len(rows), **totals, "output": str(output)}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "data" / "uw_madison_2020_w1.csv")
    parser.add_argument("--provenance", type=Path,
                        default=root / "data" / "uw_madison_2020_w1.provenance.json")
    parser.add_argument("--w2w3-output", type=Path, default=root / "data" / "uw_madison_2020_w2w3.csv")
    parser.add_argument("--w2w3-provenance", type=Path,
                        default=root / "data" / "uw_madison_2020_w2w3.provenance.json")
    parser.add_argument("--replay-only", action="store_true",
                        help="Build the 75-day replay table without rewriting the existing E0 tables")
    parser.add_argument("--replay-output", type=Path,
                        default=root / "data" / "uw_madison_2020_replay.csv")
    parser.add_argument("--replay-provenance", type=Path,
                        default=root / "data" / "uw_madison_2020_replay.provenance.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    frame = load_observations(DATASET_ID, entity_id=ENTITY_ID, observation_scope=SCOPE)
    if args.replay_only:
        results = [build("replay", frame, args.replay_output, args.replay_provenance, args.force)]
    else:
        results = [build("w1", frame, args.output, args.provenance, args.force),
                   build("w2w3", frame, args.w2w3_output, args.w2w3_provenance, args.force)]
    for result in results:
        print(f"{result['name']}: {result['rows']} rows, "
              f"{result['totals']['positive']} positives / {result['totals']['tests']} tests -> {result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

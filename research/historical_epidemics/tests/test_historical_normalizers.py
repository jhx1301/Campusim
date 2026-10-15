"""Regression checks for historical observation boundaries and source semantics."""

import csv
from io import StringIO
from pathlib import Path

import pytest

from research.historical_epidemics.scripts.normalizers import normalize


RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.mark.parametrize("source,filename,start,end,days,measurements_per_day", [
    ("uw_madison_2020", "uw_madison_2020.html", "2020-08-17", "2020-12-31", 137, 4),
    ("uw_madison_2021_spring", "uw_madison_2021_spring.html", "2020-08-07", "2021-05-09", 276, 6),
])
def test_wisconsin_snapshots_preserve_actual_days_across_calendar_years(
    source, filename, start, end, days, measurements_per_day,
):
    observations = list(normalize(source, (RAW / filename).read_bytes()))
    dates = {row["date_start"] for row in observations}
    assert (min(dates), max(dates), len(dates)) == (start, end, days)
    assert len(observations) == days * measurements_per_day
    assert all(row["date_start"] == row["date_end"] for row in observations)
    if source == "uw_madison_2021_spring":
        assert {"2020-12-31", "2021-01-01"} <= dates
        assert {row["observation_scope"] for row in observations} == {
            "on_campus_testing", "off_campus_testing",
        }


def test_cambridge_outputs_only_selected_complete_aggregate_panels():
    observations = list(normalize("cambridge_2020", (RAW / "cambridge_2020.xlsx").read_bytes()))
    cohort = [row for row in observations if row["metric"] == "university_cohort_cases_figure2c"]
    community = [row for row in observations if row["metric"] == "new_reported_cases"]

    assert len(observations) == 23
    assert len(cohort) == 9
    assert len(community) == 14
    assert min(row["date_start"] for row in cohort) == "2020-10-05"
    assert max(row["date_end"] for row in cohort) == "2020-12-06"
    assert all(row["date_start"] != "2020-12-14" for row in cohort)
    # The partial Dec 14 figure row contains 321 in one category; it is not
    # a complete cohort week and must not be imported as a cohort total.
    assert all(row["value"] != 321 for row in cohort)
    assert next(row["value"] for row in cohort if row["date_start"] == "2020-10-05") == 33
    assert all("not_full_campus" in row["quality"] for row in cohort)
    assert (min(row["date_start"] for row in community), max(row["date_end"] for row in community)) == (
        "2020-09-21", "2020-12-27",
    )
    assert all(
        row["source_locator"].startswith((
            "xlsx:sheet=Figure2c;", "xlsx:sheet=Supplementary_Figure_1;",
        )) for row in observations
    )


def test_bigten_keeps_missing_tests_true_zero_and_undifferenced_cumulative_cases():
    raw = b"""Country_Region,Date,Tests,Confirmed
Illinois,2020-08-01,,0
Illinois,2020-08-03,100.0,7
Illinois,2020-08-04,110.0,9
"""
    observations = list(normalize("bigten_raw", raw))
    cases = [row for row in observations if row["metric"] == "cumulative_reported_cases"]
    tests = [row for row in observations if row["metric"] == "cumulative_tests"]
    assert [row["value"] for row in cases] == [0, 7, 9]
    assert cases[0]["quality"] == "observed"
    assert tests[0]["value"] is None
    assert tests[0]["quality"] == "missing"
    assert tests[0]["raw_value"] == ""
    assert [row["value"] for row in tests[1:]] == [100, 110]
    assert {row["frequency"] for row in observations} == {"irregular"}
    assert {row["entity_id"] for row in observations} == {"university_illinois"}


def test_nyc_preserves_nonboolean_flag_and_admission_date_hospitalization_counts():
    # Reuse one fixed published row rather than normalizing the entire city
    # history just to check its unusual source incompleteness marker.
    with (RAW / "nyc_daily.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        last_row = list(reader)[-1]
    assert last_row["INCOMPLETE"] == "61030"
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(last_row)
    observations = list(normalize("nyc_daily", buffer.getvalue().encode("utf-8")))

    assert len(observations) == 24  # Four reported metrics for city and five boroughs.
    assert {row["quality"] for row in observations} == {"source_incomplete_flag=61030"}
    hospitalizations = [
        row for row in observations if row["metric"] == "hospitalized_cases_by_admission_date"
    ]
    assert len(hospitalizations) == 6
    assert {row["time_basis"] for row in hospitalizations} == {"admission_date"}
    assert not any(row["metric"] == "hospitalized_current" for row in observations)
    city = next(row for row in hospitalizations if row["entity_id"] == "new_york_city")
    assert city["value"] == int(last_row["HOSPITALIZED_COUNT"])
    assert city["raw_value"] == last_row["HOSPITALIZED_COUNT"]

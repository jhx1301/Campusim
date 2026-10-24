"""UW audit context must preserve cohort scope and unknown revision boundaries."""

import csv
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTITY = "university_uw_madison"


def manual_context():
    return json.loads((ROOT / "sources/manual_context.json").read_text(encoding="utf-8"))


def test_uw_testing_changes_keep_revision_scope_and_unknown_regime_dates():
    events = {
        row["event_type"]: row for row in manual_context()["events"]
        if row["entity_id"] == ENTITY
    }
    raw = (ROOT / "data/raw/uw_madison_2020.html").read_text(encoding="utf-8")
    revisions = {
        "dashboard_phmdc_integration_updated": ("2020-09-03", "On September 3, 2020"),
        "dashboard_role_and_90day_exclusion_updated": ("2020-09-16", "On September 16"),
        "off_campus_reporting_clock_and_dedup_updated": ("2020-10-02", "On October 2"),
    }
    for kind, (day, anchor) in revisions.items():
        row = events[kind]
        assert anchor in raw
        assert row["date_effective"] == day
        assert row["quality"] == "official_dashboard_revision_backfill_unknown"
        assert row["date_announced"] == row["date_end"] == ""
    regime = events["residence_serial_screening_regime"]
    assert regime["population_group"] == "residence_hall_students"
    assert regime["date_announced"] == regime["date_effective"] == regime["date_end"] == ""
    assert regime["quality"] == "published_research_regime_dates_unknown"
    assert events["campus_testing_sites_expanded"]["date_effective"] == "2020-08-25"
    assert events["campus_testing_site_added"]["date_effective"] == "2020-10-06"


def test_uw_tested_people_are_a_move_in_interval_not_daily_full_campus_coverage():
    populations = {
        row["population_group"]: row for row in manual_context()["populations"]
        if row["entity_id"] == ENTITY
    }
    tested = populations["residence_hall_move_in_tested"]
    cohort = populations["residence_hall_study_cohort"]
    assert tested["value"] == 5820 < cohort["value"] == 6162
    assert (tested["date_start"], tested["date_end"]) == ("2020-08-25", "2020-08-31")
    assert cohort["date_start"] == cohort["date_end"] == "2020-09-22"
    assert tested["quality"] == "published_research_tested_people_interval"
    raw = (ROOT / "data/raw/uw_madison_2020_residence_study.html").read_text(encoding="utf-8")
    assert "5,820/6,162" in raw
    assert "September 22, 2020" in raw
    assert "every 2 weeks" in raw
    records = json.loads((ROOT / "sources/records.json").read_text(encoding="utf-8"))["sources"]
    source = next(row for row in records if row["id"] == "REVIEW-X01")
    assert tested["source_url"] in source["urls"]
    manifest = json.loads((ROOT / "data/download_manifest.json").read_text(encoding="utf-8"))
    archived = next(row for row in manifest if row["file"] == "uw_madison_2020_residence_study.html")
    assert archived["url"] == tested["source_url"]
    assert archived["status"] == "downloaded"


def test_built_uw_context_preserves_all_manual_values_including_unknown_dates():
    context = manual_context()
    for kind in ("events", "populations"):
        expected = [row for row in context[kind] if row["entity_id"] == ENTITY]
        with gzip.open(ROOT / f"data/{kind}.csv.gz", "rt", encoding="utf-8", newline="") as handle:
            actual = [row for row in csv.DictReader(handle) if row["entity_id"] == ENTITY]
        assert len(actual) == len(expected)
        for source, built in zip(expected, actual):
            for key, value in source.items():
                assert built[key] == str(value), (kind, key)

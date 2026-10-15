"""Fetch, build, and verify public historical aggregate observations.

The default command is an offline build from retained public source files.
No simulation, fitted parameters, or current policy recommendations are made.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data"
SOURCES = ROOT / "sources"
if __package__:
    from .normalizers import normalize
    from .school_tables import normalize_case_member, normalize_context, source_csv_members
else:
    sys.path.insert(0, str(ROOT))
    from scripts.normalizers import normalize
    from scripts.school_tables import normalize_case_member, normalize_context, source_csv_members


FIELDS = [
    "dataset_id", "entity_id", "population_group", "observation_scope", "date_start", "date_end",
    "time_basis", "frequency", "metric", "value", "unit", "quality", "source_id", "source_url",
    "source_locator", "raw_value",
]
SOURCE_INFO = {
    "bigten_raw": ("Big Ten 14 university dashboard archive", "bigten_raw.csv", "US-CAMPUS-02", "MPL-2.0 repository; consult original university sources", "14 US universities; cumulative reports, irregular observation dates"),
    "uw_madison_2020": ("UW-Madison 2020 dashboard snapshot", "uw_madison_2020.html", "REVIEW-X01", "University public statistics; no separate data license identified", "Students/employees; on-campus testing; 2020 snapshot"),
    "uw_madison_2021_spring": ("UW-Madison through 2021 spring snapshot", "uw_madison_2021_spring.html", "REVIEW-X01", "University public statistics; no separate data license identified", "Students/employees; on/off-campus results; overlaps 2020 snapshot"),
    "shanghai_2022": ("Shanghai 2022 author-defined geographic aggregates", "shanghai_2022.csv", "CN03", "Paper and supplementary data CC BY 4.0; Git repository has no separate license", "Two author-defined areas; reported symptomatic plus asymptomatic cases; not administrative districts"),
    "nyc_daily": ("NYC and five boroughs historical outcomes", "nyc_daily.csv", "PH01", "Public official repository; no separate data license identified", "NYC and borough residents; metric-specific diagnosis/admission/death dates"),
    "italy_national": ("Italy national historical surveillance", "italy_national.csv", "PH09", "CC BY 4.0", "Italy national reports; cases, deaths, hospital stocks and testing totals"),
    "tianjin_2014": ("Tianjin one-school 2014 ILI outbreak", "tianjin_2014.xlsx", "REVIEW-S03", "PLOS paper and supplementary material CC BY", "One school and one outbreak; symptom-defined ILI, not all infections"),
    "cambridge_2020": ("Cambridge published weekly aggregate panels", "cambridge_2020.xlsx", "UK-CAM-2020", "Nature Communications paper/source data CC BY 4.0", "University Figure2c cohort aggregate and separate Cambridgeshire community weeks; no individual tables normalized"),
}
METRIC_DEFINITIONS = {
    "new_positive_tests": "Published positive-test/case count in the campus table; not inferred infections or automatically deduplicated diagnoses.",
    "new_tests": "Published tests performed/reported; repeated tests are not unique people.",
    "cumulative_tests": "Source cumulative test count; original baseline and corrections retained.",
    "cumulative_people_tested": "Source cumulative tested-person count; distinct from test count.",
    "new_reported_cases": "Source-reported cases in the stated day/interval; case definitions differ across datasets.",
    "cumulative_reported_cases": "Source cumulative reported cases at the observation endpoint; no differencing or baseline reset.",
    "new_confirmed_cases": "Laboratory-confirmed case count using the source case-date definition.",
    "new_probable_cases": "Probable cases, kept separately from confirmed cases.",
    "hospitalized_cases_by_admission_date": "NYC hospitalized cases counted by admission date; not current occupancy or every repeat admission.",
    "hospitalized_current": "Reported hospital occupancy/stock at the observation date, not new admissions.",
    "icu_current": "Reported ICU occupancy/stock, not admissions.",
    "new_icu_admissions": "Source-reported new ICU admissions.",
    "new_deaths": "Source-reported deaths by death date.",
    "cumulative_deaths": "Source cumulative deaths; corrections retained.",
    "active_reported_cases": "Source current/active case stock at the reporting interval endpoint.",
    "reported_cases_14_day_window": "Source two-week case-window statistic; original reporting interval retained, not daily incidence.",
    "new_ili_cases": "Symptom-defined influenza-like illness by onset date, not laboratory-confirmed infections.",
    "university_cohort_cases_figure2c": "Sum of published Figure2c upper-panel categories for each of nine term weeks; paper cohort statistic, not proof of complete campus ascertainment.",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compressed_csv(path, fields, rows):
    """Stable gzip output; return statistics while streaming large school files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    counts, entities, metrics = Counter(), set(), set()
    first_date = last_date = None
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})
                    counts["rows"] += 1
                    if row.get("quality"):
                        counts["quality:" + row["quality"]] += 1
                    if row.get("entity_id"):
                        entities.add(row["entity_id"])
                    if row.get("metric"):
                        metrics.add(row["metric"])
                    start, end = row.get("date_start"), row.get("date_end")
                    if start:
                        first_date = min(first_date, start) if first_date else start
                    if end:
                        last_date = max(last_date, end) if last_date else end
    return {
        "rows": counts.pop("rows", 0), "sha256": sha256(path), "bytes": path.stat().st_size,
        "entity_count": len(entities), "metrics": sorted(metrics),
        "date_start": first_date, "date_end": last_date, "quality_counts": dict(counts),
    }


def manifest():
    records = json.loads((BASE / "download_manifest.json").read_text(encoding="utf-8"))
    return {row["file"]: row for row in records}


def fetch_missing():
    records = manifest()
    for filename, item in records.items():
        path = BASE / "raw" / filename
        if path.exists() and item.get("sha256") == sha256(path):
            continue
        if item.get("status") == "redirected_no_data":
            continue
        try:
            request = urllib.request.Request(item["url"], headers={"User-Agent": "Campusim historical public data research/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read(40_000_001)
                if len(data) > 40_000_000:
                    raise ValueError("Source exceeds the 40 MB per-file limit")
                if filename.endswith((".xlsx", ".zip")) and not data.startswith(b"PK"):
                    raise ValueError("Expected ZIP/XLSX, received another response")
                if filename.endswith(".csv") and data.lstrip().lower().startswith((b"<!doctype", b"<html")):
                    raise ValueError("Expected CSV, received HTML")
                final_url = response.url.split("?")[0]
            path.write_bytes(data)
            item.update(status="downloaded", sha256=sha256(path), bytes=len(data), final_url=final_url,
                        retrieved_at=datetime.now(timezone.utc).isoformat())
            item.pop("error", None)
        except Exception as exc:
            item.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
        print(filename, item["status"], flush=True)
    write_json(BASE / "download_manifest.json", list(records.values()))


def observation_rows(dataset_id, source_id, source_url, rows):
    for row in rows:
        yield {"dataset_id": dataset_id, **row, "source_id": source_id, "source_url": source_url}


def registry():
    """Generate a tabular view from the authoritative structured source records."""
    records = json.loads((SOURCES / "records.json").read_text(encoding="utf-8"))["sources"]
    ids = [row["id"] for row in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source IDs")
    for row in records:
        if not row.get("name") or not row.get("urls") or not all(
            url.startswith(("http://", "https://")) for url in row["urls"]
        ):
            raise ValueError(f"Missing source name or public URL: {row['id']}")
    fields = ["id", "category", "name", "role", "scope", "coverage", "data_types", "granularity", "access", "policy_timeline",
              "population_structure", "contact_network", "abm_use", "strengths", "limitations",
              "urls", "checked_date", "review_file", "review_excerpt", "access_at_initial_review"]
    with (SOURCES / "catalog.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({field: " | ".join(row[field]) if isinstance(row.get(field), list)
                             else row.get(field, "") for field in fields})
    return len(records)


def write_dataset_index(datasets):
    fields = ["id", "title", "date_start", "date_end", "rows", "entity_count", "metrics",
              "calendar_alignment_status", "observations_file", "source_id", "license_note", "sha256"]
    with (BASE / "dataset_index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in datasets:
            writer.writerow({field: " | ".join(row[field]) if isinstance(row.get(field), list)
                             else row.get(field, "") for field in fields})


def build():
    records, datasets, issues, entities = manifest(), [], [], {}
    for source_id, (title, filename, research_id, license_note, scope) in SOURCE_INFO.items():
        path = BASE / "raw" / filename
        if not path.exists() or records[filename].get("sha256") != sha256(path):
            raise ValueError(f"Missing or altered raw source: {filename}")
        relative = f"observations/{source_id}.csv.gz"
        stats = compressed_csv(BASE / relative, FIELDS,
                               observation_rows(source_id, source_id, records[filename]["url"], normalize(source_id, path.read_bytes())))
        datasets.append({"id": source_id, "title": title, "observations_file": relative,
                         "research_source_id": research_id, "source_id": source_id,
                         "scope": scope, "license_note": license_note, **stats})
        print(source_id, stats["rows"], stats["date_start"], stats["date_end"], flush=True)
    source_url = records["csdh_cases.zip"]["url"]
    with ZipFile(BASE / "raw/csdh_cases.zip") as archive:
        for member in source_csv_members(archive):
            stem = Path(member).stem.lower().replace("csdh_", "csdh_cases_")
            relative = f"observations/{stem}.csv.gz"
            start_issues = len(issues)
            stats = compressed_csv(BASE / relative, FIELDS,
                                   observation_rows(stem, "csdh_cases", source_url,
                                                    normalize_case_member(archive, member, issues, entities)))
            date_review = any("source_date_review_required" in key for key in stats["quality_counts"])
            datasets.append({"id": stem, "title": Path(member).stem,
                             "observations_file": relative, "research_source_id": "REVIEW-S01",
                             "source_id": "csdh_cases", "scope": "US K-12 institution aggregates; source school/district level preserved",
                             "license_note": "CSDH attribution requested; consult original state source terms",
                             "quarantined_cells_or_rows": len(issues) - start_issues,
                             "calendar_alignment_status": "requires_source_date_review" if date_review else "source_dates_preserved",
                             **stats})
            print(stem, stats["rows"], "issues", len(issues) - start_issues, flush=True)
    manual = json.loads((SOURCES / "manual_context.json").read_text(encoding="utf-8"))
    populations, events = manual["populations"], manual["events"]
    for kind, row in normalize_context(BASE / "raw/csdh_learning_models.zip", BASE / "raw/csdh_masking.zip", issues):
        row["source_url"] = records[row["source_id"] + ".zip"]["url"]
        (populations if kind == "population" else events).append(row)
    event_fields = ["event_id", "entity_id", "population_group", "observation_scope", "date_announced", "date_effective", "date_end", "event_type", "description", "quality", "source_id", "source_url", "source_locator"]
    for index, row in enumerate(events, 1):
        row["event_id"] = f"historical_event_{index:07d}"
    population_fields = ["entity_id", "population_group", "date_start", "date_end", "reference_period", "value", "definition", "quality", "raw_value", "source_id", "source_url", "source_locator"]
    context = {}
    for filename, fields, rows in (("events.csv.gz", event_fields, events), ("populations.csv.gz", population_fields, populations)):
        context[filename] = compressed_csv(BASE / filename, fields, rows)
    for row in entities.values():
        row.update(source_id="csdh_cases", source_url=source_url)
    context["entities.csv.gz"] = compressed_csv(BASE / "entities.csv.gz",
        ["entity_id", "state", "level", "name", "district_name", "nces_school_id_raw", "nces_district_id_raw", "source_id", "source_url", "source_locator"], entities.values())
    for row in issues:
        locator = row["source_locator"]
        source_id = "csdh_learning_models" if "LearningModel" in locator else "csdh_masking" if "MaskingData" in locator else "csdh_cases"
        row.update(source_id=source_id, source_url=records[source_id + ".zip"]["url"])
    context["quality_issues.csv.gz"] = compressed_csv(BASE / "quality_issues.csv.gz",
        ["source_id", "source_url", "source_locator", "field", "raw_value", "reason"], issues)
    source_count = registry()
    write_dataset_index(datasets)
    write_json(BASE / "catalog.json", {
        "schema_version": "historical-epidemics-v1", "checked_date": "2026-10-15",
        "purpose": "Historical aggregate observations and documented event context; no modeled infections or policy optimization",
        "observation_columns": FIELDS, "metric_definitions": METRIC_DEFINITIONS,
        "source_registry_count": source_count, "raw_manifest": "download_manifest.json",
        "datasets": datasets, "context_tables": context,
        "limitations": ["Datasets can share upstream observations; do not treat archive copies as independent outbreaks.",
                        "Population registration, tested cohorts, and residential populations are not interchangeable.",
                        "Missing/suppressed cells are not zero; bounded source strings are retained in raw_value.",
                        "NCES numeric identifiers are padded to their standard widths; original IDs are retained in entities.csv.gz.",
                        "CSDH school and district statistics must not be copied or summed across nested geographic levels.",
                        "Raw sources and normalized files retain original case definitions; explicit mapping is required for model comparison."]})
    print("BUILT", len(datasets), "datasets", sum(row["rows"] for row in datasets), "observations", source_count, "research sources", flush=True)


def verify():
    catalog = json.loads((BASE / "catalog.json").read_text(encoding="utf-8"))
    if catalog["schema_version"] != "historical-epidemics-v1":
        raise ValueError("Unknown catalogue schema")
    checked = []
    for item in catalog["datasets"]:
        path = BASE / item["observations_file"]
        if sha256(path) != item["sha256"]:
            raise ValueError(f"Altered normalized data: {item['id']}")
        count, first_date, last_date = 0, None, None
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != FIELDS:
                raise ValueError(f"Wrong columns: {item['id']}")
            for row in reader:
                count += 1
                if row["dataset_id"] != item["id"] or not row["source_url"].startswith("https://") or not row["source_locator"]:
                    raise ValueError(f"Missing row provenance: {item['id']} row {count}")
                start, end = datetime.fromisoformat(row["date_start"]).date(), datetime.fromisoformat(row["date_end"]).date()
                if start > end:
                    raise ValueError(f"Reversed interval: {item['id']}")
                if row["value"]:
                    number = float(row["value"])
                    if number != number or abs(number) == float("inf"):
                        raise ValueError("Nonfinite value")
                elif not row["quality"]:
                    raise ValueError("Missing value without quality flag")
                first_date = min(first_date, row["date_start"]) if first_date else row["date_start"]
                last_date = max(last_date, row["date_end"]) if last_date else row["date_end"]
        if (count, first_date, last_date) != (item["rows"], item["date_start"], item["date_end"]):
            raise ValueError(f"Coverage/row-count mismatch: {item['id']}")
        checked.append({"id": item["id"], "rows": count, "sha256": item["sha256"]})
    raw_checked = []
    for filename, item in manifest().items():
        if item["status"] == "downloaded":
            if sha256(BASE / "raw" / filename) != item["sha256"]:
                raise ValueError(f"Altered raw file: {filename}")
            raw_checked.append(filename)
    for filename, item in catalog["context_tables"].items():
        if sha256(BASE / filename) != item["sha256"]:
            raise ValueError(f"Altered context: {filename}")
        with gzip.open(BASE / filename, "rt", encoding="utf-8", newline="") as handle:
            count = 0
            for row in csv.DictReader(handle):
                count += 1
                if not row["source_url"].startswith("https://") or not row["source_locator"]:
                    raise ValueError(f"Missing context provenance: {filename} row {count}")
                for field in ("date_start", "date_end", "date_announced", "date_effective"):
                    if row.get(field):
                        datetime.fromisoformat(row[field])
                start = row.get("date_start") or row.get("date_effective")
                if start and row.get("date_end") and start > row["date_end"]:
                    raise ValueError(f"Reversed context interval: {filename} row {count}")
            if count != item["rows"]:
                raise ValueError(f"Context row-count mismatch: {filename}")
    summary = {"schema_version": catalog["schema_version"], "status": "verified", "datasets": checked,
               "raw_files_checked": raw_checked, "observation_count": sum(row["rows"] for row in checked),
               "context_row_counts": {key: val["rows"] for key, val in catalog["context_tables"].items()},
               "source_registry_count": catalog["source_registry_count"]}
    write_json(BASE / "verification_summary.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key not in {"datasets", "raw_files_checked"}}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "build", "verify"), nargs="?", default="build")
    options = parser.parse_args()
    {"fetch": fetch_missing, "build": build, "verify": verify}[options.command]()

"""Build an offline research supplement; never replace the legacy calibration CSVs."""

import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "derived"
CATEGORIES = ("asymptomatic", "symptomatic", "presymptomatic")
COHORTS = (389, 485, 324)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(name):
    with (RAW / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def clean_text(element):
    return " ".join("".join(element.itertext()).split())


def calendar(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return {(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)}


def build_testing():
    rows = read_csv("COVID_Surveillance_Impact_20200810-20201204.csv")
    output, keys = [], set()
    for line, row in enumerate(rows, 2):
        day = date.fromisoformat(row["CRU_COMPLETED_DATE"]).isoformat()
        tests, positives = int(row["Tested"]), int(row["Positive"])
        key = (day, row["Description"], row["Test_Type"])
        if key in keys or not 0 <= positives <= tests:
            raise ValueError(f"Invalid or duplicate testing row {line}: {row}")
        keys.add(key)
        output.append(dict(date=day, role=row["Description"], test_reason=row["Test_Type"],
                           tests=tests, positive_results=positives,
                           date_basis="CRU_COMPLETED_DATE_definition_unverified",
                           source_id="wastewater_cases", source_row=line))
    write_csv("testing_by_role_reason.csv", output)
    dates = {row["date"] for row in output}
    totals = {}
    for role in sorted({row["role"] for row in output}):
        selected = [row for row in output if row["role"] == role]
        totals[role] = {"tests": sum(row["tests"] for row in selected),
                        "positive_results": sum(row["positive_results"] for row in selected)}
    return {"rows": len(output), "start": min(dates), "end": max(dates),
            "observed_dates": len(dates), "missing_dates": sorted(calendar(min(dates), max(dates)) - dates),
            "roles": sorted(totals), "test_reasons": sorted({row["test_reason"] for row in output}),
            "totals_by_role": totals, "unique_people_verified": False}


def build_wastewater():
    rows = read_csv("NDCampus_ddPCRdata_cleanedrawdata_0s.csv")
    output, seen = [], set()
    for line, row in enumerate(rows, 2):
        day = datetime.strptime(row.pop("Date"), "%m/%d/%Y").date().isoformat()
        if day in seen:
            raise ValueError(f"Duplicate wastewater date: {day}")
        seen.add(day)
        measurements = {k: "" if v in ("NA", "NaN", "") else v for k, v in row.items()}
        available = all(measurements[k] != "" for k in row if k != "WW_flow")
        output.append(dict(date=day, **measurements,
                           rna_status="available" if available else "missing_in_author_file",
                           source_id="wastewater_samples", source_row=line))
    write_csv("wastewater_daily.csv", output)
    available_dates = {row["date"] for row in output if row["rna_status"] == "available"}
    return {"rows": len(output), "start": min(seen), "end": max(seen),
            "complete_rna_dates": len(available_dates),
            "missing_rna_dates": sorted(seen - available_dates),
            "flow_observed_dates": sum(row["WW_flow"] != "" for row in output),
            "paper_vs_file_warning": "Paper says sampling interrupted September 1-9, but file has RNA on September 1 and September 9. No dates were shifted."}


def build_isolation():
    rows = read_csv("Sewage_Sampling_Fall_Data_20210507.csv")
    output, seen = [], set()
    for line, row in enumerate(rows, 2):
        day = date.fromisoformat(row.pop("CRU_COMPLETED_DATE")).isoformat()
        if day in seen:
            raise ValueError(f"Duplicate isolation-linked date: {day}")
        seen.add(day)
        total = int(row["Total_Pos_Daily"])
        for field, numerator in (("prop_off", "Iso_Off_Campus"), ("prop_total", None)):
            value = row[field]
            if value not in ("NA", "NaN", ""):
                count = int(row[numerator]) if numerator else int(row["Iso_Off_Campus"]) + int(row["Iso_On_Campus"])
                if total <= 0 or abs(float(value) - count / total) > 1e-12:
                    raise ValueError(f"Inconsistent published ratio at row {line}")
        output.append(dict(date=day, **row, semantics="author_fields_not_occupancy_verified",
                           source_id="wastewater_fall", source_row=line))
    write_csv("isolation_author_daily.csv", output)
    return {"rows": len(output), "start": min(seen), "end": max(seen),
            "missing_dates": sorted(calendar(min(seen), max(seen)) - seen),
            "occupancy_or_entry_semantics_verified": False,
            "Total_Pos_Daily_sum_not_unique_people": sum(int(row["Total_Pos_Daily"]) for row in output)}


def build_supplement():
    with zipfile.ZipFile(RAW / "phr_europepmc_supplement.zip") as package:
        name = "sj-docx-1-phr-10.1177_00333549221110300.docx"
        with zipfile.ZipFile(io.BytesIO(package.read(name))) as document:
            tree = ET.fromstring(document.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    tables = []
    for table in tree.findall(".//w:tbl", ns):
        tables.append([[" ".join(t.text or "" for t in cell.findall(".//w:t", ns))
                        for cell in row.findall("w:tc", ns)] for row in table.findall("w:tr", ns)])
    if len(tables) != 2:
        raise ValueError("Expected the two published supplementary tables")
    reasons = []
    for cells in tables[0][2:]:
        counts = ["" if c.strip() == "—" else int(c.replace(" ", "")) for c in cells[2:]]
        reasons.append(dict(test_reason=cells[0], tests_administered=int(cells[1].replace(" ", "")),
                            **dict(zip(CATEGORIES, counts)),
                            source_id="phr_europepmc_supplement", locator="Supplementary Table 1",
                            period_start="2020-08-10", period_end="2020-11-20"))
    for category, expected in zip(CATEGORIES, COHORTS):
        if sum(row[category] for row in reasons if row[category] != "") != expected:
            raise ValueError(f"Symptom-cohort count mismatch: {category}")
    write_csv("supplement_testing_reasons.csv", reasons)
    contacts = []
    for cells in tables[1][2:]:
        day = int(cells[0])
        for i, (category, cohort, susceptible) in enumerate(zip(CATEGORIES, COHORTS, (719, 842, 650))):
            match = re.fullmatch(r"([0-9.]+) \(([0-9.]+)-([0-9.]+)\)", cells[2 + i * 2].strip())
            if not match:
                raise ValueError(f"Unexpected SAR cell: {cells}")
            sar, low, high = match.groups()
            infected = int(cells[1 + i * 2])
            if abs(float(sar) - infected / susceptible) > 0.00051:
                raise ValueError(f"Inconsistent rounded SAR: {cells}")
            contacts.append(dict(days_after_index_positive=day, index_category=category,
                                 index_cases=cohort, susceptible_contacts=susceptible,
                                 infected_contacts=infected, sar=sar, ci95_low=low, ci95_high=high,
                                 source_id="phr_europepmc_supplement", locator="Supplementary Table 2"))
    if len(contacts) != 42 or {row["days_after_index_positive"] for row in contacts} != set(range(1, 15)):
        raise ValueError("Incomplete day 1-14 SAR table")
    write_csv("secondary_attack_rates.csv", contacts)
    return {"testing_reason_rows": len(reasons), "sar_rows": len(contacts),
            "symptom_cohort_cases": sum(COHORTS),
            "testing_reason_total_tests": sum(row["tests_administered"] for row in reasons),
            "first_positive_only": True,
            "contact_groups_overlap": True}


def build_demographics():
    tree = ET.parse(RAW / "phr_europepmc.xml")
    table = tree.find(".//table-wrap[@id='table2-00333549221110300']/table")
    output, characteristic = [], None
    for tr in table.findall(".//tr")[1:]:
        cells = [clean_text(cell) for cell in tr]
        if len(cells) == 1:
            characteristic = cells[0]
            continue
        if len(cells) != 4:
            raise ValueError(f"Unexpected demographic row: {cells}")
        for category, cohort, cell in zip(CATEGORIES, COHORTS, cells[1:]):
            match = re.fullmatch(r"(\d+) \(([0-9.]+)\)", cell)
            if not match:
                raise ValueError(f"Unexpected demographic cell: {cell}")
            count, percentage = match.groups()
            output.append(dict(characteristic=characteristic, group=cells[0], symptom_category=category,
                               cases=int(count), category_cases=cohort, percentage=percentage,
                               source_id="phr_europepmc_xml", locator="Main Table"))
    for characteristic in {row["characteristic"] for row in output}:
        for category, expected in zip(CATEGORIES, COHORTS):
            if sum(row["cases"] for row in output if row["characteristic"] == characteristic and row["symptom_category"] == category) != expected:
                raise ValueError("Demographic cells do not sum to the published cohort")
    write_csv("case_demographics.csv", output)
    symptoms = tree.find(".//table-wrap[@id='table1-00333549221110300']/table")
    definitions = [dict(symptom=clean_text(tr[0]), definition=clean_text(tr[1]),
                        source_id="phr_europepmc_xml", locator="Symptom Box")
                   for tr in symptoms.findall(".//tr")[1:]]
    write_csv("symptom_definitions.csv", definitions)
    return {"demographic_rows": len(output), "symptom_definitions": len(definitions),
            "represents_whole_campus": False}


def main():
    # Verify local inputs against archived receipts, including the immutable author revision.
    receipts = {}
    for file in ("download_manifest.json", "multisource_download_manifest.json"):
        for receipt in json.loads((ROOT / file).read_text(encoding="utf-8")):
            if receipt["status"] == "downloaded":
                receipts[receipt["file"]] = receipt
    inputs = ("COVID_Surveillance_Impact_20200810-20201204.csv", "NDCampus_ddPCRdata_cleanedrawdata_0s.csv",
              "Sewage_Sampling_Fall_Data_20210507.csv", "phr_europepmc_supplement.zip", "phr_europepmc.xml")
    for name in inputs:
        if digest(RAW / name) != receipts[name]["sha256"]:
            raise ValueError(f"Input hash differs from download receipt: {name}")
    snapshot = json.loads((ROOT / "source_snapshot_checks.json").read_text(encoding="utf-8"))
    for record in snapshot["files"]:
        if not record["matches"] or digest(RAW / record["file"]) != record["remote_sha256"]:
            raise ValueError(f"Author snapshot hash mismatch: {record['file']}")
    source_ids = {source["id"] for name in ("sources.json", "multisource_sources.json")
                  for source in json.loads((ROOT / name).read_text(encoding="utf-8"))}
    manual_context = {}
    for name in ("context_observations.csv", "events.csv"):
        with (ROOT / name).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if None in row or row["source_id"] not in source_ids:
                raise ValueError(f"Invalid context row in {name}: {row}")
            if name == "context_observations.csv" and not math.isfinite(float(row["value"])):
                raise ValueError(f"Invalid context value: {row}")
            for key in ("announced_on", "effective_start", "effective_end"):
                if row.get(key):
                    date.fromisoformat(row[key])
        manual_context[name] = {"rows": len(rows), "sha256": digest(ROOT / name)}
    OUT.mkdir(exist_ok=True)
    summary = {"testing": build_testing(), "wastewater": build_wastewater(),
               "isolation_linked": build_isolation(), "supplement": build_supplement(),
               "demographics": build_demographics(), "repository_commit": snapshot["repository_commit"],
               "inputs": {name: digest(RAW / name) for name in inputs}, "manual_context": manual_context,
               "outputs": {path.name: digest(path) for path in sorted(OUT.glob("*.csv"))}}
    (OUT / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"testing_dates": summary["testing"]["observed_dates"],
                      "rna_dates": summary["wastewater"]["complete_rna_dates"],
                      "sar_rows": summary["supplement"]["sar_rows"],
                      "output_csv_files": len(summary["outputs"])}, indent=2))


if __name__ == "__main__":
    main()

"""Normalize CSDH institution aggregates without inventing daily incidence."""

import csv
from datetime import datetime
import hashlib
from io import StringIO
from pathlib import PurePosixPath
import re
from zipfile import ZipFile


CASE_FIELDS = {
    "NewCasesCombined": ("new_reported_cases", "combined"),
    "NewCasesStudents": ("new_reported_cases", "students"),
    "NewCasesStaff": ("new_reported_cases", "staff"),
    "NewCasesUnknown": ("new_reported_cases", "unknown"),
    "TwoWeekPeriodStaffStudentCasesCombined": ("reported_cases_14_day_window", "combined"),
    "TwoWeekPeriodCasesStudents": ("reported_cases_14_day_window", "students"),
    "TwoWeekPeriodCasesStaff": ("reported_cases_14_day_window", "staff"),
    "CumulativeCasesCombined": ("cumulative_reported_cases", "combined"),
    "CumulativeCasesStudents": ("cumulative_reported_cases", "students"),
    "CumulativeCasesStaff": ("cumulative_reported_cases", "staff"),
    "CumulativeCasesUnknown": ("cumulative_reported_cases", "unknown"),
    "ActiveCasesCombined": ("active_reported_cases", "combined"),
    "ActiveCasesStudents": ("active_reported_cases", "students"),
    "ActiveCasesStaff": ("active_reported_cases", "staff"),
    "ActiveCasesUnknown": ("active_reported_cases", "unknown"),
}
MISSING = {"", "nan", "na", "n/a", "null", "none"}


def source_csv_members(archive):
    """Exclude macOS resource forks, which also have .csv filenames."""
    return sorted(name for name in archive.namelist()
                  if name.lower().endswith(".csv") and "__MACOSX/" not in name
                  and not PurePosixPath(name).name.startswith("._"))


def csv_rows(archive, member):
    return csv.DictReader(StringIO(archive.read(member).decode("utf-8-sig")))


def iso_date(value):
    value = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised source date: {value!r}")


def entity(row):
    level = row.get("DataLevel", "").strip().lower()
    school = level.startswith("school")
    field = "NCESSchoolID" if school else "NCESDistrictID"
    source_id = row.get(field, "").strip()
    if re.fullmatch(r"\d+\.0", source_id):
        source_id = source_id[:-2]
    if source_id.isdigit():
        # NCES identifiers have fixed widths; spreadsheet exports drop zeros.
        canonical = source_id.zfill(12 if school else 7)
        return f"nces_{'school' if school else 'district'}_{canonical}"
    key = "|".join(row.get(k, "").strip() for k in
                   ("StateAbbrev", "DataLevel", "SchoolName", "DistrictName", "County"))
    return "source_named_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def numeric_value(value):
    """Return exact values, explicit missing/bounded values, or an error."""
    raw = str(value or "").strip()
    if raw.lower() in MISSING:
        return "", "missing"
    if re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        number = float(raw.replace(",", ""))
        return (int(number) if number.is_integer() else number), (
            "negative_source_value" if number < 0 else "observed")
    if re.fullmatch(r"(?:[<>]=?\s*\d+|\d+\s*\+|\d+\s*(?:-|to)\s*\d+)(?:\s*\(.*\))?", raw):
        return "", "suppressed_or_bounded"
    raise ValueError(f"Non-numeric source cell: {raw!r}")


def normalize_case_member(archive, member, issues, entities):
    """Keep stocks at the interval endpoint and flows over the stated interval."""
    for line, row in enumerate(csv_rows(archive, member), 2):
        locator = f"{member}:CSV row {line}"
        try:
            if None in row:
                raise ValueError("CSV row has extra columns")
            start, end = iso_date(row["TimePeriodStart"]), iso_date(row["TimePeriodEnd"])
            if start > end:
                raise ValueError("Source period ends before it starts")
            entity_id = entity(row)
        except (ValueError, KeyError, AttributeError) as exc:
            issues.append({"source_locator": locator, "reason": str(exc), "field": "row", "raw_value": ""})
            continue
        entities.setdefault(entity_id, {
            "entity_id": entity_id, "state": row.get("StateAbbrev", ""),
            "level": row.get("DataLevel", ""), "name": row.get("SchoolName") or row.get("DistrictName", ""),
            "district_name": row.get("DistrictName", ""), "nces_school_id_raw": row.get("NCESSchoolID", ""),
            "nces_district_id_raw": row.get("NCESDistrictID", ""),
            "source_locator": locator,
        })
        for field, (metric, group) in CASE_FIELDS.items():
            raw = row.get(field, "")
            try:
                value, quality = numeric_value(raw)
            except ValueError as exc:
                issues.append({"source_locator": locator, "reason": str(exc), "field": field, "raw_value": raw})
                continue
            if quality == "missing":
                continue
            if "_FL_" in member and start < "2020-08-01":
                # The 2020-21 source package labels Jan-May observations 2020.
                # Keep written dates; never silently shift a year or leap day.
                quality += ";source_date_review_required"
            stock = metric.startswith(("cumulative_", "active_"))
            yield {
                "entity_id": entity_id, "population_group": group,
                "observation_scope": "source_reported_institution",
                "date_start": end if stock else start, "date_end": end,
                "time_basis": "source_interval_end" if stock else "source_reporting_period",
                "frequency": "irregular" if stock else "daily" if start == end else "period",
                "metric": metric, "value": value, "unit": "people",
                "quality": quality, "source_locator": f"{locator}, {field}; original period {start}/{end}",
                "raw_value": raw,
            }


def normalize_context(learning_zip, masking_zip, issues):
    """Yield tagged population/teaching/masking rows using the same NCES keys."""
    for archive_path, kind in ((learning_zip, "learning"), (masking_zip, "masking")):
        with ZipFile(archive_path) as archive:
            for member in source_csv_members(archive):
                for line, row in enumerate(csv_rows(archive, member), 2):
                    locator = f"{member}:CSV row {line}"
                    entity_id = entity(row)
                    if kind == "learning":
                        try:
                            start, end = iso_date(row["TimePeriodStart"]), iso_date(row["TimePeriodEnd"])
                            if start > end:
                                raise ValueError("Source period ends before it starts")
                        except (ValueError, KeyError) as exc:
                            issues.append({"source_locator": locator, "reason": str(exc), "field": "context_dates", "raw_value": ""})
                            continue
                        for field, group in (("EnrollmentTotal", "students"), ("StaffCount", "staff")):
                            try:
                                value, quality = numeric_value(row.get(field, ""))
                            except ValueError as exc:
                                issues.append({"source_locator": locator, "reason": str(exc), "field": field, "raw_value": row.get(field, "")})
                                continue
                            if quality != "missing":
                                yield "population", {
                                    "entity_id": entity_id, "population_group": group,
                                    "date_start": start, "date_end": end, "value": value,
                                    "definition": "source_reported_enrollment" if group == "students" else "source_reported_staff_count_units_not_harmonized",
                                    "quality": quality, "raw_value": row.get(field, ""),
                                    "source_id": "csdh_learning_models", "source_locator": f"{locator}, {field}",
                                }
                        for field, scope in (("LearningModel", "all_grades"), ("LearningModelGrK5", "grades_k5"),
                                             ("LearningModelGr68", "grades_6_8"), ("LearningModelGr912", "grades_9_12")):
                            value = row.get(field, "").strip()
                            if value and value.lower() not in MISSING:
                                yield "event", {
                                    "entity_id": entity_id, "population_group": "students", "observation_scope": scope,
                                    "date_announced": "", "date_effective": start, "date_end": end,
                                    "event_type": "recorded_instruction_mode", "description": value,
                                    "quality": "recorded_period_state", "source_id": "csdh_learning_models",
                                    "source_locator": f"{locator}, {field}",
                                }
                    else:
                        for group, prefix in (("students", "Student"), ("staff", "Staff")):
                            description = row.get(prefix + "MaskPolicy", "").strip()
                            if not description or description.lower() in MISSING:
                                continue
                            intervals = []
                            for index in (1, 2):
                                raw_start, raw_end = row.get(f"{prefix}MaskStart{index}", ""), row.get(f"{prefix}MaskEnd{index}", "")
                                try:
                                    start = iso_date(raw_start) if raw_start.strip().lower() not in MISSING else ""
                                    end = iso_date(raw_end) if raw_end.strip().lower() not in MISSING else ""
                                except ValueError as exc:
                                    issues.append({"source_locator": locator, "reason": str(exc), "field": prefix + "MaskDates", "raw_value": f"{raw_start}/{raw_end}"})
                                    continue
                                if start or end:
                                    intervals.append((start, end))
                            for start, end in intervals or [("", "")]:
                                yield "event", {
                                    "entity_id": entity_id, "population_group": group, "observation_scope": "school_year_2020_2021",
                                    "date_announced": "", "date_effective": start, "date_end": end,
                                    "event_type": "recorded_mask_policy", "description": description,
                                    "quality": "recorded_policy" if start else "effective_date_not_reported",
                                    "source_id": "csdh_masking", "source_locator": f"{locator}, {prefix}MaskPolicy",
                                }

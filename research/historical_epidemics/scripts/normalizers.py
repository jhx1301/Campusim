"""Normalize selected published aggregate observations without model assumptions.

Every output retains its source cell/column and original text. Cumulative values
are not differenced, missing values stay missing, and zero remains an observation.
Source identity and provenance URLs are supplied by the caller's catalog.
"""

import csv
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from io import StringIO
import json
import math
import re

from .format_parsers import parse_html_tables, parse_xlsx_rows


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_SHORT_DATE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})$")
_MISSING = {"", "na", "n/a", "n.a.", "nan", "null", "none", "-", "--", "–", "—", "not reported"}


def _number(raw_value, locator, *, percentage_cell=False):
    if raw_value is None:
        return None, "missing"
    text = str(raw_value).replace("\u00ad", "").strip()
    if text.lower() in _MISSING:
        return None, "missing"
    if re.match(r"^[<>≤≥*]", text):
        return None, "suppressed"
    if percentage_cell:
        match = re.fullmatch(r"([+-]?[\d,]+(?:\.\d+)?)\s*(?:\([^)]*\))?", text)
        if match is None:
            raise ValueError(f"Unexpected count/percentage cell at {locator}: {text!r}")
        text = match.group(1)
    try:
        number = float(text.replace(",", ""))
    except ValueError as error:
        raise ValueError(f"Non-numeric observation at {locator}: {text!r}") from error
    if not math.isfinite(number):
        return None, "missing"
    return (int(number) if number.is_integer() else number), "observed"


def _observation(*, entity, group, scope, start, metric, raw_value, locator,
                 time_basis, unit, frequency="daily", end=None,
                 percentage_cell=False, flags=()):
    value, quality = _number(raw_value, locator, percentage_cell=percentage_cell)
    if flags:
        quality = ";".join(([quality] if quality != "observed" else []) + list(flags))
    return {
        "entity_id": entity,
        "population_group": group,
        "observation_scope": scope,
        "date_start": start.isoformat(),
        "date_end": (end or start).isoformat(),
        "time_basis": time_basis,
        "frequency": frequency,
        "metric": metric,
        "value": value,
        "unit": unit,
        "quality": quality,
        "source_locator": locator,
        "raw_value": "" if raw_value is None else str(raw_value),
    }


def _csv_rows(raw):
    yield from enumerate(csv.DictReader(StringIO(raw.decode("utf-8-sig"))), start=2)


def _bigten(raw):
    for row_number, row in _csv_rows(raw):
        start = date.fromisoformat(row["Date"])
        slug = re.sub(r"[^a-z0-9]+", "_", row["Country_Region"].lower()).strip("_")
        for column, metric, unit in (
            ("Confirmed", "cumulative_reported_cases", "cases"),
            ("Tests", "cumulative_tests", "tests"),
        ):
            yield _observation(
                entity="university_" + slug, group="all_reported", scope="campus_dashboard",
                start=start, metric=metric, raw_value=row[column],
                locator=f"csv:row={row_number};column={column}",
                time_basis="dashboard_date", unit=unit, frequency="irregular",
            )


def _short_date(text):
    match = _SHORT_DATE.fullmatch(text.replace("\u00ad", "").strip())
    if match is None or match.group(1).lower() not in _MONTHS:
        return None
    return _MONTHS[match.group(1).lower()], int(match.group(2))


def _wisconsin(raw, spring):
    columns = [
        (1, "students", "on_campus_testing", "new_positive_tests"),
        (2, "students", "on_campus_testing", "new_tests"),
        (3, "employees", "on_campus_testing", "new_positive_tests"),
        (4, "employees", "on_campus_testing", "new_tests"),
    ]
    if spring:
        columns.extend([
            (5, "students", "off_campus_testing", "new_positive_tests"),
            (6, "employees", "off_campus_testing", "new_positive_tests"),
        ])
    for table_number, table in enumerate(parse_html_tables(raw), start=1):
        year = 2021 if spring else 2020
        previous = None
        for row_number, row in enumerate(table, start=1):
            month_day = _short_date(row[0]) if row else None
            if month_day is None:
                continue
            if len(row) != (7 if spring else 5):
                raise ValueError(f"Unexpected Wisconsin table width: table {table_number}, row {row_number}")
            # Source tables run backwards. December after January belongs to
            # the previous year, including in the page labelled Spring 2021.
            if previous is not None and month_day > previous:
                year -= 1
            previous = month_day
            start = date(year, *month_day)
            for column, group, scope, metric in columns:
                yield _observation(
                    entity="university_uw_madison", group=group, scope=scope, start=start,
                    metric=metric, raw_value=row[column],
                    locator=f"html:table={table_number};row={row_number};column={column + 1}",
                    time_basis="dashboard_date", unit="tests", percentage_cell=True,
                )


def _shanghai(raw):
    for row_number, row in _csv_rows(raw):
        for column, entity in (("pd_case", "shanghai_author_pd"), ("px_case", "shanghai_author_px")):
            yield _observation(
                entity=entity, group="all_reported", scope="author_community_aggregate",
                start=date.fromisoformat(row["date"]), metric="new_reported_cases",
                raw_value=row[column], locator=f"csv:row={row_number};column={column}",
                time_basis="report_date", unit="cases",
            )


def _nyc(raw):
    entities = [
        ("", "new_york_city"), ("BX_", "nyc_bronx"), ("BK_", "nyc_brooklyn"),
        ("MN_", "nyc_manhattan"), ("QN_", "nyc_queens"), ("SI_", "nyc_staten_island"),
    ]
    metrics = [
        ("CASE_COUNT", "new_confirmed_cases", "diagnosis_date", "cases"),
        ("PROBABLE_CASE_COUNT", "new_probable_cases", "diagnosis_date", "cases"),
        ("HOSPITALIZED_COUNT", "hospitalized_cases_by_admission_date", "admission_date", "people"),
        ("DEATH_COUNT", "new_deaths", "death_date", "deaths"),
    ]
    for row_number, row in _csv_rows(raw):
        start = datetime.strptime(row["date_of_interest"], "%m/%d/%Y").date()
        incomplete = row.get("INCOMPLETE", "").strip()
        flags = ()
        if incomplete == "1":
            flags = ("incomplete",)
        elif incomplete not in {"", "0"}:
            # The downloaded historical file contains 61030, not a boolean.
            # Preserve the flag without interpreting its undocumented encoding.
            flags = ("source_incomplete_flag=" + incomplete,)
        for prefix, entity in entities:
            for suffix, metric, time_basis, unit in metrics:
                column = prefix + suffix
                yield _observation(
                    entity=entity, group="all_reported", scope="community_surveillance",
                    start=start, metric=metric, raw_value=row[column],
                    locator=f"csv:row={row_number};column={column}",
                    time_basis=time_basis, unit=unit, flags=flags,
                )


def _italy(raw):
    metrics = [
        ("nuovi_positivi", "new_reported_cases", "cases"),
        ("totale_casi", "cumulative_reported_cases", "cases"),
        ("deceduti", "cumulative_deaths", "deaths"),
        ("totale_ospedalizzati", "hospitalized_current", "people"),
        ("terapia_intensiva", "icu_current", "people"),
        ("ingressi_terapia_intensiva", "new_icu_admissions", "admissions"),
        ("tamponi", "cumulative_tests", "tests"),
        ("casi_testati", "cumulative_people_tested", "people"),
        ("totale_positivi", "active_reported_cases", "cases"),
    ]
    for row_number, row in _csv_rows(raw):
        # DPC timestamps are local publication times; preserve the written day.
        start = date.fromisoformat(row["data"][:10])
        for column, metric, unit in metrics:
            yield _observation(
                entity="italy", group="all_reported", scope="national_surveillance",
                start=start, metric=metric, raw_value=row[column],
                locator=f"csv:row={row_number};column={column}",
                time_basis="report_date", unit=unit,
            )


def _tianjin(raw):
    rows = parse_xlsx_rows(raw)["Sheet1"]
    if not rows or rows[0][:2] != ["Onset date", "ILI"]:
        raise ValueError("Unexpected Tianjin Sheet1 header")
    for row_number, row in enumerate(rows[1:], start=2):
        if not row or row[0] is None:
            continue
        start = row[0].date() if isinstance(row[0], datetime) else row[0]
        if not isinstance(start, date):
            raise ValueError(f"Tianjin date is not an XLSX date at row {row_number}")
        yield _observation(
            entity="tianjin_school_outbreak_2014", group="students", scope="school_ili_surveillance",
            start=start, metric="new_ili_cases", raw_value=row[1] if len(row) > 1 else None,
            locator=f"xlsx:sheet=Sheet1;row={row_number};column=B",
            time_basis="onset_date", unit="cases",
        )


def _cambridge(raw):
    sheets = parse_xlsx_rows(raw)
    community = sheets["Supplementary_Figure_1"]
    if not community or community[0][:2] != ["week_commencing", "Cambridgeshire_cases"]:
        raise ValueError("Unexpected Cambridge community header")
    for row_number, row in enumerate(community[1:], start=2):
        if not row or row[0] is None:
            continue
        start = row[0].date() if isinstance(row[0], datetime) else row[0]
        if not isinstance(start, date):
            raise ValueError(f"Cambridge week is not an XLSX date at row {row_number}")
        yield _observation(
            entity="cambridgeshire", group="all_reported", scope="community_surveillance",
            start=start, end=start + timedelta(days=6), frequency="weekly",
            metric="new_reported_cases", raw_value=row[1] if len(row) > 1 else None,
            locator=f"xlsx:sheet=Supplementary_Figure_1;row={row_number};column=B",
            time_basis="week_commencing", unit="cases",
        )
    # Only the upper aggregate panel is eligible. Later rows describe another
    # population; sample/individual sheets are never converted to observations.
    for row_number, row in enumerate(sheets["Figure2c"][:12], start=1):
        month_day = _short_date(row[1]) if len(row) > 1 and isinstance(row[1], str) else None
        if month_day is None:
            continue
        start = date(2020, *month_day)
        if not date(2020, 10, 5) <= start <= date(2020, 11, 30):
            continue
        locator = f"xlsx:sheet=Figure2c;row={row_number};columns=C:L"
        cells = row[2:12]
        if len(cells) != 10:
            raise ValueError(f"Incomplete Cambridge upper panel at {locator}")
        numbers = [_number(cell, locator)[0] for cell in cells]
        total = sum(numbers) if all(number is not None for number in numbers) else None
        observation = _observation(
            entity="university_cambridge", group="figure2c_cohort", scope="figure2c_cohort",
            start=start, end=start + timedelta(days=6), frequency="weekly",
            metric="university_cohort_cases_figure2c", raw_value=total, locator=locator,
            time_basis="week_commencing", unit="cases",
            flags=("derived_sum_figure_cohort_not_full_campus",),
        )
        observation["raw_value"] = json.dumps(cells, ensure_ascii=False)
        yield observation


def normalize(source_id: str, raw: bytes) -> Iterator[dict]:
    """Yield observations from a supported aggregate source; unknown IDs fail.

    Wisconsin snapshot overlaps are intentionally preserved by separate calls.
    NYC nonboolean INCOMPLETE flags retain their source text in quality. No
    epidemiological parameters, contact edges or individual records are emitted.
    """
    parsers = {
        "bigten_raw": _bigten,
        "uw_madison_2020": lambda data: _wisconsin(data, False),
        "uw_madison_2021_spring": lambda data: _wisconsin(data, True),
        "shanghai_2022": _shanghai,
        "nyc_daily": _nyc,
        "italy_national": _italy,
        "tianjin_2014": _tianjin,
        "cambridge_2020": _cambridge,
    }
    if source_id not in parsers:
        raise ValueError(f"Unsupported historical aggregate source: {source_id!r}")
    yield from parsers[source_id](raw)

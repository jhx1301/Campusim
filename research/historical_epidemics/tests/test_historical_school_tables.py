"""Check source semantics that could silently change historical case counts."""

import csv
from io import StringIO
from zipfile import ZipFile

from research.historical_epidemics.scripts.school_tables import (
    entity, normalize_case_member, normalize_context, numeric_value, source_csv_members,
)


def write_archive(path, name, rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    with ZipFile(path, "w") as archive:
        archive.writestr(name, stream.getvalue())


def test_source_nces_identifiers_are_not_float_rounded():
    assert entity({"DataLevel": "District", "NCESDistrictID": "100197"}) == "nces_district_0100197"
    assert entity({"DataLevel": "School", "NCESSchoolID": "010000100001"}) == "nces_school_010000100001"


def test_bounded_values_are_never_midpoint_imputed():
    assert numeric_value("0") == (0, "observed")
    assert numeric_value("nan") == ("", "missing")
    assert numeric_value("  8,563.2") == (8563.2, "observed")
    for text in ("5-10 (Statt & Students)", "16+", "35 to 39", "<5"):
        assert numeric_value(text) == ("", "suppressed_or_bounded")


def test_stocks_keep_endpoints_and_bad_cells_do_not_erase_valid_counts(tmp_path):
    path = tmp_path / "cases.zip"
    row = {"DataLevel": "District", "NCESDistrictID": "100197", "TimePeriodStart": "10/11/20",
           "TimePeriodEnd": "10/17/20", "NewCasesStudents": "0", "CumulativeCasesStudents": "8",
           "ActiveCasesCombined": "Regular local school district"}
    write_archive(path, "source.csv", [row])
    issues, entities = [], {}
    with ZipFile(path) as archive:
        observations = list(normalize_case_member(archive, "source.csv", issues, entities))
    assert len(observations) == 2
    flow, stock = observations
    assert (flow["date_start"], flow["date_end"], flow["value"]) == ("2020-10-11", "2020-10-17", 0)
    assert stock["date_start"] == stock["date_end"] == "2020-10-17"
    assert issues[0]["field"] == "ActiveCasesCombined"
    assert issues[0]["raw_value"] == "Regular local school district"


def test_archive_resource_forks_are_not_parsed_as_data(tmp_path):
    path = tmp_path / "source.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("cases.csv", "x\n1\n")
        archive.writestr("__MACOSX/._cases.csv", b"not csv")
    with ZipFile(path) as archive:
        assert source_csv_members(archive) == ["cases.csv"]


def test_florida_written_year_is_preserved_and_flagged(tmp_path):
    path = tmp_path / "cases.zip"
    name = "CSDH_FL_COVID_Schools.csv"
    write_archive(path, name, [{"DataLevel": "School", "NCESSchoolID": "120003000019",
        "TimePeriodStart": "01/04/20", "TimePeriodEnd": "01/18/20", "ActiveCasesStudents": "2"}])
    with ZipFile(path) as archive:
        row = next(normalize_case_member(archive, name, [], {}))
    assert row["date_start"] == row["date_end"] == "2020-01-18"
    assert "source_date_review_required" in row["quality"]


def test_mask_policy_without_dates_stays_undated(tmp_path):
    learning, masking = tmp_path / "learning.zip", tmp_path / "masking.zip"
    with ZipFile(learning, "w"):
        pass
    write_archive(masking, "policy.csv", [{"DataLevel": "District", "NCESDistrictID": "100197",
        "StudentMaskPolicy": "Required full school year", "StudentMaskStart1": "", "StudentMaskEnd1": ""}])
    rows = list(normalize_context(learning, masking, []))
    assert len(rows) == 1
    kind, row = rows[0]
    assert kind == "event"
    assert row["date_effective"] == row["date_end"] == ""
    assert row["quality"] == "effective_date_not_reported"

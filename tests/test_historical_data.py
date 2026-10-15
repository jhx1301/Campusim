"""Historical data integrity and conversion checks using local public-style fixtures."""

import csv
import gzip
import hashlib
import json

import pandas as pd
import pytest

from cemas.historical_data import (
    OBSERVATION_COLUMNS, SCHEMA_VERSION, list_datasets, load_observations,
    to_covasim_data,
)


def test_default_data_location_reads_consolidated_research_package():
    datasets = {item["id"] for item in list_datasets()}
    assert "uw_madison_2020" in datasets
    frame = load_observations(
        "uw_madison_2020", entity_id="university_uw_madison", population_group="students",
        observation_scope="on_campus_testing",
    )
    positives = frame[frame["metric"] == "new_positive_tests"]
    assert len(positives) == 137
    assert positives["value"].sum() == 3704


def observation(**changes):
    row = dict.fromkeys(OBSERVATION_COLUMNS, "")
    row.update(
        dataset_id="campus-test", entity_id="campus", population_group="students",
        observation_scope="on-campus-tests", date_start="2020-10-05",
        date_end="2020-10-05", time_basis="sample_date", frequency="irregular",
        metric="positive_tests_cumulative", value="120", unit="tests",
        quality="reported", source_id="official", source_url="https://example.org/archive",
        source_locator="Table 1",
    )
    row.update(changes)
    return row


def write_dataset(root, rows, *, columns=OBSERVATION_COLUMNS):
    directory = root / "observations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "campus.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "datasets": [{
            "id": "campus-test", "title": "Historical campus fixture",
            "observations_file": "observations/campus.csv",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }],
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return catalog, path


def conversion(root, metric_map=None, **filters):
    selection = dict(entity_id="campus", population_group="students", observation_scope="on-campus-tests")
    selection.update(filters)
    return to_covasim_data(
        "campus-test", data_root=root,
        metric_map=metric_map if metric_map is not None else {"positive_tests_cumulative": "cum_diagnoses"},
        **selection,
    )


def test_metadata_filtering_and_missing_values_are_preserved(tmp_path):
    write_dataset(tmp_path, [
        observation(), observation(date_start="2020-10-07", date_end="2020-10-07", value=""),
        observation(population_group="staff", value="3"),
        observation(entity_id="other", value="8"),
        observation(observation_scope="external-reports", value="4"),
    ])
    assert list_datasets(tmp_path)[0]["id"] == "campus-test"
    frame = load_observations(
        "campus-test", entity_id="campus", population_group="students",
        observation_scope="on-campus-tests", data_root=tmp_path,
    )
    assert len(frame) == 2
    assert frame.iloc[0]["value"] == 120
    assert pd.isna(frame.iloc[1]["value"])
    assert frame.iloc[0]["date_start"] == pd.Timestamp("2020-10-05")
    assert frame.iloc[0]["source_locator"] == "Table 1"


def test_covasim_mapping_preserves_irregular_dates_cumulative_levels_and_missing_cells(tmp_path):
    write_dataset(tmp_path, [
        observation(), observation(date_start="2020-10-07", date_end="2020-10-07", value="125"),
        observation(metric="tests", value="0"),
        observation(metric="tests", date_start="2020-10-07", date_end="2020-10-07", value=""),
        observation(metric="unmapped_context", value="42"),
    ])
    frame = conversion(tmp_path, {"positive_tests_cumulative": "cum_diagnoses", "tests": "new_tests"})
    assert list(frame.columns) == ["date", "cum_diagnoses", "new_tests"]
    assert list(frame.index) == [pd.Timestamp("2020-10-05"), pd.Timestamp("2020-10-07")]
    assert frame["date"].tolist() == frame.index.tolist()
    assert frame["cum_diagnoses"].tolist() == [120, 125]
    assert frame.iloc[0]["new_tests"] == 0
    assert pd.isna(frame.iloc[1]["new_tests"])


def test_hash_mismatch_is_rejected_and_explicit_opt_out_still_validates_data(tmp_path):
    _, path = write_dataset(tmp_path, [observation()])
    path.write_text(path.read_text(encoding="utf-8").replace(",120,", ",121,"), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_observations("campus-test", data_root=tmp_path)
    assert load_observations("campus-test", data_root=tmp_path, verify_hash=False).iloc[0]["value"] == 121


def test_flagged_source_dates_can_be_inspected_but_not_silently_aligned(tmp_path):
    write_dataset(tmp_path, [observation(quality="observed;source_date_review_required")])
    assert len(load_observations("campus-test", data_root=tmp_path)) == 1
    with pytest.raises(ValueError, match="Source dates require review"):
        conversion(tmp_path)


def test_gzip_hash_uses_stored_bytes_and_preserves_suppressed_raw_value(tmp_path):
    catalog, path = write_dataset(
        tmp_path, [observation(value="", raw_value="<5", quality="suppressed_or_bounded")],
        columns=(*OBSERVATION_COLUMNS, "raw_value"),
    )
    compressed = path.with_suffix(".csv.gz")
    compressed.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    catalog["datasets"][0].update(
        observations_file="observations/campus.csv.gz",
        sha256=hashlib.sha256(compressed.read_bytes()).hexdigest(),
    )
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    frame = load_observations("campus-test", data_root=tmp_path)
    assert pd.isna(frame.iloc[0]["value"])
    assert frame.iloc[0]["raw_value"] == "<5"
    assert frame.iloc[0]["quality"] == "suppressed_or_bounded"
    catalog["datasets"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_observations("campus-test", data_root=tmp_path)


@pytest.mark.parametrize("relative", ["../outside.csv", "C:\\outside.csv"])
def test_catalog_paths_cannot_escape_root(tmp_path, relative):
    catalog, _ = write_dataset(tmp_path, [observation()])
    catalog["datasets"][0]["observations_file"] = relative
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="data_root"):
        list_datasets(tmp_path)


def test_absolute_catalog_path_is_rejected(tmp_path):
    catalog, path = write_dataset(tmp_path, [observation()])
    catalog["datasets"][0]["observations_file"] = str(path.resolve())
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        load_observations("campus-test", data_root=tmp_path)


def test_unknown_and_invalid_dataset_ids_are_rejected(tmp_path):
    write_dataset(tmp_path, [observation()])
    with pytest.raises(ValueError, match="dataset_id"):
        load_observations("../campus-test", data_root=tmp_path)
    with pytest.raises(KeyError, match="Unknown dataset_id"):
        load_observations("unknown", data_root=tmp_path)


def test_catalog_schema_and_duplicate_ids_are_rejected(tmp_path):
    catalog, _ = write_dataset(tmp_path, [observation()])
    catalog["schema_version"] = "future-format"
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        list_datasets(tmp_path)
    catalog["schema_version"] = SCHEMA_VERSION
    catalog["datasets"].append(catalog["datasets"][0].copy())
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate dataset_id"):
        list_datasets(tmp_path)


def test_missing_observation_columns_are_rejected(tmp_path):
    write_dataset(tmp_path, [observation()], columns=[name for name in OBSERVATION_COLUMNS if name != "time_basis"])
    with pytest.raises(ValueError, match="Missing observation columns.*time_basis"):
        load_observations("campus-test", data_root=tmp_path)


@pytest.mark.parametrize("change,error", [
    ({"date_start": "2020-02-30"}, "Invalid date_start"),
    ({"date_start": "2020-10-06"}, "date_start must not be later"),
    ({"date_end": "2020/10/05"}, "ISO dates"),
    ({"value": "not reported"}, "must be numeric"),
    ({"value": "inf"}, "finite"),
    ({"dataset_id": "another-dataset"}, "does not match"),
])
def test_invalid_observations_are_rejected(tmp_path, change, error):
    write_dataset(tmp_path, [observation(**change)])
    with pytest.raises(ValueError, match=error):
        load_observations("campus-test", data_root=tmp_path)


def test_weekly_intervals_remain_loadable_but_cannot_be_converted(tmp_path):
    write_dataset(tmp_path, [observation(date_end="2020-10-11", frequency="weekly")])
    assert len(load_observations("campus-test", data_root=tmp_path)) == 1
    with pytest.raises(ValueError, match="point observations"):
        conversion(tmp_path)


def test_duplicate_date_metric_is_not_averaged_or_summed(tmp_path):
    write_dataset(tmp_path, [observation(), observation(source_id="another-report", value="121")])
    with pytest.raises(ValueError, match="Duplicate observations"):
        conversion(tmp_path)


@pytest.mark.parametrize("mapping,error", [
    ({}, "nonempty mapping"),
    ({"unavailable": "new_diagnoses"}, "absent from the selected"),
    ({"positive_tests_cumulative": "date"}, "reserved date"),
    ({"positive_tests_cumulative": "cum_diagnoses", "tests": "cum_diagnoses"}, "distinct column"),
])
def test_implicit_or_ambiguous_mappings_are_rejected(tmp_path, mapping, error):
    write_dataset(tmp_path, [observation()])
    with pytest.raises(ValueError, match=error):
        conversion(tmp_path, mapping)

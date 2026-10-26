"""Acceptance checks for the continuous UW replay observation table."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from cemas.historical_data import load_observations
from tools import build_uw_e0_data as builder


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def observed():
    return load_observations(builder.DATASET_ID, entity_id=builder.ENTITY_ID,
                             observation_scope=builder.SCOPE)


def test_replay_preserves_all_observations_and_old_windows(observed):
    path = ROOT / "data/uw_madison_2020_replay.csv"
    replay = pd.read_csv(path)
    expected = builder._window_frame(observed, *builder.WINDOWS["replay"])
    assert replay.to_dict("records") == expected
    assert list(replay.columns) == list(builder.COLUMNS)
    assert replay["date"].tolist() == pd.date_range("2020-08-17", "2020-10-30").strftime("%Y-%m-%d").tolist()
    pd.testing.assert_frame_equal(replay.iloc[:21].reset_index(drop=True),
                                  pd.read_csv(ROOT / "data/uw_madison_2020_w1.csv"))
    pd.testing.assert_frame_equal(replay.iloc[40:].reset_index(drop=True),
                                  pd.read_csv(ROOT / "data/uw_madison_2020_w2w3.csv"))
    assert replay.loc[replay["date"] == "2020-08-24", list(builder.COLUMNS[1:])].sum(axis=1).item() == 0
    assert builder._totals(expected)["groups"] == {
        "students": {"positive": 2440, "tests": 76244},
        "employees": {"positive": 92, "tests": 8004},
    }


def test_replay_provenance_and_intervention_source_hashes():
    provenance = json.loads((ROOT / "data/uw_madison_2020_replay.provenance.json").read_text(encoding="utf-8"))
    for field, digest in (("derived_file", "derived_sha256"),
                          ("source_observations_file", "source_observations_sha256"),
                          ("source_raw_file", "source_raw_sha256"),
                          ("intervention_sources_file", "intervention_sources_sha256")):
        assert hashlib.sha256((ROOT / provenance[field]).read_bytes()).hexdigest() == provenance[digest]
    assert provenance["rows"] == 75
    assert [provenance["windows"][window]["rows"] for window in ("w1", "w2", "w3")] == [21, 19, 35]
    assert provenance["windows"]["w2"]["groups"] == {
        "students": {"positive": 1393, "tests": 20457},
        "employees": {"positive": 11, "tests": 1706},
    }
    sources = json.loads((ROOT / provenance["intervention_sources_file"]).read_text(encoding="utf-8"))
    dashboard, extension = sources["sources"]
    assert hashlib.sha256((ROOT / dashboard["archive_file"]).read_bytes()).hexdigest() == dashboard["archive_sha256"]
    assert extension["published_on"] == "2020-09-18"
    assert extension["verified_events"][0]["end_date"] == "2020-09-25"


def test_replay_rejects_duplicate_raw_records(observed):
    row = observed[observed["date_start"] == pd.Timestamp("2020-09-07")].iloc[[0]]
    duplicated = pd.concat([observed, row], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate"):
        builder._window_frame(duplicated, *builder.WINDOWS["replay"])


@pytest.mark.parametrize("day", ["2020-08-17", "2020-09-07", "2020-10-30"])
def test_replay_rejects_missing_dates_including_endpoints(observed, day):
    incomplete = observed[observed["date_start"] != pd.Timestamp(day)]
    with pytest.raises(ValueError, match="every date"):
        builder._window_frame(incomplete, *builder.WINDOWS["replay"])


def test_replay_rejects_missing_group_series_value(observed):
    incomplete = observed.drop(observed[(observed["date_start"] == pd.Timestamp("2020-09-07")) &
                                        (observed["population_group"] == "employees") &
                                        (observed["metric"] == "new_tests")].index)
    with pytest.raises(ValueError, match="missing days"):
        builder._window_frame(incomplete, *builder.WINDOWS["replay"])


def test_replay_validates_window_totals_before_writing(observed, tmp_path):
    changed = observed.copy()
    mask = ((changed["date_start"] == pd.Timestamp("2020-09-07")) &
            (changed["population_group"] == "students") &
            (changed["metric"] == "new_positive_tests"))
    changed.loc[mask, "value"] += 1
    output = tmp_path / "replay.csv"
    with pytest.raises(ValueError, match="Replay w2"):
        builder.build("replay", changed, output, tmp_path / "provenance.json", False)
    assert not output.exists()


def test_replay_only_does_not_build_existing_e0_tables(monkeypatch):
    calls = []
    monkeypatch.setattr(builder, "load_observations", lambda *args, **kwargs: object())

    def fake_build(name, frame, output, provenance, force):
        calls.append(name)
        return {"name": name, "rows": 75, "totals": {"positive": 2532, "tests": 84248},
                "output": str(output)}

    monkeypatch.setattr(builder, "build", fake_build)
    assert builder.main(["--replay-only"]) == 0
    assert calls == ["replay"]

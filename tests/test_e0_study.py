"""Tests for the UW E0 data, loss, scan/fit orchestration, and CLI."""

import json
from pathlib import Path

import numpy as np
import pytest

from cemas.e0 import study as cal
from cemas.e0.data import load_e0_config, load_e0_data


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/e0_protocol_v2.json"
DATA = ROOT / "data/uw_madison_2020_w1.csv"


@pytest.fixture(scope="module")
def loaded():
    config = load_e0_config(CONFIG)
    data = load_e0_data(config)
    return config, data


def _fake_world(config, data, beta, seed, *, initial_infections=None, symp_test=None):
    days = len(data["dates"])
    base = np.linspace(1.0, 12.0, days) * (beta / 0.02)
    positives = np.maximum(0, np.round(base + (seed % 3) * 0.1)).astype(int)
    tests = [int(a) + int(b) for a, b in zip(data["groups"]["students"]["tests"],
                                              data["groups"]["employees"]["tests"])]
    zeros = [0] * days
    return {
        "beta": float(beta), "seed": seed, "dates": list(data["dates"]),
        "groups": {"students": {"positive": positives.tolist(), "tests": tests},
                   "employees": {"positive": zeros, "tests": [0] * days}},
        "requested_tests": tests, "requested_vs_actual": None,
        "r_eff": [2.0] * days, "population": config["population"],
        "roles": {"students": 1, "employees": 1},
        "group_test_weights": {"students": 1.0, "employees": 1.0},
        "actual_test_share": {"students": 1.0, "employees": 0.0},
        "resolved_parameters": {"beta": float(beta)},
        "config_sha256": config.get("config_sha256"),
    }


def test_data_and_provenance_are_frozen(loaded):
    config, data = loaded
    assert len(data["dates"]) == 21
    assert data["dates"][0] == "2020-08-17"
    assert data["dates"][-1] == "2020-09-06"
    assert data["totals"] == {"positive": 589, "tests": 18314}
    assert sum(data["groups"]["students"]["positive"]) == 584
    assert sum(data["groups"]["employees"]["tests"]) == 1637
    assert data["provenance"]["window"] == ["2020-08-17", "2020-09-06"]
    assert data["provenance"]["derived_sha256"] == data["sha256"]
    assert sum(config["scan_seeds"]) + sum(config["fit_seeds"]) + sum(config["evaluation_seeds"]) > 0


def test_calibration_loss_hand_examples():
    assert cal.calibration_loss([1, 2, 3], [1, 1, 1]) == pytest.approx(10 / 9)
    assert cal.calibration_loss([2] * 7, [1] * 7, "weekly") == pytest.approx(1.0)
    assert cal.calibration_loss([1] * 14, [1] * 14, "weekly") == pytest.approx(0.0)
    with pytest.raises(ValueError):
        cal.calibration_loss([1] * 8, [1] * 8, "weekly")
    with pytest.raises(ValueError):
        cal.calibration_loss([1, 2], [0, 0])


def test_align_world_moves_positives_tests_and_tail():
    world = {"dates": ["2020-08-17", "2020-08-18", "2020-08-19"],
             "groups": {"students": {"positive": [1, 2, 3], "tests": [10, 20, 30]},
                        "employees": {"positive": [0, 1, 0], "tests": [1, 2, 3]}},
             "requested_tests": [11, 22, 33]}
    aligned = cal.align_world(world, 1)
    assert aligned["groups"]["students"]["positive"] == [0, 1, 2]
    assert aligned["groups"]["students"]["tests"] == [0, 10, 20]
    assert aligned["requested_tests"] == [0, 11, 22]
    assert aligned["out_of_window"]["groups"]["students"]["positive"] == [3]
    assert aligned["out_of_window"]["groups"]["students"]["tests"] == [30]
    assert aligned["out_of_window"]["dates"] == ["2020-08-20"]
    with pytest.raises(ValueError):
        cal.align_world(world, 3)


def test_summarize_profile_uses_best_point_se():
    rows = [
        {"beta": 1.0, "world_losses": [1.0, 1.1, 0.9]},
        {"beta": 2.0, "world_losses": [0.9, 1.0, 1.0]},
        {"beta": 3.0, "world_losses": [2.0, 2.1, 1.9]},
    ]
    profile = cal.summarize_profile(rows)
    assert profile["best_beta"] == 2.0
    assert profile["one_se_betas"] == [1.0, 2.0]
    assert profile["identifiable"] is True
    assert profile["one_se_rule"].startswith("best_point")


def test_summarize_profile_flags_boundary_monotone_and_full_grid():
    boundary = cal.summarize_profile([
        {"beta": 1.0, "world_losses": [1.0, 1.1]},
        {"beta": 2.0, "world_losses": [2.0, 2.1]},
    ])
    assert boundary["identifiable"] is False
    assert boundary["non_identifiable_reason"] == "best_point_on_boundary"
    full = cal.summarize_profile([
        {"beta": 1.0, "world_losses": [1.0, 1.0]},
        {"beta": 2.0, "world_losses": [1.0, 1.0]},
        {"beta": 3.0, "world_losses": [1.0, 1.0]},
    ])
    assert full["identifiable"] is False
    assert full["non_identifiable_reason"] == "one_se_set_covers_grid"


def test_refinement_grid_brackets_one_se_range():
    coarse = [0.01, 0.02, 0.03]
    profiles = [{"one_se_betas": [0.02]}]
    grid = cal.refinement_grid(coarse, profiles, factor=4)
    assert len(grid) == 9
    assert grid[0] == pytest.approx(0.01)
    assert grid[-1] == pytest.approx(0.03)
    assert grid[4] == pytest.approx(0.02)


def test_baselines_use_first_week_and_leave_comparison_days(loaded):
    _, data = loaded
    result = cal._baselines(dict(data, baseline_days=7))
    assert result["fit_dates"][0] == "2020-08-17"
    assert result["comparison_dates"][0] == "2020-08-24"
    assert len(result["persistence"]["positive_daily"]) == 21
    assert result["persistence"]["comparison_daily_mse"] >= 0


def test_evaluation_handles_shifted_windows_and_weekly_blocks(loaded):
    config, data = loaded
    records = []
    for seed in (1, 2, 3, 4):
        world = _fake_world(config, data, 0.02, seed)
        records.append({"beta": 0.02, "seed": seed, "world": world,
                        "losses": cal._world_losses(world, cal._total(data["groups"], "positive"),
                                                    [0, 1, 2])})
    profile = {"alignment": 1, "metric": "cumulative", "best_beta": 0.02,
               "identifiable": True, "non_identifiable_reason": None}
    coarse = dict(profile)
    evaluation = cal._evaluation(records, profile, coarse, data)
    assert evaluation["groups"]["total"]["metrics"]["daily"]["coverage"] is not None
    assert len(evaluation["groups"]["total"]["positive_weekly"]["q50"]) == 3
    assert evaluation["groups"]["total"]["allocation"]["target_test_share"] == pytest.approx(1.0)


def test_study_writes_summary_and_primary(loaded, tmp_path, monkeypatch):
    config, data = loaded
    config = dict(config)
    config.update({"coarse_points": 5, "scan_seeds": config["scan_seeds"][:2],
                   "fit_seeds": config["fit_seeds"][:2],
                   "evaluation_seeds": config["evaluation_seeds"][:2],
                   "alignments": [0], "primary_alignment": 0, "sensitivities": []})
    monkeypatch.setattr(cal, "run_e0_world", _fake_world)
    summary = cal.run_e0_study(config, data, tmp_path / "study", workers=1)
    assert summary["status"] == "complete"
    assert summary["primary"] == {"alignment": 0, "metric": config["primary_metric"]}
    assert (tmp_path / "study" / "summary.json").exists()
    assert (tmp_path / "study" / "profiles.json").exists()
    assert (tmp_path / "study" / "report.md").exists()
    assert (tmp_path / "study" / "manifest.json").exists()
    assert any(item["is_primary"] for item in summary["cases"][0]["evaluations"])


def test_cli_runs_with_a_small_config(loaded, tmp_path, monkeypatch):
    from examples.control_v1 import e0_study

    config, data = loaded
    tiny = dict(config)
    tiny.update({"coarse_points": 5, "scan_seeds": config["scan_seeds"][:2],
                 "fit_seeds": config["fit_seeds"][:2],
                 "evaluation_seeds": config["evaluation_seeds"][:2],
                 "alignments": [0], "primary_alignment": 0, "sensitivities": []})
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(tiny), encoding="utf-8")
    monkeypatch.setattr(cal, "run_e0_world", _fake_world)
    monkeypatch.setattr("cemas.e0.artifacts.export_control_anchor", lambda *a: tmp_path / "anchor.json")
    assert e0_study.main(["--config", str(config_path), "--output", str(tmp_path / "cli"),
                          "--scenarios", "main"]) == 0
    assert (tmp_path / "cli" / "summary.json").exists()


def test_real_small_world_reconciles_groups(loaded):
    config, _ = loaded
    days = 5
    dates = ("2020-08-17", "2020-08-18", "2020-08-19", "2020-08-20", "2020-08-21")
    data = {
        "dates": dates,
        "groups": {"students": {"positive": (0, 1, 0, 2, 1), "tests": (100, 120, 90, 140, 110)},
                   "employees": {"positive": (0, 0, 1, 0, 0), "tests": (20, 30, 20, 30, 20)}},
        "provenance": {}, "sha256": "0" * 64,
    }
    small = dict(config)
    small.update({
        "population": 500, "target_groups": {"students": 400, "employees": 100},
        "target_roles": {"undergraduate_students": 330, "non_undergraduate_students": 70,
                         "teachers": 10, "staff": 90},
        "initial_infections": 2, "window_days": days,
        "engine_overrides": {
            "campus_age_data": [[17, 23, 0.66], [24, 30, 0.14], [31, 65, 0.20]],
            "campus_age_counts": [330, 70, 100],
            "campus_teacher_ratio": 0.02, "campus_staff_ratio": 0.18,
        },
        "config_sha256": "0" * 64,
    })
    from cemas.e0.simulation import run_e0_world

    world = run_e0_world(small, data, 0.02, 12101)
    assert world["population"] == 500
    assert world["roles"] == {"students": 400, "undergraduate_students": 330,
                              "non_undergraduate_students": 70, "teachers": 10,
                              "staff": 90, "employees": 100}
    assert len(world["groups"]["students"]["positive"]) == days
    assert len(world["groups"]["students"]["tests"]) == days
    assert sum(world["groups"]["students"]["positive"]) + sum(world["groups"]["employees"]["positive"]) >= 0
    assert world["requested_tests"] == [120, 150, 110, 170, 130]
    assert len(world["r_eff"]) == days

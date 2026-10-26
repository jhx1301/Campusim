"""Continuous alignment, world-level rates and window-local replay metrics."""

from copy import deepcopy
import csv
from datetime import date, timedelta
import json

import numpy as np
import pytest

from cemas.replay import reporting


def _inputs(days=75):
    dates = [(date(2020, 8, 17) + timedelta(days=offset)).isoformat()
             for offset in range(days)]
    data = {"dates": dates, "groups": {
        "students": {"positive": [2] * days, "tests": [20] * days},
        "employees": {"positive": [1] * days, "tests": [10] * days}}}
    world = deepcopy(data)
    world["requested_tests"] = [30] * days
    return data, world


def test_align_once_preserves_cross_window_counts_denominators_and_tail():
    data, world = _inputs()
    # 9/6 is the last W1 simulation date, but reports on the first W2 day.
    world["groups"]["students"]["positive"][20] = 17
    world["groups"]["students"]["tests"][20] = 99
    world["groups"]["employees"]["positive"][-1] = 7
    world["groups"]["employees"]["tests"][-1] = 71
    original = deepcopy(world)
    summary = reporting.summarize_worlds([world], data)
    student = summary["groups"]["students"]
    assert student["series"]["positive"]["q50"][21] == 17
    assert student["series"]["actual_tests"]["q50"][21] == 99
    assert student["series"]["cumulative_positive"]["q50"][21] == 17
    assert student["series"]["cumulative_error"]["q50"][21] == 15
    assert student["windows"]["W2"]["total_positive"]["q50"] == 17 + 18 * 2
    assert student["windows"]["W2"]["days"] == 19
    assert student["windows"]["W2"]["cumulative_loss"]["q50"] == pytest.approx(
        19 * 15 ** 2 / 38 ** 2)
    assert summary["out_of_window"]["dates"] == ["2020-10-31"]
    assert summary["out_of_window"]["groups"]["employees"]["positive"]["q50"] == [7]
    assert summary["out_of_window"]["groups"]["employees"]["tests"]["q50"] == [71]
    assert world == original
    json.dumps(summary, allow_nan=False)
    with pytest.raises(ValueError, match="raw, unaligned"):
        reporting.summarize_worlds([dict(world, alignment=1)], data)


def test_rolling_ratios_use_seven_complete_days_and_cross_boundaries():
    data, world = _inputs()
    world["groups"]["students"]["positive"][20] = 14
    world["groups"]["students"]["tests"][20] = 70
    details = reporting.summarize_worlds([world], data)["groups"]["students"]
    rolling = details["series"]["positive_7day_mean"]["q50"]
    positivity = details["series"]["positivity_7day"]["q50"]
    assert rolling[:6] == [None] * 6
    assert rolling[21] == pytest.approx((6 * 2 + 14) / 7)
    assert positivity[21] == pytest.approx((6 * 2 + 14) / (6 * 20 + 70))
    # Seven-day ratio is not an average of daily positivity percentages.
    assert positivity[21] != pytest.approx((6 * .1 + .2) / 7)
    assert details["observed"]["positive_7day_mean"][21] == 2
    assert details["series"]["cumulative_positive"]["q50"][40] == 2


def test_zero_denominators_stay_null_and_rates_are_computed_per_world():
    data, world = _inputs()
    empty = deepcopy(world)
    empty["groups"]["students"]["tests"] = [0] * 75
    empty["groups"]["students"]["positive"] = [0] * 75
    empty["groups"]["employees"]["tests"] = [0] * 75
    empty["groups"]["employees"]["positive"] = [0] * 75
    empty["requested_tests"] = [0] * 75
    summary = reporting.summarize_worlds([empty], data)
    assert summary["groups"]["total"]["series"]["positivity_7day"]["q50"] == [None] * 75
    assert summary["groups"]["students"]["series"]["test_share"]["q50"] == [None] * 75
    assert summary["groups"]["students"]["windows"]["W3"]["test_share"]["q50"] is None
    another = deepcopy(world)
    another["groups"]["students"]["positive"] = [10] * 75
    another["groups"]["students"]["tests"] = [100] * 75
    summary = reporting.summarize_worlds([world, another], data)
    assert summary["groups"]["students"]["series"]["positivity_7day"]["q50"][7] == pytest.approx(.1)
    # Ratio of group medians would differ from the median of role allocations.
    expected_share = np.median([20 / 30, 100 / 110])
    assert summary["groups"]["students"]["series"]["test_share"]["q50"][7] == pytest.approx(expected_share)
    json.dumps(summary, allow_nan=False)


def test_daily_absolute_errors_are_aggregated_per_world_and_staff_is_separate():
    data, low = _inputs()
    high = deepcopy(low)
    low["groups"]["students"]["positive"] = [0] * 75
    high["groups"]["students"]["positive"] = [4] * 75
    high["groups"]["employees"]["positive"] = [7] * 75
    details = reporting.summarize_worlds([low, high], data)["groups"]
    assert details["students"]["series"]["positive"]["q50"][1] == 2
    assert details["students"]["series"]["absolute_error"]["mean"][1] == 2
    assert details["students"]["windows"]["W3"]["daily_coverage"] == 1
    assert details["employees"]["windows"]["W3"]["end_bias"]["q50"] == 105
    assert details["students"]["windows"]["W3"]["total_positive"]["q50"] == 70


def test_tables_and_report_support_real_study_schema(tmp_path, monkeypatch):
    data, world = _inputs()
    metrics = reporting.summarize_worlds([world], data)
    scenario = {"name": "h1.15_calibrated_r0.5", "kind": "calibrated", "h": 1.15,
                "c": .2, "recovery": .5, "worlds": 1, "metrics": metrics}
    profiles = [{"h": 1.15, "best_c": .2, "one_se_cs": [.15, .2], "rows": [
        {"c": .15, "mean_loss": .03, "se_loss": .01},
        {"c": .2, "mean_loss": .02, "se_loss": .01}]}]
    summary = {"beta": .056, "anchor_path": "anchor.json", "anchor_sha256": "hash",
               "profiles": profiles, "scenarios": [scenario], "fixed_w2": [],
               "worlds_completed": 1, "failed_worlds": 0}
    monkeypatch.setattr(reporting, "_figures", lambda *args: None)
    reporting.write_report(tmp_path, summary, profiles, data)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "失败世界：0" in report
    assert "员工" in report and "多个候选" in report
    with (tmp_path / "daily_metrics.csv").open(encoding="utf-8-sig", newline="") as handle:
        daily = list(csv.DictReader(handle))
    assert len(daily) == 75 * 3
    assert "cumulative_error_mean" in daily[0]
    assert "test_share_difference_q50" in daily[0]
    with (tmp_path / "window_metrics.csv").open(encoding="utf-8-sig", newline="") as handle:
        windows = list(csv.DictReader(handle))
    assert len(windows) == 9
    assert "cumulative_loss_mean" in windows[0]
    assert (tmp_path / "out_of_window.csv").exists()

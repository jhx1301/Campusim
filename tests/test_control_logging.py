"""Audit persistence and serialization boundaries without running a world."""

import csv
from dataclasses import dataclass
import json
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest

from cemas.control.logging import RunLogger, resolved_snapshot, snapshot_sha256
from cemas.control.rewards import RewardBreakdown
from cemas.control.types import (
    ActionResolution, ActionVector, PrivateDailyMetrics, PrivateMetrics, PublicCost,
    PublicDailyRecord, PublicResources, PublicWeekFeedback, PublicWeeklyRecord,
)


@dataclass(frozen=True)
class NestedConfiguration:
    parameters: object


def test_resolved_snapshot_preserves_nested_numpy_and_readonly_parameters():
    config = NestedConfiguration(MappingProxyType({
        "dur": MappingProxyType({"exp2inf": {"par1": np.float64(4.5)}}),
        "prognoses": {"ages": np.array([0, 10, 20]), "risk": np.array([.1, .2, .3])},
        "variant_map": {0: "wild"},
    }))
    output = resolved_snapshot(config)
    assert output["parameters"]["dur"]["exp2inf"]["par1"] == 4.5
    assert output["parameters"]["prognoses"]["ages"] == [0, 10, 20]
    assert output["parameters"]["variant_map"] == {"0": "wild"}
    assert snapshot_sha256(config) == snapshot_sha256(output)
    output["parameters"]["prognoses"]["ages"][0] = 99
    assert config.parameters["prognoses"]["ages"][0] == 0


@pytest.mark.parametrize("value", [object(), float("nan"), {0: "x", "0": "y"}])
def test_snapshot_rejects_silent_data_loss(value):
    with pytest.raises((TypeError, ValueError)):
        resolved_snapshot(value)


def audit_snapshot(status="completed"):
    action = ActionVector((0, 0, 0, 0, 0))
    cost = PublicCost(clinical_tests=2)
    resources = PublicResources(2, 0, 1)
    daily = PublicDailyRecord(0, 0, cost, action, resources, 0, 0, 0)
    private = PrivateDailyMetrics(0, 1, 2, 3, 3)
    metrics = PrivateMetrics(0, 0, 1, 2, 3, 1, 3)
    feedback = PublicWeekFeedback(PublicWeeklyRecord(0, 0, 0, cost, action, resources))
    window = SimpleNamespace(start_day=0, end_day=0, feedback=feedback, private_metrics=metrics, reward=-.3,
                             reward_breakdown=RewardBreakdown((.1, .8, 0, 0, 0), (.1, .2, 0, 0, 0)))
    return SimpleNamespace(public_daily=(daily,), private_daily=(private,), windows=(window,),
                           manifest=MappingProxyType({"world_seed": 90001, "reward_configuration":
                                                      {"formula_version": "cemas-reward-v1"}}), status=status,
                           elapsed_days=1)


def test_logger_separates_raw_counts_and_rewards_and_does_not_duplicate_snapshots(tmp_path):
    output = tmp_path / "run"
    logger = RunLogger(output, {"purpose": "smoke"})
    snapshot = audit_snapshot()
    logger.write_snapshot(snapshot)
    logger.write_snapshot(snapshot)
    logger.complete({"total_reward": -.3})
    public = list(csv.DictReader((output / "public_daily.csv").open(encoding="utf-8")))
    weekly = list(csv.DictReader((output / "private_weekly_rewards.csv").open(encoding="utf-8")))
    assert len(public) == len(weekly) == 1
    assert "new_infections" not in public[0] and "world_seed" not in public[0]
    assert public[0]["clinical_tests"] == "2"
    assert weekly[0]["new_infections"] == "1" and float(weekly[0]["weighted_tests"]) == .2
    assert weekly[0]["window_days"] == "1" and weekly[0]["formula_version"] == "cemas-reward-v1"
    assert json.loads((output / "manifest.json").read_text())["status"] == "completed"
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        RunLogger(output, {})
    assert (output / "manifest.json").read_bytes() == before


def test_partial_or_failed_log_cannot_be_reported_completed(tmp_path):
    output = tmp_path / "failed"
    logger = RunLogger(output, {})
    logger.write_snapshot(audit_snapshot("active"))
    with pytest.raises(RuntimeError, match="completed environment"):
        logger.complete({})
    logger.fail(RuntimeError("sample failure"), audit_snapshot("failed"))
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((output / "summary.json").read_text())["status"] == "failed"
    assert "sample failure" in (output / "failure.json").read_text()
    assert len(list(csv.DictReader((output / "private_daily.csv").open()))) == 1


@pytest.mark.parametrize("broken_operation", ["flush", "close"])
def test_failure_metadata_survives_stream_cleanup_errors(tmp_path, monkeypatch, broken_operation):
    output = tmp_path / broken_operation
    logger = RunLogger(output, {})
    logger.write_snapshot(audit_snapshot("failed"))
    original_close = logger.close

    def broken():
        if broken_operation == "close":
            original_close()
        raise OSError(f"injected {broken_operation} failure")

    monkeypatch.setattr(logger, broken_operation, broken)
    logger.fail(RuntimeError("original run failure"))
    failure = json.loads((output / "failure.json").read_text())
    assert failure["error"] == "original run failure"
    assert any(broken_operation in message for message in failure["logging_errors"])
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((output / "summary.json").read_text())["status"] == "failed"


def test_failed_failure_file_does_not_prevent_failed_manifest(tmp_path, monkeypatch):
    output = tmp_path / "partial-write"
    logger = RunLogger(output, {})
    write_json = logger._write_json

    def broken(filename, payload):
        if filename == "failure.json":
            raise OSError("failure file unavailable")
        write_json(filename, payload)

    monkeypatch.setattr(logger, "_write_json", broken)
    with pytest.raises(OSError, match="failure file"):
        logger.fail(RuntimeError("run failed"))
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((output / "summary.json").read_text())["status"] == "failed"

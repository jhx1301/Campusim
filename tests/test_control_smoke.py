"""Offline smoke entries must actually reach the behavior they advertise."""

import json

import pytest

from examples.control_v1 import smoke_llm, smoke_memory


@pytest.mark.parametrize("case,days,minimum", [
    ("retry", 7, 8), ("exhaust", 7, 8), ("fatal", 14, 15),
])
def test_llm_smoke_rejects_short_horizon_before_running(tmp_path, monkeypatch, capsys,
                                                      case, days, minimum):
    import cemas.control.runner as runner

    def forbidden(*args, **kwargs):
        raise AssertionError("short smoke must not create a controller or simulate")

    monkeypatch.setattr(runner, "run_episode", forbidden)
    monkeypatch.setattr(smoke_llm, "OfflineTransport", forbidden)
    output = tmp_path / "short"
    with pytest.raises(SystemExit) as error:
        smoke_llm.main(["--output", str(output), "--case", case, "--days", str(days)])
    assert error.value.code == 2
    assert f"at least {minimum} days" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("mode", ["none", "short", "global", "both"])
def test_memory_smoke_rejects_short_horizon_before_opening_resources(tmp_path, monkeypatch,
                                                                   capsys, mode):
    import cemas.control.memory_store as memory_store
    import cemas.control.runner as runner

    def forbidden(*args, **kwargs):
        raise AssertionError("short smoke must not open a store or simulate")

    monkeypatch.setattr(runner, "run_episode", forbidden)
    monkeypatch.setattr(memory_store.FrozenPublicCaseStore, "open", forbidden)
    monkeypatch.setattr(smoke_memory, "OfflineMemoryTransport", forbidden)
    output = tmp_path / "short"
    with pytest.raises(SystemExit) as error:
        smoke_memory.main(["--output", str(output), "--mode", mode, "--days", "7",
                           "--store", str(tmp_path / "missing-store"),
                           "--store-manifest", str(tmp_path / "missing-manifest")])
    assert error.value.code == 2
    assert "at least 8 days" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("case,days,calls,status", [
    ("retry", 8, 2, "completed"),
    ("exhaust", 8, 3, "completed"),
    ("fatal", 15, 2, "failed"),
])
def test_llm_smoke_minimum_horizon_exercises_fixture(tmp_path, case, days, calls, status):
    output = tmp_path / case
    assert smoke_llm.main(["--output", str(output), "--case", case, "--days", str(days),
                           "--population", "30", "--initial-infections", "1"]) == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    audits = [json.loads(line) for line in
              (output / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    decisions = [json.loads(line) for line in
                 (output / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["status"] == status
    assert len(audits) == calls
    assert decisions[0]["decision_source"] == "protocol_fixed"
    assert decisions[0]["llm_attempt_count"] == 0
    assert decisions[1]["decision_day"] == 7
    if case == "exhaust":
        assert decisions[1]["fallback_reason"] == "llm_retry_exhausted"
    if case == "fatal":
        failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
        assert failure["details"]["error_code"] == "offline_fatal_fixture"
        assert manifest["elapsed_days"] == 14
    else:
        assert manifest["elapsed_days"] == days


@pytest.mark.parametrize("mode", ["none", "short"])
def test_memory_smoke_minimum_horizon_calls_fixture(tmp_path, mode):
    output = tmp_path / mode
    assert smoke_memory.main(["--output", str(output), "--mode", mode, "--days", "8",
                              "--population", "30", "--initial-infections", "1"]) == 0
    audits = [json.loads(line) for line in
              (output / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    decisions = [json.loads(line) for line in
                 (output / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(audits) == 1
    assert decisions[0]["llm_attempt_count"] == 0
    assert decisions[1]["decision_day"] == 7
    assert decisions[1]["llm_succeeded"] is True

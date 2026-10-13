"""Tests for the standard-library-only control-v1 environment inventory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_control_environment.py"
SPEC = importlib.util.spec_from_file_location("control_environment_check", SCRIPT)
environment_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(environment_check)


def test_cli_defaults_to_current_interpreter():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert Path(report["python"]["executable"]).resolve() == Path(sys.executable).resolve()
    assert report["check_kind"] == "metadata_and_discovery_only"
    assert report["dependency_installation"] is False
    assert set(report["packages"]["future"]) == set(environment_check.FUTURE_PACKAGES)


def test_cli_selected_interpreter_writes_report_and_snapshot(tmp_path):
    output = tmp_path / "nested" / "environment.json"
    lock = tmp_path / "nested" / "installed.txt"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--python", sys.executable,
         "--output", str(output), "--write-lock", str(lock)],
        capture_output=True, text=True, check=True,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == json.loads(result.stdout)
    snapshot = lock.read_text(encoding="utf-8")
    assert f"# Python: {report['python']['version']}" in snapshot
    assert "not a validated future dependency lock" in snapshot
    entries = [line for line in snapshot.splitlines() if line and not line.startswith("#")]
    assert entries == sorted(set(entries))
    assert all("==" in entry for entry in entries)


def test_missing_dependencies_are_reported_without_failing_phase_zero(monkeypatch, capsys):
    monkeypatch.setattr(environment_check.importlib.util, "find_spec", lambda module: None)

    def missing(distribution):
        raise environment_check.importlib.metadata.PackageNotFoundError(distribution)

    monkeypatch.setattr(environment_check.importlib.metadata, "version", missing)
    assert environment_check.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["missing_base_packages"] == list(environment_check.BASE_PACKAGES)
    assert report["missing_future_packages"] == list(environment_check.FUTURE_PACKAGES)
    assert report["future_dependency_validation"] == "not_performed"


def test_snapshot_rejects_unsafe_metadata_and_normalizes_names(monkeypatch):
    distributions = [
        SimpleNamespace(metadata={"Name": "Safe_Package"}, version="1.2.3"),
        SimpleNamespace(metadata={"Name": "bad\n--extra-index-url"}, version="1.0"),
        SimpleNamespace(metadata={"Name": "otherwise-safe"}, version="1.0\n--trusted-host"),
    ]
    monkeypatch.setattr(environment_check.importlib.metadata, "distributions", lambda: distributions)
    assert environment_check.installed_snapshot() == (["safe-package==1.2.3"], 2)


def test_report_and_lock_do_not_read_or_include_credentials(monkeypatch, tmp_path, capsys):
    sentinel = "secret-control-environment-test-value"
    monkeypatch.setenv("LLM_API_KEY", sentinel)
    monkeypatch.setenv("DASHSCOPE_API_KEY", sentinel)
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    output = tmp_path / "environment.json"
    lock = tmp_path / "installed.txt"
    assert environment_check.main(["--output", str(output), "--write-lock", str(lock)]) == 0
    rendered = capsys.readouterr().out + output.read_text(encoding="utf-8") + lock.read_text(encoding="utf-8")
    assert sentinel not in rendered
    assert "API_KEY" not in rendered

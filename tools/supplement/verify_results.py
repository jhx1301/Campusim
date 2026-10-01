"""Offline integrity, aggregation, memory-store, and anonymity checks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_aggregate(run_path: Path, summary_path: Path, expected_runs: int) -> None:
    runs = read_csv(run_path)
    summaries = read_csv(summary_path)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in runs:
        grouped[(row["scenario"], row["strategy"])].append(row)
    require(len(grouped) == len(summaries), f"Group count mismatch: {run_path}")
    for summary in summaries:
        key = (summary["scenario"], summary["strategy"])
        group = grouped.get(key, [])
        require(len(group) == expected_runs, f"{key} has {len(group)} runs, expected {expected_runs}")
        require(int(float(summary["n_runs"])) == expected_runs, f"Bad n_runs for {key}")
        for metric in ("cum_infections", "peak_new_infections", "cum_tests", "policy_switch_count"):
            values = [float(row[metric]) for row in group]
            expected_mean = statistics.fmean(values)
            actual_mean = float(summary[f"{metric}_mean"])
            require(math.isclose(actual_mean, expected_mean, rel_tol=1e-9, abs_tol=1e-7), f"Mean mismatch: {key} {metric}")
            actual_var = float(summary[f"{metric}_var"])
            require(math.isclose(actual_var, statistics.pvariance(values), rel_tol=1e-9, abs_tol=1e-6), f"Variance mismatch: {key} {metric}")


def verify_tables() -> None:
    calibration = json.loads((RESULTS / "calibration" / "calibration_results.json").read_text(encoding="utf-8"))
    require("default_pars" in calibration and "best_pars" in calibration, "Calibration parameters missing")
    require(len(read_csv(RESULTS / "calibration" / "sensitivity_run_metrics.csv")) > 0, "Sensitivity runs missing")
    verify_aggregate(
        RESULTS / "policy_comparison" / "policy_run_metrics.csv",
        RESULTS / "policy_comparison" / "policy_summary_metrics.csv",
        expected_runs=10,
    )
    verify_aggregate(
        RESULTS / "recent_memory_ablation" / "memory_run_metrics.csv",
        RESULTS / "recent_memory_ablation" / "memory_summary_metrics.csv",
        expected_runs=5,
    )
    policy_strategies = {row["strategy"] for row in read_csv(RESULTS / "policy_comparison" / "policy_summary_metrics.csv")}
    require(policy_strategies == {"baseline_no_policy", "baseline_threshold", "llm_single_memory"}, "Unexpected Table 3 strategies")
    memory_strategies = {row["strategy"] for row in read_csv(RESULTS / "recent_memory_ablation" / "memory_summary_metrics.csv")}
    require(memory_strategies == {"baseline_single_agent_nomemory", "llm_single_memory"}, "Unexpected Table 4 strategies")
    dual = read_csv(RESULTS / "dual_memory_ablation" / "eval" / "memory_summary_metrics.csv")
    require("llm_dual_memory" in {row["strategy"] for row in dual}, "Dual-memory results missing")


def verify_memory_audit_index() -> None:
    path = RESULTS / "dual_memory_ablation" / "memory_audit_index.db"
    require(path.exists(), "Memory audit index missing")
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require("decision_audit" in tables and "retrieval_audit" in tables, "Memory audit schema missing")
        count = connection.execute("SELECT COUNT(*) FROM decision_audit").fetchone()[0]
        require(count > 0, "Memory audit index is empty")


def verify_checksums() -> None:
    checksum_path = ROOT / "SHA256SUMS.txt"
    require(checksum_path.exists(), "SHA256SUMS.txt missing")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = ROOT / relative
        require(path.is_file(), f"Missing checksummed file: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == expected, f"Checksum mismatch: {relative}")


def verify_audit_logs() -> None:
    path = RESULTS / "llm_audit_logs.zip"
    require(path.exists(), "LLM audit archive missing")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(any(name.startswith("policy_comparison/") for name in names), "Policy audit logs missing")
        require(any(name.startswith("recent_memory_ablation/") for name in names), "Recent-memory audit logs missing")
        require(any(name.startswith("dual_memory_ablation/") for name in names), "Dual-memory audit logs missing")


def verify_anonymity() -> None:
    identity_patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (r"[A-Za-z]:\\(?:Users|项目|椤圭洰)\\", r"/(?:Users|home)/[^/]+/")
    ]
    secret_patterns = [
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
    ]
    text_suffixes = {".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".rst", ".toml", ".yml", ".yaml"}
    failures = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if any(pattern.search(text) for pattern in identity_patterns + secret_patterns):
            failures.append(path.relative_to(ROOT).as_posix())
    audit_path = RESULTS / "llm_audit_logs.zip"
    with zipfile.ZipFile(audit_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".jsonl"):
                continue
            text = archive.read(name).decode("utf-8-sig", errors="replace")
            if any(pattern.search(text) for pattern in identity_patterns + secret_patterns):
                failures.append(f"llm_audit_logs.zip::{name}")
    require(not failures, "Identity or secret-like content found: " + ", ".join(failures))


def main() -> int:
    checks = [verify_tables, verify_memory_audit_index, verify_audit_logs, verify_checksums, verify_anonymity]
    for check in checks:
        check()
        print(f"PASS: {check.__name__}")
    print("All CEMAS supplement checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise

"""Inspect the control-v1 environment without importing or installing packages."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


BASE_PACKAGES = {
    "numpy": "numpy",
    "numba": "numba",
    "pandas": "pandas",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
    "matplotlib": "matplotlib",
    "sciris": "sciris",
    "openai": "openai",
    "pytest": "pytest",
}
FUTURE_PACKAGES = {
    "optuna": "optuna",
    "torch": "torch",
    "gymnasium": "gymnasium",
    "stable_baselines3": "stable-baselines3",
    "sb3_contrib": "sb3-contrib",
    "sentence_transformers": "sentence-transformers",
}
SAFE_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*\Z")


def package_status(module: str, distribution: str) -> dict:
    """Read discovery and distribution metadata; this does not import module."""
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        available = False
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {"distribution": distribution, "available": available, "version": version}


def collect_report() -> dict:
    base = {name: package_status(name, dist) for name, dist in BASE_PACKAGES.items()}
    future = {name: package_status(name, dist) for name, dist in FUTURE_PACKAGES.items()}
    return {
        "schema_version": "cemas-control-environment-v1",
        "check_kind": "metadata_and_discovery_only",
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "cpu": {"logical_count": os.cpu_count()},
        "packages": {"base": base, "future": future},
        "missing_base_packages": [name for name, status in base.items() if not status["available"]],
        "missing_future_packages": [name for name, status in future.items() if not status["available"]],
        "future_dependency_validation": "not_performed",
        "dependency_installation": False,
    }


def installed_snapshot() -> tuple[list[str], int]:
    """Return safe installed requirements, skipping malformed metadata."""
    entries = set()
    skipped = 0
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "")
        version = distribution.version
        if not isinstance(name, str) or not isinstance(version, str):
            skipped += 1
            continue
        if not SAFE_NAME.fullmatch(name) or not SAFE_VERSION.fullmatch(version):
            skipped += 1
            continue
        normalized_name = re.sub(r"[-_.]+", "-", name).lower()
        entries.add(f"{normalized_name}=={version}")
    return sorted(entries), skipped


def write_lock(path: Path, report: dict) -> None:
    entries, skipped = installed_snapshot()
    header = [
        "# CEMAS control-v1: current installed distribution snapshot.",
        "# This is an environment inventory, not a validated future dependency lock.",
        f"# Python: {report['python']['version']} ({report['python']['implementation']})",
        f"# Platform: {report['platform']['system']} {report['platform']['machine']}",
        "# Future dependencies are unvalidated; none were installed by this tool:",
        "# " + ", ".join(FUTURE_PACKAGES.values()),
        "# Missing future modules: " + (", ".join(report["missing_future_packages"]) or "none"),
        f"# Unsafe distribution metadata entries skipped: {skipped}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header + entries) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", help="Inspect this interpreter instead of the current interpreter.")
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path.")
    parser.add_argument("--write-lock", type=Path, help="Write the currently installed distribution snapshot.")
    args = parser.parse_args(argv)

    if args.python:
        command = [args.python, str(Path(__file__).resolve())]
        if args.output is not None:
            command.extend(["--output", str(args.output)])
        if args.write_lock is not None:
            command.extend(["--write-lock", str(args.write_lock)])
        try:
            return subprocess.run(command, check=False).returncode
        except OSError:
            parser.error("The requested Python interpreter could not be started.")

    report = collect_report()
    if args.write_lock is not None:
        write_lock(args.write_lock, report)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

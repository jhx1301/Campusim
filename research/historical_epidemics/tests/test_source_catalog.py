"""The source catalogue builds from its JSON input outside the project tree."""

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys


def test_source_catalog_builds_without_reports_or_old_directories(tmp_path):
    task = Path(__file__).resolve().parents[1]
    shutil.copytree(task / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    sources = tmp_path / "sources"
    sources.mkdir()
    original = (task / "sources/records.json").read_bytes()
    (sources / "records.json").write_bytes(original)

    result = subprocess.run(
        [sys.executable, "-c", "from scripts.prepare_historical_epidemics import registry; print(registry())"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    records = json.loads(original)["sources"]
    assert int(result.stdout.strip()) == len(records)
    assert (sources / "records.json").read_bytes() == original
    with (sources / "catalog.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["id"] for row in rows] == [row["id"] for row in records]
    assert [row["urls"] for row in rows] == [" | ".join(row["urls"]) for row in records]
    assert not (tmp_path / "data/source_registry.json").exists()

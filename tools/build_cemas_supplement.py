"""Build the anonymous CEMAS code-and-data supplement from an allowlist."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE_NAME = "CEMAS_Code_and_Data_Supplement"
STAGE = DIST / PACKAGE_NAME
ZIP_PATH = DIST / f"{PACKAGE_NAME}.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_clean_stage() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    resolved = STAGE.resolve()
    if resolved.parent != DIST.resolve() or resolved.name != PACKAGE_NAME:
        raise RuntimeError(f"Unsafe staging path: {resolved}")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_package(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or "regression" in relative.parts:
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        copy_file(path, destination / relative)


def copy_named_files(source: Path, destination: Path, names: list[str]) -> None:
    for name in names:
        copy_file(source / name, destination / name)


def copy_result_tables(source: Path, destination: Path) -> None:
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
            if path.name == "experiment_manifest.json":
                continue
            copy_file(path, destination / path.name)


def audit_log_sources() -> list[tuple[str, Path]]:
    roots = [
        ("policy_comparison", ROOT / "examples/figures/campus_llm_thesis_experiments/policy"),
        ("recent_memory_ablation", ROOT / "examples/figures/campus_llm_thesis_experiments/memory"),
        ("dual_memory_ablation/eval", ROOT / "examples/figures/campus_llm_dual_memory_eval"),
        ("dual_memory_ablation/branches", ROOT / "examples/figures/campus_llm_memory_branch_ablation"),
    ]
    logs = []
    for label, directory in roots:
        for path in sorted(directory.glob("*.jsonl")):
            logs.append((label, path))
    return logs


def read_first_record(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)
    return {}


def build_audit_archive(logs: list[tuple[str, Path]]) -> Path:
    destination = STAGE / "results/llm_audit_logs.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for label, path in logs:
            archive.write(path, f"{label}/{path.name}")
    return destination


def build_memory_audit_index(logs: list[tuple[str, Path]]) -> Path:
    destination = STAGE / "results/dual_memory_ablation/memory_audit_index.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(
            """
            CREATE TABLE decision_audit (
                collection TEXT NOT NULL,
                source_log TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                record_sha256 TEXT NOT NULL,
                decision_day INTEGER,
                model_name TEXT,
                base_url TEXT,
                temperature REAL,
                max_tokens INTEGER,
                proposed_policy TEXT,
                applied_policy TEXT,
                system_prompt_sha256 TEXT,
                PRIMARY KEY (collection, source_log, line_number)
            );
            CREATE TABLE retrieval_audit (
                source_row INTEGER PRIMARY KEY,
                scenario TEXT,
                strategy TEXT,
                seed INTEGER,
                decision_day INTEGER,
                row_json TEXT NOT NULL,
                row_sha256 TEXT NOT NULL
            );
            """
        )
        for label, path in logs:
            if not label.startswith("dual_memory_ablation"):
                continue
            with path.open("r", encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    connection.execute(
                        "INSERT INTO decision_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            label, path.name, line_number,
                            hashlib.sha256(line.encode("utf-8")).hexdigest(),
                            record.get("decision_day"), record.get("model_name"),
                            record.get("base_url"), record.get("temperature"),
                            record.get("max_tokens"), record.get("model_policy_proposed"),
                            record.get("applied_policy"), record.get("system_prompt_sha256"),
                        ),
                    )
        retrieval = ROOT / "examples/figures/campus_llm_memory_branch_ablation/memory_branch_retrieval_audit.csv"
        with retrieval.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=1):
                payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
                connection.execute(
                    "INSERT INTO retrieval_audit VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_number, row.get("scenario"), row.get("strategy"),
                        int(float(row["seed"])) if row.get("seed") else None,
                        int(float(row["decision_day"])) if row.get("decision_day") else None,
                        payload, hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    ),
                )
        connection.commit()
    finally:
        connection.close()
    return destination


def summarize_result_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "path": path.relative_to(STAGE).as_posix(),
        "rows": len(rows),
        "scenarios": sorted({row.get("scenario", "") for row in rows if row.get("scenario")}),
        "strategies": sorted({row.get("strategy", "") for row in rows if row.get("strategy")}),
        "seeds": sorted({int(float(row["seed"])) for row in rows if row.get("seed")}),
    }


def build_manifest(logs: list[tuple[str, Path]]) -> None:
    settings = {}
    for label, path in logs:
        if label in settings:
            continue
        record = read_first_record(path)
        settings[label] = {
            "model": record.get("model_name"),
            "base_url": record.get("base_url"),
            "temperature": record.get("temperature"),
            "max_tokens": record.get("max_tokens"),
        }
    manifest = {
        "format_version": 1,
        "project": "CEMAS",
        "supplement_version": "1.0.0",
        "anonymous_review_copy": True,
        "paper_configuration": {
            "population": 40000,
            "days": 84,
            "policy_seeds": list(range(1, 11)),
            "memory_ablation_seeds": list(range(1, 6)),
            "calibration_trials": 80,
            "sensitivity_perturbation": "+/-20%",
        },
        "llm_settings_observed_in_logs": settings,
        "result_sets": {
            "table3": summarize_result_csv(STAGE / "results/policy_comparison/policy_run_metrics.csv"),
            "table4": summarize_result_csv(STAGE / "results/recent_memory_ablation/memory_run_metrics.csv"),
            "dual_memory_eval": summarize_result_csv(STAGE / "results/dual_memory_ablation/eval/memory_run_metrics.csv"),
            "memory_branch_ablation": summarize_result_csv(STAGE / "results/dual_memory_ablation/branches/memory_branch_run_metrics.csv"),
        },
        "memory_database": {
            "included": "results/dual_memory_ablation/memory_audit_index.db",
            "kind": "audit index reconstructed from preserved logs and retrieval CSV",
            "original_frozen_vector_store_included": False,
        },
    }
    path = STAGE / "results/manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_anonymity() -> None:
    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"jhx1301", r"Hanxiang", r"Jiang", r"江翰翔",
            r"[A-Za-z]:\\(?:Users|项目|椤圭洰)\\", r"/(?:Users|home)/[^/]+/",
            r"sk-[A-Za-z0-9_-]{16,}",
            r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._-]{12,}",
        )
    ]
    suffixes = {".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".rst"}
    failures = []
    for path in STAGE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            failures.append(path.relative_to(STAGE).as_posix())
    audit = STAGE / "results/llm_audit_logs.zip"
    with zipfile.ZipFile(audit) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8-sig", errors="replace")
            if any(pattern.search(text) for pattern in patterns):
                failures.append(f"results/llm_audit_logs.zip::{name}")
    if failures:
        raise RuntimeError("Anonymous supplement scan failed: " + ", ".join(failures))


def write_checksums() -> None:
    lines = []
    checksum_file = STAGE / "SHA256SUMS.txt"
    for path in sorted(STAGE.rglob("*")):
        if path.is_file() and path != checksum_file:
            lines.append(f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}")
    checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(STAGE).as_posix()}")


def main() -> int:
    ensure_clean_stage()

    for name in ["README.md", "RESULT_MAPPING.md", "LICENSE", "requirements.txt", "setup.py"]:
        copy_file(ROOT / name, STAGE / name)
    copy_package(ROOT / "cemas", STAGE / "cemas")
    copy_package(ROOT / "covasim", STAGE / "covasim")

    experiments = STAGE / "experiments"
    copy_file(ROOT / "examples/t17_campus_llm_thesis_experiments.py", experiments / "run_cemas_experiments.py")
    copy_file(ROOT / "examples/t18_campus_validation.py", experiments / "run_cemas_validation.py")
    copy_file(ROOT / "tools/supplement/reproduce_tables.py", experiments / "reproduce_tables.py")
    copy_file(ROOT / "tools/supplement/verify_results.py", experiments / "verify_results.py")

    data = STAGE / "data"
    copy_named_files(ROOT / "data", data, ["README.md", "notre_dame_2020_early.csv", "notre_dame_2020_campus.csv"])

    calibration = ROOT / "examples/figures/campus_validation"
    copy_named_files(calibration, STAGE / "results/calibration", [
        "calibration_results.json", "sensitivity_run_metrics.csv", "sensitivity_summary.csv",
    ])
    policy = ROOT / "examples/figures/campus_llm_thesis_experiments/policy"
    memory = ROOT / "examples/figures/campus_llm_thesis_experiments/memory"
    dual_eval = ROOT / "examples/figures/campus_llm_dual_memory_eval"
    branches = ROOT / "examples/figures/campus_llm_memory_branch_ablation"
    copy_result_tables(policy, STAGE / "results/policy_comparison")
    copy_result_tables(memory, STAGE / "results/recent_memory_ablation")
    copy_result_tables(dual_eval, STAGE / "results/dual_memory_ablation/eval")
    copy_result_tables(branches, STAGE / "results/dual_memory_ablation/branches")

    figures = STAGE / "results/figures"
    selected_figures = [
        (calibration / "fig_calibration_fit.png", "calibration_fit.png"),
        (calibration / "fig_sensitivity_tornado.png", "sensitivity_tornado.png"),
        (policy / "policy_infection_curves.png", "policy_comparison.png"),
        (memory / "memory_infection_curves.png", "recent_memory_ablation.png"),
        (dual_eval / "memory_infection_curves.png", "dual_memory_evaluation.png"),
        (branches / "memory_branch_infections_ci.png", "memory_branch_ablation.png"),
    ]
    for source, name in selected_figures:
        copy_file(source, figures / name)

    logs = audit_log_sources()
    if not logs:
        raise RuntimeError("No LLM decision logs found")
    build_audit_archive(logs)
    build_memory_audit_index(logs)
    build_manifest(logs)
    scan_anonymity()
    write_checksums()
    create_zip()
    print(f"Built staging directory: {STAGE}")
    print(f"Built supplement ZIP: {ZIP_PATH}")
    print(f"ZIP size: {ZIP_PATH.stat().st_size / (1024 * 1024):.2f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

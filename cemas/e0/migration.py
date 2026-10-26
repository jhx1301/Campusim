"""Explicit evidence migration for the shared employee-background integration."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import shutil

from .artifacts import (ARTIFACT_FILENAME, ARTIFACT_SCHEMA, STUDY_FILES, _compatibility,
                        _config, _digest, _file_hash, _read, _study_payload)
from .data import load_e0_data
from .simulation import run_e0_world


MIGRATION_KIND = "uw-employee-background-v1"
SOURCE_ANCHOR = "source_control_anchor.json"
REPORT = "migration.json"
WORLDS = "worlds_migration.jsonl"
# Only the reviewed background extraction and evidence plumbing may differ.
CHANGED_SOURCES = frozenset({"cemas/e0/artifacts.py", "cemas/e0/simulation.py",
                             "cemas/e0/study.py", "cemas/control/scenarios.py",
                             "cemas/control/protocol.py"})
ADDED_SOURCES = frozenset({"cemas/control/background.py", "cemas/e0/migration.py"})


def _write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")


def _source_anchor(path, protocol, current):
    envelope = _read(path)
    source = envelope["payload"]
    if (source["schema_version"] != ARTIFACT_SCHEMA or _digest(source) != envelope["sha256"]
            or "migration" in source or set(source["study_sha256"]) != STUDY_FILES):
        raise ValueError("Migration requires an intact original UW anchor and complete study")
    for name, digest in source["study_sha256"].items():
        if _file_hash(path.parent / name) != digest:
            raise ValueError(f"Original study evidence changed: {name}")
    old = source["compatibility"]
    expected = deepcopy(old["base_model"])
    if "campus_background" in expected:
        raise ValueError("Source anchor already contains the shared background")
    config = _config(protocol)
    background = {key: config[key] for key in ("employee_cm", "employee_ta")}
    expected["beta_layer"]["ta"] *= background["employee_ta"]
    expected["campus_background"] = background
    if (expected != current["base_model"] or old["runtime"] != current["runtime"]
            or old["start_day"] != current["start_day"]):
        raise ValueError("Migration only permits the declared employee background integration")
    previous, latest = old["source_sha256"], current["source_sha256"]
    if set(previous) - set(latest) or set(latest) - set(previous) != ADDED_SOURCES:
        raise ValueError("Unexpected source file additions/removals during background migration")
    if any(previous[name] != latest[name] for name in previous if name not in CHANGED_SOURCES):
        raise ValueError("Source outside the background migration scope changed")
    return source


def _selected_worlds(root, beta, seeds):
    records = [json.loads(line) for line in (root / "worlds_evaluation.jsonl").read_text(
        encoding="utf-8").splitlines()]
    selected = [r for r in records if r["case"] == "main" and r["beta"] == beta]
    if sorted(r["seed"] for r in selected) != sorted(seeds):
        raise ValueError("Migration requires every selected-beta evaluation seed exactly once")
    return {r["seed"]: r["world"] for r in selected}


def _verify_world(original, actual, background, base_model):
    # New audit fields were absent from the original records. Every original
    # field, including individual daily counts and r_eff, must match exactly.
    projected = {key: actual[key] for key in original}
    projected["resolved_parameters"] = {
        key: actual["resolved_parameters"][key] for key in original["resolved_parameters"]}
    if projected != original:
        raise ValueError(f"Migrated world differs from original seed {original['seed']}")
    if actual["campus_background"] != background or any(
            actual["resolved_parameters"][key] != base_model[key]
            for key in ("beta_layer", "iso_factor", "quar_factor")):
        raise ValueError("Migration world effective background differs from target model")


def verify_background_migration(root, payload, protocol):
    """Check linked source bytes, replay coverage and actual comparisons on load."""
    evidence = payload["migration"]
    if evidence["kind"] != MIGRATION_KIND or set(evidence["files"]) != {SOURCE_ANCHOR, REPORT, WORLDS}:
        raise ValueError("Unsupported or incomplete UW migration evidence")
    for name, digest in evidence["files"].items():
        if _file_hash(root / name) != digest:
            raise ValueError(f"UW migration evidence changed: {name}")
    current = payload["compatibility"]
    source = _source_anchor(root / SOURCE_ANCHOR, protocol, current)
    expected = {**source, "compatibility": current, "migration": evidence}
    if payload != expected:
        raise ValueError("Migration changed the original calibration selection or evidence")
    config = _config(protocol)
    seeds = config["evaluation_seeds"]
    report = _read(root / REPORT)
    expected_report = {"kind": MIGRATION_KIND, "status": "complete", "beta": source["beta"],
                       "source_anchor_sha256": _file_hash(root / SOURCE_ANCHOR),
                       "target_compatibility_sha256": _digest(current),
                       "evaluation_seeds": list(seeds), "matched_worlds": len(seeds),
                       "scan_fit_recomputed": False}
    if report != expected_report:
        raise ValueError("Migration report does not match its source, target or evaluation coverage")
    original = _selected_worlds(root, source["beta"], seeds)
    actual = [json.loads(line) for line in (root / WORLDS).read_text(encoding="utf-8").splitlines()]
    if sorted(row["seed"] for row in actual) != sorted(seeds):
        raise ValueError("Migration replay coverage has missing or duplicate seeds")
    base = current["base_model"]
    for row in actual:
        _verify_world(original[row["seed"]], row, base["campus_background"], base)


def migrate_background_anchor(source_anchor, output_dir, protocol, *, workers=1):
    """Keep original evidence, replay all selected worlds, publish a linked anchor."""
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    source_anchor = Path(source_anchor).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    current = _compatibility(protocol)
    source = _source_anchor(source_anchor, protocol, current)
    reconstructed = _study_payload(source_anchor.parent, protocol, compatibility=source["compatibility"])
    if reconstructed != source:
        raise ValueError("Original anchor differs from reconstructed scan/fit/evaluation evidence")
    config = _config(protocol)
    data = load_e0_data(config)
    seeds = config["evaluation_seeds"]
    original = _selected_worlds(source_anchor.parent, source["beta"], seeds)
    output.mkdir(parents=True, exist_ok=False)
    for name in STUDY_FILES:
        shutil.copyfile(source_anchor.parent / name, output / name)
    shutil.copyfile(source_anchor, output / SOURCE_ANCHOR)
    matched = []
    try:
        with (output / WORLDS).open("x", encoding="utf-8", newline="\n") as stream:
            def record(world):
                base = current["base_model"]
                _verify_world(original[world["seed"]], world, base["campus_background"], base)
                stream.write(json.dumps(world, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                matched.append(world["seed"])
                print(f"Migration evaluation: {len(matched)}/{len(seeds)} matched", flush=True)

            if workers == 1:
                for seed in seeds:
                    record(run_e0_world(config, data, source["beta"], seed))
            else:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    jobs = [executor.submit(run_e0_world, config, data, source["beta"], seed) for seed in seeds]
                    for job in as_completed(jobs):
                        record(job.result())
        if _compatibility(protocol) != current:
            raise ValueError("Model/source identity changed during migration")
        report = {"kind": MIGRATION_KIND, "status": "complete", "beta": source["beta"],
                  "source_anchor_sha256": _file_hash(output / SOURCE_ANCHOR),
                  "target_compatibility_sha256": _digest(current),
                  "evaluation_seeds": list(seeds), "matched_worlds": len(matched),
                  "scan_fit_recomputed": False}
        _write(output / REPORT, report)
        evidence = {"kind": MIGRATION_KIND, "files": {
            name: _file_hash(output / name) for name in (SOURCE_ANCHOR, REPORT, WORLDS)}}
        payload = {**source, "compatibility": current, "migration": evidence}
        verify_background_migration(output, payload, protocol)
        target = output / ARTIFACT_FILENAME
        _write(target, {"payload": payload, "sha256": _digest(payload)})
        return target
    except BaseException as error:
        _write(output / "migration_failure.json", {"status": "failed", "matched_seeds": matched,
               "error_type": type(error).__name__, "message": str(error)})
        raise

"""Prepare three independent 32+32 episode schedules without running experiments."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from cemas.control.logging import resolved_snapshot, snapshot_sha256
from cemas.control.snapshot_protocol import (
    ROOT, SnapshotEpisodePlan, load_training_protocol, snapshot_scenarios,
)


CHECKPOINTS = (16, 32, 64)


def select_unique_world_episodes(protocol, seed, artifact, data_path=None, *, count=64):
    """Keep existing scenario values and the first occurrence of each world."""
    plan = SnapshotEpisodePlan(protocol, seed, artifact, data_path)
    selected, worlds = [], set()
    for _ in range(len(plan.items)):
        scenario = plan()
        if scenario["world_seed"] in worlds:
            continue
        worlds.add(scenario["world_seed"])
        options = dict(scenario["scenario_options"])
        options.pop("calibration_artifact")
        options.pop("calibration_data_path")
        selected.append({"episode_id": f"llm-seed{seed}-episode{len(selected) + 1:03d}",
                         "world_seed": scenario["world_seed"], "scenario_options": options})
        if len(selected) == count:
            return selected
    raise ValueError(f"Seed {seed} has only {len(selected)} distinct eligible training worlds; need {count}")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(resolved_snapshot(value), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _snapshot_resources(scenarios):
    """Check files and metadata only; never deserialize or advance a simulator."""
    resources = {}
    for row in scenarios:
        path = Path(row["scenario_options"]["snapshot_path"]).resolve()
        if str(path) in resources:
            continue
        metadata = _read(path)
        state = path.parent / metadata["state_file"]
        if metadata["history_seed"] != row["world_seed"] or not state.is_file():
            raise ValueError(f"Missing or inconsistent snapshot resource: {path}")
        resources[str(path)] = {"metadata_sha256": snapshot_sha256(metadata),
                               "state_file": str(state), "state_bytes": state.stat().st_size,
                               "snapshot_day": metadata["snapshot_day"], "split": metadata["split"]}
    return resources


def _coverage(episodes, resources):
    dates = Counter(resources[str(Path(row["scenario_options"]["snapshot_path"]).resolve())]["snapshot_day"]
                    for row in episodes)
    capacities = Counter(row["scenario_options"]["screening_capacity_ratio"] for row in episodes)
    return {"episodes": len(episodes),
            "distinct_worlds": len({row["world_seed"] for row in episodes}),
            "snapshot_days": {str(day): count for day, count in sorted(dates.items())},
            "screening_capacity_ratios": {str(ratio): count for ratio, count in sorted(capacities.items())}}


def prepare_low_reasoning(protocol, settings, directory):
    """Use the same pinned tokenizer files with a separate low-mode manifest."""
    from cemas.control.llm import OfficialInputTokenCounter
    from cemas.control.runner import make_llm_settings

    directory = Path(directory).resolve()
    base = _read(ROOT / protocol.definition["snapshot_training"]["base_protocol"])
    base["controllers"]["llm"]["primary_effort"] = "low"
    task = resolved_snapshot(protocol.definition["snapshot_training"])
    task["base_protocol"] = str(directory / "base_protocol.json")
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / "base_protocol.json", base)
    _write(directory / "protocol.json", task)
    low_protocol = load_training_protocol(directory / "protocol.json")
    low_settings = dict(settings)
    llm_settings = make_llm_settings(low_protocol, provider=settings["provider"],
        endpoint=settings["endpoint"], api_key_env=settings["api_key_env"])
    source_manifest = Path(settings["tokenizer_manifest"])
    tokenizer = _read(source_manifest)
    target = directory / "tokenizer"
    target.mkdir()
    for name in tokenizer["files"]:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_manifest.parent / name, destination)
    tokenizer["template_kwargs"]["reasoning_effort"] = "low"
    tokenizer["input_tokenization_sha256"] = snapshot_sha256(llm_settings.input_tokenization_parameters())
    _write(target / "manifest.json", tokenizer)
    low_settings["tokenizer_manifest"] = str(target / "manifest.json")
    counter = OfficialInputTokenCounter(low_settings["tokenizer_manifest"])
    counter.validate(llm_settings)
    _write(directory / "settings.json", low_settings)
    return {"protocol_path": str(directory / "protocol.json"),
            "protocol_sha256": low_protocol.source_sha256,
            "settings_path": str(directory / "settings.json"),
            "request_parameters": llm_settings.request_parameters(),
            "tokenizer_identity": resolved_snapshot(counter.identity)}


def prepare_experiment(protocol_path, settings_path, artifact_path, output, *, data_path=None,
                       low_reasoning_seed=None):
    from cemas.control.llm import OfficialInputTokenCounter
    from cemas.control.knowledge import load_knowledge_bundle
    from cemas.control.memory import load_memory_profile
    from cemas.control.runner import make_llm_settings
    from cemas.control.snapshots import snapshot_identity
    from cemas.e0.artifacts import load_calibration_artifact

    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Preparation needs a new directory: {output}")
    protocol = load_training_protocol(protocol_path)
    settings = _read(settings_path)
    settings["tokenizer_manifest"] = str(Path(settings["tokenizer_manifest"]).resolve())
    if settings.get("memory_profile_path"):
        settings["memory_profile_path"] = str(Path(settings["memory_profile_path"]).resolve())
    llm_settings = make_llm_settings(protocol, provider=settings["provider"],
        endpoint=settings["endpoint"], api_key_env=settings["api_key_env"])
    counter = OfficialInputTokenCounter(settings["tokenizer_manifest"])
    counter.validate(llm_settings)
    profile = load_memory_profile(settings.get("memory_profile_path"))
    knowledge = load_knowledge_bundle(profile.resource_path("knowledge_path"))
    artifact_path = Path(artifact_path).resolve()
    data_path = str(Path(data_path).resolve()) if data_path else None
    anchor = load_calibration_artifact(artifact_path, protocol, data_path=data_path)
    catalog_path = ROOT / protocol.definition["snapshot_training"]["library"] / "snapshots_manifest.json"
    catalog = _read(catalog_path)
    current_identity = snapshot_identity(protocol, anchor.sha256)
    # The existing fixed snapshots are reused, including their original source provenance.
    if ({key: value for key, value in catalog["identity"].items() if key != "source_sha256"}
            != {key: value for key, value in current_identity.items() if key != "source_sha256"}):
        raise ValueError("Historical snapshot catalog does not match the current calibration and replay recipe")

    schedules = {seed: select_unique_world_episodes(protocol, seed, artifact_path, data_path)
                 for seed in protocol.definition["source"]["train_seed_values"]}
    if low_reasoning_seed is not None and low_reasoning_seed not in schedules:
        raise ValueError("Low reasoning seed must be one of the declared training seeds")
    evaluation = {split: snapshot_scenarios(protocol, split) for split in ("val", "test")}
    resources = _snapshot_resources([row for rows in (*schedules.values(), *evaluation.values()) for row in rows])
    for path in resources:
        metadata = _read(path)
        recorded = catalog["snapshots"].get(Path(path).name)
        if recorded is None or any(recorded[key] != metadata[key] for key in ("history_seed", "snapshot_day", "split")):
            raise ValueError(f"Snapshot is absent from its catalog: {path}")

    manifest = {"status": "prepared", "prepared_at": datetime.now(timezone.utc).isoformat(),
        "training_started": False, "model_calls": 0,
        "protocol_path": str(Path(protocol_path).resolve()), "protocol_sha256": protocol.source_sha256,
        "settings_path": str(output / "settings.json"), "calibration_artifact": str(artifact_path),
        "calibration_data_path": data_path, "calibration_sha256": anchor.sha256,
        "python": sys.executable,
        "source_commit": subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}",
            "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "request_parameters": llm_settings.request_parameters(),
        "input_token_budget": llm_settings.input_token_budget,
        "tokenizer_identity": resolved_snapshot(counter.identity),
        "knowledge_sha256": knowledge.sha256,
        "credential_present_in_process": bool(os.environ.get(settings["api_key_env"])),
        "observation_days": protocol.definition["snapshot_training"]["observation_days"],
        "control_days": protocol.definition["snapshot_training"]["control_days"],
        "total_days": protocol.execution_days, "checkpoints": CHECKPOINTS,
        "selection": "First occurrence of each world in SnapshotEpisodePlan; no repeated world within a seed",
        "low_reasoning_seed": low_reasoning_seed,
        "seeds": [], "evaluation_scenarios": {}, "snapshot_resources": resources,
        "snapshot_catalog_identity": catalog["identity"], "current_snapshot_identity": current_identity,
        "checks": {"calibration_verified": True, "tokenizer_verified": True,
            "snapshot_recipe_and_anchor_verified": True, "snapshot_files_present": True,
            "snapshot_source_hashes_match": catalog["identity"].get("source_sha256") == current_identity.get("source_sha256"),
            "snapshot_state_hashes_verified": False,
            "training_worlds_disjoint_from_evaluation": True}}
    for split, rows in evaluation.items():
        evaluation_worlds = {row["world_seed"] for row in rows}
        if any(evaluation_worlds & {row["world_seed"] for row in entries} for entries in schedules.values()):
            raise ValueError("Training and evaluation worlds overlap")
        manifest["evaluation_scenarios"][split] = {"episodes": len(rows),
            "path": str(output / f"{split}_scenarios.json")}
    output.mkdir(parents=True)
    _write(output / "settings.json", settings)
    for seed, episodes in schedules.items():
        directory = output / f"seed{seed}"
        directory.mkdir()
        configuration = {"protocol_path": manifest["protocol_path"],
                         "protocol_sha256": manifest["protocol_sha256"],
                         "settings_path": manifest["settings_path"],
                         "request_parameters": manifest["request_parameters"],
                         "tokenizer_identity": manifest["tokenizer_identity"]}
        if seed == low_reasoning_seed:
            configuration = prepare_low_reasoning(protocol, settings, directory / "low_reasoning")
        checkpoints = []
        for count in CHECKPOINTS:
            path = directory / f"episodes_001_{count:03d}.json"
            _write(path, episodes[:count])
            checkpoints.append({"episodes": count, "episodes_path": str(path),
                                "frozen_library": str(directory / f"frozen_{count:03d}.sqlite")})
        manifest["seeds"].append({"seed": seed, **configuration, "library": str(directory / "learning.sqlite"),
            "runs_directory": str(directory / "runs"), "checkpoints": checkpoints,
            "batches": [_coverage(episodes[:32], resources), _coverage(episodes[32:], resources)],
            "episodes_sha256": snapshot_sha256(episodes)})
    for split, rows in evaluation.items():
        _write(output / f"{split}_scenarios.json", rows)
    _write(output / "experiment.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path("docs/baseline_snapshot_training_v1.json"))
    parser.add_argument("--settings", type=Path, default=Path("docs/llm_training_settings_v1.json"))
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--low-reasoning-seed", type=int, default=33,
                        help="Use low reasoning for this group (default: 33); other groups keep the base settings")
    args = parser.parse_args(argv)
    manifest = prepare_experiment(args.protocol, args.settings, args.artifact, args.output,
                                  data_path=args.data, low_reasoning_seed=args.low_reasoning_seed)
    print(json.dumps({"status": manifest["status"], "model_calls": manifest["model_calls"],
                      "seeds": [row["seed"] for row in manifest["seeds"]],
                      "experiment": str(args.output.resolve() / "experiment.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

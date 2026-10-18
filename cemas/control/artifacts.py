"""Concrete baseline and Phase 6 file contracts, without a training dependency."""

import hashlib
import importlib.metadata
import json
from math import fsum, isfinite
from pathlib import Path

from .actions import ACTION_ENCODING
from .logging import resolved_snapshot, snapshot_sha256
from .observation import RL_OBSERVATION_ENCODING_VERSION
from .scenarios import base_model_configuration, population_configuration


BASELINE_SCHEMA = "cemas-baseline-artifact-v1"
RELEASE_SCHEMA = "cemas-phase6-release-v1"


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def baseline_task_configuration(protocol):
    objective = resolved_snapshot(protocol.definition["objective"])
    objective.pop("status", None)
    return resolved_snapshot({
        "population": protocol.population, "execution_days": protocol.execution_days,
        "initial_infections": protocol.initial_infections, "objective": objective,
        "population_configuration": population_configuration(protocol),
        "base_model_configuration": base_model_configuration(protocol),
        "actions": protocol.definition["actions"], "activity": protocol.definition["activity"],
    })


def save_baseline_artifact(output_dir, protocol, method, *, parameters=None,
                           weights_path=None, training=None, selection=None,
                           calibration_artifact=None):
    if method not in ("threshold", "ppo", "ddqn"):
        raise ValueError("baseline method must be threshold, ppo or ddqn")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ("numpy", "torch", "gymnasium", "stable-baselines3", "sb3-contrib"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    weights = None
    if weights_path is not None:
        import os
        path = Path(weights_path).resolve()
        weights = {"path": os.path.relpath(path, output), "sha256": file_sha256(path)}
    task = baseline_task_configuration(protocol)
    from .runner import memory_source_compatibility
    calibration = None
    calibration_sha = None
    if calibration_artifact is not None:
        import os
        calibration_path = Path(calibration_artifact).resolve()
        calibration = {"path": os.path.relpath(calibration_path, output), "sha256": file_sha256(calibration_path)}
        calibration_sha = json.loads(calibration_path.read_text(encoding="utf-8"))["sha256"]
        _sha256(calibration_sha)
    payload = {
        "schema_version": BASELINE_SCHEMA, "method": method,
        "algorithm_semantics": {"threshold": "public-two-week-hysteresis-v1",
                                "ppo": "sb3-maskable-ppo-v1", "ddqn": "masked-double-dqn-v1"}[method],
        "action_encoding": ACTION_ENCODING, "rl_encoding": RL_OBSERVATION_ENCODING_VERSION,
        "reference_population": protocol.population, "reference_horizon": protocol.execution_days,
        "task": task, "task_sha256": snapshot_sha256(task),
        "protocol_sha256": protocol.source_sha256,
        "parameters": parameters, "weights": weights, "training": training,
        "selection": selection, "dependency_versions": versions,
        "source_code_sha256": memory_source_compatibility(protocol)["source_code_sha256"],
        "calibration_artifact_sha256": calibration_sha, "calibration_artifact_file": calibration,
    }
    path = output / "artifact.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(resolved_snapshot(payload), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return path


def get_baseline_artifact(path, protocol):
    path = Path(path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != BASELINE_SCHEMA or payload.get("method") not in ("threshold", "ppo", "ddqn"):
        raise ValueError("unsupported baseline artifact")
    if (payload.get("task") != baseline_task_configuration(protocol)
            or payload.get("task_sha256") != snapshot_sha256(payload["task"])):
        raise ValueError("baseline task is incompatible with current protocol")
    if (payload.get("action_encoding") != ACTION_ENCODING
            or payload.get("rl_encoding") != RL_OBSERVATION_ENCODING_VERSION
            or payload.get("reference_population") != protocol.population
            or payload.get("reference_horizon") != protocol.execution_days):
        raise ValueError("baseline action or observation encoding is incompatible")
    semantics = {"threshold": "public-two-week-hysteresis-v1", "ppo": "sb3-maskable-ppo-v1",
                 "ddqn": "masked-double-dqn-v1"}
    if payload.get("algorithm_semantics") != semantics[payload["method"]]:
        raise ValueError("baseline algorithm semantics are incompatible")
    from .runner import memory_source_compatibility
    if payload.get("source_code_sha256") != memory_source_compatibility(protocol)["source_code_sha256"]:
        raise ValueError("baseline source code is incompatible with the current implementation")
    if payload["calibration_artifact_file"] is not None:
        _sha256(payload["calibration_artifact_sha256"])
        _, calibration = _read_reference(payload["calibration_artifact_file"], path.parent)
        if calibration.get("sha256") != payload["calibration_artifact_sha256"]:
            raise ValueError("baseline E0 semantic identity differs from its file")
    if payload["method"] != "threshold":
        weights = payload["weights"]
        weight_path = (path.parent / weights["path"]).resolve()
        if file_sha256(weight_path) != weights["sha256"]:
            raise ValueError("baseline weights hash mismatch")
        payload["weights_path"] = str(weight_path)
    payload["artifact_path"] = str(path)
    payload["artifact_sha256"] = file_sha256(path)
    return payload


def _sha256(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("artifact identity must be a lowercase SHA-256")
    return value


def _reference_path(reference, root):
    if not isinstance(reference, dict) or type(reference.get("path")) is not str or not reference["path"]:
        raise ValueError("artifact reference requires an actual file path and SHA-256")
    _sha256(reference.get("sha256"))
    path = (root / reference["path"]).resolve()
    if file_sha256(path) != reference["sha256"]:
        raise ValueError(f"release file hash mismatch: {path.name}")
    return path


def _read_reference(reference, root):
    path = _reference_path(reference, root)
    return path, json.loads(path.read_text(encoding="utf-8"))


def training_budget(record_path):
    """Count actual transitions/days, including initialized but unstepped worlds."""
    worlds, transitions, days = {}, 0, 0
    with Path(record_path).open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            world = event["world_seed"]
            if event["event"] == "initializing":
                worlds[world] = {"world_seed": world, "scenario_options": event["scenario_options"],
                                 "elapsed_days": 0, "transitions": 0, "completed": False,
                                 "initialized": False, "failed": False}
            elif event["event"] == "initialized":
                worlds[world]["initialized"] = True
            elif event["event"] == "transition":
                current = worlds[world]
                days += event["elapsed_days"] - current["elapsed_days"]
                transitions += 1
                current.update(elapsed_days=event["elapsed_days"], transitions=current["transitions"]+1)
            elif event["event"] == "completed":
                worlds[world]["completed"] = True
            elif event["event"] == "failed":
                current = worlds[world]
                days += event["elapsed_days"] - current["elapsed_days"]
                current.update(elapsed_days=event["elapsed_days"], failed=True)
    return {"transitions": transitions, "simulated_days": days, "worlds": list(worlds.values()),
            "initialized_unstepped_worlds": [row["world_seed"] for row in worlds.values()
                                             if row["initialized"] and not row["transitions"]]}


def budget_extension(protocol, checkpoint_means, current_budget):
    """Only A curves, averaged over all training seeds, may extend the budget."""
    source = protocol.definition["source"]
    ladder = source["budget_ladder"]
    if current_budget not in ladder:
        raise ValueError("current budget is outside the common protocol ladder")
    if len(checkpoint_means) < 2:
        raise ValueError("budget selection needs the two most recent A checkpoints")
    old, new = checkpoint_means[-2:]
    improvement = (old - new) / max(old, 1e-12)
    improving = improvement >= source["extend_budget_relative_improvement"]
    index = ladder.index(current_budget)
    next_budget = ladder[index + 1] if improving and index + 1 < len(ladder) else current_budget
    return {"current_budget": current_budget, "next_budget": next_budget,
            "relative_improvement": improvement, "improving_at_ceiling": improving and index == len(ladder)-1}


def horizon_report(protocol, selected_records):
    """Final selected B trajectories only; private infections never control a run."""
    gate = protocol.definition["horizon_gate"]
    if set(selected_records) != set(protocol.definition["controllers"]["methods"]):
        raise ValueError("horizon confirmation requires all seven main methods")
    pool = protocol.definition["seeds"]["validation_B"]
    required_worlds = set(range(pool["start_inclusive"], pool["end_inclusive"] + 1))
    reports = {}
    for method, records in selected_records.items():
        seeds = protocol.definition["source"]["train_seed_values"] if method in ("maskable_ppo", "double_dqn") else (None,)
        expected = {(seed, world) for seed in seeds for world in required_worlds}
        identities = [(row.get("train_seed"), row["world_seed"]) for row in records]
        if len(identities) != len(expected) or set(identities) != expected:
            raise ValueError("horizon report requires selected B worlds exactly once per retained training seed")
        affected, per_seed = 0, {}
        for seed in seeds:
            subset = [row for row in records if row.get("train_seed") == seed]
            flags = []
            for row in subset:
                summary = row["summary"]
                if summary["status"] != "completed" or summary["execution_days"] != protocol.execution_days:
                    raise ValueError("horizon evidence must contain complete runs at the common H")
                count = summary["population"]
                flags.append(row["last_window_infections"] > gate["last_window_infections_threshold_ratio"] * count
                    or summary["private_metrics"]["terminal_active_infections"] > gate["terminal_active_infection_threshold_ratio"] * count)
            per_seed[str(seed)] = {"affected": sum(flags), "episodes": len(flags)}
            affected += sum(flags)
        reports[method] = {"affected": affected, "episodes": len(records),
                           "affected_fraction": affected / len(records), "per_seed": per_seed}
    ongoing = any(row["affected_fraction"] > gate["affected_validation_fraction"] for row in reports.values())
    candidates = gate["candidate_days"]
    index = candidates.index(protocol.execution_days)
    next_horizon = candidates[index + 1] if ongoing and index + 1 < len(candidates) else protocol.execution_days
    return {"status": "completed", "execution_days": protocol.execution_days, "methods": reports,
            "next_horizon": next_horizon, "selected_records": selected_records,
            "requires_extension": next_horizon != protocol.execution_days,
            "finite_horizon_limitation": ongoing and index == len(candidates) - 1}


def _llm_identity(protocol, settings):
    from .knowledge import load_knowledge_bundle
    from .llm_memory import memory_prompt_config
    from .memory import load_memory_profile
    from .memory_types import public_hash
    from .runner import make_llm_settings, make_public_prompt_config
    profile = load_memory_profile(settings.get("memory_profile_path"))
    prompt = memory_prompt_config(make_public_prompt_config(protocol), profile)
    actual_settings = make_llm_settings(protocol, provider=settings.get("provider", "deepseek"),
        endpoint=settings["endpoint"], api_key_env=settings.get("api_key_env", "DASHSCOPE_API_KEY"))
    tokenizer_path = Path(settings["tokenizer_manifest"]).resolve()
    tokenizer = json.loads(tokenizer_path.read_text(encoding="utf-8"))
    for filename, digest in tokenizer["files"].items():
        _reference_path({"path": filename, "sha256": digest}, tokenizer_path.parent)
    return {"llm_settings": resolved_snapshot(actual_settings), "template_sha256": prompt.template_sha256,
            "public_spec_sha256": prompt.public_spec_sha256, "memory_profile_sha256": profile.sha256,
            "knowledge_sha256": load_knowledge_bundle(profile.resource_path("knowledge_path")).sha256,
            "retrieval_config_sha256": public_hash(profile.retrieval),
            "tokenizer_identity": {**tokenizer, "manifest_sha256": snapshot_sha256(tokenizer)}}


def _screening_condition(directory, population, ratio):
    import csv
    from fractions import Fraction
    from math import ceil
    with (directory / "public_daily.csv").open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle))
    if int(first["screening_daily_capacity"]) != ceil(Fraction(str(ratio)) * population):
        raise ValueError("source run used a different screening capacity condition")


def _source_evaluation(report, protocol, calibration_sha, method, *, pool="validation_B", parameters=None, model=None, memory_mode=None, llm_identity=None, library_sha=None):
    """Check the actual runner outputs behind each source score."""
    import csv
    from .protocol import source_grid
    from .rewards import V1RewardCalculator
    if report.get("purpose") != "source_development":
        raise ValueError("release evaluations require actual source development, never fixtures")
    if report["pool"] != pool or pool not in ("validation_A", "validation_B"):
        raise ValueError("release scores must come from the declared A/B pools")
    bounds = protocol.definition["seeds"][pool]
    expected = set(range(bounds["start_inclusive"], bounds["end_inclusive"] + 1))
    records = report["records"]
    if len(records) != len(expected) or {row["world_seed"] for row in records} != expected:
        raise ValueError("release evaluation does not cover its source pool exactly once")
    reward = resolved_snapshot(V1RewardCalculator(protocol, protocol.population, protocol.execution_days).configuration)
    reward.pop("status", None)
    for row in records:
        directory = Path(row["output_dir"]).resolve()
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        if (summary != row["summary"] or summary.get("status") != "completed"
                or summary.get("elapsed_days") != protocol.execution_days
                or summary.get("execution_days") != protocol.execution_days
                or summary.get("population") != protocol.population
                or summary.get("daily_weekly_terminal_reconciled") is not True):
            raise ValueError("release evaluation summary differs from a complete common-task run")
        configuration = dict(summary["reward_configuration"])
        configuration.pop("status", None)
        if configuration != reward:
            raise ValueError("release evaluation uses a different objective")
        if (manifest.get("status") != "completed" or manifest.get("purpose") != "scientific"
                or manifest.get("run_purpose") != "scientific" or manifest.get("mode") != "evaluation"
                or manifest.get("world_seed") != row["world_seed"] or manifest.get("controller_type") != method
                or manifest.get("calibration_verified") is not True
                or manifest.get("calibration", {}).get("artifact_sha256") != calibration_sha):
            raise ValueError("release evaluation runner identity, purpose, method or E0 differs")
        condition = source_grid(protocol, pool, row["world_seed"])
        if manifest["calibration"]["beta_scale"] != condition["beta_scale"]:
            raise ValueError("release evaluation uses the wrong source condition")
        _screening_condition(directory, protocol.population, condition["screening_capacity_ratio"])
        if parameters is not None and manifest.get("baseline", {}).get("parameters") != parameters:
            raise ValueError("Threshold evaluation used different parameters")
        if model is not None:
            recorded = manifest.get("baseline", {})
            if (recorded.get("weights", {}).get("sha256") != model["weights"]["sha256"]
                    or recorded.get("training", {}).get("train_seed") != model["training"]["train_seed"]
                    or recorded.get("training", {}).get("steps") != model["training"]["steps"]):
                raise ValueError("evaluation did not use the selected trained model")
        if memory_mode is not None:
            metadata = manifest.get("llm", {})
            if (metadata.get("live_provider") is not True or metadata.get("memory_mode") != memory_mode
                    or any(metadata.get(key) != value for key, value in llm_identity.items())
                    or memory_mode in ("global", "both") and metadata.get("case_store_sha256") != library_sha):
                raise ValueError("LLM evidence is synthetic or uses another memory mode")
        with (directory / "private_daily.csv").open(encoding="utf-8", newline="") as handle:
            days = list(csv.DictReader(handle))
        width = protocol.definition["horizon_gate"]["last_window_days"]
        if (len(days) != protocol.execution_days or [int(day["day"]) for day in days] != list(range(protocol.execution_days))
                or row["last_window_infections"] != sum(int(day["new_infections"]) for day in days[-width:])):
            raise ValueError("horizon infection evidence differs from the actual daily records")
    costs = [row["summary"]["positive_cost"] for row in records]
    activities = [row["summary"]["reward_breakdown"]["normalized"][4] for row in records]
    if (any(not isfinite(value) for value in (*costs, *activities))
            or report["mean_positive_cost"] != fsum(costs) / len(costs)
            or report["mean_normalized_activity"] != fsum(activities) / len(activities)):
        raise ValueError("release score aggregation does not match completed run summaries")
    return records


def _threshold_selection(artifact, protocol, calibration_sha):
    report = artifact["selection"]
    config = protocol.definition["controllers"]["threshold"]
    candidates = report["candidates"]
    if (report.get("purpose") != "source_development" or report.get("method") != "threshold"
            or len(candidates) != config["candidate_count"]
            or {row["candidate_id"] for row in candidates} != set(range(config["candidate_count"]))):
        raise ValueError("Threshold selection requires its complete prespecified source candidates")
    for candidate in candidates:
        _source_evaluation(candidate["validation_A"], protocol, calibration_sha, "threshold", pool="validation_A", parameters=candidate["parameters"])
    rank = lambda row, split: (row[split]["mean_positive_cost"], row[split]["mean_normalized_activity"], row["candidate_id"])
    finalists = sorted(candidates, key=lambda row: rank(row, "validation_A"))[:config["finalists"]]
    if {row["candidate_id"] for row in candidates if "validation_B" in row} != {row["candidate_id"] for row in finalists}:
        raise ValueError("Threshold B evaluations must be exactly the four A finalists")
    for candidate in finalists:
        _source_evaluation(candidate["validation_B"], protocol, calibration_sha, "threshold", parameters=candidate["parameters"])
    selected = min(finalists, key=lambda row: rank(row, "validation_B"))
    episodes = sum(len(row["validation_A"]["records"]) + len(row.get("validation_B", {}).get("records", [])) for row in candidates)
    a = protocol.definition["seeds"]["validation_A"]
    b = protocol.definition["seeds"]["validation_B"]
    expected_episodes = (config["candidate_count"] * (a["end_inclusive"] - a["start_inclusive"] + 1)
                         + config["finalists"] * (b["end_inclusive"] - b["start_inclusive"] + 1))
    if (report["selected_candidate_id"] != selected["candidate_id"] or artifact["parameters"] != selected["parameters"]
            or report["validation_episode_count"] != episodes or episodes != expected_episodes):
        raise ValueError("Threshold artifact does not match the 32-to-4-to-1 source selection")
    return selected["validation_B"]["records"]


def _rl_selection(artifact, report, report_path, protocol, calibration_sha):
    seed = artifact["training"]["train_seed"]
    method = artifact["method"]
    rows = report["checkpoints"][str(seed)]
    if [row["step"] for row in rows] != list(range(protocol.definition["source"]["checkpoint_steps"],
            rows[-1]["step"] + 1, protocol.definition["source"]["checkpoint_steps"])):
        raise ValueError("RL training report has missing checkpoints")
    for row in rows:
        if row["train_seed"] != seed:
            raise ValueError("RL checkpoint selection crosses training seeds")
        checkpoint = get_baseline_artifact(row["artifact"], protocol)
        if (checkpoint["method"] != method or checkpoint["training"]["steps"] != row["step"]
                or checkpoint["training"]["train_seed"] != seed or checkpoint["calibration_artifact_sha256"] != calibration_sha):
            raise ValueError("RL checkpoint metadata differs from its evaluation")
        _source_evaluation(row["validation_A"], protocol, calibration_sha, method, pool="validation_A", model=checkpoint)
    count = protocol.definition["source"]["final_checkpoint_candidates"]
    finalists = sorted(rows, key=lambda row: (row["validation_A"]["mean_positive_cost"], row["step"], str(row["artifact"])))[:count]
    choice = artifact["selection"]
    if (choice["train_seed"] != seed or len(choice["candidates"]) != count
            or {row["artifact"] for row in choice["candidates"]} != {row["artifact"] for row in finalists}):
        raise ValueError("RL B candidates are not the two best A checkpoints for this seed")
    for row in choice["candidates"]:
        original = next(item for item in finalists if item["artifact"] == row["artifact"])
        if {key: value for key, value in row.items() if key != "validation_B"} != original:
            raise ValueError("RL B candidate metadata differs from its A finalist")
        checkpoint = get_baseline_artifact(row["artifact"], protocol)
        _source_evaluation(row["validation_B"], protocol, calibration_sha, method, model=checkpoint)
    selected = min(choice["candidates"], key=lambda row: (row["validation_B"]["mean_positive_cost"], row["step"], str(row["artifact"])))
    selected_checkpoint = get_baseline_artifact(selected["artifact"], protocol)
    if (choice["selected"] != selected or artifact["weights"]["sha256"] != selected_checkpoint["weights"]["sha256"]
            or artifact["training"]["steps"] != selected["step"]):
        raise ValueError("RL release artifact differs from the selected B winner")
    saved = [row for row in report["selected_models"] if row["train_seed"] == seed]
    if (len(saved) != 1 or {k: v for k, v in saved[0].items() if k != "artifact"} != choice
            or file_sha256(saved[0]["artifact"]) != artifact["artifact_sha256"]):
        raise ValueError("RL training and selected artifact records disagree")
    actual = training_budget(report_path.parent / f"worlds-{seed}.jsonl")
    if (actual != report["actual_training"][str(seed)] or actual["transitions"] != rows[-1]["step"]
            or any(row["failed"] for row in actual["worlds"])):
        raise ValueError("RL budget does not match the actual worker transition records")
    return selected["validation_B"]["records"]


def _horizon_evidence(report, selected_records, protocol):
    order = lambda records: sorted(records, key=lambda row: (row.get("train_seed") or 0, row["world_seed"]))
    if (set(report.get("selected_records", {})) != set(selected_records)
            or any(order(report["selected_records"][method]) != order(records) for method, records in selected_records.items())):
        raise ValueError("horizon evidence must use exactly the final selected methods and B trajectories")
    expected = horizon_report(protocol, selected_records)
    if expected["requires_extension"] or any(report.get(key) != value for key, value in expected.items() if key != "selected_records"):
        raise ValueError("the common H needs redevelopment or an explicit H168 finite-horizon limitation")


def _source_trajectories(manifest, protocol, calibration_sha):
    """Bind source registrations to the audited collection runs, without replay."""
    for entry in manifest["trajectories"]:
        if not {"run_dir", "run_manifest_sha256", "run_summary_sha256", "public_transitions_sha256"} <= entry.keys():
            raise ValueError("source trajectories require references to actual audited runner outputs")
        directory = Path(entry["run_dir"])
        values = {}
        for filename, key in (("manifest.json", "run_manifest_sha256"), ("summary.json", "run_summary_sha256"),
                              ("public_transitions.json", "public_transitions_sha256")):
            _, values[filename] = _read_reference({"path": filename, "sha256": entry[key]}, directory)
        run, summary = values["manifest.json"], values["summary.json"]
        expected_method = "threshold" if entry["policy"] == "tuned_threshold" else entry["policy"]
        if (run.get("status") != "completed" or run.get("purpose") != "memory_collection"
                or run.get("run_purpose") != "memory_collection" or run.get("mode") != "evaluation"
                or run.get("world_seed") != entry["seed"] or run.get("controller_type") != expected_method
                or run.get("calibration", {}).get("artifact_sha256") != calibration_sha
                or run.get("calibration", {}).get("beta_scale") != entry["world"]["beta_scale"]
                or summary.get("status") != "completed" or summary.get("elapsed_days") != protocol.execution_days
                or summary.get("execution_days") != protocol.execution_days or summary.get("population") != protocol.population
                or summary.get("daily_weekly_terminal_reconciled") is not True
                or values["public_transitions.json"].get("synthetic_fixture") is not False):
            raise ValueError("source registrations do not match actual completed collection runs")
        _screening_condition(directory, protocol.population, entry["world"]["screening_capacity_ratio"])
        if expected_method == "threshold" and run.get("baseline", {}).get("artifact_sha256") != entry["baseline_artifact_sha256"]:
            raise ValueError("Threshold source run did not load its registered parameter artifact")


def _training_report(report, protocol, method):
    source = protocol.definition["source"]
    seeds = {str(seed) for seed in source["train_seed_values"]}
    if (report.get("status") != "completed" or report.get("purpose") != "source_development"
            or report.get("method") != method or set(report["checkpoints"]) != seeds
            or set(report["actual_training"]) != seeds or len(report["selected_models"]) != len(seeds)):
        raise ValueError("training evidence must retain all three independent seeds")
    curves = {seed: [row["step"] for row in report["checkpoints"][seed]] for seed in seeds}
    final = next(iter(curves.values()))[-1]
    ceiling = report["available_budget_ceiling"]
    if (any(curve != next(iter(curves.values())) for curve in curves.values())
            or final not in source["budget_ladder"] or ceiling not in source["budget_ladder"] or final > ceiling):
        raise ValueError("RL seeds do not have the same valid actual training budget")
    budgets = source["budget_ladder"][:source["budget_ladder"].index(final) + 1]
    if [row["current_budget"] for row in report["budget_decisions"]] != list(budgets):
        raise ValueError("RL budget decisions skip a required common budget stage")
    for decision in report["budget_decisions"]:
        budget = decision["current_budget"]
        values = []
        for step in (budget - source["checkpoint_steps"], budget):
            values.append(fsum(next(row["validation_A"]["mean_positive_cost"] for row in report["checkpoints"][seed]
                                     if row["step"] == step) for seed in sorted(seeds)) / len(seeds))
        expected = budget_extension(protocol, values, budget)
        next_budget = expected["next_budget"]
        if (decision["relative_improvement"] != expected["relative_improvement"] or decision["next_budget"] != next_budget
                or decision["resource_ceiling"] != ceiling
                or budget < final and (next_budget <= budget or next_budget > ceiling)
                or budget == final and budget < next_budget <= ceiling):
            raise ValueError("RL budget extension does not follow the A-only improvement rule")


def _validate_phase6_release(release_path, *, development_dir=None):
    """Validate real source data, final selections and auditable freeze evidence."""
    from .memory import public_task_hash
    from .memory_store import DATABASE_FILENAME, FrozenPublicCaseStore, verify_source_manifest, coverage_report
    from .protocol import load_protocol
    from .runner import make_public_prompt_config, memory_source_compatibility
    path = Path(release_path).resolve()
    release = json.loads(path.read_text(encoding="utf-8"))
    if release.get("schema_version") != RELEASE_SCHEMA or release.get("incomplete") != [] or release.get("purpose") != "source_development":
        raise ValueError("Phase 6 release is incomplete, synthetic or has an unsupported schema")
    protocol_path, _ = _read_reference(release["protocol"], path.parent)
    protocol = load_protocol(protocol_path)
    if release.get("task") != baseline_task_configuration(protocol):
        raise ValueError("release task does not match its frozen protocol")
    calibration_path = _reference_path(release["calibration_artifact_file"], path.parent)
    data_path = _reference_path(release["calibration_data_file"], path.parent) if release.get("calibration_data_file") else None
    compatibility = memory_source_compatibility(protocol, calibration_path, data_path=data_path)
    calibration_sha = compatibility["calibration_artifact_sha256"]
    if release["calibration_artifact_sha256"] != calibration_sha:
        raise ValueError("release E0 semantic identity differs from verified calibration evidence")
    library = release["development"]
    library_dir = Path(development_dir).resolve() if development_dir else (path.parent / library["path"]).resolve()
    manifest_path = library_dir / "build_manifest.json"
    manifest = verify_source_manifest(manifest_path, compatibility, purpose="development")
    if (manifest["public_task_sha256"] != public_task_hash(make_public_prompt_config(protocol), protocol.execution_days)
            or file_sha256(library_dir / DATABASE_FILENAME) != library["database_sha256"]
            or file_sha256(manifest_path) != library["build_manifest_sha256"]):
        raise ValueError("release development library task or data identity differs")
    with FrozenPublicCaseStore.open(library_dir, library_dir / "store_manifest.json") as store:
        if store.purpose != "development" or store.public_task_sha256 != manifest["public_task_sha256"]:
            raise ValueError("release requires the actual verified development publication")
    _source_trajectories(manifest, protocol, calibration_sha)
    coverage = coverage_report(manifest_path)
    if not coverage["exact_108_identity_coverage"] or not coverage["public_case_coverage"]["action_coverage_complete"]:
        raise ValueError("release source identity or executed-action coverage is incomplete")
    evidence = release["evidence"]
    _, saved_coverage = _read_reference(evidence["coverage"], path.parent)
    if saved_coverage != resolved_snapshot(coverage):
        raise ValueError("coverage evidence differs from the actual source database")
    _, holdout = _read_reference(evidence["world_holdout"], path.parent)
    queries = {seed: sum(len(row["case_ids"]) for row in manifest["trajectories"] if row["seed"] == seed) for seed in range(30001, 30028)}
    if (holdout.get("status") != "completed" or holdout.get("purpose") != "development"
            or holdout.get("database_sha256") != library["database_sha256"]
            or holdout.get("public_task_sha256") != manifest["public_task_sha256"]
            or holdout.get("kind") != "offline_leave_world_out_retrieval" or holdout.get("control_effectiveness_experiment") is not False
            or len(holdout["worlds"]) != 27 or {row["world_seed"] for row in holdout["worlds"]} != set(queries)
            or any(row["queries"] != queries[row["world_seed"]] or sum(row["statuses"].values()) != row["queries"] for row in holdout["worlds"])):
        raise ValueError("world holdout evidence does not cover all four policies of every source world")
    artifacts = release["baseline_artifacts"]
    if set(artifacts) != {"threshold", "ppo", "ddqn"} or set(evidence["budget"]) != {"ppo", "ddqn"}:
        raise ValueError("release requires all three baselines and both actual training reports")
    selected_records = {}
    ceilings = []
    for method in ("threshold", "ppo", "ddqn"):
        references = [artifacts[method]] if method == "threshold" else artifacts[method]
        if len(references) != (1 if method == "threshold" else 3):
            raise ValueError("release must retain all three training seeds per RL algorithm")
        seed_records = []
        if method != "threshold":
            report_path, budget = _read_reference(evidence["budget"][method], path.parent)
            _training_report(budget, protocol, method)
            ceilings.append(budget["available_budget_ceiling"])
        seeds = set()
        for reference in references:
            artifact_path = _reference_path(reference, path.parent)
            artifact = get_baseline_artifact(artifact_path, protocol)
            if artifact["method"] != method or artifact["calibration_artifact_sha256"] != calibration_sha:
                raise ValueError("release baseline method or verified E0 identity differs")
            if method == "threshold":
                selected_records["tuned_threshold"] = _threshold_selection(artifact, protocol, calibration_sha)
                if any(row.get("baseline_artifact_sha256") != reference["sha256"] for row in manifest["trajectories"] if row["policy"] == "tuned_threshold"):
                    raise ValueError("source library did not use the selected Threshold artifact")
            else:
                seed = artifact["training"]["train_seed"]
                seeds.add(seed)
                seed_records.extend({**row, "train_seed": seed} for row in _rl_selection(artifact, budget, report_path, protocol, calibration_sha))
        if method != "threshold":
            if seeds != set(protocol.definition["source"]["train_seed_values"]):
                raise ValueError("release RL training seeds are incomplete")
            selected_records[{"ppo": "maskable_ppo", "ddqn": "double_dqn"}[method]] = seed_records
    if len(set(ceilings)) != 1:
        raise ValueError("PPO and DDQN must have the same available training budget ceiling")
    _, llm = _read_reference(evidence["llm"], path.parent)
    modes = {"none", "short", "global", "both"}
    if (llm.get("status") != "completed" or llm.get("purpose") != "source_development" or llm.get("final_test_read") is not False
            or set(llm["selected"]) != modes or set(release["llm_configs"]) != modes):
        raise ValueError("release requires actual source development of all four LLM memory modes")
    shared_llm_identity = None
    for mode in sorted(modes):
        winner = llm["selected"][mode]
        _, settings = _read_reference(release["llm_configs"][mode], path.parent)
        candidates = [row for row in llm["candidates"] if row["settings"]["memory_mode"] == mode]
        for row in candidates:
            _source_evaluation(row["validation_A"], protocol, calibration_sha, "llm", pool="validation_A", memory_mode=mode,
                llm_identity=_llm_identity(protocol, row["settings"]), library_sha=library["database_sha256"])
        best = min(candidates, key=lambda row: (row["validation_A"]["mean_positive_cost"], str(row["candidate_id"])))
        if settings != winner["settings"] or {k: v for k, v in winner.items() if k != "validation_B"} != best:
            raise ValueError("LLM frozen settings differ from the source A winner")
        identity = _llm_identity(protocol, settings)
        if shared_llm_identity is None:
            shared_llm_identity = identity
        elif identity != shared_llm_identity:
            raise ValueError("the four memory modes must share model, prompt, knowledge, retrieval and tokenizer resources")
        records = _source_evaluation(winner["validation_B"], protocol, calibration_sha, "llm", memory_mode=mode,
            llm_identity=identity, library_sha=library["database_sha256"])
        if mode in ("none", "both"):
            selected_records["llm_no_explicit_memory" if mode == "none" else "llm_full"] = records
    _, horizon = _read_reference(evidence["horizon"], path.parent)
    for method in ("minimum", "maximum_feasible"):
        records = horizon["selected_records"][method]
        report = {"pool": "validation_B", "purpose": "source_development", "records": records,
                  "mean_positive_cost": fsum(row["summary"]["positive_cost"] for row in records) / len(records),
                  "mean_normalized_activity": fsum(row["summary"]["reward_breakdown"]["normalized"][4] for row in records) / len(records)}
        selected_records[method] = _source_evaluation(report, protocol, calibration_sha, method)
    _horizon_evidence(horizon, selected_records, protocol)
    return release


def validate_phase6_release(release_path, *, development_dir=None):
    """Check primary and independent sensitivity releases without cyclic hashes."""
    path = Path(release_path).resolve()
    release = _validate_phase6_release(path, development_dir=development_dir)
    if release["task"]["objective"]["lambda"] != 1:
        return release
    if release.get("sensitivity_frozen") is not True or not release.get("sensitivity_releases"):
        raise ValueError("Phase 7 sensitivity prerequisites require actual frozen release references")
    sensitivity_values = set()
    for reference in release["sensitivity_releases"]:
        sensitivity_path = _reference_path(reference, path.parent)
        sensitivity = _validate_phase6_release(sensitivity_path)
        primary_task = resolved_snapshot(release["task"])
        sensitivity_task = resolved_snapshot(sensitivity["task"])
        primary_task["objective"].pop("lambda")
        sensitivity_task["objective"].pop("lambda")
        if sensitivity_task != primary_task:
            raise ValueError("sensitivity source development changes more than the declared lambda")
        sensitivity_values.add(sensitivity["task"]["objective"]["lambda"])
    if sensitivity_values != {.5, 2.0}:
        raise ValueError("the independently redeveloped lambda .5 and 2 sensitivity batches are missing")
    return release

"""Concrete source-development orchestration, separate from controller inputs."""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import json
from math import fsum, isfinite, log
import multiprocessing
from pathlib import Path
import random
import sys

import numpy as np

from .logging import resolved_snapshot, snapshot_sha256
from .protocol import source_grid
from .artifacts import (THRESHOLD_ALGORITHM_SEMANTICS, budget_extension,
                        horizon_report, training_budget)


def _write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(resolved_snapshot(value), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


class TrainingEpisodePlan:
    """Independent, without-replacement source worlds shared by both algorithms."""

    def __init__(self, protocol, train_seed, calibration_artifact, *, calibration_data_path=None):
        source = protocol.definition["source"]
        seeds = source["train_seed_values"]
        if train_seed not in seeds:
            raise ValueError("train_seed must be one of the three protocol training seeds")
        pool = source["source_world_pools"][seeds.index(train_seed)]
        world_rng, self._beta_rng, self._capacity_rng = [np.random.default_rng(sequence)
            for sequence in np.random.SeedSequence(train_seed).spawn(3)]
        self._worlds = world_rng.permutation(np.arange(pool["start_inclusive"], pool["end_exclusive"]))
        self._beta_range = source["beta_scale_uniform"]
        self._capacities = protocol.definition["resources"]["screening_static_capacity_ratios"]
        self._artifact = str(calibration_artifact)
        self._data = str(calibration_data_path) if calibration_data_path is not None else None
        self.train_seed, self._index = train_seed, 0

    def __call__(self, seed=None):
        if seed is not None and (seed != self.train_seed or self._index):
            raise ValueError("episode scheduling can only be seeded with its declared training seed before use")
        if self._index == len(self._worlds):
            raise RuntimeError("the reserved source-world pool is exhausted")
        world_seed = int(self._worlds[self._index])
        self._index += 1
        return {"world_seed": world_seed, "scenario_options": {
            "beta_scale": float(self._beta_rng.uniform(*self._beta_range)),
            "screening_capacity_ratio": float(self._capacity_rng.choice(self._capacities)),
            "calibration_artifact": self._artifact, "calibration_data_path": self._data}}


def threshold_candidates(protocol):
    config = protocol.definition["controllers"]["threshold"]
    rng = np.random.default_rng(config["candidate_generator_seed"])
    low, high = config["independent_dimension_scale_loguniform"]
    result = []
    for identity in range(config["candidate_count"]):
        scales = np.exp(rng.uniform(log(low), log(high), len(protocol.action_order)))
        thresholds = {name: [float(value * scale) for value in
            config["base_thresholds_per_1000_per_week"][name]]
            for name, scale in zip(protocol.action_order, scales)}
        result.append({"candidate_id": identity, "scales": scales.tolist(),
                       "parameters": {"thresholds": thresholds}})
    return result


def _pool_seeds(protocol, pool):
    bounds = protocol.definition["seeds"][pool]
    return tuple(range(bounds["start_inclusive"], bounds["end_inclusive"] + 1))


def _scores(records, expected_seeds):
    worlds = [row["world_seed"] for row in records]
    if len(worlds) != len(expected_seeds) or set(worlds) != set(expected_seeds):
        raise ValueError("evaluation must contain every declared world exactly once")
    if any(row["summary"]["status"] != "completed" for row in records):
        raise ValueError("incomplete evaluations cannot be averaged")
    cost = [row["summary"]["positive_cost"] for row in records]
    activity = [row["summary"]["reward_breakdown"]["normalized"][4] for row in records]
    if any(not isfinite(value) for value in (*cost, *activity)):
        raise ValueError("evaluation scores must be finite")
    return {"mean_positive_cost": fsum(cost) / len(cost),
            "mean_normalized_activity": fsum(activity) / len(activity)}


def evaluate_source(protocol, controller_spec, output_dir, calibration_artifact, *,
                    pool="validation_A", calibration_data_path=None, evaluator=None):
    """A single spawned evaluator preserves the learner's process RNG state."""
    from .worker import evaluate_job

    if pool not in ("validation_A", "validation_B"):
        raise ValueError("source model evaluation is restricted to validation A or B")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    jobs = []
    for seed in _pool_seeds(protocol, pool):
        condition = source_grid(protocol, pool, seed)
        jobs.append({"protocol_path": str(protocol.source_path), "controller": controller_spec,
                     "world_seed": seed, "output_dir": str(output / str(seed)),
                     "scenario_options": {"calibration_artifact": str(calibration_artifact),
                         "calibration_data_path": str(calibration_data_path) if calibration_data_path else None,
                         "beta_scale": condition["beta_scale"],
                         "screening_capacity_ratio": condition["screening_capacity_ratio"]}})
    if evaluator is None:
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            # Exceptions propagate; runner attempt directories retain failure evidence.
            records = list(executor.map(evaluate_job, jobs))
    else:
        records = [evaluator(job) for job in jobs]
    report = {"purpose": "fixture" if evaluator else "source_development", "pool": pool,
              "records": records, **_scores(records, _pool_seeds(protocol, pool))}
    _write(output / "evaluation.json", report)
    return report


def tune_threshold(protocol, output_dir, calibration_artifact, *, calibration_data_path=None, evaluator=None):
    from .artifacts import baseline_task_configuration, save_baseline_artifact

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    candidates = threshold_candidates(protocol)
    _write(output / "candidates.json", {
        "algorithm_semantics": THRESHOLD_ALGORITHM_SEMANTICS,
        "task_sha256": snapshot_sha256(baseline_task_configuration(protocol)),
        "candidate_generator_seed": protocol.definition["controllers"]["threshold"]["candidate_generator_seed"],
        "candidates": candidates})
    for candidate in candidates:
        spec = {"method": "threshold", "parameters": candidate["parameters"]}
        candidate["validation_A"] = evaluate_source(protocol, spec,
            output / f"A-{candidate['candidate_id']:02d}", calibration_artifact,
            calibration_data_path=calibration_data_path, evaluator=evaluator)
    def ranking(candidate, split):
        report = candidate[split]
        return report["mean_positive_cost"], report["mean_normalized_activity"], candidate["candidate_id"]
    finalists = sorted(candidates, key=lambda row: ranking(row, "validation_A"))[
        :protocol.definition["controllers"]["threshold"]["finalists"]]
    for candidate in finalists:
        candidate["validation_B"] = evaluate_source(protocol,
            {"method": "threshold", "parameters": candidate["parameters"]},
            output / f"B-{candidate['candidate_id']:02d}", calibration_artifact,
            pool="validation_B", calibration_data_path=calibration_data_path, evaluator=evaluator)
    selected = min(finalists, key=lambda row: ranking(row, "validation_B"))
    report = {"purpose": "fixture" if evaluator else "source_development",
              "method": "threshold", "algorithm_semantics": THRESHOLD_ALGORITHM_SEMANTICS,
              "task_sha256": snapshot_sha256(baseline_task_configuration(protocol)), "candidates": candidates,
              "selected_candidate_id": selected["candidate_id"],
              "validation_episode_count": sum(len(row["validation_A"]["records"]) +
                  len(row.get("validation_B", {}).get("records", ())) for row in candidates)}
    _write(output / "selection.json", report)
    artifact = save_baseline_artifact(output / "selected", protocol, "threshold",
        parameters=selected["parameters"], selection=report, calibration_artifact=calibration_artifact)
    return {"artifact": str(artifact), "selection": report}


@dataclass
class LearnerRNGState:
    python: object
    numpy: object
    torch: object

    @classmethod
    def capture(cls):
        import torch
        return cls(random.getstate(), np.random.get_state(), torch.get_rng_state().clone())

    def restore(self):
        import torch
        random.setstate(self.python)
        np.random.set_state(self.numpy)
        torch.set_rng_state(self.torch)


def select_checkpoint(protocol, checkpoints, evaluate):
    """Select within one training seed, retaining all B candidate evidence."""
    if not checkpoints or len({row["train_seed"] for row in checkpoints}) != 1:
        raise ValueError("checkpoint selection requires exactly one training seed")
    candidates = sorted(checkpoints, key=lambda row: (
        row["validation_A"]["mean_positive_cost"], row["step"], str(row["artifact"])))[
        :protocol.definition["source"]["final_checkpoint_candidates"]]
    evaluated = [{**row, "validation_B": evaluate(row)} for row in candidates]
    for row in evaluated:
        _scores(row["validation_B"]["records"], _pool_seeds(protocol, "validation_B"))
    selected = min(evaluated, key=lambda row: (
        row["validation_B"]["mean_positive_cost"], row["step"], str(row["artifact"])))
    return {"train_seed": selected["train_seed"], "selected": selected, "candidates": evaluated}


def train_controller(protocol, method, output_dir, calibration_artifact, *, calibration_data_path=None,
                     maximum_budget=None, evaluator=None):
    """Train three independent learners in 2048-step chunks, then select per seed."""
    if method not in ("ppo", "ddqn"):
        raise ValueError("training supports ppo and ddqn")
    if protocol.execution_days <= protocol.definition["engine"]["initial_baseline_days"]:
        raise ValueError("RL training requires at least one autonomous decision window")
    # Optional dependencies are loaded only when actual training is requested.
    import torch
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from .artifacts import save_baseline_artifact, get_baseline_artifact
    from .worker import TrainingEnvFactory

    source = protocol.definition["source"]
    ceiling = maximum_budget if maximum_budget is not None else source["budget_ladder"][-1]
    if ceiling not in source["budget_ladder"]:
        raise ValueError("maximum_budget must belong to the protocol budget ladder")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    learners, environments, rngs = {}, {}, {}
    checkpoints = {seed: [] for seed in source["train_seed_values"]}
    means, decisions = [], []
    try:
        for seed in source["train_seed_values"]:
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            env = SubprocVecEnv([TrainingEnvFactory(str(protocol.source_path), seed,
                str(calibration_artifact), str(output / f"worlds-{seed}.jsonl"),
                str(calibration_data_path) if calibration_data_path else None)], start_method="spawn")
            environments[seed] = env
            config = resolved_snapshot(protocol.definition["controllers"][method])
            if method == "ppo":
                from .rl.ppo import build_ppo
                learner = build_ppo(env, config, seed)
            else:
                from .rl.ddqn import DDQNTrainer
                learner = DDQNTrainer(env, config, seed,
                    initial_budget=source["initial_week_decisions_per_training_seed"])
            learners[seed], rngs[seed] = learner, LearnerRNGState.capture()
        current_budget = source["initial_week_decisions_per_training_seed"]
        step, chunk = 0, source["checkpoint_steps"]
        while True:
            while step < current_budget:
                step += chunk
                a_scores = []
                for seed, learner in learners.items():
                    rngs[seed].restore()
                    if method == "ppo":
                        learner.learn(total_timesteps=chunk, reset_num_timesteps=False)
                    else:
                        learner.train(chunk)
                    checkpoint_dir = output / f"seed-{seed}" / f"step-{step}"
                    checkpoint_dir.mkdir(parents=True)
                    weights = checkpoint_dir / ("model.zip" if method == "ppo" else "model.pt")
                    learner.save(str(weights))
                    rngs[seed] = LearnerRNGState.capture()
                    artifact = save_baseline_artifact(checkpoint_dir / "artifact", protocol, method,
                        weights_path=weights, calibration_artifact=calibration_artifact,
                        training={"train_seed": seed, "steps": step,
                                  "episode_plan": training_budget(output / f"worlds-{seed}.jsonl")})
                    validation = evaluate_source(protocol, {"method": method, "artifact": str(artifact)},
                        checkpoint_dir / "A", calibration_artifact,
                        calibration_data_path=calibration_data_path, evaluator=evaluator)
                    checkpoints[seed].append({"train_seed": seed, "step": step,
                                              "artifact": str(artifact), "validation_A": validation})
                    a_scores.append(validation["mean_positive_cost"])
                means.append(fsum(a_scores) / len(a_scores))
            decision = budget_extension(protocol, means, current_budget)
            decision["resource_ceiling"] = ceiling
            decision["stopped_by_resource_ceiling"] = decision["next_budget"] > ceiling
            decisions.append(decision)
            if decision["next_budget"] <= current_budget or decision["next_budget"] > ceiling:
                break
            current_budget = decision["next_budget"]
        selections = []
        for seed, rows in checkpoints.items():
            def evaluate(row):
                return evaluate_source(protocol, {"method": method, "artifact": row["artifact"]},
                    output / f"seed-{seed}" / f"B-step-{row['step']}", calibration_artifact,
                    pool="validation_B", calibration_data_path=calibration_data_path, evaluator=evaluator)
            choice = select_checkpoint(protocol, rows, evaluate)
            metadata = get_baseline_artifact(choice["selected"]["artifact"], protocol)
            artifact = save_baseline_artifact(output / f"selected-{seed}", protocol, method,
                weights_path=metadata["weights_path"], calibration_artifact=calibration_artifact,
                training=metadata["training"], selection=choice)
            selections.append({**choice, "artifact": str(artifact)})
        report = {"status": "completed", "purpose": "fixture" if evaluator else "source_development",
                  "method": method, "available_budget_ceiling": ceiling,
                  "checkpoints": checkpoints, "budget_decisions": decisions,
                  "selected_models": selections, "actual_training": {
                      seed: training_budget(output / f"worlds-{seed}.jsonl") for seed in learners}}
        _write(output / "training.json", report)
        return report
    except BaseException as error:
        try:
            _write(output / "failure.json", {"status": "failed", "method": method,
                   "error_type": type(error).__name__, "checkpoints": checkpoints,
                   "budget_decisions": decisions})
        except Exception as audit_error:
            from .runner import _add_error_note
            _add_error_note(error, f"Training failure evidence also failed ({type(audit_error).__name__})")
        raise
    finally:
        active_error = sys.exc_info()[1]
        for env in environments.values():
            try:
                env.close()
            except Exception as close_error:
                if active_error is None:
                    raise
                from .runner import _add_error_note
                _add_error_note(active_error, f"Training environment close also failed ({type(close_error).__name__})")


def world_holdout_report(store, case_worlds, *, retrieval_config=None):
    """Offline retrieval diagnostics; exclude every policy and revision of a world."""
    from .actions import encode_action
    from .retrieval import NumericRetriever, build_case_query

    cases = store.cases()
    if {case.case_id for case in cases} != set(case_worlds):
        raise ValueError("world holdout requires an exact private case-to-world mapping")
    class WorldView:
        def __init__(self, world):
            self.world = world
        def cases(self):
            return tuple(case for case in cases if case_worlds[case.case_id] != self.world)
        def group_for(self, case_id):
            return store.group_for(case_id)
    result = []
    for world in sorted(set(case_worlds.values())):
        retriever = NumericRetriever(WorldView(world), retrieval_config)
        queries = [case for case in cases if case_worlds[case.case_id] == world]
        statuses, scores, distances, actions = Counter(), [], [], set()
        for case in queries:
            found = retriever.retrieve(build_case_query(case.pre_observation, case.public_task_sha256))
            statuses[found.status] += 1
            for item in found.items:
                scores.append(item.final_score)
                distances.append(item.state_rms)
                actions.add(encode_action(item.case.executed_window.executed_action))
        result.append({"world_seed": world, "queries": len(queries), "statuses": dict(statuses),
                       "retrieved_items": len(scores), "mean_state_rms": fsum(distances)/len(distances) if distances else None,
                       "mean_score": fsum(scores)/len(scores) if scores else None,
                       "retrieved_action_count": len(actions)})
    return {"status": "completed", "purpose": store.purpose,
            "database_sha256": store.store_sha256, "public_task_sha256": store.public_task_sha256,
            "kind": "offline_leave_world_out_retrieval", "control_effectiveness_experiment": False,
            "worlds": result}


def develop_llm(protocol, candidates, output_dir, calibration_artifact, *, calibration_data_path=None, evaluator=None):
    """Evaluate only prespecified candidates; A chooses, B confirms each memory mode."""
    modes = ("none", "short", "global", "both")
    if not candidates or {row["settings"]["memory_mode"] for row in candidates} != set(modes):
        raise ValueError("LLM development candidates must cover all four existing memory modes")
    if len({row["candidate_id"] for row in candidates}) != len(candidates):
        raise ValueError("LLM candidate identities must be unique")
    if any(not row.get("hypothesis") for row in candidates):
        raise ValueError("each prespecified LLM candidate needs its development hypothesis")
    providers = {(row["settings"].get("provider", "deepseek"), row["settings"]["endpoint"])
                 for row in candidates}
    if len(providers) != 1:
        raise ValueError("four memory modes must use the same provider and model endpoint")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "candidates.json", candidates)
    results = []
    for identity, candidate in enumerate(candidates):
        validation = evaluate_source(protocol, {"method": "llm", "settings": candidate["settings"]},
            output / f"A-{identity}", calibration_artifact,
            calibration_data_path=calibration_data_path, evaluator=evaluator)
        results.append({**candidate, "validation_A": validation})
    selected = {}
    for mode in modes:
        winner = min((row for row in results if row["settings"]["memory_mode"] == mode),
            key=lambda row: (row["validation_A"]["mean_positive_cost"], str(row["candidate_id"])))
        selected[mode] = {**winner, "validation_B": evaluate_source(protocol,
            {"method": "llm", "settings": winner["settings"]}, output / f"B-{mode}",
            calibration_artifact, pool="validation_B", calibration_data_path=calibration_data_path, evaluator=evaluator)}
    report = {"status": "completed", "purpose": "fixture" if evaluator else "source_development",
              "candidates": results, "selected": selected, "final_test_read": False}
    _write(output / "llm_development.json", report)
    return report


def run_pilot(protocol, controller_spec, output_dir, calibration_artifact, *, calibration_data_path=None, evaluator=None):
    """Four declared timing episodes; these are not training or policy validation."""
    from .worker import evaluate_job

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    jobs = [{"protocol_path": str(protocol.source_path), "controller": controller_spec,
             "world_seed": seed, "purpose": "pilot", "output_dir": str(output / str(seed)),
             "scenario_options": {"calibration_artifact": str(calibration_artifact),
                                  "calibration_data_path": str(calibration_data_path) if calibration_data_path else None}}
            for seed in protocol.definition["source"]["pilot_worlds"]]
    if evaluator is None:
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            records = list(executor.map(evaluate_job, jobs))
    else:
        records = [evaluator(job) for job in jobs]
    report = {"kind": "pilot_timing_only", "records": records,
              "first_episode_seconds": records[0]["elapsed_seconds"],
              "subsequent_episode_seconds": [row["elapsed_seconds"] for row in records[1:]],
              "initialization_seconds": [row["summary"].get("initialization_seconds") for row in records],
              "memory_bytes": [row.get("memory_bytes") for row in records],
              "decision_elapsed_ms": [row.get("decision_elapsed_ms") for row in records],
              "gradient_timing": "separate_synthetic_report_required",
              "training_transitions": 0, "policy_validation": False}
    _write(output / "pilot.json", report)
    return report

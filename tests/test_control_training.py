"""Independent source scheduling, selection and finite-horizon decision oracles."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from cemas.control.protocol import load_protocol, source_grid
from cemas.control.training import (TrainingEpisodePlan, budget_extension, evaluate_source,
    horizon_report, select_checkpoint, threshold_candidates, training_budget,
    tune_threshold, world_holdout_report)


@pytest.fixture
def protocol():
    return load_protocol(Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json")


def record(world, cost=1., activity=.1, *, seed=None, active=0, recent=0):
    result = {"world_seed": world, "last_window_infections": recent,
              "summary": {"status": "completed", "positive_cost": cost,
                          "population": 12000, "execution_days": 112,
                          "private_metrics": {"terminal_active_infections": active},
                          "reward_breakdown": {"normalized": [0., 0., 0., 0., activity]}}}
    if seed is not None:
        result["train_seed"] = seed
    return result


def report(records):
    return {"records": records, "mean_positive_cost": sum(row["summary"]["positive_cost"] for row in records)/len(records)}


def test_episode_plan_is_reproducible_without_replacement_and_global_rng_independent(protocol):
    first = TrainingEpisodePlan(protocol, 11, "e0.json")
    second = TrainingEpisodePlan(protocol, 11, "e0.json")
    rows = []
    for _ in range(100):
        row = first()
        np.random.random(13)
        assert row == second()
        rows.append(row)
    assert len({row["world_seed"] for row in rows}) == 100
    assert all(1000000 <= row["world_seed"] < 1100000 for row in rows)
    assert all(.85 <= row["scenario_options"]["beta_scale"] <= 1.15 for row in rows)
    assert all(row["scenario_options"]["screening_capacity_ratio"] in (.02, .05, .1) for row in rows)
    with pytest.raises(ValueError, match="before use"):
        first(seed=11)
    with pytest.raises(ValueError, match="three protocol"):
        TrainingEpisodePlan(protocol, 50001, "e0.json")


def test_threshold_candidates_use_exact_prescribed_rng_order(protocol):
    rng = np.random.default_rng(82001)
    scales = np.exp(rng.uniform(np.log(.5), np.log(2), 5))
    rho = float(rng.choice((.5, .75)))
    candidates = threshold_candidates(protocol)
    assert len(candidates) == 32 and candidates == threshold_candidates(protocol)
    assert candidates[0]["scales"] == pytest.approx(scales)
    assert candidates[0]["parameters"]["hysteresis"] == rho
    assert candidates[0]["parameters"]["thresholds"]["S"] == pytest.approx(np.array([.5, 3, 10])*scales[1])


@pytest.mark.parametrize("pool,world,expected", [
    ("validation_A", 20005, (1, .05, 0)),
    ("validation_B", 20103, (.9, .05, 0)),
    ("memory_collection", 30027, (1.12, .1, 2)),
])
def test_single_grid_mapping(protocol, pool, world, expected):
    row = source_grid(protocol, pool, world)
    assert (row["beta_scale"], row["screening_capacity_ratio"], row["replicate"]) == expected


def test_source_evaluation_rejects_forbidden_pool_before_creating_output(protocol, tmp_path):
    with pytest.raises(ValueError, match="validation A or B"):
        evaluate_source(protocol, {"method": "minimum"}, tmp_path / "bad", "e0", pool="E1_E2")
    assert not (tmp_path / "bad").exists()


def test_threshold_screening_is_32_A_4_B_and_fixture_artifact_is_marked(protocol, tmp_path):
    calibration = tmp_path / "e0.json"
    calibration.write_text(json.dumps({"sha256": "a"*64}), encoding="utf-8")
    seen = []
    def evaluator(job):
        seen.append(job)
        return record(job["world_seed"], job["controller"]["parameters"]["thresholds"]["T"][0])
    result = tune_threshold(protocol, tmp_path / "tuned", calibration, evaluator=evaluator)
    assert len(seen) == result["selection"]["validation_episode_count"] == 360
    assert sum(job["world_seed"] < 20100 for job in seen) == 288
    candidates = threshold_candidates(protocol)
    expected = min(candidates, key=lambda row: (row["parameters"]["thresholds"]["T"][0], row["candidate_id"]))
    assert result["selection"]["selected_candidate_id"] == expected["candidate_id"]
    artifact = json.loads(Path(result["artifact"]).read_text(encoding="utf-8"))
    assert artifact["selection"]["purpose"] == "fixture"


def test_budget_boundary_and_ceiling_use_latest_two_A_means(protocol):
    decision = budget_extension(protocol, [100., 1., .98], 8192)
    assert decision["next_budget"] == 16384
    assert budget_extension(protocol, [1., .981], 8192)["next_budget"] == 8192
    final = budget_extension(protocol, [1., .9], 32768)
    assert final["next_budget"] == 32768 and final["improving_at_ceiling"]


def test_checkpoint_selection_retains_seed_and_uses_B_only_for_A_finalists(protocol):
    checkpoints = [{"train_seed": 22, "step": step, "artifact": str(step),
                    "validation_A": {"mean_positive_cost": cost}}
                   for step, cost in ((2048, 2.), (4096, 1.), (6144, 1.))]
    seen = []
    def evaluate(row):
        seen.append(row["step"])
        return report([record(world) for world in range(20101, 20119)])
    choice = select_checkpoint(protocol, checkpoints, evaluate)
    assert seen == [4096, 6144]
    assert choice["train_seed"] == 22 and choice["selected"]["step"] == 4096
    checkpoints[-1]["train_seed"] = 11
    with pytest.raises(ValueError, match="exactly one"):
        select_checkpoint(protocol, checkpoints, evaluate)


def test_horizon_uses_final_B_models_OR_and_strict_twenty_percent(protocol):
    records = {}
    for method in protocol.definition["controllers"]["methods"]:
        seeds = (11, 22, 33) if method in ("maskable_ppo", "double_dqn") else (None,)
        records[method] = [record(world, seed=seed) for seed in seeds for world in range(20101, 20119)]
    for row in records["maskable_ppo"][:10]:
        row["last_window_infections"] = 25  # 24 is the strict threshold.
    assert not horizon_report(protocol, records)["requires_extension"]
    records["maskable_ppo"][10]["summary"]["private_metrics"]["terminal_active_infections"] = 61
    result = horizon_report(protocol, records)
    assert result["requires_extension"] and result["next_horizon"] == 140
    assert result["methods"]["maskable_ppo"]["episodes"] == 54
    assert result["methods"]["maskable_ppo"]["affected"] == 11
    records["maskable_ppo"].pop()
    with pytest.raises(ValueError, match="exactly once"):
        horizon_report(protocol, records)


def test_private_budget_counts_partial_failure_and_initialized_unstepped_world(tmp_path):
    events = [{"event": "initializing", "world_seed": 1, "scenario_options": {}},
              {"event": "initialized", "world_seed": 1},
              {"event": "transition", "world_seed": 1, "elapsed_days": 7},
              {"event": "failed", "world_seed": 1, "elapsed_days": 9},
              {"event": "initializing", "world_seed": 2, "scenario_options": {}},
              {"event": "initialized", "world_seed": 2},
              {"event": "closed", "world_seed": 2, "elapsed_days": 0}]
    path = tmp_path / "worlds.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in events), encoding="utf-8")
    result = training_budget(path)
    assert result["transitions"] == 1 and result["simulated_days"] == 9
    assert result["initialized_unstepped_worlds"] == [2]
    assert result["worlds"][0]["failed"]


def test_world_holdout_excludes_all_policies_and_revisions_with_real_retriever():
    from cemas.control.memory_types import CASE_SCHEMA_VERSION, PublicCase, public_hash
    from cemas.control.types import (ActionVector, PublicCost, PublicObservation,
                                     PublicPopulation, PublicResources, PublicWeeklyRecord)
    resources = PublicResources(2, 5, 1)
    action = ActionVector((0, 0, 0, 0, 0))
    week = PublicWeeklyRecord(0, 6, 1, PublicCost(clinical_tests=7), action, resources)
    observation = PublicObservation(7, 112, 1, PublicPopulation(100, (10, 20, 20, 40, 10), 20, 40),
        resources, action, (7,)*5, (True,)*324, (PublicWeeklyRecord(),)*3+(week,), (False,)*3+(True,))
    following = PublicWeeklyRecord(7, 13, 2, PublicCost(clinical_tests=7), action, resources)
    cases = tuple(PublicCase(identity, 1, CASE_SCHEMA_VERSION, "a"*64, observation, following,
        7, None, "closed_one", 13, "descriptive_not_causal", ("truncated_followup",), "Public example.",
        {"kind": "source_simulation", "observation_sha256": public_hash(observation),
         "feedback_sha256": public_hash(following), "followup_sha256": None}) for identity in range(1, 5))
    inspected = []
    def group(identity):
        inspected.append(identity)
        return str(identity)
    store = SimpleNamespace(cases=lambda: cases, group_for=group, purpose="fixture",
                            store_sha256="b"*64, public_task_sha256="a"*64)
    result = world_holdout_report(store, {1: 1, 2: 1, 3: 2, 4: 2})
    assert result["purpose"] == "fixture" and not result["control_effectiveness_experiment"]
    assert len(result["worlds"]) == 2
    assert all(row["queries"] == 2 and row["statuses"] == {"ok": 2} for row in result["worlds"])
    assert all(row["retrieved_items"] <= 4 for row in result["worlds"])
    assert inspected == [3, 4, 3, 4, 1, 2, 1, 2]


def test_cli_help_is_inert_and_dependency_lazy():
    from examples.control_v1.baselines import main
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0


def test_training_orchestration_keeps_all_seeds_and_saves_after_updates(protocol, tmp_path, monkeypatch):
    import sys
    import cemas.control.artifacts as artifacts
    import cemas.control.training as training
    import cemas.control.rl.ppo as ppo

    learners, saved, evaluations = {}, {}, []
    class Env:
        def __init__(self, factories, *, start_method):
            assert len(factories) == 1 and start_method == "spawn"
            self.seed = factories[0].train_seed
        def close(self):
            pass
    class Learner:
        def __init__(self, seed):
            self.seed, self.num_timesteps = seed, 0
        def learn(self, *, total_timesteps, reset_num_timesteps):
            assert total_timesteps == 2048 and reset_num_timesteps is False
            self.num_timesteps += total_timesteps
        def save(self, path):
            # A checkpoint must reflect the completed update, not its pre-update state.
            assert self.num_timesteps in (2048, 4096, 6144, 8192)
            Path(path).write_text(str(self.num_timesteps), encoding="utf-8")
    def build(env, config, seed):
        learner = Learner(seed)
        learners[seed] = learner
        return learner
    def save(output, protocol, method, **kwargs):
        path = str(Path(output) / "artifact.json")
        saved[path] = kwargs
        return Path(path)
    def get(path, protocol):
        return {**saved[path], "weights_path": str(saved[path]["weights_path"])}
    def evaluate(protocol, spec, output, calibration, *, pool="validation_A", **kwargs):
        evaluations.append((spec["artifact"], pool))
        step = int(Path(saved[spec["artifact"]]["weights_path"]).read_text(encoding="utf-8"))
        worlds = range(20001, 20010) if pool == "validation_A" else range(20101, 20119)
        # Flat final two A checkpoints prevent an extension; B picks the earlier tie.
        cost = 2. if step == 2048 else 1.
        return report([record(world, cost) for world in worlds])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(manual_seed=lambda seed: None))
    monkeypatch.setitem(sys.modules, "stable_baselines3.common.vec_env", SimpleNamespace(SubprocVecEnv=Env))
    monkeypatch.setattr(training, "LearnerRNGState", SimpleNamespace(capture=lambda: SimpleNamespace(restore=lambda: None)))
    monkeypatch.setattr(training, "training_budget", lambda path: {"transitions": 0, "worlds": [], "plan_identity": str(path)})
    monkeypatch.setattr(training, "evaluate_source", evaluate)
    monkeypatch.setattr(ppo, "build_ppo", build)
    monkeypatch.setattr(artifacts, "save_baseline_artifact", save)
    monkeypatch.setattr(artifacts, "get_baseline_artifact", get)
    result = training.train_controller(protocol, "ppo", tmp_path / "training", "e0", maximum_budget=8192,
                                       evaluator=lambda job: None)
    assert [row["train_seed"] for row in result["selected_models"]] == [11, 22, 33]
    assert [row["selected"]["step"] for row in result["selected_models"]] == [4096]*3
    assert len(evaluations) == 18  # Twelve A checkpoints and six B candidates.
    for row in result["selected_models"]:
        assert "episode_plan" in saved[row["artifact"]]["training"]
    assert result["purpose"] == "fixture"


def test_worker_reuses_runner_and_preserves_threshold_and_missing_usage_evidence(protocol, tmp_path, monkeypatch):
    import cemas.control.runner as runner
    from cemas.control.controllers import _BASELINE_METADATA
    from cemas.control.worker import evaluate_job

    output = tmp_path / "attempt"
    output.mkdir()
    (output / "private_daily.csv").write_text("new_infections\n" + "1\n"*16, encoding="utf-8")
    calls = [{"elapsed_ms": 2., "response": {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}},
             {"elapsed_ms": 1., "response": None}]
    (output / "llm_calls.jsonl").write_text("\n".join(json.dumps(row) for row in calls), encoding="utf-8")
    parameters = threshold_candidates(protocol)[0]["parameters"]
    def run(protocol, controller, output_dir, world_seed, **kwargs):
        assert kwargs["mode"] == "evaluation" and kwargs["purpose"] == "scientific"
        assert _BASELINE_METADATA[controller]["parameters"] == parameters
        return SimpleNamespace(summary=record(world_seed)["summary"], output_dir=output)
    monkeypatch.setattr(runner, "run_episode", run)
    result = evaluate_job({"protocol_path": str(protocol.source_path),
        "controller": {"method": "threshold", "parameters": parameters},
        "output_dir": str(output), "world_seed": 20001, "scenario_options": {}})
    assert result["last_window_infections"] == 14
    assert result["llm_usage"]["total_tokens"] == 7
    assert result["llm_usage"]["usage_missing_attempts"] == 1
    assert result["llm_usage"]["provider_fee"] is None


def test_holdout_cli_uses_real_frozen_manifest_filename(tmp_path, monkeypatch):
    from examples.control_v1.baselines import main
    import cemas.control.memory_store as stores
    import cemas.control.training as training

    opened = []
    class Store:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def open_store(database, manifest):
        opened.append((database.name, manifest.name))
        return Store()
    monkeypatch.setattr(stores.FrozenPublicCaseStore, "open", open_store)
    monkeypatch.setattr(stores, "verify_source_manifest", lambda *args, **kwargs:
                        {"trajectories": [{"seed": 30001, "case_ids": [1]}]})
    monkeypatch.setattr(training, "world_holdout_report", lambda store, worlds: {"worlds": worlds})
    assert main(["holdout", "--development-dir", str(tmp_path),
                 "--output", str(tmp_path / "holdout.json")]) == 0
    assert opened == [(stores.DATABASE_FILENAME, "store_manifest.json")]

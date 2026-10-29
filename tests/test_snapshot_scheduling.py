"""Scheduling and diagnostics checks using fixtures instead of formal experiments."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from cemas.control.snapshot_protocol import load_training_protocol, snapshot_scenarios
from cemas.control import snapshots, training


@pytest.fixture
def protocol():
    return load_training_protocol(Path(__file__).resolve().parents[1] / "docs/baseline_snapshot_training_v1.json")


def capture_fixture(job):
    """Spawn-safe stand-in: writes tiny fixture files, never invokes the simulator."""
    output = Path(job["output"])
    paths, entries = [], {}
    for day in job["days"]:
        path = output / f"{job['history_seed']}-{day}.json"
        path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        path.with_suffix(".pkl").write_bytes(b"fixture")
        paths.append(str(path))
        entries[path.name] = {"history_seed": job["history_seed"], "snapshot_day": day,
                              "split": job["split"], "state_sha256": "fixture"}
    return paths, entries


def test_spawn_snapshot_parent_merges_preserves_existing_and_rejects_overwrite(protocol, tmp_path, monkeypatch):
    from cemas.e0 import artifacts

    monkeypatch.setattr(artifacts, "load_calibration_artifact",
                        lambda *args: SimpleNamespace(beta=.038, sha256="fixture"))
    monkeypatch.setattr(snapshots, "snapshot_identity", lambda *args: {"schema": "fixture"})
    monkeypatch.setattr(snapshots, "_capture_snapshot_job", capture_fixture)
    writes = []
    original_write = snapshots._write_snapshot_catalog

    def write(path, catalog):
        writes.append(os.getpid())
        original_write(path, catalog)

    monkeypatch.setattr(snapshots, "_write_snapshot_catalog", write)
    catalog_path = tmp_path / "snapshots_manifest.json"
    old = {"identity": {"schema": "fixture"}, "snapshots": {"old.json": {"state_sha256": "old"}}}
    catalog_path.write_text(json.dumps(old), encoding="utf-8")
    paths = snapshots.generate_snapshot_library(protocol, "fixture", tmp_path, "val",
        [20101, 20102], days=[21, 35], workers=2)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(paths) == 4 and len(catalog["snapshots"]) == 5
    assert catalog["snapshots"]["old.json"] == old["snapshots"]["old.json"]
    assert all(json.loads(Path(path).read_text())["pid"] != os.getpid() for path in paths)
    assert writes == [os.getpid(), os.getpid()]
    assert not (tmp_path / "snapshots_manifest.lock").exists()
    before = catalog_path.read_bytes()
    with pytest.raises(FileExistsError):
        snapshots.generate_snapshot_library(protocol, "fixture", tmp_path, "val", [20101], days=[21], workers=2)
    assert catalog_path.read_bytes() == before
    (tmp_path / "snapshots_manifest.lock").write_text("owned by another command")
    with pytest.raises(FileExistsError):
        snapshots.generate_snapshot_library(protocol, "fixture", tmp_path, "val", [20103], days=[21], workers=2)
    assert (tmp_path / "snapshots_manifest.lock").read_text() == "owned by another command"


def test_worker_failure_preserves_completed_manifest_and_releases_lock(protocol, tmp_path, monkeypatch):
    from cemas.e0 import artifacts

    monkeypatch.setattr(artifacts, "load_calibration_artifact",
                        lambda *args: SimpleNamespace(beta=.038, sha256="fixture"))
    monkeypatch.setattr(snapshots, "snapshot_identity", lambda *args: {"schema": "fixture"})

    def capture(p, output, seed, split, days, beta):
        if seed == 20102:
            raise RuntimeError("fixture failure")
        return capture_fixture({"output": str(output), "history_seed": seed, "split": split, "days": days})

    monkeypatch.setattr(snapshots, "_capture_history_snapshots", capture)
    with pytest.raises(RuntimeError, match="fixture failure"):
        snapshots.generate_snapshot_library(protocol, "fixture", tmp_path, "val", [20101, 20102], days=[21])
    catalog = json.loads((tmp_path / "snapshots_manifest.json").read_text())
    assert set(catalog["snapshots"]) == {"20101-21.json"}
    assert not (tmp_path / "snapshots_manifest.lock").exists()


def test_evaluation_and_pilot_worker_counts_keep_scenario_order(protocol, tmp_path, monkeypatch):
    from cemas.control import worker

    sizes, seen = [], []

    class Pool:
        def __init__(self, *, max_workers, mp_context):
            sizes.append(max_workers)
            assert mp_context.get_start_method() == "spawn"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def map(self, function, jobs):
            return map(function, jobs)

    def evaluate(job):
        seen.append(job)
        return {"world_seed": job["world_seed"], **({"scenario_id": job["scenario_id"]} if "scenario_id" in job else {}),
                "elapsed_seconds": 1., "summary": {"status": "completed", "positive_cost": 1.,
                    "reward_breakdown": {"normalized": [0.] * 5}}}

    monkeypatch.setattr(training, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(worker, "evaluate_job", evaluate)
    result = training.evaluate_source(protocol, {"method": "minimum"}, tmp_path / "val", "fixture", workers=3)
    assert [r["scenario_id"] for r in result["records"]] == [r["scenario_id"] for r in snapshot_scenarios(protocol, "val")]
    training.run_pilot(protocol, {"method": "maximum_feasible"}, tmp_path / "pilot", "fixture", workers=2)
    assert sizes == [3, 2] and len(seen) == 40
    assert all(job.get("purpose") != "snapshot_test" for job in seen)
    with pytest.raises(ValueError, match="positive integer"):
        training.evaluate_source(protocol, {}, tmp_path / "invalid", "fixture", workers=0)
    assert not (tmp_path / "invalid").exists()


def test_threshold_workers_cover_32_candidates_on_val_only(protocol, tmp_path, monkeypatch):
    from cemas.control import artifacts

    calls = []

    def evaluate(p, spec, output, anchor, **kwargs):
        calls.append(kwargs)
        return {"mean_positive_cost": 1., "mean_normalized_activity": 0., "records": [None] * 36}

    monkeypatch.setattr(training, "evaluate_source", evaluate)
    monkeypatch.setattr(artifacts, "save_baseline_artifact", lambda *args, **kwargs: "fixture")
    result = training.tune_threshold(protocol, tmp_path / "threshold", "fixture", workers=3)
    assert len(calls) == 32 and all(call["workers"] == 3 for call in calls)
    assert all("pool" not in call for call in calls)
    assert result["selection"]["validation_episode_count"] == 1152
    assert result["selection"]["selected_candidate_id"] == 0


@pytest.mark.parametrize("command", ["snapshots", "pilot", "evaluate", "tune", "train"])
def test_cli_passes_workers_and_independent_seed(protocol, tmp_path, monkeypatch, command):
    from examples.control_v1.baselines import main
    from cemas.e0 import artifacts

    calls = []
    monkeypatch.setattr(artifacts, "load_calibration_artifact", lambda *args, **kwargs: None)

    def run(*args, **kwargs):
        calls.append(kwargs)
        return []

    argv = ["--protocol", str(protocol.source_path), command, "--artifact", "fixture", "--workers", "2"]
    if command == "snapshots":
        monkeypatch.setattr(snapshots, "generate_snapshot_library", run)
        argv += ["--output", protocol.definition["snapshot_training"]["library"], "--split", "train"]
    else:
        function = {"pilot": "run_pilot", "evaluate": "evaluate_source", "tune": "tune_threshold",
                    "train": "train_controller"}[command]
        monkeypatch.setattr(training, function, run)
        argv += ["--output", str(tmp_path / command)]
        if command in ("pilot", "evaluate"):
            argv += ["--reference", "minimum"]
        if command == "train":
            argv += ["--method", "ppo", "--train-seed", "22", "--maximum-budget", "8192"]
    assert main(argv) == 0
    assert calls[0]["workers"] == 2
    if command == "train":
        assert calls[0]["train_seed"] == 22 and calls[0]["maximum_budget"] == 8192


@pytest.mark.parametrize("method", ["ppo", "ddqn"])
def test_checkpoint_diagnostics_current_network_maximum_and_rng(method):
    class Values:
        def predict_values(self, observations):
            return observations[:, :1] * -2

    observations = np.zeros((2050, 197), dtype=np.float32)
    observations[-1, 0] = 7
    learner = SimpleNamespace(device="cpu", policy=Values(),
        rollout_buffer=SimpleNamespace(observations=observations.reshape(2050, 1, 197)),
        replay=SimpleNamespace(observations=observations, size=2050),
        online=lambda batch: torch.cat((batch[:, :1], batch[:, :1] * -3), dim=1))
    rng = torch.get_rng_state().clone()
    result = training._checkpoint_diagnostics(learner, method)
    assert result["sample_count"] == 2050
    assert result["max_abs_value" if method == "ppo" else "max_abs_q"] == (14 if method == "ppo" else 21)
    assert torch.equal(rng, torch.get_rng_state())
    observations[-1, 0] = np.inf
    with pytest.raises(FloatingPointError):
        training._checkpoint_diagnostics(learner, method)


@pytest.mark.parametrize("method", ["ppo", "ddqn"])
def test_independent_seed_checkpoints_fixed_budget_and_logs(protocol, tmp_path, monkeypatch, method):
    import stable_baselines3.common.vec_env as vec
    from cemas.control import artifacts
    from cemas.control.rl import ppo, ddqn

    seeds, saved, calls = [], {}, []

    class Env:
        def __init__(self, factories, *, start_method):
            assert start_method == "spawn"
            seeds.append(factories[0].train_seed)
        def close(self):
            pass

    class Learner:
        def __init__(self, *args, **kwargs):
            self.num_timesteps = 0
        def learn(self, *, total_timesteps, reset_num_timesteps):
            self.num_timesteps += total_timesteps
        def train(self, steps):
            self.num_timesteps += steps
        def save(self, path):
            Path(path).write_text(str(self.num_timesteps))

    def save(output, p, name, **kwargs):
        path = Path(output) / "artifact.json"
        saved[str(path)] = kwargs
        return path

    def evaluate(p, spec, output, anchor, **kwargs):
        calls.append(kwargs)
        return {"mean_positive_cost": 1.}

    monkeypatch.setattr(vec, "SubprocVecEnv", Env)
    monkeypatch.setattr(ppo, "build_ppo", lambda *args: Learner())
    monkeypatch.setattr(ddqn, "DDQNTrainer", Learner)
    monkeypatch.setattr(training, "_checkpoint_diagnostics", lambda learner, name:
                        {"sample_count": 1, "max_abs_value" if name == "ppo" else "max_abs_q": 2.})
    monkeypatch.setattr(training, "training_budget", lambda path: {"step_count": 8192})
    monkeypatch.setattr(training, "evaluate_source", evaluate)
    monkeypatch.setattr(artifacts, "save_baseline_artifact", save)
    monkeypatch.setattr(artifacts, "get_baseline_artifact", lambda path, p: saved[str(path)])
    output = tmp_path / method
    report = training.train_controller(protocol, method, output, "fixture", train_seed=22, workers=2)
    assert seeds == [22] and report["train_seeds"] == [22]
    assert report["available_budget_ceiling"] == 8192 and len(calls) == 4
    assert all(call["workers"] == 2 for call in calls)
    assert report["selected_models"][0]["selected"]["step"] == 2048
    logs = [json.loads(line) for line in (output / "checkpoint_diagnostics.jsonl").read_text().splitlines()]
    assert [row["step"] for row in logs] == [2048, 4096, 6144, 8192]
    assert all(row["train_seed"] == 22 for row in logs)
    for row in logs:
        assert json.loads((output / f"seed-22/step-{row['step']}/diagnostics.json").read_text()) == row
    with pytest.raises(ValueError, match="extension requires joint validation"):
        training.train_controller(protocol, method, tmp_path / "extended", "fixture", train_seed=22, maximum_budget=16384)
    assert not (tmp_path / "extended").exists()

"""Reproduce full-population E0/replay W1 and individual-role compatibility."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np
import psutil


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cemas.control.protocol import load_protocol
from cemas.e0.artifacts import load_calibration_artifact
from cemas.e0.data import load_e0_config, load_e0_data
from cemas.e0.simulation import run_e0_world
from cemas.replay.simulation import population_assignment_hash, run_replay_world


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _capture_world(runner, *args, **kwargs):
    """Capture fixed role arrays without changing initialization or its RNG."""
    import covasim as cv

    original = cv.Sim
    instances = []

    def capture(*sim_args, **sim_kwargs):
        sim = original(*sim_args, **sim_kwargs)
        instances.append(sim)
        return sim

    cv.Sim = capture
    try:
        world = runner(*args, **kwargs)
        people = instances[0].people
        arrays = {"student_level": np.asarray(people.student_level).copy(),
                  **{key: np.asarray(people.campus_registry_metadata[key]).copy()
                     for key in ("student_indices", "teacher_indices", "staff_indices")}}
        return world, arrays, population_assignment_hash(people)
    finally:
        cv.Sim = original


def _measured_world(runner, *args, **kwargs):
    process = psutil.Process()
    stopped = threading.Event()
    samples = [process.memory_info().rss]

    def sample():
        while not stopped.wait(.05):
            samples.append(process.memory_info().rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    started = time.perf_counter()
    try:
        result = _capture_world(runner, *args, **kwargs)
    finally:
        stopped.set()
        monitor.join()
    memory = process.memory_info()
    metrics = {"elapsed_seconds": time.perf_counter() - started,
               "rss_sample_interval_seconds": .05,
               "sampled_peak_rss_bytes": max(samples + [memory.rss]),
               "rss_after_world_bytes": memory.rss,
               "process_lifetime_peak_rss_bytes": getattr(memory, "peak_wset", None)}
    return result, metrics


def verify(anchor_path, config_path, data_path, provenance_path, seed):
    config = load_e0_config(config_path)
    protocol = load_protocol(config["base_protocol_path"])
    anchor = load_calibration_artifact(anchor_path, protocol)
    w1 = load_e0_data(config)
    full_config = dict(config, window={"start": "2020-08-17", "end": "2020-10-30"},
                       window_days=75, data_path=str(data_path.resolve()),
                       provenance_path=str(provenance_path.resolve()))
    data = load_e0_data(full_config)
    evidence_path = anchor_path.parent / "worlds_evaluation.jsonl"
    evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    baseline_records = [record for record in evidence if record["case"] == "main"
                        and record["seed"] == seed and record["beta"] == anchor.beta]
    if len(baseline_records) != 1:
        raise ValueError("Exactly one original selected-main evaluation world is required for this seed")
    recorded = baseline_records[0]["world"]
    before_available = psutil.virtual_memory().available
    (original, original_arrays, original_assignment), original_measurement = _measured_world(
        run_e0_world, config, w1, anchor.beta, seed)
    gc.collect()
    (replay, replay_arrays, replay_assignment), replay_measurement = _measured_world(
        run_replay_world, config, data, anchor.beta, seed, w1_data=w1)
    checks = {}
    arrays = {}
    for name, values in original_arrays.items():
        same = bool(np.array_equal(values, replay_arrays[name]))
        arrays[name] = {"length": len(values), "elementwise_equal": same,
                       "original_sha256": hashlib.sha256(np.asarray(values, dtype="<i8").tobytes()).hexdigest(),
                       "replay_sha256": hashlib.sha256(np.asarray(replay_arrays[name], dtype="<i8").tobytes()).hexdigest()}
        checks[f"individual_{name}"] = same
    for group in ("students", "employees"):
        for field in ("positive", "tests"):
            checks[f"daily_{group}_{field}"] = (
                original["groups"][group][field] == recorded["groups"][group][field]
                == replay["groups"][group][field][:21])
    for field in ("roles", "group_test_weights"):
        checks[field] = original[field] == recorded[field] == replay[field]
    checks["daily_requested_tests"] = (original["requested_tests"] == recorded["requested_tests"]
                                        == replay["requested_tests"][:21])
    checks["individual_assignment_sha256"] = (original_assignment == replay_assignment
                                               == replay["replay"]["population_assignment_sha256"])
    checks["dorm_topology_unchanged"] = (replay["replay"]["dorm_topology_initial_sha256"]
                                        == replay["replay"]["dorm_topology_final_sha256"])
    checks["dorm_weights_restored"] = replay["replay"]["dorm_weights_restored"]
    if not all(checks.values()):
        raise ValueError(f"Replay regression failed: {[key for key, passed in checks.items() if not passed]}")
    return {"schema_version": "cemas-uw2020-replay-role-regression-v1", "status": "passed",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": seed, "beta": anchor.beta, "population": replay["population"],
            "anchor_path": str(anchor_path.resolve()), "anchor_file_sha256": _sha256(anchor_path),
            "anchor_payload_sha256": anchor.sha256,
            "e0_evaluation_file_sha256": _sha256(evidence_path),
            "e0_config_sha256": config["config_sha256"],
            "w1_data_sha256": w1["sha256"], "replay_data_sha256": data["sha256"],
            "source_sha256": {path: _sha256(ROOT / path) for path in
                              ("tools/verify_uw_replay.py", "cemas/replay/simulation.py")},
            "checks": checks, "individual_role_arrays": arrays,
            "original_assignment_sha256": original_assignment,
            "replay_assignment_sha256": replay_assignment, "replay_audit": replay["replay"],
            "memory": {"system_available_before_bytes": before_available,
                       "original_e0": original_measurement, "replay75": replay_measurement,
                       "eight_worker_sampled_peak_estimate_bytes":
                           8 * replay_measurement["sampled_peak_rss_bytes"],
                       "estimate_note": "Per-process measured RSS multiplied by eight; excludes parent and concurrent host workloads."},
            "reproduce": f'"{sys.executable}" tools/verify_uw_replay.py --seed {seed}'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, default=ROOT / "results/e0_v3/teacher2321_k3/full/control_anchor.json")
    parser.add_argument("--config", type=Path, default=ROOT / "docs/e0_protocol_v2.json")
    parser.add_argument("--data", type=Path, default=ROOT / "data/uw_madison_2020_replay.csv")
    parser.add_argument("--provenance", type=Path, default=ROOT / "data/uw_madison_2020_replay.provenance.json")
    parser.add_argument("--seed", type=int, default=12201)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results/uw2020_replay_v2_acceptance/role_regression.json")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    report = verify(args.anchor, args.config, args.data, args.provenance, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "memory": report["memory"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Spawn entry points; simulator and learner state never cross this boundary."""

from dataclasses import dataclass
from pathlib import Path
import csv
import json
from time import perf_counter


@dataclass(frozen=True)
class TrainingEnvFactory:
    protocol_path: str
    train_seed: int
    calibration_artifact: str
    private_record_path: str
    calibration_data_path: str | None = None

    def __call__(self):
        from .environment import WeeklyControlEnvironment
        from .snapshot_protocol import load_training_protocol as load_protocol
        from .rl.env import GymControlEnv
        from .training import TrainingEpisodePlan

        protocol = load_protocol(self.protocol_path)
        plan = TrainingEpisodePlan(protocol, self.train_seed, self.calibration_artifact,
                                   calibration_data_path=self.calibration_data_path)
        path = Path(self.private_record_path)

        def record(event):
            # A separate file is private runner evidence, never VecEnv info.
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

        return GymControlEnv(WeeklyControlEnvironment(protocol, mode="training", purpose="scientific"),
                             plan, reference_population=protocol.population,
                             reference_horizon=protocol.execution_days, private_record_sink=record)


def evaluate_job(job):
    """Evaluate one declared source identity using the existing complete runner."""
    from .controllers import (MinimumController, MaximumFeasibleController,
                              ThresholdController, load_baseline_controller)
    from .logging import resolved_snapshot
    from .snapshot_protocol import load_training_protocol as load_protocol
    from .runner import make_memory_llm_controller, run_episode
    from .timing import observation_days

    protocol = load_protocol(job["protocol_path"])
    spec = job["controller"]
    method = spec["method"]
    if method == "minimum":
        controller = MinimumController()
    elif method == "maximum_feasible":
        controller = MaximumFeasibleController()
    elif method == "threshold":
        controller = ThresholdController(**spec["parameters"])
        from .controllers import _BASELINE_METADATA
        _BASELINE_METADATA[controller] = {"method": "threshold", "parameters": spec["parameters"]}
    elif method in ("ppo", "ddqn", "baseline"):
        controller, _ = load_baseline_controller(protocol, spec["artifact"])
    elif method == "llm":
        settings = dict(spec["settings"])
        library = settings.pop("learning_store_path", None)
        if library is not None:
            from .learning_store import LearningMemoryStore
            settings["learning_store"] = LearningMemoryStore(library, readonly=True)
        try:
            controller = make_memory_llm_controller(protocol, **settings)
        except BaseException:
            if library is not None:
                settings["learning_store"].close()
            raise
    else:
        raise ValueError("unsupported source evaluation method")
    started = perf_counter()
    try:
        result = run_episode(protocol, controller, job["output_dir"], job["world_seed"],
                             purpose=job.get("purpose", "scientific"), mode="evaluation",
                             scenario_options=job["scenario_options"])
    finally:
        store = getattr(controller, "store", None)
        if store is not None:
            store.close()
    summary = resolved_snapshot(result.summary)
    private_path = result.output_dir / "private_daily.csv"
    with private_path.open(encoding="utf-8", newline="") as handle:
        days = list(csv.DictReader(handle))
    width = protocol.definition["horizon_gate"]["last_window_days"]
    usage = {"attempts": 0, "auxiliary_attempts": 0, "total_attempts": 0,
             "elapsed_ms": 0., "prompt_tokens": 0,
             "completion_tokens": 0, "total_tokens": 0, "usage_missing_attempts": 0,
             "provider_fee": None, "fee_status": "not_supplied"}
    for filename in ("llm_calls.jsonl", "feedback_events.jsonl"):
        calls = result.output_dir / filename
        if not calls.exists():
            continue
        for line in calls.read_text(encoding="utf-8").splitlines():
            call = json.loads(line)
            if filename == "feedback_events.jsonl" and call.get("event") != "provider_call":
                continue
            usage["attempts" if filename == "llm_calls.jsonl" else "auxiliary_attempts"] += 1
            usage["total_attempts"] += 1
            usage["elapsed_ms"] += call["elapsed_ms"]
            reported = (call.get("response") or {}).get("usage", {})
            if any(name not in reported for name in ("prompt_tokens", "completion_tokens", "total_tokens")):
                usage["usage_missing_attempts"] += 1
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[name] += reported.get(name, 0) or 0
    timing = {}
    if job.get("purpose") == "pilot":
        import psutil

        memory = psutil.Process().memory_info()
        timing["memory_bytes"] = {"resident": memory.rss,
                                  "process_peak_resident": getattr(memory, "peak_wset", None)}
        decisions = [json.loads(line) for line in
                     (result.output_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        timing["decision_elapsed_ms"] = [row["elapsed_ms"] for row in decisions
                                         if row["decision_source"] == "controller"]
    from .controllers import _BASELINE_METADATA
    baseline = _BASELINE_METADATA.get(controller, {})
    return {"world_seed": job["world_seed"], "summary": summary, **timing,
            **({"method": controller.controller_type,
                "train_seed": (baseline.get("training") or {}).get("train_seed"),
                "snapshot_active_infections": json.loads((result.output_dir / "manifest.json").read_text(
                    encoding="utf-8"))["snapshot_active_infections"]}
               if "snapshot_training" in protocol.definition else {}),
            **({"scenario_id": job["scenario_id"], "snapshot_day": job["snapshot_day"]}
               if "scenario_id" in job else {}),
            **({"day112_active_infections": int(days[observation_days(protocol) + 111]["active_infections"])}
               if "snapshot_training" in protocol.definition and len(days) >= observation_days(protocol) + 112 else {}),
            "last_window_infections": sum(int(row["new_infections"]) for row in days[-width:]),
            "elapsed_seconds": perf_counter() - started, "llm_usage": usage,
            "output_dir": str(result.output_dir)}

"""Sequential experience learning; completed episodes are the only resume cursor."""

import json
from pathlib import Path
from uuid import uuid4

from .learning_store import LearningMemoryStore
from .logging import resolved_snapshot, snapshot_sha256
from .memory import public_task_hash
from .runner import make_public_prompt_config, make_memory_llm_controller, run_episode
from .snapshot_protocol import history_seeds


def train_memory(protocol, episodes, library, output_dir, settings, calibration_artifact, *,
                 calibration_data_path=None, controller_factory=make_memory_llm_controller, run=run_episode):
    """Append, reorder or repeat explicit scenarios without locking model configuration."""
    if "snapshot_training" not in protocol.definition:
        raise ValueError("experience learning requires the snapshot task")
    allowed = set(history_seeds(protocol, "train"))
    seen = set()
    prepared = []
    for entry in episodes:
        identity = entry["episode_id"]
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError("training episodes require distinct stable nonempty IDs")
        seen.add(identity)
        if entry["world_seed"] not in allowed:
            raise ValueError("learning episodes must use the snapshot training split")
        options = dict(entry["scenario_options"])
        path = Path(options["snapshot_path"]).resolve()
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot["split"] != "train" or snapshot["history_seed"] != entry["world_seed"]:
            raise ValueError("learning snapshot does not belong to its training world")
        if "execution_days" in options and options["execution_days"] != protocol.execution_days:
            raise ValueError("training control horizon must match the task")
        options["snapshot_path"] = str(path)
        options.update(calibration_artifact=str(calibration_artifact),
                       calibration_data_path=str(calibration_data_path) if calibration_data_path else None)
        scenario = {"snapshot": snapshot, "world_seed": entry["world_seed"],
                    "future_seed": options["future_seed"],
                    "screening_capacity_ratio": options.get("screening_capacity_ratio", protocol.definition["resources"]["screening_main_capacity_ratio"]),
                    "execution_days": protocol.execution_days, "beta_scale": options.get("beta_scale", 1.0)}
        prepared.append((entry, options, snapshot_sha256(scenario)))
    task_hash = public_task_hash(make_public_prompt_config(protocol), protocol.execution_days)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    store = LearningMemoryStore(library, task_hash)
    results = []
    try:
        for entry, options, scenario_hash in prepared:
            if not store.begin_episode(entry["episode_id"], scenario_hash):
                results.append({"episode_id": entry["episode_id"], "status": "already_completed"})
                continue
            attempt = output / (snapshot_sha256(entry["episode_id"])[:12] + "-" + uuid4().hex[:12])
            attempt.mkdir()
            metadata = {"episode_id": entry["episode_id"], "scenario": entry,
                        "settings": settings, "scenario_hash": scenario_hash,
                        "learning_library": str(store.path), "public_task_sha256": task_hash}
            try:
                (attempt / "learning_run.json").write_text(json.dumps(resolved_snapshot(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
                controller = controller_factory(protocol, learning_store=store, **settings)
                result = run(protocol, controller, attempt / "episode", entry["world_seed"],
                             purpose="memory_training", scenario_options=options)
                store.complete_episode(result.output_dir)
                results.append({"episode_id": entry["episode_id"], "status": "completed", "output_dir": str(result.output_dir)})
            except BaseException:
                store.rollback()
                raise
    finally:
        store.close()
    return results

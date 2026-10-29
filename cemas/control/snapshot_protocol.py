"""Load the separate snapshot task without changing the frozen E0 base model."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from .logging import resolved_snapshot, snapshot_sha256
from .protocol import load_protocol, _freeze


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "uw-snapshot-training-v3"


def load_training_protocol(path):
    path = Path(path).resolve()
    settings = json.loads(path.read_text(encoding="utf-8"))
    legacy = settings.get("schema_version") == "uw-snapshot-training-v2"
    if settings.get("schema_version") != SCHEMA and not legacy:
        return load_protocol(path)
    required = {"schema_version", "base_protocol", "library", "snapshot_days",
                "training_worlds", "schedule_seed", "future_seed_root", "test_branches",
                "replay_parameters"}
    required |= {"execution_days"} if legacy else {"observation_days", "control_days"}
    if set(settings) - {"validation_worlds"} != required:
        raise ValueError("snapshot training configuration has missing or unexpected fields")
    base = load_protocol(ROOT / settings["base_protocol"])
    for key in {"training_worlds", "test_branches", "validation_worlds"} & settings.keys():
        if type(settings[key]) is not int or settings[key] < 1:
            raise ValueError(f"snapshot {key} must be a positive integer")
    control = settings["execution_days"] if legacy else settings["control_days"]
    observation = 0 if legacy else settings["observation_days"]
    if type(control) is not int or control != 112:
        raise ValueError("snapshot training uses fixed H=112; extensions belong to frozen evaluation")
    if type(observation) is not int or observation != (0 if legacy else 7):
        raise ValueError("snapshot observation period must be seven days")
    total = observation + control
    days = settings["snapshot_days"]
    if (not isinstance(days, list) or not days or days != sorted(set(days))
            or any(type(d) is not int or not 7 <= d <= 74 or d % 7 for d in days)):
        raise ValueError("snapshot_days must be distinct increasing week boundaries in [7,74]")
    for key in ("schedule_seed", "future_seed_root"):
        if type(settings[key]) is not int or not 0 <= settings[key] < 2**32:
            raise ValueError(f"invalid snapshot {key}")
    if not isinstance(settings["library"], str) or not settings["library"]:
        raise ValueError("snapshot library path is required")
    from ..replay.simulation import HistoricalMeasures
    HistoricalMeasures(**settings["replay_parameters"])
    definition = resolved_snapshot(base.definition)
    definition["snapshot_training"] = settings
    definition["engine"].update(initial_baseline_days=observation, execution_days=total,
                                 n_days=total - 1)
    identity = "uw-snapshot-control-v1" if legacy else "uw-snapshot-control-v2"
    definition["protocol_id"] = identity
    definition["controllers"]["methods"] = ["maskable_ppo", "double_dqn", "tuned_threshold",
                                             "minimum", "maximum_feasible", "llm_full"]
    definition["source"]["budget_ladder"] = [8192, 16384]
    return replace(base, protocol_id=identity, execution_days=total,
                   n_days=total - 1, definition=_freeze(definition),
                   source_path=path, source_sha256=snapshot_sha256({"base": base.source_sha256,
                                                                            "snapshot": settings}))


def history_seeds(protocol, split):
    settings = protocol.definition["snapshot_training"]
    if split == "train":
        bounds = protocol.definition["source"]["source_world_pools"][0]
        rng = np.random.default_rng(settings["schedule_seed"])
        count = settings["training_worlds"]
        if count > bounds["end_exclusive"] - bounds["start_inclusive"]:
            raise ValueError("snapshot world count exceeds reserved training pool")
        return tuple(int(i) for i in rng.choice(np.arange(bounds["start_inclusive"],
            bounds["end_exclusive"]), count, replace=False))
    if split == "pilot":
        return tuple(protocol.definition["source"]["pilot_worlds"])
    key = {"val": "validation_B", "test": "E1_E2"}.get(split)
    if key is None:
        raise ValueError("snapshot split must be train, val, test or pilot")
    bounds = protocol.definition["seeds"][key]
    if split == "val":
        count = settings.get("validation_worlds", bounds["end_inclusive"] - bounds["start_inclusive"] + 1)
        if count > bounds["end_inclusive"] - bounds["start_inclusive"] + 1:
            raise ValueError("snapshot world count exceeds reserved validation pool")
        return tuple(range(bounds["start_inclusive"], bounds["start_inclusive"] + count))
    return tuple(range(bounds["start_inclusive"], bounds["end_inclusive"] + 1))


def future_seed(protocol, history, day, branch, learner_seed=0):
    return int(np.random.SeedSequence([protocol.definition["snapshot_training"]["future_seed_root"],
                                      history, day, branch, learner_seed]).generate_state(1)[0])


def snapshot_scenarios(protocol, split):
    settings = protocol.definition["snapshot_training"]
    worlds = history_seeds(protocol, split)
    capacities = protocol.definition["resources"]["screening_static_capacity_ratios"]
    if split == "val" and len(worlds) % len(capacities):
        raise ValueError("snapshot validation must balance capacities")
    rows = []
    for index, history in enumerate(worlds):
        days = settings["snapshot_days"]
        if split == "pilot":
            days = (days[index % len(days)],)
        for day in days:
            chosen = capacities if split == "test" else (capacities[
                index // (len(worlds) // len(capacities))] if split == "val" else capacities[1],)
            for capacity in chosen:
                for branch in range(settings["test_branches"] if split == "test" else 1):
                    rows.append({"scenario_id": f"{history}-{day}-c{capacity}-b{branch}", "snapshot_day": day,
                        "world_seed": history, "scenario_options": {
                            "snapshot_path": str(ROOT / settings["library"] / f"{history}-{day}.json"),
                            "future_seed": future_seed(protocol, history, day, branch),
                            "screening_capacity_ratio": capacity}})
    return rows


class SnapshotEpisodePlan:
    def __init__(self, protocol, train_seed, anchor, data_path=None):
        self.protocol, self.train_seed = protocol, train_seed
        self.settings = protocol.definition["snapshot_training"]
        if train_seed not in protocol.definition["source"]["train_seed_values"]:
            raise ValueError("unknown snapshot learner seed")
        self.worlds = history_seeds(protocol, "train")
        self.items = []
        self.filtered_count = 0
        for day in self.settings["snapshot_days"]:
            for index, history in enumerate(self.worlds):
                metadata = json.loads((ROOT / self.settings["library"] / f"{history}-{day}.json").read_text(encoding="utf-8"))
                if day >= 49 and metadata["active_infections"] == 0:
                    self.filtered_count += 1
                else:
                    self.items.append((index, day))
        if not self.items:
            raise ValueError("no eligible training snapshots remain")
        self.rng = np.random.default_rng(np.random.SeedSequence([self.settings["schedule_seed"], train_seed, 1]))
        self.order = self.rng.permutation(len(self.items))
        self.index, self.round = 0, 0
        self.anchor, self.data_path = str(anchor), str(data_path) if data_path else None

    def __call__(self, seed=None):
        if seed is not None and (seed != self.train_seed or self.index or self.round):
            raise ValueError("snapshot episode plan may only be seeded before use")
        if self.index == len(self.order):
            self.index, self.round = 0, self.round + 1
            self.order = self.rng.permutation(len(self.items))
        index, day = self.items[int(self.order[self.index])]
        self.index += 1
        history = self.worlds[index]
        capacities = self.protocol.definition["resources"]["screening_static_capacity_ratios"]
        return {"world_seed": history, "scenario_options": {
            "snapshot_path": str(ROOT / self.settings["library"] / f"{history}-{day}.json"),
            "future_seed": future_seed(self.protocol, history, day, self.round, self.train_seed),
            "screening_capacity_ratio": capacities[(index + self.round) % len(capacities)],
            "calibration_artifact": self.anchor, "calibration_data_path": self.data_path}}

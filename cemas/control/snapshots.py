"""Historical state capture and explicit policy handoff for baseline training."""

from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
import hashlib
import json
import multiprocessing
from math import ceil, log2
from pathlib import Path
from types import MappingProxyType

import cloudpickle
import covasim as cv
import numpy as np

from .background import employee_community
from .logging import resolved_snapshot
from .scenarios import ScenarioBundle, resolve_campus_parameters
from .snapshot_protocol import ROOT, history_seeds
from .types import PublicCost, PublicResources, PublicWeeklyRecord


SNAPSHOT_SCHEMA = "uw-snapshot-control-v1"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_identity(protocol, anchor_sha):
    from ..e0.data import load_e0_config
    config = load_e0_config(ROOT / protocol.definition["calibration"]["config"])
    return {"schema": SNAPSHOT_SCHEMA, "anchor_sha256": anchor_sha,
        "recipe": resolved_snapshot(protocol.definition["snapshot_training"]["replay_parameters"]),
        "e0_config_sha256": config["config_sha256"],
        "observation_sha256": file_hash(ROOT / "data/uw_madison_2020_replay.csv"),
        # The anchor already binds the engine, E0 and shared base-model sources.
        # Learner/selection changes invalidate models, not the historical states.
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): file_hash(p)
            for p in (Path(__file__), ROOT / "cemas/replay/simulation.py")}}


class HistoricalPublicRecorder(cv.Analyzer):
    def __init__(self):
        super().__init__(label="snapshot-public-history")
        self.records = []

    def apply(self, sim):
        people = sim.people
        iso, quar = people.isolated & ~people.dead, people.quarantined & ~people.dead
        self.records.append({"day": int(sim.t),
            "diagnoses": int(np.count_nonzero(people.date_diagnosed == sim.t)),
            "tests": int(np.count_nonzero(people.date_tested == sim.t)),
            "isolated": int(iso.sum()), "quarantined": int(quar.sum()),
            "union": int((iso | quar).sum())})


def _capture_history_snapshots(protocol, output, history_seed, split, days, beta):
    from ..e0.data import load_e0_config, load_e0_data
    from ..replay.simulation import build_replay_sim
    from ..replay.study import load_replay_data

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    settings = protocol.definition["snapshot_training"]
    config = load_e0_config(ROOT / protocol.definition["calibration"]["config"])
    sim, measures, _, _, _ = build_replay_sim(config, load_replay_data(config), beta,
        history_seed, **dict(settings["replay_parameters"]), w1_data=load_e0_data(config))
    recorder = HistoricalPublicRecorder()
    recorder.initialize(sim)
    sim["analyzers"].append(recorder)
    paths, entries = [], {}
    for day in days:
        while sim.t < day:
            sim.step()
        bundle = {"version": SNAPSHOT_SCHEMA, "sim": sim, "public_history": recorder.records,
                  "dorm_baseline": measures.dorm_baseline}
        state_path = output / f"{history_seed}-{day}.pkl"
        with state_path.open("xb") as handle:
            cloudpickle.dump(bundle, handle)
        payload = {"version": SNAPSHOT_SCHEMA,
            "history_seed": history_seed, "snapshot_day": day, "split": split,
            "state_file": state_path.name,
            "active_infections": int(np.count_nonzero((sim.people.exposed | sim.people.infectious) & ~sim.people.dead)),
            "population": sim.n, "beta": beta}
        path = state_path.with_suffix(".json")
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        paths.append(str(path))
        entries[path.name] = {"history_seed": history_seed, "snapshot_day": day,
                              "split": split, "state_sha256": file_hash(state_path)}
    return paths, entries


def _capture_snapshot_job(job):
    """Spawn entry: only world-specific state files are written by workers."""
    from .snapshot_protocol import load_training_protocol

    protocol = load_training_protocol(job["protocol_path"])
    return _capture_history_snapshots(protocol, job["output"], job["history_seed"],
        job["split"], job["days"], job["beta"])


def _write_snapshot_catalog(path, catalog):
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2)
    temporary.replace(path)


def generate_snapshot_library(protocol, anchor_path, output, split, seeds=None, *,
                              days=None, workers=1):
    """Capture worlds independently; the parent alone merges the shared manifest."""
    from ..e0.artifacts import load_calibration_artifact

    if type(workers) is not int or workers < 1:
        raise ValueError("snapshot workers must be a positive integer")
    allowed = history_seeds(protocol, split)
    seeds = tuple(allowed if seeds is None else seeds)
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("history seeds must be nonempty and distinct")
    if any(seed not in allowed for seed in seeds):
        raise ValueError("history seed does not belong to declared snapshot split")
    settings = protocol.definition["snapshot_training"]
    days = list(settings["snapshot_days"] if days is None else days)
    if not days or any(d not in settings["snapshot_days"] for d in days) or days != sorted(set(days)):
        raise ValueError("capture days must be increasing declared snapshot days")
    anchor = load_calibration_artifact(anchor_path, protocol)
    identity = snapshot_identity(protocol, anchor.sha256)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output / "snapshots_manifest.lock"
    lock = lock_path.open("x")
    try:
        catalog_path = output / "snapshots_manifest.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {
            "identity": identity, "snapshots": {}}
        if catalog["identity"] != identity:
            raise ValueError("snapshot output already belongs to a different model/recipe")
        for seed in seeds:
            for day in days:
                path = output / f"{seed}-{day}.json"
                if path.exists() or path.with_suffix(".pkl").exists() or path.name in catalog["snapshots"]:
                    raise FileExistsError(path)
        paths = []

        def merge(result):
            captured, entries = result
            catalog["snapshots"].update(entries)
            _write_snapshot_catalog(catalog_path, catalog)
            paths.extend(captured)
            print(f"Captured {split}: {len(paths)}/{len(seeds) * len(days)} snapshots", flush=True)

        if workers == 1:
            for seed in seeds:
                merge(_capture_history_snapshots(protocol, output, seed, split, days, anchor.beta))
        else:
            jobs = [{"protocol_path": str(protocol.source_path), "output": str(output),
                     "history_seed": seed, "split": split, "days": days, "beta": anchor.beta}
                    for seed in seeds]
            with ProcessPoolExecutor(max_workers=min(workers, len(seeds)),
                    mp_context=multiprocessing.get_context("spawn")) as executor:
                for result in executor.map(_capture_snapshot_job, jobs):
                    merge(result)
        return paths
    finally:
        lock.close()
        lock_path.unlink()


def generate_history_snapshots(protocol, anchor_path, output, history_seed, split, *, days=None):
    return generate_snapshot_library(protocol, anchor_path, output, split, [history_seed], days=days)


def _resize_results(sim, horizon):
    # Keep the historical prefix and absolute disease dates. Only result storage
    # and the stopping date change; no simulator/population initialization.
    sim["n_days"] = horizon - 1
    sim["end_day"] = sim["start_day"] + timedelta(days=horizon - 1)
    for result in [*sim.results.values(), *sim.results["variant"].values()]:
        if isinstance(result, cv.Result):
            old = result.values
            values = np.zeros((*old.shape[:-1], horizon), dtype=old.dtype)
            values[..., :sim.t] = old[..., :sim.t]
            result.values = values
    sim.results["date"], sim.results["t"] = sim.datevec, sim.tvec
    sim.rescale_vec = np.ones(horizon)
    sim.complete = False
    sim._orig_pars = None


def restore_snapshot(protocol, path, history_seed, future_seed, beta, *,
                     execution_days=None, screening_capacity_ratio=None):
    from .execution import JointActionExecutor, NotificationEvent
    from .ledger import PublicLedgerAnalyzer
    from .metrics import PrivateMetricsAnalyzer

    if type(future_seed) is not int or not 0 <= future_seed < 2**32:
        raise ValueError("snapshot future_seed must be an ordinary uint32 integer")
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.stem != f"{history_seed}-{payload['snapshot_day']}":
        raise ValueError("snapshot filename differs from its world/date identity")
    if payload["version"] != SNAPSHOT_SCHEMA:
        raise ValueError("unsupported snapshot version")
    if Path(payload["state_file"]).name != payload["state_file"]:
        raise ValueError("snapshot state_file must be a sibling filename")
    state_path = path.parent / payload["state_file"]
    with state_path.open("rb") as handle:
        saved = cloudpickle.load(handle)
    if saved["version"] != SNAPSHOT_SCHEMA:
        raise ValueError("unsupported snapshot state version")
    sim = saved["sim"]
    start = payload["snapshot_day"]
    history = saved["public_history"]
    horizon = protocol.execution_days if execution_days is None else execution_days
    if type(horizon) is not int or horizon < 2:
        raise ValueError("snapshot execution_days must be >= 2")
    _resize_results(sim, start + horizon)
    base = resolve_campus_parameters(protocol, history_seed, beta=beta)
    sim["beta_layer"] = dict(base["beta_layer"])
    sim.people.contacts["d"]["beta"][:] = saved["dorm_baseline"]
    sim.people.contacts["cm"]["beta"][:] = 1.0
    # Existing dated quarantine events must survive removal of native tracing.
    pending = []
    for day, events in list(sim.people._pending_quarantine.items()):
        if day >= start:
            pending.extend(NotificationEvent(-1, int(person), "historical", -1,
                                              int(day), int(end)) for person, end in events)
            del sim.people._pending_quarantine[day]
    resources = protocol.definition["resources"]
    ratio = resources["screening_main_capacity_ratio"] if screening_capacity_ratio is None else screening_capacity_ratio
    if type(ratio) not in (int, float) or not np.isfinite(ratio) or not 0 <= ratio <= 1:
        raise ValueError("invalid snapshot screening capacity")
    capacities = PublicResources(ceil(resources["clinical_tests_per_person_per_day"] * sim.n),
        ceil(ratio * sim.n), ceil(resources["tracing_index_cases_per_person_per_day"] * sim.n))
    executor = JointActionExecutor(protocol, capacities)
    background = employee_community(cv, protocol.definition["engine"]["employee_cm"])
    cum_infections_at_x = int(sim["pop_infected"] + sim.results["new_infections"].values[:start].sum())
    public = PublicLedgerAnalyzer(executor)
    private = PrivateMetricsAnalyzer(protocol.initial_infections, start_day=start)
    sim["interventions"] = [executor, background]
    sim["analyzers"] = [public, private]
    for item in (*sim["interventions"], *sim["analyzers"]):
        item.initialize(sim)
    for event in pending:
        executor._pending_notifications[event.delivery_day].append(event)
    cv.set_seed(future_seed)
    registry = sim.people.campus_registry_metadata
    metadata = MappingProxyType({"world_seed": history_seed, "future_seed": future_seed,
        "snapshot_day": start, "snapshot_path": str(path), "snapshot_split": payload["split"],
        "snapshot_active_infections": payload["active_infections"],
        "public_history": history, "execution_days": horizon, "initial_infections": protocol.initial_infections,
        "cum_infections_at_x": cum_infections_at_x, "beta": beta, "beta_provenance": "verified_e0_snapshot",
        "campus_background": {key: protocol.definition["engine"][key] for key in ("employee_cm", "employee_ta")},
        "registration": {key: tuple(int(i) for i in indices) for key, indices in registry.items()}})
    return ScenarioBundle(sim, executor, public, private, metadata)


def historical_weeks(bundle):
    start = bundle.private_metadata["snapshot_day"]
    past = bundle.private_metadata["public_history"]
    weeks = []
    for lo in range(max(0, start - 28), start, 7):
        rows = past[lo:lo + 7]
        previous = past[lo - 7:lo] if lo >= 7 else []
        diagnoses, tests = sum(r["diagnoses"] for r in rows), sum(r["tests"] for r in rows)
        weeks.append(PublicWeeklyRecord(lo - start, lo + 6 - start, diagnoses,
            cost=PublicCost(isolation_person_days=sum(r["isolated"] for r in rows),
                quarantine_person_days=sum(r["quarantined"] for r in rows),
                union_person_days=sum(r["union"] for r in rows)),
            growth=log2((diagnoses + 1)/(sum(r["diagnoses"] for r in previous)+1)) if previous else 0.,
            growth_valid=bool(previous), diagnosis_test_proxy=diagnoses/tests if tests else 0.,
            proxy_valid=bool(tests), historical=True, total_tests=tests))
    return weeks


def snapshot_week(bundle, start_day, end_day):
    """The same public window is used in observations and execution feedback."""
    if start_day < 0:
        return next(w for w in historical_weeks(bundle)
                    if w.start_day == start_day and w.end_day == end_day)
    week = bundle.public_analyzer.ledger.aggregate_week(start_day, end_day)
    if start_day == 0 and end_day == 6:
        history = historical_weeks(bundle)
        if history:
            week = replace(week, growth=log2((week.delivered_diagnoses + 1) /
                                            (history[-1].delivered_diagnoses + 1)), growth_valid=True)
    return week


def snapshot_feedback(bundle, start_day, end_day):
    from .types import PublicWeekFeedback
    previous = (snapshot_week(bundle, start_day - 7, start_day - 1)
                if start_day or historical_weeks(bundle) else None)
    return PublicWeekFeedback(snapshot_week(bundle, start_day, end_day), previous)


def snapshot_observation(observation, bundle):
    """Merge historical public facts with completed post-takeover weeks."""
    start = bundle.private_metadata["snapshot_day"]
    past = bundle.private_metadata["public_history"]
    weeks = historical_weeks(bundle)
    for lo in range(0, observation.decision_day // 7 * 7, 7):
        weeks.append(snapshot_week(bundle, lo, lo + 6))
    weeks = weeks[-4:]
    known = {} if observation.decision_day else {
        "previous_day_known_isolated": past[-1]["isolated"],
        "previous_day_known_quarantined": past[-1]["quarantined"],
        "previous_day_known_union": past[-1]["union"]}
    return replace(observation, snapshot_day=start,
        history=(PublicWeeklyRecord(),) * (4-len(weeks)) + tuple(weeks),
        week_valid=(False,) * (4-len(weeks)) + (True,) * len(weeks), **known)

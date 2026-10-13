"""Load the v1 control definition without constructing a simulation.

The complete definition belongs to the runner: it contains private configuration
and must never be passed to a controller. Objective settings are recommendations
pending Phase 3 source-domain confirmation, not an executable reward contract.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class ProtocolValidationError(ValueError):
    """The protocol contains an invalid or inconsistent static definition."""


@dataclass(frozen=True, slots=True)
class ControlProtocol:
    """Immutable runner configuration; only public observations reach policies."""

    protocol_id: str
    population: int
    execution_days: int
    n_days: int
    decision_interval_days: int
    history_weeks: int
    initial_infections: int
    action_order: tuple[str, ...]
    action_sizes: tuple[int, ...]
    joint_count: int
    definition: Mapping[str, Any] = field(repr=False)
    source_path: Path
    source_sha256: str

    @property
    def objective_status(self) -> str:
        """Phase 0 preserves objective recommendations without freezing them."""
        return "recommendation_pending_phase3"


def _required(mapping: Mapping[str, Any], key: str, location: str) -> Any:
    if key not in mapping:
        raise ProtocolValidationError(f"Missing {location}.{key}")
    return mapping[key]


def _section(mapping: Mapping[str, Any], key: str, location: str) -> dict:
    value = _required(mapping, key, location)
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"{location}.{key} must be an object")
    return value


def _integer(value: Any, location: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProtocolValidationError(f"{location} must be an integer >= {minimum}")
    return value


def _number(value: Any, location: str, *, positive: bool = False) -> None:
    valid = type(value) in (int, float)
    if valid:
        try:
            valid = math.isfinite(value) and (value > 0 if positive else value >= 0)
        except OverflowError:
            valid = False
    if not valid:
        constraint = "positive" if positive else "nonnegative"
        raise ProtocolValidationError(f"{location} must be a finite {constraint} number")


def _seed_list(value: Any, location: str) -> list[tuple[str, int, int]]:
    if not isinstance(value, list) or not value:
        raise ProtocolValidationError(f"{location} must be a nonempty seed list")
    seeds = [_integer(seed, location) for seed in value]
    if len(set(seeds)) != len(seeds):
        raise ProtocolValidationError(f"{location} contains duplicate seeds")
    return [(location, seed, seed) for seed in seeds]


def _seed_range(value: Any, location: str, *, exclusive: bool = False) -> tuple[str, int, int]:
    end_key = "end_exclusive" if exclusive else "end_inclusive"
    if not isinstance(value, dict) or set(value) != {"start_inclusive", end_key}:
        raise ProtocolValidationError(
            f"{location} must explicitly contain start_inclusive and {end_key}"
        )
    start = _integer(value["start_inclusive"], f"{location}.start_inclusive")
    end = _integer(value[end_key], f"{location}.{end_key}")
    if exclusive:
        end -= 1
    if start > end:
        raise ProtocolValidationError(f"{location} must contain at least one seed")
    return location, start, end


def _validate_world_seeds(definition: dict) -> None:
    seeds = _section(definition, "seeds", "protocol")
    required_uses = {
        "smoke", "calibration", "fit_evaluation", "validation_A", "validation_B",
        "memory_collection", "prompt_development", "E1_E2", "E3_city_A", "E3_city_B", "E4",
    }
    missing = required_uses - set(seeds)
    if missing:
        raise ProtocolValidationError(f"Missing seeds uses: {sorted(missing)}")
    intervals = []
    for use, value in seeds.items():
        if use in {"range_notation", "controller_rng"}:
            continue
        location = f"seeds.{use}"
        if isinstance(value, list):
            intervals.extend(_seed_list(value, location))
        else:
            intervals.append(_seed_range(value, location))

    source = _section(definition, "source", "protocol")
    intervals.extend(_seed_list(_required(source, "pilot_worlds", "source"), "source.pilot_worlds"))
    pools = _required(source, "source_world_pools", "source")
    if not isinstance(pools, list) or not pools:
        raise ProtocolValidationError("source.source_world_pools must be a nonempty list")
    for index, pool in enumerate(pools):
        intervals.append(_seed_range(pool, f"source.source_world_pools[{index}]", exclusive=True))

    calibration = _section(definition, "calibration", "protocol")
    intervals.extend(_seed_list(
        _required(calibration, "exploratory_train_seeds", "calibration"),
        "calibration.exploratory_train_seeds",
    ))
    holdout = _required(calibration, "exploratory_holdout_seed_range_inclusive", "calibration")
    # This existing field explicitly declares inclusive endpoints in its name.
    if isinstance(holdout, dict) and set(holdout) == {"start", "end"}:
        holdout = {"start_inclusive": holdout["start"], "end_inclusive": holdout["end"]}
    intervals.append(_seed_range(holdout, "calibration.exploratory_holdout_seed_range_inclusive"))
    # World identities are distinct from optimizer, training, and controller RNG seeds.
    for index, (use, start, end) in enumerate(intervals):
        for other_use, other_start, other_end in intervals[:index]:
            if max(start, other_start) <= min(end, other_end):
                raise ProtocolValidationError(f"World seeds overlap: {use} and {other_use}")


def _validate_v1(definition: Any) -> None:
    if not isinstance(definition, dict):
        raise ProtocolValidationError("Protocol must be a JSON object")
    if _required(definition, "protocol_id", "protocol") != "cemas-control-v1":
        raise ProtocolValidationError("protocol_id must be cemas-control-v1")

    engine = _section(definition, "engine", "protocol")
    population = _integer(_required(engine, "pop_size", "engine"), "engine.pop_size", 1)
    horizon = _integer(_required(engine, "execution_days", "engine"), "engine.execution_days", 1)
    n_days = _integer(_required(engine, "n_days", "engine"), "engine.n_days")
    if n_days != horizon - 1:
        raise ProtocolValidationError("engine.n_days must equal execution_days - 1")
    infections = _integer(_required(engine, "pop_infected", "engine"), "engine.pop_infected")
    if infections > population:
        raise ProtocolValidationError("engine.pop_infected must not exceed pop_size")
    for key in ("decision_interval_days", "history_weeks"):
        _integer(_required(engine, key, "engine"), f"engine.{key}", 1)
    if engine["decision_interval_days"] != 7:
        raise ProtocolValidationError("engine.decision_interval_days must be 7 for v1")
    if engine["history_weeks"] != 4:
        raise ProtocolValidationError("engine.history_weeks must be 4 for the public schema")
    scale = _required(engine, "pop_scale", "engine")
    _number(scale, "engine.pop_scale", positive=True)
    if scale != 1:
        raise ProtocolValidationError("engine.pop_scale must be 1")
    for key in ("rescale", "use_waning"):
        if _required(engine, key, "engine") is not False:
            raise ProtocolValidationError(f"engine.{key} must be false")

    actions = _section(definition, "actions", "protocol")
    if _required(actions, "order", "actions") != ["T", "S", "C", "E", "A"]:
        raise ProtocolValidationError("actions.order must be [T, S, C, E, A]")
    sizes = _required(actions, "sizes", "actions")
    if not isinstance(sizes, list) or any(type(size) is not int for size in sizes) or sizes != [3, 4, 3, 3, 3]:
        raise ProtocolValidationError("actions.sizes must be integer values [3, 4, 3, 3, 3]")
    joint_count = _integer(_required(actions, "joint_count", "actions"), "actions.joint_count", 1)
    if joint_count != math.prod(sizes):
        raise ProtocolValidationError("actions.joint_count must equal the product of actions.sizes (324)")

    objective = _section(definition, "objective", "protocol")
    for key in ("test_reference_daily_ratio", "notification_reference_daily_ratio"):
        _number(_required(objective, key, "objective"), f"objective.{key}", positive=True)
    resources = _section(definition, "resources", "protocol")
    for key in ("clinical_tests_per_person_per_day", "screening_main_capacity_ratio", "tracing_index_cases_per_person_per_day"):
        _number(_required(resources, key, "resources"), f"resources.{key}")
    ratios = _required(resources, "screening_static_capacity_ratios", "resources")
    if not isinstance(ratios, list) or not ratios:
        raise ProtocolValidationError("resources.screening_static_capacity_ratios must be a nonempty list")
    for index, ratio in enumerate(ratios):
        _number(ratio, f"resources.screening_static_capacity_ratios[{index}]")
    experiments = _section(definition, "experiments", "protocol")
    for name, experiment in experiments.items():
        if isinstance(experiment, dict):
            for key in ("screening_capacity_ratio", "low_capacity_ratio", "high_capacity_ratio"):
                if key in experiment:
                    _number(experiment[key], f"experiments.{name}.{key}")
    _validate_world_seeds(definition)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _reject_constant(value: str) -> None:
    raise ProtocolValidationError(f"JSON constant {value} is not finite")


def load_protocol(path: str | Path) -> ControlProtocol:
    """Read, validate, and freeze configuration; no simulation or reward runs."""
    source_path = Path(path).resolve()
    contents = source_path.read_bytes()
    try:
        definition = json.loads(contents.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolValidationError(f"Cannot decode protocol JSON: {exc}") from exc
    _validate_v1(definition)
    engine = definition["engine"]
    actions = definition["actions"]
    return ControlProtocol(
        protocol_id=definition["protocol_id"],
        population=engine["pop_size"],
        execution_days=engine["execution_days"],
        n_days=engine["n_days"],
        decision_interval_days=engine["decision_interval_days"],
        history_weeks=engine["history_weeks"],
        initial_infections=engine["pop_infected"],
        action_order=tuple(actions["order"]),
        action_sizes=tuple(actions["sizes"]),
        joint_count=actions["joint_count"],
        definition=_freeze(definition),
        source_path=source_path,
        source_sha256=hashlib.sha256(contents).hexdigest(),
    )

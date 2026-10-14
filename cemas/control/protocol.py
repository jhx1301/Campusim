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

    def __deepcopy__(self, memo):
        """The frozen protocol is safe to share across simulator copies.

        Its recursively frozen definition contains ``MappingProxyType`` objects,
        which are intentionally not deepcopyable.  Covasim copies intervention
        parameters during construction; returning this immutable object keeps
        that engine operation from mutating or re-materializing protocol state.
        """
        return self

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


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolValidationError(f"{location} must be nonempty text")
    return value


def _probability(value: Any, location: str) -> None:
    _number(value, location)
    if value > 1:
        raise ProtocolValidationError(f"{location} must be in [0, 1]")


def _validate_action_dimension(actions: Mapping[str, Any], name: str, size: int) -> None:
    levels = _required(actions, name, "actions")
    if not isinstance(levels, list) or len(levels) != size:
        raise ProtocolValidationError(f"actions.{name} must contain exactly {size} levels")
    testing_keys = (
        "symptomatic_daily_probability", "ordinary_asymptomatic_daily_probability",
        "symptomatic_quarantine_entry_probability", "asymptomatic_quarantine_entry_probability",
    )
    contact_scopes = {"home", "school", "work", "community"}
    expected_keys = {
        "T": set(testing_keys), "S": {"request_ratio"},
        "C": {"coverage_probability", "notification_delay_days"},
        "E": {"transmission_multiplier", "restriction_time_fraction"},
        "A": {"transmission_multiplier", "restriction_time_fraction"},
    }
    parameter_sets = []
    for index, level in enumerate(levels):
        location = f"actions.{name}[{index}]"
        if not isinstance(level, dict):
            raise ProtocolValidationError(f"{location} must be an object")
        if _integer(level.get("level"), f"{location}.level") != index:
            raise ProtocolValidationError(f"{location}.level must equal {index}")
        for key in ("label", "semantic"):
            _text(level.get(key), f"{location}.{key}")
        params = _section(level, "effective_parameters", location)
        if set(params) != expected_keys[name]:
            raise ProtocolValidationError(f"{location}.effective_parameters has incorrect fields")
        parameter_sets.append(params)
        if name == "C":
            for key in ("coverage_probability", "notification_delay_days"):
                group = _section(params, key, location)
                if set(group) != contact_scopes:
                    raise ProtocolValidationError(f"{location}.{key} must describe all four contact scopes")
                for scope, value in group.items():
                    validator = _probability if key == "coverage_probability" else _integer
                    validator(value, f"{location}.{key}.{scope}")
        else:
            for key, value in params.items():
                _probability(value, f"{location}.{key}")
            if name == "T" and params["ordinary_asymptomatic_daily_probability"] != 0:
                raise ProtocolValidationError("ordinary asymptomatic testing belongs to S, not T")

    # Level ordering describes intensity, independently of any simulator mapping.
    if name == "C":
        columns = [([p[key][scope] for p in parameter_sets], key == "notification_delay_days")
                   for key in ("coverage_probability", "notification_delay_days")
                   for scope in sorted(contact_scopes)]
    else:
        columns = [([p[key] for p in parameter_sets], key == "transmission_multiplier")
                   for key in sorted(expected_keys[name])]
    if any(values != sorted(values, reverse=descending) for values, descending in columns):
        raise ProtocolValidationError(f"actions.{name} intensity must be monotone by level")
    if name == "S" and parameter_sets[0]["request_ratio"] != 0:
        raise ProtocolValidationError("actions.S level zero must request no screening")
    if name in ("E", "A") and parameter_sets[0] != {
            "transmission_multiplier": 1, "restriction_time_fraction": 0}:
        raise ProtocolValidationError(f"actions.{name} level zero must be unrestricted")


def _validate_action_semantics(definition: Mapping[str, Any]) -> None:
    actions = definition["actions"]
    fixed_values = {
        "semantics_version": "cemas-action-semantics-v1",
        "representation": "additional_intervention_over_fixed_baseline",
        "zero_level_semantics": "no_additional_intervention",
        "effective_parameter_semantics": "total_effective_setting_after_level_selection_including_baseline_not_an_additive_delta",
        "encoding": "((((t*4+s)*3+c)*3+e)*3+a)",
        "simulator_mapping": "deferred_to_phase2_executor",
        "initial": [0, 0, 0, 0, 0], "minimum_reference": [0, 0, 0, 0, 0],
        "maximum_reference": {"T": 2, "S": "highest_resource_legal_level", "C": 2, "E": 2, "A": 2},
    }
    for key, expected in fixed_values.items():
        # JSON spelling also distinguishes booleans/floats from integer levels.
        if json.dumps(_required(actions, key, "actions"), sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ProtocolValidationError(f"actions.{key} must match the frozen v1 definition")
    for key, expected in (("hold_intervals", 0), ("transition_limit", None),
                          ("truth_guardrail", False), ("risk_override", False)):
        value = _required(actions, key, "actions")
        if type(value) is not type(expected) or value != expected:
            raise ProtocolValidationError(f"actions.{key} must match the shared v1 selection rules")

    environment = _section(definition, "environment_configuration", "protocol")
    baseline = _section(environment, "fixed_baseline", "environment_configuration")
    if baseline.get("owner") != "environment_configuration":
        raise ProtocolValidationError("fixed_baseline.owner must be environment_configuration")
    for key in ("controller_visible", "public_observation_inclusion"):
        if baseline.get(key) is not False:
            raise ProtocolValidationError(f"fixed_baseline.{key} must be false")
    for name, dim in (("testing", "T"), ("screening", "S"), ("contact_tracing", "C"),
                      ("education", "E"), ("activity", "A")):
        entry = _section(baseline, name, "fixed_baseline")
        _text(entry.get("semantic"), f"fixed_baseline.{name}.semantic")
        if entry.get("reference_level") != f"actions.{dim}[0].effective_parameters":
            raise ProtocolValidationError(f"fixed_baseline.{name} must reference its zero level")

    dimensions = _section(actions, "dimension_metadata", "actions")
    scopes = {
        "T": "case_related_testing_and_quarantine_testing",
        "S": "active_periodic_screening",
        "C": "contact_tracing_investigation_and_notification",
        "E": "classroom_teaching_contacts",
        "A": "non_classroom_work_public_and_community_activity",
    }
    if set(dimensions) != set(scopes):
        raise ProtocolValidationError("actions.dimension_metadata must describe T/S/C/E/A")
    for name, scope in scopes.items():
        metadata = _section(dimensions, name, "actions.dimension_metadata")
        for key in ("name", "level_semantics", "parameter_provenance"):
            _text(metadata.get(key), f"actions.dimension_metadata.{name}.{key}")
        if metadata.get("target_scope") != scope:
            raise ProtocolValidationError(f"actions.dimension_metadata.{name}.target_scope must be {scope}")
    screening = dimensions["S"]
    for key, expected in (
        ("request_quantity_unit", "people_per_day"),
        ("population_reference", "public_registered_population_N_fixed_at_reset"),
        ("request_count_rounding", "ceil_ratio_times_N"),
        ("legality_rule", "request_ratio_times_N_lte_public_screening_daily_capacity"),
    ):
        if screening.get(key) != expected:
            raise ProtocolValidationError(f"actions.dimension_metadata.S.{key} must be {expected}")
    for name, size in zip(("T", "S", "C", "E", "A"), (3, 4, 3, 3, 3)):
        _validate_action_dimension(actions, name, size)


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
    _validate_action_semantics(definition)

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

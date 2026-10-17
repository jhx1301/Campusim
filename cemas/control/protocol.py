"""Load the v1 control definition without constructing a simulation.

The complete definition belongs to the runner: it contains private configuration
and must never be passed to a controller. P3 validates an executable development
objective; source validation and the horizon gate precede final parameter freeze.
"""

from dataclasses import dataclass, field
from datetime import date
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
        """The verified configuration distinguishes development from final use."""
        return self.definition["objective"]["status"]


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


def validate_activity_config(activity_config: Mapping[str, Any]) -> None:
    """Validate the shared nominal daily budgets without changing their values."""
    if not isinstance(activity_config, Mapping):
        raise ProtocolValidationError("activity must be an object")
    for key in ("daily_budget_school_or_work", "daily_budget_community",
                "dual_school_work_each", "neither_school_nor_work_community"):
        _probability(_required(activity_config, key, "activity"), f"activity.{key}")
    community = activity_config["daily_budget_community"]
    totals = (
        (activity_config["daily_budget_school_or_work"] + community,
         "daily_budget_school_or_work + daily_budget_community"),
        (2 * activity_config["dual_school_work_each"] + community,
         "2 * dual_school_work_each + daily_budget_community"),
        (activity_config["neither_school_nor_work_community"],
         "neither_school_nor_work_community"),
    )
    for total, fields in totals:
        if not math.isclose(total, 1, rel_tol=0, abs_tol=1e-12):
            raise ProtocolValidationError(f"activity.{fields} must equal 1")


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


def _validate_objective(definition: Mapping[str, Any]) -> None:
    objective = _section(definition, "objective", "protocol")
    if objective.get("formula_version") != "cemas-reward-v1":
        raise ProtocolValidationError("unsupported objective.formula_version")
    if objective.get("status") not in ("development_candidate", "frozen"):
        raise ProtocolValidationError("unsupported objective.status")
    _text(objective.get("formula"), "objective.formula")
    _number(objective.get("lambda"), "objective.lambda")
    weights = _section(objective, "burden_weights", "objective")
    if set(weights) != {"tests", "notifications", "union", "activity"}:
        raise ProtocolValidationError("objective.burden_weights must contain the four v1 burdens")
    for key, value in weights.items():
        _number(value, f"objective.burden_weights.{key}")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ProtocolValidationError("objective.burden_weights must sum to one")
    for key in ("test_reference_daily_ratio", "notification_reference_daily_ratio"):
        _number(objective.get(key), f"objective.{key}", positive=True)
    for key, expected in (("gamma", 1), ("switch_penalty", 0),
                          ("reward_clip", False), ("initial_infections_in_reward", False)):
        value = objective.get(key)
        if type(value) is not type(expected) or value != expected:
            raise ProtocolValidationError(f"objective.{key} must match v1 semantics")
    architecture = _section(definition, "architecture_constraints", "protocol")
    if (architecture.get("reward_formula_confirmation_phase") != 3
            or architecture.get("reward_parameters_freeze_phase") != 6
            or "reward_formula_freeze_phase" in architecture):
        raise ProtocolValidationError("reward formula confirmation and parameter freeze phases must be explicit")


def _validate_calibration(definition: Mapping[str, Any]) -> None:
    spec = _section(definition, "calibration", "protocol")
    for key, expected in (("method_version", "cemas-e0-v1"),
                          ("primary_demography", "shared_v1_engine_population"),
                          ("fit_parameter", "beta"), ("trials", 100),
                          ("repeats_per_trial", 3), ("fixed_layer_weights", True),
                          ("use_waning", False), ("r_eff_penalty", False),
                          ("independent_fit_runs", 20),
                          ("loss", "daily_diagnoses_MSE_normalized_by_observed_mean_plus_1_squared"),
                          ("data_provenance", "reconstructed_aggregate_series")):
        value = spec.get(key)
        if type(value) is not type(expected) or value != expected:
            raise ProtocolValidationError(f"calibration.{key} must match v1 semantics")
    limits = spec.get("beta_range")
    if not isinstance(limits, list) or len(limits) != 2:
        raise ProtocolValidationError("calibration.beta_range must have two endpoints")
    for value in limits:
        _number(value, "calibration.beta_range", positive=True)
    if limits[0] >= limits[1]:
        raise ProtocolValidationError("calibration.beta_range must be increasing")
    for window_key, execution_key, n_days_key in (
            ("primary_window", "primary_execution_days", "primary_n_days"),
            ("exploratory_fit_window", "exploratory_fit_execution_days", "exploratory_fit_n_days")):
        window = spec.get(window_key)
        try:
            if not isinstance(window, list) or len(window) != 2:
                raise ValueError()
            start, end = (date.fromisoformat(item) for item in window)
            days = (end - start).days + 1
        except (TypeError, ValueError) as exc:
            raise ProtocolValidationError(f"invalid calibration.{window_key}") from exc
        if days <= 0 or spec.get(execution_key) != days or spec.get(n_days_key) != days - 1:
            raise ProtocolValidationError(f"calibration.{window_key} actual days do not match n_days")
    testing = _section(spec, "testing", "calibration")
    expected_testing = {"symp_test": 80, "quar_test": 30, "sensitivity": 0.95,
                        "loss_prob": 0, "test_delay": 0}
    if set(testing) != set(expected_testing):
        raise ProtocolValidationError("calibration.testing must explicitly specify test_num parameters")
    for key, expected in expected_testing.items():
        if type(testing[key]) is not type(expected) or testing[key] != expected:
            raise ProtocolValidationError(f"calibration.testing.{key} must match v1")
    if len(definition["seeds"]["calibration"]) != spec["repeats_per_trial"]:
        raise ProtocolValidationError("calibration repeats must match the calibration world list")
    if len(spec["exploratory_train_seeds"]) != spec["repeats_per_trial"]:
        raise ProtocolValidationError("auxiliary calibration requires three fitting worlds")
    primary_evaluation = definition["seeds"]["fit_evaluation"]
    auxiliary_evaluation = spec["exploratory_holdout_seed_range_inclusive"]
    if (primary_evaluation["end_inclusive"] - primary_evaluation["start_inclusive"] + 1 != 20
            or auxiliary_evaluation["end"] - auxiliary_evaluation["start"] + 1 != 20):
        raise ProtocolValidationError("independent calibration evaluation requires twenty worlds")
    if spec.get("fit_band_quantiles") != [0.05, 0.95]:
        raise ProtocolValidationError("calibration.fit_band_quantiles must be [0.05, 0.95]")
    try:
        auxiliary_start, auxiliary_end = map(date.fromisoformat, spec["exploratory_fit_window"])
        holdout_start, holdout_end = map(date.fromisoformat, spec["exploratory_holdout"])
        primary_start, primary_end = map(date.fromisoformat, spec["primary_window"])
        if (auxiliary_start != primary_start or (holdout_start - auxiliary_end).days != 1
                or holdout_end < holdout_start or holdout_end != primary_end):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolValidationError("auxiliary holdout must continuously follow fitting through the primary end") from exc
    _integer(spec.get("optimizer_seed"), "calibration.optimizer_seed")


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

    _validate_objective(definition)
    validate_activity_config(_required(definition, "activity", "protocol"))
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
    _validate_calibration(definition)


def _validate_llm(definition: Mapping[str, Any]) -> None:
    llm = _section(_section(definition, "controllers", "protocol"), "llm", "controllers")
    for key in ("primary_api_model", "secondary_api_model", "primary_effort", "prompt_template"):
        _text(llm.get(key), f"controllers.llm.{key}")
    template = Path(llm["prompt_template"])
    if template.is_absolute() or ".." in template.parts:
        raise ProtocolValidationError("controllers.llm.prompt_template must be project-relative")
    if llm.get("token_count_method") != "official_local_chat_template_v1":
        raise ProtocolValidationError("controllers.llm.token_count_method must use the official local chat template")
    for key in ("input_token_budget", "max_output_tokens", "reason_max_chars"):
        _integer(llm.get(key), f"controllers.llm.{key}", 1)
    _number(llm.get("timeout_seconds"), "controllers.llm.timeout_seconds", positive=True)
    _number(llm.get("temperature"), "controllers.llm.temperature")
    _probability(llm.get("primary_top_p"), "controllers.llm.primary_top_p")
    for key, expected in (("max_attempts", 3), ("primary_sdk_retries", 0), ("repair_model_calls", 0),
                          ("ensemble_size", 1), ("tools_enabled", False)):
        if type(llm.get(key)) is not type(expected) or llm[key] != expected:
            raise ProtocolValidationError(f"controllers.llm.{key} must match Phase 4")
    if llm.get("retry_delays_seconds") != [2, 4] or any(type(item) is not int for item in llm["retry_delays_seconds"]):
        raise ProtocolValidationError("controllers.llm.retry_delays_seconds must be [2, 4]")
    if type(llm.get("thinking")) is not bool or llm.get("json_fields") != ["action", "reason"]:
        raise ProtocolValidationError("controllers.llm thinking/json_fields are invalid")


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
    _validate_llm(definition)
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

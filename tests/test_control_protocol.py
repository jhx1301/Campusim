"""Phase 0 static protocol checks; these tests never construct a simulator."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType

import pytest

from cemas.control.protocol import ProtocolValidationError, load_protocol


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "docs" / "control_protocol_v1.json"


@pytest.fixture
def definition():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def write_protocol(tmp_path, definition):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(definition, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_v1_metadata_and_exact_source_hash():
    protocol = load_protocol(PROTOCOL_PATH)
    assert protocol.protocol_id == "cemas-control-v1"
    assert (protocol.population, protocol.execution_days, protocol.n_days) == (12000, 112, 111)
    assert (protocol.initial_infections, protocol.decision_interval_days, protocol.history_weeks) == (30, 7, 4)
    assert protocol.action_order == ("T", "S", "C", "E", "A")
    assert protocol.action_sizes == (3, 4, 3, 3, 3)
    assert protocol.joint_count == 324
    assert protocol.source_path == PROTOCOL_PATH.resolve()
    assert protocol.source_sha256 == hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()


def test_definition_and_nested_values_are_read_only():
    protocol = load_protocol(PROTOCOL_PATH)
    assert isinstance(protocol.definition, MappingProxyType)
    assert isinstance(protocol.definition["engine"], MappingProxyType)
    assert isinstance(protocol.definition["source"]["source_world_pools"], tuple)
    with pytest.raises(FrozenInstanceError):
        protocol.population = 1
    with pytest.raises(TypeError):
        protocol.definition["engine"]["pop_size"] = 1
    with pytest.raises(TypeError):
        protocol.definition["source"]["source_world_pools"][0]["start_inclusive"] = 1
    assert "source_world_pools" not in repr(protocol)


@pytest.mark.parametrize("key,value", [
    ("prompt_template", "../private.json"), ("token_count_method", "characters_divided_by_four"),
    ("max_attempts", 4), ("max_attempts", True), ("retry_delays_seconds", [2, 4, 8]),
    ("primary_sdk_retries", 2), ("input_token_budget", 0), ("max_output_tokens", True),
    ("reason_max_chars", 0), ("max_output_tokens", 0), ("tools_enabled", True),
    ("thinking", "true"), ("json_fields", ["action", "reason", "risk"]),
])
def test_phase4_rejects_inconsistent_call_configuration(tmp_path, definition, key, value):
    definition["controllers"]["llm"][key] = value
    with pytest.raises(ProtocolValidationError, match="controllers.llm"):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("section,key,value,error", [
    (None, "protocol_id", "other-v1", "protocol_id"),
    ("engine", "pop_size", 0, "engine.pop_size"),
    ("engine", "pop_size", True, "engine.pop_size"),
    ("engine", "execution_days", 0, "engine.execution_days"),
    ("engine", "n_days", 112, "execution_days - 1"),
    ("engine", "pop_infected", 12001, "must not exceed"),
    ("engine", "decision_interval_days", 0, "decision_interval_days"),
    ("engine", "decision_interval_days", 14, "decision_interval_days must be 7"),
    ("engine", "history_weeks", -1, "history_weeks"),
    ("engine", "history_weeks", 6, "history_weeks must be 4"),
    ("engine", "pop_scale", 2, "pop_scale must be 1"),
    ("engine", "pop_scale", True, "pop_scale"),
    ("engine", "rescale", True, "rescale must be false"),
    ("engine", "use_waning", 0, "use_waning must be false"),
    ("actions", "order", ["S", "T", "C", "E", "A"], "actions.order"),
    ("actions", "sizes", [3.0, 4, 3, 3, 3], "actions.sizes"),
    ("actions", "sizes", [3, 3, 3, 3, 3], "actions.sizes"),
    ("actions", "joint_count", 323, "actions.joint_count"),
    ("objective", "test_reference_daily_ratio", 0, "positive"),
    ("objective", "notification_reference_daily_ratio", -1, "positive"),
    ("resources", "clinical_tests_per_person_per_day", -0.01, "nonnegative"),
    ("resources", "screening_static_capacity_ratios", [0.02, -0.05], "nonnegative"),
    ("resources", "tracing_index_cases_per_person_per_day", True, "nonnegative"),
])
def test_inconsistent_static_definition_rejected(tmp_path, definition, section, key, value, error):
    target = definition if section is None else definition[section]
    target[key] = value
    with pytest.raises(ProtocolValidationError, match=error):
        load_protocol(write_protocol(tmp_path, definition))


def test_horizon_can_be_revised_with_matching_n_days(tmp_path, definition):
    definition["engine"].update(execution_days=140, n_days=139)
    assert load_protocol(write_protocol(tmp_path, definition)).execution_days == 140


def test_zero_resources_are_valid_but_event_capacities_cannot_be_negative(tmp_path, definition):
    definition["resources"]["screening_main_capacity_ratio"] = 0
    assert load_protocol(write_protocol(tmp_path, definition)).definition["resources"]["screening_main_capacity_ratio"] == 0
    definition["experiments"]["E4"]["low_capacity_ratio"] = -1
    with pytest.raises(ProtocolValidationError, match="experiments.E4.low_capacity_ratio"):
        load_protocol(write_protocol(tmp_path, definition))


def test_objective_configuration_is_validated_without_evaluating_formula_text(tmp_path, definition):
    definition["objective"].update(
        formula="raise_if_evaluated()", **{"lambda": 7},
        burden_weights={"tests": 0.1, "notifications": 0.2, "union": 0.3, "activity": 0.4},
    )
    protocol = load_protocol(write_protocol(tmp_path, definition))
    assert protocol.objective_status == "development_candidate"
    assert protocol.definition["objective"]["lambda"] == 7
    assert protocol.definition["objective"]["formula"] == "raise_if_evaluated()"
    assert protocol.definition["objective"]["burden_weights"]["tests"] == 0.1


ACTIVITY_BUDGET_KEYS = (
    "daily_budget_school_or_work", "daily_budget_community", "dual_school_work_each",
    "neither_school_nor_work_community",
)


def test_activity_budgets_accept_a_conserving_configuration(tmp_path, definition):
    definition["activity"].update(daily_budget_school_or_work=.6, daily_budget_community=.4,
                                  dual_school_work_each=.3, neither_school_nor_work_community=1)
    activity = load_protocol(write_protocol(tmp_path, definition)).definition["activity"]
    assert tuple(activity[key] for key in ACTIVITY_BUDGET_KEYS) == (.6, .4, .3, 1)


@pytest.mark.parametrize("key", ACTIVITY_BUDGET_KEYS)
def test_activity_requires_each_budget(tmp_path, definition, key):
    del definition["activity"][key]
    with pytest.raises(ProtocolValidationError, match="activity"):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("activity", [None, [], "activity"])
def test_activity_configuration_must_be_a_mapping(tmp_path, definition, activity):
    definition["activity"] = activity
    with pytest.raises(ProtocolValidationError, match="activity"):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("key", ACTIVITY_BUDGET_KEYS)
@pytest.mark.parametrize("value", [True, "0.2", -.1, 1.1, float("nan"), float("inf")])
def test_activity_rejects_invalid_budget_values(tmp_path, definition, key, value):
    definition["activity"][key] = value
    with pytest.raises(ProtocolValidationError, match="activity|not finite"):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("key,value", [
    ("daily_budget_school_or_work", .7), ("dual_school_work_each", .35),
    ("neither_school_nor_work_community", .9),
    ("daily_budget_school_or_work", .8 + 5e-10),
    ("dual_school_work_each", .4 + 5e-10),
    ("neither_school_nor_work_community", 1 - 5e-10),
])
def test_activity_budgets_must_conserve_one_day(tmp_path, definition, key, value):
    definition["activity"][key] = value
    with pytest.raises(ProtocolValidationError, match="activity"):
        load_protocol(write_protocol(tmp_path, definition))


def test_activity_sum_tolerance_preserves_values_without_normalizing(tmp_path, definition):
    definition["activity"]["daily_budget_school_or_work"] += 5e-13
    activity = load_protocol(write_protocol(tmp_path, definition)).definition["activity"]
    assert activity["daily_budget_school_or_work"] == definition["activity"]["daily_budget_school_or_work"]
    assert activity["daily_budget_community"] == .2
    assert activity["daily_budget_school_or_work"] + activity["daily_budget_community"] > 1


@pytest.mark.parametrize("key,value", [
    ("status", "recommendation_pending_phase3"), ("formula_version", "unknown"),
    ("lambda", True), ("lambda", -1), ("gamma", .99),
    ("switch_penalty", 1), ("reward_clip", True), ("initial_infections_in_reward", True),
    ("burden_weights", {"tests": .5, "notifications": .5, "union": .5, "activity": .5}),
    ("burden_weights", {"tests": .25, "notifications": .25, "union": .25}),
])
def test_executable_objective_rejects_inconsistent_configuration(tmp_path, definition, key, value):
    definition["objective"][key] = value
    with pytest.raises(ProtocolValidationError):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("key,value", [
    ("trials", 99), ("primary_demography", "legacy_t18"),
    ("fit_parameter", "beta_and_layers"), ("r_eff_penalty", True),
    ("primary_n_days", 16), ("beta_range", [.04, .005]),
    ("fit_band_quantiles", [.1, .9]), ("exploratory_holdout", ["2020-08-14", "2020-08-18"]),
])
def test_e0_configuration_rejects_legacy_or_misaligned_definitions(tmp_path, definition, key, value):
    definition["calibration"][key] = value
    with pytest.raises(ProtocolValidationError):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("change", ["purpose_overlap", "duplicate_list", "inclusive_boundary", "pilot_overlap", "calibration_overlap", "training_pool_overlap"])
def test_world_seed_purpose_overlap_is_rejected(tmp_path, definition, change):
    if change == "purpose_overlap":
        definition["seeds"]["smoke"][0] = 20001
    elif change == "duplicate_list":
        definition["seeds"]["smoke"] = [90001, 90001]
    elif change == "inclusive_boundary":
        definition["seeds"]["memory_collection"]["start_inclusive"] = 20118
    elif change == "pilot_overlap":
        definition["source"]["pilot_worlds"][0] = 90001
    elif change == "calibration_overlap":
        definition["calibration"]["exploratory_train_seeds"][0] = 10021
    else:
        definition["source"]["source_world_pools"][0] = {"start_inclusive": 50020, "end_exclusive": 50100}
    with pytest.raises(ProtocolValidationError, match="overlap|duplicate"):
        load_protocol(write_protocol(tmp_path, definition))


@pytest.mark.parametrize("change", ["ambiguous_endpoint", "inclusive_source", "empty_range", "boolean_seed", "missing_purpose"])
def test_seed_definitions_require_explicit_valid_endpoints(tmp_path, definition, change):
    if change == "ambiguous_endpoint":
        definition["seeds"]["validation_A"] = {"start": 20001, "end": 20009}
    elif change == "inclusive_source":
        definition["source"]["source_world_pools"][0] = {"start_inclusive": 1000000, "end_inclusive": 1100000}
    elif change == "empty_range":
        definition["seeds"]["validation_A"]["end_inclusive"] = 20000
    elif change == "boolean_seed":
        definition["seeds"]["smoke"][0] = True
    else:
        del definition["seeds"]["memory_collection"]
    with pytest.raises(ProtocolValidationError):
        load_protocol(write_protocol(tmp_path, definition))


def test_adjacent_half_open_training_pools_do_not_overlap(tmp_path, definition):
    definition["source"]["source_world_pools"][1] = {"start_inclusive": 1100000, "end_exclusive": 1200000}
    assert load_protocol(write_protocol(tmp_path, definition)).definition["source"]["source_world_pools"][1]["start_inclusive"] == 1100000


def test_named_inclusive_holdout_range_includes_its_end(tmp_path, definition):
    definition["seeds"]["smoke"][0] = definition["calibration"]["exploratory_holdout_seed_range_inclusive"]["end"]
    with pytest.raises(ProtocolValidationError, match="overlap"):
        load_protocol(write_protocol(tmp_path, definition))


def test_invalid_json_and_nonfinite_numbers_are_rejected(tmp_path, definition):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ProtocolValidationError, match="Cannot decode"):
        load_protocol(path)
    definition["resources"]["screening_main_capacity_ratio"] = float("nan")
    with pytest.raises(ProtocolValidationError, match="not finite"):
        load_protocol(write_protocol(tmp_path, definition))


def test_protocol_module_can_load_without_engine_or_optional_algorithms():
    code = """
import importlib.abc
import importlib.util
import sys

class BlockDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'covasim', 'cemas', 'gymnasium', 'gym', 'torch', 'numpy', 'sentence_transformers'}:
            raise AssertionError('Unexpected dependency: ' + fullname)

sys.meta_path.insert(0, BlockDependencies())
spec = importlib.util.spec_from_file_location('isolated_protocol', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
protocol = module.load_protocol(sys.argv[2])
assert protocol.joint_count == 324
assert protocol.objective_status == 'development_candidate'
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT / "cemas" / "control" / "protocol.py"), str(PROTOCOL_PATH)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr

"""Phase 1 action language and protocol boundary checks; no simulator runs."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, fields, replace
from itertools import product
import json
from pathlib import Path

import pytest

from cemas.control import (
    ACTION_TABLE, ActionResolution, ActionVector, PublicObservation, PublicResources,
    decode_action, encode_action, legal_action_mask, load_protocol,
)
from cemas.control.protocol import ProtocolValidationError


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs" / "control_protocol_v1.json"


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_PATH)


@pytest.fixture
def definition():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_exhaustive_joint_actions_and_both_codec_directions():
    independent = tuple(ActionVector(v) for v in product(range(3), range(4), range(3), range(3), range(3)))
    assert type(ACTION_TABLE) is tuple
    assert ACTION_TABLE == independent
    assert len(set(ACTION_TABLE)) == 324
    for action in independent:
        assert decode_action(encode_action(action)) == action
    for action_id in range(324):
        assert encode_action(decode_action(action_id)) == action_id
        assert ACTION_TABLE[action_id] == decode_action(action_id)
    with pytest.raises(FrozenInstanceError):
        ACTION_TABLE[0].values = (1, 0, 0, 0, 0)


@pytest.mark.parametrize("vector,expected", [
    ((0, 0, 0, 0, 0), 0), ((0, 0, 0, 0, 1), 1), ((0, 0, 0, 1, 0), 3),
    ((0, 0, 1, 0, 0), 9), ((0, 1, 0, 0, 0), 27), ((1, 0, 0, 0, 0), 108),
    ((2, 3, 1, 0, 1), 307), ((2, 3, 2, 2, 2), 323),
])
def test_frozen_id_examples(vector, expected):
    assert encode_action(ActionVector(vector)) == expected
    assert decode_action(expected).values == vector


@pytest.mark.parametrize("bad_id", [-1, 324, 1.0, True, False, "1", None])
def test_decode_rejects_invalid_ids_without_fallback(bad_id):
    with pytest.raises((TypeError, ValueError)):
        decode_action(bad_id)


@pytest.mark.parametrize("bad_vector", [
    (), (0,) * 6, (3, 0, 0, 0, 0), (0, 4, 0, 0, 0), (0, 0, 3, 0, 0),
    (0, 0, 0, 3, 0), (0, 0, 0, 0, 3), (0, 0, -1, 0, 0),
    (0, 0, 0.0, 0, 0), (0, 0, True, 0, 0),
])
def test_action_vector_rejects_bad_shape_type_or_level(bad_vector):
    with pytest.raises(ValueError):
        ActionVector(bad_vector)


def test_codec_accepts_only_the_shared_action_type():
    with pytest.raises(TypeError):
        encode_action((0, 0, 0, 0, 0))


@pytest.mark.parametrize("capacity,allowed_s", [
    (0, {0}), (239, {0}), (240, {0, 1}), (599, {0, 1}),
    (600, {0, 1, 2}), (1199, {0, 1, 2}), (1200, {0, 1, 2, 3}),
])
def test_mask_matches_public_screening_boundary_for_every_id(protocol, capacity, allowed_s):
    resources = PublicResources(screening_daily_capacity=capacity)
    mask = legal_action_mask(resources, 12000, protocol.definition["actions"])
    assert type(mask) is tuple and len(mask) == 324
    assert all(type(value) is bool for value in mask)
    assert sum(mask) == 81 * len(allowed_s)
    for action_id, action in enumerate(ACTION_TABLE):
        assert mask[action_id] == (action.values[1] in allowed_s)
    # Masking never removes a codec entry or changes a requested vector.
    assert decode_action(323) == ActionVector((2, 3, 2, 2, 2))


def test_mask_uses_registered_population_and_ignores_runtime_capacities(protocol):
    spec = protocol.definition["actions"]
    low = PublicResources(0, 240, 0)
    high = PublicResources(999999, 240, 999999)
    assert legal_action_mask(low, 12000, spec) == legal_action_mask(high, 12000, spec)
    assert sum(legal_action_mask(low, 24000, spec)) == 81


def test_mask_reads_protocol_ratios_and_preserves_decimal_boundaries(definition):
    spec = definition["actions"]
    for level, ratio in zip(spec["S"], (0, .01, .02, .07)):
        level["effective_parameters"]["request_ratio"] = ratio
    before = deepcopy(spec)
    assert sum(legal_action_mask(PublicResources(0, 2, 0), 100, spec)) == 243
    assert sum(legal_action_mask(PublicResources(0, 7, 0), 100, spec)) == 324
    assert sum(legal_action_mask(PublicResources(0, 7, 0), 101, spec)) == 243
    assert spec == before


@pytest.mark.parametrize("population", [0, -1, True, 12000.0, "12000"])
def test_mask_rejects_invalid_population(protocol, population):
    with pytest.raises(ValueError):
        legal_action_mask(PublicResources(), population, protocol.definition["actions"])


@pytest.mark.parametrize("ratio", [True, float("nan"), float("inf"), -0.1, 1.1, "0.02"])
def test_mask_rejects_invalid_ratio(definition, ratio):
    definition["actions"]["S"][1]["effective_parameters"]["request_ratio"] = ratio
    with pytest.raises(ValueError):
        legal_action_mask(PublicResources(), 12000, definition["actions"])


def test_mask_rejects_invalid_specs_and_nonpublic_resource_payloads(definition):
    spec = definition["actions"]
    with pytest.raises(TypeError):
        legal_action_mask({"screening_daily_capacity": 0}, 12000, spec)
    with pytest.raises(TypeError):
        legal_action_mask(PublicResources(), 12000, None)
    with pytest.raises(ValueError):
        legal_action_mask(PublicResources(), 12000, {})
    spec["S"][0]["effective_parameters"]["request_ratio"] = .01
    with pytest.raises(ValueError):
        legal_action_mask(PublicResources(), 12000, spec)
    spec["S"][0]["effective_parameters"]["request_ratio"] = 0
    spec["S"][0]["level"] = False
    with pytest.raises(ValueError):
        legal_action_mask(PublicResources(), 12000, spec)


def test_resolution_preserves_request_adjustment_and_fallback():
    requested = ActionVector((2, 3, 1, 0, 1))
    executed = ActionVector((2, 2, 1, 0, 1))
    accepted = ActionResolution(requested, requested, 307, 307)
    assert accepted.requested_action == accepted.executed_action
    adjusted = ActionResolution(requested, executed, 307, 280, "screening_capacity_changed")
    assert adjusted.requested_action is requested
    assert adjusted.executed_action is executed
    assert adjusted.fallback_reason is None
    fallback = ActionResolution(None, executed, None, 280, fallback_reason="invalid_controller_output")
    assert fallback.requested_action is None
    assert asdict(adjusted)["requested_action_id"] == 307
    with pytest.raises(FrozenInstanceError):
        adjusted.executed_action = requested


@pytest.mark.parametrize("changes", [
    {"requested_action_id": 1}, {"requested_action_id": True},
    {"executed_action_id": -1}, {"executed_action_id": 324}, {"executed_action_id": 0.0},
    {"requested_action": None}, {"executed_action": (0, 0, 0, 0, 0)},
    {"adjustment_reason": ""}, {"fallback_reason": " "},
    {"adjustment_reason": "changed_but_same_action"},
])
def test_resolution_rejects_inconsistent_contract(changes):
    action = ActionVector((0, 0, 0, 0, 0))
    valid = ActionResolution(action, action, 0, 0)
    with pytest.raises((ValueError, TypeError)):
        replace(valid, **changes)


def test_resolution_requires_reasons_for_missing_or_changed_requests():
    zero = decode_action(0)
    with pytest.raises(ValueError):
        ActionResolution(None, zero, None, 0)
    with pytest.raises(ValueError):
        ActionResolution(zero, decode_action(1), 0, 1)


def test_protocol_defines_environment_baseline_and_abstract_semantics(protocol):
    d = protocol.definition
    baseline = d["environment_configuration"]["fixed_baseline"]
    assert baseline["owner"] == "environment_configuration"
    assert baseline["controller_visible"] is False
    assert baseline["public_observation_inclusion"] is False
    public_names = {field.name for field in fields(PublicObservation)}
    assert not public_names & {"fixed_baseline", "environment_configuration", "effective_parameters"}
    actions = d["actions"]
    assert "fixed_baseline" not in actions
    assert not {"layer_semantics", "protected_home_layers"} & actions.keys()
    assert actions["zero_level_semantics"] == "no_additional_intervention"
    assert actions["simulator_mapping"] == "deferred_to_phase2_executor"
    for name in actions["order"]:
        assert actions["dimension_metadata"][name]["parameter_provenance"]
        for level in actions[name]:
            assert level["semantic"] and level["effective_parameters"]


def test_protocol_effective_parameters_match_approved_levels(protocol):
    actions = protocol.definition["actions"]
    testing = [level["effective_parameters"] for level in actions["T"]]
    assert [p["symptomatic_daily_probability"] for p in testing] == [.08, .14, .22]
    assert [p["ordinary_asymptomatic_daily_probability"] for p in testing] == [0, 0, 0]
    assert [p["symptomatic_quarantine_entry_probability"] for p in testing] == [.25, .5, .8]
    assert [p["asymptomatic_quarantine_entry_probability"] for p in testing] == [0, .03, .08]
    assert [p["effective_parameters"]["request_ratio"] for p in actions["S"]] == [0, .02, .05, .1]
    scopes = ("home", "school", "work", "community")
    tracing = [level["effective_parameters"] for level in actions["C"]]
    assert [tuple(p["coverage_probability"][s] for s in scopes) for p in tracing] == [
        (.6, .2, .18, .15), (.95, .45, .4, .35), (1, .8, .7, .55)]
    assert [tuple(p["notification_delay_days"][s] for s in scopes) for p in tracing] == [
        (0, 3, 3, 4), (0, 1, 1, 2), (0, 0, 0, 1)]
    for name, multipliers, fractions in [("E", [1, .5, 0], [0, .5, 1]), ("A", [1, .75, .5], [0, .25, .5])]:
        assert [p["effective_parameters"]["transmission_multiplier"] for p in actions[name]] == multipliers
        assert [p["effective_parameters"]["restriction_time_fraction"] for p in actions[name]] == fractions


@pytest.mark.parametrize("path,value", [
    (("actions", "encoding"), "other_order"),
    (("actions", "zero_level_semantics"), "disabled"),
    (("actions", "initial"), [False, 0, 0, 0, 0]),
    (("actions", "T", 0, "level"), False),
    (("actions", "T", 0, "effective_parameters", "symptomatic_daily_probability"), 2),
    (("actions", "T", 1, "effective_parameters", "symptomatic_daily_probability"), .01),
    (("actions", "T", 2, "effective_parameters", "ordinary_asymptomatic_daily_probability"), .1),
    (("actions", "S", 0, "effective_parameters", "request_ratio"), .01),
    (("actions", "C", 0, "effective_parameters", "notification_delay_days", "home"), 0.0),
    (("actions", "C", 1, "effective_parameters", "coverage_probability", "home"), .1),
    (("actions", "E", 0, "effective_parameters", "transmission_multiplier"), .9),
    (("actions", "A", 1, "effective_parameters", "restriction_time_fraction"), -.2),
    (("actions", "dimension_metadata", "T", "parameter_provenance"), ""),
    (("actions", "dimension_metadata", "A", "target_scope"), "classroom_teaching_contacts"),
    (("environment_configuration", "fixed_baseline", "controller_visible"), True),
    (("environment_configuration", "fixed_baseline", "public_observation_inclusion"), True),
    (("environment_configuration", "fixed_baseline", "testing", "reference_level"), "actions.T[1].effective_parameters"),
])
def test_protocol_rejects_inconsistent_action_semantics(tmp_path, definition, path, value):
    target = definition
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    path = tmp_path / "bad_protocol.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ProtocolValidationError):
        load_protocol(path)

"""Threshold decisions at upgrade/downgrade and capacity boundaries."""

from pathlib import Path

import numpy as np
import pytest

from cemas.control.actions import legal_action_mask
from cemas.control.controllers import ThresholdController, load_baseline_controller
from cemas.control.artifacts import save_baseline_artifact
from cemas.control.observation import encode_observation, encode_rl_observation, OBSERVATION_FEATURE_NAMES
from cemas.control.protocol import load_protocol, source_grid, ProtocolValidationError
from cemas.control.types import (ActionVector, PublicObservation, PublicPopulation,
                                 PublicResources, PublicWeeklyRecord)


PROTOCOL = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"
BOUNDARIES = {"T": [1, 5], "S": [.5, 3, 10], "C": [.5, 3], "E": [5, 15], "A": [3, 10]}


def observation(diagnoses=(), current=(0, 0, 0, 0, 0), capacity=100, growth=0, growth_valid=False):
    protocol = load_protocol(PROTOCOL)
    population = PublicPopulation(1000, (0, 1000, 0, 0, 0), 1000, 0)
    resources = PublicResources(20, capacity, 100)
    weeks = tuple(PublicWeeklyRecord(start_day=i * 7, end_day=i * 7 + 6,
                                    delivered_diagnoses=count, growth=growth, growth_valid=growth_valid)
                  for i, count in enumerate(diagnoses))
    missing = 4 - len(weeks)
    return PublicObservation(len(weeks) * 7, 112, 2, population, resources, ActionVector(current),
                             (0,) * 5, legal_action_mask(resources, 1000, protocol.definition["actions"]),
                             (PublicWeeklyRecord(),) * missing + weeks,
                             (False,) * missing + (True,) * len(weeks))


def test_threshold_day_zero_and_first_week_upgrade():
    controller = ThresholdController(BOUNDARIES, .5)
    assert controller.decide(observation()).action.values == (0, 0, 0, 0, 0)
    assert controller.decide(observation((15,))).action.values == (2, 3, 2, 2, 2)
    assert controller.decide(observation((0,), current=(2, 3, 2, 2, 2))).action.values == (2, 3, 2, 2, 2)


def test_downgrade_is_strict_two_weeks_and_can_cross_multiple_boundaries():
    controller = ThresholdController(BOUNDARIES, .5)
    assert controller.decide(observation((0, 0), current=(2, 3, 2, 2, 2))).action.values == (0, 0, 0, 0, 0)
    assert controller.decide(observation((0, 5), current=(0, 0, 0, 0, 2))).action.values[4] == 2
    assert controller.decide(observation((0, 4), current=(0, 0, 0, 0, 2))).action.values[4] == 1


def test_capacity_drop_is_immediate_without_losing_other_dimensions():
    action = ThresholdController(BOUNDARIES, .5).decide(observation((15,), capacity=20)).action
    assert action.values == (2, 1, 2, 2, 2)
    day_zero = ThresholdController(BOUNDARIES, .5).decide(observation(current=(2, 3, 2, 2, 2), capacity=0))
    assert day_zero.action.values == (2, 0, 2, 2, 2)


@pytest.mark.parametrize("growth,valid,expected", [(2, True, 2), (-2, True, 1), (0, False, 1)])
def test_growth_uses_valid_measurement_and_clipped_multiplier(growth, valid, expected):
    action = ThresholdController(BOUNDARIES, .5).decide(observation((3,), growth=growth, growth_valid=valid)).action
    assert action.values[0] == expected


def test_fixed_rl_encoding_changes_only_two_raw_constants():
    obs = observation((3, 6))
    raw = encode_observation(obs)
    encoded = encode_rl_observation(obs, 1000, 112)
    changed = [OBSERVATION_FEATURE_NAMES.index("context.population"),
               OBSERVATION_FEATURE_NAMES.index("context.execution_days")]
    assert encoded.dtype == np.float32 and encoded.shape == (198,)
    assert np.all(encoded[changed] == 1)
    keep = np.ones(198, dtype=bool)
    keep[changed] = False
    assert np.array_equal(encoded[keep], raw[keep])
    other = encode_rl_observation(obs, 2000, 224)
    assert np.all(other[changed] == .5)


def test_threshold_artifact_roundtrip_and_tampered_task(tmp_path):
    import json
    protocol = load_protocol(PROTOCOL)
    path = save_baseline_artifact(tmp_path, protocol, "threshold",
                                  parameters={"thresholds": BOUNDARIES, "hysteresis": .75})
    loaded, metadata = load_baseline_controller(protocol, path)
    assert loaded.decide(observation((10,))).action == ThresholdController(BOUNDARIES, .75).decide(observation((10,))).action
    assert not hasattr(loaded, "protocol") and metadata["method"] == "threshold"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["task"]["execution_days"] = 140
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="task"):
        load_baseline_controller(protocol, path)


@pytest.mark.parametrize("pool,seed,expected", [
    ("validation_A", 20005, (1, .05, 0)),
    ("validation_B", 20104, (.9, .05, 1)),
    ("memory_collection", 30027, (1.12, .1, 2)),
])
def test_shared_grid(pool, seed, expected):
    condition = source_grid(load_protocol(PROTOCOL), pool, seed)
    assert tuple(condition.values()) == expected


def test_baseline_protocol_rejects_incompatible_rollout_and_replay(tmp_path):
    import json
    original = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    for method, key, value in (("ppo", "n_steps", 300), ("ddqn", "warmup_steps", 1)):
        from copy import deepcopy
        data = deepcopy(original)
        data["controllers"][method][key] = value
        path = tmp_path / f"{method}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ProtocolValidationError):
            load_protocol(path)


@pytest.mark.parametrize("section,key,value", [
    ("source", "train_seed_values", [11, 11, 33]),
    ("ddqn", "epsilon_linear_fraction", .00001),
])
def test_source_configuration_rejects_seed_loss_and_zero_epsilon_horizon(tmp_path, section, key, value):
    import json
    data = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    target = data["source"] if section == "source" else data["controllers"][section]
    target[key] = value
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProtocolValidationError):
        load_protocol(path)


def test_threshold_trial_metadata_is_not_mistaken_for_a_loaded_model(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import cemas.control.calibration as calibration
    from cemas.control.controllers import _BASELINE_METADATA
    from cemas.control.runner import run_episode

    protocol = load_protocol(PROTOCOL)
    monkeypatch.setattr(calibration, "load_calibration_artifact",
                        lambda *args, **kwargs: SimpleNamespace(beta=.01, sha256="a" * 64))
    controller = ThresholdController(BOUNDARIES, .5)
    _BASELINE_METADATA[controller] = {"method": "threshold", "parameters": {
        "thresholds": BOUNDARIES, "hysteresis": .5}}
    result = run_episode(protocol, controller, tmp_path / "trial", 20001,
                         purpose="scientific", scenario_options={
                             "execution_days": 2, "calibration_artifact": "verified-by-test"})
    assert result.summary["elapsed_days"] == 2
    assert result.summary["positive_cost"] >= 0

"""Employee background scope, regenerated edges, and policy composition."""

from pathlib import Path
from types import SimpleNamespace
import json

import covasim as cv
import numpy as np
import pytest

from cemas.control.actions import encode_action
from cemas.control.background import background_multipliers, employee_community
from cemas.control.protocol import load_protocol, ProtocolValidationError
from cemas.control.scenarios import base_model_configuration, build_scenario
from cemas.control.types import ActionResolution, ActionVector


ROOT = Path(__file__).resolve().parents[1]


def test_employee_edges_scaled_once_after_each_regeneration():
    class Sim(dict):
        pass

    sim = Sim(dynam_layer={"cm": 1})
    sim.n = 4
    layer = {"p1": np.array([0, 0, 2]), "p2": np.array([1, 2, 3]),
             "beta": np.array([.7, 1.3, 1.8])}
    sim.people = SimpleNamespace(campus_registry_metadata={"student_indices": [0, 1]},
                                 contacts={"cm": layer})
    background = employee_community(cv, .1)
    background.initialize(sim)
    sim.t = 0
    background.apply(sim)
    np.testing.assert_allclose(layer["beta"], [.7, .13, .18])
    background.apply(sim)
    np.testing.assert_allclose(layer["beta"], [.7, .13, .18])
    sim.t = 1
    layer.update(p1=np.array([2, 0, 1]), p2=np.array([3, 1, 3]), beta=np.ones(3))
    background.apply(sim)
    np.testing.assert_allclose(layer["beta"], [.1, 1., .1])


@pytest.mark.parametrize("name", ["employee_cm", "employee_ta"])
@pytest.mark.parametrize("value", [-.1, 1.1, float("nan"), True])
def test_background_rejects_invalid_configuration(name, value):
    with pytest.raises(ValueError, match=name):
        background_multipliers({name: value})


def test_control_background_composes_with_actions_and_survives_week_boundary():
    protocol = load_protocol(ROOT / "docs/control_protocol_v1.json")
    bundle = build_scenario(protocol, 90001, population=300, execution_days=9,
                            initial_infections=2)
    sim = bundle.sim
    base = base_model_configuration(protocol)
    assert base["campus_background"] == {"employee_cm": .1, "employee_ta": .5}
    assert base["beta_layer"]["ta"] == pytest.approx(.6)
    assert protocol.definition["engine"]["beta_layer"]["ta"] == 1.2
    students = sim.people.campus_registry_metadata["student_indices"]
    employees = np.setdiff1d(np.arange(sim.n), students)
    for day in range(9):
        if day in (0, 7):
            action = ActionVector((0, 0, 0, 2, 2) if day == 0 else (0, 0, 0, 0, 0))
            identity = encode_action(action)
            bundle.executor.set_action(ActionResolution(action, action, identity, identity))
        sim.step()
        layer = sim.people.contacts["cm"]
        mask = np.isin(layer["p1"], employees) | np.isin(layer["p2"], employees)
        assert mask.any() and (~mask).any()
        np.testing.assert_allclose(layer["beta"][mask], .1)
        np.testing.assert_allclose(layer["beta"][~mask], 1.)
        assert sim["beta_layer"]["ta"] == pytest.approx(.6)
        assert sim["beta_layer"]["cm"] == pytest.approx(.35 * (.5 if day < 7 else 1))
        assert sim["beta_layer"]["clu"] == (0 if day < 7 else 1)
    sim.finalize(verbose=0)


def test_static_community_cannot_accumulate_background_scaling():
    background = employee_community(cv, .1)
    with pytest.raises(ValueError, match="daily dynamic cm"):
        background.initialize({"dynam_layer": {"cm": 0}})


@pytest.mark.parametrize("name", ["employee_cm", "employee_ta"])
def test_control_rejects_background_different_from_e0(tmp_path, name):
    definition = json.loads((ROOT / "docs/control_protocol_v1.json").read_text(encoding="utf-8"))
    definition["engine"][name] = 1.0
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ProtocolValidationError, match=name):
        load_protocol(path)

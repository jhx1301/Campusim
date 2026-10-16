"""Task-cost invariants independent of a simulator or particular controller."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from cemas.control.protocol import load_protocol
from cemas.control.rewards import V1RewardCalculator
from cemas.control.types import ActionVector, ExecutedAction, PrivateMetrics, PublicCost


PROTOCOL = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


def metrics(start=0, end=6, new=0):
    return PrivateMetrics(start, end, new, 3, new + 3, new, new)


def history(start=0, end=6, action=(0, 0, 0, 0, 0)):
    return (ExecutedAction(start, end, ActionVector(action)),)


def test_cost_has_fixed_full_horizon_scales_and_matches_the_recommended_formula():
    calc = V1RewardCalculator(load_protocol(PROTOCOL), 100, 10)
    cost = PublicCost(clinical_tests=10, screening_tests=20, delivered_notifications=40,
                      isolation_person_days=50, quarantine_person_days=20, union_person_days=60,
                      school_restriction_person_days=20, work_restriction_person_days=10,
                      community_restriction_person_days=30)
    result = calc.breakdown(metrics(new=5), cost, history())
    expected = -(5 / 100 + .25 * (30 / 120 + 40 / 100 + 60 / 1000 + 60 / 1000))
    assert result.reward == pytest.approx(expected)
    assert calc.compute(metrics(new=5), cost, history()) == result.reward
    assert calc.configuration["denominators"] == (100, 120, 100, 1000, 1000)


def test_initial_infections_and_action_levels_do_not_add_cost():
    calc = V1RewardCalculator(load_protocol(PROTOCOL), 100, 10)
    first = metrics()
    assert calc.compute(first, PublicCost(), history()) == 0
    changed_initial = replace(first, initial_infections=50, cumulative_infections=50)
    assert calc.compute(changed_initial, PublicCost(), history(action=(2, 3, 2, 2, 2))) == 0


def test_terminal_tail_is_additive_without_an_extra_terminal_charge():
    calc = V1RewardCalculator(load_protocol(PROTOCOL), 100, 10)
    first = PublicCost(clinical_tests=14, isolation_person_days=7, union_person_days=7)
    tail = PublicCost(clinical_tests=6, isolation_person_days=3, union_person_days=3)
    full = PublicCost(clinical_tests=20, isolation_person_days=10, union_person_days=10)
    weekly = calc.compute(metrics(new=2), first, history())
    weekly += calc.compute(metrics(7, 9, 1), tail, history(7, 9))
    assert weekly == pytest.approx(calc.compute(metrics(0, 9, 3), full, history(0, 9)))


def test_notifications_above_reference_are_retained():
    calc = V1RewardCalculator(load_protocol(PROTOCOL), 100, 10)
    result = calc.breakdown(metrics(), PublicCost(delivered_notifications=300), history())
    assert result.normalized[2] == 3
    assert result.weighted[2] == .75


def test_development_lambda_changes_the_same_burdens_only(tmp_path):
    definition = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    definition["objective"]["lambda"] = 2
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    default = V1RewardCalculator(load_protocol(PROTOCOL), 100, 10)
    changed = V1RewardCalculator(load_protocol(path), 100, 10)
    cost = PublicCost(clinical_tests=12)
    a = default.breakdown(metrics(new=5), cost, history())
    b = changed.breakdown(metrics(new=5), cost, history())
    assert b.weighted[0] == a.weighted[0]
    assert b.weighted[1] == 2 * a.weighted[1]


def test_reward_requires_actual_complete_window_and_uses_actual_horizon():
    protocol = load_protocol(PROTOCOL)
    short, long = V1RewardCalculator(protocol, 100, 10), V1RewardCalculator(protocol, 100, 20)
    cost = PublicCost(clinical_tests=12)
    assert short.compute(metrics(), cost, history()) == 2 * long.compute(metrics(), cost, history())
    with pytest.raises(ValueError, match="cover"):
        short.compute(metrics(), cost, ())
    with pytest.raises(ValueError, match="exactly"):
        short.compute(metrics(), cost, history(0, 5))
    with pytest.raises(ValueError, match="horizon"):
        short.compute(metrics(7, 10), cost, history(7, 10))

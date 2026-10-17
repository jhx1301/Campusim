"""Shared execution rules tested against Covasim's real People primitives."""

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import covasim as cv
import numpy as np
import pytest

from cemas.control.actions import encode_action
from cemas.control.execution import JointActionExecutor
from cemas.control.protocol import load_protocol
from cemas.control.types import ActionResolution, ActionVector, PublicPopulation, PublicResources


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs" / "control_protocol_v1.json"
LAYERS = {"home": ("d", "ta"), "school": ("clu", "clg"),
          "work": ("of",), "community": ("cm",)}


def resolution(values):
    action = ActionVector(values)
    return ActionResolution(action, action, encode_action(action), encode_action(action))


@pytest.fixture
def world(monkeypatch):
    """Small registered groups with actual People.test/check_quar methods."""
    from cemas.control import scenarios

    n = 12
    definition = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    definition["resources"]["tests"]["sensitivity"] = 1
    protocol = replace(load_protocol(PROTOCOL_PATH), definition=definition)
    sim = cv.Sim(pop_size=n, pop_infected=0, n_days=60, pop_type="random",
                 rand_seed=9102, verbose=0, rescale=False)
    sim.initialize()
    sim.people.contacts = cv.Contacts(layer_keys=[name for group in LAYERS.values() for name in group])
    sim["beta_layer"] = {name: 1.2 for group in LAYERS.values() for name in group}
    population = PublicPopulation(n, (n, 0, 0, 0, 0), 6, 6, 2)
    school = np.zeros(n)
    work = np.zeros(n)
    community = np.full(n, .2)
    school[:4], school[4:6] = .8, .4
    work[4:6], work[6:10] = .4, .8
    community[10:] = 1
    registry = SimpleNamespace(
        public_population=population, school_indices=tuple(range(6)),
        work_indices=tuple(range(4, 10)),
        screening_groups=(tuple(range(6)), tuple(range(6, 10)), tuple(range(10, 12))),
        school_weights=school, work_weights=work, community_weights=community,
        layer_groups=LAYERS)
    monkeypatch.setattr(scenarios, "build_population_registry", lambda people, *, activity_config: registry)
    executor = JointActionExecutor(protocol, PublicResources(12, 12, 12))
    executor.initialize(sim)
    return sim, executor, definition


def run_day(sim, executor, day):
    sim.t = sim.people.t = day
    sim.people.init_flows()
    sim.people.is_exp = sim.people.true("exposed")
    executor.apply(sim)
    sim.people.update_states_post()
    return executor.finish_day(sim)


def links(sim, layer, left, right):
    sim.people.contacts[layer] = cv.Layer(p1=np.asarray(left, dtype=np.int64),
                                          p2=np.asarray(right, dtype=np.int64),
                                          beta=np.ones(len(left)))


def test_clinical_priority_capacity_and_no_action_rewriting(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    sim.people.symptomatic[:5] = True
    sim.people.quarantined[[0, 1, 6]] = True
    sim.people.date_quarantined[[0, 1, 6]] = -1
    sim.people.date_end_quarantine[[0, 1, 6]] = 14
    executor.set_resources(PublicResources(2, 12, 0))
    executor.set_action(resolution((2, 0, 0, 0, 0)))
    record = run_day(sim, executor, 0)
    audit = executor.day_audits[0]
    assert set(audit.clinical_indices) == {0, 1}
    assert (audit.clinical_requested, audit.clinical_executed, audit.clinical_unmet) == (6, 2, 4)
    assert record.cost.clinical_tests == 2
    assert record.executed_action == ActionVector((2, 0, 0, 0, 0))
    assert sim.results["new_tests"][0] == 2


def test_selected_testing_parameters_already_include_baseline(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.full(n, .2))
    sim.people.symptomatic[:] = True
    executor.set_action(resolution((1, 0, 0, 0, 0)))
    record = run_day(sim, executor, 0)
    # T1=.14, not .14+.08: no .2 draw is a request.
    assert record.cost.clinical_tests == 0


def test_screening_recent_test_boundary_both_paths_and_same_day_dedup(world, monkeypatch):
    sim, executor, definition = world
    definition["actions"]["S"][3]["effective_parameters"]["request_ratio"] = 1
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    sim.people.symptomatic[:6] = True
    executor.set_resources(PublicResources(6, 12, 0))
    executor.set_action(resolution((2, 3, 0, 0, 0)))
    first = run_day(sim, executor, 0)
    audit = executor.day_audits[0]
    assert first.cost.clinical_tests == first.cost.screening_tests == 6
    assert not set(audit.clinical_indices) & set(audit.screening_indices)
    assert len(set(audit.clinical_indices + audit.screening_indices)) == 12
    assert (audit.screening_requested, audit.screening_unmet) == (12, 6)
    sim.people.symptomatic[:] = False
    for day in (1, 2, 3):
        assert run_day(sim, executor, day).cost.screening_tests == 0
    fourth = run_day(sim, executor, 4)
    assert fourth.cost.screening_tests == 12
    assert set(executor.day_audits[-1].screening_indices[:6]) == set(range(6))


def test_screening_largest_remainders_redistribution_and_ceiling(world):
    sim, executor, definition = world
    definition["actions"]["S"][1]["effective_parameters"]["request_ratio"] = .34
    definition["actions"]["S"][2]["effective_parameters"]["request_ratio"] = .34
    definition["actions"]["S"][3]["effective_parameters"]["request_ratio"] = .34
    executor.set_action(resolution((0, 1, 0, 0, 0)))
    sim.people.diagnosed[:6] = True
    # ceil(.34*12)=5. School's unavailable proportional quota is reassigned.
    record = run_day(sim, executor, 0)
    selected = executor.day_audits[0].screening_indices
    assert record.cost.screening_tests == 5
    assert all(i >= 6 for i in selected)
    assert sum(6 <= i < 10 for i in selected) == 3
    assert sum(i >= 10 for i in selected) == 2


def test_screening_prefers_never_screened_then_oldest_in_each_group(world):
    sim, executor, definition = world
    definition["actions"]["S"][3]["effective_parameters"]["request_ratio"] = .5
    executor.set_action(resolution((0, 3, 0, 0, 0)))
    executor._last_screen_day[:6] = [0, 0, -1, -2, -np.inf, -np.inf]
    record = run_day(sim, executor, 0)
    assert record.cost.screening_tests == 6
    assert set(executor.day_audits[0].screening_indices[:3]) == {3, 4, 5}


def test_diagnosis_counts_delivery_not_sample_day(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    sim.people.symptomatic[0] = sim.people.infectious[0] = True
    sim.people.date_recovered[0] = 20
    executor.set_action(resolution((2, 0, 0, 0, 0)))
    first = run_day(sim, executor, 0)
    assert sim.people.flows["new_diagnoses"] == 1
    assert first.delivered_diagnoses == 0
    assert first.cost.clinical_tests == 1
    assert executor.day_audits[0].tracing_requested == 0
    second = run_day(sim, executor, 1)
    assert second.delivered_diagnoses == 1
    assert second.cost.clinical_tests == 0
    assert second.known_isolated == 1
    assert executor.day_audits[1].tracing_requested == 1


def test_tracing_counts_index_cases_not_contacts_and_no_backlog(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    links(sim, "d", [0, 0, 0, 1, 1, 1], [2, 3, 4, 5, 6, 7])
    sim.people.date_diagnosed[:2] = 0
    sim.people.date_recovered[:2] = 30
    executor.set_resources(PublicResources(0, 12, 1))
    executor.set_action(resolution((0, 0, 2, 0, 0)))
    record = run_day(sim, executor, 0)
    audit = executor.day_audits[0]
    assert (audit.tracing_requested, audit.tracing_executed, audit.tracing_unmet) == (2, 1, 1)
    assert record.cost.delivered_notifications == 3
    assert len(executor.investigations) == 1
    assert run_day(sim, executor, 1).cost.delivered_notifications == 0
    assert executor.day_audits[1].tracing_requested == 0


def test_notifications_deduplicate_keep_investigations_and_merge_expiry(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    links(sim, "d", [0, 1], [2, 2])
    links(sim, "ta", [0, 1], [2, 2])
    sim.people.date_diagnosed[:2] = 0
    sim.people.date_recovered[:2] = 30
    sim.people.quarantined[2] = True
    sim.people.date_end_quarantine[2] = 25
    executor.set_action(resolution((0, 0, 2, 0, 0)))
    first = run_day(sim, executor, 0)
    assert first.cost.delivered_notifications == 1
    assert sum(len(event.notifications) for event in executor.investigations) == 4
    assert sim.people.date_end_quarantine[2] == 25
    sim.people.date_diagnosed[1] = 1
    assert run_day(sim, executor, 1).cost.delivered_notifications == 1
    assert sim.people.date_end_quarantine[2] == 25


def test_future_notifications_deliver_after_c_downgrade_and_cancel_deceased(world, monkeypatch):
    sim, executor, definition = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    definition["actions"]["C"][2]["effective_parameters"]["notification_delay_days"]["community"] = 8
    links(sim, "cm", [0, 0], [1, 2])
    sim.people.date_diagnosed[0] = 0
    sim.people.date_recovered[0] = 30
    executor.set_action(resolution((0, 0, 2, 0, 0)))
    for day in range(7):
        assert run_day(sim, executor, day).cost.delivered_notifications == 0
    assert not sim.people.known_contact[1]
    sim.t = sim.people.t = 7
    executor.set_action(resolution((0, 0, 0, 0, 0)))
    assert run_day(sim, executor, 7).cost.delivered_notifications == 0
    sim.people.dead[2] = True
    record = run_day(sim, executor, 8)
    assert record.cost.delivered_notifications == 1
    assert executor.day_audits[-1].cancelled_notification_events == 1
    assert sim.people.date_end_quarantine[1] == 14
    assert sim.people.quarantined[1]
    assert not sim.people.known_contact[2]


def test_recovered_contacts_are_quarantined_and_invalid_isolation_is_cleared(world, monkeypatch):
    sim, executor, _ = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    links(sim, "d", [0], [1])
    sim.people.date_diagnosed[0] = 0
    sim.people.date_recovered[0] = 30
    sim.people.recovered[1] = sim.people.diagnosed[1] = True
    sim.people.isolated[1] = True
    sim.people.isolated[2] = sim.people.dead[2] = True
    executor.set_action(resolution((0, 0, 2, 0, 0)))
    record = run_day(sim, executor, 0)
    assert not sim.people.isolated[1] and not sim.people.isolated[2]
    assert sim.people.quarantined[1]
    assert sim.people.date_end_quarantine[1] == 14
    assert sim.people.flows["new_quarantined"] == 1
    assert (record.known_isolated, record.known_quarantined, record.known_union) == (1, 1, 2)


def test_activity_absolute_application_restoration_weights_and_union(world):
    sim, executor, _ = world
    executor.set_action(resolution((0, 0, 0, 1, 2)))
    sim.people.isolated[10] = sim.people.quarantined[10] = True
    sim.people.date_end_isolation[10] = sim.people.date_end_quarantine[10] = 30
    first = run_day(sim, executor, 0)
    second = run_day(sim, executor, 1)
    assert sim["beta_layer"]["clu"] == sim["beta_layer"]["of"] == .6
    assert sim["beta_layer"]["d"] == sim["beta_layer"]["ta"] == 1.2
    assert first.cost == second.cost
    assert first.cost.school_restriction_person_days == pytest.approx(2)
    assert first.cost.work_restriction_person_days == pytest.approx(2)
    assert first.cost.community_restriction_person_days == pytest.approx(2)
    assert (first.cost.isolation_person_days, first.cost.quarantine_person_days,
            first.cost.union_person_days) == (1, 1, 1)
    for day in range(2, 7):
        run_day(sim, executor, day)
    sim.t = sim.people.t = 7
    executor.set_action(resolution((0, 0, 0, 0, 0)))
    assert executor.action_duration_days == (7, 7, 7, 0, 0)
    assert run_day(sim, executor, 7).cost.school_restriction_person_days == 0
    assert all(value == 1.2 for value in sim["beta_layer"].values())


@pytest.mark.parametrize("education,activity,expected", [(2, 0, 420), (0, 2, 140)])
def test_configured_activity_budget_matches_prompt_execution_and_reward(tmp_path, education, activity, expected):
    from cemas.control.actions import legal_action_mask
    from cemas.control.ledger import PublicLedger
    from cemas.control.llm import build_public_messages
    from cemas.control.rewards import V1RewardCalculator
    from cemas.control.runner import make_public_prompt_config
    from cemas.control.types import ExecutedAction, PrivateMetrics, PublicObservation

    definition = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    definition["engine"].update(pop_size=100, pop_infected=0, execution_days=7, n_days=6)
    definition["activity"].update(daily_budget_school_or_work=.6, daily_budget_community=.4,
                                  dual_school_work_each=.3, neither_school_nor_work_community=1)
    path = tmp_path / "activity_protocol.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    protocol = load_protocol(path)
    sim = cv.Sim(pop_size=100, pop_infected=0, n_days=6, pop_type="random",
                 rand_seed=9102, verbose=0, rescale=False)
    sim.initialize()
    sim.people.age[:] = 20
    sim.people.class_groups_ug = [dict(students=np.arange(100), teachers=[])]
    sim.people.class_groups_gr = []
    sim.people.lab_groups = []
    sim.people.contacts = cv.Contacts(layer_keys=[name for group in LAYERS.values() for name in group])
    sim["beta_layer"] = {name: 1.2 for group in LAYERS.values() for name in group}
    executor = JointActionExecutor(protocol, PublicResources(0, 0, 0))
    executor.initialize(sim)
    observation = PublicObservation(
        0, 7, 0, executor.registry.public_population, executor.resources,
        executor.current_action, executor.action_duration_days,
        legal_action_mask(executor.resources, 100, protocol.definition["actions"]))
    messages = build_public_messages(observation, make_public_prompt_config(protocol))
    assert "只参加学校者：学校0.6、社区0.4" in messages[0].content
    executor.set_action(resolution((0, 0, 0, education, activity)))
    ledger = PublicLedger()
    for day in range(7):
        ledger.append(run_day(sim, executor, day))
    cost = ledger.aggregate_week(0, 6).cost
    assert (cost.school_restriction_person_days + cost.work_restriction_person_days
            + cost.community_restriction_person_days) == pytest.approx(expected)
    calculator = V1RewardCalculator(protocol, 100, 7)
    breakdown = calculator.breakdown(PrivateMetrics(0, 6, 0, 0, 0, 0, 0), cost,
                                     (ExecutedAction(0, 6, executor.current_action),))
    assert breakdown.normalized[-1] == pytest.approx(expected / 700)
    assert breakdown.reward == pytest.approx(-.25 * expected / 700)


def test_illegal_resolution_and_out_of_order_calls_raise_without_fallback(world):
    sim, executor, _ = world
    executor.set_resources(PublicResources(0, 0, 0))
    with pytest.raises(ValueError, match="resolve it first"):
        executor.set_action(resolution((0, 1, 0, 0, 0)))
    assert executor.current_action == ActionVector((0, 0, 0, 0, 0))
    record = run_day(sim, executor, 0)
    assert executor.finish_day(sim) is record
    with pytest.raises(RuntimeError, match="exactly once"):
        executor.apply(sim)
    sim.t = sim.people.t = 1
    with pytest.raises(ValueError, match="decision-day"):
        executor.set_resources(PublicResources(0, 12, 0))
    with pytest.raises(ValueError, match="decision-day"):
        executor.set_action(resolution((0, 0, 0, 0, 0)))


def test_reinitialize_clears_pending_events_audits_durations_and_restricted_base(world, monkeypatch):
    sim, executor, definition = world
    monkeypatch.setattr(np.random, "random", lambda n: np.zeros(n))
    definition["actions"]["C"][2]["effective_parameters"]["notification_delay_days"]["community"] = 8
    links(sim, "cm", [0], [1])
    sim.people.date_diagnosed[0] = 0
    sim.people.date_recovered[0] = 30
    executor.set_action(resolution((0, 0, 2, 2, 2)))
    run_day(sim, executor, 0)
    assert executor._pending_notifications and executor.day_audits
    executor.initialize(sim)
    assert not executor._pending_notifications and not executor.day_audits and not executor.investigations
    assert executor.action_duration_days == (0,) * 5
    assert executor.current_action == ActionVector((0, 0, 0, 0, 0))
    assert all(value == 1.2 for value in executor._base_beta.values())

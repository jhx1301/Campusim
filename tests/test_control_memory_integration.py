"""Phase 5 runner integration: public sinks, independent RNG and durable evidence."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from cemas.control.actions import encode_action, legal_action_mask
from cemas.control.controllers import MinimumController, UniformLegalController
from cemas.control.environment import WeeklyControlEnvironment
from cemas.control.llm import (LLMConfigurationError, LLMController, LLMResponse,
                               LLMTransport, OfficialInputTokenCounter)
from cemas.control.llm_memory import MemoryLLMController
from cemas.control.logging import RunLogger
from cemas.control.memory import PublicEpisodeMemory, public_task_hash
from cemas.control.memory_store import FrozenPublicCaseStore, PublicCaseBuilder, freeze_public_store
from cemas.control.memory_types import RetrievalResult, public_to_dict
from cemas.control.protocol import load_protocol
from cemas.control.runner import make_llm_settings, make_public_prompt_config, run_episode
from cemas.control.types import (
    ActionVector, PublicObservation, PublicPopulation, PublicResources, PublicWeekFeedback, PublicWeeklyRecord,
)


ROOT = Path(__file__).resolve().parents[1]
OPTIONS = {"population": 30, "execution_days": 9, "initial_infections": 1}


@pytest.fixture
def protocol():
    return load_protocol(ROOT / "docs/control_protocol_v1.json")


def _observation(protocol):
    population = PublicPopulation(100, (0, 100, 0, 0, 0), 50, 40, 10)
    resources = PublicResources(2, 5, 1)
    return PublicObservation(
        0, 112, 2, population, resources, ActionVector((0, 0, 0, 0, 0)),
        (0,) * 5, legal_action_mask(resources, 100, protocol.definition["actions"]),
    )


def _json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class FixtureCounter:
    """A fake count for control-flow checks; never a provider token estimate."""

    identity = {"adapter": "offline_integration_fixture", "accepted_for_live": False}

    def __init__(self):
        self.messages = []

    def validate(self, settings):
        pass

    def count_input(self, messages, settings):
        self.messages.append(messages)
        return 100

    def verify_response(self, response):
        pass


class AutomaticFixtureTransport:
    """Echo public schema/required flags; performs no API or model reasoning."""

    def __init__(self, invalid_first=0):
        self.invalid_first = invalid_first
        self.messages = []
        self.prepare_count = 0

    def prepare(self):
        self.prepare_count += 1

    def complete(self, messages):
        self.messages.append(messages)
        if len(self.messages) <= self.invalid_first:
            return LLMResponse("offline malformed JSON", model="offline-integration-fixture")
        user = json.loads(messages[1].content)
        text = json.dumps({
            "action": [0, 0, 0, 0, 0], "reason": "Offline public memory fixture",
            "evidence_ids": ["K:SIM-01"], "alternative_actions": [],
            "uncertainty_codes": user["required_uncertainty_codes"],
        })
        return LLMResponse(text, model="offline-integration-fixture", finish_reason="stop",
                           usage={"prompt_tokens": 100})


class EmptyFixtureRetriever:
    def __init__(self):
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        return RetrievalResult("empty")


def _controller(protocol, *, mode="none", invalid_first=0, store=None):
    transport = AutomaticFixtureTransport(invalid_first)
    counter, retriever, sleeps = FixtureCounter(), EmptyFixtureRetriever(), []
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED_OFFLINE_FIXTURE")
    controller = MemoryLLMController(
        transport, make_public_prompt_config(protocol), settings, counter,
        memory_mode=mode, retriever=retriever if mode in ("global", "both") else None, store=store,
        sleeper=sleeps.append,
    )
    return controller, transport, counter, retriever, sleeps


def _fixture_store(protocol, directory, *, horizon=9):
    initial = replace(_observation(protocol), execution_days=horizon)
    memory = PublicEpisodeMemory()
    memory.stage(initial)
    first = PublicWeeklyRecord(0, min(6, horizon - 1), resources=initial.resources)
    revisions = list(memory.accept(PublicWeekFeedback(first)))
    if horizon > 7:
        current = replace(initial, decision_day=7,
                          history=(PublicWeeklyRecord(),) * 3 + (first,),
                          week_valid=(False,) * 3 + (True,))
        memory.stage(current)
        tail = PublicWeeklyRecord(7, horizon - 1, resources=initial.resources)
        revisions.extend(memory.accept(PublicWeekFeedback(tail, first)))
    task_hash = public_task_hash(make_public_prompt_config(protocol), horizon)
    builder = PublicCaseBuilder(directory / "staging", task_hash)
    builder.append(tuple(revisions), {"trajectory_id": "offline-integration-fixture"})
    report = builder.finalize("completed")
    manifest = freeze_public_store(directory / "staging", report.private_manifest_path, directory / "frozen")
    return FrozenPublicCaseStore.open(directory / "frozen", manifest)

def test_uniform_legal_controller_owns_rng_and_reset_replays_without_touching_world_rng(protocol):
    original = _observation(protocol)
    legal_ids = {0, 8, 80, 242}
    observation = replace(original, legal_action_mask=tuple(index in legal_ids for index in range(324)))
    np.random.seed(9381)
    before = np.random.get_state()
    first, second = UniformLegalController(17), UniformLegalController(17)
    actions1 = [encode_action(first.decide(observation).action) for _ in range(50)]
    np.random.seed(4567)  # A world/global RNG change must not affect the policy-local stream.
    actions2 = [encode_action(second.decide(observation).action) for _ in range(50)]
    assert actions1 == actions2 and set(actions1).issubset(legal_ids)
    first.reset()
    np.random.set_state(before)
    actions3 = [encode_action(first.decide(observation).action) for _ in range(50)]
    after = np.random.get_state()
    assert actions3 == actions1
    assert before[0] == after[0] and np.array_equal(before[1], after[1])
    assert before[2:] == after[2:]
    with pytest.raises(TypeError):
        first.decide(public_to_dict(observation))
    with pytest.raises(ValueError):
        UniformLegalController(True)


def test_runner_public_sink_receives_exact_two_public_types_and_terminal_tail(protocol, tmp_path):
    transitions, revisions = [], []
    memory = PublicEpisodeMemory()

    def sink(public_observation, public_feedback, /):
        assert type(public_observation) is PublicObservation
        assert type(public_feedback) is PublicWeekFeedback
        public = public_to_dict({"observation": public_observation, "feedback": public_feedback})
        encoded = json.dumps(public)
        assert not any(key in encoded for key in ("world_seed", "reward", "private_metrics", "beta", "new_infections"))
        memory.stage(public_observation)
        revisions.extend(memory.accept(public_feedback))
        transitions.append((public_observation.decision_day, public_feedback.week.end_day))

    result = run_episode(protocol, MinimumController(), tmp_path / "public-sink", 90001,
                         scenario_options=OPTIONS, public_transition_sink=sink)
    assert result.status == "completed"
    assert transitions == [(0, 6), (7, 8)]
    assert len(revisions) == 3 and revisions[-1].status == "terminal_censored"
    assert revisions[-1].window_days == 2 and revisions[-2].followup_window.end_day == 8


def test_sink_failure_preserves_executed_window_and_stops_next_decision(protocol, tmp_path):
    class CountingMinimum(MinimumController):
        def __init__(self):
            self.days = []

        def decide(self, observation):
            self.days.append(observation.decision_day)
            return super().decide(observation)

    controller = CountingMinimum()
    completed = []

    def failed_sink(observation, feedback):
        completed.append(feedback.week)
        raise OSError("public export disk fixture")

    output = tmp_path / "sink-failed"
    with pytest.raises(OSError, match="public export disk fixture"):
        run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS,
                    public_transition_sink=failed_sink)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["elapsed_days"] == 7
    assert controller.days == [0] and [week.end_day for week in completed] == [6]
    assert len((output / "public_daily.csv").read_text(encoding="utf-8").splitlines()) == 8


@pytest.mark.parametrize("mode", ["none", "short", "global", "both"])
def test_four_memory_modes_complete_offline_with_evidence_and_terminal_revisions(protocol, tmp_path, mode):
    store = _fixture_store(protocol, tmp_path / "fixture-store") if mode in ("global", "both") else None
    controller, transport, counter, retriever, sleeps = _controller(protocol, mode=mode, store=store)
    output = tmp_path / mode
    result = run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS)
    assert result.status == "completed" and len(transport.messages) == len(counter.messages) == 2
    assert sleeps == []
    evidence = _json_lines(output / "decision_evidence.jsonl")
    prepared = [item for item in evidence if item["event"] == "prepared"]
    resolved = [item for item in evidence if item["event"] == "resolved"]
    assert [item["decision_day"] for item in prepared] == [0, 7]
    assert [item["decision_day"] for item in resolved] == [0, 7]
    assert all(item["memory_mode"] == mode and item["status"] == "success" for item in prepared)
    assert {item["context_hash"] for item in prepared} == {item["context_hash"] for item in resolved}
    decisions = _json_lines(output / "decisions.jsonl")
    assert all(item["retrieved_case_ids"] == [] for item in decisions)
    revisions = _json_lines(output / "memory_revisions.jsonl")
    assert [item["revision"] for item in revisions] == [1, 2, 1]
    assert revisions[-1]["executed_window"]["end_day"] == 8
    assert revisions[-1]["status"] == "terminal_censored"
    for messages in transport.messages:
        user = json.loads(messages[1].content)
        assert (user["memory"]["recent"] is not None) == (mode in ("short", "both"))
        if mode in ("none", "short"):
            assert user["memory"]["retrieval"]["flags"] == ["disabled"]
        else:
            assert "no_case" in user["required_uncertainty_codes"]
    assert len(retriever.queries) == (2 if mode in ("global", "both") else 0)
    if store is not None:
        store.close()


def test_actual_call_and_prepared_evidence_are_durable_before_each_environment_step(protocol, tmp_path, monkeypatch):
    controller, transport, *_ = _controller(protocol)
    output, days = tmp_path / "evidence-order", []
    original_step = WeeklyControlEnvironment.step_proposal

    def checked_step(self, proposal, **kwargs):
        records = _json_lines(output / "decision_evidence.jsonl")
        prepared = [item for item in records if item["event"] == "prepared"]
        calls = _json_lines(output / "llm_calls.jsonl")
        assert len(prepared) == len(days) + 1 and len(calls) == len(days) + 1
        assert prepared[-1]["decision_day"] == len(days) * 7
        days.append(prepared[-1]["decision_day"])
        return original_step(self, proposal, **kwargs)

    monkeypatch.setattr(WeeklyControlEnvironment, "step_proposal", checked_step)
    run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS)
    assert days == [0, 7] and len(transport.messages) == 2


def test_evidence_write_failure_prevents_world_advance_and_retains_actual_call(protocol, tmp_path, monkeypatch):
    controller, *_ = _controller(protocol)
    output, advances = tmp_path / "evidence-write-failure", []

    def failed_write(self, evidence):
        raise OSError("prepared evidence disk fixture")

    def forbidden_step(*args, **kwargs):
        advances.append(True)
        raise AssertionError("world advanced without durable evidence")

    monkeypatch.setattr(RunLogger, "write_decision_evidence", failed_write)
    monkeypatch.setattr(WeeklyControlEnvironment, "step_proposal", forbidden_step)
    with pytest.raises(OSError, match="prepared evidence disk fixture"):
        run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS)
    assert advances == []
    assert len(_json_lines(output / "llm_calls.jsonl")) == 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["elapsed_days"] == 0


def test_fatal_decision_and_secondary_evidence_failure_keep_primary_error_sanitized(protocol, tmp_path, monkeypatch):
    controller, *_ = _controller(protocol)
    output = tmp_path / "compound-failure"

    def fatal_decide(observation):
        raise LLMConfigurationError("fixture_fatal", "Safe primary fixture failure")

    def failed_write(self, evidence):
        raise OSError("secret-secondary-payload")

    monkeypatch.setattr(controller, "decide", fatal_decide)
    monkeypatch.setattr(RunLogger, "write_decision_evidence", failed_write)
    with pytest.raises(LLMConfigurationError, match="Safe primary") as caught:
        run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS)
    assert caught.value.code == "fixture_fatal"
    failure_text = (output / "failure.json").read_text(encoding="utf-8")
    failure = json.loads(failure_text)
    assert failure["details"]["error_code"] == "fixture_fatal"
    assert failure["details"]["call_audit_error"]["error_type"] == "OSError"
    assert "secret-secondary-payload" not in failure_text


def test_memory_controller_inherits_one_retry_loop_with_same_bytes_and_public_fallback_cases(protocol, tmp_path):
    controller, transport, counter, _, sleeps = _controller(protocol, invalid_first=3)
    assert MemoryLLMController.decide is LLMController.decide
    output = tmp_path / "shared-exhaustion"
    run_episode(protocol, controller, output, 90002, scenario_options=OPTIONS)
    assert len(transport.messages) == 4 and transport.messages[0] == transport.messages[1] == transport.messages[2]
    assert len(counter.messages) == 2 and sleeps == [2, 4]
    evidence = [item for item in _json_lines(output / "decision_evidence.jsonl") if item["event"] == "prepared"]
    assert evidence[0]["status"] == "retry_exhausted" and evidence[0]["attempt_count"] == 3
    assert evidence[0]["reason"] is None
    assert evidence[1]["status"] == "success"
    decisions = _json_lines(output / "decisions.jsonl")
    assert decisions[0]["fallback_reason"] == "llm_retry_exhausted"
    cases = _json_lines(output / "memory_revisions.jsonl")
    assert cases[0]["executed_window"]["executed_action"] == decisions[0]["executed_action"]
    assert not any(name in json.dumps(cases) for name in ("private_metrics", "world_seed", "reward"))


@pytest.mark.parametrize("seed", [20001, 20101, 40001, 50001, 90001])
def test_collection_rejects_non_source_pools_before_creating_output(protocol, tmp_path, seed):
    output = tmp_path / str(seed)
    with pytest.raises(ValueError, match="seeds"):
        run_episode(protocol, MinimumController(), output, seed, purpose="memory_collection")
    assert not output.exists()



def test_integrated_global_mode_refuses_unverified_store_before_environment_creation(protocol, tmp_path):
    controller, *_ = _controller(protocol, mode="global", store=object())
    output = tmp_path / "unverified-store"
    with pytest.raises(LLMConfigurationError) as caught:
        run_episode(protocol, controller, output, 90001, scenario_options=OPTIONS)
    assert caught.value.code == "invalid_case_store"
    assert not output.exists()


def test_live_prompt_development_refuses_fixture_store_even_when_read_only(protocol, tmp_path):
    store = _fixture_store(protocol, tmp_path / "fixture-library")
    try:
        controller, *_ = _controller(protocol, mode="both", store=store)
        controller.transport = LLMTransport(controller.settings, client=object())
        output = tmp_path / "fixture-live"
        with pytest.raises(LLMConfigurationError) as caught:
            run_episode(protocol, controller, output, 40001, purpose="prompt_development", scenario_options=OPTIONS)
        assert caught.value.code == "fixture_store_forbidden"
        assert not output.exists()
    finally:
        store.close()


def test_live_memory_requires_extra_receipt_before_environment_or_paid_call(protocol, tmp_path, monkeypatch):
    controller, *_ = _controller(protocol)
    controller.transport = LLMTransport(controller.settings, client=object())
    # Isolate only the extra P5 gate; this is not an accepted production counter.
    controller.token_counter = object.__new__(OfficialInputTokenCounter)
    monkeypatch.setattr(OfficialInputTokenCounter, "validate", lambda self, settings: None)
    output = tmp_path / "missing-p5-receipt"
    with pytest.raises(LLMConfigurationError) as caught:
        run_episode(protocol, controller, output, 40001, purpose="prompt_development", scenario_options=OPTIONS)
    assert caught.value.code == "memory_not_accepted"
    assert not output.exists()

"""Actual retry messages, counting and audit stay aligned without paid calls."""

import json
from dataclasses import replace

import pytest

from cemas.control.feedback import project_feedback
from cemas.control.llm import LLMController, LLMResponse, LLMServiceError, PromptBudgetError
from cemas.control.llm_feedback import LLMFeedback
from cemas.control.llm_memory import MemoryLLMController
from cemas.control.logging import snapshot_sha256
from cemas.control.runner import run_episode
from test_control_feedback import library
from test_control_llm_memory import Counter, Transport, config, day0, successful_response


def request_tokens(messages):
    return 100 + (len(messages[-1].content) if len(messages) > 2 else 0)


def ordinary_response(value):
    def render(messages):
        return LLMResponse(json.dumps(value), usage={"prompt_tokens": request_tokens(messages)})
    return render


def test_reason_length_target_does_not_gate_controller_configuration(config, day0):
    _, prompt, settings = config
    transport = Transport([ordinary_response({"action": [0] * 5, "reason": "A concise valid explanation"})])
    policy = LLMController(transport, replace(prompt, reason_max_chars=1), settings,
                           Counter(request_tokens), sleeper=lambda _: None)
    assert policy.decide(day0).reasoning == "A concise valid explanation"


def test_new_validation_error_replaces_previous_correction_and_recounts(config, day0):
    _, prompt, settings = config
    waits = []
    transport = Transport([ordinary_response({"action": [0] * 5}),
                           ordinary_response({"action": [0] * 5, "reason": {"text": "wrong shape"}}),
                           ordinary_response({"action": [0] * 5, "reason": "Valid response"})])
    counter = Counter(request_tokens)
    policy = LLMController(transport, prompt, settings, counter, sleeper=waits.append)
    assert policy.decide(day0) is not None
    first, second, third = transport.messages
    assert len(first) == 2 and len(second) == len(third) == 3
    assert second[:-1] == third[:-1] == first
    assert json.loads(second[-1].content)["validation_error"]["code"] == "invalid_fields"
    latest = json.loads(third[-1].content)["validation_error"]
    assert latest["code"] == "invalid_reason" and latest["path"] == "/reason"
    assert latest["actual"] == "dict" and "wrong shape" not in third[-1].content
    assert len(counter.counted) == 3 and waits == [2, 4]
    audits = policy.drain_call_audits()
    assert [record.input_tokens for record in audits] == [request_tokens(m) for m in transport.messages]
    assert [record.messages_sha256 for record in audits] == [snapshot_sha256(m) for m in transport.messages]
    assert audits[0].validation_error["code"] == "invalid_fields"
    assert audits[1].validation_error == latest and audits[2].validation_error is None
    assert all(record.input_tokens == record.response.usage["prompt_tokens"] for record in audits)


def test_connection_retry_reuses_current_corrected_messages(config, day0):
    _, prompt, settings = config
    transport = Transport([ordinary_response({"action": [0] * 5}),
                           LLMServiceError("temporary_connection", "Temporary connection failure"),
                           ordinary_response({"action": [0] * 5, "reason": "Valid"})])
    counter = Counter(request_tokens)
    policy = LLMController(transport, prompt, settings, counter, sleeper=lambda _: None)
    assert policy.decide(day0) is not None
    assert len(counter.counted) == 2
    assert transport.messages[1] is transport.messages[2]
    audits = policy.drain_call_audits()
    assert audits[1].validation_error is None and audits[1].response is None
    assert audits[1].input_tokens == audits[2].input_tokens


def test_correction_does_not_authorize_unknown_references_and_final_audit_is_actual(config, day0):
    _, prompt, settings = config
    bad = lambda messages: successful_response(messages, evidence_ids=["C:999"])
    transport = Transport([bad, bad, successful_response])
    counter = Counter(request_tokens)
    policy = MemoryLLMController(transport, prompt, settings, counter,
                                 memory_mode="short", sleeper=lambda _: None)
    assert policy.decide(day0) is not None
    audits = policy.drain_call_audits()
    assert [record.error_code for record in audits] == ["unknown_evidence_id", "unknown_evidence_id", None]
    assert transport.messages[1] is transport.messages[2]
    assert len(counter.counted) == 2
    evidence, = policy.drain_decision_evidence()
    assert "C:999" not in evidence["registry"]
    assert evidence["attempt_count"] == 3
    assert evidence["messages_sha256"] == audits[-1].messages_sha256 != audits[0].messages_sha256
    assert evidence["input_tokens"] == audits[-1].input_tokens > audits[0].input_tokens
    assert evidence["context_hash"] == policy._prepared_context.context_hash
    assert evidence["registry"] == tuple(policy._prepared_context.registry)


@pytest.mark.parametrize("memory", [False, True])
def test_correction_over_budget_makes_no_second_provider_call(config, day0, memory):
    _, prompt, settings = config
    bad = (lambda messages: successful_response(messages, reason={"text": "object"})) if memory else ordinary_response({"action": [0] * 5})
    transport = Transport([bad])
    counter = Counter(lambda messages: settings.input_token_budget + 1 if len(messages) == 3 else 100)
    cls = MemoryLLMController if memory else LLMController
    policy = cls(transport, prompt, settings, counter, sleeper=lambda _: None)
    with pytest.raises(PromptBudgetError) as caught:
        policy.decide(day0)
    assert len(transport.messages) == 1 and len(policy.drain_call_audits()) == 1
    assert caught.value.details["stage"] == "retry_preflight"
    assert caught.value.details["input_tokens"] == settings.input_token_budget + 1
    assert caught.value.details["messages_sha256"] == snapshot_sha256(counter.counted[-1])


def test_auxiliary_correction_budget_failure_retains_call_and_preflight_audit(config):
    _, prompt, settings = config
    events = []
    transport = Transport([LLMResponse("{}")])
    counter = Counter(lambda messages: settings.input_token_budget + 1 if len(messages) == 3 else 100)
    feedback = LLMFeedback(transport, counter, settings, prompt, events,
                           sleeper=lambda _: None, clock=lambda: 0.)
    with pytest.raises(PromptBudgetError):
        feedback.generate({"as_of_day": 14, "weeks": [], "facts": {}})
    assert len(transport.messages) == 1
    assert [event["event"] for event in events] == ["provider_call", "preflight_error"]
    assert events[1]["details"]["input_tokens"] == settings.input_token_budget + 1
    assert events[1]["messages_sha256"] == snapshot_sha256(counter.counted[-1])


def test_auxiliary_wrong_applicability_corrects_against_original_packet(config, library):
    _, prompt, settings = config
    store, _, _ = library
    packet = project_feedback(store.cases(), 35, store.public_task_sha256, group_for=store.group_for)
    identity = next(week["window_id"] for week in packet["weeks"] if week["role"] == "autonomous")
    fact = next(iter(packet["facts"]))
    item = {"window_id": identity, "status": "candidate",
            "finding": {"text": "Public change", "evidence_ids": [fact]},
            "decision_check": {"text": "Check next week", "evidence_ids": [fact]},
            "applicability": {"text": "Wrong object"}, "limitations": ["Not causal"]}
    bad = {"schema_version": "cemas-public-feedback-result-v2", "items": [item]}
    good = {"schema_version": "cemas-public-feedback-result-v2", "items": [
        {"window_id": identity, "status": "abstain", "reason_code": "no_new_insight"}]}
    transport = Transport([ordinary_response(bad), ordinary_response(good)])
    events = []
    feedback = LLMFeedback(transport, Counter(request_tokens), settings, prompt, events,
                           sleeper=lambda _: None, clock=lambda: 0.)
    assert feedback.generate(packet) == good
    correction = json.loads(transport.messages[1][-1].content)["validation_error"]
    assert correction["path"] == "/items/0/applicability" and correction["actual"] == "dict"
    assert transport.messages[1][:-1] == transport.messages[0]
    assert len(events) == 3 and events[-1]["status"] == "generated"


@pytest.mark.parametrize("memory", [False, True])
def test_long_reason_runs_and_is_logged_without_truncation(config, tmp_path, memory):
    protocol, prompt, settings = config
    reason = "A public descriptive explanation. " * 20
    render = ((lambda messages: successful_response(messages, reason=reason)) if memory else
              (lambda messages: LLMResponse(json.dumps({"action": [0] * 5, "reason": reason}))))
    cls = MemoryLLMController if memory else LLMController
    policy = cls(Transport([render]), prompt, settings, Counter(), sleeper=lambda _: None)
    result = run_episode(protocol, policy, tmp_path / "run", 90001,
        scenario_options={"population": 30, "initial_infections": 1, "execution_days": 14})
    decisions = [json.loads(line) for line in (result.output_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[-1]["reasoning"] == reason
    assert decisions[-1]["llm_attempt_count"] == 1
    assert result.summary["status"] == "completed"

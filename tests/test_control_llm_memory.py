"""Offline five-field decisions, shared retries, exact references and trimming."""

from dataclasses import replace
import json
from math import log2
from pathlib import Path

import pytest

from cemas.control import (ActionResponseError, LLMConfigurationError, LLMResponse, LLMServiceError,
                           PromptBudgetError, legal_action_mask, load_protocol,
                           make_llm_settings, make_public_prompt_config)
from cemas.control.knowledge import CORE_IDS
from cemas.control.llm import build_public_messages
from cemas.control.llm_memory import (MEMORY_MODES, MemoryLLMController, build_memory_messages,
                                      memory_prompt_config, parse_memory_response)
from cemas.control.logging import resolved_snapshot, snapshot_sha256
from cemas.control.memory import public_task_hash
from tools.memory_acceptance import (MEMORY_PROBE_MODES, accept_memory_llm,
                                     validate_memory_acceptance)
from cemas.control.memory_types import (CASE_SCHEMA_VERSION, PublicCase,
                                        RetrievalItem, RetrievalResult, observation_from_dict,
                                        public_hash, public_to_dict, weekly_record_from_dict)
from cemas.control.types import (ActionVector, PublicCost, PublicObservation, PublicPopulation,
                                 PublicResources, PublicWeekFeedback, PublicWeeklyRecord)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    protocol = load_protocol(ROOT / "docs/control_protocol_v1.json")
    return protocol, make_public_prompt_config(protocol), make_llm_settings(protocol, endpoint="https://provider.invalid/v1", api_key_env="CEMAS_OFFLINE_TEST_KEY")


@pytest.fixture
def day0(config):
    protocol, _, _ = config
    resources = PublicResources(2, 5, 1)
    return PublicObservation(0, 112, 2, PublicPopulation(100, (0, 100, 0, 0, 0), 50, 40),
                             resources, ActionVector((0,) * 5), (0,) * 5,
                             legal_action_mask(resources, 100, protocol.definition["actions"]))


@pytest.fixture
def observation(day0):
    tests, diagnoses = (80, 90, 100, 150), (3, 4, 5, 6)
    weeks = tuple(PublicWeeklyRecord(i * 7, i * 7 + 6, count,
                                     PublicCost(clinical_tests=tests[i], delivered_notifications=i),
                                     resources=day0.resources,
                                     growth=log2((count + 1) / (diagnoses[i - 1] + 1)) if i else 0,
                                     growth_valid=bool(i), diagnosis_test_proxy=count / tests[i], proxy_valid=True)
                  for i, count in enumerate(diagnoses))
    return replace(day0, decision_day=28, history=weeks, week_valid=(True,) * 4,
                   action_duration_days=(28,) * 5)


class Counter:
    identity = {"adapter": "offline_test_stub", "accepted_for_live": False}

    def __init__(self, count=100):
        self.count, self.counted, self.validations = count, [], 0

    def validate(self, settings):
        self.validations += 1

    def count_input(self, messages, settings):
        self.counted.append(messages)
        return self.count(messages) if callable(self.count) else self.count

    def verify_response(self, response):
        pass


def successful_response(messages, **updates):
    payload = json.loads(messages[1].content)
    value = {"action": [0] * 5, "reason": "??????????", "evidence_ids": ["O:/decision_day"],
             "alternative_actions": [], "uncertainty_codes": payload["required_uncertainty_codes"]}
    value.update(updates)
    return LLMResponse(json.dumps(value, ensure_ascii=False), model="offline-model", response_id="offline-response")


class Transport:
    def __init__(self, outcomes=()):
        self.outcomes, self.messages, self.prepared = list(outcomes), [], 0

    def prepare(self):
        self.prepared += 1

    def complete(self, messages):
        self.messages.append(messages)
        value = self.outcomes.pop(0) if self.outcomes else successful_response
        if isinstance(value, BaseException):
            raise value
        return value(messages) if callable(value) else value


class Retriever:
    def __init__(self, result):
        self.result, self.queries = result, []

    def retrieve(self, query):
        self.queries.append(query)
        return self.result


def controller(config, *, mode="none", counter=None, transport=None, retriever=None, **kwargs):
    _, prompt, settings = config
    return MemoryLLMController(transport or Transport(), prompt, settings, counter or Counter(),
                               memory_mode=mode, retriever=retriever, sleeper=kwargs.pop("sleeper", lambda _: None), **kwargs)


def make_case(pre, prompt, identity, diagnoses, *, followup=True):
    week = PublicWeeklyRecord(pre.decision_day, pre.decision_day + 6, diagnoses,
                              PublicCost(clinical_tests=7), resources=pre.resources)
    later = replace(week, start_day=week.end_day + 1, end_day=week.end_day + 7) if followup else None
    return PublicCase(identity, 2 if later else 1, CASE_SCHEMA_VERSION,
                       public_task_hash(prompt, pre.execution_days), pre, week, 7, later,
                       "closed_two" if later else "closed_one", (later or week).end_day,
                       "descriptive_not_causal", () if later else ("truncated_followup",),
                       "?????????????",
                       {"kind": "source_simulation", "observation_sha256": public_hash(pre),
                        "feedback_sha256": public_hash(week), "followup_sha256": public_hash(later) if later else None})


def retrieval_result(observation, prompt):
    cases = (make_case(observation, prompt, 101, 1), make_case(observation, prompt, 207, 11),
             make_case(observation, prompt, 309, 5, followup=False))
    items = tuple(RetrievalItem(case, 0, 1, 1, 1 - index * .01,
                                ("conflict_pair",) if index < 2 else ()) for index, case in enumerate(cases))
    return RetrievalResult("ok", items, ("case_conflict",))


def test_four_modes_share_system_knowledge_rates_and_raw_history(config, observation):
    results = {}
    for mode in MEMORY_MODES:
        policy = controller(config, mode=mode, retriever=Retriever(RetrievalResult("empty")))
        policy.decide(observation)
        messages = policy.transport.messages[0]
        results[mode] = (messages, json.loads(messages[1].content))
    systems = {messages[0].content for messages, _ in results.values()}
    assert len(systems) == 1
    knowledge = [payload["memory"]["knowledge"] for _, payload in results.values()]
    assert all(value == knowledge[0] for value in knowledge)
    p4 = json.loads(build_public_messages(observation, config[1])[1].content)
    for mode, (_, payload) in results.items():
        assert set(payload) == {"observation", "public_rates", "memory", "evidence_registry", "required_uncertainty_codes"}
        assert payload["observation"] == p4["observation"] and payload["public_rates"] == p4["public_rates"]
        assert (payload["memory"]["recent"] is None) == (mode in ("none", "global"))
        assert any(identity.startswith("R:") for identity in payload["evidence_registry"]) == (mode in ("short", "both"))
        assert ("no_case" in payload["required_uncertainty_codes"]) == (mode in ("global", "both"))
        if mode in ("none", "short"):
            assert payload["memory"]["retrieval"]["flags"] == ["disabled"]
    assert results["none"][1]["required_uncertainty_codes"] == ["partial_observability", "testing_changed"]


def test_no_global_modes_never_query_supplied_retriever(config, day0):
    class NoQuery:
        def retrieve(self, query):
            raise AssertionError("disabled mode queried global cases")
    for mode in ("none", "short"):
        policy = controller(config, mode=mode, retriever=NoQuery())
        assert policy.decide(day0).action.values == (0,) * 5
        assert policy.store is None


def test_global_modes_require_store_or_explicit_public_retriever(config):
    for mode in ("global", "both"):
        with pytest.raises(LLMConfigurationError) as caught:
            controller(config, mode=mode)
        assert caught.value.code == "missing_case_store"


def test_registry_refuses_invalid_history_growth_and_proxy(config, day0, observation):
    policy = controller(config)
    policy.decide(day0)
    payload = json.loads(policy.transport.messages[0][1].content)
    assert not any(identity.startswith("O:/history/") for identity in payload["evidence_registry"])
    assert payload["required_uncertainty_codes"] == ["partial_observability", "no_history"]
    policy.reset()
    policy.decide(observation)
    registry = policy._prepared_context.registry
    assert "O:/history/0/growth" not in registry
    assert registry["O:/history/0/diagnosis_test_proxy"] == 3 / 80
    assert registry["O:/history/3/cost"]["clinical_tests"] == 150
    with pytest.raises(TypeError):
        registry["O:/decision_day"] = 10


def test_only_public_projection_changes_messages(config, observation):
    protocol, prompt, settings = config
    data = resolved_snapshot(protocol.definition)
    data["engine"]["smoke_beta"] = .023
    data["engine"]["pop_infected"] = 90
    data["private_metrics"] = {"reward": 99, "world_seed": 30001}
    private_prompt = make_public_prompt_config(replace(protocol, definition=data))
    first = MemoryLLMController(Transport(), prompt, settings, Counter(), memory_mode="short", sleeper=lambda _: None)
    second = MemoryLLMController(Transport(), private_prompt, settings, Counter(), memory_mode="short", sleeper=lambda _: None)
    first.decide(observation)
    second.decide(observation)
    assert first.transport.messages == second.transport.messages
    assert first._prepared_context.context_hash == second._prepared_context.context_hash
    with pytest.raises(TypeError):
        first.decide(public_to_dict(observation))


def wire(**changes):
    value = {"action": [0] * 5, "reason": "????", "evidence_ids": ["O:/decision_day"],
             "alternative_actions": [], "uncertainty_codes": ["partial_observability"]}
    value.update(changes)
    return json.dumps(value)


def parse(raw, **kwargs):
    return parse_memory_response(raw, registry={"O:/decision_day": 28, "K:SIM-01": {}},
                                  required_uncertainty_codes=("partial_observability",), **kwargs)


@pytest.mark.parametrize("change", [
    {"action": [True, 0, 0, 0, 0]}, {"action": [0., 0, 0, 0, 0]}, {"action": [3, 0, 0, 0, 0]},
    {"action": [0] * 4}, {"reason": " "}, {"reason": "a\nb"}, {"reason": "a" * 121},
    {"evidence_ids": []}, {"evidence_ids": ["O:/history/0/growth"]},
    {"evidence_ids": ["O:/decision_day"] * 2}, {"evidence_ids": ["C:999"]},
    {"evidence_ids": [1]}, {"uncertainty_codes": []}, {"uncertainty_codes": ["no_history"]},
    {"uncertainty_codes": ["partial_observability", "knowledge_conflict"]},
    {"uncertainty_codes": ["partial_observability"] * 2}, {"alternative_actions": None},
    {"alternative_actions": [{"action": [0] * 5, "tradeoff": "different", "evidence_ids": ["K:SIM-01"]}]},
    {"alternative_actions": [{"action": [1] * 5, "tradeoff": "a" * 81, "evidence_ids": ["K:SIM-01"]}]},
    {"alternative_actions": [{"action": [1] * 5, "tradeoff": "ok", "evidence_ids": ["C:999"]}]},
    {"alternative_actions": [{"action": [1] * 5, "tradeoff": "ok", "evidence_ids": ["K:SIM-01"], "score": 1}]},
    {"private_reward": 1},
])
def test_strict_five_field_wire_rejects_without_repair(change):
    with pytest.raises(ActionResponseError):
        parse(wire(**change))


@pytest.mark.parametrize("raw", ["null", "[]", "```json\n{}\n```", "prefix {}",
                                  '{"action":[0,0,0,0,0],"reason":"ok","reason":"again"}',
                                  wire().replace('"action": [0', '"action": [NaN'),
                                  wire().replace('"action": [0', '"action": [Infinity')])
def test_wire_rejects_non_json_and_ambiguous_json(raw):
    with pytest.raises(ActionResponseError):
        parse(raw)


def test_feasibility_is_recorded_for_alternative_and_main_reaches_common_resolver(day0):
    alternative = {"action": [0, 3, 0, 0, 0], "tradeoff": "??????", "evidence_ids": ["K:SIM-01"]}
    result = parse(wire(action=[0, 3, 0, 0, 0], alternative_actions=[dict(alternative, action=[1, 3, 0, 0, 0])]),
                   legal_action_mask=day0.legal_action_mask)
    assert result.proposal.action.values == (0, 3, 0, 0, 0)
    assert result.alternative_actions[0]["feasible"] is False


def test_duplicates_or_too_many_alternatives_fail():
    alternative = {"action": [1, 0, 0, 0, 0], "tradeoff": "??", "evidence_ids": ["K:SIM-01"]}
    for alternatives in ([alternative, alternative], [alternative] * 3):
        with pytest.raises(ActionResponseError):
            parse(wire(alternative_actions=alternatives))


def test_same_final_messages_single_retrieval_and_count_across_three_attempts(config, observation):
    counter, delays = Counter(), []
    retriever = Retriever(RetrievalResult("empty"))
    transport = Transport([LLMServiceError("timeout", "Temporary failure"),
                           LLMResponse(wire(evidence_ids=["C:999"])), successful_response])
    policy = controller(config, mode="both", counter=counter, transport=transport, retriever=retriever, sleeper=delays.append)
    proposal = policy.decide(observation)
    assert proposal is not None and delays == [2, 4]
    assert len(counter.counted) == 1 and len(retriever.queries) == 1 and counter.validations == 1
    assert transport.messages[0] is transport.messages[1] is transport.messages[2]
    audits = policy.drain_call_audits()
    assert [audit.error_code for audit in audits] == ["timeout", "unknown_evidence_id", None]
    evidence = policy.drain_decision_evidence()
    assert len(evidence) == 1 and evidence[0]["attempt_count"] == 3 and evidence[0]["status"] == "success"
    assert policy.drain_decision_evidence() == ()


def test_exhaustion_has_program_context_without_fabricated_model_reason(config, day0):
    transport = Transport([LLMServiceError("timeout", "Temporary failure")] * 3)
    policy = controller(config, transport=transport)
    assert policy.decide(day0) is None
    assert policy.consume_failure_reason() == "llm_retry_exhausted"
    evidence, = policy.drain_decision_evidence()
    assert evidence["status"] == "retry_exhausted" and evidence["reason"] is None
    assert evidence["cited_case_ids"] == () and evidence["cited_evidence"] == {}
    actual = PublicWeeklyRecord(0, 6, resources=day0.resources, executed_action=day0.current_action)
    policy.observe(PublicWeekFeedback(actual))
    revision, = policy.drain_case_revisions()
    assert revision.executed_window.executed_action == day0.current_action


def test_truncated_completion_retries_same_input(config, day0):
    policy = controller(config, transport=Transport([LLMResponse(wire(), finish_reason="length"), successful_response]))
    assert policy.decide(day0) is not None
    audits = policy.drain_call_audits()
    assert [audit.error_code for audit in audits] == ["truncated_content", None]
    assert len(policy.token_counter.counted) == 1


def test_exact_budget_trims_complete_cases_pair_then_external_then_recent(config, observation):
    _, prompt, settings = config
    result = retrieval_result(observation, prompt)
    def volume(messages):
        memory = json.loads(messages[1].content)["memory"]
        return 100 + 20 * len(memory["retrieval"]["items"]) + 10 * sum(card["id"].startswith("PH-") for card in memory["knowledge"]) + 10 * (memory["recent"] is not None)
    counter = Counter(volume)
    policy = MemoryLLMController(Transport(), prompt, replace(settings, input_token_budget=100), counter,
                                 memory_mode="both", retriever=Retriever(result), sleeper=lambda _: None)
    assert policy.decide(observation) is not None
    evidence, = policy.drain_decision_evidence()
    assert [event["kind"] for event in evidence["trim_events"]] == ["cases", "cases", "knowledge", "knowledge", "knowledge", "recent"]
    assert evidence["trim_events"][0]["ids"] == (309,)
    assert evidence["trim_events"][1]["ids"] == (101, 207)
    assert evidence["dropped_case_ids"] == (309, 101, 207) and evidence["selected_case_ids"] == ()
    assert set(evidence["knowledge_ids"]) == set(CORE_IDS)
    assert "no_case" in evidence["required_uncertainty_codes"]
    assert "case_conflict" not in evidence["required_uncertainty_codes"] and "truncated_followup" not in evidence["required_uncertainty_codes"]
    assert not any(identity.startswith(("C:", "R:")) for identity in evidence["registry"])
    assert len(counter.counted) == 7 and len(policy.transport.messages) == 1
    for messages in counter.counted:
        ids = [item["case"]["case_id"] for item in json.loads(messages[1].content)["memory"]["retrieval"]["items"]]
        assert (101 in ids) == (207 in ids)


def test_soft_target_is_no_reason_to_drop_public_material(config, observation):
    policy = controller(config, mode="short", counter=Counter(20000))
    policy.decide(observation)
    evidence, = policy.drain_decision_evidence()
    assert evidence["trim_events"] == ()
    assert any(identity.startswith("R:") for identity in evidence["registry"])


def test_core_over_budget_zero_provider_calls_no_fake_audits(config, day0):
    policy = controller(config, counter=Counter(config[2].input_token_budget + 1))
    with pytest.raises(PromptBudgetError) as caught:
        policy.decide(day0)
    assert caught.value.details["messages_sha256"] and caught.value.details["input_tokens"] > 0
    assert not policy.transport.messages and policy.transport.prepared == 0
    assert policy.drain_call_audits() == () and policy.drain_decision_evidence() == ()
    assert policy.drain_case_revisions() == ()


def test_sent_case_refs_and_public_values_are_distinct_from_selected_ids(config, observation):
    _, prompt, _ = config
    result = retrieval_result(observation, prompt)
    transport = Transport([lambda messages: successful_response(messages, evidence_ids=["C:309", "O:/history/3/delivered_diagnoses"],
                           alternative_actions=[{"action": [1, 0, 0, 0, 0], "tradeoff": "????", "evidence_ids": ["C:101"]}])])
    policy = controller(config, mode="both", retriever=Retriever(result), transport=transport)
    policy.decide(observation)
    evidence, = policy.drain_decision_evidence()
    assert evidence["selected_case_ids"] == (101, 207, 309)
    assert evidence["cited_case_ids"] == (309, 101)
    assert evidence["cited_evidence"]["O:/history/3/delivered_diagnoses"] == 6
    assert {"case_conflict", "truncated_followup"}.issubset(evidence["required_uncertainty_codes"])
    assert evidence["review_status"] == "not_reviewed"
    with pytest.raises(TypeError):
        evidence["cited_evidence"]["O:/history/3/delivered_diagnoses"] = 0


@pytest.mark.parametrize("status,flags,expected", [("empty", (), {"no_case"}),
                                                   ("out_of_support", (), {"no_case", "out_of_support"}),
                                                   ("unavailable", ("query_io_error",), {"no_case"})])
def test_zero_result_semantics_continue_model_with_explicit_limits(config, day0, status, flags, expected):
    policy = controller(config, mode="global", retriever=Retriever(RetrievalResult(status, flags=flags)))
    assert policy.decide(day0) is not None
    evidence, = policy.drain_decision_evidence()
    assert expected.issubset(evidence["required_uncertainty_codes"])
    assert evidence["retrieval_status"] == status and "disabled" not in evidence["retrieval_flags"]


def test_terminal_feedback_and_reset_clear_episode_only(config):
    fixture = json.loads((ROOT / "docs/llm_architecture_research/examples/terminal_feedback.json").read_text(encoding="utf-8"))
    observation = observation_from_dict(fixture["pre_observation"])
    feedback = PublicWeekFeedback(weekly_record_from_dict(fixture["feedback"]["week"]),
                                  weekly_record_from_dict(fixture["feedback"]["previous_week"]))
    policy = controller(config, mode="short")
    policy.decide(observation)
    policy.observe(feedback)
    revision, = policy.drain_case_revisions()
    assert revision.status == "terminal_censored" and revision.window_days == 5
    assert "partial_window" in revision.flags and "truncated_followup" in revision.flags
    assert revision.executed_window.executed_action == feedback.week.executed_action
    assert len(policy.transport.messages) == 1
    policy.reset()
    assert policy.drain_decision_evidence() == () and policy.drain_case_revisions() == ()
    assert policy.drain_call_audits() == ()


def test_p4_legacy_keeps_two_field_template_and_memory_rejection(config, day0):
    prompt = config[1]
    assert memory_prompt_config(prompt).version != prompt.version
    legacy = build_public_messages(day0, prompt)
    assert set(json.loads(legacy[1].content)) == {"observation", "public_rates"}
    with pytest.raises(NotImplementedError):
        build_public_messages(day0, prompt, memory_context={})


@pytest.fixture
def memory_receipt(config, day0, observation, tmp_path):
    """Synthetic provider evidence for the receipt code path; no service is called."""
    class AcceptedFixtureCounter(Counter):
        def verify_response(self, response):
            if (response.model, response.system_fingerprint) != ("offline-model", None):
                raise LLMConfigurationError("provider_changed", "Offline accepted service changed")

    class ProbeStore:
        def cases(self):
            return tuple(item.case for item in retrieval_result(observation, config[1]).items)

        def group_for(self, case_id):
            return str(case_id)

    scale = 10000
    weeks = tuple(replace(week, delivered_diagnoses=week.delivered_diagnoses * scale,
                          cost=replace(week.cost, clinical_tests=week.cost.clinical_tests * scale,
                                       delivered_notifications=week.cost.delivered_notifications * scale),
                          resources=PublicResources(2 * scale, 5 * scale, scale))
                  for week in observation.history)
    long_observation = replace(observation, population=PublicPopulation(100 * scale,
        (0, 100 * scale, 0, 0, 0), 50 * scale, 40 * scale),
        resources=weeks[-1].resources, history=weeks)
    store = ProbeStore()
    probes = {name: {"observation": observation, "store": store}
              for name in MEMORY_PROBE_MODES}
    probes["day0_none"] = {"observation": day0}
    probes["no_case"] = {"observation": replace(observation, resources=PublicResources(100, 100, 100)),
                         "store": store}
    probes["long_numeric"] = {"observation": long_observation, "store": store}
    transport = Transport([lambda messages: replace(successful_response(messages), usage={"prompt_tokens": 100})] * 6)
    transport.settings = config[2]
    receipt = accept_memory_llm(transport, AcceptedFixtureCounter(), config[1], probes, tmp_path / "offline-receipt")
    return receipt, transport


@pytest.mark.parametrize("mode", MEMORY_MODES)
def test_provider_receipt_accepts_all_modes_without_binding_probe_library(config, day0, memory_receipt, mode):
    receipt, transport = memory_receipt
    class NoQuery:
        def retrieve(self, query):
            raise AssertionError("provider receipt queried the episode library")
    policy = controller(config, mode=mode, retriever=NoQuery())
    if mode in ("none", "short"):
        policy.decide(day0)
    else:
        policy.memory.stage(day0)
    pending = policy.memory.pending_observation
    prepared = policy._prepared_context
    policy.token_counter.counted.clear()
    record = validate_memory_acceptance(receipt, policy)
    assert record["status"] == "accepted" and len(record["cases"]) == len(transport.messages) == 6
    assert len(policy.token_counter.counted) == 6
    assert policy.memory_mode == mode and policy.memory.pending_observation is pending
    assert policy._prepared_context is prepared


def _rewrite_receipt(path, mutate):
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    value["sha256"] = snapshot_sha256({key: item for key, item in value.items() if key != "sha256"})
    path.write_text(json.dumps(value), encoding="utf-8")


def test_provider_receipt_checks_previously_accepted_service(config, memory_receipt):
    receipt, _ = memory_receipt
    policy = controller(config)
    def verify(response):
        if (response.model, response.system_fingerprint) != ("current-provider-model", "current-fingerprint"):
            raise LLMConfigurationError("provider_changed", "Provider changed")
    policy.token_counter.verify_response = verify
    with pytest.raises(LLMConfigurationError):
        validate_memory_acceptance(receipt, policy)


@pytest.mark.parametrize("name", tuple(MEMORY_PROBE_MODES))
def test_provider_receipt_recounts_every_probe(config, memory_receipt, name):
    receipt, _ = memory_receipt
    def mutate(record):
        case = next(item for item in record["cases"] if item["name"] == name)
        case["input_tokens"] += 1
        case["response"]["usage"]["prompt_tokens"] += 1
    _rewrite_receipt(receipt, mutate)
    with pytest.raises(LLMConfigurationError) as caught:
        validate_memory_acceptance(receipt, controller(config))
    assert caught.value.code == "memory_acceptance_invalid"


def test_provider_receipt_rejects_rehashed_but_incorrect_recent_summary(config, memory_receipt):
    receipt, _ = memory_receipt
    def mutate(record):
        case = next(item for item in record["cases"] if item["name"] == "four_weeks_short")
        payload = json.loads(case["messages"][1]["content"])
        payload["memory"]["recent"]["trend_direction"] = "down"
        case["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        case["messages_sha256"] = snapshot_sha256(case["messages"])
    _rewrite_receipt(receipt, mutate)
    with pytest.raises(LLMConfigurationError) as caught:
        validate_memory_acceptance(receipt, controller(config))
    assert caught.value.code == "memory_acceptance_invalid"

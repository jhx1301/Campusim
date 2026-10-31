"""Actual snapshot loop with offline model responses and a persistent library."""

from dataclasses import replace
import json

import pytest

from cemas.control.learning_store import LearningMemoryStore
from cemas.control.llm import (LLMController, LLMError, LLMResponse, LLMTransport,
                               OfficialInputTokenCounter, PromptBudgetError)
from cemas.control.llm_memory import MemoryLLMController
from cemas.control.memory import public_task_hash
from cemas.control.memory_types import public_to_dict, observation_from_dict
from cemas.control.runner import make_public_prompt_config, make_llm_settings, run_episode
from test_control_llm_memory import Counter, Transport, successful_response
from test_snapshot_training import small_world, protocol, make_env, ANCHOR


class ReflectingTransport(Transport):
    def complete(self, messages):
        self.messages.append(messages)
        payload = json.loads(messages[1].content)
        if "evidence_bundle" in payload:
            result = {"schema_version": "cemas-public-rule-patch-v3", "operations": []}
            if not payload["current_rule_set"]:
                from test_control_feedback import add_operation
                result["operations"] = [add_operation(payload["evidence_bundle"])]
        elif "weeks" in payload:
            result = {"schema_version": "cemas-public-feedback-result-v2", "items": [
                {"window_id": item["window_id"], "status": "abstain", "reason_code": "no_new_insight"}
                for item in payload["weeks"] if item["role"] == "autonomous"]}
        else:
            result = {"action": [0]*5, "reason": "Use public observations", "evidence_ids": ["O:/decision_day"],
                      "alternative_actions": [], "uncertainty_codes": payload["required_uncertainty_codes"]}
        return LLMResponse(json.dumps(result), model="offline", response_id="fixture")


@pytest.mark.parametrize("memory_enabled", [False, True])
@pytest.mark.parametrize("failures", [1, 3])
def test_snapshot_illegal_main_action_retries_before_execution(small_world, tmp_path, memory_enabled, failures):
    protocol, paths = small_world
    prompt = make_public_prompt_config(protocol)
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")

    def response(action, reason):
        def render(messages):
            if memory_enabled:
                alternatives = [] if action[1] == 3 else [{"action": [0, 3, 0, 0, 0],
                    "tradeoff": "Exceeds current capacity", "evidence_ids": ["O:/decision_day"]}]
                return successful_response(messages, action=action, reason=reason, alternative_actions=alternatives)
            return LLMResponse(json.dumps({"action": action, "reason": reason}))
        return render

    outcomes = [response([0, 3, 0, 0, 0], "Rejected main action")] * failures
    if failures < 3:
        outcomes.append(response([0] * 5, "Accepted main action"))
    transport, counter, waits = Transport(outcomes), Counter(), []
    cls = MemoryLLMController if memory_enabled else LLMController
    kwargs = {"memory_mode": "short"} if memory_enabled else {}
    policy = cls(transport, prompt, settings, counter, sleeper=waits.append, **kwargs)
    output = tmp_path / "run"
    options = {"snapshot_path": str(paths[1]), "future_seed": 321,
               "calibration_artifact": ANCHOR, "execution_days": 14}
    if failures == 3:
        with pytest.raises(LLMError) as caught:
            run_episode(protocol, policy, output, 20101, purpose="smoke", scenario_options=options)
        assert caught.value.code == "llm_retry_exhausted"
        failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
        assert failure["details"]["error_code"] == "llm_retry_exhausted"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "failed" and manifest["elapsed_days"] == 7
    else:
        result = run_episode(protocol, policy, output, 20101, purpose="smoke", scenario_options=options)
        assert result.summary["decision_count"] == 1 and result.summary["execution_window_count"] == 2

    calls = [json.loads(line) for line in (output / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == min(failures + 1, 3)
    assert [c["error_code"] for c in calls] == ["illegal_action"] * failures + ([None] if failures < 3 else [])
    assert all(c["retryable"] for c in calls[:failures])
    assert all(messages[:2] == transport.messages[0] for messages in transport.messages)
    assert all(json.loads(messages[-1].content)["validation_error"]["code"] == "illegal_action"
               for messages in transport.messages[1:])
    assert len(counter.counted) == 2 and waits == [2, 4][:failures]
    decisions = [json.loads(line) for line in (output / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(decisions) == (1 if failures == 3 else 2)
    if failures < 3:
        assert decisions[-1]["llm_attempt_count"] == 2
        assert decisions[-1]["executed_action"]["values"] == [0] * 5
        assert decisions[-1]["reasoning"] == "Accepted main action"
    if memory_enabled:
        evidence = [json.loads(line) for line in (output / "decision_evidence.jsonl").read_text(encoding="utf-8").splitlines()]
        prepared = [item for item in evidence if item["event"] == "prepared"]
        assert len(prepared) == 1
        assert prepared[0]["status"] == ("retry_exhausted" if failures == 3 else "success")
        if failures < 3:
            assert prepared[0]["request_action"] == [0] * 5
            assert prepared[0]["reason"] == "Accepted main action"
            assert prepared[0]["alternative_actions"][0]["feasible"] is False
        else:
            assert prepared[0]["evidence_ids"] == []


def test_snapshot_illegal_action_exhaustion_rolls_back_training(small_world, tmp_path):
    from cemas.control.learning import train_memory
    from cemas.control.snapshot_protocol import history_seeds
    from cemas.control.snapshots import generate_history_snapshots

    protocol = small_world[0]
    world = history_seeds(protocol, "train")[0]
    snapshot, = generate_history_snapshots(protocol, ANCHOR, tmp_path / "train-snapshots", world, "train", days=[35])
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")
    policies = []
    before_failure = []

    class TrainingTransport(ReflectingTransport, LLMTransport):
        def complete(self, messages):
            payload = json.loads(messages[1].content)
            if payload.get("observation", {}).get("decision_day") == 63:
                before_failure.append((len(policies[0].store.cases()), len(policies[0].store.current_rules())))
                self.messages.append(messages)
                return successful_response(messages, action=[0, 3, 0, 0, 0])
            return super().complete(messages)

    class TrainingCounter(Counter, OfficialInputTokenCounter):
        pass

    def factory(protocol, learning_store, **kwargs):
        policy = MemoryLLMController(TrainingTransport(), make_public_prompt_config(protocol), settings,
            TrainingCounter(), memory_mode="both", store=learning_store,
            feedback_backend="llm", rule_memory="adaptive", sleeper=lambda _: None)
        policies.append(policy)
        return policy

    entry = {"episode_id": "failed", "world_seed": world,
             "scenario_options": {"snapshot_path": str(snapshot), "future_seed": 321}}
    library = tmp_path / "library.sqlite"
    output = tmp_path / "training"
    with pytest.raises(LLMError) as caught:
        train_memory(protocol, [entry], library, output, {}, ANCHOR, controller_factory=factory)
    assert caught.value.code == "llm_retry_exhausted"
    assert len(before_failure) == 3 and all(cases == 8 and rules > 0 for cases, rules in before_failure)
    run, = output.glob("*/episode")
    failure = json.loads((run / "failure.json").read_text(encoding="utf-8"))
    assert failure["details"]["error_code"] == "llm_retry_exhausted"
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed" and summary["elapsed_days"] == 63
    calls = [json.loads(line) for line in (run / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    rejected = [call for call in calls if call["decision_day"] == 63]
    assert len(rejected) == 3 and all(call["error_code"] == "illegal_action" for call in rejected)
    events = [json.loads(line) for line in (run / "feedback_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(e["event"] == "provider_call" and e["decision_day"] == 63 and e["purpose"] == "feedback" for e in events) == 1
    assert sum(e["event"] == "provider_call" and e["decision_day"] == 63 and e["purpose"] == "rule_distillation" for e in events) == 1
    reader = LearningMemoryStore(library)
    try:
        assert reader.cases() == () and reader.current_rules() == () and reader.rule_updates() == ()
        assert reader.begin_episode("failed", "new-scenario")
    finally:
        reader.close()


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_first_snapshot_control_feedback_matches_history(small_world, index):
    from cemas.control.memory import PublicEpisodeMemory, recent_summary
    env, _ = make_env(small_world, index=index, horizon=21)
    observation, *_ = env.advance_initial_week()
    assert observation_from_dict(public_to_dict(observation)) == observation
    recent = recent_summary(observation)
    assert len(recent.windows) == 4
    assert recent.windows[0].start_day < 0
    assert recent.windows[0].notifications is None and recent.windows[0].resources is None
    memory = PublicEpisodeMemory()
    memory.stage(observation)
    _, _, _, _, info = env.step(0)
    assert info.feedback.previous_week == observation.history[-1]
    memory.accept(info.feedback)
    env.close()


def test_full_snapshot_feedback_schedule_and_frozen_evaluation(small_world, tmp_path):
    protocol, paths = small_world
    prompt = make_public_prompt_config(protocol)
    task = public_task_hash(prompt, 119)
    store = LearningMemoryStore(tmp_path / "learning.sqlite", task)
    store.begin_episode("first", "scenario")
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")
    transport = ReflectingTransport()
    controller = MemoryLLMController(transport, prompt, settings, Counter(), memory_mode="both", store=store,
                                    feedback_backend="llm", rule_memory="adaptive", sleeper=lambda _: None)
    options = {"snapshot_path": str(paths[1]), "future_seed": 321, "calibration_artifact": ANCHOR}
    result = run_episode(protocol, controller, tmp_path / "run", 20101, purpose="smoke", scenario_options=options)
    assert result.summary["elapsed_days"] == 119
    assert result.summary["decision_count"] == 16
    assert result.summary["execution_window_count"] == 17
    assert result.summary["control_period"]["execution_days"] == 112
    assert result.summary["positive_cost"] == result.summary["control_period"]["positive_cost"]
    assert len(store.cases()) == 16 and store.cases()[0].pre_observation.decision_day == 7
    assert store.current_rules()[0]["status"] == "active"
    rule_inputs = [json.loads(messages[1].content) for messages in transport.messages
                   if "evidence_bundle" in json.loads(messages[1].content)]
    assert [payload["evidence_bundle"]["weeks"][-1]["end_day"] + 1 for payload in rule_inputs] == [35, 63, 91, 119]
    for payload in rule_inputs:
        assert list(payload) == ["task_rules", "current_rule_set", "evidence_bundle"]
        assert all("version" not in card for card in payload["task_rules"])
        bundle = payload["evidence_bundle"]
        assert list(bundle) == ["condition_catalog", "weeks", "comparisons"]
        day = bundle["weeks"][-1]["end_day"] + 1
        assert [(item["start_day"], item["end_day"]) for item in bundle["weeks"]] == [
            (start, start + 6) for start in range(day - 35, day, 7)]
        assert len({item["window_id"] for item in bundle["weeks"]}) == 5
        for item in bundle["weeks"]:
            assert not {"case_id", "revision", "opaque_group"} & item.keys()
            assert not {"start_day", "end_day"} & item["values"].keys()
        assert "facts" not in bundle and "cases" not in bundle
        for rule in payload["current_rule_set"]:
            assert set(rule) == {"id", "version", "content", "status", "support_count", "contradiction_count", "confidence"}
            assert set(rule["content"]["condition_ids"]) <= bundle["condition_catalog"].keys()
    action_inputs = [json.loads(m[1].content) for m in transport.messages
                     if "observation" in json.loads(m[1].content)]
    assert any(payload["learned_rules"] for payload in action_inputs)
    assert all("evidence" not in rule for payload in action_inputs for rule in payload["learned_rules"])
    events = [json.loads(line) for line in (result.output_dir / "feedback_events.jsonl").read_text(encoding="utf-8").splitlines()]
    calls = [e for e in events if e["event"] == "provider_call"]
    assert [e["decision_day"] for e in calls if e["purpose"] == "rule_distillation"] == [35, 63, 91, 119]
    assert all(e["template_version"] == "cemas-rule_distillation-prompt-v6"
               for e in calls if e["purpose"] == "rule_distillation")
    assert all(e["template_version"] == "cemas-feedback-prompt-v5"
               for e in calls if e["purpose"] == "feedback")
    assert [e["decision_day"] for e in calls if e["purpose"] == "feedback"] == list(range(14, 119, 7))
    decisions = [json.loads(line) for line in (result.output_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(d["llm_attempt_count"] for d in decisions) == 16
    controller.finish_episode()
    assert controller.drain_feedback_events() == ()
    store.complete_episode(result.output_dir)
    store.begin_episode("second", "scenario2")
    second = run_episode(protocol, controller, tmp_path / "second-run", 20101, purpose="smoke", scenario_options=options)
    assert len(store.cases()) == 32 and len({store.group_for(c.case_id) for c in store.cases()}) == 2
    evidence = [json.loads(line) for line in (second.output_dir / "decision_evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    first = next(item for item in evidence if item["event"] == "prepared")
    assert first["decision_day"] == 7 and any(ref.startswith("L:") for ref in first["registry"])
    assert first["selected_case_ids"] and len(first["selected_case_ids"]) == 1
    store.complete_episode(second.output_dir)
    frozen = store.freeze(tmp_path / "frozen.sqlite")
    store.close()
    before = frozen.read_bytes()
    reader = LearningMemoryStore(frozen, readonly=True)
    controller = MemoryLLMController(ReflectingTransport(), prompt, settings, Counter(), memory_mode="both", store=reader,
                                    feedback_backend="llm", rule_memory="adaptive", sleeper=lambda _: None)
    result = run_episode(protocol, controller, tmp_path / "evaluation", 20101, purpose="smoke", scenario_options=options)
    events = [json.loads(line) for line in (result.output_dir / "feedback_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(e["purpose"] != "rule_distillation" for e in events)
    reader.close()
    assert frozen.read_bytes() == before


def test_auxiliary_success_then_action_budget_failure_keeps_events(small_world):
    env, _ = make_env(small_world, horizon=28)
    observation, *_ = env.advance_initial_week()
    protocol = small_world[0]
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")
    counter = Counter()
    controller = MemoryLLMController(ReflectingTransport(), make_public_prompt_config(protocol), settings, counter,
                                    memory_mode="short", feedback_backend="llm", sleeper=lambda _: None)
    controller.decide(observation)
    observation, _, _, _, info = env.step(0)
    controller.observe(info.feedback)
    counter.count = lambda messages: settings.input_token_budget + 1 if "observation" in json.loads(messages[1].content) else 100
    with pytest.raises(PromptBudgetError):
        controller.decide(observation)
    events = controller.drain_feedback_events()
    assert any(event["event"] == "provider_call" and event["purpose"] == "feedback" for event in events)
    assert controller.memory.pending_observation is None
    env.close()


def test_snapshot_prompt_over_limit_is_not_trimmed(small_world):
    env, _ = make_env(small_world, horizon=21)
    observation, *_ = env.advance_initial_week()
    protocol = small_world[0]
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")
    transport = ReflectingTransport()
    counter = Counter(settings.input_token_budget + 1)
    controller = MemoryLLMController(transport, make_public_prompt_config(protocol), settings, counter, memory_mode="short")
    with pytest.raises(PromptBudgetError):
        controller.decide(observation)
    assert len(counter.counted) == 1 and transport.messages == []
    assert controller.memory.pending_observation is None
    env.close()


def test_notes_enter_prompt_and_expire_without_followup_revision(small_world):
    class CandidateTransport(ReflectingTransport):
        def complete(self, messages):
            packet = json.loads(messages[1].content)
            if "weeks" in packet and packet["as_of_day"] == 14:
                self.messages.append(messages)
                current_week = next(item for item in packet["weeks"] if item["role"] == "autonomous")
                reference_week = packet["weeks"][0]
                ref = reference_week["window_id"] + ":" + reference_week["reference_fields"][0]
                item = {"window_id": current_week["window_id"], "status": "candidate",
                        "finding": {"text": "Observed testing and burden", "evidence_ids": [ref]},
                        "decision_check": {"text": "Check testing composition", "evidence_ids": [ref]},
                        "applicability": "Comparable observed windows", "limitations": ["Not causal"]}
                return LLMResponse(json.dumps({"schema_version": "cemas-public-feedback-result-v2", "items": [item]}))
            return super().complete(messages)
    env, _ = make_env(small_world, horizon=49)
    current, *_ = env.advance_initial_week()
    protocol = small_world[0]
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED")
    transport = CandidateTransport()
    policy = MemoryLLMController(transport, make_public_prompt_config(protocol), settings, Counter(),
                                 memory_mode="short", feedback_backend="llm", sleeper=lambda _: None)
    policy.decide(current)
    current, _, _, _, info = env.step(0)
    policy.observe(info.feedback)
    policy.decide(current)
    payload = json.loads(transport.messages[-1][1].content)
    assert len(payload["feedback"]) == 1
    cited = payload["feedback"][0]["item"]["finding"]["evidence_ids"][0]
    assert payload["feedback"][0]["facts"][cited]["value"] is not None
    old_id = payload["feedback"][0]["id"]
    assert old_id in payload["evidence_registry"]
    policy.decide(current)
    assert len([m for m in transport.messages if "weeks" in json.loads(m[1].content)]) == 1
    current, _, _, _, info = env.step(0)
    policy.observe(info.feedback)
    policy.decide(current)
    payload = json.loads(transport.messages[-1][1].content)
    assert payload["feedback"][0]["id"] == old_id
    while current.decision_day < 42:
        current, _, _, _, info = env.step(0)
        policy.observe(info.feedback)
        policy.decide(current)
    payload = json.loads(transport.messages[-1][1].content)
    assert payload["feedback"] == [] and old_id not in payload["evidence_registry"]
    env.close()

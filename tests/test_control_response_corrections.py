"""Offline regressions from real response failures, with no provider calls."""

from copy import deepcopy
import json

import pytest

from cemas.control.feedback import FeedbackResponseError, parse_feedback, project_feedback
from cemas.control.learning_store import LearningMemoryStore
from cemas.control.llm import ActionResponseError, parse_action_response
from cemas.control.llm_memory import parse_memory_response
from cemas.control.memory import PublicEpisodeMemory
from cemas.control.rule_memory import prepare_patch, rule_bundle
from cemas.control.types import ActionVector, PublicWeekFeedback
from test_control_feedback import add_operation, apply, bundle_for, library, patch, revise
from test_control_memory import observation, week


LONG_TEXT = "Public observations do not establish a causal effect. " * 6


def feedback_candidate(store):
    packet = project_feedback(store.cases(), 35, store.public_task_sha256, group_for=store.group_for)
    current = next(item for item in packet["weeks"] if item["role"] == "autonomous")
    reference = next(identity for identity in packet["facts"] if identity.endswith(":cost.delivered_notifications"))
    result = {"schema_version": "cemas-public-feedback-result-v2", "items": [{
        "window_id": current["window_id"], "status": "candidate",
        "finding": {"text": "Compare public notifications", "evidence_ids": [reference]},
        "decision_check": {"text": "Check actual testing", "evidence_ids": [reference]},
        "applicability": "Comparable public weeks", "limitations": ["Descriptive only"]}]}
    return packet, result


def test_long_action_text_survives_wire_parsing_and_action_proposal():
    # These exact lengths caused expensive retries in the real pilot.
    reason = "Diagnoses and growth fall with stable resources; maintain current controls one week; hidden-infection uncertainty persists."
    tradeoff = "Lower school burden, but weaker school transmission control with growth positive."
    assert len(reason) == 123 and len(tradeoff) == 81
    ordinary = parse_action_response(json.dumps({"action": [0] * 5, "reason": reason}), reason_max_chars=1)
    assert ordinary.reasoning == reason
    value = {"action": [0] * 5, "reason": LONG_TEXT,
             "evidence_ids": ["O:/decision_day"], "uncertainty_codes": ["partial_observability"],
             "alternative_actions": [{"action": [1, 0, 0, 0, 0], "tradeoff": tradeoff,
                                      "evidence_ids": ["O:/decision_day"]}]}
    parsed = parse_memory_response(json.dumps(value), registry={"O:/decision_day": 7}, reason_max_chars=1)
    assert parsed.proposal.reasoning == LONG_TEXT
    assert parsed.alternative_actions[0]["tradeoff"] == tradeoff


@pytest.mark.parametrize("bad_text", ["", "   ", "two\nlines", {"text": "wrong type"}])
def test_removing_length_cap_does_not_accept_invalid_action_text(bad_text):
    with pytest.raises(ActionResponseError):
        parse_action_response(json.dumps({"action": [0] * 5, "reason": bad_text}))


def test_long_feedback_fields_are_preserved(library):
    store, _, _ = library
    packet, result = feedback_candidate(store)
    item = result["items"][0]
    item["finding"]["text"] = item["decision_check"]["text"] = LONG_TEXT
    item["applicability"] = LONG_TEXT
    item["limitations"] = [LONG_TEXT]
    assert parse_feedback(json.dumps(result), packet) == result


def test_applicability_object_reports_exact_field_instead_of_coercing(library):
    store, _, _ = library
    packet, result = feedback_candidate(store)
    # The real pilot copied the {text: ...} shape from finding/decision_check.
    result["items"][0]["applicability"] = {"text": "Comparable observed weeks"}
    with pytest.raises(FeedbackResponseError) as caught:
        parse_feedback(json.dumps(result), packet)
    assert caught.value.code == "invalid_text"
    assert caught.value.details["path"] == "/items/0/applicability"
    assert caught.value.details["expected"] == "nonempty single-line string"
    assert caught.value.details["actual"] == "dict"


def test_missing_cost_prefix_reports_the_invalid_reference(library):
    store, _, _ = library
    packet, result = feedback_candidate(store)
    supplied = result["items"][0]["finding"]["evidence_ids"][0]
    invalid = supplied.replace(":cost.delivered_notifications", ":delivered_notifications")
    result["items"][0]["finding"]["evidence_ids"] = [invalid]
    with pytest.raises(FeedbackResponseError) as caught:
        parse_feedback(json.dumps(result), packet)
    assert caught.value.code == "invalid_reference"
    assert caught.value.details["path"] == "/items/0/finding/evidence_ids/0"
    assert caught.value.details["actual"] == invalid
    assert supplied in packet["facts"] and invalid not in packet["facts"]


def test_long_rule_content_increment_and_suspend_reason_preserve_versions(library):
    store, _, _ = library
    bundle = bundle_for(store)
    operation = add_operation(bundle)
    operation["content"].update(lesson=LONG_TEXT, limitations=[LONG_TEXT])
    operation["increment"] = LONG_TEXT
    apply(store, bundle, [operation])
    rule, = store.current_rules()
    assert rule["content"]["lesson"] == LONG_TEXT and rule["increment"] == LONG_TEXT
    changed = deepcopy(rule["content"])
    changed["lesson"] = LONG_TEXT + "Refined scope."
    revision = revise(rule, content=changed)
    revision["increment"] = LONG_TEXT
    apply(store, bundle, [revision])
    revised, = store.current_rules()
    assert revised["version"] == 2 and revised["support_count"] == 0
    assert revised["content"] == changed
    apply(store, bundle, [{"op": "SUSPEND", "target_id": revised["id"],
                          "base_version": revised["version"], "reason": LONG_TEXT}])
    suspended, = store.current_rules()
    assert suspended["reason"] == LONG_TEXT and suspended["version"] == 2


def test_reference_ignore_is_rejected_at_the_judgment_window(library):
    store, _, _ = library
    bundle = bundle_for(store)
    operation = add_operation(bundle)
    reference = next(item["window_id"] for item in bundle["weeks"] if item["role"] == "reference")
    operation["judgments"].append({"window_id": reference, "judgment": "ignore"})
    with pytest.raises(FeedbackResponseError) as caught:
        prepare_patch(patch([operation]), bundle, store.current_rules(), store)
    assert caught.value.code == "invalid_judgment"
    assert caught.value.details["path"] == "/operations/0/judgments/2/window_id"
    assert caught.value.details["actual"] == reference
    assert caught.value.details["role"] == "reference"
    assert store.current_rules() == () and store.rule_updates() == ()


def test_action_condition_uses_pre_decision_action_and_reports_mismatch(tmp_path):
    store = LearningMemoryStore(tmp_path / "temporal.sqlite", "a" * 64)
    store.begin_episode("temporal", "scenario")
    memory = PublicEpisodeMemory()
    baseline = week(0, horizon=119, action=ActionVector((0, 0, 0, 0, 2)))
    weeks = [baseline]
    try:
        for day in (7, 14):
            memory.stage(observation(day, weeks, horizon=119))
            executed = week(day, horizon=119, action=ActionVector((0, 0, 0, 0, 1)))
            store.append_cases(memory.accept(PublicWeekFeedback(executed, weeks[-1])))
            weeks.append(executed)
        bundle = rule_bundle(store.cases(), (), store, 21, 7, [])
        controls = [item for item in bundle["weeks"] if item["role"] == "autonomous"]
        first, second = controls
        assert first["pre_decision_action"] == [0, 0, 0, 0, 2]
        assert tuple(first["values"]["executed_action"]["values"]) == (0, 0, 0, 0, 1)
        assert second["pre_decision_action"] == [0, 0, 0, 0, 1]
        action_one = next(identity for identity, condition in bundle["condition_catalog"].items()
                          if condition == {"kind": "action", "dimension": 4, "value": 1})
        operation = add_operation(bundle)
        operation["content"]["condition_ids"] = [action_one]
        operation["judgments"] = [{"window_id": first["window_id"], "judgment": "support"}]
        with pytest.raises(FeedbackResponseError) as caught:
            prepare_patch(patch([operation]), bundle, (), store)
        assert caught.value.code == "conditions_not_matched"
        assert caught.value.details["path"] == "/operations/0/judgments/0/judgment"
        assert caught.value.details["window_id"] == first["window_id"]
        assert action_one in caught.value.details["missing_condition_ids"]
        assert tuple(caught.value.details["pre_decision_action"]) == (0, 0, 0, 0, 2)
        operation["judgments"] = [{"window_id": first["window_id"], "judgment": "ignore"},
                                  {"window_id": second["window_id"], "judgment": "support"}]
        parsed = prepare_patch(patch([operation]), bundle, (), store)
        store.write_rule_changes(parsed["rules"], parsed["updates"])
        rule, = store.current_rules()
        assert rule["support_count"] == 1 and rule["contradiction_count"] == 0
    finally:
        store.close()

"""Flat weekly inputs, aggregate rules, and transactional public learning."""

from copy import deepcopy
from dataclasses import replace
import json
import sqlite3

import pytest

from cemas.control.feedback import FeedbackResponseError, parse_feedback, project_feedback
from cemas.control.learning_store import LearningMemoryStore
from cemas.control.memory import PublicEpisodeMemory, load_memory_profile
from cemas.control.memory_store import CaseStoreError
from cemas.control.memory_types import public_hash, public_to_dict
from cemas.control.rule_memory import prepare_patch, retrieve_rules, rule_bundle
from cemas.control.types import PublicWeekFeedback
from test_control_memory import observation, week


def add_weeks(store, count=4):
    memory = PublicEpisodeMemory()
    weeks = [week(0, horizon=119)]
    for day in range(7, 7 * (count + 1), 7):
        memory.stage(observation(day, weeks, horizon=119))
        current = week(day, horizon=119, diagnoses=day)
        store.append_cases(memory.accept(PublicWeekFeedback(current, weeks[-1])))
        weeks.append(current)
    return memory, observation(7 * (count + 1), weeks, horizon=119)


@pytest.fixture
def library(tmp_path):
    store = LearningMemoryStore(tmp_path / "learning.sqlite", "a" * 64)
    store.begin_episode("first", "scenario1")
    memory, current = add_weeks(store)
    yield store, memory, current
    store.close()


def bundle_for(store, day=35):
    return rule_bundle(store.cases(), store.current_rules(), store, day, 7, [])


def supporting(bundle):
    return [item["window_id"] for item in bundle["weeks"] if item["support_window"]]


def add_operation(bundle, number=0):
    conditions = [key for key, value in bundle["condition_catalog"].items()
                  if value["kind"] == "resources"][:1]
    return {"op": "ADD", "increment": "Specific observation from executed windows",
            "content": {"condition_ids": conditions, "lesson": f"Compare testing and burden {number}",
                        "limitations": ["Not causal"]},
            "judgments": [{"window_id": identity, "judgment": "support"}
                          for identity in supporting(bundle)[:2]]}


def patch(operations):
    return json.dumps({"schema_version": "cemas-public-rule-patch-v3", "operations": operations})


def revise(rule, judgments=(), *, content=None):
    return {"op": "REVISE", "target_id": rule["id"], "base_version": rule["version"],
            "content": deepcopy(content if content is not None else rule["content"]),
            "increment": "New observations", "judgments": list(judgments)}


def apply(store, bundle, operations):
    result = prepare_patch(patch(operations), bundle, store.current_rules(), store)
    store.write_rule_changes(result["rules"], result["updates"])


def test_continuous_rule_windows_are_unique_at_every_maintenance(tmp_path):
    store = LearningMemoryStore(tmp_path / "learning.sqlite", "a" * 64)
    store.begin_episode("full", "s")
    add_weeks(store, 16)
    for day in (35, 63, 91, 119):
        bundle = bundle_for(store, day)
        weeks = bundle["weeks"]
        assert [(item["start_day"], item["end_day"]) for item in weeks] == [
            (start, start + 6) for start in range(day - 35, day, 7)]
        assert len({item["window_id"] for item in weeks}) == 5
        assert weeks[0]["role"] == "reference" and not weeks[0]["support_window"]
        assert all(item["role"] == "autonomous" and item["support_window"] for item in weeks[1:])
        assert all(item["matched_condition_ids"] for item in weeks[1:])
        if day > 35:
            assert {condition["value"] for condition in bundle["condition_catalog"].values()
                    if condition["kind"] == "history"} == {4}
        assert [(item["before_window_id"], item["after_window_id"]) for item in bundle["comparisons"]] == [
            (before["window_id"], after["window_id"]) for before, after in zip(weeks, weeks[1:])]
        assert "facts" not in bundle and "cases" not in bundle
    assert store.cases()[-1].executed_week.end_day == 118
    assert not hasattr(store.cases()[-1], "followup_window")
    store.close()


def test_aggregate_statistics_are_idempotent_and_reclassification_replaces(library):
    store, _, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    rule, = store.current_rules()
    assert (rule["version"], rule["support_count"], rule["contradiction_count"], rule["confidence"]) == (1, 2, 0, .75)
    first, second, third, _ = supporting(bundle)
    apply(store, bundle, [revise(rule, [{"window_id": first, "judgment": "support"}])])
    repeated, = store.current_rules()
    assert repeated["version"] == 1 and repeated["support_count"] == 2
    apply(store, bundle, [revise(repeated, [{"window_id": third, "judgment": "contradict"}])])
    contradicted, = store.current_rules()
    assert (contradicted["version"], contradicted["support_count"], contradicted["contradiction_count"]) == (1, 2, 1)
    assert contradicted["confidence"] == pytest.approx(.6)
    apply(store, bundle, [revise(contradicted, [{"window_id": first, "judgment": "contradict"},
                                             {"window_id": third, "judgment": "ignore"}])])
    changed, = store.current_rules()
    assert (changed["version"], changed["support_count"], changed["contradiction_count"]) == (1, 1, 1)
    assert changed["confidence"] == .5
    assert changed["status"] == "candidate"
    assert len(store.rule_updates(changed["id"], 1)) == 3
    assert all("evidence" not in key for key in changed)
    assert set(changed["content"]) == {"condition_ids", "lesson", "limitations"}


def test_database_write_failure_rolls_back_the_whole_rule_batch(library):
    store, _, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    original_rules, original_updates = store.current_rules(), store.rule_updates()
    result = prepare_patch(patch([add_operation(bundle, 1)]), bundle, original_rules, store)
    invalid = {**result["updates"][-1], "case_id": 999999}
    with pytest.raises(sqlite3.IntegrityError):
        store.write_rule_changes(result["rules"], (*result["updates"], invalid))
    assert store.current_rules() == original_rules
    assert store.rule_updates() == original_updates


def test_content_revision_resets_statistics_and_suspend_preserves_version(library):
    store, _, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    rule, = store.current_rules()
    content = {**rule["content"], "lesson": "A narrower new rule"}
    apply(store, bundle, [revise(rule, content=content)])
    revised, = store.current_rules()
    assert (revised["version"], revised["support_count"], revised["contradiction_count"], revised["confidence"]) == (2, 0, 0, .5)
    assert revised["status"] == "candidate"
    assert len(store.rule_updates(rule["id"], 1)) == 2
    apply(store, bundle, [{"op": "SUSPEND", "target_id": revised["id"], "base_version": 2, "reason": "Reconsider scope"}])
    suspended, = store.current_rules()
    assert suspended["version"] == 2 and suspended["status"] == "suspended"
    assert retrieve_rules(store.cases()[0].pre_observation, store, load_memory_profile().retrieval) == []


def test_suspension_preserves_existing_statistics(library):
    store, _, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    original, = store.current_rules()
    apply(store, bundle, [{"op": "SUSPEND", "target_id": original["id"],
                          "base_version": original["version"], "reason": "Needs review"}])
    suspended, = store.current_rules()
    assert suspended["status"] == "suspended"
    for field in ("version", "support_count", "contradiction_count", "confidence"):
        assert suspended[field] == original[field]
    assert len(store.rule_updates(original["id"], original["version"])) == 2


def test_old_prepared_patch_cannot_overwrite_a_new_content_version(library):
    store, _, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    original, = store.current_rules()
    stale = prepare_patch(patch([revise(original, [{"window_id": supporting(bundle)[2],
                                                   "judgment": "support"}])]),
                          bundle, (original,), store)
    apply(store, bundle, [revise(original, content={**original["content"], "lesson": "Revised scope"})])
    rules_before, updates_before = store.current_rules(), store.rule_updates()
    with pytest.raises(CaseStoreError, match="version conflicts"):
        store.write_rule_changes(stale["rules"], stale["updates"])
    assert store.current_rules() == rules_before
    assert store.rule_updates() == updates_before


def test_case_revision_rejudgment_still_counts_one_window(library):
    store, memory, _ = library
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    rule, = store.current_rules()
    window_id = supporting(bundle)[-1]
    apply(store, bundle, [revise(rule, [{"window_id": window_id, "judgment": "support"}])])
    local = memory.latest_revisions[-1]
    corrected = replace(local, revision=2,
                        executed_week=replace(local.executed_week, delivered_diagnoses=99))
    store.append_cases((corrected,))
    bundle = bundle_for(store)
    current, = store.current_rules()
    apply(store, bundle, [revise(current, [{"window_id": window_id, "judgment": "contradict"}])])
    current, = store.current_rules()
    assert (current["version"], current["support_count"], current["contradiction_count"]) == (1, 2, 1)
    updates = store.rule_updates(current["id"], current["version"])
    assert len(updates) == 3
    assert next(row for row in updates if row["window_start"] == 28)["case_revision"] == 2


def test_arbitrary_batch_atomic_validation_and_top_six(library):
    store, _, _ = library
    bundle = bundle_for(store)
    operations = [add_operation(bundle, index) for index in range(8)]
    invalid = deepcopy(operations)
    invalid[-1]["judgments"][0]["window_id"] = "missing"
    with pytest.raises(FeedbackResponseError):
        apply(store, bundle, invalid)
    assert store.current_rules() == () and store.rule_updates() == ()
    apply(store, bundle, operations)
    assert len(store.current_rules()) == 8
    selected = retrieve_rules(store.cases()[0].pre_observation, store, load_memory_profile().retrieval)
    assert [item["rule_id"] for item in selected] == list(range(1, 7))
    assert all("evidence" not in item and item["support_count"] == 2 for item in selected)
    query = store.cases()[0].pre_observation
    different = replace(query, resources=replace(query.resources, clinical_daily_capacity=99))
    assert retrieve_rules(different, store, load_memory_profile().retrieval) == []


@pytest.mark.parametrize("mutation", [
    lambda op, bundle: op.update(op=[]),
    lambda op, bundle: op["judgments"][0].update(window_id=[]),
    lambda op, bundle: op["judgments"].append(deepcopy(op["judgments"][0])),
    lambda op, bundle: op["judgments"][0].update(window_id=bundle["weeks"][0]["window_id"]),
])
def test_invalid_response_values_are_retryable_boundary_errors(library, mutation):
    store, _, _ = library
    bundle = bundle_for(store)
    operation = add_operation(bundle)
    mutation(operation, bundle)
    with pytest.raises(FeedbackResponseError):
        prepare_patch(patch([operation]), bundle, (), store)
    assert store.current_rules() == () and store.rule_updates() == ()


def test_inapplicable_judgments_must_be_ignored_and_stale_batch_rejected(library):
    store, _, _ = library
    bundle = bundle_for(store)
    operation = add_operation(bundle)
    apply(store, bundle, [operation])
    rule, = store.current_rules()
    different = replace(store.cases()[-1].pre_observation.resources, clinical_daily_capacity=99)
    condition = {"kind": "resources", "value": public_to_dict(different)}
    identity = "COND:" + public_hash(condition)
    bundle["condition_catalog"][identity] = condition
    content = {**rule["content"], "condition_ids": [identity]}
    with pytest.raises(FeedbackResponseError, match="ignored"):
        apply(store, bundle, [revise(rule, [{"window_id": supporting(bundle)[0], "judgment": "support"}], content=content)])
    bad = revise(rule, [{"window_id": supporting(bundle)[0], "judgment": "ignore"}], content=content)
    bad["base_version"] = 999
    with pytest.raises(FeedbackResponseError, match="stale"):
        apply(store, bundle, [bad])
    assert store.current_rules() == (rule,)


def test_grouping_rollback_resume_and_freeze(tmp_path):
    path = tmp_path / "learning.sqlite"
    store = LearningMemoryStore(path, "a" * 64)
    store.begin_episode("one", "s1")
    add_weeks(store)
    bundle = bundle_for(store)
    apply(store, bundle, [add_operation(bundle)])
    assert len({store.group_for(case.case_id) for case in store.cases()}) == 1
    store.complete_episode("first-attempt")
    store.close()
    store = LearningMemoryStore(path)
    assert not store.begin_episode("one", "s1")
    with pytest.raises(CaseStoreError, match="different scenario"):
        store.begin_episode("one", "other")
    store.begin_episode("two", "s2")
    add_weeks(store, 1)
    original_rule, = store.current_rules()
    store.write_rule_changes([{**original_rule, "status": "suspended"}])
    store.rollback()
    assert len(store.cases()) == 4 and store.current_rules()[0]["status"] == "active"
    store.begin_episode("two", "s2")
    add_weeks(store, 1)
    store.complete_episode("second-attempt")
    assert len({store.group_for(case.case_id) for case in store.cases()}) == 2
    frozen = store.freeze(tmp_path / "frozen.sqlite")
    before = frozen.read_bytes()
    reader = LearningMemoryStore(frozen, readonly=True)
    assert len(reader.cases()) == 5 and reader.current_rules()[0]["support_count"] == 2
    with pytest.raises(CaseStoreError, match="writable"):
        reader.begin_episode("three", "s3")
    reader.close()
    assert frozen.read_bytes() == before
    store.close()


def test_old_learning_schema_is_rejected(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.executemany("INSERT INTO metadata VALUES(?,?)",
                       [("schema_version", "cemas-learning-memory-v1"), ("public_task_sha256", "a" * 64)])
    with pytest.raises(CaseStoreError, match="schema"):
        LearningMemoryStore(path)


def test_feedback_is_flat_and_abstention_covers_sent_windows(library):
    store, _, _ = library
    packet = project_feedback(store.cases(), 35, store.public_task_sha256, group_for=store.group_for)
    assert [(item["start_day"], item["role"]) for item in packet["weeks"]] == [(21, "reference"), (28, "autonomous")]
    assert "cases" not in packet
    result = {"schema_version": "cemas-public-feedback-result-v2", "items": [
        {"window_id": item["window_id"], "status": "abstain", "reason_code": "no_new_insight"}
        for item in packet["weeks"] if item["role"] == "autonomous"]}
    assert parse_feedback(json.dumps(result), packet) == result
    result["items"].pop()
    with pytest.raises(FeedbackResponseError):
        parse_feedback(json.dumps(result), packet)

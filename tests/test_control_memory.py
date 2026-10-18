"""Public episode memory: lifecycle, exact boundaries, and semantic task identity."""

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from cemas.control.protocol import load_protocol
from cemas.control.memory import (
    DEFAULT_PROFILE_PATH, MemoryProfile, PublicEpisodeMemory, case_flags,
    describe_case, load_memory_profile, public_task_hash, recent_summary,
)
from cemas.control.memory_types import (
    CASE_SCHEMA_VERSION, PublicCase, PublicMemoryContext,
    RetrievalResult, canonical_json, feedback_from_dict,
    local_case_from_dict, memory_context_from_dict, observation_from_dict,
    public_case_from_dict, public_hash, public_to_dict, recent_summary_from_dict,
    strict_json_loads,
)
from cemas.control.runner import make_public_prompt_config
from cemas.control.types import (
    ActionVector, PrivateMetrics, PublicCost, PublicObservation, PublicPopulation,
    PublicResources, PublicWeekFeedback, PublicWeeklyRecord,
)


POP = PublicPopulation(100, (0, 100, 0, 0, 0), 40, 50, 10)
RESOURCES = PublicResources(2, 10, 1)
ZERO = ActionVector((0, 0, 0, 0, 0))


def week(day, *, horizon=112, diagnoses=10, tests=20, action=ZERO, resources=RESOURCES):
    return PublicWeeklyRecord(
        day, min(day + 6, horizon - 1), diagnoses,
        PublicCost(clinical_tests=tests, delivered_notifications=7,
                   isolation_person_days=3, quarantine_person_days=4,
                   union_person_days=7, school_restriction_person_days=3,
                   work_restriction_person_days=4,
                   community_restriction_person_days=5),
        action, resources, 0.0, False, diagnoses / tests if tests else 0.0, bool(tests),
    )


def observation(day=0, weeks=(), *, horizon=112, resources=RESOURCES):
    history = tuple(weeks[-4:])
    padding = 4 - len(history)
    return PublicObservation(
        day, horizon, 2, POP, resources,
        history[-1].executed_action if history else ZERO,
        (0,) * 5, (True,) * 324,
        (PublicWeeklyRecord(),) * padding + history,
        (False,) * padding + (True,) * len(history),
    )


def public_case(local, *, case_id=1, task_hash="a" * 64):
    return PublicCase(
        case_id, local.revision, CASE_SCHEMA_VERSION, task_hash,
        local.pre_observation, local.executed_window, local.window_days,
        local.followup_window, local.status, local.available_through_day,
        "descriptive_not_causal", local.flags, local.description,
        {"kind": "source_simulation", "observation_sha256": public_hash(local.pre_observation),
         "feedback_sha256": public_hash(local.executed_window),
         "followup_sha256": public_hash(local.followup_window) if local.followup_window else None},
    )


def test_actual_execution_and_second_revision_are_immutable():
    memory = PublicEpisodeMemory()
    before = observation()
    memory.stage(before)
    first = week(0, action=ActionVector((1, 2, 1, 1, 0)))
    (original,) = memory.accept(PublicWeekFeedback(first))
    assert original.local_id == 1 and original.revision == 1
    assert original.executed_window.executed_action == first.executed_action != before.current_action
    assert "action_changed" in original.flags and "truncated_followup" in original.flags
    memory.stage(observation(7, [first]))
    second = week(7, action=ActionVector((2, 1, 2, 0, 1)), resources=PublicResources(3, 10, 1))
    updated, current = memory.accept(PublicWeekFeedback(second, first))
    assert updated.local_id == original.local_id and updated.revision == 2
    assert original.followup_window is None and updated.followup_window == second
    assert updated.status == "closed_two" and current.local_id == 2
    assert "followup_action_changed" in updated.flags and "capacity_changed" in updated.flags
    assert "truncated_followup" not in updated.flags
    with pytest.raises(FrozenInstanceError):
        original.status = "closed_two"
    assert "非因果" in updated.description and "实际执行[2, 1, 2, 0, 1]" in updated.description


def test_stage_and_accept_are_idempotent_without_re_emitting_revisions():
    memory = PublicEpisodeMemory()
    initial = observation()
    memory.stage(initial)
    memory.stage(initial)
    feedback = PublicWeekFeedback(week(0))
    assert len(memory.accept(feedback)) == 1
    memory.stage(initial)
    assert memory.accept(feedback) == ()
    assert len(memory.latest_revisions) == 1
    memory.stage(observation(7, [feedback.week]))
    assert memory.accept(feedback) == ()
    assert memory.pending_observation.decision_day == 7


@pytest.mark.parametrize("mutation", [
    lambda o: replace(o, initial_infections=3),
    lambda o: replace(o, resources=PublicResources(2, 9, 1)),
])
def test_conflicting_repeated_stage_is_fatal(mutation):
    memory = PublicEpisodeMemory()
    memory.stage(observation())
    with pytest.raises(ValueError, match="conflicting"):
        memory.stage(mutation(observation()))
    assert memory.latest_revisions == ()


def test_pending_or_unpaired_windows_cannot_advance():
    memory = PublicEpisodeMemory()
    with pytest.raises(ValueError, match="staged"):
        memory.accept(PublicWeekFeedback(week(0)))
    memory.stage(observation())
    with pytest.raises(ValueError, match="pending"):
        memory.stage(observation(7, [week(0)]))
    with pytest.raises(ValueError, match="window"):
        memory.accept(PublicWeekFeedback(week(7)))
    with pytest.raises(ValueError, match="window"):
        memory.accept(PublicWeekFeedback(replace(week(0), end_day=5)))
    assert memory.latest_revisions == () and memory.pending_observation == observation()


def test_previous_week_must_match_observation_and_duplicate_payload():
    memory = PublicEpisodeMemory()
    first = week(0)
    memory.stage(observation())
    memory.accept(PublicWeekFeedback(first))
    with pytest.raises(ValueError, match="conflicting"):
        memory.accept(PublicWeekFeedback(replace(first, delivered_diagnoses=99)))
    memory.stage(observation(7, [first]))
    with pytest.raises(ValueError, match="previous_week"):
        memory.accept(PublicWeekFeedback(week(7)))
    with pytest.raises(ValueError, match="previous_week"):
        memory.accept(PublicWeekFeedback(week(7), replace(first, delivered_diagnoses=99)))
    assert len(memory.latest_revisions) == 1


def test_h110_terminal_tail_preserves_actual_stored_days_and_truncates_previous_followup():
    memory = PublicEpisodeMemory()
    weeks = []
    originals = []
    for day in range(0, 110, 7):
        memory.stage(observation(day, weeks, horizon=110))
        closed = week(day, horizon=110)
        emitted = memory.accept(PublicWeekFeedback(closed, weeks[-1] if weeks else None))
        originals.append(emitted[-1])
        weeks.append(closed)
    latest = memory.latest_revisions
    assert len(latest) == 16
    assert latest[-1].window_days == 5  # 105..109 inclusive, with no day-110 decision.
    assert latest[-1].status == "terminal_censored"
    assert set(latest[-1].flags) >= {"partial_window", "truncated_followup"}
    assert latest[-2].status == "closed_two" and "truncated_followup" in latest[-2].flags
    assert all(item.revision == 1 for item in originals)
    with pytest.raises(ValueError, match="executable"):
        memory.stage(replace(observation(105, weeks[:-1], horizon=110), decision_day=110))
    assert memory.pending_observation is None


def test_reset_discards_pending_dedup_and_ids_without_touching_external_store():
    memory = PublicEpisodeMemory()
    memory.stage(observation())
    first = PublicWeekFeedback(week(0))
    memory.accept(first)
    memory.stage(observation(7, [first.week]))
    memory.reset()
    assert memory.latest_revisions == () and memory.pending_observation is None
    memory.stage(observation())
    assert memory.accept(first)[0].local_id == 1


@pytest.mark.parametrize("value", [{}, object(), PrivateMetrics(0, 6, 2, 2, 4, 1, 1)])
def test_memory_requires_exact_public_input(value):
    memory = PublicEpisodeMemory()
    for operation in (memory.stage, memory.accept, memory.recent):
        with pytest.raises(TypeError):
            operation(value)
    with pytest.raises(TypeError, match="public payload"):
        public_to_dict(PrivateMetrics(0, 6, 2, 2, 4, 1, 1))


def test_stage_rejects_missing_or_stale_history_and_changed_task():
    memory = PublicEpisodeMemory()
    with pytest.raises(ValueError, match="complete public history"):
        memory.stage(observation(7))
    first = week(0)
    memory.stage(observation())
    memory.accept(PublicWeekFeedback(first))
    with pytest.raises(ValueError, match="task constants"):
        memory.stage(replace(observation(7, [first]), execution_days=110))
    with pytest.raises(ValueError, match="last accepted"):
        memory.stage(observation(14, [first, week(7)]))
    assert memory.pending_observation is None


def test_recent_summary_uses_only_observation_and_has_hand_calculated_fields():
    weeks = [week(index * 7, diagnoses=count, tests=tests) for index, (count, tests) in enumerate([(2, 4), (20, 5)])]
    current = observation(14, weeks, resources=PublicResources(2, 9, 1))
    summary = recent_summary(current)
    assert summary.valid_week_count == 2 and summary.trend_direction == "up"
    assert summary.windows[-1].tests == 5 and summary.windows[-1].proxy == 4
    assert summary.windows[-1].activity_person_days == 12
    assert summary.windows[-1].union_person_days == 7
    assert summary.capacity_changed and not summary.testing_changed  # exactly 25% is not >25%.
    changed = replace(current, history=current.history[:3] + (week(7, tests=6),))
    assert recent_summary(changed).testing_changed
    assert PublicEpisodeMemory().recent(current) == summary
    assert recent_summary(observation()).flags == ("partial_observability", "no_history")
    assert recent_summary(observation(7, [week(0, tests=0)])).windows[0].proxy_valid is False
    assert recent_summary(observation(14, [week(0, tests=0), week(7, tests=1)])).testing_changed


def test_recent_never_adds_a_fifth_week_from_episode_cache():
    memory = PublicEpisodeMemory()
    weeks = []
    for day in range(0, 35, 7):
        memory.stage(observation(day, weeks))
        closed = week(day)
        memory.accept(PublicWeekFeedback(closed, weeks[-1] if weeks else None))
        weeks.append(closed)
    recent = memory.recent(observation(35, weeks))
    assert len(memory.latest_revisions) == 5
    assert [item.start_day for item in recent.windows] == [7, 14, 21, 28]


def test_public_case_round_trip_validates_hashes_and_all_nested_allowlists():
    memory = PublicEpisodeMemory()
    memory.stage(observation())
    (local,) = memory.accept(PublicWeekFeedback(week(0)))
    case = public_case(local)
    assert public_case_from_dict(public_to_dict(case)) == case
    assert local_case_from_dict(public_to_dict(local)) == local
    assert observation_from_dict(public_to_dict(observation())) == observation()
    assert feedback_from_dict(public_to_dict(PublicWeekFeedback(week(0)))) == PublicWeekFeedback(week(0))
    for location in ((), ("pre_observation",), ("pre_observation", "population"),
                     ("executed_window", "cost"), ("executed_window", "resources"), ("public_source",)):
        payload = public_to_dict(case)
        target = payload
        for name in location:
            target = target[name]
        target["private_reward"] = 5
        with pytest.raises((ValueError, TypeError)):
            public_case_from_dict(payload)
    changed = public_to_dict(case)
    changed["executed_window"]["delivered_diagnoses"] = 99
    with pytest.raises(ValueError, match="public_source"):
        public_case_from_dict(changed)
    with pytest.raises(TypeError):
        case.public_source["kind"] = "test"


def test_case_metadata_cannot_claim_causality_duration_or_wrong_revision():
    memory = PublicEpisodeMemory()
    memory.stage(observation())
    case = public_case(memory.accept(PublicWeekFeedback(week(0)))[0])
    for changes in ({"attribution": "caused_success"}, {"window_days": 6}, {"revision": 2},
                    {"available_through_day": 99}, {"status": "terminal_censored"},
                    {"flags": ("reward_success",)}):
        with pytest.raises(ValueError):
            replace(case, **changes)


@pytest.mark.parametrize("literal", ['{"a":1,"a":2}', '{"n":NaN}', '{"n":Infinity}', '{"n":-Infinity}', '{"n":1e999}'])
def test_strict_json_rejects_duplicate_or_nonfinite_values(literal):
    with pytest.raises(ValueError):
        strict_json_loads(literal)


def test_profile_is_separate_strict_immutable_and_content_identified(tmp_path):
    profile = load_memory_profile()
    assert len(profile.retrieval["state_scales"]) == 38
    assert profile.retrieval["state_weight"] == 0.75
    assert profile.retrieval["trend_weight"] == 0.25
    assert profile.retrieval["capacity_ratio_tolerances"] == (0.01, 0.03, 0.005)
    relocated = tmp_path / "different-name.json"
    relocated.write_text(DEFAULT_PROFILE_PATH.read_text(encoding="utf-8-sig"), encoding="utf-8")
    assert load_memory_profile(relocated).sha256 == profile.sha256
    with pytest.raises(TypeError):
        profile.retrieval["top_k"] = 99
    assert profile.resource_path("template_path").name == "public_memory_v1.json"
    for changes in ({"embedding": "forbidden"}, {"short_term_window": 5}, {"schema_version": "old"},
                    {"template_path": "../private/file"}):
        with pytest.raises(ValueError):
            MemoryProfile({**public_to_dict(profile.data), **changes})
    for key, value in (("top_k", 7), ("state_weight", 0.4), ("maximum_per_group", 2),
                       ("state_scales", [1] * 37), ("state_scales", [0] * 38)):
        data = public_to_dict(profile.data)
        data["retrieval"][key] = value
        with pytest.raises((ValueError, TypeError)):
            MemoryProfile(data)


def test_semantic_public_task_hash_ignores_registration_and_prompt_but_includes_horizon():
    protocol = load_protocol(DEFAULT_PROFILE_PATH.with_name("control_protocol_v1.json"))
    config = make_public_prompt_config(protocol)
    task_hash = public_task_hash(config, 112)
    spec = public_to_dict(config.public_spec)
    spec["objective"]["status"] = "frozen"
    assert public_task_hash(replace(config, public_spec=spec), 112) == task_hash
    assert public_task_hash(replace(config, reason_max_chars=119), 112) == task_hash
    template = public_to_dict(config.template)
    template["version"] = "another-prompt"
    assert public_task_hash(replace(config, template=template), 112) == task_hash
    assert public_task_hash(config, 110) != task_hash
    spec["objective"]["lambda"] += 0.1
    assert public_task_hash(replace(config, public_spec=spec), 112) != task_hash
    with pytest.raises(TypeError):
        public_task_hash(config.public_spec, 112)


def test_context_decoders_enforce_mode_and_do_not_accept_extra_private_keys():
    recent = recent_summary(observation())
    disabled = RetrievalResult("empty", flags=("disabled",))
    context = PublicMemoryContext("short", recent, (), disabled)
    assert memory_context_from_dict(public_to_dict(context)) == context
    assert recent_summary_from_dict(public_to_dict(recent)) == recent
    with pytest.raises(ValueError, match="recent-summary"):
        PublicMemoryContext("none", recent, (), disabled)
    with pytest.raises(ValueError, match="disabled"):
        PublicMemoryContext("short", recent, (), RetrievalResult("unavailable"))
    payload = public_to_dict(context)
    payload["private_metrics"] = {}
    with pytest.raises(ValueError):
        memory_context_from_dict(payload)


@pytest.mark.parametrize("values", [[0]*4, [True,0,0,0,0], [3,0,0,0,0], "00000"])
def test_observation_decoder_preserves_action_validation(values):
    payload = public_to_dict(observation())
    payload["current_action"]["values"] = values
    with pytest.raises((TypeError, ValueError)):
        observation_from_dict(payload)


def test_canonical_json_hash_matches_public_observation_audit():
    from cemas.control.logging import hash_observation
    initial = observation()
    assert public_hash(initial) == hash_observation(initial)
    assert canonical_json(public_to_dict(initial)) == canonical_json(initial)
    assert public_hash({"a": -0.0}) == public_hash({"a": 0.0})

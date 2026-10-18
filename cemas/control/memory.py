"""Deterministic episode memory and separately versioned Phase 5 configuration.

The state machine receives only exact public observations and feedback. It never
reads a proposal, reward, private runner record, model response, or simulator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from .memory_types import (
    ARCHITECTURE_VERSION, FEATURE_VERSION, MEMORY_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION, RETRIEVAL_VERSION, LocalCaseRevision, RecentSummary,
    RecentWindow, _exact, _integer, _number, _sequence, immutable_json, public_hash,
    public_to_dict, strict_json_loads,
)
from .types import SCHEMA_VERSION, PublicObservation, PublicWeekFeedback


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "docs" / "control_memory_v1.json"
_PROFILE_FIELDS = (
    "schema_version", "architecture_version", "response_schema_version",
    "template_path", "knowledge_path", "short_term_window", "trend_window",
    "retrieval", "budget_policy",
)
_RETRIEVAL_FIELDS = (
    "configuration_version", "feature_version", "state_scales", "trend_scales",
    "state_weight", "trend_weight", "minimum_valid_overlap", "maximum_state_rms",
    "minimum_score", "capacity_ratio_tolerances", "candidate_pool_size", "top_k",
    "maximum_per_action", "maximum_per_group", "redundancy_penalty",
    "conflict_minimum_state_score", "conflict_minimum_diagnosis_change",
)


def _validate_retrieval_config(retrieval):
    """Apply the same Phase 5 contract to profiles and direct retrievers."""
    _exact(retrieval, _RETRIEVAL_FIELDS, "retrieval profile")
    if retrieval["configuration_version"] != RETRIEVAL_VERSION or retrieval["feature_version"] != FEATURE_VERSION:
        raise ValueError("unsupported retrieval or feature version")
    for key, length in (("state_scales", 38), ("trend_scales", 5), ("capacity_ratio_tolerances", 3)):
        for value in _sequence(retrieval[key], key, length=length):
            _number(value, key, minimum=0)
            if key != "capacity_ratio_tolerances" and value == 0:
                raise ValueError("feature scales must be positive")
    for key in ("state_weight", "trend_weight", "minimum_valid_overlap", "minimum_score",
                "redundancy_penalty", "conflict_minimum_state_score"):
        _number(retrieval[key], key, minimum=0, maximum=1)
    if abs(retrieval["state_weight"] + retrieval["trend_weight"] - 1) > 1e-12 or retrieval["state_weight"] <= 0:
        raise ValueError("retrieval weights must sum to one with positive state weight")
    if retrieval["minimum_valid_overlap"] == 0:
        raise ValueError("valid overlap must be positive")
    _number(retrieval["maximum_state_rms"], "maximum_state_rms", minimum=0)
    for key in ("candidate_pool_size", "top_k", "maximum_per_action", "maximum_per_group",
                "conflict_minimum_diagnosis_change"):
        _integer(retrieval[key], key, minimum=1)
    if retrieval["candidate_pool_size"] != 24 or retrieval["top_k"] > 6:
        raise ValueError("Phase 5 requires a 24-candidate pool and at most six selected cases")
    if retrieval["maximum_per_action"] > 2 or retrieval["maximum_per_group"] != 1:
        raise ValueError("Phase 5 diversity limits cannot be relaxed")


@dataclass(frozen=True, slots=True)
class MemoryProfile:
    data: Mapping
    sha256: str = field(init=False)

    def __post_init__(self):
        data = self.data
        _exact(data, _PROFILE_FIELDS, "memory profile")
        for key, expected in (("schema_version", MEMORY_SCHEMA_VERSION),
                              ("architecture_version", ARCHITECTURE_VERSION),
                              ("response_schema_version", RESPONSE_SCHEMA_VERSION)):
            if data[key] != expected:
                raise ValueError(f"unsupported {key}")
        for key, expected in (("short_term_window", 4), ("trend_window", 3)):
            _integer(data[key], key, minimum=1)
            if data[key] != expected:
                raise ValueError(f"{key} differs from the Phase 5 public feature contract")
        for key in ("template_path", "knowledge_path"):
            value = data[key]
            if type(value) is not str or not value.strip():
                raise ValueError(f"{key} must be a project-relative resource path")
            path = PurePosixPath(value.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in value:
                raise ValueError(f"{key} must stay inside the project root")
        _validate_retrieval_config(data["retrieval"])
        budget = data["budget_policy"]
        _exact(budget, ("soft_input_target", "truncation_order", "preserve_conflict_pairs"), "budget policy")
        _integer(budget["soft_input_target"], "soft_input_target", minimum=1)
        if _sequence(budget["truncation_order"], "truncation_order") != ("cases", "external_knowledge", "recent"):
            raise ValueError("the deterministic budget truncation order cannot change")
        if budget["preserve_conflict_pairs"] is not True:
            raise ValueError("conflict pairs must be removed together")
        object.__setattr__(self, "data", immutable_json(data))
        object.__setattr__(self, "sha256", public_hash(data))

    @property
    def retrieval(self):
        return self.data["retrieval"]

    @property
    def configuration_version(self):
        return self.retrieval["configuration_version"]

    @property
    def budget_policy(self):
        return self.data["budget_policy"]

    @property
    def architecture_version(self):
        return self.data["architecture_version"]

    @property
    def schema_version(self):
        return self.data["schema_version"]

    @property
    def response_schema_version(self):
        return self.data["response_schema_version"]

    def resource_path(self, key, *, project_root=None):
        if key not in ("template_path", "knowledge_path"):
            raise ValueError("unknown memory resource path")
        root = Path(project_root) if project_root is not None else PROJECT_ROOT
        return root / self.data[key]


def load_memory_profile(path=None):
    """Load the independent profile; never read legacy protocol.memory defaults."""
    data = strict_json_loads(Path(path or DEFAULT_PROFILE_PATH).read_text(encoding="utf-8-sig"))
    return MemoryProfile(data)


def public_task_hash(prompt_config, execution_days):
    """Hash public task semantics, including H and excluding registration status.

    P4's own prompt/spec hashes are untouched. Template/reason limits and private
    protocol settings cannot affect the identity of public case task semantics.
    """
    from .llm import PublicPromptConfig

    if type(prompt_config) is not PublicPromptConfig:
        raise TypeError("task identity requires an exact PublicPromptConfig")
    _integer(execution_days, "execution_days", minimum=1)
    spec = public_to_dict(prompt_config.public_spec)
    del spec["objective"]["status"]
    return public_hash({"schema_version": SCHEMA_VERSION,
                        "execution_days": execution_days, "public_spec": spec})


def recent_summary(observation):
    """Pure display arithmetic over the four valid public weeks in this O only."""
    if type(observation) is not PublicObservation:
        raise TypeError("recent summary requires exact PublicObservation")
    weeks = tuple(week for week, valid in zip(observation.history, observation.week_valid) if valid)
    windows = tuple(RecentWindow(
        week.start_day, week.end_day, week.delivered_diagnoses,
        week.cost.clinical_tests + week.cost.screening_tests,
        week.cost.delivered_notifications, week.cost.union_person_days,
        week.cost.school_restriction_person_days + week.cost.work_restriction_person_days + week.cost.community_restriction_person_days,
        week.executed_action.values, week.resources, week.growth, week.growth_valid,
        week.diagnosis_test_proxy, week.proxy_valid,
    ) for week in weeks)
    capacity_changed = bool(weeks and observation.resources != weeks[-1].resources)
    testing_changed = False
    direction = "insufficient"
    if len(windows) >= 2:
        previous, latest = windows[-2:]
        testing_changed = abs(latest.tests - previous.tests) / max(previous.tests, 1) > 0.25
        change = latest.diagnoses - previous.diagnoses
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
    flags = ["partial_observability"]
    if not weeks:
        flags.append("no_history")
    if testing_changed:
        flags.append("testing_changed")
    if capacity_changed:
        flags.append("capacity_changed")
    return RecentSummary(observation.decision_day, len(windows), windows,
                         observation.current_action.values, observation.action_duration_days,
                         capacity_changed, testing_changed, direction, tuple(flags))


def case_flags(pre_observation, executed_window, followup_window=None):
    """Describe observed changes without reward, hidden infection, or causal labels."""
    if type(pre_observation) is not PublicObservation:
        raise TypeError("case flags require exact PublicObservation")
    baseline = next((week for week, valid in zip(reversed(pre_observation.history), reversed(pre_observation.week_valid)) if valid), None)
    flags = []
    if baseline is None:
        flags.append("missing_baseline")
    else:
        before_tests = baseline.cost.clinical_tests + baseline.cost.screening_tests
        after_tests = executed_window.cost.clinical_tests + executed_window.cost.screening_tests
        if abs(after_tests - before_tests) / max(before_tests, 1) > 0.25:
            flags.append("testing_changed")
    if executed_window.resources != pre_observation.resources or (baseline is not None and baseline.resources != executed_window.resources):
        flags.append("capacity_changed")
    if executed_window.executed_action != pre_observation.current_action:
        flags.append("action_changed")
    if followup_window is not None:
        if followup_window.executed_action != executed_window.executed_action:
            flags.append("followup_action_changed")
        if followup_window.resources != executed_window.resources and "capacity_changed" not in flags:
            flags.append("capacity_changed")
        tests1 = executed_window.cost.clinical_tests + executed_window.cost.screening_tests
        tests2 = followup_window.cost.clinical_tests + followup_window.cost.screening_tests
        if abs(tests2 - tests1) / max(tests1, 1) > 0.25 and "testing_changed" not in flags:
            flags.append("testing_changed")
    if executed_window.end_day - executed_window.start_day != 6:
        flags.append("partial_window")
    if followup_window is None or followup_window.end_day - followup_window.start_day != 6:
        flags.append("truncated_followup")
    return tuple(flags)


def describe_case(pre_observation, executed_window, followup_window=None):
    """A fixed, reproducible descriptive template; no LLM reflection is involved."""
    if type(pre_observation) is not PublicObservation:
        raise TypeError("case descriptions require exact PublicObservation")
    week = executed_window
    cost = week.cost
    tests = cost.clinical_tests + cost.screening_tests
    activity = cost.school_restriction_person_days + cost.work_restriction_person_days + cost.community_restriction_person_days
    baseline = next((item for item, valid in zip(reversed(pre_observation.history), reversed(pre_observation.week_valid)) if valid), None)
    before = f"最近完整周交付诊断{baseline.delivered_diagnoses}" if baseline is not None else "无已完成完整周"
    if followup_window is None:
        after = "后窗尚未交付"
    else:
        after = (f"后窗{followup_window.start_day}至{followup_window.end_day}日实际执行"
                 f"{list(followup_window.executed_action.values)}，交付诊断{followup_window.delivered_diagnoses}")
    return (f"在公开状态（{before}）实际执行{list(week.executed_action.values)}持续"
            f"{week.end_day - week.start_day + 1}日；随后交付诊断{week.delivered_diagnoses}，"
            f"实际检测{tests}，通知{cost.delivered_notifications}，并集{cost.union_person_days:g}人天，"
            f"活动{activity:g}人天；{after}；这些是关联记录，非因果估计。")


class PublicEpisodeMemory:
    """Pair staged O with actual public execution; publish immutable revisions."""

    __slots__ = ("_pending", "_staged", "_accepted", "_waiting", "_last_feedback", "_next_id", "_latest_revisions")

    def __init__(self):
        self.reset()

    def reset(self):
        self._pending = None
        self._staged = {}
        self._accepted = {}
        self._waiting = None
        self._last_feedback = None
        self._next_id = 1
        self._latest_revisions = {}

    @property
    def latest_revisions(self):
        return tuple(self._latest_revisions[key] for key in sorted(self._latest_revisions))

    @property
    def pending_observation(self):
        return self._pending[1] if self._pending is not None else None

    def stage(self, observation):
        if type(observation) is not PublicObservation:
            raise TypeError("memory stage requires exact PublicObservation")
        day = observation.decision_day
        if day >= observation.execution_days or day % 7:
            raise ValueError("memory may stage only executable weekly decisions")
        digest = public_hash(observation)
        if day in self._staged:
            if digest != self._staged[day]:
                raise ValueError("the same decision day has conflicting public observations")
            return
        if self._pending is not None:
            raise ValueError("the pending public decision must be closed before staging a new day")
        weeks = tuple(week for week, valid in zip(observation.history, observation.week_valid) if valid)
        expected_count = min(day // 7, 4)
        if len(weeks) != expected_count or (weeks and weeks[-1].end_day != day - 1):
            raise ValueError("staged observation lacks the current complete public history")
        if self._last_feedback is not None:
            previous = self._last_feedback.week
            if day != previous.end_day + 1 or previous != weeks[-1]:
                raise ValueError("new observation must follow the last accepted public window")
            known_windows = {case.executed_window.start_day: case.executed_window
                             for case in self._latest_revisions.values()}
            if any(week.start_day in known_windows and week != known_windows[week.start_day] for week in weeks):
                raise ValueError("staged history conflicts with previously accepted public windows")
            prior_observation = self._latest_revisions[max(self._latest_revisions)].pre_observation
            if (observation.execution_days != prior_observation.execution_days
                    or observation.population != prior_observation.population
                    or observation.initial_infections != prior_observation.initial_infections):
                raise ValueError("public task constants cannot change within an episode")
        self._pending = (self._next_id, observation)
        self._next_id += 1
        self._staged[day] = digest

    def accept(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("memory accept requires exact PublicWeekFeedback")
        digest = public_hash(feedback)
        day = feedback.week.start_day
        if day in self._accepted:
            if self._accepted[day] != digest:
                raise ValueError("duplicate public feedback has conflicting content")
            return ()
        if self._pending is None:
            raise ValueError("public feedback requires a staged decision")
        local_id, observation = self._pending
        expected_end = min(observation.decision_day + 6, observation.execution_days - 1)
        if day != observation.decision_day or feedback.week.end_day != expected_end:
            raise ValueError("public feedback does not match the staged execution window")
        previous = next((week for week, valid in zip(reversed(observation.history), reversed(observation.week_valid)) if valid), None)
        if feedback.previous_week != previous:
            raise ValueError("feedback previous_week must equal the staged observation's latest public week")
        emitted = []
        if self._waiting is not None:
            waiting = self._waiting
            if waiting.executed_window.end_day + 1 != feedback.week.start_day:
                raise ValueError("followup must be the adjacent actual public window")
            updated = replace(waiting, revision=2, followup_window=feedback.week, status="closed_two",
                              flags=case_flags(waiting.pre_observation, waiting.executed_window, feedback.week),
                              description=describe_case(waiting.pre_observation, waiting.executed_window, feedback.week))
            emitted.append(updated)
        status = "terminal_censored" if feedback.week.end_day == observation.execution_days - 1 else "closed_one"
        current = LocalCaseRevision(local_id, 1, observation, feedback.week, None, status,
                                    case_flags(observation, feedback.week),
                                    describe_case(observation, feedback.week))
        emitted.append(current)
        # Mutate only after all new public revisions have validated successfully.
        for revision in emitted:
            self._latest_revisions[revision.local_id] = revision
        self._waiting = None if status == "terminal_censored" else current
        self._pending = None
        self._last_feedback = feedback
        self._accepted[day] = digest
        return tuple(emitted)

    def recent(self, observation):
        return recent_summary(observation)

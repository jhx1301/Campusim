"""Immutable public Phase 5 contracts and exact JSON allow-list decoders.

Only the explicit public dataclasses in this module and ``types`` can pass the
serializer. In particular, a runner record or private metrics object cannot be
serialized by virtue of merely being a dataclass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
import hashlib
import json
from math import isfinite
from types import MappingProxyType

from .types import (ActionVector, PublicCost, PublicObservation,
                    PublicPopulation, PublicResources, PublicWeekFeedback,
                    PublicWeeklyRecord, _action_id)


CASE_SCHEMA_VERSION = "cemas-public-case-v2"
QUERY_SCHEMA_VERSION = "cemas-case-query-v1"
MEMORY_SCHEMA_VERSION = "cemas-control-memory-v1"
ARCHITECTURE_VERSION = "numeric-public-memory-v1"
RESPONSE_SCHEMA_VERSION = "cemas-public-decision-v1"
FEATURE_VERSION = "cemas-public-case-features-v1"
RETRIEVAL_VERSION = "numeric-retrieval-v1"
CASE_FLAGS = ("testing_changed", "capacity_changed", "action_changed",
              "partial_window", "conflicting_peer")
UNCERTAINTY_CODES = ("partial_observability", "no_history", "testing_changed",
                     "capacity_changed", "no_case", "case_conflict",
                     "out_of_support")


def _exact(value, expected, name):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"{name} has invalid fields")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{name} keys must be strings")


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an ordinary integer >= {minimum}")


def _number(value, name, *, minimum=None, maximum=None):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be a finite number in range")


def _digest(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _text(value, name):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _sequence(value, name, *, length=None):
    if type(value) not in (tuple, list) or (length is not None and len(value) != length):
        raise TypeError(f"{name} must be a sequence" + (f" of length {length}" if length is not None else ""))
    return tuple(value)


def _flags(value, allowed=None, name="flags"):
    result = _sequence(value, name)
    if any(type(flag) is not str or not flag for flag in result) or len(set(result)) != len(result):
        raise ValueError(f"{name} must contain distinct text values")
    if allowed is not None and any(flag not in allowed for flag in result):
        raise ValueError(f"{name} contains an unknown value")
    return result


def immutable_json(value):
    """Detach and recursively freeze JSON data; reject unknown runtime objects."""
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType({key: immutable_json(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(immutable_json(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        _number(value, "JSON number")
        return 0.0 if value == 0 else value
    raise TypeError("only JSON-compatible public values are accepted")


def _latest(observation):
    return next((week for week, valid in zip(reversed(observation.history), reversed(observation.week_valid)) if valid), None)


def _validate_case_window(pre, executed, status):
    if status != "closed":
        raise ValueError("a delivered single-week case must be closed")
    if type(pre) is not PublicObservation or type(executed) is not PublicWeeklyRecord:
        raise TypeError("cases require exact public observation and weekly record types")
    if pre.decision_day >= pre.execution_days or pre.decision_day % 7:
        raise ValueError("case pre-state must be an executable weekly decision")
    if executed.start_day != pre.decision_day or executed.end_day != min(pre.decision_day + 6, pre.execution_days - 1):
        raise ValueError("executed window does not match the public decision horizon")
    if not pre.legal_action_mask[_action_id(executed.executed_action.values)]:
        raise ValueError("actual executed action must be legal under its public pre-state")


@dataclass(frozen=True, slots=True)
class RecentWindow:
    start_day: int
    end_day: int
    diagnoses: int
    tests: int | None
    notifications: int | None
    union_person_days: float
    activity_person_days: float | None
    executed_action: tuple[int, ...] | None
    resources: PublicResources | None
    growth: float
    growth_valid: bool
    proxy: float
    proxy_valid: bool

    def __post_init__(self):
        for name in ("start_day", "end_day"):
            if type(getattr(self, name)) is not int:
                raise ValueError("window dates must be integers")
        for name in ("diagnoses", "tests", "notifications"):
            if getattr(self, name) is not None:
                _integer(getattr(self, name), name)
        if self.end_day != self.start_day + 6:
            raise ValueError("recent windows must contain exactly seven completed days")
        for name in ("union_person_days", "activity_person_days", "proxy"):
            if getattr(self, name) is not None:
                _number(getattr(self, name), name, minimum=0)
        _number(self.growth, "growth")
        if self.executed_action is not None:
            object.__setattr__(self, "executed_action", ActionVector(self.executed_action).values)
        if self.resources is not None and type(self.resources) is not PublicResources:
            raise TypeError("resources must be PublicResources")
        if type(self.growth_valid) is not bool or type(self.proxy_valid) is not bool:
            raise TypeError("validity values must be booleans")
        if (not self.growth_valid and self.growth != 0) or (not self.proxy_valid and self.proxy != 0):
            raise ValueError("invalid measurements must be zero-filled")


@dataclass(frozen=True, slots=True)
class RecentSummary:
    decision_day: int
    valid_week_count: int
    windows: tuple[RecentWindow, ...]
    current_action: tuple[int, ...]
    action_duration_days: tuple[int, ...]
    capacity_changed: bool
    testing_changed: bool
    trend_direction: str
    flags: tuple[str, ...] = ()

    def __post_init__(self):
        _integer(self.decision_day, "decision_day")
        _integer(self.valid_week_count, "valid_week_count")
        windows = _sequence(self.windows, "windows")
        if len(windows) != self.valid_week_count or len(windows) > 4 or any(type(window) is not RecentWindow for window in windows):
            raise ValueError("recent summary must contain its zero to four exact public windows")
        for index, window in enumerate(windows):
            if window.end_day >= self.decision_day or (index and window.start_day != windows[index - 1].end_day + 1):
                raise ValueError("recent windows must be chronological completed observations")
        durations = _sequence(self.action_duration_days, "action_duration_days", length=5)
        for value in durations:
            _integer(value, "action_duration_days")
            if value > self.decision_day:
                raise ValueError("action duration exceeds elapsed days")
        if type(self.capacity_changed) is not bool or type(self.testing_changed) is not bool:
            raise TypeError("change markers must be booleans")
        if self.trend_direction not in ("up", "down", "flat", "insufficient"):
            raise ValueError("unknown diagnosis trend direction")
        object.__setattr__(self, "windows", windows)
        object.__setattr__(self, "current_action", ActionVector(self.current_action).values)
        object.__setattr__(self, "action_duration_days", durations)
        object.__setattr__(self, "flags", _flags(self.flags, UNCERTAINTY_CODES))


@dataclass(frozen=True, slots=True)
class LocalCaseRevision:
    local_id: int
    revision: int
    pre_observation: PublicObservation
    executed_week: PublicWeeklyRecord
    status: str
    flags: tuple[str, ...]
    description: str

    def __post_init__(self):
        _integer(self.local_id, "local_id", minimum=1)
        _integer(self.revision, "revision", minimum=1)
        _validate_case_window(self.pre_observation, self.executed_week, self.status)
        object.__setattr__(self, "flags", _flags(self.flags, CASE_FLAGS))
        _text(self.description, "description")

    @property
    def window_days(self):
        return self.executed_week.end_day - self.executed_week.start_day + 1

    @property
    def available_through_day(self):
        return self.executed_week.end_day


@dataclass(frozen=True, slots=True)
class PublicCase:
    case_id: int
    revision: int
    schema_version: str
    public_task_sha256: str
    pre_observation: PublicObservation
    executed_week: PublicWeeklyRecord
    window_days: int
    status: str
    available_through_day: int
    attribution: str
    flags: tuple[str, ...]
    description: str
    public_source: Mapping

    def __post_init__(self):
        _integer(self.case_id, "case_id", minimum=1)
        _integer(self.revision, "revision", minimum=1)
        if self.schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("unsupported public case schema")
        _digest(self.public_task_sha256, "public_task_sha256")
        _validate_case_window(self.pre_observation, self.executed_week, self.status)
        _integer(self.window_days, "window_days", minimum=1)
        _integer(self.available_through_day, "available_through_day")
        if self.window_days != self.executed_week.end_day - self.executed_week.start_day + 1:
            raise ValueError("window_days must equal the actual executed duration")
        if self.available_through_day != self.executed_week.end_day:
            raise ValueError("available_through_day must describe the latest delivered window")
        if self.attribution != "descriptive_not_causal":
            raise ValueError("public cases cannot assert causal or reward labels")
        object.__setattr__(self, "flags", _flags(self.flags, CASE_FLAGS))
        _text(self.description, "description")
        _exact(self.public_source, ("kind", "observation_sha256", "week_sha256"), "public_source")
        if self.public_source["kind"] != "source_simulation":
            raise ValueError("public source must be an audited source simulation")
        expected = {"observation_sha256": public_hash(self.pre_observation),
                    "week_sha256": public_hash(self.executed_week)}
        for key, digest in expected.items():
            if self.public_source[key] != digest:
                raise ValueError(f"public_source {key} does not match public content")
        object.__setattr__(self, "public_source", immutable_json(self.public_source))


@dataclass(frozen=True, slots=True)
class CaseQuery:
    schema_version: str
    public_task_sha256: str
    state: tuple[float, ...]
    state_valid: tuple[bool, ...]
    trend: tuple[tuple[float, ...], ...]
    trend_valid: tuple[tuple[bool, ...], ...]
    resources: PublicResources
    legal_action_mask: tuple[bool, ...]
    remaining_fraction: float

    def __post_init__(self):
        if self.schema_version != QUERY_SCHEMA_VERSION:
            raise ValueError("unsupported public query schema")
        _digest(self.public_task_sha256, "public_task_sha256")
        state = _sequence(self.state, "state", length=38)
        valid = _sequence(self.state_valid, "state_valid", length=38)
        trend = tuple(_sequence(row, "trend row", length=5) for row in _sequence(self.trend, "trend"))
        trend_valid = tuple(_sequence(row, "trend validity row", length=5) for row in _sequence(self.trend_valid, "trend_valid"))
        if len(trend) > 2 or len(trend) != len(trend_valid):
            raise ValueError("trend must contain at most two matching difference rows")
        for value in (*state, *(cell for row in trend for cell in row)):
            _number(value, "query measurement")
        if any(type(value) is not bool for value in (*valid, *(cell for row in trend_valid for cell in row))):
            raise TypeError("query valid masks must contain booleans")
        mask = _sequence(self.legal_action_mask, "legal_action_mask", length=324)
        if any(type(value) is not bool for value in mask) or not any(mask):
            raise ValueError("legal_action_mask must contain booleans and a legal action")
        if type(self.resources) is not PublicResources:
            raise TypeError("query resources must be PublicResources")
        _number(self.remaining_fraction, "remaining_fraction", minimum=0, maximum=1)
        for name, value in (("state", state), ("state_valid", valid), ("trend", trend), ("trend_valid", trend_valid), ("legal_action_mask", mask)):
            object.__setattr__(self, name, value)

    @property
    def has_history(self):
        return self.state_valid[0]


@dataclass(frozen=True, slots=True)
class RetrievalItem:
    case: PublicCase
    state_rms: float
    state_score: float
    trend_score: float | None
    final_score: float
    applicability_codes: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.case) is not PublicCase:
            raise TypeError("retrieval items must contain exact PublicCase records")
        _number(self.state_rms, "state_rms", minimum=0)
        for name in ("state_score", "final_score"):
            _number(getattr(self, name), name, minimum=0, maximum=1)
        if self.trend_score is not None:
            _number(self.trend_score, "trend_score", minimum=0, maximum=1)
        object.__setattr__(self, "applicability_codes", _flags(self.applicability_codes, name="applicability_codes"))


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    status: str
    items: tuple[RetrievalItem, ...] = ()
    flags: tuple[str, ...] = ()
    excluded_counts: Mapping = field(default_factory=dict)
    configuration_version: str = RETRIEVAL_VERSION

    def __post_init__(self):
        if self.status not in ("ok", "empty", "out_of_support", "unavailable"):
            raise ValueError("unknown retrieval status")
        items = _sequence(self.items, "items")
        if len(items) > 6 or any(type(item) is not RetrievalItem for item in items):
            raise ValueError("retrieval must contain at most six exact items")
        if len({item.case.case_id for item in items}) != len(items):
            raise ValueError("retrieval case IDs must be distinct")
        if bool(items) != (self.status == "ok"):
            raise ValueError("only successful retrieval may contain items")
        if not isinstance(self.excluded_counts, Mapping):
            raise TypeError("excluded_counts must be an object")
        for key, count in self.excluded_counts.items():
            _text(key, "exclusion reason")
            _integer(count, "exclusion count")
        _text(self.configuration_version, "configuration_version")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "flags", _flags(self.flags))
        object.__setattr__(self, "excluded_counts", immutable_json(self.excluded_counts))


@dataclass(frozen=True, slots=True)
class KnowledgeCard:
    id: str
    version: str
    kind: str
    source: Mapping
    statement: str
    preconditions: tuple[str, ...]
    limitations: tuple[str, ...]
    public_fields: tuple[str, ...]
    action_dimensions: tuple[str, ...]
    trigger: str
    priority: int
    conflict_group: str | None
    supersedes: tuple[str, ...]
    review_status: str

    def __post_init__(self):
        for name in ("id", "version", "kind", "statement", "trigger", "review_status"):
            _text(getattr(self, name), name)
        if self.kind not in ("simulation_rule", "real_guideline", "research_finding"):
            raise ValueError("unknown knowledge kind")
        if self.trigger not in ("always", "has_history", "testing_changed", "capacity_changed"):
            raise ValueError("knowledge trigger is outside the shared four-mode profile")
        if self.review_status != "reviewed":
            raise ValueError("only reviewed knowledge may enter a bundle")
        if self.conflict_group is not None:
            _text(self.conflict_group, "conflict_group")
        _integer(self.priority, "priority")
        if not isinstance(self.source, Mapping):
            raise TypeError("knowledge source must be an object")
        object.__setattr__(self, "source", immutable_json(self.source))
        for name in ("preconditions", "limitations", "public_fields", "action_dimensions", "supersedes"):
            object.__setattr__(self, name, _flags(getattr(self, name), name=name))
        if any(name not in ("T", "S", "C", "E", "A") for name in self.action_dimensions):
            raise ValueError("knowledge action dimensions must be public action names")


@dataclass(frozen=True, slots=True)
class PublicMemoryContext:
    mode: str
    recent: RecentSummary | None
    knowledge: tuple[KnowledgeCard, ...]
    retrieval: RetrievalResult

    def __post_init__(self):
        if self.mode not in ("none", "short", "global", "both"):
            raise ValueError("unknown memory mode")
        if self.recent is not None and type(self.recent) is not RecentSummary:
            raise TypeError("recent must be RecentSummary or None")
        if self.mode in ("none", "global") and self.recent is not None:
            raise ValueError("this mode must not send recent-summary text")
        knowledge = _sequence(self.knowledge, "knowledge")
        if any(type(card) is not KnowledgeCard for card in knowledge) or len({card.id for card in knowledge}) != len(knowledge):
            raise ValueError("knowledge must contain distinct exact cards")
        if type(self.retrieval) is not RetrievalResult:
            raise TypeError("retrieval must be RetrievalResult")
        if self.mode in ("none", "short") and (self.retrieval.items or self.retrieval.status != "empty" or "disabled" not in self.retrieval.flags):
            raise ValueError("disabled global memory must be explicitly identified")
        object.__setattr__(self, "knowledge", knowledge)


_PUBLIC_TYPES = (ActionVector, PublicCost, PublicPopulation, PublicResources,
                 PublicWeeklyRecord, PublicObservation, PublicWeekFeedback,
                 RecentWindow, RecentSummary, LocalCaseRevision, PublicCase,
                 CaseQuery, RetrievalItem, RetrievalResult, KnowledgeCard,
                 PublicMemoryContext)


def public_to_dict(value):
    """Serialize allow-listed public records without accepting private dataclasses."""
    if type(value) is PublicObservation:
        from .logging import public_observation_to_dict
        return public_observation_to_dict(value)
    if type(value) is PublicWeeklyRecord:
        from .public_history import week_values
        return week_values(value)
    if type(value) in _PUBLIC_TYPES:
        result = {item.name: public_to_dict(getattr(value, item.name)) for item in fields(value)}
        return result
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("public JSON keys must be strings")
        return {key: public_to_dict(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [public_to_dict(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        _number(value, "public number")
        return 0.0 if value == 0 else value
    raise TypeError("unsupported public payload type")


def canonical_json(value):
    return json.dumps(public_to_dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prompt_json(value):
    """Render a public request in its deliberately constructed prefix order."""
    return json.dumps(public_to_dict(value), ensure_ascii=False, sort_keys=False, separators=(",", ":"), allow_nan=False)


def public_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _record_dict(value, record_type):
    defaults = ({"snapshot_day": 0} if record_type is PublicObservation else
        {"historical": False, "total_tests": None} if record_type is PublicWeeklyRecord else {})
    if defaults and not (set(defaults) & set(value)):
        value = {**value, **defaults}
    _exact(value, (item.name for item in fields(record_type)), record_type.__name__)
    return dict(value)


def _action_from_dict(value):
    return ActionVector(**_record_dict(value, ActionVector))


def resources_from_dict(value):
    return PublicResources(**_record_dict(value, PublicResources))


def weekly_record_from_dict(value):
    values = _record_dict(value, PublicWeeklyRecord)
    if values["historical"]:
        # Native records keep placeholders; the historical flag hides them at every public projection.
        values["cost"] = {key: 0 if item is None else item for key, item in values["cost"].items()}
        values["resources"] = values["resources"] or public_to_dict(PublicResources())
        values["executed_action"] = values["executed_action"] or public_to_dict(ActionVector((0, 0, 0, 0, 0)))
    values["cost"] = PublicCost(**_record_dict(values["cost"], PublicCost))
    values["resources"] = resources_from_dict(values["resources"])
    values["executed_action"] = _action_from_dict(values["executed_action"])
    return PublicWeeklyRecord(**values)


def observation_from_dict(value):
    values = _record_dict(value, PublicObservation)
    population = _record_dict(values["population"], PublicPopulation)
    population["age_band_counts"] = _sequence(population["age_band_counts"], "age_band_counts", length=5)
    values["population"] = PublicPopulation(**population)
    values["resources"] = resources_from_dict(values["resources"])
    values["current_action"] = _action_from_dict(values["current_action"])
    values["action_duration_days"] = _sequence(values["action_duration_days"], "action_duration_days", length=5)
    values["legal_action_mask"] = _sequence(values["legal_action_mask"], "legal_action_mask", length=324)
    values["history"] = tuple(weekly_record_from_dict(week) for week in _sequence(values["history"], "history", length=4))
    values["week_valid"] = _sequence(values["week_valid"], "week_valid", length=4)
    return PublicObservation(**values)


def feedback_from_dict(value):
    values = _record_dict(value, PublicWeekFeedback)
    values["week"] = weekly_record_from_dict(values["week"])
    if values["previous_week"] is not None:
        values["previous_week"] = weekly_record_from_dict(values["previous_week"])
    return PublicWeekFeedback(**values)


def local_case_from_dict(value):
    values = _record_dict(value, LocalCaseRevision)
    values["pre_observation"] = observation_from_dict(values["pre_observation"])
    values["executed_week"] = weekly_record_from_dict(values["executed_week"])
    return LocalCaseRevision(**values)


def public_case_from_dict(value):
    values = _record_dict(value, PublicCase)
    values["pre_observation"] = observation_from_dict(values["pre_observation"])
    values["executed_week"] = weekly_record_from_dict(values["executed_week"])
    return PublicCase(**values)


def knowledge_card_from_dict(value):
    return KnowledgeCard(**_record_dict(value, KnowledgeCard))


def recent_summary_from_dict(value):
    values = _record_dict(value, RecentSummary)
    windows = []
    for item in _sequence(values["windows"], "windows"):
        window = _record_dict(item, RecentWindow)
        if window["resources"] is not None:
            window["resources"] = resources_from_dict(window["resources"])
        windows.append(RecentWindow(**window))
    values["windows"] = tuple(windows)
    return RecentSummary(**values)


def case_query_from_dict(value):
    values = _record_dict(value, CaseQuery)
    values["resources"] = resources_from_dict(values["resources"])
    return CaseQuery(**values)


def retrieval_result_from_dict(value):
    values = _record_dict(value, RetrievalResult)
    items = []
    for item in _sequence(values["items"], "items"):
        data = _record_dict(item, RetrievalItem)
        data["case"] = public_case_from_dict(data["case"])
        items.append(RetrievalItem(**data))
    values["items"] = tuple(items)
    return RetrievalResult(**values)


def memory_context_from_dict(value):
    values = _record_dict(value, PublicMemoryContext)
    if values["recent"] is not None:
        values["recent"] = recent_summary_from_dict(values["recent"])
    values["knowledge"] = tuple(knowledge_card_from_dict(card) for card in _sequence(values["knowledge"], "knowledge"))
    values["retrieval"] = retrieval_result_from_dict(values["retrieval"])
    return PublicMemoryContext(**values)


def strict_json_loads(text):
    """Reject duplicate fields and non-finite literals before schema decoding."""
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON object field")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("non-finite JSON constant")

    def finite_float(literal):
        value = float(literal)
        _number(value, "JSON number")
        return value

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)

"""Immutable public and private data contracts for control protocol v1."""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite
from typing import TypeAlias


SCHEMA_VERSION = "cemas-control-schema-v1"
ACTION_ORDER = ("T", "S", "C", "E", "A")
ACTION_SIZES = (3, 4, 3, 3, 3)
JOINT_ACTION_COUNT = 324
HISTORY_WEEKS = 4
AGE_BANDS = ((0, 16), (17, 23), (24, 30), (31, 60), (61, 99))


def _counts(**values: int) -> None:
    for name, value in values.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative ordinary integer")


def _measurements(**values: float) -> None:
    for name, value in values.items():
        try:
            valid = type(value) in (int, float) and isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"{name} must be a finite nonnegative number")


def _canonical_float(value: int | float) -> float:
    # Equal numeric inputs must produce identical public JSON, including -0.0.
    return 0.0 if value == 0 else float(value)


def _tuple(value: tuple, length: int, name: str) -> None:
    if type(value) is not tuple or len(value) != length:
        raise ValueError(f"{name} must be an immutable tuple of length {length}")


def _instance(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _window(start_day: int, end_day: int) -> None:
    _counts(start_day=start_day, end_day=end_day)
    if end_day < start_day:
        raise ValueError("end_day must not precede start_day")


def _reason(value: str | None) -> None:
    if value is None:
        return
    if type(value) is not str or not value.strip() or len(value) > 120:
        raise ValueError("reasoning must be nonempty text of at most 120 characters")
    if any(character in value for character in ("\n", "\r", "\u2028", "\u2029")):
        raise ValueError("reasoning must be a single line")


@dataclass(frozen=True, slots=True)
class ActionVector:
    """Extra policy levels in T/S/C/E/A order, relative to the fixed baseline.

    Level zero means no additional intervention. Baseline configuration belongs
    to the environment and is not part of this vector or PublicObservation.
    """

    values: tuple[int, int, int, int, int]

    def __post_init__(self) -> None:
        if type(self.values) not in (tuple, list):
            raise TypeError("action values must be a tuple or list")
        values = tuple(self.values)
        _tuple(values, len(ACTION_ORDER), "action values")
        for name, value, size in zip(ACTION_ORDER, values, ACTION_SIZES):
            if type(value) is not int or not 0 <= value < size:
                raise ValueError(f"{name} must be an ordinary integer in [0, {size})")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Controller output; LLM wire field 'reason' maps to reasoning."""

    action: ActionVector
    reasoning: str | None = None

    def __post_init__(self) -> None:
        _instance(self.action, ActionVector, "action")
        _reason(self.reasoning)


def _action_id(values: tuple[int, int, int, int, int]) -> int:
    """Return the protocol action id for an already validated action tuple."""
    t, s, c, e, a = values
    return ((((t * ACTION_SIZES[1] + s) * ACTION_SIZES[2] + c)
             * ACTION_SIZES[3] + e) * ACTION_SIZES[4] + a)


@dataclass(frozen=True, slots=True)
class ActionResolution:
    """Requested action and the action handed to the executor.

    This is a data contract only.  It deliberately performs no resource
    projection or fallback: a resolver in a later phase must decide whether
    the requested action can be executed and record the corresponding reason.
    """

    requested_action: ActionVector | None
    executed_action: ActionVector
    requested_action_id: int | None
    executed_action_id: int
    adjustment_reason: str | None = None
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if self.requested_action is not None:
            _instance(self.requested_action, ActionVector, "requested_action")
            if type(self.requested_action_id) is not int:
                raise TypeError("requested_action_id must be an integer when requested_action is set")
            if not 0 <= self.requested_action_id < JOINT_ACTION_COUNT:
                raise ValueError("requested_action_id must be in [0, 324)")
            expected = _action_id(self.requested_action.values)
            if self.requested_action_id != expected:
                raise ValueError("requested_action_id does not match requested_action")
        elif self.requested_action_id is not None:
            raise TypeError("requested_action_id must be None when requested_action is None")

        _instance(self.executed_action, ActionVector, "executed_action")
        if type(self.executed_action_id) is not int:
            raise TypeError("executed_action_id must be an ordinary integer")
        if not 0 <= self.executed_action_id < JOINT_ACTION_COUNT:
            raise ValueError("executed_action_id must be in [0, 324)")
        expected = _action_id(self.executed_action.values)
        if self.executed_action_id != expected:
            raise ValueError("executed_action_id does not match executed_action")

        for name in ("adjustment_reason", "fallback_reason"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be nonempty text or None")
        if self.requested_action is None and self.fallback_reason is None:
            raise ValueError("missing requested_action requires fallback_reason")
        if (self.requested_action is not None
                and self.requested_action != self.executed_action
                and self.adjustment_reason is None
                and self.fallback_reason is None):
            raise ValueError("changed executed_action requires adjustment or fallback reason")
        if (self.requested_action is not None
                and self.requested_action == self.executed_action
                and self.adjustment_reason is not None):
            raise ValueError("adjustment_reason requires a changed executed_action")


@dataclass(frozen=True, slots=True)
class PublicPopulation:
    """Registered aggregate counts; individual rosters remain executor-private."""

    population: int
    age_band_counts: tuple[int, int, int, int, int]
    school_population: int
    work_population: int
    school_work_population: int = 0

    def __post_init__(self) -> None:
        _counts(population=self.population, school_population=self.school_population,
                work_population=self.work_population,
                school_work_population=self.school_work_population)
        if self.population == 0:
            raise ValueError("population must be positive")
        _tuple(self.age_band_counts, len(AGE_BANDS), "age_band_counts")
        for value in self.age_band_counts:
            _counts(age_band_count=value)
        if sum(self.age_band_counts) != self.population:
            raise ValueError("age band counts must sum to population")
        if max(self.school_population, self.work_population) > self.population:
            raise ValueError("target populations cannot exceed population")
        if self.school_work_population > min(self.school_population, self.work_population):
            raise ValueError("school/work overlap cannot exceed either target population")
        if self.school_population + self.work_population - self.school_work_population > self.population:
            raise ValueError("school/work union cannot exceed population")


@dataclass(frozen=True, slots=True)
class PublicResources:
    """Current daily capacities; tracing capacity counts index investigations."""

    clinical_daily_capacity: int = 0
    screening_daily_capacity: int = 0
    tracing_daily_index_capacity: int = 0

    def __post_init__(self) -> None:
        _counts(clinical_daily_capacity=self.clinical_daily_capacity,
                screening_daily_capacity=self.screening_daily_capacity,
                tracing_daily_index_capacity=self.tracing_daily_index_capacity)


@dataclass(frozen=True, slots=True)
class PublicCost:
    """Executed test/notification counts and operational/activity person-days."""

    clinical_tests: int = 0
    screening_tests: int = 0
    delivered_notifications: int = 0
    isolation_person_days: float = 0.0
    quarantine_person_days: float = 0.0
    union_person_days: float = 0.0
    school_restriction_person_days: float = 0.0
    work_restriction_person_days: float = 0.0
    community_restriction_person_days: float = 0.0

    def __post_init__(self) -> None:
        _counts(clinical_tests=self.clinical_tests, screening_tests=self.screening_tests,
                delivered_notifications=self.delivered_notifications)
        measurements = {field.name: getattr(self, field.name) for field in fields(self)
                        if field.name.endswith("person_days")}
        _measurements(**measurements)
        for name, value in measurements.items():
            object.__setattr__(self, name, _canonical_float(value))
        if not (max(self.isolation_person_days, self.quarantine_person_days)
                <= self.union_person_days
                <= self.isolation_person_days + self.quarantine_person_days):
            raise ValueError("union person-days must describe the isolation/quarantine union")


@dataclass(frozen=True, slots=True)
class PublicWeeklyRecord:
    """Delivered and executed data in an inclusive model-day window."""

    start_day: int = 0
    end_day: int = 0
    delivered_diagnoses: int = 0
    cost: PublicCost = PublicCost()
    executed_action: ActionVector = ActionVector((0, 0, 0, 0, 0))
    resources: PublicResources = PublicResources()
    growth: float = 0.0
    growth_valid: bool = False
    diagnosis_test_proxy: float = 0.0
    proxy_valid: bool = False

    def __post_init__(self) -> None:
        _window(self.start_day, self.end_day)
        _counts(delivered_diagnoses=self.delivered_diagnoses)
        _instance(self.cost, PublicCost, "cost")
        _instance(self.executed_action, ActionVector, "executed_action")
        _instance(self.resources, PublicResources, "resources")
        try:
            valid_growth = type(self.growth) in (int, float) and isfinite(self.growth)
        except OverflowError:
            valid_growth = False
        if not valid_growth:
            raise ValueError("growth must be finite")
        _measurements(diagnosis_test_proxy=self.diagnosis_test_proxy)
        object.__setattr__(self, "growth", _canonical_float(self.growth))
        object.__setattr__(self, "diagnosis_test_proxy", _canonical_float(self.diagnosis_test_proxy))
        if type(self.growth_valid) is not bool or type(self.proxy_valid) is not bool:
            raise TypeError("growth_valid and proxy_valid must be booleans")
        if not self.growth_valid and self.growth != 0:
            raise ValueError("invalid growth must be zero-filled")
        if not self.proxy_valid and self.diagnosis_test_proxy != 0:
            raise ValueError("invalid diagnosis/test proxy must be zero-filled")


_EMPTY_WEEK = PublicWeeklyRecord()


@dataclass(frozen=True, slots=True)
class PublicObservation:
    """Controller allow-list. No simulator, private metrics, seeds or metadata."""

    decision_day: int
    execution_days: int
    initial_infections: int
    population: PublicPopulation
    resources: PublicResources
    current_action: ActionVector
    action_duration_days: tuple[int, int, int, int, int]
    legal_action_mask: tuple[bool, ...]
    history: tuple[PublicWeeklyRecord, ...] = (_EMPTY_WEEK,) * HISTORY_WEEKS
    week_valid: tuple[bool, bool, bool, bool] = (False,) * HISTORY_WEEKS
    previous_day_known_isolated: int = 0
    previous_day_known_quarantined: int = 0
    previous_day_known_union: int = 0

    def __post_init__(self) -> None:
        _counts(decision_day=self.decision_day, execution_days=self.execution_days,
                initial_infections=self.initial_infections,
                previous_day_known_isolated=self.previous_day_known_isolated,
                previous_day_known_quarantined=self.previous_day_known_quarantined,
                previous_day_known_union=self.previous_day_known_union)
        if self.execution_days == 0 or self.decision_day > self.execution_days:
            raise ValueError("decision_day must be within the announced task horizon")
        _instance(self.population, PublicPopulation, "population")
        _instance(self.resources, PublicResources, "resources")
        _instance(self.current_action, ActionVector, "current_action")
        _tuple(self.action_duration_days, len(ACTION_ORDER), "action_duration_days")
        for value in self.action_duration_days:
            _counts(action_duration=value)
            if value > self.decision_day:
                raise ValueError("action duration cannot exceed elapsed model days")
        _tuple(self.legal_action_mask, JOINT_ACTION_COUNT, "legal_action_mask")
        if (any(type(value) is not bool for value in self.legal_action_mask)
                or not any(self.legal_action_mask)):
            raise ValueError("legal_action_mask must contain booleans and a legal action")
        _tuple(self.history, HISTORY_WEEKS, "history")
        _tuple(self.week_valid, HISTORY_WEEKS, "week_valid")
        seen_valid = False
        previous_end = None
        for record, valid in zip(self.history, self.week_valid):
            _instance(record, PublicWeeklyRecord, "history record")
            if type(valid) is not bool:
                raise TypeError("week_valid must contain booleans")
            if not valid:
                if seen_valid or record != _EMPTY_WEEK:
                    raise ValueError("missing weeks must be zero-filled on the left")
                continue
            seen_valid = True
            if record.end_day - record.start_day != 6 or record.end_day >= self.decision_day:
                raise ValueError("history must contain completed seven-day public weeks")
            if previous_end is not None and record.start_day != previous_end + 1:
                raise ValueError("public history must be chronological and contiguous")
            previous_end = record.end_day
        if self.initial_infections > self.population.population:
            raise ValueError("initial infections cannot exceed population")
        if (self.previous_day_known_union > self.population.population
                or not (max(self.previous_day_known_isolated, self.previous_day_known_quarantined)
                        <= self.previous_day_known_union
                        <= self.previous_day_known_isolated + self.previous_day_known_quarantined)):
            raise ValueError("known union must describe the known isolation/quarantine union")


@dataclass(frozen=True, slots=True)
class PublicWeekFeedback:
    """A completed public execution window, including a possible terminal tail."""

    week: PublicWeeklyRecord
    previous_week: PublicWeeklyRecord | None = None

    def __post_init__(self) -> None:
        _instance(self.week, PublicWeeklyRecord, "week")
        if self.week.end_day - self.week.start_day > 6:
            raise ValueError("feedback window cannot exceed seven days")
        if self.previous_week is not None:
            _instance(self.previous_week, PublicWeeklyRecord, "previous_week")
            if self.previous_week.end_day >= self.week.start_day:
                raise ValueError("previous feedback must precede the completed window")


@dataclass(frozen=True, slots=True)
class PrivateMetrics:
    """True infection counts for reward/analysis only; never a public payload."""

    start_day: int
    end_day: int
    new_infections: int
    initial_infections: int
    cumulative_infections: int
    peak_daily_infections: int
    terminal_active_infections: int

    def __post_init__(self) -> None:
        _window(self.start_day, self.end_day)
        _counts(new_infections=self.new_infections, initial_infections=self.initial_infections,
                cumulative_infections=self.cumulative_infections,
                peak_daily_infections=self.peak_daily_infections,
                terminal_active_infections=self.terminal_active_infections)


@dataclass(frozen=True, slots=True)
class ExecutedAction:
    """Actual execution interval, not the controller's requested action."""

    start_day: int
    end_day: int
    action: ActionVector

    def __post_init__(self) -> None:
        _window(self.start_day, self.end_day)
        _instance(self.action, ActionVector, "action")


ExecutedActionHistory: TypeAlias = tuple[ExecutedAction, ...]

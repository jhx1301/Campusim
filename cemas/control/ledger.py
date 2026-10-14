"""Delivered public records, separated from simulation state and private metrics."""

from __future__ import annotations

from dataclasses import fields
from math import log2

from covasim import Analyzer

from .types import (
    HISTORY_WEEKS, ActionVector, PublicCost, PublicDailyRecord,
    PublicWeekFeedback, PublicWeeklyRecord,
)


class PublicLedger:
    """Append-only aggregate records; no simulator or execution object is stored."""

    __slots__ = ("_records",)

    def __init__(self, records: tuple[PublicDailyRecord, ...] = ()) -> None:
        if type(records) is not tuple:
            raise TypeError("records must be an immutable tuple")
        self._records: list[PublicDailyRecord] = []
        for record in records:
            self.append(record)

    def append(self, record: PublicDailyRecord) -> None:
        if type(record) is not PublicDailyRecord:
            raise TypeError("record must be PublicDailyRecord")
        if record.day != len(self._records):
            raise ValueError("public records must be contiguous from day zero")
        self._records.append(record)

    def snapshot(self) -> tuple[PublicDailyRecord, ...]:
        """An immutable view detached from future appends."""
        return tuple(self._records)

    def require_completed(self, decision_day: int) -> None:
        if type(decision_day) is not int or decision_day < 0:
            raise ValueError("decision_day must be a nonnegative ordinary integer")
        if len(self._records) < decision_day:
            raise ValueError("all days before decision_day must have completed public records")

    def aggregate_week(self, start_day: int, end_day: int) -> PublicWeeklyRecord:
        """Sum a closed window of at most seven completed model days."""
        if (type(start_day) is not int or type(end_day) is not int
                or start_day < 0 or not start_day <= end_day <= start_day + 6):
            raise ValueError("a public window must contain one to seven ordinary model days")
        self.require_completed(end_day + 1)
        records = self._records[start_day:end_day + 1]
        action, resources = records[0].executed_action, records[0].resources
        if any(record.executed_action != action or record.resources != resources
               for record in records):
            raise ValueError("a public window cannot mix executed actions or resources")
        cost = PublicCost(**{
            field.name: sum(getattr(record.cost, field.name) for record in records)
            for field in fields(PublicCost)
        })
        diagnoses = sum(record.delivered_diagnoses for record in records)
        growth_valid = end_day - start_day == 6 and start_day >= 7
        growth = 0.0
        if growth_valid:
            previous_diagnoses = sum(record.delivered_diagnoses
                                     for record in self._records[start_day - 7:start_day])
            growth = log2((diagnoses + 1) / (previous_diagnoses + 1))
        tests = cost.clinical_tests + cost.screening_tests
        return PublicWeeklyRecord(
            start_day=start_day, end_day=end_day, delivered_diagnoses=diagnoses,
            cost=cost, executed_action=action, resources=resources,
            growth=growth, growth_valid=growth_valid,
            diagnosis_test_proxy=diagnoses / tests if tests else 0.0,
            proxy_valid=tests > 0,
        )

    def full_history(self, decision_day: int) -> tuple[
        tuple[PublicWeeklyRecord, ...], tuple[bool, bool, bool, bool]
    ]:
        """Latest four complete day-zero-anchored weeks before the decision."""
        self.require_completed(decision_day)
        completed_weeks = decision_day // 7
        start_week = max(0, completed_weeks - HISTORY_WEEKS)
        weeks = tuple(self.aggregate_week(week * 7, week * 7 + 6)
                      for week in range(start_week, completed_weeks))
        missing = HISTORY_WEEKS - len(weeks)
        return ((PublicWeeklyRecord(),) * missing + weeks,
                (False,) * missing + (True,) * len(weeks))

    def feedback(self, start_day: int, end_day: int) -> PublicWeekFeedback:
        """Closed weekly feedback, including a terminal window shorter than seven days."""
        week = self.aggregate_week(start_day, end_day)
        previous = self.aggregate_week(start_day - 7, start_day - 1) if start_day >= 7 else None
        return PublicWeekFeedback(week, previous)

    def action_duration_days(self, decision_day: int, action: ActionVector) -> tuple[int, ...]:
        """Count each current level's uninterrupted, actually executed days."""
        self.require_completed(decision_day)
        if type(action) is not ActionVector:
            raise TypeError("action must be ActionVector")
        durations = []
        for dimension, level in enumerate(action.values):
            count = 0
            for record in reversed(self._records[:decision_day]):
                if record.executed_action.values[dimension] != level:
                    break
                count += 1
            durations.append(count)
        return tuple(durations)


class PublicLedgerAnalyzer(Analyzer):
    """Simulation adapter; only the resulting aggregate ledger goes to controllers."""

    def __init__(self, executor, label: str = "cemas-public-ledger") -> None:
        super().__init__(label=label)
        if not callable(getattr(executor, "finish_day", None)):
            raise TypeError("executor must provide finish_day(sim)")
        self._executor_label = executor.label
        self._executor = executor
        self.ledger = PublicLedger()

    def initialize(self, sim=None) -> None:
        if sim is None:
            raise ValueError("PublicLedgerAnalyzer requires a simulator")
        # Sim may copy its interventions separately from its analyzers.
        matches = [intervention for intervention in sim["interventions"]
                   if getattr(intervention, "label", None) == self._executor_label]
        if len(matches) != 1 or not callable(getattr(matches[0], "finish_day", None)):
            raise ValueError("exactly one matching execution intervention is required")
        self._executor = matches[0]
        self.ledger = PublicLedger()
        super().initialize(sim)

    def apply(self, sim) -> None:
        if not self.initialized:
            raise RuntimeError("PublicLedgerAnalyzer must be initialized")
        self.ledger.append(self._executor.finish_day(sim))

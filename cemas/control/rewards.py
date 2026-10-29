"""Independent finite-horizon rewards, for learners and private analysis only."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import fsum

from .protocol import ControlProtocol
from .types import ExecutedActionHistory, PrivateMetrics, PublicCost


class RewardCalculator(ABC):
    """Shared source-training and offline-evaluation reward interface."""

    @abstractmethod
    def compute(self, private_metrics: PrivateMetrics, public_cost: PublicCost,
                action_history: ExecutedActionHistory) -> float:
        """Compute from recorded inputs, without owning a simulator/controller."""


REWARD_COMPONENTS = ("infections", "tests", "notifications", "union", "activity")


@dataclass(frozen=True, slots=True)
class RewardBreakdown:
    """Normalized quantities and positive weighted costs in I/T/L/Q/A order."""

    normalized: tuple[float, float, float, float, float]
    weighted: tuple[float, float, float, float, float]

    @property
    def positive_cost(self) -> float:
        return fsum(self.weighted)

    @property
    def reward(self) -> float:
        return -self.positive_cost


class V1RewardCalculator(RewardCalculator):
    """One common objective; counts come from records, never action levels."""

    def __init__(self, protocol: ControlProtocol, population: int, execution_days: int):
        if type(protocol) is not ControlProtocol:
            raise TypeError("protocol must be ControlProtocol")
        if type(population) is not int or population <= 0:
            raise ValueError("population must be a positive ordinary integer")
        if type(execution_days) is not int or execution_days <= 0:
            raise ValueError("execution_days must be a positive ordinary integer")
        self.population = population
        self.execution_days = execution_days
        self._objective = protocol.definition["objective"]
        weights = self._objective["burden_weights"]
        self._weights = (1.0, *(self._objective["lambda"] * weights[name]
                                for name in REWARD_COMPONENTS[1:]))
        from .timing import normalization_days
        self.normalization_days = normalization_days(protocol, execution_days)
        nh = population * self.normalization_days
        self._denominators = (population,
                              self._objective["test_reference_daily_ratio"] * nh,
                              self._objective["notification_reference_daily_ratio"] * nh,
                              nh, nh)

    @property
    def configuration(self) -> dict:
        """A detached private manifest snapshot, including actual episode N/H."""
        return {
            "formula_version": self._objective["formula_version"],
            "status": self._objective["status"],
            "lambda": self._objective["lambda"],
            "burden_weights": dict(self._objective["burden_weights"]),
            "population": self.population, "execution_days": self.execution_days,
            **({"normalization_days": self.normalization_days} if self.normalization_days != self.execution_days else {}),
            "test_reference_daily_ratio": self._objective["test_reference_daily_ratio"],
            "notification_reference_daily_ratio": self._objective["notification_reference_daily_ratio"],
            "components": REWARD_COMPONENTS, "denominators": self._denominators,
            "gamma": 1, "reward_clip": False, "switch_penalty": 0,
            "initial_infections_in_reward": False,
        }

    def breakdown(self, private_metrics: PrivateMetrics, public_cost: PublicCost,
                  action_history: ExecutedActionHistory) -> RewardBreakdown:
        if type(private_metrics) is not PrivateMetrics or type(public_cost) is not PublicCost:
            raise TypeError("reward requires PrivateMetrics and PublicCost")
        if private_metrics.end_day >= self.execution_days:
            raise ValueError("reward window exceeds the episode horizon")
        if type(action_history) is not tuple or not action_history:
            raise ValueError("actual executed action history must cover the reward window")
        from .types import ExecutedAction
        next_day = private_metrics.start_day
        for action in action_history:
            if type(action) is not ExecutedAction or action.start_day != next_day:
                raise ValueError("executed action history must be contiguous over the reward window")
            next_day = action.end_day + 1
        if next_day != private_metrics.end_day + 1:
            raise ValueError("executed action history must cover the reward window exactly")
        raw = (private_metrics.new_infections,
               public_cost.clinical_tests + public_cost.screening_tests,
               public_cost.delivered_notifications,
               public_cost.union_person_days,
               fsum((public_cost.school_restriction_person_days,
                     public_cost.work_restriction_person_days,
                     public_cost.community_restriction_person_days)))
        normalized = tuple(value / scale for value, scale in zip(raw, self._denominators))
        weighted = tuple(value * weight for value, weight in zip(normalized, self._weights))
        return RewardBreakdown(normalized, weighted)

    def compute(self, private_metrics: PrivateMetrics, public_cost: PublicCost,
                action_history: ExecutedActionHistory) -> float:
        return self.breakdown(private_metrics, public_cost, action_history).reward

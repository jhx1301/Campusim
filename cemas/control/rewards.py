"""Private reward calculation contract; formula and weights await Phase 3."""

from abc import ABC, abstractmethod

from .types import ExecutedActionHistory, PrivateMetrics, PublicCost


class RewardCalculator(ABC):
    """Shared source-training and offline-evaluation reward interface."""

    @abstractmethod
    def compute(self, private_metrics: PrivateMetrics, public_cost: PublicCost,
                action_history: ExecutedActionHistory) -> float:
        """Compute from recorded inputs, without owning a simulator/controller."""

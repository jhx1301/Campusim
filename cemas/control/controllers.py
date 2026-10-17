"""Shared controller contracts and the two fixed v1 references."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMCallAudit

from .types import ActionProposal, ActionVector, PublicObservation, PublicWeekFeedback


class Controller(ABC):
    """Every frozen policy sees only public observations and public feedback."""

    @abstractmethod
    def reset(self) -> None:
        """Clear controller-local episode state."""

    @abstractmethod
    def decide(self, observation: PublicObservation) -> ActionProposal | None:
        """Propose an action without accessing a simulator or private reward."""

    @abstractmethod
    def observe(self, feedback: PublicWeekFeedback) -> None:
        """Accept a closed public execution window."""

    def consume_failure_reason(self) -> str | None:
        """Return and clear a decision failure for the common resolver."""
        return None

    def drain_call_audits(self) -> tuple["LLMCallAudit", ...]:
        """Deliver pending private call records to the runner."""
        return ()

    def drain_decision_evidence(self) -> tuple:
        """Deliver public decision evidence to the runner without receiving its audit."""
        return ()

    def drain_case_revisions(self) -> tuple:
        """Deliver completed public experience after observe(), including terminal tails."""
        return ()


class UniformLegalController(Controller):
    """Collection policy using an independent local random stream."""

    controller_type = "uniform_legal_independent_rng"

    def __init__(self, controller_seed=0):
        if type(controller_seed) is not int or controller_seed < 0:
            raise ValueError("controller_seed must be a nonnegative ordinary integer")
        self._controller_seed = controller_seed
        self.reset()

    def reset(self):
        import numpy as np
        self._rng = np.random.default_rng(self._controller_seed)

    def decide(self, observation):
        if type(observation) is not PublicObservation:
            raise TypeError("collection controllers require PublicObservation")
        from .actions import decode_action
        legal = tuple(i for i, value in enumerate(observation.legal_action_mask) if value)
        index = int(self._rng.choice(legal))
        return ActionProposal(decode_action(index), "Uniform legal collection policy")

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("collection controllers require PublicWeekFeedback")


class ActionDecoder(ABC):
    """RL adapters use this shared contract before returning ActionProposal."""

    @abstractmethod
    def decode(self, action_id: int) -> ActionVector:
        """Decode a joint id; resource legality and fallback belong to execution."""


class MinimumController(Controller):
    """Keep routine baseline behavior with no additional intervention."""

    controller_type = "minimum"

    def reset(self) -> None:
        pass

    def decide(self, observation: PublicObservation) -> ActionProposal:
        if type(observation) is not PublicObservation:
            raise TypeError("reference controllers require PublicObservation")
        return ActionProposal(ActionVector((0, 0, 0, 0, 0)), "Minimum intervention")

    def observe(self, feedback: PublicWeekFeedback) -> None:
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("reference controllers require PublicWeekFeedback")


class MaximumFeasibleController(MinimumController):
    """Use maximum levels and the highest screening level in the public mask."""

    controller_type = "maximum_feasible"

    def decide(self, observation: PublicObservation) -> ActionProposal:
        if type(observation) is not PublicObservation:
            raise TypeError("reference controllers require PublicObservation")
        from .actions import encode_action

        for screening in range(3, -1, -1):
            action = ActionVector((2, screening, 2, 2, 2))
            if observation.legal_action_mask[encode_action(action)]:
                return ActionProposal(action, "Maximum resource-feasible intervention")
        raise ValueError("public mask has no maximum resource-feasible v1 action")

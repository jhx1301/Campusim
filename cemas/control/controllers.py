"""Shared controller contracts and the two fixed v1 references."""

from abc import ABC, abstractmethod

from .types import ActionProposal, ActionVector, PublicObservation, PublicWeekFeedback


class Controller(ABC):
    """Every frozen policy sees only public observations and public feedback."""

    @abstractmethod
    def reset(self) -> None:
        """Clear controller-local episode state."""

    @abstractmethod
    def decide(self, observation: PublicObservation) -> ActionProposal:
        """Propose an action without accessing a simulator or private reward."""

    @abstractmethod
    def observe(self, feedback: PublicWeekFeedback) -> None:
        """Accept a closed public execution window."""


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

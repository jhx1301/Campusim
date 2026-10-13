"""Controller and decoder contracts; concrete implementations start later."""

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

"""Public policy contracts, fixed references and the tuned threshold policy."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from math import isfinite
from weakref import WeakKeyDictionary

_BASELINE_METADATA = WeakKeyDictionary()

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

    def observe_initial_week(self, observation: PublicObservation, feedback: PublicWeekFeedback) -> None:
        """Accept the protocol-fixed window without asking the policy to decide."""
        self.observe(feedback)

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

    def finish_episode(self) -> None:
        """Finish learning after the last actual window, including a time limit."""

    def drain_feedback_events(self) -> tuple:
        """Deliver auxiliary calls separately from action attempts."""
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


class ThresholdController(MinimumController):
    """Use completed public weeks and actual levels, without duplicate history."""

    controller_type = "threshold"

    def __init__(self, thresholds):
        from .types import ACTION_ORDER, ACTION_SIZES

        if set(thresholds) != set(ACTION_ORDER):
            raise ValueError("thresholds must describe T/S/C/E/A")
        self.thresholds = {}
        for name, size in zip(ACTION_ORDER, ACTION_SIZES):
            values = tuple(thresholds[name])
            if (len(values) != size - 1
                    or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in values)
                    or any(a >= b for a, b in zip(values, values[1:]))):
                raise ValueError(f"{name} thresholds must be positive and strictly increasing")
            self.thresholds[name] = values

    def decide(self, observation):
        from .actions import encode_action
        from .types import ACTION_ORDER

        if type(observation) is not PublicObservation:
            raise TypeError("threshold requires PublicObservation")
        levels = list(observation.current_action.values)
        for week, valid in zip(reversed(observation.history), reversed(observation.week_valid)):
            if not valid:
                continue
            growth = week.growth if week.growth_valid else 0.0
            multiplier = 2 ** max(-1.0, min(1.0, growth / 2))
            indicator = week.delivered_diagnoses / observation.population.population * 1000 * multiplier
            for index, name in enumerate(ACTION_ORDER):
                boundaries = self.thresholds[name]
                levels[index] = sum(indicator >= boundary for boundary in boundaries)
            break
        # The resolver rejects the whole illegal proposal; make S feasible here.
        for screening in range(levels[1], -1, -1):
            levels[1] = screening
            action = ActionVector(levels)
            if observation.legal_action_mask[encode_action(action)]:
                return ActionProposal(action, "Public latest-week threshold")
        raise ValueError("public mask has no feasible threshold action")


def load_baseline_controller(protocol, artifact_path):
    """Validate private metadata once; give the policy only its public inputs."""
    from .artifacts import get_baseline_artifact

    metadata = get_baseline_artifact(artifact_path, protocol)
    if metadata["method"] == "threshold":
        controller = ThresholdController(**metadata["parameters"])
    else:
        if metadata["method"] == "ppo":
            from .rl.ppo import PPOController
            controller_class = PPOController
        else:
            from .rl.ddqn import DDQNController
            controller_class = DDQNController
        controller = controller_class.load(
            metadata["weights_path"], reference_population=metadata["reference_population"],
            reference_horizon=metadata["reference_horizon"])
    _BASELINE_METADATA[controller] = metadata
    return controller, metadata

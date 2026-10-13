"""Decision audit schema and public serialization; no log-writing workflow."""

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json

from .types import ActionProposal, ActionVector, PublicObservation, SCHEMA_VERSION


CONTROLLER_TYPES = (
    "llm", "ppo", "ddqn", "threshold", "minimum", "maximum_feasible",
    "uniform_legal_independent_rng",
)


def public_observation_to_dict(observation: PublicObservation) -> dict:
    """Serialize the exact public type; private/general dictionaries are rejected."""
    if type(observation) is not PublicObservation:
        raise TypeError("only PublicObservation can be serialized as a public observation")
    return json.loads(json.dumps(asdict(observation), ensure_ascii=False, allow_nan=False))


def hash_observation(observation: PublicObservation) -> str:
    """Hash only the common public observation, excluding memory and audit data."""
    payload = json.dumps(public_observation_to_dict(observation), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Runner-owned record. Do not pass this object to controllers or memory."""

    observation_hash: str
    decision_day: int
    decision_time: datetime
    controller_type: str
    action_proposal: ActionProposal | None
    executed_action: ActionVector
    fallback_used: bool = False
    fallback_reason: str | None = None
    adjustment_reason: str | None = None
    reasoning: str | None = None
    retrieved_case_ids: tuple[int, ...] = ()
    elapsed_ms: float = 0.0

    def __post_init__(self) -> None:
        if (type(self.observation_hash) is not str or len(self.observation_hash) != 64
                or any(character not in "0123456789abcdef" for character in self.observation_hash)):
            raise ValueError("observation_hash must be a lowercase SHA-256 hex digest")
        if type(self.decision_day) is not int or self.decision_day < 0:
            raise ValueError("decision_day must be a nonnegative ordinary integer")
        if type(self.decision_time) is not datetime or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be a timezone-aware datetime")
        if type(self.controller_type) is not str or self.controller_type not in CONTROLLER_TYPES:
            raise ValueError("unknown controller_type")
        if self.action_proposal is not None and type(self.action_proposal) is not ActionProposal:
            raise TypeError("action_proposal must be ActionProposal or None")
        if type(self.executed_action) is not ActionVector:
            raise TypeError("executed_action must be ActionVector")
        if type(self.fallback_used) is not bool:
            raise TypeError("fallback_used must be a boolean")
        for name in ("fallback_reason", "adjustment_reason", "reasoning"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be nonempty text or None")
        if self.fallback_used != (self.fallback_reason is not None):
            raise ValueError("fallback_used and fallback_reason must agree")
        if (type(self.retrieved_case_ids) is not tuple
                or any(type(value) is not int or value <= 0 for value in self.retrieved_case_ids)):
            raise ValueError("retrieved_case_ids must be a tuple of positive case ids")
        if type(self.elapsed_ms) not in (int, float) or not 0 <= self.elapsed_ms < float("inf"):
            raise ValueError("elapsed_ms must be finite and nonnegative")
        object.__setattr__(self, "elapsed_ms", 0.0 if self.elapsed_ms == 0 else float(self.elapsed_ms))

    def to_dict(self) -> dict:
        record = asdict(self)
        record["schema_version"] = SCHEMA_VERSION
        record["decision_time"] = self.decision_time.isoformat()
        return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))

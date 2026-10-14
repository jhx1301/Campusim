"""Shared control contracts and the Phase 1 action space; no controllers yet."""

from .controllers import ActionDecoder, Controller
from .actions import ACTION_ENCODING, ACTION_TABLE, decode_action, encode_action, legal_action_mask
from .logging import DecisionRecord, hash_observation, public_observation_to_dict
from .protocol import ControlProtocol, ProtocolValidationError, load_protocol
from .rewards import RewardCalculator
from .types import (
    ACTION_ORDER, ACTION_SIZES, AGE_BANDS, HISTORY_WEEKS, JOINT_ACTION_COUNT,
    SCHEMA_VERSION, ActionProposal, ActionResolution, ActionVector, ExecutedAction,
    ExecutedActionHistory, PrivateDailyMetrics, PrivateMetrics, PublicCost,
    PublicDailyRecord, PublicObservation,
    PublicPopulation, PublicResources, PublicWeekFeedback, PublicWeeklyRecord,
)
from .resolution import resolve_action
from .execution import (
    DayExecutionAudit, InvestigationEvent, JointActionExecutor, NotificationEvent,
)
from .ledger import PublicLedger, PublicLedgerAnalyzer
from .metrics import PrivateMetricsAnalyzer
from .observation import (
    OBSERVATION_ENCODING_VERSION, OBSERVATION_FEATURE_NAMES,
    build_observation, encode_observation,
)
from .scenarios import PopulationRegistry, ScenarioBundle, build_population_registry, build_scenario


__all__ = [
    "ACTION_ORDER", "ACTION_SIZES", "AGE_BANDS", "HISTORY_WEEKS",
    "JOINT_ACTION_COUNT", "SCHEMA_VERSION", "ActionDecoder", "Controller",
    "ACTION_ENCODING", "ACTION_TABLE", "decode_action", "encode_action", "legal_action_mask",
    "DecisionRecord", "RewardCalculator", "ActionProposal", "ActionResolution", "ActionVector",
    "ExecutedAction", "ExecutedActionHistory", "PrivateDailyMetrics", "PrivateMetrics",
    "PublicCost", "PublicDailyRecord", "PublicObservation", "PublicPopulation", "PublicResources",
    "PublicWeekFeedback", "PublicWeeklyRecord", "hash_observation",
    "public_observation_to_dict",
    "ControlProtocol", "ProtocolValidationError", "load_protocol",
    "resolve_action", "JointActionExecutor", "DayExecutionAudit", "InvestigationEvent",
    "NotificationEvent", "PublicLedger", "PublicLedgerAnalyzer",
    "PrivateMetricsAnalyzer", "OBSERVATION_ENCODING_VERSION", "OBSERVATION_FEATURE_NAMES",
    "build_observation", "encode_observation", "PopulationRegistry", "ScenarioBundle",
    "build_population_registry", "build_scenario",
]

"""Shared v1 control contracts, weekly execution and private evaluation."""

from .controllers import ActionDecoder, Controller, MaximumFeasibleController, MinimumController
from .actions import ACTION_ENCODING, ACTION_TABLE, decode_action, encode_action, legal_action_mask
from .logging import DecisionRecord, RunLogger, hash_observation, public_observation_to_dict, resolved_snapshot
from .protocol import ControlProtocol, ProtocolValidationError, load_protocol
from .rewards import REWARD_COMPONENTS, RewardBreakdown, RewardCalculator, V1RewardCalculator
from .types import (
    ACTION_ORDER, ACTION_SIZES, AGE_BANDS, HISTORY_WEEKS, JOINT_ACTION_COUNT,
    SCHEMA_VERSION, ActionProposal, ActionResolution, ActionVector, ExecutedAction,
    ExecutedActionHistory, PrivateDailyMetrics, PrivateMetrics, PublicCost,
    PublicDailyRecord, PublicInfo, PublicObservation,
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
from .scenarios import (
    PopulationRegistry, ScenarioBundle, base_model_configuration, build_population_registry,
    build_scenario, configuration_sha256, population_configuration, resolve_campus_parameters,
)
from .environment import EpisodeAuditSnapshot, WeeklyControlEnvironment, WindowAudit
from .calibration import (
    CalibrationArtifact, CalibrationData, CalibrationFitError, FitReport, evaluate_beta, fit_beta,
    load_calibration_artifact, make_calibration_sim, read_calibration_data,
    save_calibration_artifact, save_fit_report,
)
from .runner import RunResult, run_episode


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
    "PublicInfo", "REWARD_COMPONENTS", "RewardBreakdown", "V1RewardCalculator",
    "WeeklyControlEnvironment", "EpisodeAuditSnapshot", "WindowAudit",
    "resolve_campus_parameters", "population_configuration", "base_model_configuration",
    "configuration_sha256", "CalibrationArtifact", "CalibrationData", "FitReport",
    "make_calibration_sim", "fit_beta", "evaluate_beta", "read_calibration_data",
    "load_calibration_artifact", "save_calibration_artifact", "save_fit_report",
    "MinimumController", "MaximumFeasibleController", "RunLogger", "RunResult", "run_episode",
    "resolved_snapshot", "CalibrationFitError",
]

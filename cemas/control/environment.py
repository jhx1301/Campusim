"""Seven-day control transitions with separate public and runner audit outputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from math import isclose, isfinite
import platform
from types import MappingProxyType
from typing import Any

import numpy as np

from .actions import decode_action, legal_action_mask
from .observation import build_observation
from .protocol import ControlProtocol
from .resolution import resolve_action
from .rewards import RewardBreakdown, V1RewardCalculator
from .scenarios import (
    base_model_configuration, build_scenario, configuration_sha256,
    population_configuration,
)
from .types import (
    ActionProposal, ActionResolution, ActionVector, ExecutedAction, PrivateDailyMetrics,
    PrivateMetrics, PublicCost, PublicDailyRecord, PublicInfo, PublicWeekFeedback,
)


def _freeze(value):
    """Detach configuration data without retaining runtime objects."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, np.ndarray):
        return _freeze(value.tolist())
    if isinstance(value, np.generic):
        return _freeze(value.item())
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise TypeError(f"unsupported configuration value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class WindowAudit:
    """Private runner record, never passed to a controller."""

    start_day: int
    end_day: int
    resolution: ActionResolution
    feedback: PublicWeekFeedback
    private_metrics: PrivateMetrics
    reward_breakdown: RewardBreakdown
    reward: float


@dataclass(frozen=True, slots=True)
class EpisodeAuditSnapshot:
    status: str
    elapsed_days: int
    horizon: int
    finalize_attempted: bool
    public_daily: tuple[PublicDailyRecord, ...]
    private_daily: tuple[PrivateDailyMetrics, ...]
    windows: tuple[WindowAudit, ...]
    manifest: Mapping[str, Any]
    terminal_metrics: PrivateMetrics | None
    error: str | None
    pending_notifications: int
    pending_diagnoses: int


class WeeklyControlEnvironment:
    """One sequential world; controllers receive only observations and feedback.

    ``audit_snapshot`` is a runner-only channel. It intentionally exposes private
    metrics for logging, but never a simulator or other mutable runtime object.
    """

    _SCENARIO_KEYS = frozenset({
        "population", "execution_days", "initial_infections", "beta",
        "screening_capacity_ratio", "calibration_artifact", "beta_scale",
        "calibration_data_path",
    })

    def __init__(self, protocol: ControlProtocol, *, mode="evaluation", purpose="smoke",
                 scenario_options=None):
        if type(protocol) is not ControlProtocol:
            raise TypeError("protocol must be ControlProtocol")
        if mode not in ("training", "evaluation"):
            raise ValueError("mode must be training or evaluation")
        if purpose not in ("smoke", "scientific"):
            raise ValueError("purpose must be smoke or scientific")
        self.protocol = protocol
        self.mode = mode
        self.purpose = purpose
        self._scenario_options = self._options(scenario_options)
        self._bundle = None
        self._reward = None
        self._closed = False
        self._closed_snapshot = None
        self._status = "new"
        self._elapsed_days = 0
        self._horizon = protocol.execution_days
        self._finalize_attempted = False
        self._windows: list[WindowAudit] = []
        self._manifest = MappingProxyType({})
        self._terminal_metrics = None
        self._error = None

    @classmethod
    def _options(cls, options):
        if options is None:
            return {}
        if not isinstance(options, Mapping):
            raise TypeError("scenario options must be a mapping")
        unknown = set(options) - cls._SCENARIO_KEYS
        if unknown:
            raise ValueError(f"unsupported scenario options: {sorted(unknown)}")
        return dict(options)

    def reset(self, seed, options=None):
        """Create a fresh world; build_scenario performs its sole initialization."""
        settings = dict(self._scenario_options)
        settings.update(self._options(options))
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be an ordinary integer within [0, 2**32)")
        self.close()
        self._closed = False
        self._closed_snapshot = None
        self._status = "initializing"
        self._elapsed_days = 0
        self._horizon = settings.get("execution_days", self.protocol.execution_days)
        self._finalize_attempted = False
        self._windows = []
        self._manifest = MappingProxyType({})
        self._terminal_metrics = None
        self._error = None
        try:
            settings, calibration = self._resolve_calibration(settings)
            self._bundle = build_scenario(self.protocol, seed, purpose=self.purpose, **settings)
            bundle = self._bundle
            population = bundle.registry.public_population.population
            self._horizon = bundle.private_metadata["execution_days"]
            self._reward = V1RewardCalculator(self.protocol, population, self._horizon)
            import covasim as cv

            engine = {key: value for key, value in bundle.sim.pars.items()
                      if key not in ("interventions", "analyzers")}
            engine["interventions"] = tuple(type(item).__name__ for item in bundle.sim["interventions"])
            engine["analyzers"] = tuple(type(item).__name__ for item in bundle.sim["analyzers"])
            self._manifest = _freeze({
                **dict(bundle.private_metadata),
                "mode": self.mode,
                "initial_baseline_days": self.protocol.definition["engine"]["initial_baseline_days"],
                "calibration_verified": calibration is not None,
                "beta_provenance": ("verified_e0_artifact" if calibration is not None
                                    else bundle.private_metadata["beta_provenance"]),
                "calibration": calibration,
                "reward_configuration": self._reward.configuration,
                "population_config_sha256": configuration_sha256(population_configuration(self.protocol)),
                "base_model_config_sha256": configuration_sha256(base_model_configuration(self.protocol)),
                "resolved_config": {
                    "engine": engine,
                    "environment_configuration": self.protocol.definition["environment_configuration"],
                    "resources": self.protocol.definition["resources"],
                    "actions": self.protocol.definition["actions"],
                },
                "versions": {"python": platform.python_version(), "numpy": np.__version__,
                             "covasim": cv.__version__},
            })
            self._status = "running"
            return self._observation(), PublicInfo()
        except Exception as error:
            self._fail(error)
            raise

    def _resolve_calibration(self, settings):
        settings = dict(settings)
        artifact = settings.pop("calibration_artifact", None)
        data_path = settings.pop("calibration_data_path", None)
        scale = settings.pop("beta_scale", 1.0)
        if type(scale) not in (int, float) or not isfinite(scale) or scale <= 0:
            raise ValueError("beta_scale must be finite and positive")
        if self.purpose == "smoke":
            if artifact is not None or data_path is not None or scale != 1:
                raise ValueError("calibration_artifact, calibration_data_path and beta_scale require scientific purpose")
            return settings, None
        if artifact is None or "beta" in settings:
            raise ValueError("scientific environments require a verified calibration artifact, not a bare beta")
        for key, expected in (("population", self.protocol.population),
                              ("initial_infections", self.protocol.initial_infections)):
            if key in settings and (type(settings[key]) is not int or settings[key] != expected):
                raise ValueError(f"scientific {key} must match the calibrated protocol")
        from ..e0.artifacts import load_calibration_artifact

        verified = load_calibration_artifact(artifact, self.protocol, data_path=data_path)
        settings["beta"] = verified.beta * scale
        return settings, {"artifact_sha256": verified.sha256, "beta_center": verified.beta,
                          "beta_scale": scale, "beta": settings["beta"]}

    def _require_running(self):
        if self._closed or self._status != "running" or self._bundle is None:
            raise RuntimeError("reset a fresh episode before stepping a non-running environment")

    def action_masks(self):
        if self._closed or self._bundle is None:
            raise RuntimeError("reset the environment before requesting an action mask")
        return legal_action_mask(self._bundle.executor.resources,
                                 self._bundle.registry.public_population.population,
                                 self.protocol.definition["actions"])

    def _observation(self):
        bundle = self._bundle
        ledger = bundle.public_analyzer.ledger
        return build_observation(
            ledger, bundle.registry.public_population, bundle.executor.current_action,
            bundle.executor.resources, self._elapsed_days, execution_days=self._horizon,
            initial_infections=bundle.private_metadata["initial_infections"],
            action_duration_days=ledger.action_duration_days(
                self._elapsed_days, bundle.executor.current_action),
            legal_action_mask=self.action_masks(),
        )

    def advance_initial_week(self):
        """Execute the common minimum through the existing weekly transition."""
        self._require_running()
        if self._elapsed_days != 0:
            raise RuntimeError("the initial baseline window has already been executed")
        return self.step_proposal(ActionProposal(ActionVector((0, 0, 0, 0, 0)),
                                                 "Protocol-fixed initial baseline"))

    def step(self, action_id):
        self._require_running()
        try:
            proposal = ActionProposal(decode_action(action_id))
        except (TypeError, ValueError):
            return self.step_proposal(None, fallback_reason="invalid_action_id")
        return self.step_proposal(proposal)

    def step_proposal(self, proposal, *, fallback_reason=None):
        """Resolve exactly once, then advance the same path used by action IDs."""
        self._require_running()
        if proposal is not None and type(proposal) is not ActionProposal:
            raise TypeError("proposal must be ActionProposal or None")
        if self._elapsed_days == 0 and (proposal is None
                or proposal.action.values != (0, 0, 0, 0, 0) or fallback_reason is not None):
            raise ValueError("day0 requires the protocol-fixed minimum action")
        bundle = self._bundle
        resolution = resolve_action(
            proposal, bundle.executor.current_action, bundle.executor.resources,
            bundle.registry.public_population.population, self.protocol.definition["actions"],
            fallback_reason=fallback_reason,
        )
        start = self._elapsed_days
        end = min(start + 7, self._horizon) - 1
        try:
            bundle.executor.set_action(resolution)
            for _ in range(start, end + 1):
                bundle.sim.step()
                self._elapsed_days += 1
                if (len(bundle.public_analyzer.ledger.snapshot()) != self._elapsed_days
                        or len(bundle.private_analyzer.records) != self._elapsed_days):
                    raise RuntimeError("public/private daily records disagree with completed days")
            feedback = bundle.public_analyzer.ledger.feedback(start, end)
            metrics = bundle.private_analyzer.aggregate(start, end)
            history = (ExecutedAction(start, end, resolution.executed_action),)
            breakdown = self._reward.breakdown(metrics, feedback.week.cost, history)
            self._windows.append(WindowAudit(start, end, resolution, feedback, metrics,
                                             breakdown, breakdown.reward))
            terminated = self._elapsed_days == self._horizon
            if terminated:
                self._terminal_metrics = bundle.private_analyzer.aggregate(0, end)
                self._finalize_attempted = True
                bundle.sim.finalize(verbose=0)
                self._reconcile()
                self._status = "completed"
            observation = self._observation()
            reward = breakdown.reward if self.mode == "training" else 0.0
            return observation, reward, terminated, False, PublicInfo(resolution, feedback)
        except Exception as error:
            self._fail(error)
            raise

    def _reconcile(self):
        """Check additive quantities; stocks and peaks have different reductions."""
        bundle = self._bundle
        public = bundle.public_analyzer.ledger.snapshot()
        private = bundle.private_analyzer.records
        metrics = self._terminal_metrics
        if len(public) != self._horizon or len(private) != self._horizon:
            raise RuntimeError("terminal day count does not match horizon")
        initial = bundle.private_metadata["initial_infections"]
        infections = sum(day.new_infections for day in private)
        if (sum(window.private_metrics.new_infections for window in self._windows) != infections
                or metrics.new_infections != infections
                or metrics.cumulative_infections != initial + infections
                or bundle.sim.results["cum_infections"][-1] != initial + infections
                or initial + infections > bundle.registry.public_population.population):
            raise RuntimeError("daily, weekly and terminal infections do not reconcile")
        if not np.array_equal([day.new_infections for day in private],
                              bundle.sim.results["new_infections"].values):
            raise RuntimeError("private infection flow differs from engine daily flow")
        if (metrics.peak_daily_infections != max(day.new_infections for day in private)
                or metrics.terminal_active_infections != private[-1].active_infections):
            raise RuntimeError("terminal infection stocks or peaks do not reconcile")
        totals = {}
        for field in fields(PublicCost):
            daily = sum(getattr(day.cost, field.name) for day in public)
            weekly = sum(getattr(window.feedback.week.cost, field.name) for window in self._windows)
            matches = (isclose(daily, weekly, rel_tol=1e-12, abs_tol=1e-9)
                       if "restriction_person_days" in field.name else daily == weekly)
            if not matches:
                raise RuntimeError(f"daily and weekly {field.name} do not reconcile")
            totals[field.name] = daily
        if sum(day.delivered_diagnoses for day in public) != sum(
                window.feedback.week.delivered_diagnoses for window in self._windows):
            raise RuntimeError("delivered diagnoses do not reconcile")
        daily_tests = [day.cost.clinical_tests + day.cost.screening_tests for day in public]
        if not np.array_equal(daily_tests, bundle.sim.results["new_tests"].values):
            raise RuntimeError("public tests differ from engine executed tests")
        history = tuple(ExecutedAction(window.start_day, window.end_day,
                                       window.resolution.executed_action) for window in self._windows)
        total_breakdown = self._reward.breakdown(metrics, PublicCost(**totals), history)
        for index in range(5):
            for name in ("normalized", "weighted"):
                window_total = sum(getattr(window.reward_breakdown, name)[index]
                                   for window in self._windows)
                if not isclose(window_total, getattr(total_breakdown, name)[index],
                               rel_tol=1e-12, abs_tol=1e-9):
                    raise RuntimeError("window and terminal reward components do not reconcile")
        if not isclose(sum(window.reward for window in self._windows), total_breakdown.reward,
                       rel_tol=1e-12, abs_tol=1e-9):
            raise RuntimeError("window and terminal rewards do not reconcile")

    def _fail(self, error):
        self._status = "failed"
        self._error = f"{type(error).__name__}: {error}"

    def audit_snapshot(self):
        """Return detached private evidence for the runner, including after close."""
        if self._closed_snapshot is not None:
            return self._closed_snapshot
        bundle = self._bundle
        public = bundle.public_analyzer.ledger.snapshot() if bundle else ()
        private = bundle.private_analyzer.records if bundle else ()
        pending_notifications = (sum(len(events) for events in bundle.executor._pending_notifications.values())
                                 if bundle else 0)
        pending_diagnoses = (int(np.count_nonzero(bundle.sim.people.date_diagnosed >= self._elapsed_days))
                             if bundle else 0)
        return EpisodeAuditSnapshot(
            self._status, self._elapsed_days, self._horizon, self._finalize_attempted,
            public, private, tuple(self._windows), self._manifest, self._terminal_metrics,
            self._error, pending_notifications, pending_diagnoses,
        )

    def close(self):
        """Release the world once; incomplete episodes are never finalized."""
        if self._closed:
            return
        if self._status in ("initializing", "running"):
            self._status = "aborted"
        self._closed_snapshot = self.audit_snapshot()
        self._bundle = None
        self._reward = None
        self._closed = True

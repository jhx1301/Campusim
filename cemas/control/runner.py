"""Sequential v1 reference runs with public controller calls and private audit."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from math import fsum, isclose
from pathlib import Path
import sys
from time import perf_counter
from types import MappingProxyType

from .controllers import Controller
from .logging import (
    DecisionRecord, RunLogger, hash_observation, resolved_snapshot, snapshot_sha256,
)
from .protocol import ControlProtocol
from .rewards import V1RewardCalculator
from .types import ActionProposal, ExecutedAction, PublicCost


@dataclass(frozen=True, slots=True)
class RunResult:
    status: str
    output_dir: Path
    summary: object


def _validate_development_seed(protocol, seed, purpose):
    seeds = protocol.definition["seeds"]
    if purpose == "smoke":
        if seed not in seeds["smoke"]:
            raise ValueError("smoke runs require protocol smoke seeds; final-test worlds are forbidden")
    elif purpose == "scientific":
        if not any(seeds[name]["start_inclusive"] <= seed <= seeds[name]["end_inclusive"]
                   for name in ("validation_A", "validation_B")):
            raise ValueError("Phase 3 scientific runs require source validation seeds; final-test worlds are forbidden")
    else:
        raise ValueError("purpose must be smoke or scientific")


def _episode_summary(protocol, snapshot, population):
    if (snapshot.status != "completed" or snapshot.elapsed_days != snapshot.horizon
            or snapshot.terminal_metrics is None):
        raise RuntimeError("environment did not complete its announced horizon")
    if len(snapshot.public_daily) != snapshot.horizon or len(snapshot.private_daily) != snapshot.horizon:
        raise ValueError("completed run must contain every public and private day")
    totals = {field.name: fsum(getattr(day.cost, field.name) for day in snapshot.public_daily)
              for field in fields(PublicCost)}
    for name in ("clinical_tests", "screening_tests", "delivered_notifications"):
        totals[name] = int(totals[name])
    cost = PublicCost(**totals)
    for name, total in totals.items():
        weekly = fsum(getattr(window.feedback.week.cost, name) for window in snapshot.windows)
        if not isclose(total, weekly, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError(f"daily/weekly {name} mismatch")
    diagnoses = sum(day.delivered_diagnoses for day in snapshot.public_daily)
    if diagnoses != sum(window.feedback.week.delivered_diagnoses for window in snapshot.windows):
        raise ValueError("daily/weekly delivered diagnoses mismatch")
    infections = sum(day.new_infections for day in snapshot.private_daily)
    terminal = snapshot.terminal_metrics
    if (infections != sum(window.private_metrics.new_infections for window in snapshot.windows)
            or infections != terminal.new_infections
            or terminal.cumulative_infections != terminal.initial_infections + infections):
        raise ValueError("daily/weekly/terminal infection counts mismatch")
    history = tuple(ExecutedAction(window.start_day, window.end_day,
                                   window.resolution.executed_action)
                    for window in snapshot.windows)
    calculator = V1RewardCalculator(protocol, population, snapshot.horizon)
    breakdown = calculator.breakdown(terminal, cost, history)
    reward = fsum(window.reward for window in snapshot.windows)
    if not isclose(reward, breakdown.reward, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError("weekly return does not equal terminal objective")
    switches = [0] * 5
    changes = [0] * 5
    for previous, current in zip(history, history[1:]):
        for index, (before, after) in enumerate(zip(previous.action.values, current.action.values)):
            switches[index] += int(before != after)
            changes[index] += abs(after - before)
    return {
        "status": "completed", "elapsed_days": snapshot.elapsed_days,
        "execution_days": snapshot.horizon, "decision_count": len(snapshot.windows),
        "population": population, "delivered_diagnoses": diagnoses,
        "private_metrics": resolved_snapshot(terminal), "public_cost": resolved_snapshot(cost),
        "total_reward": reward, "positive_cost": -reward,
        "reward_breakdown": resolved_snapshot(breakdown),
        "reward_configuration": calculator.configuration,
        "objective_sha256": snapshot_sha256(calculator.configuration),
        "switches_by_dimension": switches, "level_changes_by_dimension": changes,
        "fallback_count": sum(window.resolution.fallback_reason is not None for window in snapshot.windows),
        "adjustment_count": sum(window.resolution.adjustment_reason is not None for window in snapshot.windows),
        "pending_notifications": snapshot.pending_notifications,
        "pending_diagnoses": snapshot.pending_diagnoses,
        "daily_weekly_terminal_reconciled": True,
    }


def run_episode(protocol: ControlProtocol, controller: Controller, output_dir: str | Path,
                world_seed: int, *, purpose="smoke", mode="evaluation", scenario_options=None) -> RunResult:
    """Run one attempt, retaining failure evidence and refusing existing paths.

    The controller receives only ``reset()``, a PublicObservation, and closed
    PublicWeekFeedback. Mode and all private audit values stay in this runner.
    """
    if type(protocol) is not ControlProtocol or not isinstance(controller, Controller):
        raise TypeError("run_episode requires ControlProtocol and Controller")
    if type(world_seed) is not int:
        raise TypeError("world_seed must be an ordinary integer")
    _validate_development_seed(protocol, world_seed, purpose)
    controller_type = getattr(controller, "controller_type", None)
    if controller_type not in ("minimum", "maximum_feasible"):
        raise ValueError("Phase 3 runner supports the two fixed references only")
    manifest = {
        "protocol_id": protocol.protocol_id, "protocol_sha256": protocol.source_sha256,
        "world_seed": world_seed, "controller_type": controller_type,
        "purpose": purpose, "mode": mode, "train_seed": None, "controller_seed": None,
        "paired_world": world_seed, "started_at": datetime.now(timezone.utc).isoformat(),
    }
    logger = RunLogger(output_dir, manifest)
    environment = None
    try:
        from .environment import WeeklyControlEnvironment

        environment = WeeklyControlEnvironment(protocol, mode=mode, purpose=purpose,
                                               scenario_options=scenario_options)
        observation, _ = environment.reset(world_seed)
        population = observation.population.population
        controller.reset()
        logger.write_snapshot(environment.audit_snapshot())
        while True:
            decision_time = datetime.now(timezone.utc)
            started = perf_counter()
            proposal = controller.decide(observation)
            elapsed_ms = (perf_counter() - started) * 1000
            next_observation, _, terminated, truncated, _ = environment.step_proposal(proposal)
            snapshot = environment.audit_snapshot()
            window = snapshot.windows[-1]
            resolution = window.resolution
            valid_proposal = proposal if type(proposal) is ActionProposal else None
            decision = DecisionRecord(
                hash_observation(observation), observation.decision_day, decision_time,
                controller_type, valid_proposal, resolution.executed_action,
                fallback_used=resolution.fallback_reason is not None,
                fallback_reason=resolution.fallback_reason,
                adjustment_reason=resolution.adjustment_reason,
                reasoning=valid_proposal.reasoning if valid_proposal else None,
                elapsed_ms=elapsed_ms,
            )
            logger.write_decision(decision, observation=observation, resolution=resolution)
            logger.write_snapshot(snapshot)
            controller.observe(window.feedback)
            if truncated:
                raise RuntimeError("an interrupted run cannot be reported as complete")
            if terminated:
                break
            observation = next_observation
        environment.close()
        snapshot = environment.audit_snapshot()
        summary = _episode_summary(protocol, snapshot, population)
        logger.complete(summary)
        return RunResult("completed", Path(output_dir), MappingProxyType(summary))
    except BaseException as error:
        snapshot = None
        if environment is not None:
            try:
                environment.close()
                snapshot = environment.audit_snapshot()
            except Exception as close_error:
                error.add_note(f"Environment cleanup also failed: {close_error}")
        try:
            logger.fail(error, snapshot)
        except Exception as log_error:
            error.add_note(f"Failure audit could not be completed: {log_error}")
        raise
    finally:
        active_error = sys.exc_info()[1]
        try:
            logger.close()
        except Exception as close_error:
            if active_error is None:
                raise
            active_error.add_note(f"Log cleanup also failed: {close_error}")

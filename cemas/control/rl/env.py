"""Gymnasium projection of the existing weekly control environment."""

from __future__ import annotations

import gymnasium as gym
import numpy as np

from ..logging import resolved_snapshot
from ..observation import rl_feature_names, encode_rl_observation
from ..types import JOINT_ACTION_COUNT


class GymControlEnv(gym.Env):
    """Keep world scheduling and private accounting outside the public Gym info.

    ``episode_plan(seed=None)`` supplies ``world_seed`` and ``scenario_options``.
    The optional sink receives private lifecycle events; the learner sees only
    encoded observations, rewards and public transition information.
    """

    metadata = {"render_modes": []}

    def __init__(self, environment, episode_plan, *, reference_population,
                 reference_horizon, private_record_sink=None):
        self.environment = environment
        self.episode_plan = episode_plan
        self.reference_population = reference_population
        self.reference_horizon = reference_horizon
        self.private_record_sink = private_record_sink
        self.observation_space = gym.spaces.Box(
            -np.inf, np.inf, shape=(len(rl_feature_names(environment.protocol)),), dtype=np.float32)
        self.action_space = gym.spaces.Discrete(JOINT_ACTION_COUNT)
        self._observation = None
        self._world_seed = None
        self._episode_transitions = 0
        self._terminated = False
        self._failed = False
        self._episode_index = -1

    def _encode(self):
        return encode_rl_observation(
            self._observation, self.reference_population, self.reference_horizon)

    def _public_info(self, info):
        return {"resolution": resolved_snapshot(info.resolution),
                "feedback": resolved_snapshot(info.feedback),
                "next_mask": self.action_masks()}

    def _record(self, event, **details):
        if self.private_record_sink is not None:
            snapshot_task = "snapshot_training" in self.environment.protocol.definition
            if snapshot_task and event != "transition":
                return
            self.private_record_sink({
                "event": event, "world_seed": self._world_seed,
                **({"episode_id": self._episode_index, "episode_completed": self._terminated}
                   if snapshot_task else {}),
                "elapsed_days": (self._observation.decision_day
                                 if self._observation is not None else 0),
                "episode_transitions": self._episode_transitions, **details,
            })

    def _record_failure(self, error):
        self._failed = True
        if self.private_record_sink is not None:
            try:
                self._record("failed", error_type=type(error).__name__,
                             elapsed_days=self.environment.audit_snapshot().elapsed_days)
            except Exception as record_error:
                from ..runner import _add_error_note

                _add_error_note(error, "private RL failure record failed: "
                                f"{type(record_error).__name__}")

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if options:
            raise ValueError("world options belong to the private episode plan")
        if self._observation is not None and not self._terminated and not self._failed:
            self._record("closed")
        episode = self.episode_plan(seed=seed)
        self._episode_index += 1
        self._world_seed = episode["world_seed"]
        self._observation = None
        self._episode_transitions = 0
        self._terminated = False
        self._failed = False
        days = episode["scenario_options"].get("execution_days", self.environment.protocol.execution_days)
        if (self.environment.purpose == "scientific"
                and days <= self.environment.protocol.definition["engine"]["initial_baseline_days"]):
            raise ValueError("RL training requires at least one autonomous decision window")
        self._record("initializing", scenario_options=resolved_snapshot(episode["scenario_options"]))
        try:
            self._observation, info = self.environment.reset(
                self._world_seed, options=episode["scenario_options"])
            self._record("initialized", scenario_options=resolved_snapshot(episode["scenario_options"]))
            if self.environment.protocol.definition["engine"]["initial_baseline_days"]:
                self._observation, reward, self._terminated, truncated, info = self.environment.advance_initial_week()
                if truncated:
                    raise RuntimeError("the fixed initial window cannot be truncated")
                if self.private_record_sink is not None:
                    positive_cost = (-reward if self.environment.mode == "training"
                                     else -self.environment.audit_snapshot().windows[-1].reward)
                    self._record("fixed_window", terminated=self._terminated,
                                 positive_cost=positive_cost,
                                 public_cost=resolved_snapshot(info.feedback.week.cost))
            self._record_completed()
        except Exception as error:
            self._record_failure(error)
            raise
        return self._encode(), self._public_info(info)

    def step(self, action):
        # SB3 sends NumPy integer scalars; the shared decoder accepts ordinary int.
        if isinstance(action, (bool, np.bool_)) or not isinstance(action, (int, np.integer)):
            raise TypeError("Gym actions must be integer scalars")
        action = int(action)
        try:
            observation, reward, terminated, truncated, info = self.environment.step(action)
        except Exception as error:
            self._record_failure(error)
            raise
        self._observation = observation
        self._episode_transitions += 1
        self._terminated = terminated or truncated
        if self.private_record_sink is not None:
            positive_cost = (-reward if self.environment.mode == "training"
                             else -self.environment.audit_snapshot().windows[-1].reward)
            self._record("transition", terminated=terminated, positive_cost=positive_cost)
        self._record_completed()
        return self._encode(), reward, terminated, truncated, self._public_info(info)

    def _record_completed(self):
        if (self._terminated and self.private_record_sink is not None
                and "snapshot_training" not in self.environment.protocol.definition):
            from ..runner import episode_summary

            summary = episode_summary(
                self.environment.protocol, self.environment.audit_snapshot(),
                self._observation.population.population)
            self._record("completed", summary=summary)

    def action_masks(self):
        if self._observation is None:
            raise RuntimeError("reset the environment before requesting an action mask")
        return np.asarray(self._observation.legal_action_mask, dtype=np.bool_)

    def close(self):
        self.environment.close()
        if self._observation is not None and not self._terminated and not self._failed:
            self._record("closed")
        self._observation = None

"""Masked Double DQN with one replay ring and one sequential environment."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from ..actions import decode_action
from ..controllers import Controller
from ..observation import OBSERVATION_FEATURE_NAMES, encode_rl_observation
from ..types import ActionProposal, JOINT_ACTION_COUNT, PublicWeekFeedback


OBSERVATION_SIZE = len(OBSERVATION_FEATURE_NAMES)


class QNetwork(nn.Module):
    def __init__(self, hidden=(128, 128)):
        super().__init__()
        self.hidden = tuple(hidden)
        widths = (OBSERVATION_SIZE, *self.hidden, JOINT_ACTION_COUNT)
        layers = []
        for index, (inputs, outputs) in enumerate(zip(widths, widths[1:])):
            layers.append(nn.Linear(inputs, outputs))
            if index < len(widths) - 2:
                layers.append(nn.ReLU())
        self.layers = nn.Sequential(*layers)

    def forward(self, observations):
        return self.layers(observations)


@dataclass(frozen=True)
class ReplayBatch:
    observations: np.ndarray
    actions: np.ndarray
    rewards: np.ndarray
    next_observations: np.ndarray
    terminated: np.ndarray
    next_masks: np.ndarray


class ReplayBuffer:
    """Fixed v1 transition layout, with uniform sampling without replacement."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.observations = np.empty((capacity, OBSERVATION_SIZE), dtype=np.float32)
        self.actions = np.empty(capacity, dtype=np.int64)
        self.rewards = np.empty(capacity, dtype=np.float32)
        self.next_observations = np.empty((capacity, OBSERVATION_SIZE), dtype=np.float32)
        self.terminated = np.empty(capacity, dtype=np.bool_)
        self.next_masks = np.empty((capacity, JOINT_ACTION_COUNT), dtype=np.bool_)
        self.position = 0
        self.size = 0

    def add(self, observation, action, reward, next_observation, terminated, next_mask):
        index = self.position
        self.observations[index] = observation
        self.actions[index] = action
        self.rewards[index] = reward
        self.next_observations[index] = next_observation
        self.terminated[index] = terminated
        self.next_masks[index] = next_mask
        self.position = (index + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size, rng):
        indices = rng.choice(self.size, size=batch_size, replace=False)
        return ReplayBatch(self.observations[indices], self.actions[indices],
                           self.rewards[indices], self.next_observations[indices],
                           self.terminated[indices], self.next_masks[indices])


def legal_argmax(values, masks):
    """An all-illegal mask or non-finite network result is a failed run."""
    if not torch.isfinite(values).all():
        raise FloatingPointError("DDQN produced non-finite Q values")
    if not masks.any(dim=-1).all():
        raise ValueError("DDQN requires at least one legal action")
    return values.masked_fill(~masks, -torch.inf).argmax(dim=-1)


@torch.no_grad()
def double_dqn_targets(online, target, next_observations, rewards, terminated,
                       next_masks, gamma):
    """Online selects, target evaluates; terminal rows never query either net."""
    result = rewards.clone()
    active = ~terminated
    if active.any():
        observations = next_observations[active]
        choices = legal_argmax(online(observations), next_masks[active])
        target_values = target(observations)
        if not torch.isfinite(target_values).all():
            raise FloatingPointError("DDQN produced non-finite target values")
        estimates = target_values.gather(1, choices.unsqueeze(1)).squeeze(1)
        result[active] += gamma * estimates
    return result


class DDQNTrainer:
    def __init__(self, vec_env, config, seed, *, initial_budget):
        if vec_env.num_envs != 1:
            raise ValueError("DDQN uses exactly one sequential environment")
        self.env = vec_env
        self.config = dict(config)
        self.rng = np.random.default_rng(seed)
        torch.manual_seed(seed)
        self.online = QNetwork(config["hidden"])
        self.target = deepcopy(self.online).requires_grad_(False)
        self.target.eval()
        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=config["learning_rate"])
        self.replay = ReplayBuffer(config["replay_capacity"])
        self.num_timesteps = 0
        self.gradient_updates = 0
        self.target_updates = 0
        self.epsilon_decay_steps = int(initial_budget * config["epsilon_linear_fraction"])
        self._observation = None
        self._mask = None

    @property
    def epsilon(self):
        fraction = min(self.num_timesteps / self.epsilon_decay_steps, 1.0)
        return self.config["epsilon_initial"] + fraction * (
            self.config["epsilon_final"] - self.config["epsilon_initial"])

    def _action(self, observation, mask):
        if (self.num_timesteps < self.config["warmup_steps"]
                or self.rng.random() < self.epsilon):
            return int(self.rng.choice(np.flatnonzero(mask)))
        with torch.no_grad():
            values = self.online(torch.as_tensor(observation).unsqueeze(0))
            return int(legal_argmax(values, torch.as_tensor(mask).unsqueeze(0)).item())

    def _update(self):
        batch = self.replay.sample(self.config["batch_size"], self.rng)
        observations = torch.as_tensor(batch.observations)
        actions = torch.as_tensor(batch.actions)
        rewards = torch.as_tensor(batch.rewards)
        targets = double_dqn_targets(
            self.online, self.target, torch.as_tensor(batch.next_observations), rewards,
            torch.as_tensor(batch.terminated), torch.as_tensor(batch.next_masks),
            self.config["gamma"])
        predictions = self.online(observations)
        if not torch.isfinite(predictions).all():
            raise FloatingPointError("DDQN produced non-finite Q values")
        values = predictions.gather(1, actions.unsqueeze(1)).squeeze(1)
        loss = nn.functional.smooth_l1_loss(values, targets)
        if not torch.isfinite(loss):
            raise FloatingPointError("DDQN produced a non-finite loss")
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online.parameters(), self.config["max_grad_norm"],
                                 error_if_nonfinite=True)
        self.optimizer.step()
        self.gradient_updates += 1
        return float(loss.detach())

    def train(self, steps):
        """Continue the same live world and replay across checkpoint chunks."""
        if type(steps) is not int or steps <= 0:
            raise ValueError("steps must be a positive ordinary integer")
        if self._observation is None:
            self._observation = self.env.reset()
            self._mask = np.asarray(self.env.env_method("action_masks")[0], dtype=np.bool_)
        for _ in range(steps):
            action = self._action(self._observation[0], self._mask)
            next_observation, rewards, dones, infos = self.env.step(
                np.asarray([action], dtype=np.int64))
            terminated = bool(dones[0])
            info = infos[0]
            replay_next = info["terminal_observation"] if terminated else next_observation[0]
            self.replay.add(self._observation[0], action, float(rewards[0]), replay_next,
                            terminated, info["next_mask"])
            self.num_timesteps += 1
            if self.num_timesteps >= self.config["warmup_steps"]:
                self._update()
            if self.num_timesteps % self.config["target_update_steps"] == 0:
                self.target.load_state_dict(self.online.state_dict())
                self.target_updates += 1
            self._observation = next_observation
            self._mask = (np.asarray(self.env.env_method("action_masks")[0], dtype=np.bool_)
                          if terminated else info["next_mask"])
        return self

    def save(self, path):
        """Inference checkpoint, deliberately not a crash-resume snapshot."""
        torch.save({"hidden": list(self.online.hidden), "state_dict": self.online.state_dict()}, path)


class DDQNController(Controller):
    controller_type = "ddqn"

    def __init__(self, network, *, reference_population, reference_horizon):
        self.network = network.eval()
        self.reference_population = reference_population
        self.reference_horizon = reference_horizon

    @classmethod
    def load(cls, path, *, reference_population, reference_horizon):
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        network = QNetwork(checkpoint["hidden"])
        network.load_state_dict(checkpoint["state_dict"])
        return cls(network, reference_population=reference_population,
                   reference_horizon=reference_horizon)

    def reset(self):
        pass

    @torch.no_grad()
    def predict(self, features, mask):
        values = self.network(torch.as_tensor(features).unsqueeze(0))
        return int(legal_argmax(values, torch.as_tensor(mask, dtype=torch.bool).unsqueeze(0)).item())

    def decide(self, observation):
        features = encode_rl_observation(
            observation, self.reference_population, self.reference_horizon)
        return ActionProposal(decode_action(self.predict(features, observation.legal_action_mask)),
                              "Frozen DDQN baseline")

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("DDQN requires PublicWeekFeedback")

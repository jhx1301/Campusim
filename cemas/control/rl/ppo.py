"""MaskablePPO construction and public-only frozen inference."""

from __future__ import annotations

import numpy as np

from ..actions import decode_action
from ..controllers import Controller
from ..observation import encode_rl_observation
from ..types import ActionProposal, PublicWeekFeedback


def build_ppo(env, config, seed):
    """Use the library's rollout, masking and PPO updates without replacement."""
    from sb3_contrib import MaskablePPO
    from torch import nn, optim

    keys = ("learning_rate", "n_steps", "batch_size", "n_epochs", "gamma",
            "gae_lambda", "clip_range", "ent_coef", "vf_coef", "max_grad_norm",
            "target_kl", "normalize_advantage")
    return MaskablePPO(
        config["policy"], env, seed=seed, device="cpu", verbose=0,
        policy_kwargs={"net_arch": {"pi": list(config["policy_hidden"]),
                                    "vf": list(config["value_hidden"])},
                       "activation_fn": nn.Tanh, "optimizer_class": optim.Adam},
        **{key: config[key] for key in keys})


class PPOController(Controller):
    """Frozen deterministic policy; no rewards, protocol or training state."""

    controller_type = "ppo"

    def __init__(self, model, *, reference_population, reference_horizon):
        self.model = model
        self.reference_population = reference_population
        self.reference_horizon = reference_horizon

    @classmethod
    def load(cls, path, *, reference_population, reference_horizon):
        from sb3_contrib import MaskablePPO

        model = MaskablePPO.load(path, env=None, device="cpu")
        return cls(model, reference_population=reference_population,
                   reference_horizon=reference_horizon)

    def reset(self):
        pass

    def predict(self, features, mask):
        action, _ = self.model.predict(features, deterministic=True,
                                       action_masks=np.asarray(mask, dtype=np.bool_))
        scalar = np.asarray(action)
        if scalar.size != 1 or not np.issubdtype(scalar.dtype, np.integer):
            raise TypeError("PPO must return one integer action")
        action_id = int(scalar.item())
        if not 0 <= action_id < len(mask) or not mask[action_id]:
            raise ValueError("PPO returned an action excluded by its public mask")
        return action_id

    def decide(self, observation):
        features = encode_rl_observation(
            observation, self.reference_population, self.reference_horizon)
        return ActionProposal(decode_action(self.predict(features, observation.legal_action_mask)),
                              "Frozen MaskablePPO baseline")

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("PPO requires PublicWeekFeedback")

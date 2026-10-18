"""RL boundary, masked Double target, replay and synthetic update checks."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from cemas.control.actions import decode_action
from cemas.control.ledger import PublicLedger
from cemas.control.observation import build_observation, encode_rl_observation
from cemas.control.protocol import load_protocol
from cemas.control.types import ActionVector, PublicPopulation, PublicResources


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


def public_observation():
    return build_observation(
        PublicLedger(), PublicPopulation(80, (8, 32, 16, 16, 8), 48, 24, 8),
        ActionVector((0, 0, 0, 0, 0)), PublicResources(8, 8, 4), 0,
        execution_days=112, initial_infections=2, action_duration_days=(0,) * 5,
        legal_action_mask=tuple(index in (1, 2) for index in range(324)))


def test_optional_rl_package_does_not_import_training_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import cemas.control.rl; "
         "assert not {'torch','gymnasium','stable_baselines3','sb3_contrib'} & set(sys.modules)"],
        cwd=PROTOCOL_PATH.parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


class PredictOnlyPPO:
    def __init__(self, action):
        self.action = action
        self.calls = []

    def predict(self, features, *, deterministic, action_masks):
        self.calls.append((features.copy(), deterministic, action_masks.copy()))
        return self.action, None


def test_frozen_ppo_sees_only_shared_features_and_mask():
    from cemas.control.rl.ppo import PPOController

    model = PredictOnlyPPO(np.asarray(2, dtype=np.int64))
    controller = PPOController(model, reference_population=12000, reference_horizon=112)
    observation = public_observation()
    controller.reset()
    assert controller.decide(observation).action == decode_action(2)
    features, deterministic, mask = model.calls[0]
    np.testing.assert_array_equal(features, encode_rl_observation(observation, 12000, 112))
    np.testing.assert_array_equal(mask, observation.legal_action_mask)
    assert deterministic is True
    assert not hasattr(controller, "protocol")


@pytest.mark.parametrize("action,error", [(1.0, TypeError), (True, TypeError),
                                         ([1, 2], TypeError), (324, ValueError),
                                         (0, ValueError)])
def test_ppo_rejects_invalid_model_output_instead_of_fallback(action, error):
    from cemas.control.rl.ppo import PPOController

    controller = PPOController(PredictOnlyPPO(action), reference_population=80,
                               reference_horizon=112)
    with pytest.raises(error):
        controller.decide(public_observation())


class SmokeEpisodePlan:
    """Spawn-safe tiny worlds, distinct from any scientific training run."""

    def __init__(self):
        self.index = 0

    def __call__(self, seed=None):
        result = {"world_seed": 91240 + self.index,
                  "scenario_options": {"screening_capacity_ratio": .02 if self.index == 0 else .10}}
        self.index += 1
        return result


def make_smoke_gym(private_record_sink=None):
    from cemas.control.environment import WeeklyControlEnvironment
    from cemas.control.rl.env import GymControlEnv

    protocol = load_protocol(PROTOCOL_PATH)
    environment = WeeklyControlEnvironment(
        protocol, mode="training", scenario_options={
            "population": 80, "execution_days": 8, "initial_infections": 2})
    return GymControlEnv(environment, SmokeEpisodePlan(), reference_population=12000,
                         reference_horizon=112, private_record_sink=private_record_sink)


def test_gym_reuses_exact_world_transitions_and_private_accounting():
    pytest.importorskip("gymnasium")
    from cemas.control.environment import WeeklyControlEnvironment

    records = []
    gym_environment = make_smoke_gym(records.append)
    protocol = load_protocol(PROTOCOL_PATH)
    plain = WeeklyControlEnvironment(protocol, mode="training", scenario_options={
        "population": 80, "execution_days": 8, "initial_infections": 2,
        "screening_capacity_ratio": .02})
    try:
        # Covasim owns process-global RNG state: finish each world sequentially.
        observation, _ = plain.reset(91240)
        initial = encode_rl_observation(observation, 12000, 112)
        expected_results = [plain.step(0), plain.step(0)]
        expected_audit = plain.audit_snapshot()
        plain.close()
        encoded, info = gym_environment.reset(seed=11)
        np.testing.assert_array_equal(encoded, initial)
        assert set(info) == {"resolution", "feedback", "next_mask"}
        for expected_day, expected in zip((7, 8), expected_results):
            result = gym_environment.step(np.int64(0))
            np.testing.assert_array_equal(result[0], encode_rl_observation(expected[0], 12000, 112))
            assert result[1:4] == expected[1:4]
            assert set(result[4]) == {"resolution", "feedback", "next_mask"}
            assert gym_environment._observation.decision_day == expected_day
        assert result[2] is True and result[3] is False
        assert gym_environment.environment.audit_snapshot() == expected_audit
        assert records[0]["event"] == "initializing" and records[0]["elapsed_days"] == 0
        assert records[1]["event"] == "initialized" and records[1]["elapsed_days"] == 0
        assert [row["elapsed_days"] for row in records if row["event"] == "transition"] == [7, 8]
        assert records[-1]["event"] == "completed"
        assert records[-1]["summary"]["positive_cost"] == pytest.approx(
            -sum(window.reward for window in expected_audit.windows))
        gym_environment.reset()
        assert records[-1]["world_seed"] == 91241
        assert records[-1]["event"] == "initialized"
        assert records[-1]["episode_transitions"] == records[-1]["elapsed_days"] == 0
    finally:
        gym_environment.close()
        plain.close()
    assert records[-1]["event"] == "closed"
    assert records[-1]["elapsed_days"] == 0


@pytest.mark.parametrize("action", [True, np.bool_(False), 1.5, np.float64(1), np.asarray([0])])
def test_gym_never_truncates_noninteger_actions(action):
    pytest.importorskip("gymnasium")
    environment = make_smoke_gym()
    try:
        environment.reset()
        with pytest.raises(TypeError, match="integer scalars"):
            environment.step(action)
        assert environment._observation.decision_day == 0
    finally:
        environment.close()


def test_spawn_vec_auto_reset_preserves_terminal_observation_and_mask():
    pytest.importorskip("gymnasium")
    pytest.importorskip("stable_baselines3")
    from stable_baselines3.common.vec_env import SubprocVecEnv

    environment = SubprocVecEnv([make_smoke_gym], start_method="spawn")
    try:
        environment.reset()
        environment.step(np.asarray([0]))
        observation, _, done, infos = environment.step(np.asarray([0]))
        assert done.tolist() == [True]
        assert observation[0, 0] == 0  # New world, not the terminal observation.
        assert infos[0]["terminal_observation"][0] == 1
        assert not np.array_equal(infos[0]["next_mask"], environment.env_method("action_masks")[0])
        assert set(infos[0]) == {"resolution", "feedback", "next_mask",
                                 "TimeLimit.truncated", "terminal_observation"}
        assert infos[0]["TimeLimit.truncated"] is False
    finally:
        environment.close()


def test_gym_failure_records_partial_days_without_a_successful_transition(monkeypatch):
    pytest.importorskip("gymnasium")
    records = []
    environment = make_smoke_gym(records.append)
    try:
        environment.reset()
        original_step = environment.environment._bundle.sim.step
        calls = []

        def fail_after_one_day():
            if calls:
                raise RuntimeError("world failed")
            calls.append(True)
            return original_step()

        monkeypatch.setattr(environment.environment._bundle.sim, "step", fail_after_one_day)
        with pytest.raises(RuntimeError, match="world failed"):
            environment.step(0)
        assert records[-1] == {
            "event": "failed", "world_seed": 91240, "elapsed_days": 1,
            "episode_transitions": 0, "error_type": "RuntimeError"}
        assert not any(record["event"] in ("transition", "completed") for record in records)
    finally:
        environment.close()
    assert records[-1]["event"] == "failed"


def test_gym_initialization_failure_preserves_world_and_original_error(monkeypatch):
    pytest.importorskip("gymnasium")
    records = []

    def private_sink(record):
        records.append(record)
        if record["event"] == "failed":
            raise OSError("private sink failed")

    environment = make_smoke_gym(private_sink)

    def fail_reset(*args, **kwargs):
        raise ValueError("world initialization failed")

    monkeypatch.setattr(environment.environment, "reset", fail_reset)
    try:
        with pytest.raises(ValueError, match="world initialization failed") as caught:
            environment.reset()
        assert [record["event"] for record in records] == ["initializing", "failed"]
        assert records[-1]["world_seed"] == 91240
        assert any("OSError" in note for note in caught.value.__notes__)
    finally:
        environment.close()


@pytest.fixture
def ddqn():
    pytest.importorskip("torch")
    from cemas.control.rl import ddqn

    return ddqn


def test_double_target_uses_online_choice_target_value_and_excludes_terminals(ddqn):
    torch = ddqn.torch

    class FixedValues(torch.nn.Module):
        def __init__(self, entries):
            super().__init__()
            self.entries = entries
            self.calls = []

        def forward(self, observations):
            assert torch.isfinite(observations).all(), "terminal row must never reach a network"
            self.calls.append(len(observations))
            result = torch.zeros((len(observations), 324))
            for action, value in self.entries.items():
                result[:, action] = value
            return result

    online = FixedValues({0: 100, 1: 7, 2: 5})
    target = FixedValues({0: 200, 1: 3, 2: 90})
    masks = torch.zeros((2, 324), dtype=torch.bool)
    masks[0, 1:3] = True
    observations = torch.zeros((2, 198))
    observations[1] = torch.nan  # Terminal contents are deliberately unusable.
    result = ddqn.double_dqn_targets(
        online, target, observations, torch.tensor([-1., -2.]),
        torch.tensor([False, True]), masks, 1)
    torch.testing.assert_close(result, torch.tensor([2., -2.]))
    assert online.calls == target.calls == [1]


def test_ddqn_greedy_ties_and_invalid_outputs_are_explicit(ddqn):
    torch = ddqn.torch
    values = torch.tensor([[100., 3., 3.]])
    masks = torch.tensor([[False, True, True]])
    assert ddqn.legal_argmax(values, masks).item() == 1
    with pytest.raises(ValueError, match="legal action"):
        ddqn.legal_argmax(values, torch.zeros_like(masks))
    values[0, 1] = torch.nan
    with pytest.raises(FloatingPointError, match="non-finite"):
        ddqn.legal_argmax(values, masks)


def test_replay_ring_has_only_required_transition_fields(ddqn):
    replay = ddqn.ReplayBuffer(3)
    mask = np.ones(324, dtype=np.bool_)
    for value in range(5):
        replay.add(np.full(198, value), value, -value, np.full(198, value + 10),
                   value % 2 == 0, mask)
    batch = replay.sample(3, np.random.default_rng(1))
    assert replay.size == 3
    assert set(batch.observations[:, 0]) == {2, 3, 4}
    np.testing.assert_array_equal(batch.next_observations[:, 0], batch.observations[:, 0] + 10)
    np.testing.assert_array_equal(batch.actions, batch.observations[:, 0])
    assert set(vars(batch)) == {"observations", "actions", "rewards", "next_observations",
                                "terminated", "next_masks"}


class AutoResetVec:
    num_envs = 1

    def __init__(self):
        self.steps = 0
        self.resets = 0
        self.actions = []

    def reset(self):
        self.resets += 1
        return np.full((1, 198), 1., dtype=np.float32)

    def env_method(self, name):
        assert name == "action_masks"
        return [np.arange(324) == 1 + self.steps % 2]

    def step(self, actions):
        self.actions.append(int(actions[0]))
        self.steps += 1
        return (np.full((1, 198), self.steps + 1, dtype=np.float32),
                np.asarray([-.25]), np.asarray([True]), [{
                    "terminal_observation": np.full(198, 100 + self.steps, dtype=np.float32),
                    "next_mask": np.arange(324) == 7}])


def ddqn_config():
    config = deepcopy(dict(load_protocol(PROTOCOL_PATH).definition["controllers"]["ddqn"]))
    config["replay_capacity"] = 1024
    return config


def test_ddqn_replay_uses_terminal_world_and_chunks_keep_live_state(ddqn):
    environment = AutoResetVec()
    trainer = ddqn.DDQNTrainer(environment, ddqn_config(), 11, initial_budget=8192)
    trainer.train(1)
    trainer.train(1)
    assert trainer.num_timesteps == 2 and environment.resets == 1
    assert environment.actions == [1, 2]
    assert trainer.replay.next_observations[0, 0] == 101
    assert trainer.replay.observations[1, 0] == 2
    np.testing.assert_array_equal(trainer.replay.next_masks[0], np.arange(324) == 7)
    assert trainer.replay.terminated[:2].all()
    assert trainer.gradient_updates == trainer.target_updates == 0


def test_ddqn_exact_warmup_sync_order_and_fixed_epsilon_horizon(ddqn, monkeypatch):
    trainer = ddqn.DDQNTrainer(AutoResetVec(), ddqn_config(), 11, initial_budget=8192)
    updates = []

    def update():
        updates.append(trainer.num_timesteps)
        with ddqn.torch.no_grad():
            next(trainer.online.parameters()).fill_(len(updates))

    monkeypatch.setattr(trainer, "_update", update)
    trainer.train(511)
    assert not updates and trainer.target_updates == 0
    trainer.train(1)
    assert updates == [512] and trainer.target_updates == 1
    ddqn.torch.testing.assert_close(next(trainer.target.parameters()),
                                    next(trainer.online.parameters()))
    trainer.train(2)
    assert updates == [512, 513, 514]
    trainer.num_timesteps = 2048
    assert trainer.epsilon == pytest.approx(.525)
    trainer.num_timesteps = 4096
    assert trainer.epsilon == pytest.approx(.05)
    trainer.num_timesteps = 32768
    assert trainer.epsilon == pytest.approx(.05)


def test_ddqn_real_gradient_and_saved_frozen_inference(ddqn, tmp_path):
    config = ddqn_config()
    config.update({"hidden": (4, 4), "batch_size": 2})
    trainer = ddqn.DDQNTrainer(AutoResetVec(), config, 11, initial_budget=8192)
    for reward in (1., 2.):
        trainer.replay.add(np.zeros(198, dtype=np.float32), 1, reward,
                           np.zeros(198, dtype=np.float32), True,
                           np.zeros(324, dtype=np.bool_))
    before = {name: value.clone() for name, value in trainer.online.state_dict().items()}
    target_before = {name: value.clone() for name, value in trainer.target.state_dict().items()}
    loss = trainer._update()
    assert np.isfinite(loss) and trainer.gradient_updates == 1
    assert any(not ddqn.torch.equal(before[name], value)
               for name, value in trainer.online.state_dict().items())
    for name, value in trainer.target.state_dict().items():
        ddqn.torch.testing.assert_close(value, target_before[name])
    path = tmp_path / "ddqn.pt"
    trainer.save(path)
    loaded = ddqn.DDQNController.load(path, reference_population=12000, reference_horizon=112)
    original = ddqn.DDQNController(trainer.online, reference_population=12000, reference_horizon=112)
    assert loaded.decide(public_observation()) == original.decide(public_observation())
    assert loaded.decide(public_observation()).action in (decode_action(1), decode_action(2))


def make_synthetic_gym():
    import gymnasium as gym

    class SyntheticPublicEnv(gym.Env):
        observation_space = gym.spaces.Box(-np.inf, np.inf, (198,), np.float32)
        action_space = gym.spaces.Discrete(324)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            self.steps = 0
            return np.zeros(198, dtype=np.float32), {}

        def action_masks(self):
            return np.arange(324) < 2

        def step(self, action):
            assert action in (0, 1)
            self.steps += 1
            return (np.zeros(198, dtype=np.float32), float(action), self.steps == 2, False,
                    {"next_mask": self.action_masks()})

    return SyntheticPublicEnv()


def test_maskable_ppo_synthetic_update_then_save_load(tmp_path):
    pytest.importorskip("gymnasium")
    torch = pytest.importorskip("torch")
    pytest.importorskip("sb3_contrib")
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from cemas.control.rl.ppo import PPOController, build_ppo

    config = load_protocol(PROTOCOL_PATH).definition["controllers"]["ppo"]
    environment = SubprocVecEnv([make_synthetic_gym], start_method="spawn")
    model = build_ppo(environment, config, 11)
    try:
        before = {name: value.clone() for name, value in model.policy.state_dict().items()}
        model.learn(256, reset_num_timesteps=False)
        assert model.num_timesteps == 256
        assert any(not torch.equal(before[name], value)
                   for name, value in model.policy.state_dict().items())
        path = tmp_path / "ppo.zip"
        model.save(path)  # Only after learn returns and optimizer updates finish.
        loaded = PPOController.load(path, reference_population=12000, reference_horizon=112)
        for name, value in model.policy.state_dict().items():
            torch.testing.assert_close(value, loaded.model.policy.state_dict()[name])
        features = np.zeros(198, dtype=np.float32)
        mask = np.arange(324) == 1
        assert loaded.predict(features, mask) == 1
    finally:
        model.get_env().close()

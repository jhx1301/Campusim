"""Measure short snapshot training without changing learner hyperparameters."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import SubprocVecEnv

from cemas.control.artifacts import training_budget
from cemas.control.logging import resolved_snapshot
from cemas.control.observation import SNAPSHOT_RL_ENCODING_VERSION
from cemas.control.rl.ddqn import DDQNTrainer, DDQNController, double_dqn_targets
from cemas.control.rl.ppo import build_ppo, PPOController
from cemas.control.snapshot_protocol import load_training_protocol
from cemas.control.worker import TrainingEnvFactory


def statistics(values):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise FloatingPointError("non-finite diagnostic values")
    return {"mean": float(values.mean()), "min": float(values.min()),
            "max": float(values.max()), "abs_max": float(np.abs(values).max())}


class PPODiagnostics(BaseCallback):
    def __init__(self, record):
        super().__init__()
        self.record = record
        self.raw_rewards = []
        self.timeouts = []
        self.optimizer_steps = 0
        self.probe = None

    def _on_step(self):
        reward = float(self.locals["rewards"][0])
        self.raw_rewards.append(reward)
        row = {"event": "transition", "step": self.num_timesteps, "raw_reward": reward,
               "value": float(self.locals["values"][0].item())}
        if self.locals["dones"][0]:
            info = self.locals["infos"][0]
            assert info["TimeLimit.truncated"]
            with torch.no_grad():
                terminal = torch.as_tensor(info["terminal_observation"]).unsqueeze(0)
                value = float(self.model.policy.predict_values(terminal).item())
            row.update(truncated=True, terminal_value=value, bootstrap_reward=reward+self.model.gamma*value)
            self.timeouts.append((self.num_timesteps-1, row["bootstrap_reward"]))
        self.record(row)
        return True

    def _on_rollout_end(self):
        buffer = self.model.rollout_buffer
        self.probe = torch.as_tensor(buffer.observations.reshape(-1, 197).copy())
        self.returns = torch.as_tensor(buffer.returns.reshape(-1).copy())
        errors = [abs(float(buffer.rewards.reshape(-1)[i])-expected) for i, expected in self.timeouts]
        assert len(self.timeouts) == 16 and max(errors) < 1e-6
        self.record({"event": "rollout", "step": self.num_timesteps,
                     "raw_rewards": statistics(self.raw_rewards),
                     "bootstrap_rewards": statistics(buffer.rewards),
                     "returns": statistics(buffer.returns),
                     "advantages": statistics(buffer.advantages),
                     "truncations": len(self.timeouts), "bootstrap_max_error": max(errors)})
        self.measure("before_update")

    def measure(self, event):
        with torch.no_grad():
            values = self.model.policy.predict_values(self.probe).flatten()
            mse = float(torch.mean((values-self.returns)**2))
        self.record({"event": event, "step": self.num_timesteps,
                     "optimizer_step": self.optimizer_steps,
                     "fixed_probe_values": statistics(values.numpy()), "fixed_return_mse": mse})

    def optimizer_step(self, optimizer, args, kwargs):
        self.optimizer_steps += 1
        self.measure("optimizer_update")


class DiagnosticDDQN(DDQNTrainer):
    def __init__(self, *args, record, **kwargs):
        super().__init__(*args, **kwargs)
        self.record = record

    def measure(self, event, **details):
        # A fixed prefix of replay avoids confusing changing inputs with Q drift.
        count = min(64, self.replay.size)
        with torch.no_grad():
            values = self.online(torch.as_tensor(self.replay.observations[:count]))
            selected = values.gather(1, torch.as_tensor(self.replay.actions[:count]).unsqueeze(1)).flatten()
            targets = double_dqn_targets(self.online, self.target,
                torch.as_tensor(self.replay.next_observations[:count]),
                torch.as_tensor(self.replay.rewards[:count]),
                torch.as_tensor(self.replay.terminated[:count]),
                torch.as_tensor(self.replay.next_masks[:count]), self.config["gamma"])
        self.record({"event": event, "step": self.num_timesteps, "updates": self.gradient_updates,
                     "target_updates": self.target_updates, "probe_size": count,
                     "fixed_probe_q": statistics(values.numpy()),
                     "fixed_probe_selected_q": statistics(selected.numpy()),
                     "fixed_probe_targets": statistics(targets.numpy()), **details})

    def _update(self):
        self.measure("before_update")
        loss = super()._update()
        self.measure("optimizer_update", loss=loss)
        return loss


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=("ppo", "ddqn"), required=True)
    args = parser.parse_args()
    protocol = load_training_protocol(args.protocol)
    assert protocol.population == 69457 and protocol.execution_days == 112
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    started = perf_counter()
    diagnostic_path = output / "diagnostics.jsonl"

    def record(row):
        row = dict(row, elapsed_seconds=perf_counter()-started)
        with diagnostic_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, allow_nan=False)+"\n")
        if row["event"] == "progress" or (row["event"] == "transition" and row["step"] % 16 == 0):
            print(f"{args.method}: {row['step']} steps, {row['elapsed_seconds']:.1f}s", flush=True)

    config = resolved_snapshot(protocol.definition["controllers"][args.method])
    assert config["gamma"] == 1
    log = output / "worlds.jsonl"
    env = SubprocVecEnv([TrainingEnvFactory(str(args.protocol.resolve()), 11,
        str(args.artifact.resolve()), str(log))], start_method="spawn")
    try:
        assert env.observation_space.shape == (197,)
        if args.method == "ppo":
            model = build_ppo(env, config, 11)
            before = [p.detach().clone() for p in model.policy.parameters()]
            callback = PPODiagnostics(record)
            hook = model.policy.optimizer.register_step_post_hook(callback.optimizer_step)
            learning_started = perf_counter()
            model.learn(256, callback=callback)
            learning_seconds = perf_counter()-learning_started
            hook.remove()
            changed = any(not torch.equal(a,b) for a,b in zip(before,model.policy.parameters()))
            updates = callback.optimizer_steps
            logger = {k: float(v) for k,v in model.logger.name_to_value.items() if k.startswith("train/")}
            record({"event": "training_summary", "step": 256, "logger": logger})
            model.save(output / "model.zip")
            frozen = PPOController.load(output / "model.zip", reference_population=69457, reference_horizon=112)
            assert all(torch.equal(a,b) for a,b in zip(model.policy.parameters(), frozen.model.policy.parameters()))
            details = {"optimizer_updates": updates, "epochs": model._n_updates,
                       "rollouts": 1, "truncations": len(callback.timeouts), "logger": logger}
        else:
            model = DiagnosticDDQN(env, config, 11, initial_budget=8192, record=record)
            before = [p.detach().clone() for p in model.online.parameters()]
            learning_started = perf_counter()
            for steps in [16]*32+[1]:
                model.train(steps)
                record({"event": "progress", "step": model.num_timesteps})
                if model.num_timesteps >= 64:
                    model.measure("probe")
            learning_seconds = perf_counter()-learning_started
            assert not model.replay.terminated[:513].any()
            changed = any(not torch.equal(a,b) for a,b in zip(before,model.online.parameters()))
            updates = model.gradient_updates
            model.save(output / "model.pt")
            frozen = DDQNController.load(output / "model.pt", reference_population=69457, reference_horizon=112)
            assert all(torch.equal(a,b) for a,b in zip(model.online.parameters(),frozen.network.parameters()))
            details = {"optimizer_updates": updates, "target_updates": model.target_updates,
                       "replay_terminal_count": int(model.replay.terminated[:513].sum()),
                       "replay_rewards": statistics(model.replay.rewards[:513])}
        assert changed and updates > 0
    finally:
        env.close()
    report = {"purpose": "short_training_diagnostics", "method": args.method, "population": 69457,
        "encoding": SNAPSHOT_RL_ENCODING_VERSION, "observation_size": 197, "gamma": config["gamma"],
        "effective_time_limit": {"terminated": False, "truncated": True, "bootstrap": True},
        "horizon": 112, "learner_seed": 11, "protocol": str(args.protocol.resolve()),
        "config": config, "parameters_changed": changed, "weights_roundtrip": True,
        "actual_training": training_budget(log), "learning_seconds": learning_seconds,
        "elapsed_seconds": perf_counter()-started, **details}
    (output / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()

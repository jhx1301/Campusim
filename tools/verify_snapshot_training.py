"""Full-population engineering acceptance; never a formal training batch."""

import argparse
import json
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--stage", choices=("prepare", "control", "ppo", "ddqn"), required=True)
    args = parser.parse_args()
    from cemas.control.snapshot_protocol import load_training_protocol, history_seeds
    from cemas.control.snapshots import generate_history_snapshots
    from cemas.control.logging import resolved_snapshot
    from cemas.control.artifacts import training_budget

    root = args.output.resolve()
    protocol_path = root / "protocol.json"
    if args.stage == "prepare":
        root.mkdir(parents=True, exist_ok=False)
        settings = json.loads(Path("docs/baseline_snapshot_training_v1.json").read_text(encoding="utf-8"))
        settings.update(library=str(root / "library"), training_worlds=1, snapshot_days=[21, 35])
        protocol_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        protocol = load_training_protocol(protocol_path)
        for seed, split in ((20101, "val"), (history_seeds(protocol, "train")[0], "train")):
            generate_history_snapshots(protocol, args.artifact, root / "library", seed, split)
            print(f"Prepared history {seed}", flush=True)
        return

    protocol = load_training_protocol(protocol_path)
    output = root / args.stage
    output.mkdir(exist_ok=False)
    started = perf_counter()
    if args.stage == "control":
        from cemas.control.controllers import MinimumController
        from cemas.control.runner import run_episode
        rows = []
        for day in (21, 35):
            result = run_episode(protocol, MinimumController(), output / str(day), 20101,
                purpose="scientific", scenario_options={"snapshot_path":str(root / "library" / f"20101-{day}.json"),
                    "future_seed":123, "calibration_artifact":str(args.artifact)})
            assert result.summary["decision_count"] == 16 and result.summary["fixed_window_count"] == 1
            assert result.summary["execution_days"] == 119 and result.summary["control_period"]["execution_days"] == 112
            rows.append({"snapshot_day":day, "summary":resolved_snapshot(result.summary)})
        report = {"purpose":"engineering_acceptance", "runs":rows}
    else:
        import torch
        from stable_baselines3.common.vec_env import SubprocVecEnv
        from cemas.control.worker import TrainingEnvFactory
        from cemas.control.rl.ppo import build_ppo, PPOController
        from cemas.control.rl.ddqn import DDQNTrainer, DDQNController
        torch.set_num_threads(1)
        log = output / "worlds.jsonl"
        env = SubprocVecEnv([TrainingEnvFactory(str(protocol_path),11,str(args.artifact.resolve()),str(log))],
                           start_method="spawn")
        try:
            config = resolved_snapshot(protocol.definition["controllers"][args.stage])
            if args.stage == "ppo":
                model = build_ppo(env,config,11)
                before = [p.detach().clone() for p in model.policy.parameters()]
                model.learn(256)
                changed = any(not torch.equal(a,b) for a,b in zip(before,model.policy.parameters()))
                weights = output / "model.zip"
                model.save(weights)
                frozen = PPOController.load(weights,reference_population=protocol.population,reference_horizon=112)
                observation = env.reset()[0]; mask = env.env_method("action_masks")[0]
                assert frozen.predict(observation,mask) == int(model.predict(observation,deterministic=True,action_masks=mask)[0])
                updates = model._n_updates
            else:
                model = DDQNTrainer(env,config,11,initial_budget=8192)
                before = [p.detach().clone() for p in model.online.parameters()]
                model.train(513)
                changed = any(not torch.equal(a,b) for a,b in zip(before,model.online.parameters()))
                weights = output / "model.pt"
                model.save(weights)
                frozen = DDQNController.load(weights,reference_population=protocol.population,reference_horizon=112)
                assert all(torch.equal(a,b) for a,b in zip(model.online.parameters(),frozen.network.parameters()))
                updates = model.gradient_updates
            assert changed and updates > 0
        finally:
            env.close()
        report = {"purpose":"engineering_acceptance", "method":args.stage,
            "population":protocol.population,"parameters_changed":changed,"updates":updates,
            "weights_roundtrip":True,"actual_training":training_budget(log)}
    report["elapsed_seconds"] = perf_counter() - started
    (output / "verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(f"Verified {args.stage}: {report['elapsed_seconds']:.1f}s",flush=True)


if __name__ == "__main__":
    main()

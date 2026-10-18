"""Thin Phase 6 source-development commands; importing this module starts no run."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pilot", "tune", "train", "evaluate", "develop"):
        command = commands.add_parser(name)
        command.add_argument("--artifact", type=Path, required=True, help="Verified E0 calibration artifact")
        command.add_argument("--data", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name in ("pilot", "evaluate"):
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument("--baseline", type=Path)
            group.add_argument("--reference", choices=("minimum", "maximum_feasible"))
        if name == "evaluate":
            command.add_argument("--split", choices=("A", "B"), default="A")
        elif name == "train":
            command.add_argument("--method", choices=("ppo", "ddqn"), required=True)
            command.add_argument("--maximum-budget", type=int, choices=(8192, 16384, 32768))
        elif name == "develop":
            command.add_argument("--candidates", type=Path, required=True,
                                 help="Prespecified four-mode LLM candidates with identities, hypotheses and settings")
    horizon = commands.add_parser("horizon")
    horizon.add_argument("--records", type=Path, required=True,
                         help="Seven-method final selected B records keyed by protocol method")
    horizon.add_argument("--output", type=Path, required=True)
    holdout = commands.add_parser("holdout")
    holdout.add_argument("--development-dir", type=Path, required=True)
    holdout.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--release", type=Path, required=True)
    freeze.add_argument("--development-dir", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from cemas.control.protocol import load_protocol
    from cemas.control.training import (develop_llm, evaluate_source, horizon_report,
        run_pilot, train_controller, tune_threshold, world_holdout_report)

    protocol = load_protocol(args.protocol)
    if args.command == "freeze":
        from cemas.control.memory_store import promote_public_store
        manifest = promote_public_store(args.development_dir, args.release, args.output)
        print(f"evaluation_ready: {args.output} ({manifest.database_sha256})")
        return 0
    if args.command == "holdout":
        from cemas.control.memory_store import (DATABASE_FILENAME, FrozenPublicCaseStore,
                                                verify_source_manifest)
        source = verify_source_manifest(args.development_dir / "build_manifest.json", purpose="development")
        worlds = {case_id: row["seed"] for row in source["trajectories"] for case_id in row["case_ids"]}
        with FrozenPublicCaseStore.open(args.development_dir / DATABASE_FILENAME,
                                       args.development_dir / "store_manifest.json") as store:
            result = world_holdout_report(store, worlds)
    elif args.command == "horizon":
        result = horizon_report(protocol, json.loads(args.records.read_text(encoding="utf-8")))
    else:
        from cemas.control.calibration import load_calibration_artifact
        load_calibration_artifact(args.artifact, protocol, require_evaluation=True, data_path=args.data)
        kwargs = {"calibration_data_path": args.data}
        if args.command == "tune":
            result = tune_threshold(protocol, args.output, args.artifact, **kwargs)
        elif args.command == "train":
            result = train_controller(protocol, args.method, args.output, args.artifact,
                                      maximum_budget=args.maximum_budget, **kwargs)
        elif args.command == "develop":
            result = develop_llm(protocol, json.loads(args.candidates.read_text(encoding="utf-8")),
                                 args.output, args.artifact, **kwargs)
        else:
            spec = ({"method": "baseline", "artifact": str(args.baseline)} if args.baseline
                    else {"method": args.reference})
            if args.command == "pilot":
                result = run_pilot(protocol, spec, args.output, args.artifact, **kwargs)
            else:
                result = evaluate_source(protocol, spec, args.output, args.artifact,
                                         pool=f"validation_{args.split}", **kwargs)
        print(f"{args.command}: {args.output}")
        return 0
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(f"{args.command}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

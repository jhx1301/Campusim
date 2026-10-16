"""Run both fixed references as an explicitly uncalibrated smoke check."""

import argparse
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--population", type=int)
    parser.add_argument("--days", type=int)
    parser.add_argument("--initial-infections", type=int)
    args = parser.parse_args(argv)

    from cemas.control.controllers import MinimumController, MaximumFeasibleController
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import run_episode

    protocol = load_protocol(args.protocol)
    seeds = args.seed or list(protocol.definition["seeds"]["smoke"])
    if len(set(seeds)) != len(seeds) or any(seed not in protocol.definition["seeds"]["smoke"] for seed in seeds):
        parser.error("smoke seeds must be distinct members of the protocol smoke pool")
    options = {key: value for key, value in (
        ("population", args.population), ("execution_days", args.days),
        ("initial_infections", args.initial_infections)) if value is not None}
    args.output.mkdir(parents=True, exist_ok=False)
    for seed in seeds:
        for controller_class in (MinimumController, MaximumFeasibleController):
            controller = controller_class()
            result = run_episode(protocol, controller,
                                 args.output / f"{seed}-{controller.controller_type}", seed,
                                 purpose="smoke", scenario_options=options)
            print(f"{result.status}: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

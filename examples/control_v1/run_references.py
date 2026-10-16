"""Run paired fixed references on calibrated source-development worlds."""

import argparse
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--data", type=Path,
                        help="CSV path relative to the project root (default: data/notre_dame_2020_early.csv)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-split", choices=("A", "B"), default="A")
    parser.add_argument("--seed", type=int, action="append",
                        help="Source validation world; defaults to the first world of the chosen split")
    args = parser.parse_args(argv)

    from cemas.control.calibration import load_calibration_artifact
    from cemas.control.controllers import MinimumController, MaximumFeasibleController
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import run_episode

    protocol = load_protocol(args.protocol)
    interval = protocol.definition["seeds"][f"validation_{args.validation_split}"]
    first, last = interval["start_inclusive"], interval["end_inclusive"]
    seeds = args.seed or [first]
    if len(set(seeds)) != len(seeds) or any(not first <= seed <= last for seed in seeds):
        parser.error("seeds must be distinct worlds in the selected source validation split")
    # Loading verifies primary fitting evidence, independent report and compatibility.
    load_calibration_artifact(args.artifact, protocol, require_evaluation=True, data_path=args.data)
    scales = protocol.definition["source"]["validation_scales"]
    capacities = protocol.definition["resources"]["screening_static_capacity_ratios"]
    combinations = len(scales) * len(capacities)
    if (last - first + 1) % combinations:
        raise ValueError("source validation worlds do not match the prescribed condition grid")
    repeats = (last - first + 1) // combinations
    args.output.mkdir(parents=True, exist_ok=False)
    for seed in seeds:
        condition = (seed - first) // repeats
        options = {"calibration_artifact": args.artifact,
                   "calibration_data_path": args.data,
                   "beta_scale": scales[condition // len(capacities)],
                   "screening_capacity_ratio": capacities[condition % len(capacities)]}
        for controller_class in (MinimumController, MaximumFeasibleController):
            controller = controller_class()
            result = run_episode(protocol, controller,
                                 args.output / f"{seed}-{controller.controller_type}", seed,
                                 purpose="scientific", scenario_options=options)
            print(f"{result.status}: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

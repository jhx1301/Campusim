"""Run the full prespecified UW 2020 replay using an existing E0 anchor."""

import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    from cemas.replay.study import run_replay_study

    result = run_replay_study(args.anchor, args.output, workers=args.workers)
    print(f"UW replay: {result['status']}; {result['worlds_completed']} worlds; {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fit the prescribed one-parameter E0 model; no work runs during import."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--data", type=Path,
                        help="CSV path relative to the project root (default: data/notre_dame_2020_early.csv)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window", choices=("primary", "exploratory"), default="primary")
    args = parser.parse_args(argv)

    from cemas.control.calibration import fit_beta, save_calibration_artifact
    from cemas.control.logging import resolved_snapshot
    from cemas.control.protocol import load_protocol

    protocol = load_protocol(args.protocol)
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        artifact = fit_beta(protocol, args.data, window=args.window)
        path = save_calibration_artifact(artifact, args.output)
    except Exception as error:
        failure = {"status": "failed", "error_type": type(error).__name__, "error": str(error),
                   "window": args.window, "protocol_sha256": protocol.source_sha256,
                   "trial_records": resolved_snapshot(getattr(error, "trial_records", ()))}
        with (args.output / "failure.json").open("x", encoding="utf-8") as stream:
            json.dump(failure, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        raise
    print(f"Fitted beta={artifact.beta}; independent evaluation still required: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

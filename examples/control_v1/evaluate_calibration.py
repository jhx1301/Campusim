"""Evaluate an E0 fit on its prescribed disjoint evaluation worlds."""

import argparse
import json
from pathlib import Path
from uuid import uuid4


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--data", type=Path,
                        help="CSV path relative to the project root (default: data/notre_dame_2020_early.csv)")
    args = parser.parse_args(argv)

    from cemas.control.calibration import evaluate_beta, load_calibration_artifact, save_fit_report
    from cemas.control.protocol import load_protocol

    protocol = load_protocol(args.protocol)
    if args.artifact.with_name("fit_report.json").exists():
        raise FileExistsError("an independent evaluation report already exists; it will not be overwritten")
    artifact = load_calibration_artifact(args.artifact, protocol, require_evaluation=False, data_path=args.data)
    try:
        report = evaluate_beta(artifact, protocol=protocol, data_path=args.data)
        path = save_fit_report(report, args.artifact.parent)
    except Exception as error:
        path = args.artifact.with_name(f"evaluation-failure-{uuid4().hex}.json")
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"status": "failed", "error_type": type(error).__name__,
                       "error": str(error), "artifact_sha256": artifact.sha256},
                      stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        raise
    print(f"Independent evaluation saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

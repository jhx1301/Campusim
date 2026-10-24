"""Run the frozen UW E0 scan, fit and evaluation study."""

import argparse
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=root / "docs/e0_protocol_v2.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--export-existing", action="store_true",
                        help="Verify a completed study at --output and export its UW control anchor")
    parser.add_argument("--scenarios", type=str, default=None,
                        help="comma-separated case names; default is every configured case")
    args = parser.parse_args(argv)

    from cemas.e0.data import load_e0_config, load_e0_data
    from cemas.e0.study import run_e0_study
    from cemas.e0.artifacts import export_control_anchor
    from cemas.control.protocol import load_protocol

    config = load_e0_config(args.config)
    data = load_e0_data(config)
    scenarios = None
    if args.scenarios is not None:
        scenarios = [name.strip() for name in args.scenarios.split(",") if name.strip()]
    if args.export_existing:
        if scenarios is not None:
            parser.error("--scenarios does not apply to --export-existing")
        anchor = export_control_anchor(args.output, load_protocol(config["base_protocol_path"]))
        print(f"Verified UW control anchor: {anchor}")
        return 0
    summary = run_e0_study(config, data, args.output, workers=args.workers, scenarios=scenarios)
    print(f"E0 study status: {summary['status']}; output: {args.output}")
    if any(case["name"] == "main" for case in summary["cases"]):
        anchor = export_control_anchor(args.output, load_protocol(config["base_protocol_path"]))
        print(f"Verified UW control anchor: {anchor}")
    else:
        print("Sensitivity-only study; no main control anchor was exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

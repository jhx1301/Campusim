"""Run the public LLM on reserved source worlds with local counting and E0 data."""

import argparse
from pathlib import Path


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--provider", choices=("deepseek", "qwen"), default="deepseek")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key-env", required=True, help="Name of an existing credential environment variable")
    parser.add_argument("--tokenizer-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer-acceptance", type=Path,
                        help="Legacy option; reports are not used at runtime")
    args = parser.parse_args(argv)

    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_llm_controller, run_episode

    protocol = load_protocol(args.protocol)
    pool = protocol.definition["seeds"]["prompt_development"]
    if not pool["start_inclusive"] <= args.seed <= pool["end_inclusive"]:
        parser.error("seed must belong to the reserved prompt_development source pool")
    controller = make_llm_controller(
        protocol, endpoint=args.endpoint, api_key_env=args.api_key_env, provider=args.provider,
        tokenizer_manifest=args.tokenizer_manifest)
    result = run_episode(protocol, controller, args.output, args.seed, purpose="prompt_development",
                         scenario_options={"calibration_artifact": args.artifact, "calibration_data_path": args.data})
    print(f"{result.status}: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

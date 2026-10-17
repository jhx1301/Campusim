"""Run the Phase 5 public memory controller after both live admission gates."""

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
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY",
                        help="Name of an existing credential environment variable")
    parser.add_argument("--tokenizer-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer-acceptance", type=Path, required=True)
    parser.add_argument("--memory-acceptance", type=Path, required=True)
    parser.add_argument("--memory-mode", choices=("none", "short", "global", "both"), default="both")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--store-manifest", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    args = parser.parse_args(argv)

    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_memory_llm_controller, run_episode

    protocol = load_protocol(args.protocol)
    pool = protocol.definition["seeds"]["prompt_development"]
    if not pool["start_inclusive"] <= args.seed <= pool["end_inclusive"]:
        parser.error("seed must belong to the reserved prompt_development source pool")
    if args.memory_mode in ("global", "both") and (args.store is None or args.store_manifest is None):
        parser.error("global/both memory requires a verified frozen public store")
    controller = make_memory_llm_controller(
        protocol, endpoint=args.endpoint, provider=args.provider, api_key_env=args.api_key_env,
        tokenizer_manifest=args.tokenizer_manifest, tokenizer_acceptance=args.tokenizer_acceptance,
        memory_acceptance=args.memory_acceptance, memory_mode=args.memory_mode,
        store_path=args.store, store_manifest=args.store_manifest, build_manifest=args.build_manifest)
    try:
        result = run_episode(protocol, controller, args.output, args.seed, purpose="prompt_development",
                             scenario_options={"calibration_artifact": args.artifact,
                                                "calibration_data_path": args.data})
    finally:
        if getattr(controller, "store", None) is not None:
            controller.store.close()
    print(f"{result.status}: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

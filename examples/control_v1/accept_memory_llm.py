"""Run the independent six-probe Phase 5 provider acceptance workflow.

The probe factory is intentionally explicit: it must return the six named probe
dictionaries expected by ``accept_memory_llm``. It may use fixture observations
and a verified public store, but it never advances a simulator trajectory.
"""

import argparse
import importlib
from pathlib import Path


def _factory(spec):
    module_name, separator, function_name = spec.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError("--probe-factory must use module:function syntax")
    function = getattr(importlib.import_module(module_name), function_name)
    if not callable(function):
        raise TypeError("probe factory must be callable")
    return function


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--provider", choices=("deepseek", "qwen"), default="deepseek")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--tokenizer-manifest", type=Path, required=True)
    parser.add_argument("--probe-factory", required=True, help="module:function returning the six public probes")
    parser.add_argument("--memory-profile", type=Path)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--store-manifest", type=Path)
    args = parser.parse_args(argv)

    from cemas.control.knowledge import load_knowledge_bundle
    from cemas.control.llm import LLMTransport, OfficialInputTokenCounter
    from cemas.control.memory import load_memory_profile
    from cemas.control.memory_acceptance import accept_memory_llm
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_llm_settings, make_public_prompt_config
    from cemas.control.memory_store import FrozenPublicCaseStore

    protocol = load_protocol(args.protocol)
    settings = make_llm_settings(protocol, provider=args.provider, endpoint=args.endpoint,
                                 api_key_env=args.api_key_env)
    store = FrozenPublicCaseStore.open(args.store, args.store_manifest) if args.store and args.store_manifest else None
    try:
        factory = _factory(args.probe_factory)
        probes = factory(protocol, store)
        result = accept_memory_llm(
            LLMTransport(settings), OfficialInputTokenCounter(args.tokenizer_manifest),
            make_public_prompt_config(protocol), probes, args.output,
            memory_profile=load_memory_profile(args.memory_profile) if args.memory_profile else None,
            knowledge_bundle=load_knowledge_bundle(args.knowledge) if args.knowledge else None)
    finally:
        if store is not None:
            store.close()
    print(f"accepted receipt: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

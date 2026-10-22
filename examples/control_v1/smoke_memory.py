"""Run one offline Phase 5 memory episode with an explicit fixture transport."""

import argparse
import json
from pathlib import Path


class OfflineMemoryCounter:
    identity = {"adapter": "offline_memory_fixture", "accepted_for_live": False}

    def validate(self, settings):
        pass

    def count_input(self, messages, settings):
        return 100

    def verify_response(self, response):
        pass


class OfflineMemoryTransport:
    def __init__(self):
        self.settings = None

    def prepare(self):
        pass

    def complete(self, messages):
        from cemas.control.llm import LLMResponse
        payload = json.loads(messages[1].content)
        response = {"action": [0, 0, 0, 0, 0], "reason": "Offline public memory fixture",
                    "evidence_ids": ["O:/decision_day"], "alternative_actions": [],
                    "uncertainty_codes": payload["required_uncertainty_codes"]}
        return LLMResponse(json.dumps(response, ensure_ascii=False), model="offline-memory-fixture",
                           response_id="offline-memory-1", finish_reason="stop",
                           usage={"prompt_tokens": 100})


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=90001)
    parser.add_argument("--mode", choices=("none", "short", "global", "both"), default="none")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--store-manifest", type=Path)
    parser.add_argument("--population", type=int)
    parser.add_argument("--days", type=int)
    parser.add_argument("--initial-infections", type=int)
    args = parser.parse_args(argv)

    from cemas.control.llm_memory import MemoryLLMController
    from cemas.control.memory_store import FrozenPublicCaseStore
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_llm_settings, make_public_prompt_config, run_episode

    protocol = load_protocol(args.protocol)
    if args.seed not in protocol.definition["seeds"]["smoke"]:
        parser.error("offline memory smoke requires a protocol smoke seed")
    minimum_days = protocol.definition["engine"]["initial_baseline_days"] + 1
    days = protocol.execution_days if args.days is None else args.days
    if days < minimum_days:
        parser.error(f"memory smoke requires at least {minimum_days} days "
                     "to exercise an autonomous decision")
    store = None
    if args.mode in ("global", "both"):
        if args.store is None or args.store_manifest is None:
            parser.error("global/both smoke requires --store and --store-manifest")
        store = FrozenPublicCaseStore.open(args.store, args.store_manifest)
    options = {key: value for key, value in (("population", args.population), ("execution_days", args.days),
               ("initial_infections", args.initial_infections)) if value is not None}
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1",
                                 api_key_env="UNUSED_OFFLINE_MEMORY_FIXTURE")
    transport = OfflineMemoryTransport()
    transport.settings = settings
    controller = MemoryLLMController(transport, make_public_prompt_config(protocol), settings,
                                     OfflineMemoryCounter(), memory_mode=args.mode, store=store,
                                     sleeper=lambda _: None)
    try:
        result = run_episode(protocol, controller, args.output, args.seed, purpose="smoke",
                             scenario_options=options)
    finally:
        if store is not None:
            store.close()
    print(f"{result.status} (offline memory {args.mode}): {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise the LLM call chain offline, on smoke worlds, with explicit fixtures."""

import argparse
import json
from pathlib import Path


class OfflineTokenCounter:
    """An injected fixture, never an estimate or accepted provider counter."""

    identity = {"adapter": "offline_fixture", "accepted_for_live": False}

    def validate(self, settings):
        pass

    def count_input(self, messages, settings):
        return 100

    def verify_response(self, response):
        pass


class OfflineTransport:
    def __init__(self, case):
        self.case, self.calls = case, 0

    def prepare(self):
        pass

    def complete(self, messages):
        from cemas.control.llm import LLMConfigurationError, LLMResponse

        self.calls += 1
        if self.case == "fatal" and self.calls == 2:
            raise LLMConfigurationError("offline_fatal_fixture", "Expected offline fatal provider fixture")
        if self.case == "exhaust" and self.calls <= 3:
            return LLMResponse("offline invalid JSON fixture", model="offline-fixture")
        if self.case == "retry" and self.calls == 1:
            return LLMResponse("offline invalid JSON fixture", model="offline-fixture")
        return LLMResponse(json.dumps({"action": [0, 0, 0, 0, 0], "reason": "Offline fixture: routine baseline"}),
                           model="offline-fixture", response_id=f"offline-{self.calls}",
                           finish_reason="stop", usage={"prompt_tokens": 100})


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=90001)
    parser.add_argument("--case", choices=("retry", "exhaust", "fatal"), default="retry")
    parser.add_argument("--population", type=int)
    parser.add_argument("--days", type=int)
    parser.add_argument("--initial-infections", type=int)
    args = parser.parse_args(argv)

    from cemas.control.llm import LLMConfigurationError, LLMController
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_llm_settings, make_public_prompt_config, run_episode

    protocol = load_protocol(args.protocol)
    if args.seed not in protocol.definition["seeds"]["smoke"]:
        parser.error("offline smoke requires a protocol smoke seed")
    options = {key: value for key, value in (("population", args.population), ("execution_days", args.days),
               ("initial_infections", args.initial_infections)) if value is not None}
    settings = make_llm_settings(protocol, endpoint="https://offline.invalid/v1", api_key_env="UNUSED_OFFLINE_FIXTURE")
    controller = LLMController(OfflineTransport(args.case), make_public_prompt_config(protocol), settings,
                               OfflineTokenCounter(), sleeper=lambda _: None)
    try:
        result = run_episode(protocol, controller, args.output, args.seed, purpose="smoke", scenario_options=options)
    except LLMConfigurationError as error:
        if args.case != "fatal" or error.code != "offline_fatal_fixture":
            raise
        print(f"expected offline failure retained: {args.output}")
        return 0
    if args.case == "fatal":
        raise RuntimeError("fatal fixture needs a horizon longer than one week")
    print(f"{result.status} (offline fixture): {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

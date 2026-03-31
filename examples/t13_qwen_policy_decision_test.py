"""Single-shot campus policy decision test using the shared Qwen policy module.

Usage:
    conda run -n simulation python examples/t13_qwen_policy_decision_test.py
    conda run -n simulation python examples/t13_qwen_policy_decision_test.py --input-json examples/campus_policy_state_example.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim.llm_policy as cvlp


DEFAULT_INPUT_JSON = Path(__file__).with_name("campus_policy_state_example.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test a single campus policy decision via DashScope Qwen.")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_JSON), help=f"Path to input state JSON, default: {DEFAULT_INPUT_JSON}")
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"Model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument("--base-url", default=cvlp.DEFAULT_DASHSCOPE_BASE_URL, help=f"Base URL, default: {cvlp.DEFAULT_DASHSCOPE_BASE_URL}")
    parser.add_argument("--temperature", type=float, default=cvlp.DEFAULT_TEMPERATURE, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS, help="Max completion tokens.")
    return parser.parse_args()


def load_state(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: environment variable DASHSCOPE_API_KEY is not set.", file=sys.stderr)
        return 1

    state = load_state(args.input_json)
    client = cvlp.QwenPolicyClient(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    print("=== Qwen Campus Policy Decision Test ===")
    print(f"Input JSON: {args.input_json}")
    print(f"Base URL: {args.base_url}")
    print(f"Model: {args.model}")
    print(f"API key loaded: yes ({api_key[:6]}...)")
    print("Sending request...")

    try:
        response = client.decide_policy(state=state, policy_catalog=cvlp.make_default_policy_catalog())
    except Exception as exc:
        print(f"REQUEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print("Prompt payload:")
    print(json.dumps(response["user_payload"], ensure_ascii=False, indent=2))
    print("Raw model reply:")
    print(response["raw_response_text"])
    print("Parsed decision:")
    print(json.dumps(response["decision"], ensure_ascii=False, indent=2))
    print("Usage:")
    print(json.dumps(response.get("usage", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

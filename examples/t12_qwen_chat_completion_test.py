"""Minimal Qwen Chat Completions connectivity test.

Usage:
    conda run -n simulation python examples/t12_qwen_chat_completion_test.py

Optional arguments:
    --model qwen3.5-plus
    --base-url https://dashscope.aliyuncs.com/compatible-mode/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from openai import OpenAI


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-plus"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test DashScope Qwen via OpenAI Chat Completions API.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name, default: {DEFAULT_MODEL}")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"OpenAI-compatible base URL, default: {DEFAULT_BASE_URL}")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature, default: 0.0")
    parser.add_argument("--max-tokens", type=int, default=128, help="Max completion tokens, default: 128")
    return parser.parse_args()


def build_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a concise assistant. "
                "Reply in Chinese with one short sentence."
            ),
        },
        {
            "role": "user",
            "content": "请简单确认你已收到测试请求，并返回当前测试状态。",
        },
    ]


def main() -> int:
    args = parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: environment variable DASHSCOPE_API_KEY is not set.", file=sys.stderr)
        return 1

    client = OpenAI(
        api_key=api_key,
        base_url=args.base_url,
    )

    messages = build_messages()

    print("=== Qwen Chat Completions Test ===")
    print(f"Base URL: {args.base_url}")
    print(f"Model: {args.model}")
    print(f"API key loaded: yes ({api_key[:6]}...)")
    print("Sending request...")

    try:
        response = client.chat.completions.create(
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    except Exception as exc:
        print(f"REQUEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    choice = response.choices[0]
    content = choice.message.content if choice.message else None

    usage: dict[str, Any] = {}
    if getattr(response, "usage", None) is not None:
        usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage)

    print("Request succeeded.")
    print("Assistant reply:")
    print(content)
    print("Usage:")
    print(json.dumps(usage, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

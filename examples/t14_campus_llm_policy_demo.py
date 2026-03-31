"""Campus LLM weekly policy demo using the real DashScope Qwen API.

Run:
    conda run -n simulation python examples/t14_campus_llm_policy_demo.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import covasim.llm_policy as cvlp


DEFAULT_LOG_PATH = Path(__file__).with_name("campus_llm_policy_decisions.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a campus Covasim demo with weekly LLM policy decisions.")
    parser.add_argument("--pop-size", type=int, default=5000, help="Campus population size.")
    parser.add_argument("--pop-infected", type=int, default=30, help="Initial infected population.")
    parser.add_argument("--n-days", type=int, default=42, help="Simulation length in days.")
    parser.add_argument("--rand-seed", type=int, default=1, help="Random seed.")
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"Model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument("--base-url", default=os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL), help="DashScope compatible base URL.")
    parser.add_argument("--temperature", type=float, default=cvlp.DEFAULT_TEMPERATURE, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS, help="Max completion tokens.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help=f"JSONL log path, default: {DEFAULT_LOG_PATH}")
    return parser.parse_args()


def summarize_final_metrics(sim: cv.Sim) -> dict[str, float]:
    return {
        "cum_infections": float(sim.results["cum_infections"][-1]),
        "cum_diagnoses": float(sim.results["cum_diagnoses"][-1]),
        "cum_tests": float(sim.results["cum_tests"][-1]),
        "peak_quarantined": float(sim.results["n_quarantined"].values.max()),
        "r_eff_final": float(sim.results["r_eff"][-1]),
    }


def main() -> int:
    args = parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: environment variable DASHSCOPE_API_KEY is not set.", file=sys.stderr)
        return 1

    agent = cv.campus_policy_agent(
        start_day=0,
        decision_interval_days=7,
        initial_policy="P1_guarded",
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        log_path=args.log_path,
        label="campus_llm_policy_agent",
    )

    sim = cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=args.pop_size,
            pop_infected=args.pop_infected,
            n_days=args.n_days,
            rand_seed=args.rand_seed,
        ),
        interventions=[agent],
    )

    print("=== Campus LLM Policy Demo ===")
    print(f"Population: {args.pop_size}")
    print(f"Initial infected: {args.pop_infected}")
    print(f"Days: {args.n_days}")
    print(f"Model: {args.model}")
    print(f"Base URL: {args.base_url}")
    print(f"Log path: {args.log_path}")
    print("Running simulation...")

    try:
        sim.run()
    except Exception as exc:
        print(f"SIMULATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    agent = sim["interventions"][0]

    print("\n=== Weekly Decisions ===")
    for record in agent.decision_history:
        print(cvlp.summarize_policy_decision(record))
        print(json.dumps({
            "date": record["decision_date"],
            "current_policy_before": record["current_policy_before"],
            "model_policy_proposed": record["model_policy_proposed"],
            "applied_policy": record["applied_policy"],
            "fallback_used": record["fallback_used"],
            "risk_level": record["risk_level"],
            "reason": record["reason"],
            "error_type": record["error_type"],
        }, ensure_ascii=False))

    print("\n=== Final Metrics ===")
    print(json.dumps(summarize_final_metrics(sim), ensure_ascii=False, indent=2))

    print("\n=== Final Policy ===")
    print(json.dumps(agent.policy_trace[-1], ensure_ascii=False, indent=2))

    print("\nDecision log saved to:")
    print(Path(args.log_path).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

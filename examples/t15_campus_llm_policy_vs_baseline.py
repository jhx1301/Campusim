"""Compare campus LLM policy simulation against a no-policy baseline.

This example runs two campus simulations with the same base parameters:
1) baseline: no interventions
2) llm_policy: weekly campus policy decisions via the real DashScope Qwen API

It saves:
- a side-by-side comparison figure
- a CSV file with daily metrics
- a JSON file with final summary metrics

Run:
    conda run -n simulation python examples/t15_campus_llm_policy_vs_baseline.py
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
import pandas as pd
import pylab as pl


DEFAULT_LOG_PATH = Path(__file__).with_name("campus_llm_policy_vs_baseline_decisions.jsonl")
DEFAULT_OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_policy_vs_baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare campus LLM policy simulation with a no-policy baseline.")
    parser.add_argument("--pop-size", type=int, default=5000, help="Campus population size.")
    parser.add_argument("--pop-infected", type=int, default=30, help="Initial infected population.")
    parser.add_argument("--n-days", type=int, default=42, help="Simulation length in days.")
    parser.add_argument("--rand-seed", type=int, default=1, help="Random seed.")
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"Model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument("--base-url", default=os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL), help="DashScope compatible base URL.")
    parser.add_argument("--temperature", type=float, default=cvlp.DEFAULT_TEMPERATURE, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS, help="Max completion tokens.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help=f"JSONL log path, default: {DEFAULT_LOG_PATH}")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help=f"Output directory, default: {DEFAULT_OUTDIR}")
    return parser.parse_args()


def make_common_pars(args: argparse.Namespace) -> dict:
    return dict(
        pop_type="campus",
        pop_size=args.pop_size,
        pop_infected=args.pop_infected,
        n_days=args.n_days,
        rand_seed=args.rand_seed,
    )


def summarize_final_metrics(sim: cv.Sim) -> dict[str, float]:
    return {
        "cum_infections": float(sim.results["cum_infections"][-1]),
        "cum_diagnoses": float(sim.results["cum_diagnoses"][-1]),
        "cum_tests": float(sim.results["cum_tests"][-1]),
        "peak_new_infections": float(sim.results["new_infections"].values.max()),
        "peak_quarantined": float(sim.results["n_quarantined"].values.max()),
        "r_eff_final": float(sim.results["r_eff"][-1]),
    }


def make_policy_agent(args: argparse.Namespace):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: environment variable DASHSCOPE_API_KEY is not set.", file=sys.stderr)
        raise SystemExit(1)

    return cv.campus_policy_agent(
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


def run_baseline(args: argparse.Namespace) -> cv.Sim:
    sim = cv.Sim(pars=make_common_pars(args), label="baseline_no_policy")
    sim.run()
    return sim


def run_llm_policy(args: argparse.Namespace) -> cv.Sim:
    agent = make_policy_agent(args)
    sim = cv.Sim(
        pars=make_common_pars(args),
        interventions=[agent],
        label="llm_policy",
    )
    sim.run()
    return sim


def build_daily_dataframe(sim: cv.Sim, scenario: str) -> pd.DataFrame:
    data = {
        "scenario": scenario,
        "day": sim.tvec,
        "date": [sim.date(t) for t in sim.tvec],
        "new_infections": sim.results["new_infections"].values,
        "cum_infections": sim.results["cum_infections"].values,
        "new_diagnoses": sim.results["new_diagnoses"].values,
        "cum_diagnoses": sim.results["cum_diagnoses"].values,
        "new_tests": sim.results["new_tests"].values,
        "cum_tests": sim.results["cum_tests"].values,
        "n_quarantined": sim.results["n_quarantined"].values,
        "r_eff": sim.results["r_eff"].values,
    }
    return pd.DataFrame(data)


def build_policy_trace_dataframe(agent) -> pd.DataFrame:
    if not getattr(agent, "policy_trace", None):
        return pd.DataFrame(columns=["day", "date", "policy_id", "restriction_intensity", "online_teaching_active"])

    rows = []
    for row in agent.policy_trace:
        rows.append(
            {
                "day": row["day"],
                "date": row["date"],
                "policy_id": row["policy_id"],
                "restriction_intensity": row["restriction_intensity"],
                "online_teaching_active": row["online_teaching_active"],
            }
        )
    return pd.DataFrame(rows)


def save_comparison_plot(baseline_sim: cv.Sim, policy_sim: cv.Sim, outdir: Path) -> Path:
    dates = policy_sim.datevec
    agent = policy_sim["interventions"][0]
    policy_trace = build_policy_trace_dataframe(agent)

    fig = pl.figure(figsize=(13, 10))

    ax1 = fig.add_subplot(4, 1, 1)
    ax1.plot(dates, baseline_sim.results["new_infections"].values, lw=2, label="Baseline")
    ax1.plot(dates, policy_sim.results["new_infections"].values, lw=2, label="LLM policy")
    ax1.set_ylabel("New infections")
    ax1.set_title("Campus LLM policy vs baseline")
    ax1.grid(alpha=0.3)
    ax1.legend()

    ax2 = fig.add_subplot(4, 1, 2, sharex=ax1)
    ax2.plot(dates, baseline_sim.results["cum_infections"].values, lw=2, label="Baseline")
    ax2.plot(dates, policy_sim.results["cum_infections"].values, lw=2, label="LLM policy")
    ax2.set_ylabel("Cumulative infections")
    ax2.grid(alpha=0.3)
    ax2.legend()

    ax3 = fig.add_subplot(4, 1, 3, sharex=ax1)
    ax3.plot(dates, baseline_sim.results["n_quarantined"].values, lw=2, label="Baseline")
    ax3.plot(dates, policy_sim.results["n_quarantined"].values, lw=2, label="LLM policy")
    ax3.set_ylabel("Quarantined")
    ax3.grid(alpha=0.3)
    ax3.legend()

    ax4 = fig.add_subplot(4, 1, 4, sharex=ax1)
    if len(policy_trace):
        policy_days = policy_trace["day"].astype(int).values
        policy_dates = [dates[day] for day in policy_days]
        ax4.step(
            policy_dates,
            policy_trace["restriction_intensity"].values,
            where="post",
            lw=2,
            color="#aa4444",
            label="Restriction intensity",
        )
        for _, row in policy_trace.drop_duplicates(subset=["day"]).iterrows():
            day = int(row["day"])
            ax4.text(
                dates[day],
                row["restriction_intensity"] + 0.08,
                row["policy_id"],
                fontsize=8,
                rotation=30,
                ha="left",
                va="bottom",
            )
    ax4.set_ylabel("Policy level")
    ax4.set_xlabel("Date")
    ax4.set_yticks([0, 1, 2, 3, 4])
    ax4.grid(alpha=0.3)
    ax4.legend()

    fig.autofmt_xdate()
    fig.tight_layout()
    fig_path = outdir / "campus_llm_policy_vs_baseline.png"
    fig.savefig(fig_path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    return fig_path


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print("=== Campus LLM Policy vs Baseline ===")
    print(f"Population: {args.pop_size}")
    print(f"Initial infected: {args.pop_infected}")
    print(f"Days: {args.n_days}")
    print(f"Model: {args.model}")
    print(f"Base URL: {args.base_url}")
    print(f"Decision log: {Path(args.log_path).resolve()}")
    print(f"Output directory: {outdir}")

    print("\nRunning baseline simulation...")
    baseline_sim = run_baseline(args)

    print("\nRunning LLM policy simulation...")
    policy_sim = run_llm_policy(args)
    agent = policy_sim["interventions"][0]

    comparison_fig = save_comparison_plot(baseline_sim, policy_sim, outdir)

    daily_df = pd.concat(
        [
            build_daily_dataframe(baseline_sim, "baseline_no_policy"),
            build_daily_dataframe(policy_sim, "llm_policy"),
        ],
        ignore_index=True,
    )
    daily_csv_path = outdir / "daily_metrics.csv"
    daily_df.to_csv(daily_csv_path, index=False, encoding="utf-8-sig")

    policy_trace_df = build_policy_trace_dataframe(agent)
    policy_trace_csv_path = outdir / "policy_trace.csv"
    policy_trace_df.to_csv(policy_trace_csv_path, index=False, encoding="utf-8-sig")

    summary = {
        "baseline_no_policy": summarize_final_metrics(baseline_sim),
        "llm_policy": summarize_final_metrics(policy_sim),
        "decision_count": len(agent.decision_history),
        "final_policy": agent.policy_trace[-1] if agent.policy_trace else None,
    }
    summary_path = outdir / "summary_metrics.json"
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print("\n=== Final Metrics ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n=== Saved artifacts ===")
    print(comparison_fig)
    print(daily_csv_path)
    print(policy_trace_csv_path)
    print(summary_path)
    print(Path(args.log_path).resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

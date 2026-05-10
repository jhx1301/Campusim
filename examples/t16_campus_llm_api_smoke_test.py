"""Lightweight real-API campus policy smoke test with visual summary.

This example is designed for real LLM API usage with a much smaller budget than
``t15_campus_llm_policy_vs_baseline.py``. By default it runs:

1. A single transmission scenario (``medium``)
2. A single random seed
3. Three strategies:
   - ``baseline_no_policy``
   - ``baseline_threshold``
   - ``llm_single_memory``

Outputs include a comparison figure, CSV/JSON artifacts, and a Markdown report
that is easy to scan after a real API run.
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
import numpy as np
import pandas as pd
import pylab as pl


DEFAULT_OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_api_smoke_test"
SCENARIOS = {
    "low": dict(beta_scale=0.90, pop_infected=180),
    "medium": dict(beta_scale=1.00, pop_infected=300),
    "high": dict(beta_scale=1.12, pop_infected=450),
}
DEFAULT_STRATEGIES = [
    "baseline_no_policy",
    "baseline_threshold",
    "llm_single_memory",
]
SUPPORTED_STRATEGIES = [
    "baseline_no_policy",
    "baseline_threshold",
    "baseline_single_agent_nomemory",
    "llm_single_memory",
    "llm_ensemble_memory",
]
API_STRATEGIES = {
    "baseline_single_agent_nomemory",
    "llm_single_memory",
    "llm_ensemble_memory",
}
STRATEGY_LABELS = {
    "baseline_no_policy": "No policy",
    "baseline_threshold": "Threshold baseline",
    "baseline_single_agent_nomemory": "LLM-style baseline",
    "llm_single_memory": "Real LLM memory",
    "llm_ensemble_memory": "Real LLM ensemble",
}
STRATEGY_COLORS = {
    "baseline_no_policy": "#D96C5F",
    "baseline_threshold": "#4F7CAC",
    "baseline_single_agent_nomemory": "#8F6593",
    "llm_single_memory": "#2D936C",
    "llm_ensemble_memory": "#F2A65A",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small real-API campus policy comparison.")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="medium", help="Transmission scenario.")
    parser.add_argument("--pop-size", type=int, default=40000, help="Campus population size.")
    parser.add_argument("--n-days", type=int, default=42, help="Simulation length in days.")
    parser.add_argument("--rand-seed", type=int, default=1, help="Single random seed for the smoke test.")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=list(DEFAULT_STRATEGIES),
        choices=SUPPORTED_STRATEGIES,
        help="Strategies to compare. Default keeps token cost small.",
    )
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"Model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument(
        "--base-url",
        default=os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL),
        help="DashScope compatible base URL.",
    )
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS, help="Max completion tokens.")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help=f"Output directory, default: {DEFAULT_OUTDIR}")
    parser.add_argument(
        "--skip-if-no-api-key",
        action="store_true",
        help="Exit successfully with a skip message if DASHSCOPE_API_KEY is missing.",
    )
    return parser.parse_args()


def make_common_pars(args: argparse.Namespace) -> dict:
    scenario = SCENARIOS[args.scenario]
    return dict(
        pop_type="campus",
        pop_size=args.pop_size,
        pop_infected=scenario["pop_infected"],
        n_days=args.n_days,
        rand_seed=args.rand_seed,
        beta=0.016 * scenario["beta_scale"],
    )


def make_threshold_decision_fn():
    def decision_fn(state, policy_catalog):
        summary = state.get("past_7d_summary", {})
        burden = state.get("intervention_burden_last_7d", {})
        infections = float(summary.get("new_infections_sum", 0.0))
        r_eff = float(summary.get("r_eff_current", 0.0))
        quarantined = float(burden.get("mean_quarantined_per_1000", 0.0))
        if infections >= 70 or r_eff >= 1.25:
            policy_id, risk_level = "P4_emergency", "critical"
        elif infections >= 40 or r_eff >= 1.10:
            policy_id, risk_level = "P3_strong", "high"
        elif infections >= 18 or r_eff >= 1.00:
            policy_id, risk_level = "P2_moderate", "medium"
        elif quarantined >= 18:
            policy_id, risk_level = "P1_guarded", "medium"
        else:
            policy_id, risk_level = "P1_guarded", "low"
        return {"policy_id": policy_id, "risk_level": risk_level, "reason": "Threshold rule output"}

    return decision_fn


def make_policy_agent(args: argparse.Namespace, strategy_name: str, outdir: Path):
    common = dict(
        start_day=0,
        decision_interval_days=7,
        initial_policy="P0_normal",
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        label=f"{strategy_name}_agent",
    )

    if strategy_name == "baseline_threshold":
        return cv.campus_policy_agent(
            decision_fn=make_threshold_decision_fn(),
            use_theory_prompt=False,
            memory_weeks=0,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=True,
            defer_first_decision_until_interval=True,
            log_path=str(outdir / f"{strategy_name}_decision_log.jsonl"),
            **common,
        )

    if strategy_name == "baseline_single_agent_nomemory":
        return cv.campus_policy_agent(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=False,
            memory_weeks=0,
            ensemble_size=1,
            min_policy_hold_intervals=0,
            enable_burden_guardrail=False,
            defer_first_decision_until_interval=True,
            log_path=str(outdir / f"{strategy_name}_decision_log.jsonl"),
            **common,
        )

    if strategy_name == "llm_single_memory":
        return cv.campus_policy_agent(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            defer_first_decision_until_interval=True,
            log_path=str(outdir / f"{strategy_name}_decision_log.jsonl"),
            **common,
        )

    if strategy_name == "llm_ensemble_memory":
        return cv.campus_policy_agent(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=4,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            defer_first_decision_until_interval=True,
            log_path=str(outdir / f"{strategy_name}_decision_log.jsonl"),
            **common,
        )

    raise ValueError(f"Unsupported strategy: {strategy_name}")


def run_strategy_once(args: argparse.Namespace, strategy_name: str, outdir: Path) -> cv.Sim:
    pars = make_common_pars(args)
    if strategy_name == "baseline_no_policy":
        sim = cv.Sim(pars=pars, label=strategy_name)
    else:
        sim = cv.Sim(pars=pars, interventions=[make_policy_agent(args, strategy_name, outdir)], label=strategy_name)
    sim.run()
    return sim


def summarize_final_metrics(sim: cv.Sim, strategy_name: str, scenario_name: str, rand_seed: int) -> dict[str, float]:
    agent = sim["interventions"][0] if sim["interventions"] else None
    trace = getattr(agent, "policy_trace", []) if agent is not None else []
    policy_ids = [row["policy_id"] for row in trace]
    switch_count = sum(int(policy_ids[idx] != policy_ids[idx - 1]) for idx in range(1, len(policy_ids)))
    teaching_days = int(sum(1 for row in trace if row.get("online_teaching_active")))
    restriction_days = float(sum(row.get("restriction_intensity", 0) for row in trace))
    return {
        "scenario": scenario_name,
        "strategy": strategy_name,
        "seed": int(rand_seed),
        "cum_infections": float(sim.results["cum_infections"][-1]),
        "cum_diagnoses": float(sim.results["cum_diagnoses"][-1]),
        "cum_tests": float(sim.results["cum_tests"][-1]),
        "mean_quarantined": float(np.mean(sim.results["n_quarantined"].values)),
        "peak_quarantined": float(np.max(sim.results["n_quarantined"].values)),
        "r_eff_final": float(sim.results["r_eff"][-1]),
        "teaching_restriction_days": teaching_days,
        "restriction_intensity_days": restriction_days,
        "policy_switch_count": float(switch_count),
        "policy_oscillation_score": cvlp.compute_policy_oscillation_score(policy_ids, getattr(agent, "policy_catalog", None)),
        "decision_count": float(len(getattr(agent, "decision_history", []))) if agent is not None else 0.0,
        "final_policy": trace[-1]["policy_id"] if trace else "none",
    }


def build_daily_metrics(sim: cv.Sim, strategy_name: str) -> pd.DataFrame:
    days = np.arange(len(sim.results["cum_infections"].values))
    df = pd.DataFrame(
        {
            "day": days,
            "strategy": strategy_name,
            "cum_infections": sim.results["cum_infections"].values,
            "new_infections": sim.results["new_infections"].values,
            "cum_tests": sim.results["cum_tests"].values,
            "n_quarantined": sim.results["n_quarantined"].values,
            "r_eff": sim.results["r_eff"].values,
        }
    )
    df["new_infections_7d_avg"] = df["new_infections"].rolling(window=7, min_periods=1).mean()
    return df


def build_policy_trace_df(sim: cv.Sim, strategy_name: str) -> pd.DataFrame:
    agent = sim["interventions"][0] if sim["interventions"] else None
    if agent is None or not getattr(agent, "policy_trace", None):
        return pd.DataFrame(
            {
                "strategy": [strategy_name],
                "day": [0],
                "date": [sim.date(0)],
                "policy_id": ["none"],
                "policy_rank": [-1],
                "restriction_intensity": [0],
                "online_teaching_active": [False],
            }
        )

    rows = []
    for row in agent.policy_trace:
        policy_id = row.get("policy_id", "none")
        rows.append(
            {
                "strategy": strategy_name,
                "day": int(row.get("day", 0)),
                "date": row.get("date"),
                "policy_id": policy_id,
                "policy_rank": cvlp.get_policy_rank(policy_id, agent.policy_catalog) if policy_id in agent.policy_catalog else -1,
                "restriction_intensity": row.get("restriction_intensity", 0),
                "online_teaching_active": bool(row.get("online_teaching_active", False)),
            }
        )
    return pd.DataFrame(rows)


def build_decision_summary_df(sim: cv.Sim, strategy_name: str) -> pd.DataFrame:
    agent = sim["interventions"][0] if sim["interventions"] else None
    if agent is None or not getattr(agent, "decision_history", None):
        return pd.DataFrame(
            columns=[
                "strategy",
                "decision_day",
                "decision_date",
                "current_policy_before",
                "model_policy_proposed",
                "applied_policy",
                "risk_level",
                "reason",
                "fallback_used",
                "guardrail_adjusted",
                "error_type",
            ]
        )

    rows = []
    for record in agent.decision_history:
        rows.append(
            {
                "strategy": strategy_name,
                "decision_day": record.get("decision_day"),
                "decision_date": record.get("decision_date"),
                "current_policy_before": record.get("current_policy_before"),
                "model_policy_proposed": record.get("model_policy_proposed"),
                "applied_policy": record.get("applied_policy"),
                "risk_level": record.get("risk_level"),
                "reason": record.get("reason"),
                "fallback_used": record.get("fallback_used"),
                "guardrail_adjusted": record.get("guardrail_adjusted"),
                "error_type": record.get("error_type"),
            }
        )
    return pd.DataFrame(rows)


def _strategy_color(strategy_name: str) -> str:
    return STRATEGY_COLORS.get(strategy_name, "#6C757D")


def _strategy_label(strategy_name: str) -> str:
    return STRATEGY_LABELS.get(strategy_name, strategy_name)


def _markdown_table(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    table_df = df if columns is None else df.loc[:, columns]
    headers = list(table_df.columns)
    rows = []
    for row in table_df.itertuples(index=False, name=None):
        formatted = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                formatted.append(f"{float(value):.2f}")
            elif pd.isna(value):
                formatted.append("")
            else:
                formatted.append(str(value))
        rows.append(formatted)

    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def save_comparison_plot(
    run_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    trace_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    outdir: Path,
) -> Path:
    strategies = list(run_df["strategy"])
    fig = pl.figure(figsize=(15, 12))
    ax1 = fig.add_subplot(3, 2, 1)
    ax2 = fig.add_subplot(3, 2, 2)
    ax3 = fig.add_subplot(3, 2, 3)
    ax4 = fig.add_subplot(3, 2, 4)
    ax5 = fig.add_subplot(3, 2, 5)

    for strategy_name in strategies:
        subset = daily_df[daily_df["strategy"] == strategy_name]
        ax1.plot(
            subset["day"],
            subset["cum_infections"],
            label=_strategy_label(strategy_name),
            color=_strategy_color(strategy_name),
            linewidth=2.2,
        )
        ax2.plot(
            subset["day"],
            subset["new_infections_7d_avg"],
            label=_strategy_label(strategy_name),
            color=_strategy_color(strategy_name),
            linewidth=2.0,
        )
        ax3.plot(
            subset["day"],
            subset["n_quarantined"],
            label=_strategy_label(strategy_name),
            color=_strategy_color(strategy_name),
            linewidth=2.0,
        )

        trace_subset = trace_df[trace_df["strategy"] == strategy_name]
        ax4.step(
            trace_subset["day"],
            trace_subset["policy_rank"],
            where="post",
            label=_strategy_label(strategy_name),
            color=_strategy_color(strategy_name),
            linewidth=2.2,
        )

    ax1.set_title("Cumulative infections")
    ax1.set_xlabel("Day")
    ax1.set_ylabel("People")
    ax1.grid(alpha=0.3)

    ax2.set_title("7-day average new infections")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("People/day")
    ax2.grid(alpha=0.3)

    ax3.set_title("Quarantine burden")
    ax3.set_xlabel("Day")
    ax3.set_ylabel("People quarantined")
    ax3.grid(alpha=0.3)

    ax4.set_title("Policy intensity over time")
    ax4.set_xlabel("Day")
    ax4.set_ylabel("Policy rank")
    ax4.set_yticks([-1, 0, 1, 2, 3, 4])
    ax4.set_yticklabels(["none", "P0", "P1", "P2", "P3", "P4"])
    ax4.grid(alpha=0.3)

    ranking_plot_df = ranking_df.set_index("strategy").reindex(strategies).reset_index()
    ax5.bar(
        [_strategy_label(name) for name in ranking_plot_df["strategy"]],
        ranking_plot_df["CPBU"],
        color=[_strategy_color(name) for name in ranking_plot_df["strategy"]],
    )
    ax5.set_title("CPBU overall balance score")
    ax5.set_ylabel("CPBU")
    ax5.tick_params(axis="x", rotation=15)
    ax5.grid(alpha=0.3, axis="y")
    for idx, value in enumerate(ranking_plot_df["CPBU"]):
        ax5.text(idx, float(value) + 0.01, f"{float(value):.3f}", ha="center", va="bottom", fontsize=9)

    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=min(4, max(1, len(labels))), frameon=False)
    fig.suptitle("Campus LLM real-API smoke test", fontsize=16, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    fig_path = outdir / "campus_llm_api_smoke_test.png"
    fig.savefig(fig_path, dpi=220, bbox_inches="tight")
    pl.close(fig)
    return fig_path


def build_markdown_report(args: argparse.Namespace, run_df: pd.DataFrame, decision_df: pd.DataFrame, fig_path: Path) -> str:
    llm_rows = run_df[run_df["strategy"].str.contains("llm")]
    infection_best = run_df.sort_values("cum_infections").iloc[0]
    low_burden_best = run_df.sort_values(["mean_quarantined", "cum_tests"]).iloc[0]

    lines = [
        "# Campus LLM API Smoke Test Summary",
        "",
        "## Run setup",
        "",
        f"- Scenario: `{args.scenario}`",
        f"- Population: `{args.pop_size}`",
        f"- Days: `{args.n_days}`",
        f"- Seed: `{args.rand_seed}`",
        f"- Strategies: `{', '.join(run_df['strategy'])}`",
        f"- Model: `{args.model}`",
        f"- Base URL: `{args.base_url}`",
        "",
        "## Key takeaways",
        "",
        f"- Lowest cumulative infections: `{infection_best['strategy']}` with `{infection_best['cum_infections']:.0f}` infections.",
        f"- Lowest operational burden: `{low_burden_best['strategy']}` with `{low_burden_best['mean_quarantined']:.1f}` mean quarantined and `{low_burden_best['cum_tests']:.0f}` tests.",
    ]

    if len(llm_rows):
        llm_row = llm_rows.sort_values("cum_infections").iloc[0]
        lines.append(
            f"- Best LLM strategy in this run: `{llm_row['strategy']}` ending at policy `{llm_row['final_policy']}` after `{llm_row['decision_count']:.0f}` decisions."
        )

    lines.extend(
        [
            "",
            "## Final metrics",
            "",
            _markdown_table(run_df),
            "",
            "## Decision trace",
            "",
        ]
    )

    if len(decision_df):
        lines.append(
            _markdown_table(
                decision_df,
                columns=[
                    "strategy",
                    "decision_day",
                    "applied_policy",
                    "risk_level",
                    "reason",
                    "fallback_used",
                    "guardrail_adjusted",
                ],
            )
        )
    else:
        lines.append("No policy decisions were recorded.")

    lines.extend(
        [
            "",
            "## Figure",
            "",
            f"![Campus LLM smoke test]({fig_path.name})",
            "",
        ]
    )
    return "\n".join(lines)


def make_benchmark_input_df(run_df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "cum_infections",
        "cum_diagnoses",
        "cum_tests",
        "mean_quarantined",
        "peak_quarantined",
        "r_eff_final",
        "teaching_restriction_days",
        "restriction_intensity_days",
        "policy_switch_count",
        "policy_oscillation_score",
        "decision_count",
    ]
    keep_cols = ["scenario", "strategy", "seed", *numeric_cols]
    return run_df.loc[:, keep_cols].copy()


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("DASHSCOPE_API_KEY")
    requested_api = any(strategy in API_STRATEGIES for strategy in args.strategies)
    if requested_api and not api_key:
        message = "SKIP: DASHSCOPE_API_KEY is not set, so real LLM strategies cannot run."
        print(message)
        return 0 if args.skip_if_no_api_key or __name__ == "__main__" else 1

    print("=== Campus LLM API Smoke Test ===")
    print(f"Scenario: {args.scenario}")
    print(f"Population: {args.pop_size}")
    print(f"Days: {args.n_days}")
    print(f"Seed: {args.rand_seed}")
    print(f"Strategies: {args.strategies}")
    print(f"Model: {args.model}")
    print(f"Output directory: {outdir}")

    rows = []
    daily_frames = []
    trace_frames = []
    decision_frames = []

    for strategy_name in args.strategies:
        print(f"\nRunning {strategy_name} ...")
        sim = run_strategy_once(args, strategy_name, outdir)
        rows.append(summarize_final_metrics(sim, strategy_name, args.scenario, args.rand_seed))
        daily_frames.append(build_daily_metrics(sim, strategy_name))
        trace_frames.append(build_policy_trace_df(sim, strategy_name))
        decision_frames.append(build_decision_summary_df(sim, strategy_name))

    run_df = pd.DataFrame(rows).sort_values("cum_infections").reset_index(drop=True)
    daily_df = pd.concat(daily_frames, ignore_index=True)
    trace_df = pd.concat(trace_frames, ignore_index=True)
    decision_df = pd.concat(decision_frames, ignore_index=True)
    benchmark_df = make_benchmark_input_df(run_df)
    evaluation = cvlp.evaluate_policy_benchmark(benchmark_df)
    ranking_df = evaluation["ranking_df"]
    aggregate_df = evaluation["aggregate_df"]

    run_csv_path = outdir / "run_metrics.csv"
    daily_csv_path = outdir / "daily_metrics.csv"
    trace_csv_path = outdir / "policy_trace.csv"
    decision_csv_path = outdir / "decision_summary.csv"
    aggregate_csv_path = outdir / "aggregate_metrics.csv"
    ranking_csv_path = outdir / "ranking_metrics.csv"
    summary_json_path = outdir / "summary_metrics.json"
    fig_path = save_comparison_plot(run_df, daily_df, trace_df, ranking_df, outdir)
    report_path = outdir / "summary_report.md"

    run_df.to_csv(run_csv_path, index=False, encoding="utf-8-sig")
    daily_df.to_csv(daily_csv_path, index=False, encoding="utf-8-sig")
    trace_df.to_csv(trace_csv_path, index=False, encoding="utf-8-sig")
    decision_df.to_csv(decision_csv_path, index=False, encoding="utf-8-sig")
    aggregate_df.to_csv(aggregate_csv_path, index=False, encoding="utf-8-sig")
    ranking_df.to_csv(ranking_csv_path, index=False, encoding="utf-8-sig")

    with summary_json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "scenario": args.scenario,
                "seed": args.rand_seed,
                "strategies": args.strategies,
                "model": args.model,
                "base_url": args.base_url,
                "run_metrics": json.loads(run_df.to_json(orient="records")),
                "aggregate_metrics": json.loads(aggregate_df.to_json(orient="records")),
                "ranking_metrics": json.loads(ranking_df.to_json(orient="records")),
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    report_text = build_markdown_report(args, run_df, decision_df, fig_path)
    report_path.write_text(report_text, encoding="utf-8")

    print("\n=== Final metrics ===")
    print(run_df.to_string(index=False))
    print("\n=== Ranking ===")
    print(ranking_df.to_string(index=False))
    print("\n=== Saved artifacts ===")
    print(fig_path)
    print(report_path)
    print(run_csv_path)
    print(daily_csv_path)
    print(trace_csv_path)
    print(decision_csv_path)
    print(aggregate_csv_path)
    print(ranking_csv_path)
    print(summary_json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

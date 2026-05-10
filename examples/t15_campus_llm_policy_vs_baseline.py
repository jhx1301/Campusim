"""Benchmark campus policy strategies across transmission scenarios.

This script compares:
1) baseline_no_policy
2) baseline_threshold
3) baseline_single_agent_nomemory
4) llm_single_memory
5) llm_ensemble_memory

By default it can run fully offline with surrogate policy decisions.
Set ``--use-api`` and ``DASHSCOPE_API_KEY`` to use the real Qwen client.
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


DEFAULT_OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_policy_vs_baseline"
SCENARIOS = {
    "low": dict(beta_scale=0.90, pop_infected=18),
    "medium": dict(beta_scale=1.00, pop_infected=30),
    "high": dict(beta_scale=1.12, pop_infected=45),
}
STRATEGIES = [
    "baseline_no_policy",
    "baseline_threshold",
    "baseline_single_agent_nomemory",
    "llm_single_memory",
    "llm_ensemble_memory",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark campus LLM policy strategies.")
    parser.add_argument("--pop-size", type=int, default=4000, help="Campus population size.")
    parser.add_argument("--n-days", type=int, default=56, help="Simulation length in days.")
    parser.add_argument("--seeds", type=int, default=20, help="Number of random seeds per scenario.")
    parser.add_argument("--scenario", choices=["all", *SCENARIOS.keys()], default="all", help="Transmission scenario.")
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"Model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument("--base-url", default=os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL), help="DashScope compatible base URL.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature.")
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS, help="Max completion tokens.")
    parser.add_argument("--log-path", default=None, help="Optional JSONL log path prefix. Disabled by default.")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help=f"Output directory, default: {DEFAULT_OUTDIR}")
    parser.add_argument("--use-api", action="store_true", help="Use the real DashScope Qwen client for LLM strategies.")
    return parser.parse_args()


def make_common_pars(args: argparse.Namespace, scenario_name: str, seed: int) -> dict:
    scenario = SCENARIOS[scenario_name]
    return dict(
        pop_type="campus",
        pop_size=args.pop_size,
        pop_infected=scenario["pop_infected"],
        n_days=args.n_days,
        rand_seed=seed,
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
        return {"policy_id": policy_id, "risk_level": risk_level, "reason": "阈值策略输出"}

    return decision_fn


def make_surrogate_llm_decision_fn(mode: str):
    def decision_fn(state, policy_catalog):
        summary = state.get("past_7d_summary", {})
        effect = state.get("policy_effect_summary", {})
        volatility = state.get("policy_volatility_last_4w", {})
        burden = state.get("intervention_burden_last_7d", {})
        infections = float(summary.get("new_infections_sum", 0.0))
        growth = float(state.get("growth_ratio_7d_vs_prev_7d", 1.0))
        r_eff = float(summary.get("r_eff_current", 0.0))
        current_policy = state.get("current_policy") or "P0_normal"
        current_rank = cvlp.get_policy_rank(current_policy, policy_catalog)

        target_rank = current_rank
        if infections >= 60 or r_eff >= 1.20 or summary.get("estimated_risk_trend") == "worsening":
            target_rank = max(target_rank, 3)
        if infections >= 85 or (r_eff >= 1.30 and growth > 1.15):
            target_rank = 4
        if infections <= 12 and r_eff < 0.95:
            target_rank = min(target_rank, 1)
        if infections <= 6 and r_eff < 0.90 and summary.get("new_infections_trend") == "down":
            target_rank = 0

        if mode != "nomemory":
            if effect.get("dominant_effect_trend") == "improving":
                target_rank = min(target_rank, current_rank)
            if effect.get("dominant_effect_trend") == "worsening":
                target_rank = max(target_rank, current_rank + 1)
            if volatility.get("policy_oscillation_score", 0.0) >= 2.0:
                target_rank = max(current_rank, target_rank - 1)
            if float(burden.get("mean_quarantined_per_1000", 0.0)) >= 20.0 and r_eff <= 1.0:
                target_rank = min(target_rank, current_rank)

        target_rank = int(np.clip(target_rank, 0, 4))
        if target_rank >= 4:
            risk_level = "critical"
        elif target_rank >= 3:
            risk_level = "high"
        elif target_rank >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"
        return {
            "policy_id": cvlp.get_policy_by_rank(target_rank, policy_catalog),
            "risk_level": risk_level,
            "reason": "离线代理策略输出",
        }

    return decision_fn


def make_policy_agent(args: argparse.Namespace, strategy_name: str, scenario_name: str, seed: int):
    log_path = None
    if args.log_path:
        log_stem = Path(args.log_path)
        log_path = log_stem.with_name(f"{log_stem.stem}_{scenario_name}_{strategy_name}_seed{seed}.jsonl")
    common = dict(
        start_day=0,
        decision_interval_days=7,
        initial_policy="P0_normal",
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        log_path=str(log_path) if log_path is not None else None,
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
            **common,
        )

    if strategy_name == "baseline_single_agent_nomemory":
        decision_fn = None if args.use_api else make_surrogate_llm_decision_fn("nomemory")
        return cv.campus_policy_agent(
            decision_fn=decision_fn,
            use_theory_prompt=False,
            memory_weeks=0,
            ensemble_size=1,
            min_policy_hold_intervals=0,
            enable_burden_guardrail=False,
            defer_first_decision_until_interval=True,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            **common,
        )

    if strategy_name == "llm_single_memory":
        decision_fn = None if args.use_api else make_surrogate_llm_decision_fn("memory")
        return cv.campus_policy_agent(
            decision_fn=decision_fn,
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            defer_first_decision_until_interval=True,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            **common,
        )

    if strategy_name == "llm_ensemble_memory":
        decision_fn = None if args.use_api else make_surrogate_llm_decision_fn("memory")
        return cv.campus_policy_agent(
            decision_fn=decision_fn,
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=5,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            defer_first_decision_until_interval=True,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            **common,
        )

    raise ValueError(f"Unsupported strategy: {strategy_name}")


def run_strategy_once(args: argparse.Namespace, scenario_name: str, strategy_name: str, seed: int) -> cv.Sim:
    pars = make_common_pars(args, scenario_name, seed)
    if strategy_name == "baseline_no_policy":
        sim = cv.Sim(pars=pars, label=strategy_name)
    else:
        sim = cv.Sim(pars=pars, interventions=[make_policy_agent(args, strategy_name, scenario_name, seed)], label=strategy_name)
    sim.run()
    return sim


def summarize_final_metrics(sim: cv.Sim, strategy_name: str, scenario_name: str, seed: int) -> dict[str, float]:
    agent = sim["interventions"][0] if sim["interventions"] else None
    trace = getattr(agent, "policy_trace", []) if agent is not None else []
    policy_ids = [row["policy_id"] for row in trace]
    switch_count = sum(int(policy_ids[idx] != policy_ids[idx - 1]) for idx in range(1, len(policy_ids)))
    teaching_days = int(sum(1 for row in trace if row.get("online_teaching_active")))
    restriction_days = float(sum(row.get("restriction_intensity", 0) for row in trace))
    return {
        "scenario": scenario_name,
        "strategy": strategy_name,
        "seed": int(seed),
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
    }


def save_summary_plot(agg_df: pd.DataFrame, outdir: Path) -> Path:
    high_df = agg_df[agg_df["scenario"] == "high"].copy()
    fig = pl.figure(figsize=(12, 8))
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)
    ax1.bar(high_df["strategy"], high_df["cum_infections_mean"], color="#d16d5b")
    ax1.set_ylabel("Mean cumulative infections")
    ax1.set_title("High-transmission scenario benchmark")
    ax1.tick_params(axis="x", rotation=20)
    ax1.grid(alpha=0.3, axis="y")

    ax2.bar(high_df["strategy"], high_df["policy_oscillation_score_mean"], color="#507dbc")
    ax2.set_ylabel("Mean oscillation score")
    ax2.tick_params(axis="x", rotation=20)
    ax2.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig_path = outdir / "campus_llm_policy_vs_baseline.png"
    fig.savefig(fig_path, dpi=200, bbox_inches="tight")
    pl.close(fig)
    return fig_path


def main() -> int:
    args = parse_args()
    if args.use_api and not os.getenv("DASHSCOPE_API_KEY"):
        print("ERROR: --use-api requires DASHSCOPE_API_KEY.", file=sys.stderr)
        return 1

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    scenarios = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    seeds = list(range(1, args.seeds + 1))
    print("=== Campus Policy Benchmark ===")
    print(f"Scenarios: {scenarios}")
    print(f"Seeds per scenario: {len(seeds)}")
    print(f"Strategies: {STRATEGIES}")
    print(f"Using real API: {args.use_api}")

    rows = []
    for scenario_name in scenarios:
        for strategy_name in STRATEGIES:
            print(f"\nRunning {scenario_name} / {strategy_name} ...")
            for seed in seeds:
                sim = run_strategy_once(args, scenario_name, strategy_name, seed)
                rows.append(summarize_final_metrics(sim, strategy_name, scenario_name, seed))

    run_df = pd.DataFrame(rows)
    evaluation = cvlp.evaluate_policy_benchmark(run_df)
    agg_df = evaluation["aggregate_df"]
    ranking_df = evaluation["ranking_df"]
    plot_path = save_summary_plot(agg_df, outdir)

    run_csv_path = outdir / "run_metrics.csv"
    agg_csv_path = outdir / "summary_metrics.csv"
    ranking_csv_path = outdir / "pareto_scores.csv"
    summary_json_path = outdir / "summary_metrics.json"

    run_df.to_csv(run_csv_path, index=False, encoding="utf-8-sig")
    agg_df.to_csv(agg_csv_path, index=False, encoding="utf-8-sig")
    ranking_df.to_csv(ranking_csv_path, index=False, encoding="utf-8-sig")
    with summary_json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "scenarios": scenarios,
                "strategies": STRATEGIES,
                "use_api": args.use_api,
                "cpbu_weights": evaluation["cpbu_weights"],
                "per_cost_weights": evaluation["per_cost_weights"],
                "aggregate_summary": json.loads(agg_df.to_json(orient="records")),
                "pareto_scores": json.loads(ranking_df.to_json(orient="records")),
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print("\n=== Aggregate Summary ===")
    print(agg_df.to_string(index=False))
    print("\n=== Saved artifacts ===")
    print(plot_path)
    print(run_csv_path)
    print(agg_csv_path)
    print(ranking_csv_path)
    print(summary_json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

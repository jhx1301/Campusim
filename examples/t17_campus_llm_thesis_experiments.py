"""Thesis-ready campus LLM policy experiments.

This script implements the experiment plan used in the final thesis chapter:

1. Model validation: no-policy doubling time, fixed-policy online teaching
   effects, and layer transmission contribution.
2. Strategy comparison: no policy, threshold policy, and LLM-style policy.
3. Memory ablation: single-agent decisions with and without memory.
4. Guardrail ablation: memory policy with and without burden guardrails.
5. Robustness: low, medium, and high transmission scenarios over multiple seeds.

The default ``quick`` preset is intended for smoke tests. Use ``--preset paper``
to run the 40000-person, 84-day setup from the thesis design.

Examples:
    python examples/t17_campus_llm_thesis_experiments.py --preset quick
    python examples/t17_campus_llm_thesis_experiments.py --preset paper --experiment core
    python examples/t17_campus_llm_thesis_experiments.py --preset paper --use-api --experiment policy
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import covasim.llm_policy as cvlp
import covasim.llm_memory as cvlm
import numpy as np
import pandas as pd
import pylab as pl


DEFAULT_OUTDIR = Path(__file__).resolve().parent / "figures" / "campus_llm_thesis_experiments"

PAPER_SCENARIOS = {
    "low": dict(beta_scale=0.90, pop_infected=180),
    "medium": dict(beta_scale=1.00, pop_infected=300),
    "high": dict(beta_scale=1.12, pop_infected=450),
}
SENSITIVITY_VARIANTS = {
    "medium_base": dict(base_scenario="medium", description="Baseline medium-transmission parameter set."),
    "medium_dorm_beta_low": dict(base_scenario="medium", beta_layer_scale=dict(d=0.80), description="Dormitory layer transmission weight -20%."),
    "medium_dorm_beta_high": dict(base_scenario="medium", beta_layer_scale=dict(d=1.20), description="Dormitory layer transmission weight +20%."),
    "medium_class_contacts_low": dict(base_scenario="medium", contacts_scale=dict(clu=0.80, clg=0.80), description="Classroom contacts -20%."),
    "medium_class_contacts_high": dict(base_scenario="medium", contacts_scale=dict(clu=1.20, clg=1.20), description="Classroom contacts +20%."),
    "medium_common_contacts_low": dict(base_scenario="medium", contacts_scale=dict(cm=0.80), description="Campus common-space contacts -20%."),
    "medium_common_contacts_high": dict(base_scenario="medium", contacts_scale=dict(cm=1.20), description="Campus common-space contacts +20%."),
}
QUICK_SCENARIOS = {
    name: dict(beta_scale=pars["beta_scale"], pop_infected=max(2, int(round(pars["pop_infected"] / 10))))
    for name, pars in PAPER_SCENARIOS.items()
}

CORE_STRATEGIES = ["baseline_no_policy", "baseline_threshold", "llm_single_memory"]
ABLATION_STRATEGIES = [
    "ablation_no_expert_no_memory",
    "ablation_memory_only",
    "ablation_expert_only",
    "ablation_expert_and_memory",
    "llm_dual_memory",
]
ALL_STRATEGIES = [
    "baseline_no_policy",
    "baseline_threshold",
    "baseline_single_agent_nomemory",
    "llm_single_memory",
    "llm_ensemble_memory",
    "ablation_no_expert_no_memory",
    "ablation_memory_only",
    "ablation_expert_only",
    "ablation_expert_and_memory",
    "llm_dual_memory",
]
FIXED_POLICIES = ["P0_normal", "P1_guarded", "P2_moderate", "P3_strong", "P4_emergency"]
API_STRATEGIES = {
    "baseline_single_agent_nomemory",
    "llm_single_memory",
    "llm_ensemble_memory",
    "ablation_no_expert_no_memory",
    "ablation_memory_only",
    "ablation_expert_only",
    "ablation_expert_and_memory",
    "llm_dual_memory",
}
CAMPUS_LAYERS = list(cvlp.CAMPUS_LAYER_KEYS)
LAYER_GROUPS = {
    "dorm_d": ("d",),
    "classroom_clu_clg": ("clu", "clg"),
    "office_lab_of_ta": ("of", "ta"),
    "common_cm": ("cm",),
}

STRATEGY_COLORS = {
    "baseline_no_policy": "#d6604d",
    "baseline_threshold": "#4393c3",
    "baseline_single_agent_nomemory": "#9970ab",
    "llm_single_memory": "#1b9e77",
    "llm_ensemble_memory": "#e6ab02",
    "llm_memory_without_guardrail": "#66a61e",
    "llm_memory_with_guardrail": "#1b9e77",
    "llm_dual_memory": "#e7298a",
    "fixed_P0_normal": "#999999",
    "fixed_P2_moderate": "#80cdc1",
    "fixed_P3_strong": "#dfc27d",
    "fixed_P4_emergency": "#bf812d",
    "ablation_no_expert_no_memory": "#d6604d",
    "ablation_memory_only": "#4393c3",
    "ablation_expert_only": "#9970ab",
    "ablation_expert_and_memory": "#1b9e77",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run thesis campus LLM policy experiments.")
    parser.add_argument(
        "--experiment",
        choices=["all", "core", "validation", "policy", "memory", "guardrail", "robustness", "sensitivity"],
        default="core",
        help="Experiment set to run. 'core' runs validation, policy, memory, and guardrail at modest cost.",
    )
    parser.add_argument("--preset", choices=["quick", "paper"], default="quick", help="Parameter preset.")
    parser.add_argument("--pop-size", type=int, default=None, help="Override population size.")
    parser.add_argument("--n-days", type=int, default=None, help="Override simulation length.")
    parser.add_argument("--seeds", type=int, default=None, help="Override number of seeds for main experiments.")
    parser.add_argument("--validation-seeds", type=int, default=None, help="Override seeds for validation experiments.")
    parser.add_argument("--scenario", choices=["all", "low", "medium", "high"], default="all", help="Scenario subset.")
    parser.add_argument("--use-api", action="store_true", help="Use the real Qwen-compatible LLM API.")
    parser.add_argument("--model", default=cvlp.DEFAULT_QWEN_MODEL, help=f"LLM model name, default: {cvlp.DEFAULT_QWEN_MODEL}")
    parser.add_argument("--base-url", default=os.getenv("DASHSCOPE_BASE_URL", cvlp.DEFAULT_DASHSCOPE_BASE_URL))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=cvlp.DEFAULT_MAX_TOKENS)
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    parser.add_argument("--skip-if-no-api-key", action="store_true")
    parser.add_argument("--no-plots", action="store_true", help="Skip PNG generation.")
    # Dual-branch memory options
    parser.add_argument(
        "--memory-mode",
        choices=["none", "build_collect", "eval"],
        default="none",
        help="Memory mode: none=standard, build_collect=collect memory without retrieval, eval=use frozen DB with retrieval.",
    )
    parser.add_argument("--memory-build-db", default=None, help="Path for build_collect phase database.")
    parser.add_argument("--memory-eval-db", default=None, help="Path to frozen database for eval phase.")
    parser.add_argument("--memory-build-seeds", type=int, default=5, help="Number of seeds for build_collect phase.")
    return parser.parse_args()


def resolve_config(args: argparse.Namespace) -> dict:
    if args.preset == "paper":
        pop_size = 40000
        n_days = 84
        seeds = 10
        validation_seeds = 30
        scenarios = PAPER_SCENARIOS
    else:
        pop_size = 4000
        n_days = 56
        seeds = 2
        validation_seeds = 3
        scenarios = QUICK_SCENARIOS

    pop_size = int(args.pop_size or pop_size)
    n_days = int(args.n_days or n_days)
    seeds = int(args.seeds or seeds)
    validation_seeds = int(args.validation_seeds or validation_seeds)
    scenario_names = list(scenarios.keys()) if args.scenario == "all" else [args.scenario]

    return {
        "pop_size": pop_size,
        "n_days": n_days,
        "seeds": list(range(1, seeds + 1)),
        "validation_seeds": list(range(1, validation_seeds + 1)),
        "scenarios": scenarios,
        "scenario_names": scenario_names,
    }


def make_common_pars(config: dict, scenario_name: str, seed: int) -> dict:
    scenario = config["scenarios"][scenario_name]
    pop_scale = config["pop_size"] / 40000.0
    initial_infected = int(round(scenario["pop_infected"] * pop_scale))
    pars = dict(
        pop_type="campus",
        pop_size=int(config["pop_size"]),
        pop_infected=max(1, initial_infected),
        n_days=int(config["n_days"]),
        rand_seed=int(seed),
        beta=0.016 * float(scenario["beta_scale"]),
    )
    if scenario.get("beta_layer_scale"):
        base_beta_layer = dict(d=2.0, clu=1.0, clg=1.0, of=0.8, ta=1.2, cm=0.35)
        pars["beta_layer"] = {
            layer: float(value) * float(scenario["beta_layer_scale"].get(layer, 1.0))
            for layer, value in base_beta_layer.items()
        }
    if scenario.get("contacts_scale"):
        base_contacts = dict(d=5, clu=25, clg=12, of=6, ta=3, cm=12)
        pars["contacts"] = {
            layer: max(1, int(round(float(value) * float(scenario["contacts_scale"].get(layer, 1.0)))))
            for layer, value in base_contacts.items()
        }
    return pars


def make_threshold_decision_fn():
    def decision_fn(state, policy_catalog):
        summary = state.get("past_7d_summary", {})
        burden = state.get("intervention_burden_last_7d", {})
        infections = float(summary.get("new_infections_sum", 0.0))
        infections_per_1000 = float(state.get("new_infections_per_1000_last_7d", 0.0))
        growth = float(state.get("growth_ratio_7d_vs_prev_7d", 1.0))
        quarantined = float(burden.get("mean_quarantined_per_1000", 0.0))
        if infections_per_1000 >= 30 or infections >= 1200 or growth >= 1.8:
            policy_id, risk_level = "P4_emergency", "critical"
        elif infections_per_1000 >= 18 or infections >= 700 or growth >= 1.5:
            policy_id, risk_level = "P3_strong", "high"
        elif infections_per_1000 >= 8 or infections >= 300 or growth >= 1.1:
            policy_id, risk_level = "P2_moderate", "medium"
        elif quarantined >= 18:
            policy_id, risk_level = "P1_guarded", "medium"
        else:
            policy_id, risk_level = "P1_guarded", "low"
        return {"policy_id": policy_id, "risk_level": risk_level, "reason": "阈值规则输出"}

    return decision_fn


def make_surrogate_llm_decision_fn(mode: str):
    def decision_fn(state, policy_catalog):
        summary = state.get("past_7d_summary", {})
        effect = state.get("policy_effect_summary", {})
        volatility = state.get("policy_volatility_last_4w", {})
        burden = state.get("intervention_burden_last_7d", {})
        infections = float(summary.get("new_infections_sum", 0.0))
        infections_per_1000 = float(state.get("new_infections_per_1000_last_7d", 0.0))
        growth = float(state.get("growth_ratio_7d_vs_prev_7d", 1.0))
        trend = summary.get("estimated_risk_trend", "stable")
        current_policy = state.get("current_policy") or "P0_normal"
        current_rank = cvlp.get_policy_rank(current_policy, policy_catalog)

        target_rank = current_rank
        if infections_per_1000 >= 8 or infections >= 300 or trend == "worsening" or growth >= 1.1:
            target_rank = max(target_rank, 2)
        if infections_per_1000 >= 18 or infections >= 700 or growth >= 1.5:
            target_rank = max(target_rank, 3)
        if infections_per_1000 >= 30 or infections >= 1200 or growth >= 1.8:
            target_rank = 4
        if infections_per_1000 <= 4 and infections < 160 and summary.get("new_infections_trend") == "down":
            target_rank = min(target_rank, 1)
        if infections_per_1000 <= 2 and infections < 80 and growth <= 1.0:
            target_rank = 0

        if mode != "nomemory":
            if effect.get("dominant_effect_trend") == "improving":
                target_rank = min(target_rank, current_rank)
            if effect.get("dominant_effect_trend") == "worsening":
                target_rank = max(target_rank, min(4, current_rank + 1))
            if float(volatility.get("policy_oscillation_score", 0.0)) >= 2.0:
                target_rank = min(target_rank, max(current_rank, target_rank - 1))
            if float(burden.get("mean_quarantined_per_1000", 0.0)) >= 20.0 and trend != "worsening":
                target_rank = min(target_rank, current_rank)

        target_rank = int(np.clip(target_rank, 0, 4))
        risk_level = ["low", "low", "medium", "high", "critical"][target_rank]
        return {
            "policy_id": cvlp.get_policy_by_rank(target_rank, policy_catalog),
            "risk_level": risk_level,
            "reason": "结合趋势与负担决策",
        }

    return decision_fn


def make_fixed_policy_decision_fn(policy_id: str):
    def decision_fn(state, policy_catalog):
        rank = cvlp.get_policy_rank(policy_id, policy_catalog)
        risk_level = ["low", "low", "medium", "high", "critical"][rank]
        return {"policy_id": policy_id, "risk_level": risk_level, "reason": "固定策略实验"}

    return decision_fn


def make_policy_agent(args: argparse.Namespace, strategy_name: str, outdir: Path | None = None,
                      memory_store=None, global_memory_store=None, enable_memory_context=True):
    log_path = None
    if outdir is not None and strategy_name != "fixed_policy_internal":
        log_path = str(outdir / f"{strategy_name}_decision_log.jsonl")

    common = dict(
        start_day=0,
        decision_interval_days=7,
        initial_policy="P0_normal",
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        defer_first_decision_until_interval=True,
        log_path=log_path,
        label=f"{strategy_name}_agent",
    )

    if strategy_name == "baseline_threshold":
        return cv.campus_policy_agent(
            decision_fn=make_threshold_decision_fn(),
            use_theory_prompt=False,
            memory_weeks=0,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=True,
            **common,
        )
    if strategy_name == "baseline_single_agent_nomemory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("nomemory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=False,
            memory_weeks=0,
            ensemble_size=1,
            min_policy_hold_intervals=0,
            enable_burden_guardrail=False,
            **common,
        )
    if strategy_name == "llm_single_memory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            **common,
        )
    if strategy_name == "llm_ensemble_memory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=3,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            **common,
        )
    if strategy_name == "llm_memory_without_guardrail":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=False,
            **common,
        )
    if strategy_name == "llm_memory_with_guardrail":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            **common,
        )
    # --- 2×2 ablation: expert knowledge × memory ---
    if strategy_name == "ablation_no_expert_no_memory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("nomemory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=False,
            memory_weeks=0,
            ensemble_size=1,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=False,
            **common,
        )
    if strategy_name == "ablation_memory_only":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=False,
            memory_weeks=2,
            ensemble_size=1,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=False,
            **common,
        )
    if strategy_name == "ablation_expert_only":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("nomemory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=0,
            ensemble_size=1,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=False,
            **common,
        )
    if strategy_name == "ablation_expert_and_memory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=2,
            ensemble_size=1,
            min_policy_hold_intervals=1,
            enable_burden_guardrail=False,
            **common,
        )
    # --- Dual-branch memory strategy ---
    if strategy_name == "llm_dual_memory":
        return cv.campus_policy_agent(
            decision_fn=None if args.use_api else make_surrogate_llm_decision_fn("memory"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            use_theory_prompt=True,
            memory_weeks=4,
            ensemble_size=1,
            min_policy_hold_intervals=2,
            enable_burden_guardrail=True,
            memory_store=memory_store,
            global_memory_store=global_memory_store,
            enable_memory_context=enable_memory_context,
            short_term_window=4,
            similar_top_k=6,
            similar_cases_per_group=2,
            trend_context_window=3,
            **common,
        )
    raise ValueError(f"Unsupported strategy: {strategy_name}")


def make_fixed_policy_agent(policy_id: str):
    return cv.campus_policy_agent(
        decision_fn=make_fixed_policy_decision_fn(policy_id),
        decision_interval_days=7,
        initial_policy=policy_id,
        memory_weeks=0,
        ensemble_size=1,
        min_policy_hold_intervals=0,
        enable_burden_guardrail=False,
        defer_first_decision_until_interval=True,
        log_path=None,
        label=f"fixed_{policy_id}_agent",
    )


def run_strategy_once(args: argparse.Namespace, config: dict, scenario_name: str, strategy_name: str,
                      seed: int, outdir: Path,
                      memory_store=None, global_memory_store=None, enable_memory_context=True) -> cv.Sim:
    pars = make_common_pars(config, scenario_name, seed)
    if strategy_name == "baseline_no_policy":
        sim = cv.Sim(pars=pars, label=strategy_name)
    elif strategy_name.startswith("fixed_"):
        policy_id = strategy_name.removeprefix("fixed_")
        sim = cv.Sim(pars=pars, interventions=[make_fixed_policy_agent(policy_id)], label=strategy_name)
    else:
        agent = make_policy_agent(args, strategy_name, outdir,
                                  memory_store=memory_store,
                                  global_memory_store=global_memory_store,
                                  enable_memory_context=enable_memory_context)
        sim = cv.Sim(pars=pars, interventions=[agent], label=strategy_name)
    sim.run()
    return sim


def result_values(sim: cv.Sim, key: str) -> np.ndarray:
    result = sim.results.get(key, None)
    if result is None:
        return np.array([], dtype=float)
    return np.asarray(getattr(result, "values", result), dtype=float)


def compute_doubling_time(sim: cv.Sim, lower: float = 20.0, upper: float = 2000.0) -> dict:
    cum = result_values(sim, "cum_infections")
    days = np.arange(len(cum), dtype=float)
    mask = (cum >= lower) & (cum <= upper)
    if int(mask.sum()) < 3:
        return {"doubling_time": np.nan, "growth_rate": np.nan, "fit_days": int(mask.sum()), "fit_start_day": np.nan, "fit_end_day": np.nan}
    x = days[mask]
    y = np.log(np.maximum(cum[mask], 1.0))
    slope, intercept = np.polyfit(x, y, 1)
    doubling_time = math.log(2.0) / slope if slope > 0 else np.nan
    return {
        "doubling_time": float(doubling_time),
        "growth_rate": float(slope),
        "fit_intercept": float(intercept),
        "fit_days": int(len(x)),
        "fit_start_day": int(x[0]),
        "fit_end_day": int(x[-1]),
    }


def count_layer_transmissions(sim: cv.Sim, start_day: int = 0, end_day: int | None = None) -> dict:
    end_day = sim.npts - 1 if end_day is None else int(end_day)
    counts = {layer: 0 for layer in CAMPUS_LAYERS}
    infection_log = getattr(getattr(sim, "people", None), "infection_log", [])
    if not isinstance(infection_log, list):
        return counts
    for entry in infection_log:
        day = int(entry.get("date", -1))
        layer = entry.get("layer")
        if start_day <= day <= end_day and layer in counts:
            counts[layer] += 1
    return counts


def summarize_layer_contributions(sim: cv.Sim, scenario_name: str, strategy_name: str, seed: int) -> list[dict]:
    raw_counts = count_layer_transmissions(sim)
    total = float(sum(raw_counts.values()))
    rows = []
    for layer, count in raw_counts.items():
        rows.append(
            {
                "scenario": scenario_name,
                "strategy": strategy_name,
                "seed": int(seed),
                "layer_group": layer,
                "transmissions": int(count),
                "share": float(count / total) if total > 0 else 0.0,
            }
        )
    for group_name, layers in LAYER_GROUPS.items():
        count = int(sum(raw_counts.get(layer, 0) for layer in layers))
        rows.append(
            {
                "scenario": scenario_name,
                "strategy": strategy_name,
                "seed": int(seed),
                "layer_group": group_name,
                "transmissions": count,
                "share": float(count / total) if total > 0 else 0.0,
            }
        )
    return rows


def build_daily_metrics(sim: cv.Sim, scenario_name: str, strategy_name: str, seed: int) -> pd.DataFrame:
    days = np.arange(sim.npts)
    df = pd.DataFrame(
        {
            "scenario": scenario_name,
            "strategy": strategy_name,
            "seed": int(seed),
            "day": days,
            "date": [sim.date(int(day)) for day in days],
            "cum_infections": result_values(sim, "cum_infections"),
            "new_infections": result_values(sim, "new_infections"),
            "cum_diagnoses": result_values(sim, "cum_diagnoses"),
            "new_diagnoses": result_values(sim, "new_diagnoses"),
            "cum_tests": result_values(sim, "cum_tests"),
            "new_tests": result_values(sim, "new_tests"),
            "n_quarantined": result_values(sim, "n_quarantined"),
            "r_eff": result_values(sim, "r_eff"),
        }
    )
    df["new_infections_7d_avg"] = df["new_infections"].rolling(window=7, min_periods=1).mean()
    return df


def build_policy_trace_df(sim: cv.Sim, scenario_name: str, strategy_name: str, seed: int) -> pd.DataFrame:
    agent = sim["interventions"][0] if sim["interventions"] else None
    if agent is None or not getattr(agent, "policy_trace", None):
        return pd.DataFrame(
            {
                "scenario": [scenario_name] * sim.npts,
                "strategy": [strategy_name] * sim.npts,
                "seed": [int(seed)] * sim.npts,
                "day": list(range(sim.npts)),
                "date": [sim.date(day) for day in range(sim.npts)],
                "policy_id": ["none"] * sim.npts,
                "policy_rank": [-1] * sim.npts,
                "restriction_intensity": [0] * sim.npts,
                "online_teaching_active": [False] * sim.npts,
            }
        )

    rows = []
    for row in agent.policy_trace:
        policy_id = row.get("policy_id", "none")
        rows.append(
            {
                "scenario": scenario_name,
                "strategy": strategy_name,
                "seed": int(seed),
                "day": int(row.get("day", 0)),
                "date": row.get("date"),
                "policy_id": policy_id,
                "policy_rank": cvlp.get_policy_rank(policy_id, agent.policy_catalog) if policy_id in agent.policy_catalog else -1,
                "restriction_intensity": int(row.get("restriction_intensity", 0)),
                "online_teaching_active": bool(row.get("online_teaching_active", False)),
            }
        )
    return pd.DataFrame(rows)


def build_decision_summary_df(sim: cv.Sim, scenario_name: str, strategy_name: str, seed: int) -> pd.DataFrame:
    agent = sim["interventions"][0] if sim["interventions"] else None
    rows = []
    if agent is None:
        return pd.DataFrame(rows)
    for record in getattr(agent, "decision_history", []):
        state = record.get("state_snapshot", {}) if isinstance(record.get("state_snapshot"), dict) else {}
        summary = state.get("past_7d_summary", {}) if isinstance(state.get("past_7d_summary"), dict) else {}
        rows.append(
            {
                "scenario": scenario_name,
                "strategy": strategy_name,
                "seed": int(seed),
                "decision_day": record.get("decision_day"),
                "decision_date": record.get("decision_date"),
                "current_policy_before": record.get("current_policy_before"),
                "model_policy_proposed": record.get("model_policy_proposed"),
                "applied_policy": record.get("applied_policy"),
                "risk_level": record.get("risk_level"),
                "reason": record.get("reason"),
                "fallback_used": bool(record.get("fallback_used")),
                "guardrail_adjusted": bool(record.get("guardrail_adjusted")),
                "guardrail_reason": record.get("guardrail_reason"),
                "new_infections_sum": float(summary.get("new_infections_sum", 0.0)),
                "new_infections_per_1000_last_7d": float(state.get("new_infections_per_1000_last_7d", 0.0)),
                "growth_ratio_7d_vs_prev_7d": float(state.get("growth_ratio_7d_vs_prev_7d", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def summarize_final_metrics(sim: cv.Sim, scenario_name: str, strategy_name: str, seed: int) -> dict:
    trace_df = build_policy_trace_df(sim, scenario_name, strategy_name, seed)
    decision_df = build_decision_summary_df(sim, scenario_name, strategy_name, seed)
    policy_ids = list(trace_df["policy_id"]) if len(trace_df) else []
    policy_ids_for_score = [pid for pid in policy_ids if pid in cvlp.POLICY_IDS]
    new_infections = result_values(sim, "new_infections")
    n_quarantined = result_values(sim, "n_quarantined")
    r_eff = result_values(sim, "r_eff")
    peak_new = float(np.max(new_infections)) if len(new_infections) else 0.0
    time_to_peak = int(np.argmax(new_infections)) if len(new_infections) else -1
    switch_count = sum(int(policy_ids[idx] != policy_ids[idx - 1]) for idx in range(1, len(policy_ids)) if policy_ids[idx] != "none")
    return {
        "scenario": scenario_name,
        "strategy": strategy_name,
        "seed": int(seed),
        "cum_infections": float(sim.results["cum_infections"][-1]),
        "cum_diagnoses": float(sim.results["cum_diagnoses"][-1]),
        "peak_new_infections": peak_new,
        "r_eff_final": float(r_eff[-1]) if len(r_eff) else 0.0,
        "time_to_peak": time_to_peak,
        "cum_tests": float(sim.results["cum_tests"][-1]),
        "mean_quarantined": float(np.mean(n_quarantined)) if len(n_quarantined) else 0.0,
        "peak_quarantined": float(np.max(n_quarantined)) if len(n_quarantined) else 0.0,
        "teaching_restriction_days": int(trace_df["online_teaching_active"].sum()) if len(trace_df) else 0,
        "restriction_intensity_days": float(trace_df["restriction_intensity"].sum()) if len(trace_df) else 0.0,
        "policy_switch_count": float(switch_count),
        "policy_oscillation_score": cvlp.compute_policy_oscillation_score(policy_ids_for_score),
        "decision_count": float(len(decision_df)),
        "guardrail_adjusted_count": float(decision_df["guardrail_adjusted"].sum()) if len(decision_df) else 0.0,
        "low_prevalence_online_guardrail_block_count": float(
            (decision_df.get("guardrail_reason", pd.Series(dtype=str)) == "low_prevalence_online_guardrail_block").sum()
        )
        if len(decision_df)
        else 0.0,
        "P3_P4_days": int(trace_df["policy_id"].isin(["P3_strong", "P4_emergency"]).sum()) if len(trace_df) else 0,
    }


def aggregate_runs(run_df: pd.DataFrame) -> pd.DataFrame:
    if run_df.empty:
        return run_df.copy()
    metric_cols = [col for col in run_df.columns if col not in {"scenario", "strategy", "seed"}]
    rows = []
    for (scenario, strategy), group in run_df.groupby(["scenario", "strategy"], sort=False):
        row = {"scenario": scenario, "strategy": strategy, "n_runs": int(len(group))}
        for col in metric_cols:
            row[f"{col}_mean"] = float(group[col].mean())
            row[f"{col}_var"] = float(group[col].var(ddof=0))
        rows.append(row)
    aggregate = pd.DataFrame(rows).sort_values(["scenario", "strategy"]).reset_index(drop=True)
    if "baseline_no_policy" in set(run_df["strategy"]):
        return cvlp.add_balanced_utility_metrics(aggregate)
    return aggregate


def run_runs(
    args: argparse.Namespace,
    config: dict,
    scenario_names: list[str],
    strategies: list[str],
    seeds: list[int],
    outdir: Path,
    label: str,
    memory_store=None,
    global_memory_store=None,
    enable_memory_context=True,
    embedding_provider=None,
) -> dict:
    rows = []
    daily_frames = []
    trace_frames = []
    decision_frames = []
    layer_rows = []
    total = len(scenario_names) * len(strategies) * len(seeds)
    completed = 0
    for scenario_name in scenario_names:
        for strategy_name in strategies:
            for seed in seeds:
                completed += 1
                print(f"[{label}] {completed}/{total}: {scenario_name} / {strategy_name} / seed {seed}")

                # For eval mode, create per-seed episode store
                episode_store = None
                actual_memory_store = memory_store
                if global_memory_store is not None and strategy_name == "llm_dual_memory":
                    # Eval mode: create in-memory episode store per seed
                    episode_store = cvlm.MemoryStore(
                        db_path=":memory:", read_only=False,
                        embedding_provider=embedding_provider)
                    actual_memory_store = episode_store

                sim = run_strategy_once(
                    args, config, scenario_name, strategy_name, seed, outdir,
                    memory_store=actual_memory_store,
                    global_memory_store=global_memory_store,
                    enable_memory_context=enable_memory_context,
                )

                # Close episode store after run
                if episode_store is not None:
                    episode_store.close()

                rows.append(summarize_final_metrics(sim, scenario_name, strategy_name, seed))
                daily_frames.append(build_daily_metrics(sim, scenario_name, strategy_name, seed))
                trace_frames.append(build_policy_trace_df(sim, scenario_name, strategy_name, seed))
                decision = build_decision_summary_df(sim, scenario_name, strategy_name, seed)
                if len(decision):
                    decision_frames.append(decision)
                layer_rows.extend(summarize_layer_contributions(sim, scenario_name, strategy_name, seed))

    run_df = pd.DataFrame(rows)
    return {
        "run": run_df,
        "aggregate": aggregate_runs(run_df),
        "daily": pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(),
        "trace": pd.concat(trace_frames, ignore_index=True) if trace_frames else pd.DataFrame(),
        "decision": pd.concat(decision_frames, ignore_index=True) if decision_frames else pd.DataFrame(),
        "layers": pd.DataFrame(layer_rows),
    }


def run_model_validation(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    validation_seed_count = min(len(config["validation_seeds"]), 10 if args.preset == "quick" else len(config["validation_seeds"]))
    validation_seeds = config["validation_seeds"][:validation_seed_count]
    medium = ["medium"]

    doubling_rows = []
    daily_frames = []
    print(f"[validation] Doubling-time runs: {len(validation_seeds)} seed(s)")
    for seed in validation_seeds:
        sim = run_strategy_once(args, config, "medium", "baseline_no_policy", seed, outdir)
        row = {"scenario": "medium", "strategy": "baseline_no_policy", "seed": int(seed)}
        row.update(compute_doubling_time(sim))
        doubling_rows.append(row)
        daily_frames.append(build_daily_metrics(sim, "medium", "baseline_no_policy", seed))

    fixed_strategies = [f"fixed_{policy_id}" for policy_id in FIXED_POLICIES]
    fixed = run_runs(
        args=args,
        config=config,
        scenario_names=medium,
        strategies=fixed_strategies,
        seeds=config["seeds"],
        outdir=outdir,
        label="fixed-policy",
    )

    layer_check = run_runs(
        args=args,
        config=config,
        scenario_names=medium,
        strategies=["baseline_no_policy", "llm_single_memory"],
        seeds=config["seeds"][: min(3, len(config["seeds"]))],
        outdir=outdir,
        label="layer-check",
    )

    return {
        "doubling": pd.DataFrame(doubling_rows),
        "doubling_daily": pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(),
        "fixed": fixed,
        "layer_check": layer_check,
    }


def run_policy_comparison(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    return run_runs(args, config, config["scenario_names"], CORE_STRATEGIES, config["seeds"], outdir, "policy")


def run_memory_ablation(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    scenario_names = [name for name in ["medium", "high"] if name in config["scenario_names"] or args.scenario == "all"]
    seeds = config["seeds"][: min(5, len(config["seeds"]))]
    strategies = ["baseline_no_policy"] + ABLATION_STRATEGIES

    memory_mode = getattr(args, "memory_mode", "none")

    # Dual-branch memory two-phase workflow
    if memory_mode == "build_collect":
        return _run_memory_build_collect(args, config, scenario_names, seeds, outdir)
    elif memory_mode == "eval":
        return _run_memory_eval(args, config, scenario_names, seeds, outdir)

    # Standard ablation without memory stores (original behavior)
    # Remove llm_dual_memory from strategies when not in memory mode
    strategies = [s for s in strategies if s != "llm_dual_memory"]
    return run_runs(
        args,
        config,
        scenario_names,
        strategies,
        seeds,
        outdir,
        "memory_ablation",
    )


def _run_memory_build_collect(args, config, scenario_names, seeds, outdir):
    """Phase 1: Collect memory entries without retrieval (LLM acts as expert_only)."""
    build_db_path = args.memory_build_db or str(outdir / "memory_build.db")
    print(f"[memory_build_collect] Building memory database: {build_db_path}")

    embedding_provider = cvlm.EmbeddingProvider()
    build_store = cvlm.MemoryStore(db_path=build_db_path, read_only=False,
                                    embedding_provider=embedding_provider)

    # Only run llm_dual_memory in build_collect mode
    strategies = ["llm_dual_memory"]
    result = run_runs(
        args, config, scenario_names, strategies, seeds, outdir,
        label="memory_build_collect",
        memory_store=build_store,
        global_memory_store=None,
        enable_memory_context=False,
        embedding_provider=embedding_provider,
    )

    build_store.close()
    print(f"[memory_build_collect] Database saved: {build_db_path}")
    return result


def _run_memory_eval(args, config, scenario_names, seeds, outdir):
    """Phase 2: Use frozen database with full dual-branch retrieval."""
    frozen_db_path = args.memory_eval_db or str(outdir / "memory_build.db")
    if not Path(frozen_db_path).exists():
        raise FileNotFoundError(
            f"Frozen memory database not found: {frozen_db_path}. "
            "Run with --memory-mode build_collect first."
        )
    print(f"[memory_eval] Using frozen memory database: {frozen_db_path}")

    embedding_provider = cvlm.EmbeddingProvider()
    global_store = cvlm.MemoryStore(db_path=frozen_db_path, read_only=True,
                                     embedding_provider=embedding_provider)

    # Run llm_dual_memory in eval mode with full retrieval
    strategies = ["baseline_no_policy", "ablation_expert_only", "llm_dual_memory"]
    result = run_runs(
        args, config, scenario_names, strategies, seeds, outdir,
        label="memory_eval",
        memory_store=None,  # Will be replaced by per-seed episode store
        global_memory_store=global_store,
        enable_memory_context=True,
        embedding_provider=embedding_provider,
    )

    global_store.close()
    return result


def run_guardrail_ablation(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    scenario_names = [name for name in ["low", "medium"] if name in config["scenario_names"] or args.scenario == "all"]
    return run_runs(
        args,
        config,
        scenario_names,
        ["llm_memory_without_guardrail", "llm_memory_with_guardrail"],
        config["seeds"],
        outdir,
        "guardrail",
    )


def run_robustness(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    return run_runs(args, config, list(PAPER_SCENARIOS.keys()), CORE_STRATEGIES, config["seeds"], outdir, "robustness")


def make_sensitivity_config(config: dict) -> dict:
    sensitivity_config = dict(config)
    scenarios = dict(config["scenarios"])
    for variant_name, variant in SENSITIVITY_VARIANTS.items():
        base = dict(config["scenarios"][variant["base_scenario"]])
        base.update({key: value for key, value in variant.items() if key != "base_scenario"})
        scenarios[variant_name] = base
    sensitivity_config["scenarios"] = scenarios
    sensitivity_config["scenario_names"] = list(SENSITIVITY_VARIANTS.keys())
    return sensitivity_config


def sensitivity_design_df() -> pd.DataFrame:
    rows = []
    for variant_name, variant in SENSITIVITY_VARIANTS.items():
        row = {
            "sensitivity_variant": variant_name,
            "base_scenario": variant["base_scenario"],
            "description": variant["description"],
            "beta_layer_scale": json.dumps(variant.get("beta_layer_scale", {}), ensure_ascii=False),
            "contacts_scale": json.dumps(variant.get("contacts_scale", {}), ensure_ascii=False),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def run_sensitivity_analysis(args: argparse.Namespace, config: dict, outdir: Path) -> dict:
    sensitivity_config = make_sensitivity_config(config)
    seeds = config["seeds"][: min(5, len(config["seeds"]))]
    bundle = run_runs(args, sensitivity_config, sensitivity_config["scenario_names"], CORE_STRATEGIES, seeds, outdir, "sensitivity")
    bundle["design"] = sensitivity_design_df()
    return bundle


def save_tables(results: dict, outdir: Path) -> dict:
    paths = {}

    def save_df(name: str, df: pd.DataFrame):
        if df is None or df.empty:
            return
        path = outdir / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        paths[name] = str(path)

    validation = results.get("validation", {})
    if validation:
        save_df("model_validation_doubling_time", validation.get("doubling"))
        fixed = validation.get("fixed", {})
        save_df("model_validation_fixed_policy_runs", fixed.get("run"))
        save_df("model_validation_fixed_policy_summary", fixed.get("aggregate"))
        layer_check = validation.get("layer_check", {})
        save_df("model_validation_layer_contributions", layer_check.get("layers"))
        save_df("model_validation_layer_runs", layer_check.get("run"))

    for key in ["policy", "memory", "guardrail", "robustness", "sensitivity"]:
        bundle = results.get(key)
        if not bundle:
            continue
        save_df(f"{key}_run_metrics", bundle.get("run"))
        save_df(f"{key}_summary_metrics", bundle.get("aggregate"))
        save_df(f"{key}_daily_metrics", bundle.get("daily"))
        save_df(f"{key}_policy_trace", bundle.get("trace"))
        save_df(f"{key}_decision_summary", bundle.get("decision"))
        save_df(f"{key}_layer_contributions", bundle.get("layers"))
        save_df(f"{key}_design", bundle.get("design"))

    summary_json = outdir / "experiment_manifest.json"
    summary_json.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["manifest"] = str(summary_json)
    return paths


def _color_for(strategy: str) -> str:
    return STRATEGY_COLORS.get(strategy, "#666666")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in df.itertuples(index=False, name=None):
        formatted = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                formatted.append(f"{float(value):.2f}")
            elif pd.isna(value):
                formatted.append("")
            else:
                formatted.append(str(value))
        lines.append("| " + " | ".join(formatted) + " |")
    return "\n".join(lines)


def plot_policy_bundle(bundle: dict, outdir: Path, name: str, scenario_name: str = "medium") -> list[Path]:
    paths = []
    daily = bundle.get("daily", pd.DataFrame())
    trace = bundle.get("trace", pd.DataFrame())
    aggregate = bundle.get("aggregate", pd.DataFrame())
    if daily.empty:
        return paths

    daily_plot = daily[daily["scenario"] == scenario_name].copy()
    if daily_plot.empty:
        daily_plot = daily.copy()
        scenario_name = str(daily_plot["scenario"].iloc[0])
    daily_mean = (
        daily_plot.groupby(["strategy", "day"], as_index=False)
        .agg(cum_infections=("cum_infections", "mean"), new_infections_7d_avg=("new_infections_7d_avg", "mean"))
        .reset_index(drop=True)
    )

    fig = pl.figure(figsize=(13, 8))
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)
    for strategy_name, group in daily_mean.groupby("strategy", sort=False):
        ax1.plot(group["day"], group["cum_infections"], label=strategy_name, color=_color_for(strategy_name), lw=2.2)
        ax2.plot(group["day"], group["new_infections_7d_avg"], label=strategy_name, color=_color_for(strategy_name), lw=2.0)
    ax1.set_title(f"{name}: cumulative infections ({scenario_name})")
    ax1.set_xlabel("Day")
    ax1.set_ylabel("Cumulative infections")
    ax1.grid(alpha=0.3)
    ax2.set_title("7-day average new infections")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("New infections/day")
    ax2.grid(alpha=0.3)
    ax1.legend(frameon=False)
    fig.tight_layout()
    path = outdir / f"{name}_infection_curves.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    pl.close(fig)
    paths.append(path)

    if not trace.empty:
        trace_plot = trace[trace["scenario"] == scenario_name].copy()
        trace_mean = trace_plot.groupby(["strategy", "day"], as_index=False).agg(policy_rank=("policy_rank", "mean"))
        fig = pl.figure(figsize=(13, 4.8))
        ax = fig.add_subplot(1, 1, 1)
        for strategy_name, group in trace_mean.groupby("strategy", sort=False):
            ax.step(group["day"], group["policy_rank"], where="post", label=strategy_name, color=_color_for(strategy_name), lw=2.2)
        ax.set_title(f"{name}: policy trajectory ({scenario_name})")
        ax.set_xlabel("Day")
        ax.set_ylabel("Policy rank")
        ax.set_yticks([-1, 0, 1, 2, 3, 4])
        ax.set_yticklabels(["none", "P0", "P1", "P2", "P3", "P4"])
        ax.grid(alpha=0.3)
        ax.legend(frameon=False)
        fig.tight_layout()
        path = outdir / f"{name}_policy_trace.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        pl.close(fig)
        paths.append(path)

    if not aggregate.empty:
        agg_plot = aggregate[aggregate["scenario"] == scenario_name].copy()
        if agg_plot.empty:
            agg_plot = aggregate.copy()
        metrics = [
            ("cum_infections_mean", "Cumulative infections"),
            ("cum_tests_mean", "Tests"),
            ("mean_quarantined_mean", "Mean quarantined"),
            ("teaching_restriction_days_mean", "Online teaching days"),
        ]
        fig = pl.figure(figsize=(14, 9))
        for idx, (col, title) in enumerate(metrics, start=1):
            ax = fig.add_subplot(2, 2, idx)
            ax.bar(agg_plot["strategy"], agg_plot[col], color=[_color_for(s) for s in agg_plot["strategy"]])
            ax.set_title(title)
            ax.tick_params(axis="x", rotation=18)
            ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        path = outdir / f"{name}_summary_bars.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        pl.close(fig)
        paths.append(path)

    return paths


def save_plots(results: dict, outdir: Path) -> list[Path]:
    paths = []
    for key in ["policy", "memory", "guardrail", "robustness"]:
        bundle = results.get(key)
        if bundle:
            paths.extend(plot_policy_bundle(bundle, outdir, key, scenario_name="medium"))
    sensitivity = results.get("sensitivity", {})
    if sensitivity:
        paths.extend(plot_policy_bundle(sensitivity, outdir, "sensitivity", scenario_name="medium_base"))

    validation = results.get("validation", {})
    fixed = validation.get("fixed", {}) if validation else {}
    if fixed:
        paths.extend(plot_policy_bundle(fixed, outdir, "model_validation_fixed_policy", scenario_name="medium"))
    return paths


def build_markdown_report(results: dict, config: dict, args: argparse.Namespace, artifact_paths: dict, plot_paths: list[Path]) -> str:
    lines = [
        "# Campus LLM Thesis Experiments",
        "",
        "## Setup",
        "",
        f"- Preset: `{args.preset}`",
        f"- Population: `{config['pop_size']}`",
        f"- Days: `{config['n_days']}`",
        f"- Seeds: `{len(config['seeds'])}` main, `{len(config['validation_seeds'])}` validation",
        f"- Scenarios: `{', '.join(config['scenario_names'])}`",
        f"- API mode: `{args.use_api}`",
        "",
    ]

    validation = results.get("validation", {})
    doubling = validation.get("doubling", pd.DataFrame()) if validation else pd.DataFrame()
    if not doubling.empty:
        valid = doubling["doubling_time"].dropna()
        if len(valid):
            lines.extend(
                [
                    "## Model Validation",
                    "",
                    f"- No-policy early doubling time: mean `{valid.mean():.2f}` days, std `{valid.std(ddof=0):.2f}` days.",
                ]
            )

    policy = results.get("policy", {})
    aggregate = policy.get("aggregate", pd.DataFrame()) if policy else pd.DataFrame()
    if not aggregate.empty:
        medium = aggregate[aggregate["scenario"] == "medium"].copy()
        if not medium.empty and "CPBU" in medium:
            best = medium.sort_values("CPBU", ascending=False).iloc[0]
            lines.extend(
                [
                    "## Policy Comparison",
                    "",
                    f"- Best medium-scenario balance score: `{best['strategy']}` with CPBU `{best['CPBU']:.3f}`.",
                ]
            )

    guardrail = results.get("guardrail", {})
    guard_df = guardrail.get("run", pd.DataFrame()) if guardrail else pd.DataFrame()
    if not guard_df.empty:
        guard_summary = (
            guard_df.groupby("strategy", as_index=False)
            .agg(
                low_prevalence_online_guardrail_block_count=("low_prevalence_online_guardrail_block_count", "mean"),
                guardrail_adjusted_count=("guardrail_adjusted_count", "mean"),
                cum_infections=("cum_infections", "mean"),
            )
            .sort_values("strategy")
        )
        lines.extend(["", "## Guardrail Summary", "", markdown_table(guard_summary)])

    sensitivity = results.get("sensitivity", {})
    sensitivity_agg = sensitivity.get("aggregate", pd.DataFrame()) if sensitivity else pd.DataFrame()
    if not sensitivity_agg.empty:
        llm_rows = sensitivity_agg[sensitivity_agg["strategy"] == "llm_single_memory"].copy()
        threshold_rows = sensitivity_agg[sensitivity_agg["strategy"] == "baseline_threshold"].copy()
        no_policy_rows = sensitivity_agg[sensitivity_agg["strategy"] == "baseline_no_policy"].copy()
        lines.extend(["", "## Sensitivity Analysis", ""])
        if not llm_rows.empty:
            lines.append(
                "- LLM memory policy cumulative infections across sensitivity variants: "
                f"min `{llm_rows['cum_infections_mean'].min():.2f}`, "
                f"max `{llm_rows['cum_infections_mean'].max():.2f}`."
            )
        if not no_policy_rows.empty and not threshold_rows.empty and not llm_rows.empty:
            compare = (
                no_policy_rows[["scenario", "cum_infections_mean"]]
                .rename(columns={"cum_infections_mean": "no_policy_infections"})
                .merge(
                    threshold_rows[["scenario", "cum_infections_mean"]].rename(
                        columns={"cum_infections_mean": "threshold_infections"}
                    ),
                    on="scenario",
                    how="inner",
                )
                .merge(
                    llm_rows[["scenario", "cum_infections_mean"]].rename(columns={"cum_infections_mean": "llm_infections"}),
                    on="scenario",
                    how="inner",
                )
            )
            if not compare.empty:
                compare["llm_avoided_vs_no_policy"] = compare["no_policy_infections"] - compare["llm_infections"]
                compare["threshold_avoided_vs_no_policy"] = compare["no_policy_infections"] - compare["threshold_infections"]
                lines.append(
                    "- In all matched variants, the sensitivity table reports infections avoided versus no policy; "
                    "use `sensitivity_summary_metrics.csv` for thesis tables."
                )

    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(artifact_paths.items()):
        lines.append(f"- `{name}`: `{path}`")
    if plot_paths:
        lines.extend(["", "## Figures", ""])
        for path in plot_paths:
            lines.append(f"- `{path.name}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    config = resolve_config(args)
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    requested_strategies = set()
    if args.experiment in {"all", "core", "policy", "robustness", "sensitivity"}:
        requested_strategies.update(CORE_STRATEGIES)
    if args.experiment in {"all", "core", "memory"}:
        requested_strategies.update(ABLATION_STRATEGIES)
    if args.experiment in {"all", "core", "guardrail"}:
        requested_strategies.update(["llm_memory_without_guardrail", "llm_memory_with_guardrail"])
    if args.use_api and requested_strategies & API_STRATEGIES and not os.getenv("DASHSCOPE_API_KEY"):
        message = "SKIP: DASHSCOPE_API_KEY is not set, so real LLM strategies cannot run."
        print(message)
        return 0 if args.skip_if_no_api_key else 1

    print("=== Campus LLM Thesis Experiments ===")
    print(f"Experiment: {args.experiment}")
    print(f"Preset: {args.preset}")
    print(f"Population: {config['pop_size']}")
    print(f"Days: {config['n_days']}")
    print(f"Scenarios: {config['scenario_names']}")
    print(f"Main seeds: {config['seeds']}")
    print(f"Output: {outdir}")
    print(f"API mode: {args.use_api}")

    results = {}
    if args.experiment in {"all", "core", "validation"}:
        results["validation"] = run_model_validation(args, config, outdir)
    if args.experiment in {"all", "core", "policy"}:
        results["policy"] = run_policy_comparison(args, config, outdir)
    if args.experiment in {"all", "core", "memory"}:
        results["memory"] = run_memory_ablation(args, config, outdir)
    if args.experiment in {"all", "core", "guardrail"}:
        results["guardrail"] = run_guardrail_ablation(args, config, outdir)
    if args.experiment in {"all", "robustness"}:
        results["robustness"] = run_robustness(args, config, outdir)
    if args.experiment in {"all", "sensitivity"}:
        results["sensitivity"] = run_sensitivity_analysis(args, config, outdir)

    artifact_paths = save_tables(results, outdir)
    plot_paths = [] if args.no_plots else save_plots(results, outdir)
    report_text = build_markdown_report(results, config, args, artifact_paths, plot_paths)
    report_path = outdir / "summary_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    print("\n=== Saved artifacts ===")
    print(report_path)
    for path in artifact_paths.values():
        print(path)
    for path in plot_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

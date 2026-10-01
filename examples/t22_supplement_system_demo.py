
"""
CEMAS supplementary-video demo.

This script is intentionally deterministic and offline.  It exercises the real
campus population, six-layer contact network, policy-state extraction, recent
and compressed memory, policy validation, and runtime
interventions.  Only the external LLM call is replaced by a deterministic
replay provider so a paper demo can be recorded without network or API risk.

Run:
    python examples/t22_supplement_system_demo.py
    python examples/t22_supplement_system_demo.py --no-show
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import textwrap
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

if "--no-show" in sys.argv:
    os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("COVASIM_VERBOSE", "0")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch

import covasim as cv
import covasim.llm_memory as cvlm
import covasim.llm_policy as cvlp


LONG_TERM_MEMORY_DB = Path(r"E:\tempt\data\memory_build.db")
LONG_TERM_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

LAYER_INFO = {
    "d": ("Dormitory", "#4C78A8"),
    "clu": ("UG classroom", "#59A14F"),
    "clg": ("Graduate classroom", "#8CD17D"),
    "of": ("Office / laboratory", "#F28E2B"),
    "ta": ("Teaching / admin", "#E15759"),
    "cm": ("Campus common space", "#B07AA1"),
}

POLICY_INFO = {
    "P0_normal": ("P0 Normal", 0, "#59A14F"),
    "P1_guarded": ("P1 Guarded", 1, "#EDC948"),
    "P2_moderate": ("P2 Moderate", 2, "#F28E2B"),
    "P3_strong": ("P3 Strong", 3, "#E15759"),
    "P4_emergency": ("P4 Emergency", 4, "#B07AA1"),
}

ROLE_INFO = {
    "undergraduate": "#4E79A7",
    "graduate": "#76B7B2",
    "teacher": "#E15759",
    "staff": "#F28E2B",
}


def configure_console() -> None:
    """Keep Unicode stage messages readable in a Windows recording terminal."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def configure_plot_style() -> None:
    """Use a clean, publication-friendly plotting style."""
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "Microsoft YaHei"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.grid": True,
            "grid.alpha": 0.18,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def section(title: str) -> None:
    print(f"\n{'=' * 76}\n  {title}\n{'=' * 76}")


def compact_text(value: object, width: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return textwrap.shorten(text, width=width, placeholder=" ...")


def build_english_memory_summary(state: dict, memory: dict) -> dict:
    """Translate both memory branches into an English-only public summary."""
    recent = state.get("recent_policy_memory", [])
    policy_path = [
        str(item.get("executed_policy", "unknown")) for item in recent
    ]
    effect = state.get("policy_effect_summary", {})
    compressed = state.get("short_term_trajectory", {})
    compressed_trend = compressed.get("epidemic_trend", {}).get(
        "label", "not available"
    )
    compressed_trend = str(compressed_trend).replace("_", " ")
    observed_effect = str(
        effect.get("dominant_effect_trend", "not available")
    ).replace("_", " ")
    if policy_path:
        summary_text = (
            f"Recent policy path: {' -> '.join(policy_path)}; "
            f"observed effect: {observed_effect}; "
            f"compressed epidemic trend: {compressed_trend}."
        )
    else:
        summary_text = "No earlier completed decision period is available."

    similar = state.get("similar_scenarios", {})
    policy_groups = similar.get("policy_groups", {})
    long_cases = []
    for policy_id, cases in policy_groups.items():
        for case in cases:
            feedback = case.get("execution_feedback", {})
            long_cases.append(
                {
                    "entry_id": int(case.get("entry_id", -1)),
                    "policy_id": str(case.get("policy_executed", policy_id)),
                    "similarity": float(case.get("similarity", 0.0)),
                    "risk_level": str(case.get("risk_level", "unknown")),
                    "dominant_layer": str(case.get("dominant_layer", "unknown")),
                    "infection_trend_at_time": str(
                        case.get("infection_trend_at_time", "flat")
                    ),
                    "post_policy_trend": str(
                        feedback.get("infection_trend", "unknown")
                    ),
                }
            )
    long_cases.sort(key=lambda item: item["similarity"], reverse=True)
    top_cases = long_cases[:2]
    retrieved_count = int(
        similar.get(
            "retrieved_count",
            memory.get("long_term_retrieved_count", len(long_cases)),
        )
    )
    if top_cases:
        top = top_cases[0]
        post_policy_trend = {
            "up": "upward",
            "down": "downward",
            "flat": "flat",
        }.get(top["post_policy_trend"], top["post_policy_trend"])
        long_summary_text = (
            f"Retrieved {retrieved_count} historical cases; top match "
            f"{top['policy_id']} at {top['similarity']:.2f} similarity, "
            f"with {top['dominant_layer']} as the dominant layer; its "
            f"post-policy trend was {post_policy_trend}."
        )
    else:
        long_summary_text = "No comparable historical cases were retrieved."

    return {
        "memory_mode": str(memory.get("memory_mode", "none")),
        "short_term_enabled": bool(memory.get("short_term_memory_enabled", False)),
        "long_term_enabled": bool(memory.get("long_term_memory_enabled", False)),
        "recent_policy_records": int(len(recent)),
        "compressed_periods": int(memory.get("short_term_entry_count", 0)),
        "policy_path": policy_path,
        "observed_effect": observed_effect,
        "compressed_epidemic_trend": compressed_trend,
        "short_term_summary_text": summary_text,
        "long_term_retrieved_count": retrieved_count,
        "long_term_entry_ids": [
            int(value) for value in similar.get(
                "entry_ids", memory.get("long_term_entry_ids", [])
            )
        ],
        "top_historical_cases": top_cases,
        "long_term_summary_text": long_summary_text,
        "summary_text": f"Short-term: {summary_text} Long-term: {long_summary_text}",
    }


def open_frozen_long_term_memory() -> tuple[cvlm.MemoryStore, int]:
    """Validate and open the fixed historical database without network access."""
    if not LONG_TERM_MEMORY_DB.is_file():
        raise FileNotFoundError(
            f"Frozen long-term memory database not found: {LONG_TERM_MEMORY_DB}"
        )

    try:
        from sentence_transformers import SentenceTransformer
        from transformers.utils import logging as transformers_logging

        transformers_logging.disable_progress_bar()

        model = SentenceTransformer(
            LONG_TERM_EMBEDDING_MODEL,
            local_files_only=True,
        )
    except Exception as exc:
        raise RuntimeError(
            "The cached long-term memory embedding model is unavailable. "
            f"Expected local model: {LONG_TERM_EMBEDDING_MODEL}"
        ) from exc

    provider = cvlm.EmbeddingProvider(model_name=LONG_TERM_EMBEDDING_MODEL)
    provider._model = model
    store = cvlm.MemoryStore(
        db_path=str(LONG_TERM_MEMORY_DB),
        read_only=True,
        embedding_provider=provider,
    )
    candidates = store.get_candidate_entries_with_vectors(
        feedback_status="complete"
    )
    if not candidates:
        store.close()
        raise RuntimeError(
            f"Frozen long-term memory database has no complete cases: "
            f"{LONG_TERM_MEMORY_DB}"
        )

    sample = candidates[0]
    try:
        state_dim = len(json.loads(sample.get("state_vector") or "[]"))
        layer_dim = len(json.loads(sample.get("layer_vector") or "[]"))
        text_dim = len(json.loads(sample.get("text_embedding") or "[]"))
    except (TypeError, json.JSONDecodeError) as exc:
        store.close()
        raise RuntimeError(
            "Frozen long-term memory database contains invalid vector data."
        ) from exc
    if (state_dim, layer_dim, text_dim) != (8, 4, 384):
        store.close()
        raise RuntimeError(
            "Frozen long-term memory vectors are incompatible: "
            f"expected (8, 4, 384), got ({state_dim}, {layer_dim}, {text_dim})."
        )
    return store, len(candidates)


class DeterministicReplayProvider:
    """
    Offline stand-in for the external model call.

    The returned objects use exactly the same response schema as PolicyClient.
    The sequence is chosen to make the video show escalation and cautious
    de-escalation.  CEMAS still validates each response and applies its normal
    configured policy guardrails.
    """

    def __init__(self) -> None:
        self.index = 0
        self.sequence = [
            {
                "policy_id": "P2_moderate",
                "risk_level": "high",
                "reason": "Rising spread needs moderate controls.",
            },
            {
                "policy_id": "P3_strong",
                "risk_level": "critical",
                "reason": "Sustained spread needs strong controls.",
            },
            {
                "policy_id": "P1_guarded",
                "risk_level": "low",
                "reason": "Improvement supports cautious step-down.",
            },
        ]

    def __call__(self, state: dict, policy_catalog: dict) -> dict:
        del state, policy_catalog
        choice = self.sequence[min(self.index, len(self.sequence) - 1)]
        self.index += 1
        return dict(choice)


class RecordingDemoAgent(cv.campus_policy_agent):
    """Campus policy agent that narrates each completed decision cycle."""

    def __init__(self, *args, demo_pause: float = 0.0, **kwargs):
        self.demo_pause = max(0.0, float(demo_pause))
        super().__init__(*args, **kwargs)

    def _pause(self) -> None:
        if self.demo_pause:
            time.sleep(self.demo_pause)

    def apply(self, sim):
        previous_count = len(self.decision_history)
        super().apply(sim)
        if len(self.decision_history) > previous_count:
            self._print_completed_cycle(sim, self.decision_history[-1])
        return

    def _print_completed_cycle(self, sim, record: dict) -> None:
        state = record.get("state_snapshot", {})
        summary = state.get("past_7d_summary", {})
        burden = state.get("intervention_burden_last_7d", {})
        recent_memory = state.get("recent_policy_memory", [])
        memory = record.get("memory_snapshot", {})
        english_memory = build_english_memory_summary(state, memory)
        profile = record.get("restriction_profile_applied", {})

        print(f"\n  ┌─ Decision cycle @ day {record.get('decision_day')} "
              f"({record.get('decision_date')})")
        print("  │ [1/4] OBSERVATION")
        print(
            "  │   7-day infections={:.0f}, diagnoses={:.0f}, "
            "growth={:.2f}, R_eff={:.2f}, risk={}".format(
                float(summary.get("new_infections_sum", 0.0)),
                float(summary.get("new_diagnoses_sum", 0.0)),
                float(state.get("growth_ratio_7d_vs_prev_7d", 0.0)),
                float(summary.get("r_eff_current", 0.0)),
                summary.get("estimated_risk_trend", "unknown"),
            )
        )
        print(
            "  │   tests={:.0f}, mean quarantined={:.1f}, dominant layer={}".format(
                float(burden.get("tests_sum", 0.0)),
                float(burden.get("mean_quarantined", 0.0)),
                state.get("peak_layer_last_7d", "none"),
            )
        )
        self._pause()

        print("  │ [2/4] MEMORY SUMMARY")
        print(
            f"  │   mode={english_memory['memory_mode']}"
        )
        print(
            f"  │   Short-term ({english_memory['compressed_periods']} periods): "
            f"{compact_text(english_memory['short_term_summary_text'], 105)}"
        )
        print(
            f"  │   Long-term ({english_memory['long_term_retrieved_count']} cases): "
            f"{compact_text(english_memory['long_term_summary_text'], 105)}"
        )
        self._pause()

        print("  │ [3/4] POLICY SELECTION")
        proposed = record.get("model_policy_proposed")
        applied = record.get("applied_policy")
        before = record.get("current_policy_before")
        transition_note = "validated"
        if proposed != applied:
            transition_note = "adjusted by policy guardrail"
        print(
            f"  │   {before} -> proposed {proposed} -> executed {applied} "
            f"({transition_note})"
        )
        print(f"  │   rationale: {compact_text(record.get('reason'))}")
        self._pause()

        print("  │ [4/4] INTERVENTION EXECUTION")
        beta_text = ", ".join(f"{key}×{float(profile.get(key, 1.0)):.2f}"
                              for key in LAYER_INFO)
        testing = self.policy_catalog[applied]["testing_profile"]
        screening = self._get_screening_profile(applied, sim)
        print(f"  │   layer transmission multipliers: {beta_text}")
        print(
            "  │   symptomatic test p={:.2f}, screening capacity={}/day, "
            "online teaching={}".format(
                float(testing["symp_prob"]),
                int(screening["daily_capacity"]),
                bool(self.policy_catalog[applied]["online_teaching_active"]),
            )
        )
        print("  └" + "─" * 72)
        self._pause()


def build_demo_sim(args: argparse.Namespace) -> cv.Sim:
    """Construct the small campus simulation and its narrated policy agent."""
    agent = RecordingDemoAgent(
        start_day=0,
        decision_interval_days=args.decision_interval,
        state_window_days=7,
        initial_policy="P1_guarded",
        defer_first_decision_until_interval=True,
        min_policy_hold_intervals=0,
        enable_burden_guardrail=True,
        enforce_transition_constraint=False,
        memory_weeks=4,
        decision_fn=DeterministicReplayProvider(),
        memory_store=None,
        global_memory_store=None,
        enable_memory_context=True,
        enable_short_term_memory=True,
        enable_long_term_memory=True,
        short_term_window=4,
        similar_top_k=6,
        similar_cases_per_group=2,
        log_path=None,
        model="deterministic-supplement-replay",
        label="supplement_demo_agent",
        demo_pause=args.pace,
    )
    sim = cv.Sim(
        pars={
            "pop_type": "campus",
            "pop_size": args.pop_size,
            "pop_infected": args.pop_infected,
            "n_days": args.days,
            "rand_seed": args.seed,
            "verbose": 0,
        },
        interventions=[agent],
        label="cemas_supplement_demo",
    )
    global_store, complete_cases = open_frozen_long_term_memory()
    sim_agent = sim["interventions"][0]
    sim_agent.memory_store = cvlm.MemoryStore(":memory:")
    sim_agent.global_memory_store = global_store
    sim.long_term_memory_db_path = str(LONG_TERM_MEMORY_DB)
    sim.long_term_memory_complete_cases = int(complete_cases)
    return sim


def close_demo_memory_stores(sim: cv.Sim) -> None:
    """Close episode and frozen-memory connections after records are materialized."""
    agent = sim["interventions"][0]
    stores = [agent.memory_store, agent.global_memory_store]
    seen = set()
    for store in stores:
        if store is not None and id(store) not in seen:
            seen.add(id(store))
            store.close()


def role_name(people, uid: int) -> str:
    student_level = int(people.student_level[uid])
    if student_level == 0:
        return "undergraduate"
    if student_level == 1:
        return "graduate"
    role = int(people.role[uid])
    return "teacher" if role == 1 else "staff"


def summarize_network(sim: cv.Sim) -> dict:
    """Return role, group, and current edge counts for the constructed campus."""
    people = sim.people
    roles = Counter(role_name(people, uid) for uid in range(sim["pop_size"]))
    edges = {key: int(len(people.contacts[key]["p1"])) for key in LAYER_INFO}
    return {
        "population": int(sim["pop_size"]),
        "roles": dict(roles),
        "groups": {
            "undergraduate_classes": int(len(people.class_groups_ug)),
            "graduate_classes": int(len(people.class_groups_gr)),
            "laboratory_groups": int(len(people.lab_groups)),
        },
        "layers": {
            key: {"name": LAYER_INFO[key][0], "edges": edges[key]}
            for key in LAYER_INFO
        },
    }


def print_network_summary(summary: dict) -> None:
    section("STAGE 1 — Build campus population and six-layer contact network")
    print(f"  Population: {summary['population']:,}")
    print("  Roles: " + ", ".join(
        f"{name}={count}" for name, count in summary["roles"].items()
    ))
    print("  Groups: " + ", ".join(
        f"{name}={count}" for name, count in summary["groups"].items()
    ))
    print("\n  Layer  Contact setting                 Current edges")
    print("  -----  ------------------------------  -------------")
    for key, item in summary["layers"].items():
        print(f"  {key:<5}  {item['name']:<30}  {item['edges']:>13,}")
    print("  ✓ Six required layers verified: " + ", ".join(summary["layers"]))


def infection_arrays(sim: cv.Sim) -> dict[str, np.ndarray]:
    """Count daily transmissions by layer from the individual infection log."""
    arrays = {key: np.zeros(sim.npts, dtype=int) for key in LAYER_INFO}
    for item in sim.people.infection_log:
        key = item.get("layer")
        day = int(item.get("date", -1))
        if key in arrays and 0 <= day < sim.npts:
            arrays[key][day] += 1
    return arrays


def result_values(sim: cv.Sim, key: str) -> np.ndarray:
    value = sim.results[key]
    return np.asarray(value.values if hasattr(value, "values") else value, dtype=float)


def policy_by_day(agent: RecordingDemoAgent, npts: int) -> list[str]:
    trace = {int(item["day"]): item["policy_id"] for item in agent.policy_trace}
    current = agent.initial_policy
    output = []
    for day in range(npts):
        current = trace.get(day, current)
        output.append(current)
    return output


def collect_metrics(sim: cv.Sim, network_summary: dict) -> tuple[dict, list[dict]]:
    agent = sim["interventions"][0]
    layers = infection_arrays(sim)
    policies = policy_by_day(agent, sim.npts)
    daily = []
    for day in range(sim.npts):
        row = {
            "day": day,
            "date": str(sim.date(day)),
            "new_infections": float(result_values(sim, "new_infections")[day]),
            "new_diagnoses": float(result_values(sim, "new_diagnoses")[day]),
            "new_tests": float(result_values(sim, "new_tests")[day]),
            "n_infectious": float(result_values(sim, "n_infectious")[day]),
            "n_quarantined": float(result_values(sim, "n_quarantined")[day]),
            "r_eff": float(result_values(sim, "r_eff")[day]),
            "policy_id": policies[day],
            "policy_rank": POLICY_INFO[policies[day]][1],
        }
        for key, values in layers.items():
            row[f"transmissions_{key}"] = int(values[day])
        daily.append(row)

    metrics = {
        "configuration": {
            "population": int(sim["pop_size"]),
            "initial_infections": int(sim["pop_infected"]),
            "simulation_days_parameter": int(sim["n_days"]),
            "recorded_time_points": int(sim.npts),
            "random_seed": int(sim["rand_seed"]),
            "decision_interval_days": int(agent.decision_interval_days),
            "decision_provider": "deterministic-supplement-replay",
            "transition_constraint_enabled": bool(
                agent.enforce_transition_constraint
            ),
            "memory_mode": "both",
            "short_term_memory_enabled": bool(agent.enable_short_term_memory),
            "long_term_memory_enabled": bool(agent.enable_long_term_memory),
            "long_term_memory_database": str(
                getattr(sim, "long_term_memory_db_path", LONG_TERM_MEMORY_DB)
            ),
            "long_term_complete_cases": int(
                getattr(sim, "long_term_memory_complete_cases", 0)
            ),
        },
        "network": network_summary,
        "epidemic": {
            "cumulative_infections": float(result_values(sim, "cum_infections")[-1]),
            "cumulative_diagnoses": float(result_values(sim, "cum_diagnoses")[-1]),
            "cumulative_tests": float(result_values(sim, "cum_tests")[-1]),
            "peak_daily_infections": float(result_values(sim, "new_infections").max()),
            "peak_infectious": float(result_values(sim, "n_infectious").max()),
            "peak_quarantined": float(result_values(sim, "n_quarantined").max()),
            "final_r_eff": float(result_values(sim, "r_eff")[-1]),
        },
        "policy": {
            "decision_count": int(len(agent.decision_history)),
            "decision_days": [int(x["decision_day"]) for x in agent.decision_history],
            "executed_policies": [x["applied_policy"] for x in agent.decision_history],
            "final_policy": policies[-1],
            "policy_switches": int(sum(
                policies[i] != policies[i - 1] for i in range(1, len(policies))
            )),
        },
        "transmission_by_layer": {
            key: int(values.sum()) for key, values in layers.items()
        },
    }
    return metrics, daily


def write_outputs(
    sim: cv.Sim,
    metrics: dict,
    daily: list[dict],
    outdir: Path,
) -> list[Path]:
    """Write compact, English-only machine-readable artefacts."""
    agent = sim["interventions"][0]
    paths = []

    metrics_path = outdir / "key_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths.append(metrics_path)

    daily_path = outdir / "daily_epidemic_and_policy.csv"
    with daily_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(daily[0]))
        writer.writeheader()
        writer.writerows(daily)
    paths.append(daily_path)

    decisions = []
    for item in agent.decision_history:
        state = item.get("state_snapshot", {})
        memory_summary = build_english_memory_summary(
            state, item.get("memory_snapshot", {})
        )
        decisions.append(
            {
                "decision_day": item.get("decision_day"),
                "decision_date": item.get("decision_date"),
                "observation": {
                    "past_7d_summary": state.get("past_7d_summary", {}),
                    "growth_ratio_7d_vs_prev_7d": state.get(
                        "growth_ratio_7d_vs_prev_7d"
                    ),
                    "peak_layer_last_7d": state.get("peak_layer_last_7d"),
                    "intervention_burden_last_7d": state.get(
                        "intervention_burden_last_7d", {}
                    ),
                },
                "memory_summary": memory_summary,
                "current_policy_before": item.get("current_policy_before"),
                "model_policy_proposed": item.get("model_policy_proposed"),
                "applied_policy": item.get("applied_policy"),
                "risk_level": item.get("risk_level"),
                "reason": item.get("reason"),
                "guardrail_adjusted": item.get("guardrail_adjusted"),
                "guardrail_reason": item.get("guardrail_reason"),
                "restriction_profile_applied": item.get(
                    "restriction_profile_applied", {}
                ),
                "transition_constraint_enabled": bool(
                    agent.enforce_transition_constraint
                ),
            }
        )

    audit_path = outdir / "decision_audit.jsonl"
    with audit_path.open("w", encoding="utf-8", newline="\n") as handle:
        for decision in decisions:
            handle.write(json.dumps(decision, ensure_ascii=True) + "\n")
    paths.append(audit_path)

    decisions_path = outdir / "decision_story.json"
    decisions_path.write_text(
        json.dumps(decisions, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    paths.append(decisions_path)

    trace_path = outdir / "policy_trace.csv"
    with trace_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "day", "date", "policy_id", "policy_duration_days",
            "restriction_intensity", "online_teaching_active",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in agent.policy_trace:
            writer.writerow({key: item.get(key) for key in fieldnames})
    paths.append(trace_path)
    return paths


def connected_sample(layer, max_nodes: int = 18) -> tuple[list[int], list[tuple[int, int]]]:
    """Extract a small connected-looking sample without adding NetworkX."""
    p1 = np.asarray(layer["p1"], dtype=int)
    p2 = np.asarray(layer["p2"], dtype=int)
    if not len(p1):
        return [], []

    adjacency: dict[int, set[int]] = defaultdict(set)
    for a, b in zip(p1, p2):
        adjacency[int(a)].add(int(b))
        adjacency[int(b)].add(int(a))

    start = max(adjacency, key=lambda node: len(adjacency[node]))
    selected = []
    seen = {start}
    queue = deque([start])
    while queue and len(selected) < max_nodes:
        node = queue.popleft()
        selected.append(node)
        neighbors = sorted(adjacency[node], key=lambda x: len(adjacency[x]), reverse=True)
        for neighbor in neighbors:
            if neighbor not in seen and len(seen) < max_nodes:
                seen.add(neighbor)
                queue.append(neighbor)

    selected_set = set(selected)
    edges = [
        (int(a), int(b)) for a, b in zip(p1, p2)
        if int(a) in selected_set and int(b) in selected_set
    ]
    return selected, edges[:45]


def make_network_figure(sim: cv.Sim, outdir: Path):
    """Visualize sampled nodes from each of the six actual contact layers."""
    fig, axes = plt.subplots(2, 3, figsize=(15.5, 8.5))
    for ax, (key, (name, layer_color)) in zip(axes.flat, LAYER_INFO.items()):
        nodes, edges = connected_sample(sim.people.contacts[key])
        if not nodes:
            ax.text(0.5, 0.5, "Dynamic layer\n(no current edges)",
                    ha="center", va="center", transform=ax.transAxes)
        else:
            angles = np.linspace(0, 2 * np.pi, len(nodes), endpoint=False)
            positions = {
                uid: (np.cos(angle), np.sin(angle))
                for uid, angle in zip(nodes, angles)
            }
            for a, b in edges:
                ax.plot(
                    [positions[a][0], positions[b][0]],
                    [positions[a][1], positions[b][1]],
                    color=layer_color,
                    alpha=0.30,
                    lw=1.1,
                    zorder=1,
                )
            colors = [ROLE_INFO[role_name(sim.people, uid)] for uid in nodes]
            ax.scatter(
                [positions[uid][0] for uid in nodes],
                [positions[uid][1] for uid in nodes],
                s=72,
                c=colors,
                edgecolor="white",
                linewidth=0.7,
                zorder=2,
            )
        ax.set_title(
            f"{key} · {name}\n{len(sim.people.contacts[key]['p1']):,} current edges",
            fontsize=11,
        )
        ax.set_aspect("equal")
        ax.axis("off")

    role_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=color,
               markeredgecolor="white", markersize=9, label=name.title())
        for name, color in ROLE_INFO.items()
    ]
    fig.legend(handles=role_handles, loc="lower center", ncol=4, frameon=False)
    fig.suptitle(
        "CEMAS small-campus population: six-layer contact network",
        fontsize=17,
        y=0.98,
    )
    fig.text(
        0.5,
        0.035,
        "Sampled nodes and edges from the simulated population; totals report the full current layer.",
        ha="center",
        color="#555555",
    )
    fig.tight_layout(rect=[0.02, 0.07, 0.98, 0.94])
    path = outdir / "01_six_layer_network.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    return fig, path


def add_policy_background(ax, policies: list[str]) -> None:
    start = 0
    for idx in range(1, len(policies) + 1):
        if idx == len(policies) or policies[idx] != policies[start]:
            color = POLICY_INFO[policies[start]][2]
            ax.axvspan(start - 0.5, idx - 0.5, color=color, alpha=0.08, lw=0)
            start = idx


def make_dashboard_figure(
    sim: cv.Sim,
    metrics: dict,
    daily: list[dict],
    outdir: Path,
):
    """Create the principal supplementary-video result dashboard."""
    days = np.arange(sim.npts)
    agent = sim["interventions"][0]
    policies = [row["policy_id"] for row in daily]
    decision_days = [int(item["decision_day"]) for item in agent.decision_history]
    layers = infection_arrays(sim)

    fig = plt.figure(figsize=(16, 10))
    grid = fig.add_gridspec(2, 2, hspace=0.34, wspace=0.20)

    ax1 = fig.add_subplot(grid[0, 0])
    add_policy_background(ax1, policies)
    ax1.bar(
        days,
        result_values(sim, "new_infections"),
        color="#4E79A7",
        alpha=0.82,
        label="New infections",
    )
    ax1.plot(
        days,
        result_values(sim, "new_diagnoses"),
        color="#E15759",
        marker="o",
        ms=3,
        lw=1.8,
        label="New diagnoses",
    )
    for day in decision_days:
        ax1.axvline(day, color="#333333", ls="--", lw=1.0, alpha=0.65)
    ax1.set_title("A. Epidemic curve and decision times")
    ax1.set_xlabel("Simulation day")
    ax1.set_ylabel("People / day")
    ax1.set_xlim(-0.5, sim.npts - 0.5)
    ax1.legend(frameon=False, ncol=2, loc="upper left")

    ax2 = fig.add_subplot(grid[0, 1])
    ranks = np.asarray([POLICY_INFO[policy][1] for policy in policies])
    ax2.step(days, ranks, where="post", color="#2F4B7C", lw=3)
    ax2.scatter(decision_days, ranks[decision_days], s=80, color="#E15759",
                edgecolor="white", zorder=3, label="Policy decision")
    for record in agent.decision_history:
        day = int(record["decision_day"])
        ax2.annotate(
            record["applied_policy"].split("_")[0],
            (day, ranks[day]),
            xytext=(0, 14),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            fontweight="bold",
        )
    ax2.set_yticks(range(5), [POLICY_INFO[key][0] for key in POLICY_INFO])
    ax2.set_ylim(-0.35, 4.35)
    ax2.set_xlim(-0.5, sim.npts - 0.5)
    ax2.set_xlabel("Simulation day")
    ax2.set_title("B. Executed policy trajectory")
    ax2.legend(frameon=False, loc="upper left")

    ax3 = fig.add_subplot(grid[1, 0])
    bottom = np.zeros(sim.npts)
    for key, (name, color) in LAYER_INFO.items():
        values = layers[key]
        ax3.bar(days, values, bottom=bottom, width=0.85, color=color, label=key)
        bottom += values
    for day in decision_days:
        ax3.axvline(day, color="#333333", ls="--", lw=0.9, alpha=0.55)
    ax3.set_xlim(-0.5, sim.npts - 0.5)
    ax3.set_xlabel("Simulation day")
    ax3.set_ylabel("Transmissions")
    ax3.set_title("C. Transmission contribution by contact layer")
    ax3.legend(
        handles=[Patch(facecolor=color, label=f"{key}: {name}")
                 for key, (name, color) in LAYER_INFO.items()],
        frameon=False,
        fontsize=8,
        ncol=2,
        loc="upper left",
    )

    ax4 = fig.add_subplot(grid[1, 1])
    ax4.axis("off")
    epi = metrics["epidemic"]
    policy = metrics["policy"]
    kpis = [
        ("Cumulative infections", f"{epi['cumulative_infections']:.0f}"),
        ("Cumulative diagnoses", f"{epi['cumulative_diagnoses']:.0f}"),
        ("Cumulative tests", f"{epi['cumulative_tests']:.0f}"),
        ("Peak infectious", f"{epi['peak_infectious']:.0f}"),
        ("Peak quarantined", f"{epi['peak_quarantined']:.0f}"),
        ("Policy decisions", f"{policy['decision_count']}"),
        ("Policy switches", f"{policy['policy_switches']}"),
        ("Final policy", POLICY_INFO[policy["final_policy"]][0]),
    ]
    for idx, (label, value) in enumerate(kpis):
        row, col = divmod(idx, 2)
        x = 0.04 + col * 0.49
        y = 0.88 - row * 0.22
        ax4.text(x, y, value, transform=ax4.transAxes, fontsize=22,
                 fontweight="bold", color="#2F4B7C", va="top")
        ax4.text(x, y - 0.08, label, transform=ax4.transAxes, fontsize=10,
                 color="#555555", va="top")
    ax4.set_title("D. Key outcomes", loc="left", pad=12)

    fig.suptitle(
        "CEMAS supplementary demo · epidemic, policy, layers, and outcomes",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.012,
        "Policy provider: deterministic replay. State extraction, memory, response "
        "validation, and interventions use the production CEMAS pipeline.",
        ha="center",
        fontsize=9,
        color="#555555",
    )
    path = outdir / "02_demo_dashboard.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    return fig, path


def make_decision_storyboard(sim: cv.Sim, outdir: Path):
    """Visual summary of observation → memory → choice → execution."""
    agent = sim["interventions"][0]
    records = agent.decision_history
    fig, axes = plt.subplots(
        len(records),
        4,
        figsize=(16, max(3.0, 2.7 * len(records))),
        squeeze=False,
        gridspec_kw={"width_ratios": [1.0, 1.65, 1.0, 1.45]},
    )
    column_titles = [
        "1 · Observation",
        "2 · Dual-branch memory",
        "3 · Policy selection",
        "4 · Intervention execution",
    ]

    for row, record in enumerate(records):
        state = record.get("state_snapshot", {})
        summary = state.get("past_7d_summary", {})
        memory = record.get("memory_snapshot", {})
        applied = record["applied_policy"]
        profile = record.get("restriction_profile_applied", {})

        observation = (
            f"Day {record['decision_day']}\n"
            f"7-day infections: {float(summary.get('new_infections_sum', 0)):.0f}\n"
            f"7-day diagnoses: {float(summary.get('new_diagnoses_sum', 0)):.0f}\n"
            f"Growth ratio: {float(state.get('growth_ratio_7d_vs_prev_7d', 0)):.2f}\n"
            f"R_eff: {float(summary.get('r_eff_current', 0)):.2f}\n"
            f"Dominant layer: {state.get('peak_layer_last_7d', 'none')}"
        )
        english_memory = build_english_memory_summary(state, memory)
        top_cases = english_memory["top_historical_cases"]
        if top_cases:
            top = top_cases[0]
            top_case_text = (
                f"Top: {top['policy_id']} | sim {top['similarity']:.2f}\n"
                f"{top['risk_level']} risk | {top['dominant_layer']} | "
                f"post-policy {top['post_policy_trend']}"
            )
        else:
            top_case_text = "Top: no comparable case"
        memory_text = (
            f"Mode: {english_memory['memory_mode']}\n"
            f"SHORT · {english_memory['compressed_periods']} periods\n"
            f"Path: "
            f"{' -> '.join(english_memory['policy_path']) if english_memory['policy_path'] else 'none yet'}\n"
            f"Effect: {english_memory['observed_effect']} | "
            f"{english_memory['compressed_epidemic_trend']}\n"
            f"LONG · {english_memory['long_term_retrieved_count']} cases\n"
            f"{top_case_text}"
        )
        selection = (
            f"Before\n{record['current_policy_before']}\n\n"
            f"Proposed\n{record['model_policy_proposed']}\n\n"
            f"Executed\n{applied}\n"
            f"Risk: {record['risk_level']}"
        )
        execution = (
            "Contact multipliers\n"
            + "  ".join(f"{key} {float(profile.get(key, 1)):.2f}"
                       for key in LAYER_INFO)
            + f"\n\nSymptomatic test p: "
              f"{agent.policy_catalog[applied]['testing_profile']['symp_prob']:.2f}"
            + f"\nOnline teaching: "
              f"{agent.policy_catalog[applied]['online_teaching_active']}"
        )

        texts = [observation, memory_text, selection, execution]
        for col, (ax, text) in enumerate(zip(axes[row], texts)):
            ax.axis("off")
            facecolor = "#F5F7FA" if col != 2 else POLICY_INFO[applied][2]
            alpha = 1.0 if col != 2 else 0.16
            ax.text(
                0.04,
                0.92,
                text,
                transform=ax.transAxes,
                va="top",
                ha="left",
                fontsize=10,
                linespacing=1.45,
                bbox={
                    "boxstyle": "round,pad=0.8",
                    "facecolor": facecolor,
                    "edgecolor": POLICY_INFO[applied][2],
                    "alpha": alpha,
                },
            )
            if row == 0:
                ax.set_title(column_titles[col], fontsize=12, pad=12)
            if col < 3:
                ax.annotate(
                    "",
                    xy=(1.04, 0.5),
                    xytext=(0.96, 0.5),
                    xycoords=ax.transAxes,
                    arrowprops={"arrowstyle": "->", "color": "#666666", "lw": 1.5},
                    annotation_clip=False,
                )

    fig.suptitle(
        "Decision-cycle audit: observation → memory → policy → intervention",
        fontsize=17,
        y=0.995,
    )
    fig.subplots_adjust(
        left=0.025, right=0.985, bottom=0.035, top=0.91, wspace=0.42, hspace=0.34
    )
    path = outdir / "03_decision_storyboard.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    return fig, path


def make_dynamic_dashboard(
    sim: cv.Sim,
    metrics: dict,
    daily: list[dict],
    interval_ms: int = 180,
):
    """Build a dual-memory dashboard that waits for a click after each decision."""
    agent = sim["interventions"][0]
    layers = infection_arrays(sim)
    all_days = np.arange(sim.npts)
    policies = [row["policy_id"] for row in daily]
    ranks = np.asarray([POLICY_INFO[policy][1] for policy in policies])
    decisions_by_day = {
        int(record["decision_day"]): record for record in agent.decision_history
    }
    decision_days = sorted(decisions_by_day)
    new_infections = result_values(sim, "new_infections")
    new_diagnoses = result_values(sim, "new_diagnoses")

    # phase: 0=monitoring, 1=observation, 2=short-term, 3=long-term,
    # 4=policy/intervention. Both memory cards remain visible in phases 1-4.
    frames = []
    for day in range(sim.npts):
        if day in decisions_by_day:
            for phase in range(1, 5):
                frames.extend([(day, phase)] * 7)
        else:
            frames.extend([(day, 0)] * 3)

    fig = plt.figure(figsize=(16, 9))
    outer = fig.add_gridspec(
        1, 2, width_ratios=[1.38, 1.0], wspace=0.24,
    )
    left = outer[0].subgridspec(2, 1, hspace=0.34)
    right = outer[1].subgridspec(2, 1, height_ratios=[0.64, 1.36], hspace=0.26)
    ax_epi = fig.add_subplot(left[0])
    ax_layers = fig.add_subplot(left[1])
    ax_policy = fig.add_subplot(right[0])
    ax_card = fig.add_subplot(right[1])
    title = fig.suptitle("", fontsize=19, y=0.975, fontweight="bold")
    footer = fig.text(
        0.5, 0.032, "", ha="center", fontsize=9.2, color="#555555"
    )
    fig.subplots_adjust(left=0.06, right=0.97, bottom=0.11, top=0.91)

    fixed_epi_max = max(
        5.0, float(max(new_infections.max(), new_diagnoses.max())) * 1.2
    )
    fixed_layer_max = max(
        5.0,
        float(np.sum(np.vstack(list(layers.values())), axis=0).max()) * 1.2,
    )
    phase_names = {
        0: "Daily monitoring",
        1: "1/4 Observation",
        2: "2/4 Short-term memory",
        3: "3/4 Long-term memory",
        4: "4/4 Policy and intervention",
    }
    controls = {
        "manual_paused": False,
        "awaiting_click": False,
        "released_decisions": set(),
        "last_day": -1,
        "animation": None,
        "armed": False,
    }

    def latest_decision(day: int):
        eligible = [value for key, value in decisions_by_day.items() if key <= day]
        return eligible[-1] if eligible else None

    def add_card(x, y, width, height, heading, lines, color, highlighted=False):
        patch = FancyBboxPatch(
            (x, y),
            width,
            height,
            transform=ax_card.transAxes,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            facecolor=color,
            edgecolor=color,
            linewidth=3.0 if highlighted else 1.1,
            alpha=0.22 if highlighted else 0.08,
            clip_on=False,
        )
        ax_card.add_patch(patch)
        ax_card.text(
            x + 0.025,
            y + height - 0.035,
            heading,
            transform=ax_card.transAxes,
            va="top",
            fontsize=10.2,
            fontweight="bold",
            color=color,
        )
        ax_card.text(
            x + 0.025,
            y + height - 0.095,
            "\n".join(lines),
            transform=ax_card.transAxes,
            va="top",
            fontsize=8.7,
            linespacing=1.25,
            color="#222222",
            wrap=True,
        )

    def draw_frame(frame):
        if isinstance(frame, (tuple, list)):
            day, phase = int(frame[0]), int(frame[1])
        else:
            day, phase = int(frame), 0
        if controls["armed"] and day < controls["last_day"]:
            # A looping animation has returned to Day 0. Require one click at
            # each decision again during the new playback cycle.
            controls["released_decisions"].clear()
            controls["awaiting_click"] = False
        controls["last_day"] = day
        current_policy = policies[day]
        policy_label, _, policy_color = POLICY_INFO[current_policy]
        shown_days = all_days[: day + 1]

        ax_epi.clear()
        add_policy_background(ax_epi, policies[: day + 1])
        ax_epi.bar(
            shown_days, new_infections[: day + 1],
            color="#4E79A7", alpha=0.84, label="New infections",
        )
        ax_epi.plot(
            shown_days, new_diagnoses[: day + 1],
            color="#E15759", marker="o", ms=3.5, lw=2,
            label="New diagnoses",
        )
        for decision_day in decision_days:
            if decision_day <= day:
                ax_epi.axvline(
                    decision_day, color="#333333", ls="--", lw=1, alpha=0.6
                )
        ax_epi.set(
            title="A. Epidemic curve", xlabel="Simulation day",
            ylabel="People / day", xlim=(-0.5, sim.npts - 0.5),
            ylim=(0, fixed_epi_max),
        )
        ax_epi.legend(frameon=False, ncol=2, loc="upper left")

        ax_layers.clear()
        bottom = np.zeros(day + 1)
        for key, (name, color) in LAYER_INFO.items():
            values = layers[key][: day + 1]
            ax_layers.bar(
                shown_days, values, bottom=bottom, width=0.85,
                color=color, label=f"{key}: {name}",
            )
            bottom += values
        for decision_day in decision_days:
            if decision_day <= day:
                ax_layers.axvline(
                    decision_day, color="#333333", ls="--", lw=0.9, alpha=0.55
                )
        ax_layers.set(
            title="B. Transmission contribution by contact layer",
            xlabel="Simulation day", ylabel="Transmissions",
            xlim=(-0.5, sim.npts - 0.5), ylim=(0, fixed_layer_max),
        )
        ax_layers.legend(frameon=False, fontsize=8, ncol=2, loc="upper left")

        ax_policy.clear()
        ax_policy.step(
            shown_days, ranks[: day + 1], where="post", color="#2F4B7C", lw=3
        )
        visible_decisions = [value for value in decision_days if value <= day]
        if visible_decisions:
            ax_policy.scatter(
                visible_decisions, ranks[visible_decisions], s=70,
                color="#E15759", edgecolor="white", zorder=3,
            )
        ax_policy.scatter(
            [day], [ranks[day]], s=135, color=policy_color,
            edgecolor="white", linewidth=1.5, zorder=4,
        )
        ax_policy.set_yticks(
            range(5), [POLICY_INFO[key][0] for key in POLICY_INFO]
        )
        ax_policy.set(
            title="C. Executed policy trajectory", xlabel="Simulation day",
            xlim=(-0.5, sim.npts - 0.5), ylim=(-0.35, 4.35),
        )

        ax_card.clear()
        ax_card.axis("off")
        record = decisions_by_day.get(day)
        if record is None:
            last_record = latest_decision(day)
            if last_record is None:
                status = "Collecting the initial seven-day observation window."
            else:
                next_day = next(
                    (value for value in decision_days if value > day), "complete"
                )
                status = (
                    f"Monitoring outcomes after {last_record['applied_policy']}.\n"
                    f"Next scheduled decision: Day {next_day}."
                )
            add_card(
                0.03, 0.28, 0.94, 0.48, "SYSTEM STATUS",
                [
                    f"Day {day} · current policy: {current_policy}",
                    f"New infections: {new_infections[day]:.0f}",
                    f"New diagnoses: {new_diagnoses[day]:.0f}",
                    status,
                ],
                policy_color,
                highlighted=True,
            )
            card_title = "Daily monitoring"
        else:
            state = record.get("state_snapshot", {})
            summary = state.get("past_7d_summary", {})
            memory = build_english_memory_summary(
                state, record.get("memory_snapshot", {})
            )
            applied = record["applied_policy"]
            profile = record.get("restriction_profile_applied", {})
            top_cases = memory["top_historical_cases"]
            top = top_cases[0] if top_cases else None

            observation_lines = [
                (
                    f"Infections {float(summary.get('new_infections_sum', 0)):.0f} "
                    f"· growth {float(state.get('growth_ratio_7d_vs_prev_7d', 0)):.2f} "
                    f"· R_eff {float(summary.get('r_eff_current', 0)):.2f}"
                ),
                (
                    f"Risk {summary.get('estimated_risk_trend', 'unknown')} "
                    f"· dominant layer {state.get('peak_layer_last_7d', 'none')}"
                ),
            ]
            short_lines = [
                f"Completed periods: {memory['compressed_periods']}",
                (
                    "Path: "
                    + (
                        " → ".join(memory["policy_path"])
                        if memory["policy_path"] else "none yet"
                    )
                ),
                f"Observed effect: {memory['observed_effect']}",
                f"Compressed trend: {memory['compressed_epidemic_trend']}",
            ]
            if top is None:
                long_lines = [
                    f"Retrieved cases: {memory['long_term_retrieved_count']}",
                    "No comparable historical case.",
                ]
            else:
                long_lines = [
                    f"Retrieved cases: {memory['long_term_retrieved_count']}",
                    f"Top match: {top['policy_id']} · similarity {top['similarity']:.2f}",
                    f"Risk {top['risk_level']} · layer {top['dominant_layer']}",
                    f"Post-policy trend: {top['post_policy_trend']}",
                ]
            policy_lines = [
                (
                    f"{record['current_policy_before']} → "
                    f"{record['model_policy_proposed']} → {applied}"
                ),
                f"Reason: {record['reason']}",
                (
                    "Contacts: "
                    + "  ".join(
                        f"{key}×{float(profile.get(key, 1.0)):.2f}"
                        for key in LAYER_INFO
                    )
                ),
                (
                    f"Symptomatic test p "
                    f"{agent.policy_catalog[applied]['testing_profile']['symp_prob']:.2f}"
                ),
            ]
            if day == sim.npts - 1:
                epidemic = metrics["epidemic"]
                policy_lines.extend(
                    [
                        (
                            f"Final: infections {epidemic['cumulative_infections']:.0f} "
                            f"· diagnoses {epidemic['cumulative_diagnoses']:.0f}"
                        ),
                        (
                            f"Tests {epidemic['cumulative_tests']:.0f} "
                            f"· policy {metrics['policy']['final_policy']}"
                        ),
                    ]
                )

            add_card(
                0.02, 0.78, 0.96, 0.19, "1 · OBSERVATION",
                observation_lines, "#4E79A7", highlighted=phase == 1,
            )
            add_card(
                0.02, 0.46, 0.46, 0.28, "2A · SHORT-TERM MEMORY",
                short_lines, "#2D936C", highlighted=phase == 2,
            )
            add_card(
                0.52, 0.46, 0.46, 0.28, "2B · LONG-TERM MEMORY",
                long_lines, "#8E63B0", highlighted=phase == 3,
            )
            add_card(
                0.02, 0.05, 0.96, 0.36, "3–4 · POLICY AND INTERVENTION",
                policy_lines, policy_color, highlighted=phase == 4,
            )
            card_title = f"Decision at Day {day} · {phase_names[phase]}"

        ax_card.set_title(card_title, loc="left", fontsize=14, pad=8)
        title.set_text(
            f"CEMAS dual-branch memory demo  ·  Day {day:02d}/{sim.npts - 1:02d}"
            f"  ·  {policy_label}"
        )
        should_wait_for_click = (
            controls["armed"]
            and day in decisions_by_day
            and phase == 4
            and day not in controls["released_decisions"]
            and not controls["awaiting_click"]
        )
        if should_wait_for_click:
            controls["awaiting_click"] = True
            controls["animation"].event_source.stop()

        if controls["awaiting_click"]:
            footer.set_text(
                "DECISION PAUSED   ·   Click anywhere in this window to continue"
                "   ·   R: replay   ·   Esc: close"
            )
            footer.set_color("#B22222")
            footer.set_fontweight("bold")
        else:
            footer.set_text(
                f"{phase_names[phase]}   ·   Space: pause/resume   ·   "
                "R: replay   ·   Esc: close"
            )
            footer.set_color("#555555")
            footer.set_fontweight("normal")
        return []

    animation = FuncAnimation(
        fig, draw_frame, frames=frames, interval=max(30, int(interval_ms)),
        repeat=True, blit=False, cache_frame_data=False,
    )
    controls["animation"] = animation
    controls["armed"] = True

    def on_key(event):
        key = (event.key or "").lower()
        if key == " ":
            # Decision gates intentionally require a mouse click.
            if controls["awaiting_click"]:
                return
            if controls["manual_paused"]:
                animation.event_source.start()
            else:
                animation.event_source.stop()
            controls["manual_paused"] = not controls["manual_paused"]
        elif key == "r":
            controls["released_decisions"].clear()
            controls["awaiting_click"] = False
            controls["manual_paused"] = False
            controls["last_day"] = -1
            animation.frame_seq = animation.new_frame_seq()
            animation.event_source.start()
        elif key == "escape":
            plt.close(fig)

    def on_click(event):
        if controls["awaiting_click"]:
            controls["released_decisions"].add(controls["last_day"])
            controls["awaiting_click"] = False
            controls["manual_paused"] = False
            footer.set_text(
                "Playback resumed   ·   Space: pause/resume   ·   "
                "R: replay   ·   Esc: close"
            )
            footer.set_color("#555555")
            footer.set_fontweight("normal")
            fig.canvas.draw_idle()
            animation.event_source.start()

    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.canvas.mpl_connect("button_press_event", on_click)
    fig._cemas_animation = animation
    fig._cemas_controls = controls
    draw_frame((0, 0))
    return fig, animation


def print_final_summary(metrics: dict, paths: list[Path]) -> None:
    section("STAGE 4 — Export epidemic curves, policy trajectory, and key metrics")
    epi = metrics["epidemic"]
    policy = metrics["policy"]
    print(f"  Cumulative infections : {epi['cumulative_infections']:.0f}")
    print(f"  Cumulative diagnoses : {epi['cumulative_diagnoses']:.0f}")
    print(f"  Cumulative tests     : {epi['cumulative_tests']:.0f}")
    print(f"  Peak infectious      : {epi['peak_infectious']:.0f}")
    print(f"  Peak quarantined     : {epi['peak_quarantined']:.0f}")
    print(f"  Decisions / switches : {policy['decision_count']} / {policy['policy_switches']}")
    print(f"  Executed policies    : {' → '.join(policy['executed_policies'])}")
    print(f"  Final policy         : {policy['final_policy']}")
    print("\n  Output artefacts:")
    project_root = Path(__file__).resolve().parents[1]
    for path in paths:
        resolved_path = path.resolve()
        try:
            display_path = resolved_path.relative_to(project_root).as_posix()
        except ValueError:
            display_path = resolved_path.name
        print(f"    ✓ {display_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic CEMAS supplementary-video demo."
    )
    parser.add_argument("--pop-size", type=int, default=1200)
    parser.add_argument("--pop-infected", type=int, default=24)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--decision-interval", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="Pause this many seconds between narrated decision stages.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "supplement_demo",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save figures without opening GUI windows (useful for CI/headless runs).",
    )
    args = parser.parse_args()
    if args.pop_size < 300:
        parser.error("--pop-size must be at least 300 for all campus roles/layers.")
    if not 14 <= args.days <= 21:
        parser.error("--days must be between 14 and 21 for this short demo.")
    if args.decision_interval <= 0:
        parser.error("--decision-interval must be positive.")
    if args.pace < 0:
        parser.error("--pace must be non-negative.")
    if args.days // args.decision_interval < 2:
        parser.error("The selected duration must allow at least two policy decisions.")
    return args


def main() -> int:
    configure_console()
    configure_plot_style()
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    # The policy logger appends by design; start each demo run with a clean audit.
    (args.outdir / "decision_audit.jsonl").write_text("", encoding="utf-8")

    section("CEMAS SUPPLEMENTARY SYSTEM DEMO")
    print("  Mode              : deterministic offline replay")
    print(f"  Population        : {args.pop_size:,}")
    print(f"  Simulation horizon: {args.days} days")
    print(f"  Decision interval : {args.decision_interval} days")
    print(f"  Narration pace    : {args.pace:g} seconds")
    print(f"  Random seed       : {args.seed}")
    project_root = Path(__file__).resolve().parents[1]
    resolved_outdir = args.outdir.resolve()
    try:
        display_outdir = resolved_outdir.relative_to(project_root).as_posix()
    except ValueError:
        display_outdir = str(resolved_outdir)
    print(f"  Output directory  : {display_outdir}")

    try:
        sim = build_demo_sim(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        section("MEMORY CONFIGURATION ERROR")
        print(f"  {type(exc).__name__}: {exc}")
        print("  The demo requires a valid frozen database and cached embedding model.")
        return 2

    print(f"  Memory mode       : both (short-term + long-term)")
    print(f"  Historical memory : {sim.long_term_memory_db_path}")
    print(f"  Complete cases    : {sim.long_term_memory_complete_cases}")
    sim.initialize()
    sim.people.update_contacts()  # Materialize the three dynamic campus layers.
    network_summary = summarize_network(sim)
    expected_layers = set(LAYER_INFO)
    actual_layers = set(sim.people.contacts)
    if actual_layers != expected_layers:
        raise RuntimeError(
            f"Six-layer network check failed: expected {expected_layers}, got {actual_layers}"
        )
    print_network_summary(network_summary)
    network_fig, network_path = make_network_figure(sim, args.outdir)

    section("STAGE 2 — Run epidemic simulation")
    print(
        "  The policy agent will now narrate observation, memory, policy selection,\n"
        "  and intervention execution at every decision point."
    )
    try:
        sim.run()
    except Exception as exc:
        close_demo_memory_stores(sim)
        section("SIMULATION ERROR")
        print(f"  {type(exc).__name__}: {exc}")
        print("  Dual-branch memory is required; no single-branch fallback was used.")
        return 3

    agent = sim["interventions"][0]
    if len(agent.decision_history) < 2:
        raise RuntimeError("Demo invariant failed: fewer than two decisions were executed.")

    section("STAGE 3 — Assemble trajectories and decision audit")
    metrics, daily = collect_metrics(sim, network_summary)
    data_paths = write_outputs(sim, metrics, daily, args.outdir)
    dashboard_fig, dashboard_path = make_dashboard_figure(
        sim, metrics, daily, args.outdir
    )
    storyboard_fig, storyboard_path = make_decision_storyboard(sim, args.outdir)
    close_demo_memory_stores(sim)

    all_paths = [
        network_path,
        dashboard_path,
        storyboard_path,
        *data_paths,
    ]
    print_final_summary(metrics, all_paths)

    if args.no_show:
        plt.close(network_fig)
        plt.close(dashboard_fig)
        plt.close(storyboard_fig)
    else:
        plt.close(network_fig)
        plt.close(dashboard_fig)
        plt.close(storyboard_fig)
        dynamic_fig, dynamic_animation = make_dynamic_dashboard(
            sim, metrics, daily
        )
        del dynamic_animation  # The figure retains the live animation reference.
        section("DYNAMIC VISUAL RESULT DISPLAY")
        print("  The animated dashboard is ready.")
        print("  Each decision pauses after its four stages.")
        print("  Click inside the window to continue after a decision.")
        print("  Controls: Space=pause/resume, R=replay, Esc=close.")
        print("  Close the animation window to finish the demo.")
        plt.show()
        plt.close(dynamic_fig)

    section("DEMO COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

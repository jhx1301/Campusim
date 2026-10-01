"""
Helpers for LLM-driven campus policy selection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import numpy as np


DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
# Backward-compatible names retained for existing experiment scripts.
DEFAULT_DASHSCOPE_BASE_URL = DEFAULT_LLM_BASE_URL
DEFAULT_QWEN_MODEL = DEFAULT_LLM_MODEL
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_REASON_MAX_CHARS = 40
DEFAULT_MEMORY_WEEKS = 4

POLICY_IDS = [
    "P0_normal",
    "P1_guarded",
    "P2_moderate",
    "P3_strong",
    "P4_emergency",
]
RISK_LEVELS = ["low", "medium", "high", "critical"]
CAMPUS_LAYER_KEYS = ["d", "clu", "clg", "of", "ta", "cm"]
SYSTEM_KNOWLEDGE_RULES = [
    "Epidemic indicators often lag policy changes, so do not downgrade too quickly after a single-day decline.",
    "Base the immediate decision primarily on the recent 7-day versus previous 7-day trends, and use recent policy memory to judge whether the trend is sustained and whether the current policy is working across multiple periods.",
    "When the epidemic is clearly growing (rising cases week over week), prioritize suppressing the contact layers whose transmission trends are worsening the most.",
    "Dormitory, classroom, and community transmission can spill over into each other at the system level, so compare both current counts and trend direction.",
    "If infections, key layer transmission, and policy effects are all improving, prefer holding the current policy level to confirm the trend is sustained. Only consider downgrading when the epidemic shows sustained, unambiguous improvement across multiple consecutive decision cycles — a single week of decline is not enough to confirm the trend is durable.",
    "P3_strong and P4_emergency have high operational and teaching costs, so reserve them for clearly worsening transmission under the current policy.",
    "Do not escalate only because one layer is still the largest source; check whether that layer is rising or falling.",
    "Testing, isolation, and online teaching reduce transmission but also increase operational burden and disruption on the campus.",
    "Frequent policy up-down switching reduces stability and should be avoided unless risk is clearly worsening.",
]
DEFAULT_CPBU_WEIGHTS = {
    "infection": 0.45,
    "ops": 0.20,
    "teaching": 0.20,
    "stability": 0.15,
}
DEFAULT_PER_COST_WEIGHTS = {
    "cum_tests": 0.01,
    "mean_quarantined": 1.0,
    "teaching_restriction_days": 15.0,
    "policy_switch_count": 10.0,
}


class PolicyDecisionError(Exception):
    """Base error for policy decision failures."""


class PolicyResponseError(PolicyDecisionError):
    """Raised when the model response is invalid."""


def make_default_policy_catalog():
    """
    Return the fixed policy catalog for weekly campus policy selection.
    """
    return {
        "P0_normal": {
            "rank": 0,
            "summary": "Lowest-cost posture with normal teaching, baseline symptom testing, low-frequency targeted screening, and routine tracing.",
            "restriction_intensity": 0,
            "online_teaching_active": False,
            "restriction_profile": dict(d=1.00, clu=1.00, clg=1.00, of=1.00, ta=1.00, cm=1.00),
            "testing_profile": dict(symp_prob=0.08, asymp_prob=0.0, symp_quar_prob=0.25, asymp_quar_prob=0.0),
            "screening_profile": dict(
                daily_capacity_ratio=0.01,
                group_cycles=dict(teacher=7, lab=7, dorm=14, course=21, id_bucket=28),
                exclude_recent_days=4,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=0.60, clu=0.20, clg=0.20, of=0.18, ta=0.15, cm=0.15),
                trace_time=dict(d=0, clu=3, clg=3, of=3, ta=3, cm=4),
                capacity=None,
            ),
        },
        "P1_guarded": {
            "rank": 1,
            "summary": "Low-cost guarded posture with stronger screening and tracing plus mild public-space restrictions while keeping in-person teaching normal.",
            "restriction_intensity": 1,
            "online_teaching_active": False,
            "restriction_profile": dict(d=1.00, clu=1.00, clg=1.00, of=1.00, ta=1.00, cm=0.85),
            "testing_profile": dict(symp_prob=0.10, asymp_prob=0.002, symp_quar_prob=0.35, asymp_quar_prob=0.01),
            "screening_profile": dict(
                daily_capacity_ratio=0.02,
                group_cycles=dict(teacher=5, lab=5, dorm=10, course=14, id_bucket=21),
                exclude_recent_days=3,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=0.90, clu=0.35, clg=0.35, of=0.30, ta=0.20, cm=0.25),
                trace_time=dict(d=0, clu=1, clg=1, of=1, ta=1, cm=2),
                capacity=None,
            ),
        },
        "P2_moderate": {
            "rank": 2,
            "summary": "Medium-cost posture with higher screening cadence, strong tracing, and reduced classroom, lab, and office intensity while staying mostly in person.",
            "restriction_intensity": 2,
            "online_teaching_active": False,
            "restriction_profile": dict(d=1.05, clu=0.85, clg=0.85, of=0.65, ta=0.75, cm=0.70),
            "testing_profile": dict(symp_prob=0.14, asymp_prob=0.006, symp_quar_prob=0.50, asymp_quar_prob=0.03),
            "screening_profile": dict(
                daily_capacity_ratio=0.04,
                group_cycles=dict(teacher=3, lab=3, dorm=5, course=7, id_bucket=10),
                exclude_recent_days=2,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=0.95, clu=0.45, clg=0.45, of=0.40, ta=0.30, cm=0.35),
                trace_time=dict(d=0, clu=1, clg=1, of=1, ta=1, cm=2),
                capacity=None,
            ),
        },
        "P3_strong": {
            "rank": 3,
            "summary": "High-cost strong-control posture with hybrid-like contact reduction, elevated screening, and strict campus restrictions to counter clearly worsening spread.",
            "restriction_intensity": 3,
            "online_teaching_active": False,
            "restriction_profile": dict(d=1.02, clu=0.62, clg=0.62, of=0.45, ta=0.58, cm=0.50),
            "testing_profile": dict(symp_prob=0.18, asymp_prob=0.009, symp_quar_prob=0.65, asymp_quar_prob=0.05),
            "screening_profile": dict(
                daily_capacity_ratio=0.06,
                group_cycles=dict(teacher=2, lab=2, dorm=4, course=5, id_bucket=7),
                exclude_recent_days=1,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=0.98, clu=0.62, clg=0.62, of=0.55, ta=0.42, cm=0.48),
                trace_time=dict(d=0, clu=1, clg=1, of=1, ta=1, cm=1),
                capacity=None,
            ),
        },
        "P4_emergency": {
            "rank": 4,
            "summary": "Highest-cost emergency posture with online teaching, campus-wide high-frequency screening, and maximum restrictions for severe uncontrolled spread.",
            "restriction_intensity": 4,
            "online_teaching_active": True,
            "restriction_profile": dict(d=1.10, clu=0.00, clg=0.00, of=0.20, ta=0.35, cm=0.30),
            "testing_profile": dict(symp_prob=0.22, asymp_prob=0.012, symp_quar_prob=0.80, asymp_quar_prob=0.08),
            "screening_profile": dict(
                daily_capacity_ratio=0.10,
                group_cycles=dict(teacher=1, lab=1, dorm=2, course=3, id_bucket=4),
                exclude_recent_days=0,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=1.00, clu=0.80, clg=0.80, of=0.70, ta=0.50, cm=0.55),
                trace_time=dict(d=0, clu=0, clg=0, of=0, ta=1, cm=1),
                capacity=None,
            ),
        },
    }


def get_policy_rank(policy_id, policy_catalog=None):
    """Return the ordinal rank of a policy."""
    catalog = policy_catalog if policy_catalog is not None else make_default_policy_catalog()
    return catalog[policy_id]["rank"]


def get_policy_by_rank(rank, policy_catalog=None):
    """Return the policy ID for a rank."""
    catalog = policy_catalog if policy_catalog is not None else make_default_policy_catalog()
    for policy_id, profile in catalog.items():
        if profile["rank"] == rank:
            return policy_id
    raise KeyError(f"No policy with rank {rank}")


def apply_policy_transition_constraint(proposed_policy_id, current_policy_id, policy_catalog=None):
    """
    Apply asymmetric transition constraint: upgrades are unrestricted, downgrades step one level at a time.
    """
    catalog = policy_catalog if policy_catalog is not None else make_default_policy_catalog()
    if current_policy_id is None:
        return proposed_policy_id
    current_rank = get_policy_rank(current_policy_id, catalog)
    proposed_rank = get_policy_rank(proposed_policy_id, catalog)
    if proposed_rank <= current_rank:
        clipped_rank = max(proposed_rank, current_rank - 1)
    else:
        clipped_rank = proposed_rank
    return get_policy_by_rank(clipped_rank, catalog)


def build_system_prompt(use_theory_prompt=True):
    """Build the fixed system prompt for policy classification."""
    prompt = (
        "You are a campus epidemic prevention and control expert. "
        "Your task is to choose exactly one next-period policy based on the aggregated campus state. "
        "You may only choose one of these policy_id values: "
        "P0_normal, P1_guarded, P2_moderate, P3_strong, P4_emergency. "
        "Do not create new policies. Do not modify policy parameters. "
        "Do not output any low-level transmission parameters. "
        "Do not give real-world medical advice. "
        "You are only selecting the next simulation policy. "
        "Output must be strict JSON containing exactly three fields: policy_id, risk_level, reason. "
        "policy_id must be one of the five fixed policies. "
        "risk_level must be one of low, medium, high, critical. "
        "reason must be a short Chinese sentence within 40 characters. "
        "Key data fields in the state you receive: "
        "growth_ratio_7d_vs_prev_7d is the ratio of new infections in the past 7 days versus the previous 7 days. "
        "Above 1.0 means the epidemic is growing week-over-week; below 1.0 means it is shrinking. "
        "new_infections_per_1000_last_7d is the weekly new infections per 1000 population. "
        "new_infections_trend is the direction label (up/down/flat) comparing the past 7 days to the previous 7 days. "
        "estimated_risk_trend is the overall risk direction (improving/stable/worsening). "
        "layer_transmission_trends are per-layer trend labels showing which contact layers are rising or falling. "
        "recent_policy_memory is the history of recent policy changes and their observed effects."
        "short_term_trajectory_summary describes recent policy evolution, infection trend, growth ratio, and the observed feedback pattern after the latest policy adjustment."
        "similar_scenarios_summary describes historical situations with similar epidemic states, grouped by the policy that was executed, showing the observed outcomes for each policy choice."
    )
    if use_theory_prompt:
        prompt += " Use these short systems rules when deciding: " + " ".join(SYSTEM_KNOWLEDGE_RULES)
    return prompt


def build_user_payload(state, policy_catalog):
    """Build the user payload for LLM policy selection.

    Strips full structured memory data (short_term_trajectory, similar_scenarios)
    and replaces them with their summary_text versions to control token count.
    Internal fields (prefixed with _) are also removed.
    """
    # Keys to exclude from LLM payload
    _EXCLUDE_KEYS = {"short_term_trajectory", "similar_scenarios", "_scaled_pop"}

    llm_state = {k: v for k, v in state.items() if k not in _EXCLUDE_KEYS and not k.startswith("_")}

    # Inject summary texts if available
    trajectory = state.get("short_term_trajectory")
    if trajectory and isinstance(trajectory, dict):
        summary = trajectory.get("summary_text", "")
        if summary:
            llm_state["short_term_trajectory_summary"] = summary

    scenarios = state.get("similar_scenarios")
    if scenarios and isinstance(scenarios, dict):
        summary = scenarios.get("summary_text", "")
        if summary:
            llm_state["similar_scenarios_summary"] = summary

    return {
        "task": "Choose exactly one next-period policy_id from the predefined campus policy catalog.",
        "state": llm_state,
        "policy_catalog_brief": policy_catalog_to_brief(policy_catalog),
        "output_schema": {
            "policy_id": "P0_normal | P1_guarded | P2_moderate | P3_strong | P4_emergency",
            "risk_level": "low | medium | high | critical",
            "reason": "short Chinese reason, <=40 chars",
        },
    }


def build_full_state_snapshot(state):
    """Return a deep copy of the full state for record keeping (includes memory data)."""
    import copy
    return copy.deepcopy(state)


def policy_catalog_to_brief(policy_catalog):
    """Return a compact catalog without runtime parameters."""
    brief = []
    for policy_id in POLICY_IDS:
        profile = policy_catalog[policy_id]
        brief.append({
            "policy_id": policy_id,
            "summary": profile["summary"],
            "online_teaching_active": profile["online_teaching_active"],
            "restriction_intensity": profile["restriction_intensity"],
        })
    return brief


def build_chat_messages(state, policy_catalog, use_theory_prompt=True):
    """Build chat completion messages for the policy call."""
    return [
        {"role": "system", "content": build_system_prompt(use_theory_prompt=use_theory_prompt)},
        {"role": "user", "content": json.dumps(build_user_payload(state, policy_catalog), ensure_ascii=False, indent=2)},
    ]


def hash_text(text):
    """Return the SHA256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_json_object(raw_text):
    """Extract a JSON object from raw model text, with repair for truncated output."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise PolicyResponseError("Model response was empty.")
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            raise PolicyResponseError("No JSON object found in model response.")
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try to fix truncated JSON by balancing braces
            open_braces = candidate.count("{") - candidate.count("}")
            if open_braces > 0:
                candidate += "}" * open_braces
            open_brackets = candidate.count("[") - candidate.count("]")
            if open_brackets > 0:
                candidate += "]" * open_brackets
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise PolicyResponseError(f"Invalid JSON in model response: {exc}") from exc


def _validate_reason_text(reason, reason_max_chars):
    """Validate and normalize the reason field.

    The policy id and risk level are the safety-critical fields. The reason is
    an audit string, so only enforce the configured length limit.
    """
    if not isinstance(reason, str):
        raise PolicyResponseError('Field "reason" must be a string.')
    reason = reason.strip()
    if len(reason) > int(reason_max_chars):
        reason = reason[: int(reason_max_chars)].strip()
    return reason


def parse_policy_response(raw_text, reason_max_chars=DEFAULT_REASON_MAX_CHARS):
    """
    Parse and validate a model response.
    """
    data = _extract_json_object(raw_text)
    if not isinstance(data, dict):
        raise PolicyResponseError("Model response must decode to a JSON object.")

    required_keys = {"policy_id", "risk_level", "reason"}
    actual_keys = set(data.keys())
    missing = required_keys - actual_keys
    extra = actual_keys - required_keys
    if missing:
        raise PolicyResponseError(f"Missing required fields: {sorted(missing)}")
    if extra:
        raise PolicyResponseError(f"Unexpected fields in model response: {sorted(extra)}")

    policy_id = data["policy_id"]
    risk_level = data["risk_level"]
    reason = _validate_reason_text(data["reason"], reason_max_chars)

    if policy_id not in POLICY_IDS:
        raise PolicyResponseError(f"Invalid policy_id: {policy_id}")
    if risk_level not in RISK_LEVELS:
        raise PolicyResponseError(f"Invalid risk_level: {risk_level}")

    return {
        "policy_id": policy_id,
        "risk_level": risk_level,
        "reason": reason,
    }


def extract_campus_policy_state(sim, agent=None, decision_day=None, window=7):
    """
    Extract aggregate policy state from simulation results.
    """
    decision_day = sim.t if decision_day is None else int(decision_day)
    end_day = min(max(decision_day - 1, -1), sim.npts - 1)
    current_policy = getattr(agent, "current_policy", None)
    current_policy_start_day = getattr(agent, "current_policy_start_day", decision_day)
    policy_catalog = getattr(agent, "policy_catalog", make_default_policy_catalog())
    memory_weeks = int(getattr(agent, "memory_weeks", DEFAULT_MEMORY_WEEKS))
    decision_history = getattr(agent, "decision_history", None)

    new_infections = _result_values(sim, "new_infections")
    new_diagnoses = _result_values(sim, "new_diagnoses")
    new_tests = _result_values(sim, "new_tests")
    n_quarantined = _result_values(sim, "n_quarantined")

    inf_window, inf_prev = _window_pair(new_infections, end_day, window)
    diag_window, diag_prev = _window_pair(new_diagnoses, end_day, window)
    test_window, _ = _window_pair(new_tests, end_day, window)
    quar_window, quar_prev = _window_pair(n_quarantined, end_day, window)

    new_infections_sum = float(inf_window.sum())
    new_diagnoses_sum = float(diag_window.sum())
    new_tests_sum = float(test_window.sum())
    growth_ratio = _growth_ratio(inf_window, inf_prev)
    layer_counts = _extract_layer_transmissions(sim, end_day=end_day, window=window)
    scaled_pop_size = getattr(sim, "scaled_pop_size", None) or sim["pop_size"]

    state = {
        "decision_day": decision_day,
        "decision_date": sim.date(decision_day),
        "current_policy": current_policy,
        "current_policy_duration_days": max(1, decision_day - int(current_policy_start_day)) if current_policy is not None else 0,
        "past_7d_summary": {
            "new_infections_sum": round(new_infections_sum, 4),
            "new_infections_mean": round(float(inf_window.mean()) if len(inf_window) else 0.0, 4),
            "new_infections_trend": _trend_label(inf_window, inf_prev),
            "new_diagnoses_sum": round(new_diagnoses_sum, 4),
            "new_diagnoses_mean": round(float(diag_window.mean()) if len(diag_window) else 0.0, 4),
            "new_diagnoses_trend": _trend_label(diag_window, diag_prev),
            "new_tests_sum": round(new_tests_sum, 4),
            "test_positivity_proxy": round(_safe_ratio(new_diagnoses_sum, new_tests_sum), 6),
            "n_quarantined_mean": round(float(quar_window.mean()) if len(quar_window) else 0.0, 4),
            "quarantine_trend": _trend_label(quar_window, quar_prev),
            "estimated_risk_trend": _estimated_risk_trend(inf_window, inf_prev, growth_ratio),
        },
        "new_infections_per_1000_last_7d": round(_safe_ratio(new_infections_sum * 1000.0, scaled_pop_size), 6),
        "diagnosis_ascertainment_proxy": round(_safe_ratio(new_diagnoses_sum, new_infections_sum), 6),
        "online_teaching_active": bool(policy_catalog.get(current_policy, {}).get("online_teaching_active", False)) if current_policy else False,
        "current_restriction_intensity": policy_catalog.get(current_policy, {}).get("restriction_intensity", 0) if current_policy else 0,
        "growth_ratio_7d_vs_prev_7d": round(growth_ratio, 6),
        "intervention_burden_last_7d": {
            "mean_quarantined": round(float(quar_window.mean()) if len(quar_window) else 0.0, 4),
            "mean_quarantined_per_1000": round(_safe_ratio((float(quar_window.mean()) if len(quar_window) else 0.0) * 1000.0, scaled_pop_size), 6),
            "tests_sum": round(new_tests_sum, 4),
            "tests_per_1000": round(_safe_ratio(new_tests_sum * 1000.0, scaled_pop_size), 6),
            "teaching_restriction_intensity": policy_catalog.get(current_policy, {}).get("restriction_intensity", 0) if current_policy else 0,
            "online_teaching_active": bool(policy_catalog.get(current_policy, {}).get("online_teaching_active", False)) if current_policy else False,
        },
    }

    # r_eff realtime fields
    r_eff_info = _extract_r_eff_realtime(sim, end_day, window)
    state["r_eff_mean"] = r_eff_info["r_eff_mean"]
    state["r_eff_current"] = r_eff_info["r_eff_current"]
    state["r_eff_trend"] = r_eff_info["r_eff_trend"]
    state["r_eff_source"] = r_eff_info["source"]
    state["past_7d_summary"]["r_eff_current"] = r_eff_info["r_eff_mean"]

    if layer_counts is not None:
        state["layer_transmission_last_7d"] = layer_counts
        state["peak_layer_last_7d"] = max(layer_counts, key=layer_counts.get) if layer_counts else None
        state["layer_transmission_trends"] = _build_layer_transmission_trends(sim, end_day=end_day, window=window)

    recent_policy_memory = _build_recent_policy_memory(
        sim=sim,
        decision_history=decision_history,
        decision_day=decision_day,
        memory_weeks=memory_weeks,
        policy_catalog=policy_catalog,
    )
    state["recent_policy_memory"] = recent_policy_memory
    state["policy_effect_summary"] = _summarize_policy_effects(recent_policy_memory)
    state["policy_volatility_last_4w"] = _compute_policy_volatility(recent_policy_memory, policy_catalog)

    # Internal field for memory vector builders (not sent to LLM)
    state["_scaled_pop"] = scaled_pop_size

    return state


def append_jsonl_record(path, record):
    """Append a JSON record to a JSONL log file."""
    if path is None:
        return
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def summarize_policy_decision(decision_record):
    """Return a short human-readable summary."""
    if decision_record.get("fallback_used"):
        return f"[day {decision_record['decision_day']}] fallback -> {decision_record['applied_policy']}"
    proposed = decision_record.get("model_policy_proposed")
    applied = decision_record.get("applied_policy")
    return f"[day {decision_record['decision_day']}] {proposed} -> {applied}"


class PolicyClient:
    """
    Provider-neutral client for an OpenAI-compatible Chat Completions API.

    Generic ``LLM_*`` environment variables take precedence over the legacy
    ``DASHSCOPE_*`` names so existing experiments remain reproducible.
    """

    def __init__(self, api_key=None, base_url=None, model=None,
                 temperature=DEFAULT_TEMPERATURE, max_tokens=DEFAULT_MAX_TOKENS):
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("DASHSCOPE_BASE_URL")
            or DEFAULT_LLM_BASE_URL
        )
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise PolicyDecisionError(
                    "Environment variable LLM_API_KEY is not set "
                    "(legacy DASHSCOPE_API_KEY is also supported)."
                )
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise PolicyDecisionError('The "openai" package is required for LLM policy decisions.') from exc
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def decide_policy(self, state, policy_catalog, use_theory_prompt=True, max_retries=3):
        """
        Request a policy decision and return parsed metadata.
        Retries on transient failures (empty response, rate limiting).
        """
        system_prompt = build_system_prompt(use_theory_prompt=use_theory_prompt)
        user_payload = build_user_payload(state, policy_catalog)
        messages = build_chat_messages(state, policy_catalog, use_theory_prompt=use_theory_prompt)

        last_exc = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                import sys, random
                delay = 2.0 * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
                print(f"[DEBUG API] retry {attempt}/{max_retries} after {delay:.1f}s: {last_exc}", file=sys.stderr)
                time.sleep(delay)
            else:
                # Small jitter before first call to avoid thundering herd
                import random as _random
                time.sleep(_random.uniform(0.05, 0.5))
            try:
                return self._call_api(messages, system_prompt, user_payload)
            except PolicyResponseError as exc:
                last_exc = exc
            except Exception as exc:
                last_exc = exc
        raise PolicyResponseError(str(last_exc)) from last_exc

    def _call_api(self, messages, system_prompt, user_payload):
        """Single API call attempt."""
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            import sys
            print(f"[DEBUG API] empty choices, full response: {response}", file=sys.stderr)
            raise PolicyResponseError("Model response did not contain any choices.")

        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "content_filter":
            raise PolicyResponseError("Model response was blocked by a safety filter.")
        if finish_reason not in (None, "stop", "length"):
            raise PolicyResponseError(f"Unexpected finish_reason: {finish_reason}")

        message = getattr(choice, "message", None)
        raw_text = getattr(message, "content", None) if message is not None else None
        if isinstance(raw_text, list):
            raw_text = "".join(part.get("text", "") for part in raw_text if isinstance(part, dict))
        if not raw_text:
            import sys
            print(f"[DEBUG API] empty content, finish_reason={finish_reason}, message={message}", file=sys.stderr)

        decision = parse_policy_response(raw_text)
        usage = {}
        if getattr(response, "usage", None) is not None:
            usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage)
        return {
            "decision": decision,
            "raw_response_text": raw_text,
            "usage": usage,
            "system_prompt": system_prompt,
            "system_prompt_sha256": hash_text(system_prompt),
            "user_payload": user_payload,
            "model_name": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "finish_reason": finish_reason,
        }


# Compatibility alias for code created before the provider-neutral rename.
QwenPolicyClient = PolicyClient


def compute_policy_oscillation_score(policy_ids, policy_catalog=None):
    """Estimate how unstable a policy sequence is by counting reversal patterns."""
    catalog = policy_catalog if policy_catalog is not None else make_default_policy_catalog()
    ranks = [get_policy_rank(policy_id, catalog) for policy_id in policy_ids if policy_id in catalog]
    if len(ranks) < 3:
        return 0.0
    score = 0.0
    for idx in range(2, len(ranks)):
        prev_delta = ranks[idx - 1] - ranks[idx - 2]
        curr_delta = ranks[idx] - ranks[idx - 1]
        if prev_delta == 0 or curr_delta == 0:
            continue
        if prev_delta * curr_delta < 0:
            score += abs(prev_delta) + abs(curr_delta)
    return float(score)


def add_balanced_utility_metrics(agg_df, cpbu_weights=None, per_cost_weights=None):
    """
    Add multi-objective policy utility metrics to an aggregated benchmark dataframe.

    Required columns:
        scenario, strategy, cum_infections_mean, cum_tests_mean,
        mean_quarantined_mean, teaching_restriction_days_mean,
        policy_switch_count_mean, policy_oscillation_score_mean
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError('Balanced utility metrics require pandas.') from exc

    if agg_df is None or len(agg_df) == 0:
        return pd.DataFrame([] if agg_df is None else agg_df)

    cpbu_weights = dict(DEFAULT_CPBU_WEIGHTS if cpbu_weights is None else cpbu_weights)
    per_cost_weights = dict(DEFAULT_PER_COST_WEIGHTS if per_cost_weights is None else per_cost_weights)

    rows = []
    for scenario, group in agg_df.groupby("scenario", sort=False):
        scenario_df = group.copy()
        max_inf = max(1.0, float(scenario_df["cum_infections_mean"].max()))
        max_tests = max(1.0, float(scenario_df["cum_tests_mean"].max()))
        max_quar = max(1.0, float(scenario_df["mean_quarantined_mean"].max()))
        max_teach = max(1.0, float(scenario_df["teaching_restriction_days_mean"].max()))
        max_switch = max(1.0, float(scenario_df["policy_switch_count_mean"].max()))
        max_osc = max(1.0, float(scenario_df["policy_oscillation_score_mean"].max()))
        no_policy_inf = float(
            scenario_df.loc[scenario_df["strategy"] == "baseline_no_policy", "cum_infections_mean"].iloc[0]
        )

        for _, row in scenario_df.iterrows():
            j_inf = float(row["cum_infections_mean"]) / max_inf
            j_ops = 0.5 * (float(row["cum_tests_mean"]) / max_tests) + 0.5 * (float(row["mean_quarantined_mean"]) / max_quar)
            j_teach = float(row["teaching_restriction_days_mean"]) / max_teach if max_teach > 0 else 0.0
            j_stab = 0.5 * (float(row["policy_switch_count_mean"]) / max_switch) + 0.5 * (
                float(row["policy_oscillation_score_mean"]) / max_osc if max_osc > 0 else 0.0
            )
            cpbu_cost = (
                cpbu_weights["infection"] * j_inf
                + cpbu_weights["ops"] * j_ops
                + cpbu_weights["teaching"] * j_teach
                + cpbu_weights["stability"] * j_stab
            )
            infections_avoided = max(0.0, no_policy_inf - float(row["cum_infections_mean"]))
            weighted_policy_cost = (
                per_cost_weights["cum_tests"] * float(row["cum_tests_mean"])
                + per_cost_weights["mean_quarantined"] * float(row["mean_quarantined_mean"])
                + per_cost_weights["teaching_restriction_days"] * float(row["teaching_restriction_days_mean"])
                + per_cost_weights["policy_switch_count"] * float(row["policy_switch_count_mean"])
            )
            enriched = row.to_dict()
            enriched.update({
                "J_inf": float(j_inf),
                "J_ops": float(j_ops),
                "J_teach": float(j_teach),
                "J_stab": float(j_stab),
                "CPBU": float(1.0 - cpbu_cost),
                "PER": float(infections_avoided / max(1.0, weighted_policy_cost)),
                "infections_avoided_vs_no_policy": float(infections_avoided),
                "weighted_policy_cost": float(weighted_policy_cost),
            })
            rows.append(enriched)
    return pd.DataFrame(rows).sort_values(["scenario", "strategy"]).reset_index(drop=True)


def build_policy_benchmark_ranking(agg_df):
    """Build a lightweight ranking table for multi-objective campus policy comparison."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError('Balanced utility metrics require pandas.') from exc

    if agg_df is None or len(agg_df) == 0:
        return pd.DataFrame([] if agg_df is None else agg_df)

    records = []
    for _, row in agg_df.iterrows():
        normalized_composite_score = (
            row["cum_infections_mean"] / max(1.0, agg_df["cum_infections_mean"].max())
            + row["mean_quarantined_mean"] / max(1.0, agg_df["mean_quarantined_mean"].max())
            + row["cum_tests_mean"] / max(1.0, agg_df["cum_tests_mean"].max())
            + row["policy_oscillation_score_mean"] / max(1.0, agg_df["policy_oscillation_score_mean"].max())
        )
        records.append({
            "scenario": row["scenario"],
            "strategy": row["strategy"],
            "normalized_composite_score": float(normalized_composite_score),
            "CPBU": float(row.get("CPBU", np.nan)),
            "PER": float(row.get("PER", np.nan)),
        })
    return pd.DataFrame(records).sort_values(["scenario", "CPBU", "PER"], ascending=[True, False, False]).reset_index(drop=True)


def aggregate_policy_benchmark_runs(run_df):
    """
    Aggregate per-run benchmark outputs into per-scenario/per-strategy mean and variance rows.

    Required columns:
        scenario, strategy, seed
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError('Policy benchmark aggregation requires pandas.') from exc

    if run_df is None or len(run_df) == 0:
        return pd.DataFrame([] if run_df is None else run_df)

    metric_cols = [col for col in run_df.columns if col not in {"scenario", "strategy", "seed"}]
    rows = []
    for (scenario, strategy), group in run_df.groupby(["scenario", "strategy"]):
        row = {"scenario": scenario, "strategy": strategy, "n_runs": int(len(group))}
        for col in metric_cols:
            row[f"{col}_mean"] = float(group[col].mean())
            row[f"{col}_var"] = float(group[col].var(ddof=0))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["scenario", "strategy"]).reset_index(drop=True)


def evaluate_policy_benchmark(run_df, cpbu_weights=None, per_cost_weights=None):
    """
    One-stop evaluation helper for campus policy benchmarks.

    Args:
        run_df: per-run dataframe with one row per simulation seed.
        cpbu_weights: optional override for CPBU component weights.
        per_cost_weights: optional override for PER cost weights.

    Returns:
        dict with:
            - run_df
            - aggregate_df
            - ranking_df
            - cpbu_weights
            - per_cost_weights
    """
    aggregated = aggregate_policy_benchmark_runs(run_df)
    aggregate_df = add_balanced_utility_metrics(
        aggregated,
        cpbu_weights=cpbu_weights,
        per_cost_weights=per_cost_weights,
    )
    ranking_df = build_policy_benchmark_ranking(aggregate_df)
    return {
        "run_df": run_df,
        "aggregate_df": aggregate_df,
        "ranking_df": ranking_df,
        "cpbu_weights": dict(DEFAULT_CPBU_WEIGHTS if cpbu_weights is None else cpbu_weights),
        "per_cost_weights": dict(DEFAULT_PER_COST_WEIGHTS if per_cost_weights is None else per_cost_weights),
    }


def evaluate_cpbu_weight_sensitivity(agg_df, cpbu_weights=None):
    """
    Evaluate CPBU sensitivity to weight perturbations.

    For each weight component (infection, ops, teaching, stability), applies
    +/-20% perturbations while keeping other weights proportional, then
    recomputes CPBU for every strategy. Also includes a combined perturbation
    and an infection-dominant extreme.

    Parameters
    ----------
    agg_df : pandas DataFrame
        Aggregated benchmark dataframe (already containing J_* columns from
        ``add_balanced_utility_metrics``). Must include columns:
        scenario, strategy, J_inf, J_ops, J_teach, J_stab, CPBU.
    cpbu_weights : dict, optional
        Baseline weights. Defaults to DEFAULT_CPBU_WEIGHTS.

    Returns
    -------
    pandas DataFrame with columns:
        weight_variant, scenario, strategy, w_infection, w_ops,
        w_teaching, w_stability, CPBU, delta_vs_baseline
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError("CPBU weight sensitivity requires pandas.") from exc

    if agg_df is None or len(agg_df) == 0:
        return pd.DataFrame()

    base = dict(DEFAULT_CPBU_WEIGHTS if cpbu_weights is None else cpbu_weights)

    # ── build weight variants ──────────────────────────────────────────
    def _make_weights(w_inf, w_ops, w_teach, w_stab):
        total = w_inf + w_ops + w_teach + w_stab
        return {
            "infection": w_inf / total,
            "ops": w_ops / total,
            "teaching": w_teach / total,
            "stability": w_stab / total,
        }

    variants = {}
    variants["W0 默认权重"] = base.copy()

    label_map = {
        "infection": "感染",
        "ops": "运营负担",
        "teaching": "教学中断",
        "stability": "策略稳定",
    }

    for key, base_val in base.items():
        for pct, direction in [(1.20, "+20%"), (0.80, "-20%")]:
            new_val = base_val * pct
            others_sum = sum(v for k, v in base.items() if k != key)
            new_others_sum = 1.0 - new_val
            w = {}
            for k in base:
                if k == key:
                    w[k] = new_val
                else:
                    w[k] = new_others_sum * base[k] / others_sum
            variants[f"W{len(variants)} {label_map[key]} {direction}"] = w

    # Combined: infection +20%, teaching -20%, stability +20%
    variants[f"W{len(variants)} 感染+20% & 教学-20% & 稳定+20%"] = _make_weights(
        base["infection"] * 1.20, base["ops"], base["teaching"] * 0.80, base["stability"] * 1.20
    )
    # Extreme: infection-dominant
    variants[f"W{len(variants)} 感染主导 (w_inf=0.60, w_teach=0.05)"] = _make_weights(
        0.60, base["ops"], 0.05, base["stability"]
    )

    # ── recompute CPBU under each variant ──────────────────────────────
    required = {"scenario", "strategy", "J_inf", "J_ops", "J_teach", "J_stab"}
    missing = required - set(agg_df.columns)
    if missing:
        raise KeyError(f"Aggregated dataframe missing columns: {missing}")

    records = []
    for vname, w in variants.items():
        for _, row in agg_df.iterrows():
            cpbu_cost = (
                w["infection"] * float(row["J_inf"])
                + w["ops"] * float(row["J_ops"])
                + w["teaching"] * float(row["J_teach"])
                + w["stability"] * float(row["J_stab"])
            )
            new_cpbu = float(1.0 - cpbu_cost)
            records.append({
                "weight_variant": vname,
                "scenario": row["scenario"],
                "strategy": row["strategy"],
                "w_infection": round(w["infection"], 4),
                "w_ops": round(w["ops"], 4),
                "w_teaching": round(w["teaching"], 4),
                "w_stability": round(w["stability"], 4),
                "CPBU": round(new_cpbu, 4),
                "delta_vs_baseline": round(new_cpbu - float(row.get("CPBU", new_cpbu)), 4),
            })

    return pd.DataFrame(records)


def _result_values(sim, key):
    result = sim.results.get(key, None)
    if result is None:
        return np.array([], dtype=float)
    values = getattr(result, "values", result)
    return np.asarray(values, dtype=float)


def _window_pair(values, end_day, window):
    if end_day < 0 or values.size == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    end = min(int(end_day), values.size - 1)
    start = max(0, end - int(window) + 1)
    current = values[start:end + 1]
    prev_end = start - 1
    prev_start = max(0, prev_end - int(window) + 1)
    previous = values[prev_start:prev_end + 1] if prev_end >= 0 else np.array([], dtype=float)
    return current, previous


def _trend_label(current, previous, tolerance=0.05):
    if len(current) == 0:
        return "flat"
    if len(previous) == 0:
        if float(current.sum()) <= 0:
            return "flat"
        return "up"
    current_sum = float(current.sum())
    previous_sum = float(previous.sum())
    if previous_sum <= 0:
        return "up" if current_sum > 0 else "flat"
    relative_change = (current_sum - previous_sum) / previous_sum
    if relative_change > tolerance:
        return "up"
    if relative_change < -tolerance:
        return "down"
    return "flat"


def _estimated_risk_trend(inf_window, inf_prev, growth_ratio):
    trend = _trend_label(inf_window, inf_prev)
    if trend == "up":
        return "worsening"
    if trend == "down" and growth_ratio < 1.0:
        return "improving"
    if trend == "flat" and growth_ratio > 1.0:
        return "worsening"
    return "stable"


def _growth_ratio(current, previous):
    current_sum = float(current.sum()) if len(current) else 0.0
    previous_sum = float(previous.sum()) if len(previous) else 0.0
    if previous_sum <= 0:
        return 0.0 if current_sum <= 0 else 1.0
    return current_sum / previous_sum


def _safe_ratio(numerator, denominator):
    denominator = float(denominator)
    if denominator <= 0:
        return 0.0
    return float(numerator) / denominator


def _window_finite_mean(values, end_day, window):
    if values.size == 0 or end_day < 0:
        return 0.0
    end = min(int(end_day), values.size - 1)
    start = max(0, end - int(window) + 1)
    window_values = values[start:end + 1]
    finite_values = window_values[np.isfinite(window_values)]
    if finite_values.size == 0:
        return 0.0
    return float(finite_values.mean())


def _extract_r_eff_realtime(sim, end_day, window=7):
    """
    Compute an approximate r_eff during simulation (before compute_results()).

    Uses the same 'daily' formula as sim.compute_r_eff():
        r_eff = mean_infectious_duration * (new_infections - n_imports) / n_infectious

    Data from ``people.date_infectious``, ``date_recovered``, ``date_dead``
    is available at intervention time (set during ``update_states_pre``).

    Falls back to sim.results['r_eff'] if pre-computed values exist (e.g., in tests).
    Falls back to growth_ratio proxy when too few outcomes exist.
    """
    # Fallback: check if sim.results['r_eff'] has pre-computed non-zero values
    r_eff_result = _result_values(sim, "r_eff")
    if r_eff_result.size > 0 and end_day >= 0:
        end = min(int(end_day), r_eff_result.size - 1)
        w_start = max(0, end - int(window) + 1)
        w_slice = r_eff_result[w_start:end + 1]
        if w_slice.size > 0 and float(w_slice.mean()) > 0:
            r_mean = float(w_slice.mean())
            r_current = float(r_eff_result[end])
            half = len(w_slice) // 2
            if half >= 1:
                first_half = float(w_slice[:half].mean())
                second_half = float(w_slice[half:].mean())
                diff = second_half - first_half
                if diff > 0.05:
                    trend = "up"
                elif diff < -0.05:
                    trend = "down"
                else:
                    trend = "flat"
            else:
                trend = "flat"
            return {
                "r_eff_mean": round(r_mean, 4),
                "r_eff_current": round(r_current, 4),
                "r_eff_trend": trend,
                "source": "results",
            }

    people = getattr(sim, "people", None)
    if people is None or end_day < 0:
        return {"r_eff_mean": 0.0, "r_eff_current": 0.0,
                "r_eff_trend": "flat", "source": "unavailable"}

    # --- mean infectious duration from recovered/dead ---
    try:
        recov_inds = people.defined("date_recovered")
        dead_inds = people.defined("date_dead")
        if len(recov_inds) + len(dead_inds) < 5:
            raise ValueError("insufficient outcomes")
        date_outcome = np.concatenate(
            (people.date_recovered[recov_inds], people.date_dead[dead_inds])
        )
        inds = np.concatenate((recov_inds, dead_inds))
        date_inf = people.date_infectious[inds]
        mean_dur = float(date_outcome.mean() - date_inf.mean())
        if mean_dur <= 0:
            raise ValueError("invalid mean duration")
    except Exception:
        return {"r_eff_mean": 0.0, "r_eff_current": 0.0,
                "r_eff_trend": "flat", "source": "unavailable"}

    # --- daily r_eff for [0 .. end_day] ---
    new_inf = _result_values(sim, "new_infections")
    n_imports = _result_values(sim, "n_imports")
    n_inf = _result_values(sim, "n_infectious")

    if new_inf.size == 0 or n_inf.size == 0:
        return {"r_eff_mean": 0.0, "r_eff_current": 0.0,
                "r_eff_trend": "flat", "source": "unavailable"}

    end = min(int(end_day), new_inf.size - 1)
    length = end + 1
    local_inf = new_inf[:length] - n_imports[:length]
    local_ninf = n_inf[:length]
    raw = mean_dur * np.divide(
        local_inf, local_ninf,
        out=np.zeros(length, dtype=float),
        where=local_ninf > 0,
    )

    # simple smoothing (kernel=2) for interior points
    if length >= 3:
        smoothed = np.copy(raw)
        for i in range(1, length - 1):
            smoothed[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0
    else:
        smoothed = raw

    # --- window stats ---
    w_start = max(0, end - int(window) + 1)
    w_slice = smoothed[w_start:end + 1]
    r_mean = float(w_slice.mean()) if len(w_slice) else 0.0
    r_current = float(smoothed[end]) if end >= 0 else 0.0

    # trend: compare first half vs second half of window
    half = len(w_slice) // 2
    if half >= 1:
        first_half = float(w_slice[:half].mean())
        second_half = float(w_slice[half:].mean())
        diff = second_half - first_half
        if diff > 0.05:
            trend = "up"
        elif diff < -0.05:
            trend = "down"
        else:
            trend = "flat"
    else:
        trend = "flat"

    return {
        "r_eff_mean": round(r_mean, 4),
        "r_eff_current": round(r_current, 4),
        "r_eff_trend": trend,
        "source": "realtime",
    }


def _extract_layer_transmissions(sim, end_day, window):
    infection_log = getattr(getattr(sim, "people", None), "infection_log", None)
    if not isinstance(infection_log, list):
        return None
    if end_day < 0:
        return {layer: 0 for layer in CAMPUS_LAYER_KEYS}
    start_day = max(0, end_day - int(window) + 1)
    counts = {layer: 0 for layer in CAMPUS_LAYER_KEYS}
    try:
        for entry in infection_log:
            day = int(entry.get("date", -1))
            layer = entry.get("layer")
            if start_day <= day <= end_day and layer in counts:
                counts[layer] += 1
    except Exception:
        return None
    return counts


def _build_layer_transmission_trends(sim, end_day, window):
    current_counts = _extract_layer_transmissions(sim, end_day=end_day, window=window)
    if current_counts is None:
        return None
    previous_counts = _extract_layer_transmissions(sim, end_day=end_day - int(window), window=window)
    if previous_counts is None:
        previous_counts = {layer: 0 for layer in CAMPUS_LAYER_KEYS}

    layer_map = {
        "dorm": ("d",),
        "classroom": ("clu", "clg"),
        "community": ("cm",),
        "lab": ("of",),
        "office": ("ta",),
    }
    trends = {}
    for label, layers in layer_map.items():
        current = np.array([current_counts.get(layer, 0) for layer in layers], dtype=float)
        previous = np.array([previous_counts.get(layer, 0) for layer in layers], dtype=float)
        current_sum = float(current.sum())
        previous_sum = float(previous.sum())
        trends[label] = {
            "current_7d": round(current_sum, 4),
            "prev_7d": round(previous_sum, 4),
            "delta": round(current_sum - previous_sum, 4),
            "ratio": round(_growth_ratio(current, previous), 6),
            "trend": _trend_label(current, previous),
        }
    return trends


def _build_recent_policy_memory(sim, decision_history, decision_day, memory_weeks, policy_catalog):
    if not isinstance(decision_history, list) or memory_weeks <= 0:
        return []

    records = [record for record in decision_history if isinstance(record, dict) and int(record.get("decision_day", -1)) < int(decision_day)]
    if not records:
        return []
    records = records[-int(memory_weeks):]
    memory = []
    for idx, record in enumerate(records):
        state_snapshot = record.get("state_snapshot", {}) if isinstance(record.get("state_snapshot"), dict) else {}
        next_day = decision_day
        if idx + 1 < len(records):
            next_day = int(records[idx + 1].get("decision_day", decision_day))
        effect_window = _compute_effect_window(
            sim=sim,
            start_day=int(record.get("decision_day", -1)),
            end_day=min(int(next_day) - 1, int(decision_day) - 1),
            policy_catalog=policy_catalog,
            applied_policy=record.get("applied_policy"),
        )
        memory.append({
            "decision_day": int(record.get("decision_day", -1)),
            "decision_date": record.get("decision_date"),
            "state_summary": {
                "new_infections_sum": state_snapshot.get("past_7d_summary", {}).get("new_infections_sum", 0.0),
                "new_infections_trend": state_snapshot.get("past_7d_summary", {}).get("new_infections_trend", "flat"),
                "growth_ratio_7d_vs_prev_7d": state_snapshot.get("growth_ratio_7d_vs_prev_7d", 0.0),
                "estimated_risk_trend": state_snapshot.get("past_7d_summary", {}).get("estimated_risk_trend", "stable"),
                "peak_layer_last_7d": state_snapshot.get("peak_layer_last_7d"),
                "layer_transmission_trends": state_snapshot.get("layer_transmission_trends", {}),
            },
            "proposed_policy": record.get("model_policy_proposed"),
            "executed_policy": record.get("applied_policy"),
            "risk_level": record.get("risk_level"),
            "execution_feedback": effect_window,
        })
    return memory


def _compute_effect_window(sim, start_day, end_day, policy_catalog, applied_policy):
    if end_day < start_day:
        profile = policy_catalog.get(applied_policy, {}) if isinstance(policy_catalog, dict) else {}
        return {
            "days_observed": 0,
            "infection_change_7d": 0.0,
            "tests_sum": 0.0,
            "mean_quarantined": 0.0,
            "teaching_restriction_intensity": profile.get("restriction_intensity", 0),
            "online_teaching_active": bool(profile.get("online_teaching_active", False)),
        }

    new_infections = _result_values(sim, "new_infections")
    new_tests = _result_values(sim, "new_tests")
    n_quarantined = _result_values(sim, "n_quarantined")
    start = max(0, min(int(start_day), new_infections.size - 1 if new_infections.size else 0))
    end = max(start, min(int(end_day), new_infections.size - 1 if new_infections.size else start))
    infections_window = new_infections[start:end + 1] if new_infections.size else np.array([], dtype=float)
    tests_window = new_tests[start:end + 1] if new_tests.size else np.array([], dtype=float)
    quarantined_window = n_quarantined[start:end + 1] if n_quarantined.size else np.array([], dtype=float)
    lookback_start = max(0, start - len(infections_window))
    previous_window = new_infections[lookback_start:start] if new_infections.size and start > 0 else np.array([], dtype=float)
    profile = policy_catalog.get(applied_policy, {}) if isinstance(policy_catalog, dict) else {}
    current_sum = float(infections_window.sum()) if len(infections_window) else 0.0
    previous_sum = float(previous_window.sum()) if len(previous_window) else 0.0
    return {
        "days_observed": int(max(0, end - start + 1)),
        "infection_change_7d": round(current_sum - previous_sum, 4),
        "infection_trend": _trend_label(infections_window, previous_window),
        "tests_sum": round(float(tests_window.sum()) if len(tests_window) else 0.0, 4),
        "mean_quarantined": round(float(quarantined_window.mean()) if len(quarantined_window) else 0.0, 4),
        "teaching_restriction_intensity": profile.get("restriction_intensity", 0),
        "online_teaching_active": bool(profile.get("online_teaching_active", False)),
    }


def _summarize_policy_effects(recent_policy_memory):
    if not recent_policy_memory:
        return {
            "memory_count": 0,
            "recency_weighted_infection_change": 0.0,
            "recency_weighted_tests": 0.0,
            "recency_weighted_quarantine": 0.0,
            "dominant_effect_trend": "stable",
        }
    weights = np.arange(1, len(recent_policy_memory) + 1, dtype=float)
    inf_changes = np.array([item.get("execution_feedback", {}).get("infection_change_7d", 0.0) for item in recent_policy_memory], dtype=float)
    tests = np.array([item.get("execution_feedback", {}).get("tests_sum", 0.0) for item in recent_policy_memory], dtype=float)
    quarantined = np.array([item.get("execution_feedback", {}).get("mean_quarantined", 0.0) for item in recent_policy_memory], dtype=float)
    weighted_change = float(np.average(inf_changes, weights=weights)) if len(inf_changes) else 0.0
    if weighted_change > 1.0:
        trend = "worsening"
    elif weighted_change < -1.0:
        trend = "improving"
    else:
        trend = "stable"
    return {
        "memory_count": len(recent_policy_memory),
        "recency_weighted_infection_change": round(weighted_change, 4),
        "recency_weighted_tests": round(float(np.average(tests, weights=weights)) if len(tests) else 0.0, 4),
        "recency_weighted_quarantine": round(float(np.average(quarantined, weights=weights)) if len(quarantined) else 0.0, 4),
        "dominant_effect_trend": trend,
    }


def _compute_policy_volatility(recent_policy_memory, policy_catalog):
    policy_ids = [item.get("executed_policy") for item in recent_policy_memory if item.get("executed_policy") in policy_catalog]
    if not policy_ids:
        return {
            "memory_count": 0,
            "policy_switch_count": 0,
            "policy_rank_span": 0,
            "policy_oscillation_score": 0.0,
            "volatility_label": "stable",
        }
    ranks = [get_policy_rank(policy_id, policy_catalog) for policy_id in policy_ids]
    switch_count = sum(int(policy_ids[idx] != policy_ids[idx - 1]) for idx in range(1, len(policy_ids)))
    oscillation_score = compute_policy_oscillation_score(policy_ids, policy_catalog=policy_catalog)
    label = "stable"
    if oscillation_score >= 2 or switch_count >= 3:
        label = "high"
    elif switch_count >= 1:
        label = "moderate"
    return {
        "memory_count": len(policy_ids),
        "policy_switch_count": int(switch_count),
        "policy_rank_span": int(max(ranks) - min(ranks)),
        "policy_oscillation_score": round(float(oscillation_score), 4),
        "volatility_label": label,
    }



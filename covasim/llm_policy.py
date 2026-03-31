"""
Helpers for LLM-driven campus policy selection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3.5-plus"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 180
DEFAULT_REASON_MAX_CHARS = 40

POLICY_IDS = [
    "P0_normal",
    "P1_guarded",
    "P2_moderate",
    "P3_strong",
    "P4_emergency",
]
RISK_LEVELS = ["low", "medium", "high", "critical"]
CAMPUS_LAYER_KEYS = ["d", "clu", "clg", "of", "ta", "cm"]
REASON_ALLOWED_RE = re.compile(r"^[\u4e00-\u9fffa-zA-Z0-9\uff0c\u3002\u3001\uff1b\uff1a\uff01\uff1f\uff08\uff09\(\)\u300a\u300b\u201c\u201d\u2018\u2019\s\-]{1,40}$")


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
            "summary": "Normal operations with baseline symptom testing, low-frequency targeted screening, and routine tracing.",
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
                trace_probs=dict(d=0.75, clu=0.60, clg=0.60, of=0.55, ta=0.50, cm=0.20),
                trace_time=dict(d=0, clu=2, clg=2, of=2, ta=2, cm=3),
                capacity=None,
            ),
        },
        "P1_guarded": {
            "rank": 1,
            "summary": "Guarded posture with stronger screening and tracing plus mild public-space restrictions.",
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
                trace_probs=dict(d=0.90, clu=0.80, clg=0.80, of=0.75, ta=0.70, cm=0.25),
                trace_time=dict(d=0, clu=1, clg=1, of=1, ta=1, cm=2),
                capacity=None,
            ),
        },
        "P2_moderate": {
            "rank": 2,
            "summary": "Moderate controls with higher screening cadence, strong tracing, and reduced classroom/lab/office intensity.",
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
                trace_probs=dict(d=0.95, clu=0.90, clg=0.90, of=0.90, ta=0.85, cm=0.35),
                trace_time=dict(d=0, clu=1, clg=1, of=1, ta=1, cm=2),
                capacity=None,
            ),
        },
        "P3_strong": {
            "rank": 3,
            "summary": "Strong response with online teaching for the current period, high-frequency screening, and tight campus restrictions.",
            "restriction_intensity": 3,
            "online_teaching_active": True,
            "restriction_profile": dict(d=1.10, clu=0.00, clg=0.00, of=0.50, ta=0.60, cm=0.45),
            "testing_profile": dict(symp_prob=0.18, asymp_prob=0.010, symp_quar_prob=0.65, asymp_quar_prob=0.05),
            "screening_profile": dict(
                daily_capacity_ratio=0.08,
                group_cycles=dict(teacher=2, lab=2, dorm=3, course=5, id_bucket=7),
                exclude_recent_days=1,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=1.00, clu=0.98, clg=0.98, of=0.95, ta=0.90, cm=0.45),
                trace_time=dict(d=0, clu=0, clg=0, of=1, ta=1, cm=1),
                capacity=None,
            ),
        },
        "P4_emergency": {
            "rank": 4,
            "summary": "Emergency posture with online teaching, campus-wide high-frequency screening, and maximum restrictions.",
            "restriction_intensity": 4,
            "online_teaching_active": True,
            "restriction_profile": dict(d=1.15, clu=0.00, clg=0.00, of=0.00, ta=0.20, cm=0.25),
            "testing_profile": dict(symp_prob=0.24, asymp_prob=0.015, symp_quar_prob=0.80, asymp_quar_prob=0.08),
            "screening_profile": dict(
                daily_capacity_ratio=0.12,
                group_cycles=dict(teacher=1, lab=1, dorm=2, course=3, id_bucket=4),
                exclude_recent_days=0,
                subtarget=None,
            ),
            "tracing_profile": dict(
                trace_probs=dict(d=1.00, clu=1.00, clg=1.00, of=1.00, ta=0.95, cm=0.55),
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
    Enforce the strict weekly +/-1 transition rule.
    """
    catalog = policy_catalog if policy_catalog is not None else make_default_policy_catalog()
    if current_policy_id is None:
        return proposed_policy_id
    current_rank = get_policy_rank(current_policy_id, catalog)
    proposed_rank = get_policy_rank(proposed_policy_id, catalog)
    clipped_rank = min(max(proposed_rank, current_rank - 1), current_rank + 1)
    return get_policy_by_rank(clipped_rank, catalog)


def build_system_prompt():
    """Build the fixed system prompt for policy classification."""
    return (
        "You are the strategy classifier inside a campus epidemic simulation system. "
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
        "Do not output any extra text or chain-of-thought."
    )


def build_user_payload(state, policy_catalog):
    """Build the fixed user payload for policy selection."""
    return {
        "task": "Choose exactly one next-period policy_id from the predefined campus policy catalog.",
        "state": state,
        "policy_catalog_brief": policy_catalog_to_brief(policy_catalog),
        "output_schema": {
            "policy_id": "P0_normal | P1_guarded | P2_moderate | P3_strong | P4_emergency",
            "risk_level": "low | medium | high | critical",
            "reason": "short Chinese reason, <=40 chars",
        },
    }


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


def build_chat_messages(state, policy_catalog):
    """Build chat completion messages for the policy call."""
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": json.dumps(build_user_payload(state, policy_catalog), ensure_ascii=False, indent=2)},
    ]


def hash_text(text):
    """Return the SHA256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_json_object(raw_text):
    """Extract a JSON object from raw model text."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise PolicyResponseError("Model response was empty.")
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            raise PolicyResponseError("No JSON object found in model response.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise PolicyResponseError(f"Invalid JSON in model response: {exc}") from exc


def _validate_reason_text(reason, reason_max_chars):
    """Validate the reason field."""
    if not isinstance(reason, str) or not reason.strip():
        raise PolicyResponseError('Field "reason" must be a non-empty string.')
    reason = reason.strip()
    if len(reason) > int(reason_max_chars):
        raise PolicyResponseError(f'Field "reason" exceeds {reason_max_chars} characters.')
    if not re.search(r"[\u4e00-\u9fff]", reason):
        raise PolicyResponseError('Field "reason" must contain Chinese text.')
    if not REASON_ALLOWED_RE.match(reason):
        raise PolicyResponseError('Field "reason" contains unsupported characters.')
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

    new_infections = _result_values(sim, "new_infections")
    new_diagnoses = _result_values(sim, "new_diagnoses")
    new_tests = _result_values(sim, "new_tests")
    n_quarantined = _result_values(sim, "n_quarantined")
    r_eff_values = _result_values(sim, "r_eff")

    inf_window, inf_prev = _window_pair(new_infections, end_day, window)
    diag_window, diag_prev = _window_pair(new_diagnoses, end_day, window)
    test_window, _ = _window_pair(new_tests, end_day, window)
    quar_window, quar_prev = _window_pair(n_quarantined, end_day, window)

    new_infections_sum = float(inf_window.sum())
    new_diagnoses_sum = float(diag_window.sum())
    new_tests_sum = float(test_window.sum())
    current_r_eff = _latest_finite_value(r_eff_values, end_day)
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
            "r_eff_current": round(float(current_r_eff), 4),
            "estimated_risk_trend": _estimated_risk_trend(inf_window, inf_prev, current_r_eff),
        },
        "new_infections_per_1000_last_7d": round(_safe_ratio(new_infections_sum * 1000.0, scaled_pop_size), 6),
        "diagnosis_ascertainment_proxy": round(_safe_ratio(new_diagnoses_sum, new_infections_sum), 6),
        "online_teaching_active": bool(policy_catalog.get(current_policy, {}).get("online_teaching_active", False)) if current_policy else False,
        "current_restriction_intensity": policy_catalog.get(current_policy, {}).get("restriction_intensity", 0) if current_policy else 0,
        "growth_ratio_7d_vs_prev_7d": round(_growth_ratio(inf_window, inf_prev), 6),
    }

    if layer_counts is not None:
        state["layer_transmission_last_7d"] = layer_counts
        state["peak_layer_last_7d"] = max(layer_counts, key=layer_counts.get) if layer_counts else None
        state["campus_pressure"] = {
            "classroom_risk": _pressure_label(max(layer_counts.get("clu", 0), layer_counts.get("clg", 0))),
            "dorm_risk": _pressure_label(layer_counts.get("d", 0)),
            "lab_risk": _pressure_label(layer_counts.get("of", 0)),
            "office_risk": _pressure_label(layer_counts.get("ta", 0)),
            "community_risk": _pressure_label(layer_counts.get("cm", 0)),
        }

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


class QwenPolicyClient:
    """
    Real DashScope Qwen client using the OpenAI-compatible Chat Completions API.
    """

    def __init__(self, api_key=None, base_url=None, model=DEFAULT_QWEN_MODEL,
                 temperature=DEFAULT_TEMPERATURE, max_tokens=DEFAULT_MAX_TOKENS):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_DASHSCOPE_BASE_URL
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise PolicyDecisionError("Environment variable DASHSCOPE_API_KEY is not set.")
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise PolicyDecisionError('The "openai" package is required for Qwen policy decisions.') from exc
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def decide_policy(self, state, policy_catalog):
        """
        Request a policy decision and return parsed metadata.
        """
        system_prompt = build_system_prompt()
        user_payload = build_user_payload(state, policy_catalog)
        messages = build_chat_messages(state, policy_catalog)
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise PolicyResponseError("Model response did not contain any choices.")

        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "content_filter":
            raise PolicyResponseError("Model response was blocked by a safety filter.")
        if finish_reason not in (None, "stop"):
            raise PolicyResponseError(f"Unexpected finish_reason: {finish_reason}")

        message = getattr(choice, "message", None)
        raw_text = getattr(message, "content", None) if message is not None else None
        if isinstance(raw_text, list):
            raw_text = "".join(part.get("text", "") for part in raw_text if isinstance(part, dict))

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


def _estimated_risk_trend(inf_window, inf_prev, current_r_eff):
    trend = _trend_label(inf_window, inf_prev)
    if current_r_eff > 1.1 or trend == "up":
        return "worsening"
    if current_r_eff < 0.9 and trend == "down":
        return "improving"
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


def _latest_finite_value(values, end_day):
    if values.size == 0 or end_day < 0:
        return 0.0
    end = min(int(end_day), values.size - 1)
    for idx in range(end, -1, -1):
        if np.isfinite(values[idx]):
            return float(values[idx])
    return 0.0


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


def _pressure_label(count):
    count = int(count)
    if count <= 2:
        return "low"
    if count <= 8:
        return "medium"
    if count <= 20:
        return "high"
    return "critical"

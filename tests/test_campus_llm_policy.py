import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim as cv
import covasim.llm_policy as cvlp


VALID_REASON = "\u75c5\u4f8b\u4e0a\u5347\u9700\u52a0\u5f3a\u9632\u63a7"
UPGRADE_REASON_1 = "\u4f20\u64ad\u589e\u957f\u660e\u663e\u9700\u5347\u7ea7"
UPGRADE_REASON_2 = "\u4f20\u64ad\u4ecd\u5f3a\u9700\u7ee7\u7eed\u5347\u7ea7"
DOWNGRADE_REASON_1 = "\u6307\u6807\u56de\u843d\u53ef\u9010\u6b65\u964d\u7ea7"
DOWNGRADE_REASON_2 = "\u98ce\u9669\u5df2\u7f13\u53ef\u7ee7\u7eed\u964d\u7ea7"
LONG_REASON = (
    "\u8fd9\u4e2a\u539f\u56e0\u63cf\u8ff0\u6545\u610f\u5199\u5f97\u975e\u5e38\u975e\u5e38\u957f"
    "\u4ee5\u4fbf\u786e\u8ba4\u672c\u5730\u89e3\u6790\u5668\u4f1a\u5bf9\u8d85\u8fc7\u56db\u5341"
    "\u4e2a\u6c49\u5b57\u7684\u4e2d\u6587\u539f\u56e0\u5b57\u6bb5\u76f4\u63a5\u62d2\u7edd\u800c"
    "\u4e0d\u662f\u7ee7\u7eed\u653e\u884c"
)
FALLBACK_REASON = "\u75c5\u4f8b\u589e\u957f\u9700\u5347\u7ea7"


class DummyResult:
    def __init__(self, values):
        self.values = np.array(values, dtype=float)


class DummySim(dict):
    def __init__(self):
        super().__init__(pop_size=1000)
        self.t = 14
        self.npts = 30
        self.scaled_pop_size = 1000
        self.results = {
            "new_infections": DummyResult([0, 1, 2, 3, 4, 4, 5, 6, 8, 10, 12, 11, 10, 9, 8]),
            "new_diagnoses": DummyResult([0, 0, 1, 1, 2, 2, 3, 4, 5, 6, 6, 7, 7, 6, 5]),
            "new_tests": DummyResult([50, 55, 60, 65, 70, 72, 74, 75, 80, 85, 90, 92, 94, 96, 100]),
            "n_quarantined": DummyResult([5, 6, 8, 10, 15, 20, 25, 30, 40, 55, 70, 72, 68, 64, 60]),
            "r_eff": DummyResult([0.9, 1.0, 1.02, 1.05, 1.08, 1.10, 1.12, 1.15, 1.18, 1.20, 1.24, 1.22, 1.18, 1.16, 1.12]),
        }
        self.people = SimpleNamespace(
            infection_log=[
                {"date": 8, "layer": "d"},
                {"date": 9, "layer": "d"},
                {"date": 10, "layer": "clu"},
                {"date": 11, "layer": "clg"},
                {"date": 12, "layer": "cm"},
                {"date": 13, "layer": "of"},
            ]
        )

    def date(self, day):
        return f"2026-04-{int(day) + 1:02d}"


def make_campus_sim(interventions=None, pop_size=600, pop_infected=20, n_days=21, rand_seed=1):
    return cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=pop_size,
            pop_infected=pop_infected,
            n_days=n_days,
            rand_seed=rand_seed,
        ),
        interventions=interventions or [],
    )


def make_sequence_decision_fn(sequence):
    state = {"items": list(sequence), "index": 0}

    def decision_fn(sim_state, policy_catalog):
        item = state["items"][state["index"]]
        state["index"] += 1
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(sim_state, policy_catalog)
        return item

    return decision_fn


def make_memory_record(day, proposed_policy, applied_policy, infections_sum, tests_sum, quarantined_mean, risk_level="medium"):
    return {
        "decision_day": day,
        "decision_date": f"2026-04-{int(day) + 1:02d}",
        "model_policy_proposed": proposed_policy,
        "applied_policy": applied_policy,
        "risk_level": risk_level,
        "state_snapshot": {
            "past_7d_summary": {
                "new_infections_sum": infections_sum,
                "new_infections_trend": "up" if infections_sum >= 10 else "down",
                "r_eff_current": 1.15 if infections_sum >= 10 else 0.92,
                "estimated_risk_trend": "worsening" if infections_sum >= 10 else "improving",
            },
            "intervention_burden_last_7d": {
                "tests_sum": tests_sum,
                "mean_quarantined": quarantined_mean,
            },
        },
    }


def test_apply_policy_transition_constraint():
    catalog = cvlp.make_default_policy_catalog()
    assert cvlp.apply_policy_transition_constraint("P4_emergency", "P1_guarded", catalog) == "P2_moderate"
    assert cvlp.apply_policy_transition_constraint("P0_normal", "P3_strong", catalog) == "P2_moderate"
    assert cvlp.apply_policy_transition_constraint("P2_moderate", None, catalog) == "P2_moderate"


def test_parse_policy_response_validation():
    valid = json.dumps({"policy_id": "P2_moderate", "risk_level": "high", "reason": VALID_REASON}, ensure_ascii=False)
    assert cvlp.parse_policy_response(valid)["policy_id"] == "P2_moderate"

    invalid_payloads = [
        "",
        "not json",
        json.dumps({"policy_id": "P9", "risk_level": "high", "reason": VALID_REASON}, ensure_ascii=False),
        json.dumps({"policy_id": "P2_moderate", "risk_level": "urgent", "reason": VALID_REASON}, ensure_ascii=False),
        json.dumps({"policy_id": "P2_moderate", "risk_level": "high"}, ensure_ascii=False),
        json.dumps({"policy_id": "P2_moderate", "risk_level": "high", "reason": VALID_REASON, "extra": 1}, ensure_ascii=False),
    ]

    for raw in invalid_payloads:
        with pytest.raises(cvlp.PolicyResponseError):
            cvlp.parse_policy_response(raw)

    long_payload = json.dumps({"policy_id": "P2_moderate", "risk_level": "high", "reason": LONG_REASON}, ensure_ascii=False)
    assert len(cvlp.parse_policy_response(long_payload)["reason"]) == cvlp.DEFAULT_REASON_MAX_CHARS


def test_build_system_prompt_and_policy_catalog_brief_include_debias_rules():
    prompt = cvlp.build_system_prompt(use_theory_prompt=True)
    assert "recent 7-day versus previous 7-day trends" in prompt
    assert "P3_strong and P4_emergency have high operational and teaching costs" in prompt
    assert "consider stepping down to P1_guarded" in prompt
    assert "consider stepping down to P0_normal" in prompt

    brief = cvlp.policy_catalog_to_brief(cvlp.make_default_policy_catalog())
    summaries = {item["policy_id"]: item["summary"] for item in brief}
    assert "Lowest-cost posture" in summaries["P0_normal"]
    assert "High-cost strong-control posture" in summaries["P3_strong"]
    assert "Highest-cost emergency posture" in summaries["P4_emergency"]


def test_extract_campus_policy_state_schema():
    sim = DummySim()
    agent = SimpleNamespace(
        current_policy="P1_guarded",
        current_policy_start_day=7,
        policy_catalog=cvlp.make_default_policy_catalog(),
        memory_weeks=4,
        decision_history=[
            make_memory_record(0, "P2_moderate", "P2_moderate", 24, 500, 20, risk_level="high"),
            make_memory_record(7, "P3_strong", "P3_strong", 12, 650, 35, risk_level="high"),
            make_memory_record(10, "P2_moderate", "P2_moderate", 8, 700, 40, risk_level="medium"),
            make_memory_record(12, "P1_guarded", "P1_guarded", 6, 720, 38, risk_level="medium"),
        ],
    )
    state = cvlp.extract_campus_policy_state(sim, agent=agent, decision_day=14, window=7)

    assert state["decision_day"] == 14
    assert state["decision_date"] == "2026-04-15"
    assert state["current_policy"] == "P1_guarded"
    assert state["current_policy_duration_days"] == 7
    assert "past_7d_summary" in state
    assert "layer_transmission_last_7d" in state
    assert "layer_transmission_trends" in state
    assert "recent_policy_memory" in state
    assert len(state["recent_policy_memory"]) == 4
    assert state["policy_effect_summary"]["memory_count"] == 4
    assert "policy_volatility_last_4w" in state
    assert state["intervention_burden_last_7d"]["mean_quarantined"] > 0
    assert state["past_7d_summary"]["new_infections_sum"] > 0
    assert state["past_7d_summary"]["r_eff_current"] == pytest.approx(1.19)
    assert state["layer_transmission_trends"]["dorm"] == {
        "current_7d": 2.0,
        "prev_7d": 0.0,
        "delta": 2.0,
        "ratio": 1.0,
        "trend": "up",
    }
    assert state["layer_transmission_trends"]["classroom"] == {
        "current_7d": 2.0,
        "prev_7d": 0.0,
        "delta": 2.0,
        "ratio": 1.0,
        "trend": "up",
    }
    assert state["recent_policy_memory"][-1]["state_summary"]["growth_ratio_7d_vs_prev_7d"] == 0.0
    assert state["recent_policy_memory"][-1]["state_summary"]["layer_transmission_trends"] == {}


def test_build_user_payload_keeps_new_layer_trends():
    state = {
        "past_7d_summary": {"new_infections_sum": 10.0, "new_infections_trend": "down"},
        "layer_transmission_trends": {
            "classroom": {"current_7d": 6.0, "prev_7d": 10.0, "delta": -4.0, "ratio": 0.6, "trend": "down"}
        },
    }
    payload = cvlp.build_user_payload(state, cvlp.make_default_policy_catalog())
    assert payload["state"]["layer_transmission_trends"]["classroom"]["trend"] == "down"
    assert any(item["policy_id"] == "P3_strong" for item in payload["policy_catalog_brief"])


def test_extract_campus_policy_state_without_infection_log():
    sim = DummySim()
    sim.people = SimpleNamespace(infection_log=None)
    state = cvlp.extract_campus_policy_state(sim, agent=None, decision_day=14, window=7)

    assert "layer_transmission_last_7d" not in state
    assert "layer_transmission_trends" not in state
    assert "past_7d_summary" in state
    assert state["recent_policy_memory"] == []
    assert state["policy_effect_summary"]["memory_count"] == 0


def test_extract_campus_policy_state_memory_window_shapes_and_trends():
    sim = DummySim()
    catalog = cvlp.make_default_policy_catalog()
    agent_empty = SimpleNamespace(
        current_policy="P1_guarded",
        current_policy_start_day=7,
        policy_catalog=catalog,
        memory_weeks=4,
        decision_history=[],
    )
    empty_state = cvlp.extract_campus_policy_state(sim, agent=agent_empty, decision_day=14, window=7)
    assert empty_state["recent_policy_memory"] == []
    assert empty_state["policy_volatility_last_4w"]["policy_switch_count"] == 0

    agent_one = SimpleNamespace(
        current_policy="P1_guarded",
        current_policy_start_day=7,
        policy_catalog=catalog,
        memory_weeks=4,
        decision_history=[make_memory_record(7, "P2_moderate", "P2_moderate", 15, 600, 30, risk_level="high")],
    )
    one_state = cvlp.extract_campus_policy_state(sim, agent=agent_one, decision_day=14, window=7)
    assert len(one_state["recent_policy_memory"]) == 1
    assert one_state["policy_effect_summary"]["dominant_effect_trend"] in {"improving", "stable", "worsening"}
    assert one_state["layer_transmission_trends"]["community"]["trend"] == "up"

    agent_many = SimpleNamespace(
        current_policy="P2_moderate",
        current_policy_start_day=10,
        policy_catalog=catalog,
        memory_weeks=4,
        decision_history=[
            make_memory_record(0, "P1_guarded", "P1_guarded", 21, 500, 16),
            make_memory_record(7, "P2_moderate", "P2_moderate", 18, 620, 25),
            make_memory_record(14, "P3_strong", "P3_strong", 12, 700, 36),
            make_memory_record(21, "P2_moderate", "P2_moderate", 8, 760, 32),
            make_memory_record(28, "P1_guarded", "P1_guarded", 5, 730, 20),
        ],
    )
    many_state = cvlp.extract_campus_policy_state(sim, agent=agent_many, decision_day=30, window=7)
    assert len(many_state["recent_policy_memory"]) == 4
    assert many_state["recent_policy_memory"][0]["decision_day"] == 7
    assert many_state["policy_volatility_last_4w"]["policy_switch_count"] >= 1
    assert many_state["policy_volatility_last_4w"]["policy_oscillation_score"] >= 0
    assert "layer_transmission_trends" in many_state["recent_policy_memory"][-1]["state_summary"]


def test_campus_policy_agent_absolute_rewrite_and_runtime_updates():
    sequence = [
        json.dumps({"policy_id": "P4_emergency", "risk_level": "critical", "reason": UPGRADE_REASON_1}, ensure_ascii=False),
        json.dumps({"policy_id": "P4_emergency", "risk_level": "critical", "reason": UPGRADE_REASON_2}, ensure_ascii=False),
        json.dumps({"policy_id": "P0_normal", "risk_level": "medium", "reason": DOWNGRADE_REASON_1}, ensure_ascii=False),
        json.dumps({"policy_id": "P0_normal", "risk_level": "low", "reason": DOWNGRADE_REASON_2}, ensure_ascii=False),
    ]
    agent = cv.campus_policy_agent(
        decision_interval_days=7,
        initial_policy="P1_guarded",
        decision_fn=make_sequence_decision_fn(sequence),
        min_policy_hold_intervals=0,
        log_path=None,
    )
    sim = make_campus_sim(interventions=[agent], n_days=21, rand_seed=2)
    sim.run()
    agent = sim["interventions"][0]

    catalog = agent.policy_catalog
    baseline = agent.baseline_beta_layer
    trace_by_day = {entry["day"]: entry for entry in agent.policy_trace}

    expected_policies = {
        0: "P2_moderate",
        6: "P2_moderate",
        7: "P3_strong",
        13: "P3_strong",
        14: "P2_moderate",
        20: "P2_moderate",
        21: "P1_guarded",
    }
    for day, policy_id in expected_policies.items():
        assert trace_by_day[day]["policy_id"] == policy_id
        for layer in cvlp.CAMPUS_LAYER_KEYS:
            expected = baseline[layer] * catalog[policy_id]["restriction_profile"][layer]
            assert trace_by_day[day]["effective_beta_layer"][layer] == pytest.approx(expected)

    assert trace_by_day[7]["effective_beta_layer"]["clu"] == pytest.approx(
        baseline["clu"] * catalog["P3_strong"]["restriction_profile"]["clu"]
    )
    assert trace_by_day[7]["effective_beta_layer"]["clg"] == pytest.approx(
        baseline["clg"] * catalog["P3_strong"]["restriction_profile"]["clg"]
    )
    assert trace_by_day[21]["effective_beta_layer"]["clu"] == pytest.approx(baseline["clu"])
    assert trace_by_day[21]["effective_beta_layer"]["clg"] == pytest.approx(baseline["clg"])

    final_policy = "P1_guarded"
    screening_profile = agent._get_screening_profile(final_policy, sim)
    assert agent.testing_intervention.symp_prob == pytest.approx(catalog[final_policy]["testing_profile"]["symp_prob"])
    assert agent.screening_intervention.exclude_recent_days == screening_profile["exclude_recent_days"]
    assert agent.screening_intervention.daily_capacity[0] == screening_profile["daily_capacity"]
    assert agent.tracing_intervention.trace_probs["d"] == pytest.approx(catalog[final_policy]["tracing_profile"]["trace_probs"]["d"])

    assert agent.decision_history[0]["model_policy_proposed"] == "P4_emergency"
    assert agent.decision_history[0]["applied_policy"] == "P2_moderate"
    assert agent.decision_history[1]["applied_policy"] == "P3_strong"
    assert agent.decision_history[2]["applied_policy"] == "P2_moderate"
    assert agent.decision_history[3]["applied_policy"] == "P1_guarded"


def test_campus_policy_agent_fallback_and_jsonl_log():
    log_path = Path.cwd() / "campus_policy_test_log.jsonl"
    if log_path.exists():
        log_path.unlink()

    sequence = [
        RuntimeError("api unavailable"),
        json.dumps({"policy_id": "P4_emergency", "risk_level": "critical", "reason": FALLBACK_REASON}, ensure_ascii=False),
    ]
    agent = cv.campus_policy_agent(
        decision_interval_days=7,
        initial_policy="P1_guarded",
        decision_fn=make_sequence_decision_fn(sequence),
        log_path=log_path,
    )
    sim = make_campus_sim(interventions=[agent], n_days=7, rand_seed=3)
    try:
        sim.run()
        agent = sim["interventions"][0]

        assert len(agent.decision_history) == 2
        assert agent.decision_history[0]["fallback_used"] is True
        assert agent.decision_history[0]["applied_policy"] == "P1_guarded"
        assert agent.decision_history[0]["error_type"] == "RuntimeError"
        assert agent.decision_history[1]["fallback_used"] is False
        assert agent.decision_history[1]["model_policy_proposed"] == "P4_emergency"
        assert agent.decision_history[1]["applied_policy"] == "P2_moderate"

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["fallback_used"] is True
        assert second["model_policy_proposed"] == "P4_emergency"
        assert second["system_prompt_sha256"] == cvlp.hash_text(second["system_prompt"])
        assert "state_snapshot" in second
        assert "memory_snapshot" in second
        assert "ensemble_votes" in second
        assert "restriction_profile_applied" in second
    finally:
        if log_path.exists():
            log_path.unlink()


def test_campus_policy_agent_ensemble_majority_tie_and_member_failure():
    majority_sequence = [
        json.dumps({"policy_id": "P1_guarded", "risk_level": "medium", "reason": VALID_REASON}, ensure_ascii=False),
        json.dumps({"policy_id": "P2_moderate", "risk_level": "high", "reason": UPGRADE_REASON_1}, ensure_ascii=False),
        json.dumps({"policy_id": "P2_moderate", "risk_level": "high", "reason": UPGRADE_REASON_2}, ensure_ascii=False),
        RuntimeError("member failed"),
        json.dumps({"policy_id": "P1_guarded", "risk_level": "medium", "reason": VALID_REASON}, ensure_ascii=False),
        json.dumps({"policy_id": "P4_emergency", "risk_level": "critical", "reason": UPGRADE_REASON_1}, ensure_ascii=False),
    ]
    agent = cv.campus_policy_agent(
        decision_interval_days=7,
        initial_policy="P1_guarded",
        ensemble_size=5,
        min_policy_hold_intervals=0,
        decision_fn=make_sequence_decision_fn(majority_sequence),
        log_path=None,
    )
    sim = make_campus_sim(interventions=[agent], n_days=7, rand_seed=4)
    sim.run()
    agent = sim["interventions"][0]

    first = agent.decision_history[0]
    second = agent.decision_history[1]
    assert first["applied_policy"] == "P2_moderate"
    assert len(first["ensemble_votes"]) == 3
    assert sum(vote.get("policy_id") == "P2_moderate" for vote in first["ensemble_votes"]) == 2
    assert second["applied_policy"] == "P3_strong"
    assert any(vote.get("error_type") == "RuntimeError" for vote in second["ensemble_votes"])


def test_campus_policy_agent_min_hold_and_burden_guardrail():
    hold_sequence = [
        json.dumps({"policy_id": "P4_emergency", "risk_level": "high", "reason": UPGRADE_REASON_1}, ensure_ascii=False),
        json.dumps({"policy_id": "P0_normal", "risk_level": "medium", "reason": DOWNGRADE_REASON_1}, ensure_ascii=False),
        json.dumps({"policy_id": "P0_normal", "risk_level": "low", "reason": DOWNGRADE_REASON_2}, ensure_ascii=False),
    ]
    agent = cv.campus_policy_agent(
        decision_interval_days=7,
        initial_policy="P1_guarded",
        decision_fn=make_sequence_decision_fn(hold_sequence),
        log_path=None,
    )
    sim = make_campus_sim(interventions=[agent], n_days=14, rand_seed=5)
    sim.run()
    agent = sim["interventions"][0]

    assert agent.decision_history[0]["applied_policy"] == "P2_moderate"
    assert agent.decision_history[1]["applied_policy"] == "P2_moderate"
    assert agent.decision_history[1]["guardrail_adjusted"] is True
    assert agent.decision_history[1]["guardrail_reason"] == "min_hold_reversal_block"
    assert agent.decision_history[2]["applied_policy"] == "P1_guarded"

    guardrail_agent = cv.campus_policy_agent(initial_policy="P3_strong")
    guardrail_agent.current_policy = "P3_strong"
    guardrail_agent.decision_history = []
    state = {
        "current_policy_duration_days": 14,
        "past_7d_summary": {
            "estimated_risk_trend": "stable",
            "new_infections_trend": "down",
            "r_eff_current": 0.95,
        },
        "intervention_burden_last_7d": {
            "mean_quarantined_per_1000": 25.0,
            "tests_per_1000": 120.0,
            "teaching_restriction_intensity": 3,
        },
        "policy_effect_summary": {
            "dominant_effect_trend": "stable",
        },
    }
    applied_policy, reason = guardrail_agent._apply_policy_guardrails(
        proposed_policy="P4_emergency",
        state=state,
        decision={"risk_level": "high"},
    )
    assert applied_policy == "P3_strong"
    assert reason == "burden_guardrail_block"

    low_prevalence_agent = cv.campus_policy_agent(initial_policy="P2_moderate")
    low_prevalence_agent.current_policy = "P2_moderate"
    low_prevalence_state = {
        "current_policy_duration_days": 14,
        "new_infections_per_1000_last_7d": 6.9,
        "growth_ratio_7d_vs_prev_7d": 2.4,
        "past_7d_summary": {
            "estimated_risk_trend": "worsening",
            "new_infections_sum": 276.0,
            "new_infections_trend": "up",
            "r_eff_current": 0.0,
        },
        "intervention_burden_last_7d": {},
        "policy_effect_summary": {
            "dominant_effect_trend": "worsening",
        },
    }
    applied_policy, reason = low_prevalence_agent._apply_policy_guardrails(
        proposed_policy="P4_emergency",
        state=low_prevalence_state,
        decision={"risk_level": "critical"},
    )
    assert applied_policy == "P2_moderate"
    assert reason == "low_prevalence_online_guardrail_block"


def test_campus_policy_agent_defer_first_decision_until_interval():
    sequence = [
        json.dumps({"policy_id": "P4_emergency", "risk_level": "critical", "reason": UPGRADE_REASON_1}, ensure_ascii=False),
    ]
    agent = cv.campus_policy_agent(
        decision_interval_days=7,
        initial_policy="P1_guarded",
        defer_first_decision_until_interval=True,
        decision_fn=make_sequence_decision_fn(sequence),
        min_policy_hold_intervals=0,
        log_path=None,
    )
    sim = make_campus_sim(interventions=[agent], n_days=8, rand_seed=6)
    sim.run()
    agent = sim["interventions"][0]

    assert len(agent.decision_history) == 1
    assert agent.decision_history[0]["decision_day"] == 7
    assert all(row["policy_id"] == "P1_guarded" for row in agent.policy_trace if row["day"] < 7)
    assert agent.policy_trace[7]["policy_id"] == "P2_moderate"


@pytest.mark.online
@pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="DASHSCOPE_API_KEY not set")
def test_qwen_policy_client_online_example_state():
    state_path = Path(__file__).resolve().parents[1] / "examples" / "campus_policy_state_example.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    client = cvlp.QwenPolicyClient(api_key=os.getenv("DASHSCOPE_API_KEY"))
    response = client.decide_policy(state=state, policy_catalog=cvlp.make_default_policy_catalog())

    assert response["decision"]["policy_id"] in cvlp.POLICY_IDS
    assert response["decision"]["risk_level"] in cvlp.RISK_LEVELS
    assert response["raw_response_text"]

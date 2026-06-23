"""Smoke tests for the dual-branch memory module (llm_memory)."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("COVASIM_VERBOSE", "0")

import covasim.llm_memory as cvlm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_state(
    infections_per_1000=5.0,
    r_eff_mean=1.2,
    growth_ratio=1.3,
    policy_rank=2,
    infection_trend="up",
):
    """Create a minimal state dict matching extract_campus_policy_state output."""
    return {
        "decision_day": 14,
        "decision_date": "2026-04-15",
        "new_infections_per_1000_last_7d": infections_per_1000,
        "growth_ratio_7d_vs_prev_7d": growth_ratio,
        "r_eff_mean": r_eff_mean,
        "r_eff_trend": "up" if r_eff_mean > 1 else "down",
        "r_eff_source": "realtime",
        "online_teaching_active": False,
        "past_7d_summary": {
            "new_infections_sum": 50.0,
            "new_diagnoses_sum": 15.0,
            "new_infections_trend": infection_trend,
            "new_diagnoses_trend": infection_trend,
            "estimated_risk_trend": "worsening" if infection_trend == "up" else "improving",
        },
        "intervention_burden_last_7d": {
            "tests_per_1000": 50.0,
            "mean_quarantined_per_1000": 20.0,
            "teaching_restriction_intensity": policy_rank,
            "online_teaching_active": False,
        },
        "layer_transmission_last_7d": {"d": 30, "clu": 20, "clg": 15, "of": 10, "ta": 5, "cm": 20},
        "layer_transmission_trends": {
            "d": "up", "clu": "flat", "clg": "flat", "of": "down", "ta": "flat", "cm": "up",
        },
        "_scaled_pop": 4000,
    }


def _make_entry(day, policy_rank=2, infection_trend="up", growth_ratio=1.3):
    """Create a minimal memory entry dict."""
    return {
        "entry_id": day * 10,
        "decision_day": day,
        "decision_date": f"2026-04-{day + 1:02d}",
        "new_infections_per_1000": 5.0 + day * 0.1,
        "new_diagnoses_per_1000": 2.0,
        "r_eff_value": 1.2,
        "r_eff_trend": "up",
        "r_eff_source": "realtime",
        "growth_ratio": growth_ratio,
        "tests_per_1000": 50.0,
        "quarantined_per_1000": 20.0,
        "teaching_restriction": policy_rank,
        "online_teaching": 0,
        "infection_trend": infection_trend,
        "diagnosis_trend": infection_trend,
        "risk_trend": "worsening",
        "layer_contributions": json.dumps({"d": 30, "clu": 20, "clg": 15, "of": 10, "ta": 5, "cm": 20}),
        "layer_transmission_trends": json.dumps({"d": "up", "clu": "flat"}),
        "policy_requested": f"P{policy_rank}_policy",
        "policy_executed": f"P{policy_rank}_policy",
        "policy_rank": policy_rank,
        "risk_level": "medium",
        "execution_feedback": json.dumps({
            "days_observed": 7,
            "infection_change": -5.0,
            "infection_trend": "down",
            "tests_sum": 350,
            "mean_quarantined": 20,
            "teaching_restriction": policy_rank,
            "online_teaching": False,
        }),
        "state_summary_text": f"Day {day} state",
        "feedback_status": "complete",
    }


# ---------------------------------------------------------------------------
# MemoryStore tests
# ---------------------------------------------------------------------------


class TestMemoryStore:
    def test_create_and_register(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = cvlm.MemoryStore(db_path=db_path)
        store.register_simulation("sim_001", 42, "medium", "test_strategy", 4000, 56)
        sim_ids = store.get_all_simulation_ids()
        assert "sim_001" in sim_ids
        store.close()

    def test_two_phase_write(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = cvlm.MemoryStore(db_path=db_path)
        store.register_simulation("sim_001", 42, "medium", "test", 4000, 56)

        state = _make_state()
        entry_data = {
            "decision_day": 7,
            "decision_date": "2026-04-08",
            "pop_size": 4000,
            "new_infections_per_1000": 5.0,
            "new_diagnoses_per_1000": 2.0,
            "r_eff_value": 1.2,
            "r_eff_trend": "up",
            "r_eff_source": "realtime",
            "growth_ratio": 1.3,
            "tests_per_1000": 50.0,
            "quarantined_per_1000": 20.0,
            "teaching_restriction": 2,
            "online_teaching": 0,
            "infection_trend": "up",
            "diagnosis_trend": "up",
            "risk_trend": "worsening",
            "layer_contributions": json.dumps({"d": 30, "clu": 20, "clg": 15, "of": 10, "ta": 5, "cm": 20}),
            "layer_transmission_trends": json.dumps({}),
            "policy_requested": "P2_moderate",
            "policy_executed": "P2_moderate",
            "policy_rank": 2,
            "risk_level": "medium",
            "execution_feedback": None,
            "state_summary_text": "test state",
            "feedback_status": "pending",
        }

        sv = cvlm.build_state_vector(state)
        lv = cvlm.build_layer_vector(state)
        tc = {"window": 1, "new_infections_per_1000": [5.0], "new_diagnoses_per_1000": [2.0],
              "r_eff": [1.2], "dorm_share": [0.3], "classroom_share": [0.35],
              "office_lab_share": [0.15], "community_share": [0.2]}
        te = np.random.rand(384).astype(np.float32)

        entry_id = store.create_pending_entry("sim_001", 7, entry_data, sv, lv, tc, te)
        assert entry_id > 0

        # Verify pending status
        recent = store.get_recent_completed_entries("sim_001", n=5, before_day=14)
        assert len(recent) == 0  # Still pending, not complete

        store.close()

    def test_read_only_blocks_write(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = cvlm.MemoryStore(db_path=db_path)
        store.register_simulation("sim_001", 42, "medium", "test", 4000, 56)
        store.close()

        ro_store = cvlm.MemoryStore(db_path=db_path, read_only=True)
        with pytest.raises(cvlm.ReadOnlyError):
            ro_store.create_pending_entry("sim_001", 7, {}, np.zeros(8), np.zeros(4), {}, np.zeros(384))
        ro_store.close()


# ---------------------------------------------------------------------------
# Vector builder tests
# ---------------------------------------------------------------------------


class TestVectorBuilders:
    def test_state_vector_shape(self):
        state = _make_state()
        sv = cvlm.build_state_vector(state)
        assert sv.shape == (8,)
        assert np.all(sv >= 0.0) and np.all(sv <= 1.0)

    def test_layer_vector_shape(self):
        state = _make_state()
        lv = cvlm.build_layer_vector(state)
        assert lv.shape == (4,)
        assert abs(lv.sum() - 1.0) < 0.01 or lv.sum() == 0.0

    def test_layer_vector_zero_when_empty(self):
        state = _make_state()
        state["layer_transmission_last_7d"] = {}
        lv = cvlm.build_layer_vector(state)
        assert np.all(lv == 0.0)

    def test_state_distance_similarity(self):
        a = np.array([0.0, 0.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0, 0.0])
        assert cvlm.state_distance_similarity(a, b) == 1.0

        c = np.array([1.0, 1.0, 1.0, 1.0])
        d = np.array([0.0, 0.0, 0.0, 0.0])
        sim = cvlm.state_distance_similarity(c, d)
        assert 0.0 <= sim < 0.5  # Max distance

    def test_cosine_similarity(self):
        a = np.array([1.0, 0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0, 0.0])
        assert abs(cvlm.cosine_similarity(a, b) - 1.0) < 1e-6

        c = np.array([1.0, 0.0, 0.0, 0.0])
        d = np.array([0.0, 1.0, 0.0, 0.0])
        assert abs(cvlm.cosine_similarity(c, d)) < 1e-6

    def test_pearson_similarity(self):
        x = [1.0, 2.0, 3.0, 4.0]
        y = [1.0, 2.0, 3.0, 4.0]
        sim = cvlm.pearson_similarity(x, y)
        assert sim is not None and abs(sim - 1.0) < 1e-6

        # Anti-correlated
        z = [4.0, 3.0, 2.0, 1.0]
        sim2 = cvlm.pearson_similarity(x, z)
        assert sim2 is not None and abs(sim2 - 0.0) < 1e-6

    def test_pearson_too_short(self):
        assert cvlm.pearson_similarity([1.0], [2.0]) is None

    def test_combine_similarity_with_missing(self):
        parts = {"state": 0.8, "layer": 0.6, "trend": None, "text": 0.7}
        lambdas = {"state": 0.30, "layer": 0.25, "trend": 0.20, "text": 0.25}
        combined = cvlm.combine_similarity(parts, lambdas)
        # trend is None, so weights renormalize over state+layer+text
        expected_denom = 0.30 + 0.25 + 0.25
        expected = (0.30 * 0.8 + 0.25 * 0.6 + 0.25 * 0.7) / expected_denom
        assert abs(combined - expected) < 1e-6


# ---------------------------------------------------------------------------
# Trend context tests
# ---------------------------------------------------------------------------


class TestTrendContext:
    def test_build_trend_context_basic(self):
        entries = [_make_entry(7), _make_entry(14)]
        state = _make_state()
        ctx = cvlm.build_trend_context(entries, state, window=3)
        assert ctx["window"] == 3
        assert len(ctx["new_infections_per_1000"]) == 3

    def test_build_trend_context_empty(self):
        state = _make_state()
        ctx = cvlm.build_trend_context([], state, window=3)
        assert ctx["window"] == 1  # Only current state

    def test_compute_trend_similarity(self):
        ctx_a = {
            "new_infections_per_1000": [3.0, 4.0, 5.0],
            "new_diagnoses_per_1000": [1.0, 2.0, 3.0],
            "r_eff": [1.0, 1.1, 1.2],
            "dorm_share": [0.3, 0.3, 0.3],
            "classroom_share": [0.3, 0.3, 0.3],
            "office_lab_share": [0.2, 0.2, 0.2],
            "community_share": [0.2, 0.2, 0.2],
        }
        ctx_b = dict(ctx_a)  # Same values
        sim = cvlm.compute_trend_similarity(ctx_a, ctx_b)
        assert sim is not None and sim > 0.5


# ---------------------------------------------------------------------------
# Trajectory compression tests
# ---------------------------------------------------------------------------


class TestTrajectoryCompression:
    def test_compress_basic(self):
        entries = [
            _make_entry(7, policy_rank=1),
            _make_entry(14, policy_rank=2),
            _make_entry(21, policy_rank=2),
        ]
        state = _make_state()
        catalog = {f"P{i}_policy": {} for i in range(5)}
        catalog["P0_normal"] = {}
        catalog["P1_guarded"] = {}
        catalog["P2_moderate"] = {}
        catalog["P3_strong"] = {}
        catalog["P4_emergency"] = {}

        result = cvlm.compress_short_term_trajectory(entries, state, catalog)
        assert "n_periods" in result
        assert result["n_periods"] == 3
        assert "strategy_path" in result
        assert "epidemic_trend" in result
        assert "adjustment_stability" in result
        assert "summary_text" in result
        assert isinstance(result["summary_text"], str)
        assert len(result["summary_text"]) > 0

    def test_compress_empty(self):
        state = _make_state()
        catalog = {f"P{i}_policy": {} for i in range(5)}
        result = cvlm.compress_short_term_trajectory([], state, catalog)
        assert result["n_periods"] == 0

    def test_strategy_path_labels(self):
        # Escalating: rank increases
        entries = [
            _make_entry(7, policy_rank=1),
            _make_entry(14, policy_rank=2),
            _make_entry(21, policy_rank=3),
        ]
        state = _make_state()
        catalog = {f"P{i}_policy": {} for i in range(5)}
        result = cvlm.compress_short_term_trajectory(entries, state, catalog)
        assert result["strategy_path"]["label"] == "escalating"

    def test_strategy_path_maintaining(self):
        entries = [
            _make_entry(7, policy_rank=2),
            _make_entry(14, policy_rank=2),
            _make_entry(21, policy_rank=2),
        ]
        state = _make_state()
        catalog = {f"P{i}_policy": {} for i in range(5)}
        result = cvlm.compress_short_term_trajectory(entries, state, catalog)
        assert result["strategy_path"]["label"] == "maintaining"


# ---------------------------------------------------------------------------
# Build pending entry tests
# ---------------------------------------------------------------------------


class TestBuildPendingEntry:
    def test_build_pending_entry(self):
        state = _make_state()
        record = {
            "decision_day": 14,
            "decision_date": "2026-04-15",
            "model_policy_proposed": "P2_moderate",
            "applied_policy": "P2_moderate",
            "risk_level": "medium",
        }

        class FakeSim:
            scaled_pop_size = 4000
            def __getitem__(self, key):
                if key == "pop_size":
                    return 4000
                return None

        entry = cvlm.build_pending_memory_entry(state, record, FakeSim())
        assert entry["decision_day"] == 14
        assert entry["policy_requested"] == "P2_moderate"
        assert entry["policy_executed"] == "P2_moderate"
        assert entry["feedback_status"] == "pending"
        assert entry["execution_feedback"] is None


# ---------------------------------------------------------------------------
# State description text tests
# ---------------------------------------------------------------------------


class TestStateDescription:
    def test_build_state_description_text(self):
        state = _make_state()
        text = cvlm.build_state_description_text(state)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "感染" in text or "R_eff" in text or "infections" in text.lower()


# ---------------------------------------------------------------------------
# EmbeddingProvider tests (skip if model not available)
# ---------------------------------------------------------------------------


class TestEmbeddingProvider:
    @pytest.fixture
    def provider(self):
        return cvlm.EmbeddingProvider()

    def test_lazy_load(self, provider):
        assert provider._model is None

    @pytest.mark.skipif(
        not os.environ.get("TEST_EMBEDDING_MODEL"),
        reason="Set TEST_EMBEDDING_MODEL=1 to run embedding tests",
    )
    def test_encode(self, provider):
        emb = provider.encode("测试文本")
        assert emb.shape == (384,)
        assert emb.dtype == np.float32


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

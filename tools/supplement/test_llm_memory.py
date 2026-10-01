"""Offline, filesystem-independent tests for CEMAS dual-branch memory."""

import numpy as np

import cemas as ce
import covasim.llm_memory as cvlm


def _state():
    return {
        "new_infections_per_1000_last_7d": 5.0,
        "growth_ratio_7d_vs_prev_7d": 1.3,
        "r_eff_mean": 1.2,
        "r_eff_trend": "up",
        "past_7d_summary": {
            "new_infections_trend": "up",
            "new_diagnoses_trend": "up",
            "estimated_risk_trend": "worsening",
        },
        "intervention_burden_last_7d": {
            "tests_per_1000": 50.0,
            "mean_quarantined_per_1000": 20.0,
            "teaching_restriction_intensity": 2,
            "online_teaching_active": False,
        },
        "layer_transmission_last_7d": {
            "d": 30,
            "clu": 20,
            "clg": 15,
            "of": 10,
            "ta": 5,
            "cm": 20,
        },
    }


def test_public_memory_exports():
    assert ce.MemoryStore is cvlm.MemoryStore
    assert ce.EmbeddingProvider is cvlm.EmbeddingProvider


def test_memory_store_registers_simulation_in_memory():
    store = cvlm.MemoryStore(db_path=":memory:")
    store.register_simulation("offline-test", 42, "medium", "memory", 4000, 56)
    assert store.get_all_simulation_ids() == ["offline-test"]
    store.close()


def test_memory_vectors_and_similarity_are_bounded():
    state_vector = cvlm.build_state_vector(_state())
    layer_vector = cvlm.build_layer_vector(_state())
    assert state_vector.shape == (8,)
    assert layer_vector.shape == (4,)
    assert np.all((state_vector >= 0.0) & (state_vector <= 1.0))
    assert np.isclose(layer_vector.sum(), 1.0)
    assert cvlm.state_distance_similarity(state_vector, state_vector) == 1.0
    assert np.isclose(cvlm.cosine_similarity(layer_vector, layer_vector), 1.0)


def test_similarity_weights_renormalize_when_a_branch_is_missing():
    parts = {"state": 0.8, "layer": 0.6, "trend": None, "text": 0.7}
    weights = {"state": 0.30, "layer": 0.25, "trend": 0.20, "text": 0.25}
    expected = (0.30 * 0.8 + 0.25 * 0.6 + 0.25 * 0.7) / 0.80
    assert np.isclose(cvlm.combine_similarity(parts, weights), expected)

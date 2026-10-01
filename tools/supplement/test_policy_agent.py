"""Offline tests for the provider-neutral CEMAS policy interface."""

import json

import cemas as ce
import covasim.llm_policy as cvlp


def test_policy_client_and_legacy_alias_are_identical():
    assert ce.PolicyClient is cvlp.PolicyClient
    assert cvlp.QwenPolicyClient is cvlp.PolicyClient


def test_policy_client_uses_explicit_provider_settings():
    client = cvlp.PolicyClient(
        api_key="test-only",
        base_url="https://provider.invalid",
        model="test-model",
        temperature=0.2,
        max_tokens=256,
    )
    assert client.api_key == "test-only"
    assert client.base_url == "https://provider.invalid"
    assert client.model == "test-model"
    assert client.temperature == 0.2
    assert client.max_tokens == 256


def test_policy_response_parser_and_catalog():
    payload = json.dumps({
        "policy_id": "P2_moderate",
        "risk_level": "high",
        "reason": "cases rising",
    })
    parsed = cvlp.parse_policy_response(payload)
    assert parsed["policy_id"] == "P2_moderate"
    assert parsed["risk_level"] == "high"
    assert set(cvlp.make_default_policy_catalog()) == set(cvlp.POLICY_IDS)


def test_policy_agent_can_be_constructed_without_api_call():
    agent = ce.campus_policy_agent(
        decision_fn=lambda *_args, **_kwargs: {
            "policy_id": "P1_guarded",
            "risk_level": "medium",
            "reason": "offline test",
        }
    )
    assert agent.client is None
    assert agent.decision_fn is not None
    assert agent.model == cvlp.DEFAULT_LLM_MODEL

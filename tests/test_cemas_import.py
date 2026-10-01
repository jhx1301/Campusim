"""Focused tests for the public CEMAS compatibility surface."""

import cemas as ce
import covasim.llm_policy as cvlp


def test_cemas_exports_sim_and_policy_client():
    assert ce.Sim is not None
    assert ce.PolicyClient is cvlp.PolicyClient
    assert ce.QwenPolicyClient is ce.PolicyClient
    assert ce.__version__ == "1.0.0"


def test_policy_client_prefers_generic_environment(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://generic.invalid")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://legacy.invalid")
    monkeypatch.setenv("LLM_MODEL", "generic-model")
    client = ce.PolicyClient()
    assert client.api_key == "generic-key"
    assert client.base_url == "https://generic.invalid"
    assert client.model == "generic-model"

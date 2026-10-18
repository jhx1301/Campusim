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


def test_control_import_does_not_load_or_export_development_acceptance():
    import subprocess
    import sys

    script = """
import sys
import cemas
import cemas.control as control
assert 'tools.memory_acceptance' not in sys.modules
assert 'cemas.control.memory_acceptance' not in sys.modules
for name in ('MEMORY_ACCEPTANCE_VERSION', 'MEMORY_PROBE_MODES',
             'accept_memory_llm', 'validate_memory_acceptance'):
    assert not hasattr(control, name)
    assert not hasattr(cemas, name)
assert control.MemoryLLMController is not None
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)

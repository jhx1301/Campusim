"""Public CEMAS API backed by the compatible Covasim-derived engine."""

import os

# Keep the public CEMAS import quiet by default. This also avoids console-encoding
# failures on Windows locales that cannot render Covasim's copyright symbol.
os.environ.setdefault("COVASIM_VERBOSE", "0")

from covasim import *  # noqa: F401,F403
from covasim import llm_memory, llm_policy

from .version import __version__, __versiondate__


PolicyClient = llm_policy.PolicyClient
QwenPolicyClient = llm_policy.QwenPolicyClient
MemoryStore = llm_memory.MemoryStore
EmbeddingProvider = llm_memory.EmbeddingProvider

# v1 control is loaded only when requested; SDK/tokenizer libraries stay lazy.
_CONTROL_EXPORTS = frozenset((
    "LLMController", "LLMTransport", "LLMSettings", "LLMResponse", "LLMCallAudit",
    "PublicPromptConfig", "ChatMessage", "OfficialInputTokenCounter", "PromptBudgetError",
    "LLMConfigurationError", "ActionResponseError", "TokenCountMismatchError",
    "build_public_messages", "parse_action_response", "make_llm_controller",
    "make_llm_settings", "make_public_prompt_config", "accept_llm_token_counter",
    "UniformLegalController", "MemoryProfile", "PublicEpisodeMemory", "PublicCase", "PublicMemoryContext",
    "FrozenPublicCaseStore", "PublicCaseBuilder", "NumericRetriever", "KnowledgeBundle", "MemoryLLMController",
    "build_memory_messages", "parse_memory_response", "make_memory_llm_controller", "memory_source_compatibility",
    "load_memory_profile", "load_knowledge_bundle", "freeze_public_store", "coverage_report",
))


def __getattr__(name):
    if name in _CONTROL_EXPORTS:
        from . import control

        value = getattr(control, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__license__ = (
    f"CEMAS {__version__} ({__versiondate__}); derived from Covasim v3.1.7 "
    "and distributed under the MIT License"
)

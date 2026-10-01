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

__license__ = (
    f"CEMAS {__version__} ({__versiondate__}); derived from Covasim v3.1.7 "
    "and distributed under the MIT License"
)

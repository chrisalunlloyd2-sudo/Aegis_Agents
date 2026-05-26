"""Single context and reply-size policy for AEGIS runtime lanes."""

from __future__ import annotations

import os
from typing import Any, Dict


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(os.getenv(name, str(default))), high))
    except ValueError:
        return default


OLLAMA_CHAT_TIMEOUT_SECONDS = env_int("AEGIS_OLLAMA_CHAT_TIMEOUT_SECONDS", 240, 20, 900)
OLLAMA_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS = env_int("AEGIS_OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS", 75, 15, 240)
OLLAMA_NUM_CTX_SIMPLE = env_int("AEGIS_OLLAMA_NUM_CTX_SIMPLE", 2048, 512, 32768)
OLLAMA_NUM_CTX_DEFAULT = env_int("AEGIS_OLLAMA_NUM_CTX_DEFAULT", 8192, 2048, 32768)
OLLAMA_NUM_CTX_LONG = env_int("AEGIS_OLLAMA_NUM_CTX_LONG", 12288, 4096, 65536)
RESPONSE_BUDGET_SIMPLE = env_int("AEGIS_RESPONSE_BUDGET_SIMPLE", 1536, 128, 8192)
RESPONSE_BUDGET_DEFAULT = env_int("AEGIS_RESPONSE_BUDGET_DEFAULT", 4096, 512, 12000)
RESPONSE_BUDGET_DELIBERATE = env_int("AEGIS_RESPONSE_BUDGET_DELIBERATE", 6144, 1024, 16000)
RESPONSE_BUDGET_FULL = env_int("AEGIS_RESPONSE_BUDGET_FULL", 8192, 1024, 24000)
RESPONSE_BUDGET_MAX = env_int("AEGIS_RESPONSE_BUDGET_MAX", 12000, 1024, 32000)

WORKER_CONTEXT_WINDOW = env_int("AEGIS_WORKER_NUM_CTX", 1024, 512, 8192)
PROGRAM_LOOP_CONTEXT_WINDOW = env_int("AEGIS_PROGRAM_LOOP_NUM_CTX", 3072, 1024, 16384)
ENGINE_CONTEXT_WINDOW = env_int("AEGIS_ENGINE_NUM_CTX", OLLAMA_NUM_CTX_DEFAULT, 1024, 32768)


def runtime_context_policy() -> Dict[str, Any]:
    return {
        "source_of_truth": "context_policy.py reading AEGIS_* environment variables",
        "timeout_seconds": OLLAMA_CHAT_TIMEOUT_SECONDS,
        "first_token_timeout_seconds": OLLAMA_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS,
        "num_ctx": {
            "simple": OLLAMA_NUM_CTX_SIMPLE,
            "default": OLLAMA_NUM_CTX_DEFAULT,
            "long": OLLAMA_NUM_CTX_LONG,
            "worker": WORKER_CONTEXT_WINDOW,
            "program_loop": PROGRAM_LOOP_CONTEXT_WINDOW,
            "engine": ENGINE_CONTEXT_WINDOW,
        },
        "response_budget": {
            "simple": RESPONSE_BUDGET_SIMPLE,
            "default": RESPONSE_BUDGET_DEFAULT,
            "deliberate": RESPONSE_BUDGET_DELIBERATE,
            "full": RESPONSE_BUDGET_FULL,
            "max": RESPONSE_BUDGET_MAX,
        },
        "anti_duplicate_rule": "Use these names for all runtime lanes; do not add competing context-window knobs.",
    }

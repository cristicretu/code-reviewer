"""Ensure deepeval is configured to use Ollama with Qwen3.5-14B as judge.

Call `ensure_config()` at the top of any eval script that uses deepeval.
"""

from __future__ import annotations

import os


def ensure_config(model_name: str = "qwen3:14b") -> None:
    os.environ.setdefault("LOCAL_MODEL_NAME", model_name)
    os.environ.setdefault("LOCAL_MODEL_API_KEY", "ollama")
    os.environ.setdefault("LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")

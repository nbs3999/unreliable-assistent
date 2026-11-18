"""Builds the configured LLM provider from settings. Returns None when no LLM is configured."""
from __future__ import annotations

import importlib

from assistant.llm.base import LLMError, LLMProvider
from assistant.llm.openai_compatible import OpenAICompatibleClient


def build_llm(provider: str, *, base_url: str | None, model: str | None,
              api_key: str | None, timeout_s: float) -> LLMProvider | None:
    provider = (provider or "none").strip()
    if provider in ("", "none"):
        return None
    if provider == "openai_compatible":
        if not model:
            raise LLMError("LLM_MODEL is required for the openai_compatible provider")
        return OpenAICompatibleClient(base_url or "", model, api_key, timeout_s)
    if ":" not in provider:
        raise LLMError(f"unknown LLM_PROVIDER '{provider}'")
    module_name, class_name = provider.split(":", 1)
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(base_url=base_url, model=model, api_key=api_key, timeout_s=timeout_s)

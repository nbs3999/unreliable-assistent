"""LLM provider interface. A provider is any object with `name` and `generate`.

Providers are plugged in and out by configuration only (LLM_PROVIDER), never by code edits:
  LLM_PROVIDER=none                                  -> extractive answers only (default)
  LLM_PROVIDER=openai_compatible                     -> any OpenAI-style /v1/chat/completions server
  LLM_PROVIDER=package.module:ClassName              -> your own provider class
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Any provider failure: unreachable, timeout, bad response. The pipeline falls back to extractive."""


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    max_tokens: int = 256


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LLMRequest) -> str: ...

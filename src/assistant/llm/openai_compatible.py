"""Client for any OpenAI-compatible chat server (llama.cpp server, Ollama, vLLM, TGI).

Uses only the standard library, so the API takes no extra dependency for this.
The model runs in its own process or container; this client only sends HTTP.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from assistant.llm.base import LLMError, LLMRequest


class OpenAICompatibleClient:
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout_s: float = 0.25, temperature: float = 0.0) -> None:
        if not base_url:
            raise LLMError("LLM_BASE_URL is required for the openai_compatible provider")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.temperature = temperature

    def generate(self, request: LLMRequest) -> str:
        body = json.dumps({
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "system", "content": request.system},
                         {"role": "user", "content": request.user}],
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:  # held in memory only; never logged or returned
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"LLM server unavailable or timed out: {type(exc).__name__}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("LLM server returned invalid JSON") from exc
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response missing choices[0].message.content") from exc
        if not isinstance(text, str):
            raise LLMError("LLM response content is not text")
        return text.strip()

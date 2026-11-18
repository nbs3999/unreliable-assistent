"""LLM provider layer: grounded generation, citation check, fallback, plug-in registry (no network)."""
import json
import uuid
from pathlib import Path

import pytest

from assistant.llm import INSUFFICIENT, LLMError, LLMRequest, build_llm, build_request
from assistant.llm.openai_compatible import OpenAICompatibleClient

from tests.integration.test_api import body, client  # noqa: F401  (fixture reuse)


class FakeLLM:
    name = "fake"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def generate(self, request: LLMRequest) -> str:
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.reply


def test_build_request_numbers_passages_and_forbids_uncited_answers():
    req = build_request("How long do refunds take?", ["Refunds take 5 days.", "Shipping is free."])
    assert "[1] Refunds take 5 days." in req.user and "[2] Shipping is free." in req.user
    assert INSUFFICIENT in req.system and "[1]" in req.system


def test_registry_default_is_none():
    assert build_llm("none", base_url=None, model=None, api_key=None, timeout_s=0.25) is None


def test_registry_openai_compatible_requires_model():
    with pytest.raises(LLMError):
        build_llm("openai_compatible", base_url="http://x", model=None, api_key=None, timeout_s=0.25)


def test_registry_loads_a_custom_plugin_by_dotted_path():
    p = build_llm("assistant.llm.openai_compatible:OpenAICompatibleClient", base_url="http://x:1/v1",
                  model="m", api_key=None, timeout_s=0.25)
    assert isinstance(p, OpenAICompatibleClient)


def test_registry_rejects_unknown_provider():
    with pytest.raises(LLMError):
        build_llm("nonsense", base_url=None, model=None, api_key=None, timeout_s=0.25)


def test_client_unreachable_server_raises_llm_error():
    c = OpenAICompatibleClient("http://127.0.0.1:9/v1", "m", timeout_s=0.2)
    with pytest.raises(LLMError):
        c.generate(LLMRequest("s", "u"))


def test_grounded_generation_is_served_with_mode_generated(client):  # noqa: F811
    c, deps = client
    deps.llm = FakeLLM(reply="Refunds are processed within 5 business days [1].")
    data = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?")).json()
    assert data["status"] == "ok" and data["mode"] == "generated"
    assert data["answer"].startswith("Refunds are processed")
    assert deps.llm.calls and "[1]" in deps.llm.calls[0].user


def test_uncited_generation_falls_back_to_extractive(client):  # noqa: F811
    c, deps = client
    deps.llm = FakeLLM(reply="Refunds take five days, trust me.")
    data = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?")).json()
    assert data["mode"] == "extractive" and data["answer"].startswith("From the approved documents")
    assert "llm_uncited" in data["degraded"]


def test_citation_to_nonexistent_passage_is_rejected(client):  # noqa: F811
    c, deps = client
    deps.llm = FakeLLM(reply="Refunds take five days [99].")
    data = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?")).json()
    assert "llm_uncited" in data["degraded"] and data["mode"] == "extractive"


def test_model_failure_falls_back_to_extractive(client):  # noqa: F811
    c, deps = client
    deps.llm = FakeLLM(error=LLMError("down"))
    r = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?"))
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "extractive" and "llm_unavailable" in data["degraded"]


def test_insufficient_context_reply_abstains(client):  # noqa: F811
    c, deps = client
    deps.llm = FakeLLM(reply=INSUFFICIENT)
    data = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?")).json()
    assert data["status"] == "abstained" and data["mode"] == "generated"


def test_no_llm_configured_keeps_extractive_default(client):  # noqa: F811
    c, deps = client
    assert deps.llm is None
    data = c.post("/api/v1/agent/query", json=body("What is the returns policy for refunds?")).json()
    assert data["mode"] == "extractive"

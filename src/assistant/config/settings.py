"""Environment-driven settings. Defaults match design.md."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    vault_dir: Path = PROJECT_ROOT / "knowledge_vault"
    allowed_tenants: tuple[str, ...] = field(default=("tenant_acme",))
    cache_ttl_s: float = 300.0
    cache_jitter_s: float = 45.0
    retrieval_backend: str = "full"  # "full" (dense + cross-encoder) or "lexical" (BM25 only, fast)
    embed_model: str = "BAAI/bge-large-en-v1.5"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    api_keys_file: Path | None = None  # JSON list of hashed key bindings (api/auth.py)
    llm_provider: str = "none"  # none | openai_compatible | package.module:ClassName
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None  # from env only; never logged
    llm_timeout_s: float = 0.25  # design LLM step budget; raise for CPU-hosted models


def load_settings() -> Settings:
    tenants = tuple(t.strip() for t in os.getenv("ALLOWED_TENANTS", "tenant_acme").split(",") if t.strip())
    return Settings(
        vault_dir=Path(os.getenv("VAULT_DIR", str(PROJECT_ROOT / "knowledge_vault"))),
        allowed_tenants=tenants,
        retrieval_backend=os.getenv("RETRIEVAL_BACKEND", "full"),
        embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5"),
        rerank_model=os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
        api_keys_file=Path(os.environ["API_KEYS_FILE"]) if os.getenv("API_KEYS_FILE") else None,
        llm_provider=os.getenv("LLM_PROVIDER", "none"),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=os.getenv("LLM_MODEL") or None,
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_timeout_s=float(os.getenv("LLM_TIMEOUT_S", "0.25")),
    )

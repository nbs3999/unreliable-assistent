"""Pydantic v2 contracts. Source of truth: design.md § 1.2.

Models are strict (no type coercion) and forbid unknown fields.
"""
from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

TENANT_RE = re.compile(r"^tenant_[a-z0-9_-]{1,56}$")
USER_RE = re.compile(r"^user_[a-z0-9_-]{1,64}$")
HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
ACTION_RE = re.compile(r"^[a-z_]{3,48}$")


def is_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value, version=4)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value.lower()


class Tier(str, Enum):
    TIER_1_READ = "TIER_1_READ"
    TIER_2_COMPUTE = "TIER_2_COMPUTE"
    TIER_3_MUTATE = "TIER_3_MUTATE"


class Route(str, Enum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    HYBRID_RAG = "HYBRID_RAG"
    TRANSACTION_EXEC = "TRANSACTION_EXEC"
    REJECT_OOS = "REJECT_OOS"


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class QueryRequest(StrictModel):
    """POST /api/v1/agent/query body."""
    request_id: str
    tenant_id: str
    user_id: str
    query: str = Field(min_length=3, max_length=512)

    @field_validator("request_id")
    @classmethod
    def _uuid4(cls, v: str) -> str:
        if not is_uuid4(v):
            raise ValueError("request_id must be a UUIDv4")
        return v.lower()

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, v: str) -> str:
        if not TENANT_RE.match(v):
            raise ValueError("tenant_id does not match ^tenant_[a-z0-9_-]{1,56}$")
        return v

    @field_validator("user_id")
    @classmethod
    def _user(cls, v: str) -> str:
        if not USER_RE.match(v):
            raise ValueError("user_id does not match ^user_[a-z0-9_-]{1,64}$")
        return v


class HybridRetrieveInput(StrictModel):
    request_id: str
    tenant_id: str
    query: str = Field(min_length=3, max_length=512)
    top_k: int = Field(default=50, ge=1, le=50)
    rerank_k: int = Field(default=4, ge=1, le=4)
    threshold: float = Field(default=0.42, ge=0.0, le=1.0)

    @field_validator("request_id")
    @classmethod
    def _uuid4(cls, v: str) -> str:
        if not is_uuid4(v):
            raise ValueError("request_id must be a UUIDv4")
        return v.lower()

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, v: str) -> str:
        if not TENANT_RE.match(v):
            raise ValueError("tenant_id does not match the design.md pattern")
        return v


class ChunkOut(StrictModel):
    chunk_id: str = Field(pattern=r"^[a-z0-9_-]{1,128}$")
    chunk_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    text: str = Field(max_length=4096)
    bm25: float
    cosine: float
    rrf_rank: int = Field(ge=1, le=40)
    rerank_score: float = Field(ge=0.0, le=1.0)


class HybridRetrieveOutput(StrictModel):
    abstain: bool
    chunks: list[ChunkOut] = Field(max_length=4)
    stage_ms: dict[str, float] = Field(default_factory=dict)


class Tier3ActionInput(StrictModel):
    """Input for workflow_transition / hitl_request (design.md § 1.2.2)."""
    request_id: str
    idempotency_key: str
    tenant_id: str
    action: str = Field(pattern=r"^[a-z_]{3,48}$")
    args: dict[str, Any] = Field(default_factory=dict)
    risk_tier: Tier = Tier.TIER_3_MUTATE

    @field_validator("request_id", "idempotency_key")
    @classmethod
    def _uuid4(cls, v: str) -> str:
        if not is_uuid4(v):
            raise ValueError("must be a UUIDv4")
        return v.lower()


class ResponseSource(StrictModel):
    chunk_id: str
    chunk_hash: str


class QueryResponse(StrictModel):
    request_id: str
    route: Route
    status: str  # ok | abstained | pending_approval | refused | degraded
    answer: str
    sources: list[ResponseSource] = Field(default_factory=list)
    mode: str = "extractive"  # "generated" when an LLM provider answered; see deployment.md
    degraded: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)

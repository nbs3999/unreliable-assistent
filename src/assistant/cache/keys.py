"""Cache key = SHA256(tenant_id:user_id:norm_query) (design.md ADR-03, Gate 9)."""
from __future__ import annotations

import hashlib

from assistant.contracts.models import TENANT_RE, USER_RE


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def build_key(tenant_id: str, user_id: str, query: str) -> str:
    if not TENANT_RE.match(tenant_id) or not USER_RE.match(user_id):
        raise ValueError("cache keys require valid tenant_id and user_id")
    raw = f"{tenant_id}:{user_id}:{normalize_query(query)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

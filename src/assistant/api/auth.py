"""API-key authentication with identity binding (gaps.md § 1.1).

Each key is bound to one tenant, one user, and a set of roles. The server never stores
the raw key: the keys file holds only SHA-256 digests. Create entries with
`scripts/make_api_key.py`.

Keys file (path from API_KEYS_FILE), JSON list:
  [{"key_sha256": "<hex>", "tenant_id": "tenant_acme", "user_id": "user_1", "roles": ["user"]}]

Roles: "user" (may query), "reviewer" (may list and decide Tier 3 approvals).
With no keys file configured, every authenticated route returns 401.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, status

ROLE_USER = "user"
ROLE_REVIEWER = "reviewer"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def has(self, role: str) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class _KeyEntry:
    digest: str
    principal: Principal


def digest_of(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class KeyStore:
    def __init__(self, entries: list[_KeyEntry] | None = None) -> None:
        self._entries = entries or []

    @classmethod
    def from_file(cls, path: Path | None) -> "KeyStore":
        if path is None or not Path(path).is_file():
            return cls([])
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = []
        for item in raw:
            digest = str(item["key_sha256"]).lower()
            if len(digest) != 64:
                raise ValueError("key_sha256 must be a 64-char hex SHA-256 digest")
            entries.append(_KeyEntry(digest, Principal(
                tenant_id=item["tenant_id"], user_id=item["user_id"],
                roles=frozenset(item.get("roles", [ROLE_USER])))))
        return cls(entries)

    def authenticate(self, token: str | None) -> Principal | None:
        if not token:
            return None
        digest = digest_of(token)
        match: Principal | None = None
        # Compare against every entry so timing does not reveal which key prefix matched.
        for entry in self._entries:
            if hmac.compare_digest(entry.digest, digest):
                match = entry.principal
        return match


def bearer_token(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_api_key or None


def require_principal(keys: KeyStore, authorization: str | None, x_api_key: str | None,
                      role: str = ROLE_USER) -> Principal:
    principal = keys.authenticate(bearer_token(authorization, x_api_key))
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="missing or invalid API key",
                            headers={"WWW-Authenticate": "Bearer"})
    if not principal.has(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"role '{role}' required")
    return principal

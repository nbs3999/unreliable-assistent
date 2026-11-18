import random
import pytest
from assistant.cache import SemanticCacheStore, build_key, normalize_query


def test_key_is_sha256_and_normalizes_case_and_spaces():
    a = build_key("tenant_acme", "user_1", "  Returns   Policy? ")
    b = build_key("tenant_acme", "user_1", "returns policy?")
    assert a == b and len(a) == 64


def test_key_differs_across_tenants_and_users():
    base = build_key("tenant_acme", "user_1", "q")
    assert build_key("tenant_globex", "user_1", "q") != base
    assert build_key("tenant_acme", "user_2", "q") != base


def test_key_rejects_invalid_tenant():
    with pytest.raises(ValueError):
        build_key("acme", "user_1", "q")


def test_ttl_is_jittered_within_bounds():
    clock = {"t": 0.0}
    store = SemanticCacheStore(clock=lambda: clock["t"], rng=random.Random(1))
    store.set("k", "tenant_acme", "v")
    entry = store._data["k"]
    assert 255.0 <= entry.expires_at <= 345.0


def test_tenant_mismatch_on_hit_is_a_miss_and_counted():
    store = SemanticCacheStore()
    store.set("k", "tenant_acme", "secret")
    assert store.get("k", "tenant_globex") is None
    assert store.isolation_violations == 1


def test_expired_entries_are_dropped():
    clock = {"t": 0.0}
    store = SemanticCacheStore(base_ttl_s=10, jitter_s=0, clock=lambda: clock["t"])
    store.set("k", "tenant_acme", "v")
    clock["t"] = 11
    assert store.get("k", "tenant_acme") is None

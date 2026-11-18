"""KPI-28: cross-tenant cache isolation."""
from assistant.cache import SemanticCacheStore, build_key


def test_same_query_different_tenants_never_share_entries():
    store = SemanticCacheStore()
    key_a = build_key("tenant_acme", "user_1", "salary bands")
    store.set(key_a, "tenant_acme", "acme-only answer")
    key_b = build_key("tenant_globex", "user_1", "salary bands")
    assert key_a != key_b
    assert store.get(key_b, "tenant_globex") is None


def test_forged_key_collision_is_still_blocked_by_tenant_recheck():
    store = SemanticCacheStore()
    store.set("same-key", "tenant_acme", "acme-only answer")
    assert store.get("same-key", "tenant_globex") is None
    assert store.isolation_violations == 1

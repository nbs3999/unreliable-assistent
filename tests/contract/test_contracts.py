import pytest
from pydantic import ValidationError
from assistant.contracts import HybridRetrieveInput, QueryRequest, Route, Tier, Tier3ActionInput

GOOD_UUID = "3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f"


def test_query_request_accepts_valid_body():
    r = QueryRequest(request_id=GOOD_UUID, tenant_id="tenant_acme", user_id="user_7",
                     query="What is the returns policy?")
    assert r.tenant_id == "tenant_acme"


@pytest.mark.parametrize("field,value", [
    ("request_id", "not-a-uuid"),
    ("request_id", "3f1c2a9e-7b4d-1c1a-9e2f-1a2b3c4d5e6f"),  # version 1, not v4
    ("tenant_id", "Acme"),
    ("user_id", "bob"),
    ("query", "hi"),
])
def test_query_request_rejects_bad_fields(field, value):
    base = dict(request_id=GOOD_UUID, tenant_id="tenant_acme", user_id="user_7", query="valid query")
    base[field] = value
    with pytest.raises(ValidationError):
        QueryRequest(**base)


def test_strict_mode_rejects_coercion():
    with pytest.raises(ValidationError):
        HybridRetrieveInput(request_id=GOOD_UUID, tenant_id="tenant_acme", query="valid", top_k="5")


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        QueryRequest(request_id=GOOD_UUID, tenant_id="tenant_acme", user_id="user_7",
                     query="valid query", admin=True)


def test_retrieval_limits_match_design():
    assert HybridRetrieveInput(request_id=GOOD_UUID, tenant_id="tenant_acme", query="abc").threshold == 0.42
    with pytest.raises(ValidationError):
        HybridRetrieveInput(request_id=GOOD_UUID, tenant_id="tenant_acme", query="abc", top_k=51)


def test_tier3_defaults_to_mutate_tier():
    t = Tier3ActionInput(request_id=GOOD_UUID, idempotency_key=GOOD_UUID,
                         tenant_id="tenant_acme", action="submit_form")
    assert t.risk_tier is Tier.TIER_3_MUTATE


def test_route_enum_matches_design():
    assert {r.value for r in Route} == {"DIRECT_ANSWER", "HYBRID_RAG", "TRANSACTION_EXEC", "REJECT_OOS"}

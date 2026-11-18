from pathlib import Path
from assistant.rag import BM25, KnowledgeBase, reciprocal_rank_fusion, retrieve, tokenize
from assistant.rag.reranker import lexical_rerank_score

VAULT = Path(__file__).resolve().parents[2] / "knowledge_vault"


def test_bm25_ranks_exact_term_match_first():
    docs = [tokenize("pressure relief valve sku 099"), tokenize("returns policy refunds")]
    scores = BM25(docs).scores(tokenize("sku 099"))
    assert scores[0] > scores[1] == 0.0


def test_rrf_rewards_agreement_and_caps_pool():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60, pool=2)
    assert [x[0] for x in fused] == ["a", "b"]  # equal scores, tie broken by id
    assert len(fused) == 2


def test_reranker_scores_coverage():
    assert lexical_rerank_score("returns policy", "the returns policy says 30 days") == 1.0
    assert lexical_rerank_score("returns policy", "weather today") == 0.0


def test_knowledge_base_loads_vault_with_frontmatter_ids():
    kb = KnowledgeBase.load(VAULT)
    ids = {c.chunk_id for c in kb.chunks}
    assert "returns-policy-001-p1" in ids
    assert all(c.chunk_hash and len(c.chunk_hash) == 64 for c in kb.chunks)


def test_retrieval_answers_from_vault_and_abstains_on_unrelated():
    kb = KnowledgeBase.load(VAULT)
    hit = retrieve(kb, "What is the returns policy for refunds?")
    assert not hit.abstain
    assert "dense_unavailable" in hit.degraded
    miss = retrieve(kb, "warranty on forklift batteries")
    assert miss.abstain and miss.chunks == []


def test_sku_query_finds_catalog_note():
    kb = KnowledgeBase.load(VAULT)
    res = retrieve(kb, "pressure relief valve SKU-099")
    assert not res.abstain
    assert res.chunks[0]["chunk_id"].startswith("catalog-sku-099")

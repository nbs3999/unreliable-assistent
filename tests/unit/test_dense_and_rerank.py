"""Dense and cross-encoder stages, tested with stub models (no downloads)."""
from pathlib import Path
import numpy as np
import pytest
from assistant.rag import CrossEncoderReranker, DenseIndex, KnowledgeBase, retrieve

VAULT = Path(__file__).resolve().parents[2] / "knowledge_vault"


class StubEncoder:
    """Maps a text to a fixed 8-dim vector by a keyword vocabulary. Deterministic, no model."""
    VOCAB = ["valve", "return", "refund", "shipping", "pump", "password", "leave", "gasket"]

    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False):
        out = []
        for t in texts:
            low = t.lower()
            v = np.array([1.0 if w in low else 0.0 for w in self.VOCAB], dtype="float32") + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


class StubCrossEncoder:
    """Scores by word overlap. Mirrors the real CrossEncoder.predict contract: returns raw
    logits when activation_fn is Identity, and sigmoid probabilities by default."""
    def predict(self, pairs, show_progress_bar=False, activation_fn=None):
        logits = []
        for q, t in pairs:
            overlap = len(set(q.lower().split()) & set(t.lower().split()))
            logits.append(overlap - 1.0)  # 1 shared word -> p=0.5 (passes 0.42), 0 -> p=0.27
        logits = np.array(logits, dtype="float32")
        if activation_fn is None:  # real default: already a probability
            return 1.0 / (1.0 + np.exp(-logits))
        return logits


def test_cross_encoder_sigmoid_is_applied_once_to_raw_logits():
    # Regression for gaps.md Phase 3: logit 0 must map to 0.5, not to sigmoid(sigmoid(0)).
    class ZeroLogit:
        def predict(self, pairs, show_progress_bar=False, activation_fn=None):
            assert activation_fn is not None, "must request raw logits"
            return np.zeros(len(pairs), dtype="float32")
    scores = CrossEncoderReranker(model=ZeroLogit()).score("q", ["a", "b"])
    assert scores == [0.5, 0.5]


def test_dense_index_returns_best_match_first():
    kb = KnowledgeBase.load(VAULT)
    idx = DenseIndex([c.search_text for c in kb.chunks], [c.chunk_id for c in kb.chunks], encoder=StubEncoder())
    hits = idx.search("pump", top_k=5)
    assert hits[0][0].startswith("catalog-sku-120")
    assert all(-1.0 <= s <= 1.0 + 1e-5 for _, s in hits)


def test_dense_index_rejects_misaligned_inputs():
    with pytest.raises(ValueError):
        DenseIndex(["a", "b"], ["only-one"], encoder=StubEncoder())


def test_cross_encoder_applies_sigmoid_to_logits():
    rr = CrossEncoderReranker(model=StubCrossEncoder())
    scores = rr.score("returns refund policy", ["refund policy for returns", "pump maintenance"])
    assert all(0.0 < s < 1.0 for s in scores)
    assert scores[0] > scores[1]


def test_full_pipeline_with_stub_models_is_not_degraded_and_abstains_on_noise():
    kb = KnowledgeBase.load(VAULT)
    dense = DenseIndex([c.search_text for c in kb.chunks], [c.chunk_id for c in kb.chunks], encoder=StubEncoder())
    rr = CrossEncoderReranker(model=StubCrossEncoder())
    res = retrieve(kb, "return refund policy", dense=dense, reranker=rr)
    assert "dense_unavailable" not in res.degraded
    assert "reranker_fallback_lexical" not in res.degraded
    assert not res.abstain
    assert all(c["cosine"] >= 0.0 for c in res.chunks)
    noise = retrieve(kb, "xylophone quartz zebra", dense=dense, reranker=rr)
    assert noise.abstain


def test_missing_models_are_reported_as_degraded_not_silent():
    kb = KnowledgeBase.load(VAULT)
    res = retrieve(kb, "return refund policy")
    assert {"dense_unavailable", "reranker_fallback_lexical"} <= set(res.degraded)

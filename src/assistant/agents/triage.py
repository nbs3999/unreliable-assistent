"""Triage Agent: deterministic, temperature 0, no LLM (design.md § 1.9).

Routes to DIRECT_ANSWER, HYBRID_RAG, TRANSACTION_EXEC, or REJECT_OOS. Low confidence
defaults to HYBRID_RAG (read-only). TRANSACTION_EXEC requires an explicit action verb.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from assistant.contracts import Route, Tier

_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you)\b", re.I)
_TRANSACTION = re.compile(r"\b(approve|submit|transfer|cancel|create|update|delete|order)\b", re.I)
_OUT_OF_SCOPE = re.compile(r"\b(weather|lottery|joke|recipe|horoscope|stock price)\b", re.I)


@dataclass(frozen=True)
class TriageResult:
    route: Route
    risk_tier: Tier
    confidence: float


def classify(query: str) -> TriageResult:
    if _GREETING.search(query):
        return TriageResult(Route.DIRECT_ANSWER, Tier.TIER_1_READ, 0.95)
    if _OUT_OF_SCOPE.search(query):
        return TriageResult(Route.REJECT_OOS, Tier.TIER_1_READ, 0.9)
    if _TRANSACTION.search(query):
        return TriageResult(Route.TRANSACTION_EXEC, Tier.TIER_3_MUTATE, 0.8)
    return TriageResult(Route.HYBRID_RAG, Tier.TIER_1_READ, 0.6)

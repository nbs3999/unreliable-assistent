# ADR-03 — Cache key isolation: per-user keys
Status: Accepted (design.md § 9.1).
Decision: key = SHA256(tenant_id:user_id:normalized_query), TTL 300 s ± 45 s. Every hit re-checks the stored tenant; a mismatch is a miss and is counted as an isolation violation (KPI-28).
Trade-off: no cross-user sharing, so KPI-27 (≥35% hits) depends on repeat queries by the same user. Revisit only if measured hit ratio falls short.
Implemented in `src/assistant/cache/`.

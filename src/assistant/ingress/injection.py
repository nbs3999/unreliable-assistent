"""Prompt-injection screen (injection_shield plugin, KPI-03). Heuristic; a classifier replaces it later."""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+(instructions|prompts?)", re.I),
    re.compile(r"(reveal|print|show|repeat)\s+(your|the)\s+(system\s+prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(developer|dan|unrestricted)\s+mode", re.I),
    re.compile(r"</?(system|assistant)>", re.I),
]


def find_injection(text: str) -> list[str]:
    """Returns the matched pattern names; empty list means clean."""
    return [p.pattern[:40] for p in _PATTERNS if p.search(text)]

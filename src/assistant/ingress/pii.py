"""PII redaction (pii_redactor plugin, KPI-02). Regex-based; Presidio is a planned upgrade."""
from __future__ import annotations

import re

# Order matters: obfuscated forms first, so the plain-email rule doesn't split them.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+\s*(?:@|\[at\]|\(at\)|\sat\s)\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(r"(?<![A-Za-z0-9-])\+?\d[\d\s().-]{8,}\d(?![A-Za-z0-9-])")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pattern in _RULES:
        text, n = pattern.subn(f"[{label}_REDACTED]", text)
        if n:
            counts[label] = n
    return text, counts

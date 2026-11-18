"""Deterministic regex auto-repair (design.md § 1.2.4 step 2). No LLM is used here."""
from __future__ import annotations

import re
from typing import Callable

SKU_RE = re.compile(r"^\s*SKU[\s-]*(\d{1,3})\s*$", re.IGNORECASE)
LOT_RE = re.compile(r"^\s*LOT[\s-]*(\d{1,5})\s*$", re.IGNORECASE)


def repair_sku(value: str) -> str | None:
    """'SKU99' -> 'SKU-099'."""
    m = SKU_RE.match(value)
    return f"SKU-{int(m.group(1)):03d}" if m else None


def repair_lot(value: str) -> str | None:
    """'lot 44' -> 'LOT-00044'."""
    m = LOT_RE.match(value)
    return f"LOT-{int(m.group(1)):05d}" if m else None


REPAIRS: dict[str, Callable[[str], str | None]] = {"sku": repair_sku, "lot": repair_lot}


def repair_args(args: dict) -> tuple[dict, list[dict]]:
    """Repair known code fields. Returns (new_args, repairs) where each repair
    records the original and corrected values so they can be audited."""
    out = dict(args)
    repairs: list[dict] = []
    for field, fn in REPAIRS.items():
        value = out.get(field)
        if isinstance(value, str):
            fixed = fn(value)
            if fixed is not None and fixed != value:
                out[field] = fixed
                repairs.append({"field": field, "original": value, "repaired": fixed})
    return out, repairs


_CODE_IN_TEXT = {
    "sku": (re.compile(r"\bSKU[\s-]?\d{1,3}\b", re.IGNORECASE), repair_sku),
    "lot": (re.compile(r"\bLOT[\s-]?\d{1,5}\b", re.IGNORECASE), repair_lot),
}


def repair_codes_in_text(text: str) -> str:
    """Repair SKU/LOT codes inside free text, e.g. 'SKU99' -> 'SKU-099' in a query."""
    for pattern, fn in _CODE_IN_TEXT.values():
        text = pattern.sub(lambda m: fn(m.group(0)) or m.group(0), text)
    return text

"""Loads Obsidian-style notes (YAML-like frontmatter + markdown) into chunks."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SLUG = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    chunk_hash: str
    text: str
    search_text: str
    note_id: str
    domain: str
    risk_tier: str


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

    @classmethod
    def load(cls, root: Path) -> "KnowledgeBase":
        chunks: list[Chunk] = []
        for path in sorted(Path(root).rglob("*.md")):
            if path.name.lower() == "readme.md":
                continue  # vault documentation, not knowledge
            chunks.extend(_chunk_note(path.read_text(encoding="utf-8")))
        return cls(chunks)


def _parse_frontmatter(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def _chunk_note(raw: str) -> list[Chunk]:
    meta: dict[str, str] = {}
    body = raw
    m = _FRONTMATTER.match(raw)
    if m:
        meta = _parse_frontmatter(m.group(1))
        body = raw[m.end():]
    note_id = _SLUG.sub("-", meta.get("id", "unknown").lower()).strip("-") or "unknown"
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    out: list[Chunk] = []
    for i, text in enumerate(paragraphs, start=1):
        out.append(Chunk(
            chunk_id=f"{note_id}-p{i}",
            chunk_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            text=text,
            search_text=f"{note_id} {meta.get('domain', '')} {text}",
            note_id=note_id,
            domain=meta.get("domain", "general"),
            risk_tier=meta.get("risk_tier", "TIER_1_READ"),
        ))
    return out

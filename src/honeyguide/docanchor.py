"""Document anchors: where an annotation sits in the map's or an answer's text.

When the text is regenerated, an anchor is re-found by its quote, using the surrounding context to break ties.
Anything else is ``unresolved`` and must be shown flagged, never attached to the nearest text.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace

CONTEXT_CHARS = 32


def context_hash(text: str, start: int, end: int) -> str:
    before = text[max(0, start - CONTEXT_CHARS):start]
    after = text[end:end + CONTEXT_CHARS]
    return hashlib.sha256(f"{before}\x00{after}".encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DocumentAnchor:
    doc: str          # "map" or "answer:<response id>"
    revision: str
    quote: str
    start: int        # character offsets into the document's plain text
    end: int
    context: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentAnchor":
        return cls(data["doc"], str(data["revision"]), data["quote"], int(data["start"]),
                   int(data["end"]), data["context"])


def make_anchor(doc: str, revision: str, text: str, start: int, end: int) -> DocumentAnchor:
    if not 0 <= start < end <= len(text):
        raise ValueError(f"offsets {start}..{end} outside a {len(text)}-character document")
    return DocumentAnchor(doc, revision, text[start:end], start, end, context_hash(text, start, end))


@dataclass(frozen=True)
class Reanchor:
    status: str                    # same, resolved, unresolved
    anchor: DocumentAnchor | None  # the updated anchor when resolved
    reason: str = ""


def reanchor(anchor: DocumentAnchor, text: str, revision: str) -> Reanchor:
    """Find ``anchor`` in a new revision of its document."""
    if revision == anchor.revision:
        return Reanchor("same", anchor)
    hits = []
    i = text.find(anchor.quote)
    while i != -1 and anchor.quote:
        hits.append(i)
        i = text.find(anchor.quote, i + 1)
    if not hits:
        return Reanchor("unresolved", None, "quote no longer in the text")
    if len(hits) > 1:
        hits = [h for h in hits if context_hash(text, h, h + len(anchor.quote)) == anchor.context]
        if len(hits) != 1:
            return Reanchor("unresolved", None, "quote occurs several times and the context doesn't decide")
    start = hits[0]
    end = start + len(anchor.quote)
    return Reanchor("resolved", replace(anchor, revision=revision, start=start, end=end,
                                        context=context_hash(text, start, end)))

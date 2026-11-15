"""Retrieval for the Investigator and Tracer: saved map claims and earlier answers about the same code.

Matched by anchor (same lines 3, same symbol 2, same file 1); keyword overlap is a fallback used only when no
anchor matches. No embeddings. Stale and retired claims and claims the Checker rejected are left out unless
asked for, and then come back marked. Notes reach an agent only when marked "share with agents".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SCORE_LINES, SCORE_SYMBOL, SCORE_FILE = 3, 2, 1
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_STOP = {"what", "when", "where", "which", "does", "this", "that", "with", "from", "into", "there", "their",
         "have", "they", "then", "than", "about", "how", "why", "the", "and", "for", "are", "here", "used",
         "uses", "called", "call", "calls", "code", "function", "class", "method", "file", "line", "lines"}


@dataclass
class Context:
    """What a question is about. ``anchors`` are code anchors (dicts with path, start, end, optional symbol),
    typically those of the claims the selected text covers (``claim_ids``)."""

    text: str = ""
    anchors: list[dict] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


@dataclass
class Hit:
    claim: dict
    response_id: str | None      # None for a map claim
    score: int
    reasons: list[str]
    marked: str | None = None    # stale, retired or not_supported when such a claim is returned at all


@dataclass
class Retrieved:
    map_claims: list[Hit]
    answers: list[dict]          # {"response": ..., "question": ..., "hits": [Hit], "has_unservable": bool}
    notes: list[dict]


def keywords(text: str) -> set[str]:
    words = set()
    for word in _WORD.findall(text):
        for part in [word, *word.split(".")]:
            low = part.lower()
            if len(low) >= 4 and low not in _STOP:
                words.add(low)
    return words


def _symbol_matches(wanted: str, symbol: str | None) -> bool:
    if not symbol:
        return False
    return wanted == symbol or symbol.endswith("." + wanted) or wanted.endswith("." + symbol)


def anchor_score(claim: dict, ctx: Context) -> tuple[int, list[str]]:
    best, reasons = 0, []
    for a in claim.get("anchors", []):
        for c in ctx.anchors:
            if c["path"] == a["path"] and c["start"] <= a["end"] and a["start"] <= c["end"]:
                score, why = SCORE_LINES, f"same lines {a['path']}:{a['start']}-{a['end']}"
            elif c.get("symbol") and c.get("symbol") == a.get("symbol"):
                score, why = SCORE_SYMBOL, f"same symbol {a['symbol']}"
            elif c["path"] == a["path"]:
                score, why = SCORE_FILE, f"same file {a['path']}"
            else:
                continue
            if score > best:
                best, reasons = score, [why]
        for s in ctx.symbols:
            if _symbol_matches(s, a.get("symbol")) and SCORE_SYMBOL > best:
                best, reasons = SCORE_SYMBOL, [f"mentions {s}"]
        if a["path"] in ctx.paths and SCORE_FILE > best:
            best, reasons = SCORE_FILE, [f"mentions {a['path']}"]
    return best, reasons


def _unservable(claim: dict) -> str | None:
    if claim.get("freshness") in ("stale", "retired"):
        return claim["freshness"]
    if claim.get("check") == "not_supported":
        return "not_supported"
    return None


def retrieve(map_layer: dict, answers_layer: dict, notes_layer: dict, ctx: Context, *,
             include_stale: bool = False, limit: int = 20) -> Retrieved:
    every = [(None, c) for c in map_layer["claims"]]
    every += [(r["id"], c) for r in answers_layer["responses"] for c in r["claims"]]
    by_id = {c["id"]: c for _, c in every}
    ctx = Context(ctx.text, list(ctx.anchors), list(ctx.claim_ids), list(ctx.paths), list(ctx.symbols))
    for claim_id in ctx.claim_ids:
        ctx.anchors.extend(by_id.get(claim_id, {}).get("anchors", []))

    hits: list[Hit] = []
    for response_id, claim in every:
        score, reasons = anchor_score(claim, ctx)
        if score:
            hits.append(Hit(claim, response_id, score, reasons))
    if not hits:
        wanted = keywords(ctx.text) | {s.lower() for s in ctx.symbols}
        for response_id, claim in every:
            shared = wanted & keywords(claim["text"] + " " + " ".join(a["anchor"] for a in claim["anchors"]))
            if shared:
                hits.append(Hit(claim, response_id, len(shared), [f"keywords: {', '.join(sorted(shared))}"]))

    kept = []
    for hit in hits:
        hit.marked = _unservable(hit.claim)
        if hit.marked is None or include_stale:
            kept.append(hit)
    kept.sort(key=lambda h: -h.score)
    kept = kept[:limit]

    questions = {q["id"]: q for q in answers_layer["questions"]}
    responses = {r["id"]: r for r in answers_layer["responses"]}
    answers: dict[str, dict] = {}
    for hit in kept:
        if hit.response_id is None:
            continue
        response = responses[hit.response_id]
        entry = answers.setdefault(hit.response_id, {
            "response": response, "question": questions.get(response["parent"]), "hits": [],
            "has_unservable": any(_unservable(c) for c in response["claims"])})
        entry["hits"].append(hit)

    hit_claims = {h.claim["id"] for h in kept}
    hit_docs = {f"answer:{rid}" for rid in answers}
    words = keywords(ctx.text)
    notes = []
    for note in notes_layer["notes"]:
        if note.get("share_with_agents") is not True:
            continue  # personal: never handed to an agent
        anchor = note.get("anchor") or {}
        if (set(note.get("claim_ids", [])) & hit_claims or anchor.get("doc") in hit_docs
                or words & keywords(note["text"])):
            notes.append(note)
    return Retrieved([h for h in kept if h.response_id is None], list(answers.values()), notes)

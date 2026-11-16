"""Split an ad-hoc answer's text into units to check: sentences, list items, headings. Deterministic, no LLM.

Rules (tested in tests/test_eval_adhoc.py with text from the pilot's answers):
  - Blocks come from lines. A list item (`-`, `*`, `+`, `1.`, `1)`, `a.`, `a)` at the start of a line, any
    indent) starts a new block, and so does a markdown heading (`# ...`). A blank line ends a paragraph; a line
    that is neither joins the block before it (a wrapped paragraph or item). A fenced code block is one unit.
  - Each block is split into sentences: at `.`, `!` or `?` (with any closing `)`, `]`, quote, `*` or `_` after
    it) followed by whitespace. Never inside a code span (`...`), after an ellipsis, or after e.g., i.e., vs.,
    cf., approx., incl., resp., et al.; after etc. only when the next word starts with a capital. Dots that are
    not followed by whitespace never split: file.py:123, 0.8, nanochat/gpt.py.
  - A list item is never merged with its neighbours: each item is at least one unit, more when it holds several
    sentences.
  - A bold lead-in that is a sentence on its own (`**Setup before the loop.** If the run ...`) is kept with the
    sentence after it in the same block; a bold line alone (`**Order inside each iteration.**`) is its own unit.
Unit text is the block's text without its list marker, whitespace runs collapsed to one space; markdown is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ITEM = re.compile(r"^(\s*)(?:[-*+•]|\d{1,3}[.)]|[a-z][.)]|\([a-z0-9]{1,3}\))\s+(.*)$")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
BOUNDARY = re.compile(r"[.!?]+[)\]\"'”’*_]*(?=\s)")
NEVER_AFTER = ("e.g", "i.e", "vs", "cf", "approx", "incl", "resp", "al")
BOLD_ONLY = re.compile(r"^\*\*[^*]+\*\*:?$")


@dataclass(frozen=True)
class Unit:
    id: str        # "<run id>#s<k>", k from 1
    text: str
    kind: str      # "para", "item", "heading" or "code"
    level: int     # list nesting (0 for paragraphs and top-level items)


def _blocks(text: str) -> list[tuple[str, int, str]]:
    """(kind, level, text) per block, in order."""
    out: list[list] = []
    cur: list | None = None
    indents: list[int] = []
    fence: list[str] | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if fence is not None:
            fence.append(line)
            if FENCE.match(line):
                out.append(["code", 0, "\n".join(fence)])
                fence = None
            continue
        if FENCE.match(line):
            fence = [line]
            cur = None
            continue
        if not line.strip():
            cur = None
            continue
        m = ITEM.match(line)
        h = HEADING.match(line)
        if m:
            ind = len(m.group(1).expandtabs(4))
            while indents and indents[-1] > ind:
                indents.pop()
            if not indents or indents[-1] < ind:
                indents.append(ind)
            cur = ["item", len(indents) - 1, m.group(2)]
            out.append(cur)
        elif h:
            out.append(["heading", 0, h.group(2)])
            cur = None
        elif cur is not None:
            cur[2] += " " + line.strip()
        else:
            indents = []
            cur = ["para", 0, line.strip()]
            out.append(cur)
    if fence is not None:                      # an unclosed fence: keep what there is
        out.append(["code", 0, "\n".join(fence)])
    return [(k, lv, t) for k, lv, t in out]


def _mask_code(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"
    return CODE_SPAN.sub(keep, text), spans


def _unmask(text: str, spans: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _no_split_here(before: str, punct: str, after: str) -> bool:
    if punct.startswith(".."):
        return True                             # an ellipsis or a range like 0..9
    word = re.split(r"[\s(\[\"']", before)[-1].lower()
    if punct.startswith(".") and word in NEVER_AFTER:
        return True
    if punct.startswith(".") and word == "etc":
        nxt = after.lstrip()[:1]
        return not (nxt.isupper())
    return False


def sentences(text: str) -> list[str]:
    """One block of text split into sentences (code spans never split)."""
    masked, spans = _mask_code(" ".join(text.split()))
    out, start = [], 0
    for m in BOUNDARY.finditer(masked):
        punct = m.group(0)
        if _no_split_here(masked[start:m.start()], punct, masked[m.end():]):
            continue
        piece = masked[start:m.end()].strip()
        if piece:
            out.append(piece)
        start = m.end()
    tail = masked[start:].strip()
    if tail:
        out.append(tail)
    merged: list[str] = []
    for s in out:                               # a bold lead-in goes with the sentence after it
        if merged and BOLD_ONLY.match(merged[-1]) and not merged[-1].endswith(":**"):
            merged[-1] = merged[-1] + " " + s
        else:
            merged.append(s)
    return [_unmask(s, spans) for s in merged]


def split_units(run_id: str, text: str) -> list[Unit]:
    """The answer's units with stable ids <run id>#s<k>."""
    units: list[Unit] = []
    for kind, level, block in _blocks(text):
        parts = [block.strip()] if kind in ("code", "heading") else sentences(block)
        for p in parts:
            if p:
                units.append(Unit(id=f"{run_id}#s{len(units) + 1}", text=p, kind=kind, level=level))
    return units

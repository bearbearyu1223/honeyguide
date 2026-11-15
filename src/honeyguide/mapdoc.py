"""The map's document structure, the Tracer's path record, and the plain text annotations index.

Pure functions over plain JSON. A document is sections -> blocks -> spans; a span with ``claim`` is that claim's
rendered text. Flows are path records (ordered hops between lanes). See docs/design/agent-contract.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator

SECTION_KINDS = ("overview", "modules", "flows", "other")
BLOCK_TYPES = ("text", "module", "flow")
TRACE = ("seen", "unseen", "blind_spot")
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_STATUS = 200


def _str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def spans_text(spans: list[dict]) -> str:
    return "".join(s.get("text", "") for s in spans)


def block_text(block: dict) -> str:
    return spans_text(block.get("spans", []))


def plain_text(document: dict | None) -> str:
    """What DocumentAnchor offsets on ``map`` index: titles and blocks, separated by blank lines."""
    if not document:
        return ""
    parts: list[str] = []
    for section in document.get("sections", []):
        parts.append(section.get("title", ""))
        parts.extend(block_text(b) for b in section.get("blocks", []))
    return "\n\n".join(parts)


def revision(document: dict) -> str:
    payload = plain_text(document) + "\x00" + json.dumps(document.get("flows", []), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def iter_spans(document: dict | None) -> Iterator[dict]:
    for section in (document or {}).get("sections", []):
        for block in section.get("blocks", []):
            yield from block.get("spans", [])


def claim_refs(document: dict | None) -> list[str]:
    """Every claim the document shows (span claims and hop claims), in order, with repeats."""
    refs = [s["claim"] for s in iter_spans(document) if s.get("claim")]
    for path in (document or {}).get("flows", []):
        refs += [h["claim"] for h in path.get("hops", []) if h.get("claim")]
    return refs


def rewrite_refs(obj: Any, mapping: dict[str, str]) -> Any:
    """A copy of a document, spans list or path record with every ``claim`` key rewritten through ``mapping``."""
    if isinstance(obj, list):
        return [rewrite_refs(x, mapping) for x in obj]
    if isinstance(obj, dict):
        out = {k: rewrite_refs(v, mapping) for k, v in obj.items()}
        if isinstance(obj.get("claim"), str) and obj["claim"] in mapping:
            out["claim"] = mapping[obj["claim"]]
        return out
    return obj


def check_spans(spans: Any, where: str, errors: list[str]) -> None:
    if not isinstance(spans, list) or not spans:
        errors.append(f"{where}: spans must be a non-empty list")
        return
    for i, span in enumerate(spans):
        if not isinstance(span, dict) or not isinstance(span.get("text"), str) or not span["text"]:
            errors.append(f"{where}.spans[{i}]: needs non-empty text")
        elif "claim" in span and not _str(span["claim"]):
            errors.append(f"{where}.spans[{i}]: claim must be a claim key or id")


def check_path_record(path: Any, where: str, errors: list[str], warnings: list[str]) -> None:
    """The Tracer's path: lanes, loops, ordered hops; every hop names lanes and a claim."""
    if not isinstance(path, dict):
        errors.append(f"{where}: must be an object")
        return
    if not _str(path.get("id")) or not ID.match(path["id"]):
        errors.append(f"{where}: id must match {ID.pattern}")
    if not _str(path.get("title")):
        errors.append(f"{where}: needs a title")
    lanes = path.get("lanes")
    lane_ids: set[str] = set()
    if not isinstance(lanes, list) or not lanes:
        errors.append(f"{where}: needs lanes")
        lanes = []
    for i, lane in enumerate(lanes):
        if not isinstance(lane, dict) or not _str(lane.get("id")) or not _str(lane.get("label")):
            errors.append(f"{where}.lanes[{i}]: needs id and label")
            continue
        if lane["id"] in lane_ids:
            errors.append(f"{where}.lanes[{i}]: duplicate lane id {lane['id']!r}")
        lane_ids.add(lane["id"])
    loop_ids: set[str] = set()
    for i, loop in enumerate(path.get("loops") or []):
        if not isinstance(loop, dict) or not _str(loop.get("id")) or not _str(loop.get("label")):
            errors.append(f"{where}.loops[{i}]: needs id and label")
            continue
        loop_ids.add(loop["id"])
    hops = path.get("hops")
    if not isinstance(hops, list) or not hops:
        errors.append(f"{where}: needs at least one hop")
        hops = []
    used_loops = set()
    for i, hop in enumerate(hops):
        at = f"{where}.hops[{i}]"
        if not isinstance(hop, dict):
            errors.append(f"{at}: must be an object")
            continue
        for end in ("from", "to"):
            if hop.get(end) not in lane_ids:
                errors.append(f"{at}: {end} {hop.get(end)!r} is not a lane")
        if not _str(hop.get("call")):
            errors.append(f"{at}: needs call")
        if hop.get("trace") not in TRACE:
            errors.append(f"{at}: trace must be one of {', '.join(TRACE)}")
        if not _str(hop.get("claim")):
            errors.append(f"{at}: every hop needs a claim (anchor-cited or labelled)")
        if hop.get("loop") is not None:
            if hop["loop"] not in loop_ids:
                errors.append(f"{at}: loop {hop['loop']!r} is not declared")
            used_loops.add(hop["loop"])
        for key in ("returns", "data", "label"):
            if key in hop and hop[key] is not None and not isinstance(hop[key], str):
                errors.append(f"{at}: {key} must be a string")
    for loop_id in sorted(loop_ids - used_loops):
        warnings.append(f"{where}: loop {loop_id!r} has no hops")


def check_document(document: Any) -> tuple[list[str], list[str]]:
    """Structural errors and warnings for a map document (claims are checked elsewhere)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, dict):
        return ["document: must be an object"], []
    if not _str(document.get("title")):
        errors.append("document: needs a title")
    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("document: needs sections")
        sections = []
    seen: set[str] = set()

    def unique(value: Any, where: str) -> None:
        if not _str(value) or not ID.match(value):
            errors.append(f"{where}: id must match {ID.pattern}")
        elif value in seen:
            errors.append(f"{where}: duplicate id {value!r}")
        else:
            seen.add(value)

    flows = document.get("flows") or []
    if not isinstance(flows, list):
        errors.append("document.flows: must be a list")
        flows = []
    flow_ids = {f.get("id") for f in flows if isinstance(f, dict)}
    for s, section in enumerate(sections):
        where = f"sections[{s}]"
        if not isinstance(section, dict):
            errors.append(f"{where}: must be an object")
            continue
        unique(section.get("id"), where)
        if section.get("kind") not in SECTION_KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(SECTION_KINDS)}")
        if not _str(section.get("title")):
            errors.append(f"{where}: needs a title")
        for b, block in enumerate(section.get("blocks") or []):
            at = f"{where}.blocks[{b}]"
            if not isinstance(block, dict):
                errors.append(f"{at}: must be an object")
                continue
            unique(block.get("id"), at)
            kind = block.get("type")
            if kind not in BLOCK_TYPES:
                errors.append(f"{at}: type must be one of {', '.join(BLOCK_TYPES)}")
            if kind == "module" and not _str(block.get("path")):
                errors.append(f"{at}: a module block needs path")
            if kind == "flow" and block.get("flow") not in flow_ids:
                errors.append(f"{at}: flow {block.get('flow')!r} is not in document.flows")
            check_spans(block.get("spans"), at, errors)
    for f, flow in enumerate(flows):
        check_path_record(flow, f"flows[{f}]", errors, warnings)
        if isinstance(flow, dict) and _str(flow.get("id")):
            unique(flow["id"], f"flows[{f}]")
    return errors, warnings


def span_ranges(document: dict | None) -> list[tuple[int, int, str | None]]:
    """``(start, end, claim)`` of every span in ``plain_text(document)`` coordinates."""
    out: list[tuple[int, int, str | None]] = []
    pos = 0
    first = True
    for section in (document or {}).get("sections", []):
        pieces = [section.get("title", "")] + [b for b in section.get("blocks", [])]
        for piece in pieces:
            if not first:
                pos += 2  # the blank line between parts
            first = False
            if isinstance(piece, str):
                pos += len(piece)
                continue
            for span in piece.get("spans", []):
                text = span.get("text", "")
                out.append((pos, pos + len(text), span.get("claim")))
                pos += len(text)
    return out


def spans_ranges(spans: list[dict]) -> list[tuple[int, int, str | None]]:
    out, pos = [], 0
    for span in spans:
        text = span.get("text", "")
        out.append((pos, pos + len(text), span.get("claim")))
        pos += len(text)
    return out


def claims_in(ranges: list[tuple[int, int, str | None]], start: int, end: int) -> list[str]:
    """Claims whose spans overlap ``start..end`` (in order, no repeats)."""
    return list(dict.fromkeys(c for s, e, c in ranges if c and s < end and start < e))


def text_revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

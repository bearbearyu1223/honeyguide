"""The map's document structure, the Tracer's path record, and the plain text annotations index.

Pure functions over plain JSON. A document is sections -> blocks -> spans; a span with ``claim`` is that claim's
rendered text. Flows are path records (ordered hops between lanes). See docs/design/agent-contract.md.

T7.13: a block's text is one or more *segments* (lists of spans), joined by one newline in the plain text: its own
``spans`` (a paragraph, a module's summary, a list's lead-in), then each ``items[]`` entry of a ``list`` block, then
each ``rows[]`` entry of a ``facts`` block (or each ``facts[]`` row of a ``module`` block). Old blocks have one segment,
so their plain text, offsets and revisions are unchanged. Overview blocks may carry a ``topic``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator

SECTION_KINDS = ("overview", "modules", "flows", "other")
BLOCK_TYPES = ("text", "module", "flow", "list", "facts")
# The Overview's topic groups (T7.13), in page order, with the page's quiet headings.
OVERVIEW_TOPICS = ("purpose", "users", "capabilities", "commands", "entry-points", "components", "start-here")
TOPIC_TITLES = {"purpose": "Purpose", "users": "Who it's for", "capabilities": "What it can do",
                "commands": "Commands", "entry-points": "Entry points", "components": "Components",
                "start-here": "Start here"}
# A module block's facts rows (T7.13), in page order, with the page's labels. Rows that don't apply are left out.
MODULE_FACTS = ("responsibility", "key_files", "key_symbols", "interfaces", "io", "callers", "dependencies",
                "external", "errors", "tests", "debug")
FACT_LABELS = {"responsibility": "Responsibility", "key_files": "Key files", "key_symbols": "Key symbols",
               "interfaces": "Interfaces", "io": "Inputs and outputs", "callers": "Callers",
               "dependencies": "Dependencies", "external": "External", "errors": "Errors", "tests": "Tests",
               "debug": "Debugging"}
MAX_LABEL = 40  # a facts row's key or label
TRACE = ("seen", "unseen", "blind_spot")
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_STATUS = 200
MAX_ROLE = 80   # a module's one-line role, shown in its heading, as its lane's subtitle and in the module graph


def _str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def spans_text(spans: list[dict]) -> str:
    return "".join(s.get("text", "") for s in spans)


def block_segments(block: dict) -> list[list[dict]]:
    """A block's text pieces in plain-text order: its spans (when any), then list items, then facts rows."""
    segs: list[list[dict]] = []
    if block.get("spans"):
        segs.append(block["spans"])
    for item in block.get("items") or []:
        segs.append(item.get("spans", []) if isinstance(item, dict) else [])
    rows = block.get("rows") if block.get("type") == "facts" else block.get("facts")
    for row in rows or []:
        segs.append(row.get("spans", []) if isinstance(row, dict) else [])
    return segs or [[]]


def block_text(block: dict) -> str:
    return "\n".join(spans_text(seg) for seg in block_segments(block))


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
            for seg in block_segments(block):
                yield from seg


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
        for key in ("returns", "data", "label", "note"):
            if key in hop and hop[key] is not None and not isinstance(hop[key], str):
                errors.append(f"{at}: {key} must be a string")
    for loop_id in sorted(loop_ids - used_loops):
        warnings.append(f"{where}: loop {loop_id!r} has no hops")


def _check_rows(rows: Any, at: str, errors: list[str], module: bool) -> None:
    """A facts block's ``rows`` or a module block's ``facts``: ``[{key, label?, spans}]``, keys unique."""
    name = "facts" if module else "rows"
    if not isinstance(rows, list) or not rows:
        errors.append(f"{at}: {name} must be a non-empty list of {{key, spans}}")
        return
    keys: list[str] = []
    for r, row in enumerate(rows):
        where = f"{at}.{name}[{r}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: must be an object")
            continue
        key = row.get("key")
        if not _str(key) or len(key) > MAX_LABEL or "\n" in key:
            errors.append(f"{where}: key must be a one-line string (<= {MAX_LABEL} chars)")
        elif module and key not in MODULE_FACTS:
            errors.append(f"{where}: key {key!r} is not a module fact; use one of {', '.join(MODULE_FACTS)}")
        elif key in keys:
            errors.append(f"{where}: duplicate key {key!r}")
        else:
            keys.append(key)
        label = row.get("label")
        if label is not None and (not _str(label) or len(label) > MAX_LABEL or "\n" in label):
            errors.append(f"{where}: label must be a one-line string (<= {MAX_LABEL} chars)")
        check_spans(row.get("spans"), where, errors)
    if module and "responsibility" in keys and keys[0] != "responsibility":
        errors.append(f"{at}.facts: responsibility must be the first row (it shows while the others are folded)")


def _check_topics(section: dict, where: str, errors: list[str], strict: bool) -> None:
    """Overview topic groups: each block names a topic, groups are contiguous and in OVERVIEW_TOPICS order."""
    blocks = [b for b in section.get("blocks") or [] if isinstance(b, dict)]
    topics = [b.get("topic") for b in blocks]
    if not any(t is not None for t in topics):
        if strict:
            errors.append(f"{where}: the Overview needs topic groups: give every block a topic "
                          f"({', '.join(OVERVIEW_TOPICS)})")
        return
    order: list[str] = []
    for b, topic in enumerate(topics):
        at = f"{where}.blocks[{b}]"
        if topic not in OVERVIEW_TOPICS:
            errors.append(f"{at}: topic must be one of {', '.join(OVERVIEW_TOPICS)}"
                          + (" (every Overview block needs one once any has one)" if topic is None else ""))
            continue
        if order and order[-1] == topic:
            continue
        if topic in order:
            errors.append(f"{at}: topic {topic!r} is split; keep each topic's blocks together")
        elif order and OVERVIEW_TOPICS.index(topic) < OVERVIEW_TOPICS.index(order[-1]):
            errors.append(f"{at}: topic {topic!r} comes after {order[-1]!r}; use the order "
                          f"{', '.join(OVERVIEW_TOPICS)}")
        order.append(topic)
    missing = [t for t in OVERVIEW_TOPICS if t not in order]
    if missing:
        errors.append(f"{where}: missing topic(s) {', '.join(missing)}; every topic is required (one the repo "
                      "doesn't have is a block citing a searched_not_found claim)")


def check_document(document: Any, strict: bool = False) -> tuple[list[str], list[str]]:
    """Structural errors and warnings for a map document (claims are checked elsewhere).

    ``strict`` (drafts, ``map check``): the Overview must have every topic group and every module block a facts
    list starting with its responsibility. Saved maps, including pre-T7.13 ones without topics or facts, are
    checked without it.
    """
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
    kinds = [s.get("kind") for s in sections if isinstance(s, dict)]
    if strict and "overview" not in kinds:
        errors.append("document: needs an overview section")
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
        if section.get("kind") == "overview":
            _check_topics(section, where, errors, strict)
        for b, block in enumerate(section.get("blocks") or []):
            at = f"{where}.blocks[{b}]"
            if not isinstance(block, dict):
                errors.append(f"{at}: must be an object")
                continue
            unique(block.get("id"), at)
            kind = block.get("type")
            if kind not in BLOCK_TYPES:
                errors.append(f"{at}: type must be one of {', '.join(BLOCK_TYPES)}")
            if block.get("topic") is not None and section.get("kind") != "overview":
                errors.append(f"{at}: topic is for Overview blocks only")
            if kind == "module" and not _str(block.get("path")):
                errors.append(f"{at}: a module block needs path")
            if "role" in block and block["role"] is not None and (
                    kind != "module" or not isinstance(block["role"], str) or "\n" in block["role"]
                    or len(block["role"]) > MAX_ROLE):
                errors.append(f"{at}: role is a module block's one-line role (a string, <= {MAX_ROLE} chars)")
            if "entry" in block and block["entry"] is not None and (kind != "module" or not isinstance(block["entry"], bool)):
                errors.append(f"{at}: entry is true or false, on a module block only")
            if kind == "flow" and block.get("flow") not in flow_ids:
                errors.append(f"{at}: flow {block.get('flow')!r} is not in document.flows")
            if "items" in block and kind != "list":
                errors.append(f"{at}: items belong to a list block")
            if "rows" in block and kind != "facts":
                errors.append(f"{at}: rows belong to a facts block")
            if "facts" in block and kind != "module":
                errors.append(f"{at}: facts belong to a module block (a facts block has rows)")
            if "ordered" in block and (kind != "list" or not isinstance(block["ordered"], bool)):
                errors.append(f"{at}: ordered is true or false, on a list block only")
            if kind == "list":
                items = block.get("items")
                if not isinstance(items, list) or not items:
                    errors.append(f"{at}: a list block needs items: [{{spans}}, ...]")
                else:
                    for i, item in enumerate(items):
                        if not isinstance(item, dict):
                            errors.append(f"{at}.items[{i}]: must be an object with spans")
                        else:
                            check_spans(item.get("spans"), f"{at}.items[{i}]", errors)
            elif kind == "facts":
                _check_rows(block.get("rows"), at, errors, module=False)
            elif kind == "module" and block.get("facts") is not None:
                _check_rows(block["facts"], at, errors, module=True)
            if kind == "module" and strict:
                keys = [r.get("key") for r in block.get("facts") or [] if isinstance(r, dict)]
                if "responsibility" not in keys:
                    errors.append(f"{at}: a module block needs facts, starting with responsibility")
                if not block.get("spans"):
                    errors.append(f"{at}: a module block needs its summary (spans, 2-4 sentences)")
            # spans: required on text, module (pre-T7.13) and flow blocks; on a list or facts block they are an
            # optional lead-in, and on a module block with facts, its optional summary
            optional = kind in ("list", "facts") or (kind == "module" and block.get("facts") is not None)
            if not optional or block.get("spans") is not None:
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
            for k, seg in enumerate(block_segments(piece)):
                if k:
                    pos += 1  # the newline between a block's segments
                for span in seg:
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

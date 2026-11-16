"""An eval map build's output: extract the map, validate it, resolve its anchors by script, render it as text.

The Cartographer in eval mode returns the full `claims save` input ({"target", "mode", "document", "claims"}).
Validation uses Honeyguide's own code (honeyguide.claims, honeyguide.mapdoc) against the pinned clone, at the
pinned commit. Invalid anchors are counted and listed, never fixed: the map is used as the Cartographer wrote it,
and the rendered text marks an anchor that did not resolve as "[path: quote not found]".

The rendered text is what a map-condition run reads (appended to its prompt): every section, block and flow hop,
each claim followed by its citation ([path:start-end] per resolved anchor, or its evidence label when it cites no
code).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from honeyguide.claims import resolve_one, validate_draft
from honeyguide.contract import ContractError
from honeyguide.gitio import Repo
from honeyguide.mapdoc import TOPIC_TITLES, check_document, normalize_document

FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.S)


def extract_json(result: dict) -> tuple[Any, str]:
    """(object, how) from a claude -p result: structured_output when present, else the result text parsed as JSON
    (a ```json fence around it is allowed). (None, reason) when neither works."""
    so = result.get("structured_output")
    if isinstance(so, dict):
        return so, "structured_output"
    text = result.get("result")
    if not isinstance(text, str) or not text.strip():
        return None, "no structured_output and no result text"
    t = text.strip()
    m = FENCE.match(t)
    if m:
        t = m.group(1)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as exc:
        return None, f"result text is not JSON ({exc.msg} at char {exc.pos})"
    return (obj, "result text") if isinstance(obj, dict) else (None, "result JSON is not an object")


def resolve_anchors(repo: Repo, commit: str, claims: list) -> tuple[dict[str, list], dict]:
    """{claim key: [resolved anchor dict, or {"path", "status"} when not found]} and the counts."""
    out: dict[str, list] = {}
    total = found = 0
    problems = []
    for i, c in enumerate(claims if isinstance(claims, list) else []):
        if not isinstance(c, dict):
            continue
        key = c.get("key") or f"#{i}"
        rows = []
        for spec in c.get("anchors") or []:
            total += 1
            status, payload = resolve_one(repo, commit, spec)
            if status == "found":
                found += 1
                rows.append(payload["anchor"])
            else:
                path = spec.get("path") if isinstance(spec, dict) else None
                rows.append({"path": path, "status": status})
                problems.append({"claim": key, "path": path, "status": status,
                                 "message": payload.get("message", "")})
        out[key] = rows
    return out, {"anchors_total": total, "anchors_resolved": found, "unresolved": problems}


def validate_map(clone, commit: str, data: Any) -> dict:
    """Everything the scorer prints about one map: structure, anchors, Honeyguide's own draft validation."""
    if not isinstance(data, dict) or not isinstance(data.get("document"), dict):
        return {"usable": False, "reason": "no document object", "anchors_total": 0, "anchors_resolved": 0,
                "unresolved": [], "structure_errors": [], "draft_valid": False, "draft_errors": []}
    repo = Repo.open(clone)
    _, counts = resolve_anchors(repo, commit, data.get("claims"))
    doc = normalize_document(copy.deepcopy(data["document"]))
    s_err, s_warn = check_document(doc, strict=True)
    try:
        v = validate_draft(repo, dict(data, commit=commit), strict=True)
        draft_valid, draft_errors = bool(v.get("valid")), list(v.get("errors", []))
    except ContractError as exc:
        draft_valid, draft_errors = False, [str(exc)]
    claims = [c for c in data.get("claims") or [] if isinstance(c, dict)]
    labels: dict[str, int] = {}
    for c in claims:
        labels[str(c.get("evidence"))] = labels.get(str(c.get("evidence")), 0) + 1
    return {"usable": True, "claims": len(claims), "evidence": dict(sorted(labels.items())), **counts,
            "structure_errors": s_err, "structure_warnings": s_warn, "draft_valid": draft_valid,
            "draft_errors": draft_errors}


def _cite(rows: list, evidence: str | None) -> str:
    if not rows:
        return {"general_knowledge": "[general knowledge]", "searched_not_found": "[searched, not found]"}.get(
            evidence or "", "[no anchor]")
    parts = []
    for a in rows:
        if "start" in a:
            rng = f"{a['start']}" if a["start"] == a["end"] else f"{a['start']}-{a['end']}"
            parts.append(f"{a['path']}:{rng}")
        else:
            parts.append(f"{a.get('path')}: quote not found")
    return "[" + "; ".join(parts) + "]"


def block_pieces(block: dict) -> list[tuple[str, list]]:
    """(line prefix, spans) in honeyguide.mapdoc.block_segments order: the block's spans, a module's design
    paragraph, list items ("- "), facts rows ("- label: ")."""
    out: list[tuple[str, list]] = []
    if block.get("spans"):
        out.append(("", block["spans"]))
    if block.get("type") == "module" and block.get("design"):
        out.append(("Design: ", block["design"]))
    for item in block.get("items") or []:
        out.append(("- ", item.get("spans", []) if isinstance(item, dict) else []))
    rows = block.get("rows") if block.get("type") == "facts" else block.get("facts")
    for row in rows or []:
        if isinstance(row, dict):
            out.append((f"- {row.get('label') or row.get('key')}: ", row.get("spans", [])))
    return out


def render_map(data: dict, resolved: dict[str, list]) -> str:
    """The map as plain text with citations. Pure."""
    claims = {c.get("key"): c for c in data.get("claims") or [] if isinstance(c, dict)}
    doc = data["document"]

    def spans(seg: list) -> str:
        out = []
        for s in seg:
            if not isinstance(s, dict):
                continue
            out.append(str(s.get("text", "")))
            k = s.get("claim")
            if k:
                out.append(" " + _cite(resolved.get(k, []), (claims.get(k) or {}).get("evidence")))
        return "".join(out).strip()

    lines = [f"# {doc.get('title', 'Map')}"]
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        lines += ["", f"## {section.get('title', section.get('id', ''))}"]
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            lines.append("")
            if block.get("topic"):
                lines.append(f"### {TOPIC_TITLES.get(block['topic'], block['topic'])}")
            if block.get("type") == "module":
                files = ", ".join(block.get("files") or ([block["path"]] if block.get("path") else []))
                title = block.get("title") or files
                lines.append(f"### {title}" + (f" ({files})" if files and files not in title else ""))
                if block.get("role"):
                    lines.append(f"Role: {block['role']}")
            for prefix, seg in block_pieces(block):
                text = spans(seg)
                if text:
                    lines.append(prefix + text)
            if block.get("type") == "flow" and block.get("flow"):
                lines.append(f"(flow: {block['flow']})")
    for path in doc.get("flows") or []:
        if not isinstance(path, dict):
            continue
        lanes = {ln.get("id"): ln.get("label") for ln in path.get("lanes") or [] if isinstance(ln, dict)}
        lines += ["", f"## Flow {path.get('id')}: {path.get('title', '')}"]
        for i, hop in enumerate(path.get("hops") or [], 1):
            if not isinstance(hop, dict):
                continue
            k = hop.get("claim")
            cite = " " + _cite(resolved.get(k, []), (claims.get(k) or {}).get("evidence")) if k else ""
            text = (claims.get(k) or {}).get("text", "")
            lines.append(f"{i}. {lanes.get(hop.get('from'), hop.get('from'))} -> "
                         f"{lanes.get(hop.get('to'), hop.get('to'))}: {hop.get('call', '')}"
                         + (f": {text}" if text else "") + cite)
    return "\n".join(lines).rstrip() + "\n"

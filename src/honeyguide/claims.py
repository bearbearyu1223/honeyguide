"""Claims as agents submit them: resolve quoted anchors, enforce the evidence rules, refuse secrets, save the
map, validate a saved map, record the Checker's verdicts.

Nothing is written unless the whole call is valid; every problem is reported at once so an agent can fix them all.
"""

from __future__ import annotations

import copy
from typing import Any

from .anchors import CodeAnchor, check_path, resolve
from .contract import ContractError, need
from .gitio import GitError, Repo
from .guard import check_secret
from .links import editor_links, github_link
from .mapdoc import check_document, check_path_record, claim_refs, revision, rewrite_refs
from .outline import line_hash
from .readability import check_readability
from .store import EVIDENCE, Store, all_claims, make_claim, now_iso, validate_claim

UNANCHORED = ("general_knowledge", "searched_not_found")
VERDICTS = ("supported", "not_supported", "skipped")


def commit_of(repo: Repo, rev: Any) -> str:
    rev = rev or "HEAD"
    if not isinstance(rev, str):
        raise ContractError("bad_input", "commit must be a string")
    try:
        sha = repo.rev(rev)
    except GitError:
        sha = ""
    if not sha:
        raise ContractError("not_found", f"{rev!r} is not a commit in this repository")
    return sha


def has_commit(repo: Repo, sha: str) -> bool:
    try:
        return bool(repo.rev(sha))
    except GitError:
        return False


def label_errors(evidence: Any, anchors: list, where: str) -> list[str]:
    """The evidence rule: labelled-unanchored claims carry no anchors, every other claim at least one."""
    if evidence not in EVIDENCE:
        return [f"{where}: evidence must be one of {', '.join(EVIDENCE)}"]
    if evidence in UNANCHORED and anchors:
        return [f"{where}: {evidence} claims cite no code; drop the anchors or change the label"]
    if evidence not in UNANCHORED and not anchors:
        return [f"{where}: {evidence} needs at least one code anchor "
                f"(or label it general_knowledge / searched_not_found)"]
    return []


def resolve_one(repo: Repo, commit: str, spec: Any) -> tuple[str, dict]:
    """``(status, payload)`` for one anchor spec; payload is the anchor dict, or a message and candidates."""
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not isinstance(
            spec.get("anchor"), str) or not spec["anchor"].strip():
        return "bad_input", {"message": "an anchor needs path and anchor (the quoted text)"}
    extent = spec.get("extent", "lines")
    if extent not in ("lines", "block"):
        return "bad_input", {"message": "extent must be lines or block"}
    try:
        check_path(spec["path"])
    except ValueError as exc:
        return "bad_input", {"message": str(exc)}
    why = check_secret(spec["path"])
    if why:
        return "secret", {"message": why}
    lines = repo.lines_at(commit, spec["path"])
    res = resolve(lines, spec["path"], spec["anchor"], commit, end_anchor=spec.get("end_anchor"), extent=extent)
    if res.status != "found":
        return res.status, {"message": res.message, "candidates": list(res.candidates)}
    anchor = res.anchor
    why = check_secret(anchor.path, lines[anchor.start - 1:anchor.end], anchor.start)
    if why:
        return "secret", {"message": why}
    return "found", {"anchor": anchor.to_dict()}


def links_for(repo: Repo, anchor: dict) -> dict:
    a = CodeAnchor.from_dict(anchor)
    lines = f"line {a.start}" if a.start == a.end else f"lines {a.start}-{a.end}"
    return {"github": github_link(repo, a), "github_title": f"pinned to {a.commit[:12]}, {lines}",
            **editor_links(repo.root, a)}


def resolve_call(repo: Repo, data: Any) -> dict:
    """``anchor resolve``: one spec or ``{anchors: [...]}``; never raises for a bad quote, reports it."""
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    commit = commit_of(repo, data.get("commit"))
    specs = data["anchors"] if isinstance(data.get("anchors"), list) else [data]
    results = []
    for spec in specs:
        status, payload = resolve_one(repo, commit, spec)
        row = {"status": status, "candidates": payload.get("candidates", []), "message": payload.get("message", "")}
        if status == "found":
            row["anchor"] = payload["anchor"]
            row["links"] = links_for(repo, payload["anchor"])
        results.append(row)
    return {"commit": commit, "results": results}


def build_claims(repo: Repo, drafts: Any, commit: str, where: str = "claims") -> tuple[list[dict], dict[str, str]]:
    """Resolve and validate draft claims. Returns ``(claims, key -> id)`` or raises with every problem."""
    if not isinstance(drafts, list):
        raise ContractError("bad_input", f"{where} must be a list")
    errors: list[str] = []
    secret = False
    claims: list[dict] = []
    keys: dict[str, str] = {}
    for i, draft in enumerate(drafts):
        at = f"{where}[{i}]"
        if not isinstance(draft, dict):
            errors.append(f"{at}: must be an object")
            continue
        key = draft.get("key")
        if key is not None:
            at = f"{at} ({key})"
            if not isinstance(key, str) or not key.strip():
                errors.append(f"{at}: key must be a non-empty string")
            elif key in keys:
                errors.append(f"{at}: duplicate key")
        text = draft.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{at}: needs text")
        specs = draft.get("anchors") or []
        if not isinstance(specs, list):
            errors.append(f"{at}: anchors must be a list")
            specs = []
        errors += label_errors(draft.get("evidence"), specs, at)
        anchors = []
        for j, spec in enumerate(specs):
            status, payload = resolve_one(repo, commit, spec)
            if status == "found":
                anchors.append(payload["anchor"])
                continue
            secret = secret or status == "secret"
            extra = f" (candidates: lines {', '.join(map(str, payload['candidates'][:8]))})" \
                if payload.get("candidates") else ""
            errors.append(f"{at}.anchors[{j}]: {status}: {payload['message']}{extra}")
        searched = draft.get("searched")
        if searched is not None and not (isinstance(searched, list) and all(isinstance(s, str) for s in searched)):
            errors.append(f"{at}: searched must be a list of strings")
        if errors:
            continue
        extra = {"key": key} if key is not None else {}
        if searched is not None:
            extra["searched"] = searched
        claim = make_claim(text.strip(), draft["evidence"], anchors, **extra)
        claims.append(claim)
        if key is not None:
            keys[key] = claim["id"]
    if errors:
        raise ContractError("secret_refused" if secret else "validation_failed",
                            f"{len(errors)} problem(s) in {where}; nothing was saved", errors)
    return claims, keys


def save_claims(store: Store, repo: Repo, data: Any) -> dict:
    """``claims save``: the Cartographer's map, replaced whole or added to."""
    if need(data, "target") != "map":
        raise ContractError("bad_input", "target must be 'map' (answers go through 'answer record')")
    mode = data.get("mode", "replace")
    if mode not in ("replace", "add"):
        raise ContractError("bad_input", "mode must be replace or add")
    document = data.get("document")
    if mode == "replace" and document is None:
        raise ContractError("bad_input", "a replace needs the document")
    commit = commit_of(repo, data.get("commit"))
    claims, keys = build_claims(repo, data.get("claims"), commit)
    retiring = _retire_items(data.get("retire"), mode)
    stamp = now_iso()

    def change(layer: dict) -> dict:
        existing = [] if mode == "replace" else layer["claims"]
        if retiring:
            have = {c["id"] for c in existing}
            unknown = [cid for cid in retiring if cid not in have]
            if unknown:
                raise ContractError("not_found", "retire names claims not in the map; nothing was saved",
                                    [f"retire: {u}: no such map claim" for u in unknown])
            for claim in existing:
                if claim["id"] in retiring and claim.get("freshness") != "retired":
                    claim.update(freshness="retired", freshness_reason=retiring[claim["id"]], retired_at=stamp)
                    claim.pop("candidates", None)
        known = {c["id"] for c in existing} | {c["id"] for c in claims}
        doc = layer.get("document") if document is None else rewrite_refs(copy.deepcopy(document), keys)
        errors: list[str] = []
        warnings: list[str] = []
        if doc is not None:
            errors, warnings = check_document(doc)
            errors += [f"document: claim {ref!r} is not a key in this call or a saved claim id"
                       for ref in dict.fromkeys(claim_refs(doc)) if ref not in known]
        if errors:
            raise ContractError("validation_failed", f"{len(errors)} problem(s) in the document; nothing was saved",
                                errors)
        if doc is not None:
            doc["revision"] = revision(doc)
            layer["document"] = doc
        layer["claims"] = existing + claims
        if mode == "replace" or layer.get("commit") is None:
            layer["commit"] = commit
        shown = set(claim_refs(doc))
        warnings += [f"claim {c.get('key') or c['id']} is not shown by any span or hop"
                     for c in layer["claims"] if c["id"] not in shown and c.get("freshness") != "retired"]
        return {"revision": doc.get("revision") if doc else None, "warnings": warnings}

    result = store.update("map", change)
    return {"commit": commit, "saved": [{"key": c.get("key"), "id": c["id"]} for c in claims],
            "retired": sorted(retiring), **result}


def _retire_items(raw: Any, mode: str) -> dict[str, str]:
    """``claims save``'s optional ``retire: [{claim, reason}]`` (mode add): old map claims this save replaces,
    retired in the same write as the new ones are added."""
    if raw is None:
        return {}
    if mode != "add":
        raise ContractError("bad_input", "retire goes with mode add (replace drops the old claims anyway)")
    if not isinstance(raw, list):
        raise ContractError("bad_input", "retire must be a list of {claim, reason}")
    out = {}
    for item in raw:
        out[need(item, "claim")] = " ".join(need(item, "reason").split())[:500]
    return out


def check_saved_claim(repo: Repo, claim: dict, where: str) -> tuple[list[str], list[str]]:
    """A saved claim against the rules and its own cited lines (re-hashed at the anchor's commit)."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        validate_claim(claim)
    except ValueError as exc:
        return [f"{where}: {exc}"], []
    errors += label_errors(claim["evidence"], claim["anchors"], where)
    for j, a in enumerate(claim["anchors"]):
        at = f"{where}.anchors[{j}] {a['path']}:{a['start']}-{a['end']}"
        lines = repo.lines_at(a["commit"], a["path"]) if has_commit(repo, a["commit"]) else None
        if lines is None:
            warnings.append(f"{at}: commit {a['commit'][:12]} or file not in this clone; can't re-read it")
            continue
        cited = lines[a["start"] - 1:a["end"]]
        if a["end"] > len(lines) or line_hash(cited) != a["hash"]:
            errors.append(f"{at}: the cited lines don't match the saved hash")
        why = check_secret(a["path"], cited, a["start"])
        if why:
            errors.append(f"{at}: {why}")
    return errors, warnings


def validate_map(repo: Repo, layer: dict, strict: bool = False) -> dict:
    """``map validate``: structure, every claim anchored or labelled, hashes, secrets, references; plus the
    readability report (T7.13).

    ``strict`` (drafts: ``map check``, ``map ingest``, ``map validate --strict``): the Overview's topic groups and
    the module facts are required, and readability errors are errors. Without it (a saved map, which may predate
    T7.13), readability is reported in ``readability`` only and never makes the map invalid.
    """
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    for i, claim in enumerate(layer.get("claims", [])):
        where = f"claims[{i}] ({claim.get('key') or claim.get('id')})"
        if claim.get("id") in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(claim.get("id"))
        e, w = check_saved_claim(repo, claim, where)
        errors += e
        warnings += w
    doc = layer.get("document")
    readable = {"errors": [], "warnings": []}
    if doc is None:
        if layer.get("claims"):
            warnings.append("document: none saved; claims are not shown anywhere")
    else:
        e, w = check_document(doc, strict=strict)
        errors += e
        warnings += w
        refs = claim_refs(doc)
        errors += [f"document: claim {r!r} is not a saved claim" for r in dict.fromkeys(refs) if r not in ids]
        shown = set(refs)
        warnings += [f"claim {c.get('key') or c['id']} is not shown by any span or hop"
                     for c in layer.get("claims", []) if c.get("id") not in shown and c.get("freshness") != "retired"]
        if doc.get("revision") != revision(doc):
            errors.append("document: revision doesn't match its text (edited outside honeyguide?)")
        re_, rw = check_readability(doc, strict=strict)
        readable = {"errors": re_, "warnings": rw}
        if strict:
            errors += re_
    return {"valid": not errors, "errors": errors, "warnings": warnings, "readability": readable}


def validate_draft(repo: Repo, data: Any, store: Store | None = None, strict: bool = False) -> dict:
    """``map validate --stdin`` (and ``map check``): a ``claims save`` input, checked without saving.

    In mode ``add`` the document may cite claims already saved: they are read from ``store``.
    """
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    try:
        claims, keys = build_claims(repo, data.get("claims"), commit_of(repo, data.get("commit")))
    except ContractError as exc:
        if exc.code == "bad_input":
            raise
        return {"valid": False, "errors": exc.details, "warnings": [], "readability": {"errors": [], "warnings": []}}
    doc = rewrite_refs(copy.deepcopy(data.get("document")), keys) if data.get("document") is not None else None
    if doc is not None:
        doc["revision"] = revision(doc)
    saved = store.load("map")["claims"] if store is not None and data.get("mode") == "add" else []
    result = validate_map(repo, {"claims": saved + claims, "document": doc}, strict=strict)
    if saved:   # the saved claims were checked when they were saved; only new ones can be unshown by this draft
        new = {c["id"] for c in claims}
        result["warnings"] = [w for w in result["warnings"] if not w.startswith("claim ")
                              or any(w.startswith(f"claim {c.get('key') or c['id']} ") for c in claims if c["id"] in new)]
    return result


def build_path(path: Any, keys: dict[str, str]) -> dict:
    """A Tracer answer's path record, after claim keys are known; returns it with refs rewritten."""
    errors: list[str] = []
    warnings: list[str] = []
    check_path_record(path, "path", errors, warnings)
    rewritten = rewrite_refs(path, keys)
    if isinstance(rewritten, dict):
        known = set(keys.values())
        errors += [f"path: hop claim {h.get('claim')!r} is not a claim key in this answer"
                   for h in rewritten.get("hops", []) if isinstance(h, dict) and h.get("claim") not in known]
    if errors:
        raise ContractError("validation_failed", f"{len(errors)} problem(s) in the path; nothing was saved", errors)
    return rewritten


def set_verdicts(store: Store, data: Any, repo: Repo | None = None) -> dict:
    """``verdict set``: one or many, every claim must exist; written in one hold of the lock.

    A **stale** claim (cited lines changed since it was checked) is re-checked here: ``supported`` needs
    ``anchors`` (quoted at ``commit``, default HEAD) showing where the claim holds now; they replace the old
    anchors and the claim becomes current. ``not_supported`` keeps it stale (never served) with the note.
    Either way it gets ``rechecked_at``. Retired claims take no verdict.
    """
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    items = data["verdicts"] if isinstance(data.get("verdicts"), list) else [data]
    wanted: dict[str, dict] = {}
    resolved: dict[str, list[dict]] = {}
    errors: list[str] = []
    secret = False
    for item in items:
        claim_id = need(item, "claim")
        if item.get("verdict") not in VERDICTS:
            raise ContractError("bad_input", f"verdict must be one of {', '.join(VERDICTS)}")
        note = item.get("note")
        if note is not None and not isinstance(note, str):
            raise ContractError("bad_input", "note must be a string")
        specs = item.get("anchors")
        if specs is not None:
            if not isinstance(specs, list) or not specs:
                raise ContractError("bad_input", f"{claim_id}: anchors must be a non-empty list")
            if repo is None:
                raise ContractError("bad_input", "anchors need the repository")
            commit = commit_of(repo, item.get("commit"))
            anchors = []
            for j, spec in enumerate(specs):
                status, payload = resolve_one(repo, commit, spec)
                if status == "found":
                    anchors.append(payload["anchor"])
                else:
                    secret = secret or status == "secret"
                    errors.append(f"{claim_id}.anchors[{j}]: {status}: {payload['message']}")
            resolved[claim_id] = anchors
        wanted[claim_id] = item
    if errors:
        raise ContractError("secret_refused" if secret else "validation_failed",
                            f"{len(errors)} problem(s); nothing was set", errors)
    stamp = now_iso()

    def problems(claim: dict, item: dict) -> list[str]:
        cid, verdict, fresh = claim["id"], item["verdict"], claim.get("freshness", "current")
        if claim["evidence"] == "general_knowledge" and verdict != "skipped":
            return [f"{cid}: general_knowledge claims are skipped, not checked"]
        if fresh == "retired":
            return [f"{cid}: retired; it takes no verdict"]
        new = resolved.get(cid)
        if fresh == "stale":
            if verdict == "supported" and not new:
                return [f"{cid}: stale; supported needs anchors quoting where the claim holds at HEAD"]
            if verdict != "supported" and new:
                return [f"{cid}: anchors go with supported only"]
            if verdict == "skipped":
                return [f"{cid}: stale; re-check it (supported with anchors, or not_supported)"]
        elif new is not None and new != claim["anchors"]:  # equal: a re-run after the claim went current
            return [f"{cid}: current; anchors are only for re-checking a stale claim"]
        return []

    def apply(claim: dict, item: dict) -> None:
        if claim.get("freshness") == "stale":
            claim["rechecked_at"] = stamp
            if item["verdict"] == "supported":
                claim.update(anchors=resolved[claim["id"]], freshness="current", freshness_reason="")
                claim.pop("candidates", None)
        claim.update(check=item["verdict"], checked_at=stamp, check_note=item.get("note") or "")

    with store.locked():
        map_layer, answers = store.load("map"), store.load("answers")
        found = {c["id"]: c for _, c in all_claims(map_layer, answers) if c["id"] in wanted}
        missing = sorted(set(wanted) - set(found))
        errors = [f"{m}: no such claim" for m in missing]
        for cid, claim in found.items():
            errors += problems(claim, wanted[cid])
        if errors:
            raise ContractError("not_found" if missing else "validation_failed",
                                f"{len(errors)} problem(s); nothing was set", errors)
        for cid, claim in found.items():
            apply(claim, wanted[cid])
        store.write_held("map", map_layer)
        store.write_held("answers", answers)
    return {"set": len(found),
            "current_again": sorted(cid for cid in found if cid in resolved and found[cid]["freshness"] == "current")}

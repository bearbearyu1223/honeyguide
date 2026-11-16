"""The repair pass (T7.15): after the Checker, the Cartographer fixes the map claims it marked ``not_supported``.

``claims repair`` takes, per claim, one of three actions:

- ``anchor``: the claim is true but cites too few lines. ``anchors`` is the claim's **whole** new anchor list (keep
  the old quotes you still want), quoted like any draft anchor, so the cited lines show the whole claim.
- ``rewrite``: the lines show less than the claim says. ``text`` is the narrower claim; ``span`` is the phrase the map
  shows for it (required when a span shows the claim, so the page never says more than the claim); ``anchors``
  optionally replaces the anchor list too.
- ``retire``: neither fix works (the claim is wrong or overstated past saving). ``reason`` says why; the claim stays
  on the page struck through, as any retired claim.

Claim ids never change, so questions and notes on them survive. Every anchored or rewritten claim goes back to
``check: unchecked`` (its old verdict and note move into its ``repairs`` history), so the Checker re-checks exactly
the changed claims. A claim takes at most ``MAX_ROUNDS`` repairs; after that it stays flagged. Nothing is written
unless the whole call is valid.
"""

from __future__ import annotations

from typing import Any

from .claims import commit_of, label_errors, resolve_one
from .contract import ContractError
from .gitio import Repo
from .mapdoc import check_document, iter_spans, revision
from .store import Store, now_iso

ACTIONS = ("anchor", "rewrite", "retire")
MAX_ROUNDS = 2
MAX_REASON = 500


def _loc(anchor: dict) -> str:
    return f"{anchor['path']}:{anchor['start']}-{anchor['end']}"


def _items(data: Any) -> list[dict]:
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    items = data.get("repairs")
    if not isinstance(items, list) or not items:
        raise ContractError("bad_input", "repairs must be a non-empty list of {claim, action, ...}")
    return items


def _resolve(repo: Repo, commit: str, specs: Any, at: str, errors: list[str]) -> tuple[list[dict], bool]:
    """Anchor specs -> resolved anchors; every problem appended to ``errors``. Returns (anchors, secret seen)."""
    if not isinstance(specs, list) or not specs:
        errors.append(f"{at}: anchors must be a non-empty list of {{path, anchor}}")
        return [], False
    out, secret = [], False
    for j, spec in enumerate(specs):
        status, payload = resolve_one(repo, commit, spec)
        if status == "found":
            out.append(payload["anchor"])
            continue
        secret = secret or status == "secret"
        extra = f" (candidates: lines {', '.join(map(str, payload['candidates'][:8]))})" \
            if payload.get("candidates") else ""
        errors.append(f"{at}.anchors[{j}]: {status}: {payload['message']}{extra}")
    return out, secret


def repair(repo: Repo, store: Store, data: Any) -> dict:
    """``claims repair``: ``{repairs: [{claim, action: anchor|rewrite|retire, anchors?, text?, span?, reason?}],
    commit?}``. Anchors resolve at ``commit`` (default: the map's commit)."""
    items = _items(data)
    map_layer = store.load("map")
    commit = commit_of(repo, data.get("commit") or map_layer.get("commit"))
    errors: list[str] = []
    secret = False
    plans: dict[str, dict] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"repairs[{i}]: must be an object")
            continue
        cid = item.get("claim")
        at = f"repairs[{i}] ({cid})"
        if not isinstance(cid, str) or not cid:
            errors.append(f"repairs[{i}]: needs claim (a c_... id from claims list)")
            continue
        if cid in plans:
            errors.append(f"{at}: the claim is repaired twice in one call")
            continue
        action = item.get("action")
        if action not in ACTIONS:
            errors.append(f"{at}: action must be one of {', '.join(ACTIONS)}")
            continue
        plan: dict = {"action": action}
        if action == "retire":
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{at}: retire needs a reason")
            else:
                plan["reason"] = " ".join(reason.split())[:MAX_REASON]
        else:
            if action == "rewrite":
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{at}: rewrite needs text (the narrower claim)")
                else:
                    plan["text"] = text.strip()
                span = item.get("span")
                if span is not None:
                    if not isinstance(span, str) or not span.strip():
                        errors.append(f"{at}: span must be the non-empty phrase the map shows")
                    else:
                        plan["span"] = span
            elif "text" in item or "span" in item:
                errors.append(f"{at}: anchor changes anchors only; use rewrite to change text or span")
            if action == "anchor" or item.get("anchors") is not None:
                anchors, s = _resolve(repo, commit, item.get("anchors"), at, errors)
                secret = secret or s
                plan["anchors"] = anchors
        plans[cid] = plan
    if errors:
        raise ContractError("secret_refused" if secret else "validation_failed",
                            f"{len(errors)} problem(s); nothing was repaired", errors)
    stamp = now_iso()

    def problems(claim: dict, plan: dict) -> list[str]:
        cid = claim["id"]
        if claim.get("freshness") != "current":
            return [f"{cid}: {claim.get('freshness')}; repair takes current claims (stale ones go through refresh)"]
        if claim.get("check") != "not_supported":
            return [f"{cid}: check is {claim.get('check')}; repair takes not_supported claims only"]
        if len(claim.get("repairs") or []) >= MAX_ROUNDS:
            return [f"{cid}: already repaired {MAX_ROUNDS} times; it stays flagged"]
        if "anchors" in plan:
            return label_errors(claim["evidence"], plan["anchors"], cid)
        return []

    with store.locked():
        map_layer = store.load("map")
        by_id = {c["id"]: c for c in map_layer["claims"]}
        missing = [cid for cid in plans if cid not in by_id]
        errors = [f"{m}: no such map claim (repair takes map claims only)" for m in missing]
        doc = map_layer.get("document")
        shown = {}
        for span in iter_spans(doc):
            if span.get("claim") in plans:
                shown[span["claim"]] = shown.get(span["claim"], 0) + 1
        for cid, plan in plans.items():
            if cid in by_id:
                errors += problems(by_id[cid], plan)
                if plan["action"] == "rewrite" and shown.get(cid) and "span" not in plan:
                    errors.append(f"{cid}: the map shows this claim in {shown[cid]} span(s); give span, the "
                                  "narrower phrase the map shows, so the page never says more than the claim")
        if errors:
            raise ContractError("not_found" if missing else "validation_failed",
                                f"{len(errors)} problem(s); nothing was repaired", errors)
        changed, retired, spans_rewritten = [], [], 0
        for cid, plan in plans.items():
            claim = by_id[cid]
            history = list(claim.get("repairs") or [])
            entry = {"round": len(history) + 1, "action": plan["action"], "at": stamp,
                     "check_note": claim.get("check_note") or "", "text": claim["text"],
                     "anchors": [_loc(a) for a in claim["anchors"]]}
            history.append(entry)
            claim["repairs"] = history
            if plan["action"] == "retire":
                claim.update(freshness="retired", freshness_reason=f"repair: {plan['reason']}", retired_at=stamp)
                claim.pop("candidates", None)
                retired.append(cid)
                continue
            if "anchors" in plan:
                claim["anchors"] = plan["anchors"]
            if "text" in plan:
                claim["text"] = plan["text"]
            claim.update(check="unchecked", check_note="")
            claim.pop("checked_at", None)
            changed.append(cid)
        if doc is not None:
            for span in iter_spans(doc):
                plan = plans.get(span.get("claim"))
                if plan and "span" in plan and span["text"] != plan["span"]:
                    span["text"] = plan["span"]
                    spans_rewritten += 1
            if spans_rewritten:
                doc_errors, _ = check_document(doc)
                if doc_errors:
                    raise ContractError("validation_failed", "the rewritten spans break the document; nothing was "
                                        "repaired", doc_errors)
                doc["revision"] = revision(doc)
        store.write_held("map", map_layer)
        left = [c["id"] for c in map_layer["claims"]
                if c.get("check") == "not_supported" and c.get("freshness") == "current"]
    return {"changed": changed, "retired": retired, "spans_rewritten": spans_rewritten,
            "revision": (doc or {}).get("revision"), "still_not_supported": len(left),
            "rounds": {cid: len(by_id[cid]["repairs"]) for cid in plans}}

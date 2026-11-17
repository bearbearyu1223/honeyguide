"""The repair pass: after the Checker, the Cartographer fixes the map claims it marked ``not_supported``.

``claims repair`` takes, per claim, one of three actions:

- ``anchor``: the claim is true but cites too few lines. ``anchors`` is the claim's **whole** new anchor list (keep
  the old quotes you still want), quoted like any draft anchor, so the cited lines show the whole claim.
- ``rewrite``: the lines show less than the claim says. ``text`` is the narrower claim; ``span`` is the phrase the map
  shows for it (required when a span shows the claim, so the page never says more than the claim); ``anchors``
  optionally replaces the anchor list too.
- ``retire``: neither fix works (the claim is wrong or overstated past saving). ``reason`` says why; the claim stays
  on the page struck through, as any retired claim.

Answers get the same pass. With ``response: r_...`` the call repairs that answer's claims (the answering agent,
Investigator or Tracer, after the Checker), under the same rules; a ``rewrite`` then narrows the answer's spans that
show the claim, and the answer's text and revision follow. Without it, map claims only.

Claim ids never change, so questions and notes on them survive. Every anchored or rewritten claim goes back to
``check: unchecked`` (its old verdict and note move into its ``repairs`` history), so the Checker re-checks exactly
the changed claims. Nothing is written unless the whole call is valid.

Passes and rounds: every call names its repair ``pass`` (an id ``p_<12 hex>`` from ``claims repair-pass``, which the
Guide mints once per repair pass) and its ``round`` within that pass (1 or 2). A claim takes at most ``MAX_ROUNDS``
repairs **per pass**, one per round; after that it stays flagged until a later pass. Each ``repairs`` history entry
records its ``pass`` and ``round``. Entries saved before passes existed have no ``pass``; together they count as one
legacy pass, so they never use up a new pass's rounds.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from .claims import commit_of, label_errors, resolve_one
from .contract import ContractError
from .gitio import Repo
from .mapdoc import check_document, iter_spans, revision, space_sentences, spans_text, text_revision
from .store import Store, now_iso

ACTIONS = ("anchor", "rewrite", "retire")
MAX_ROUNDS = 2
MAX_REASON = 500
PASS_ID = re.compile(r"p_[0-9a-f]{12}")
LEGACY_PASS = None   # the ``pass`` of a history entry saved before passes existed


def new_pass() -> dict:
    """``claims repair-pass``: a fresh repair-pass id (48 random bits; nothing is stored)."""
    return {"pass": "p_" + secrets.token_hex(6)}


def _pass_round(data: dict) -> tuple[str, int]:
    pid, rnd = data.get("pass"), data.get("round")
    errors = []
    if not isinstance(pid, str) or not PASS_ID.fullmatch(pid):
        errors.append("pass: needs the repair pass's id (p_ + 12 hex, from claims repair-pass)")
    if isinstance(rnd, bool) or not isinstance(rnd, int) or not 1 <= rnd <= MAX_ROUNDS:
        errors.append(f"round: needs the round within the pass, 1 to {MAX_ROUNDS}")
    if errors:
        raise ContractError("bad_input", "; ".join(errors), errors)
    return pid, rnd


def pass_history(claim: dict, pid: str | None) -> list[dict]:
    """The claim's repairs in pass ``pid`` (``LEGACY_PASS``: the entries saved without a pass)."""
    return [e for e in claim.get("repairs") or [] if e.get("pass") == pid]


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


def _response_of(answers: dict, rid: str) -> dict:
    for r in answers["responses"]:
        if r["id"] == rid:
            return r
    raise ContractError("not_found", f"no answer {rid!r}", [f"response: {rid}: no such answer"])


def repair(repo: Repo, store: Store, data: Any) -> dict:
    """``claims repair``: ``{pass, round, repairs: [{claim, action: anchor|rewrite|retire, anchors?, text?, span?,
    reason?}], response?, commit?}``. Without ``response``, map claims; with it, that answer's claims. Anchors resolve at
    ``commit`` (default: the map's commit, or the answer's)."""
    items = _items(data)
    pid, rnd = _pass_round(data)
    rid = data.get("response")
    if rid is not None and (not isinstance(rid, str) or not rid.strip()):
        raise ContractError("bad_input", "response must be an answer id (r_...)")
    if rid is None:
        default_commit = store.load("map").get("commit")
    else:
        default_commit = _response_of(store.load("answers"), rid).get("commit")
    commit = commit_of(repo, data.get("commit") or default_commit)
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
        done = pass_history(claim, pid)
        if len(done) >= MAX_ROUNDS:
            return [f"{cid}: already repaired {MAX_ROUNDS} times in pass {pid}; it stays flagged"]
        if any(e.get("round", 0) >= rnd for e in done):
            last = max(e.get("round", 0) for e in done)
            return [f"{cid}: already repaired in round {last} of pass {pid}; this call is round {rnd}"]
        if "anchors" in plan:
            return label_errors(claim["evidence"], plan["anchors"], cid)
        return []

    scope = "map" if rid is None else f"answer {rid}"
    with store.locked():
        if rid is None:
            layer = store.load("map")
            claims, doc = layer["claims"], layer.get("document")
            shown_spans = list(iter_spans(doc))
        else:
            layer = store.load("answers")
            response = _response_of(layer, rid)
            claims, doc = response["claims"], None
            shown_spans = list(response.get("spans") or [])
        by_id = {c["id"]: c for c in claims}
        missing = [cid for cid in plans if cid not in by_id]
        errors = [f"{m}: no such map claim (repair takes map claims; give response for an answer's)" if rid is None
                  else f"{m}: no such claim in answer {rid} (repair takes that answer's claims only)" for m in missing]
        shown = {}
        for span in shown_spans:
            if span.get("claim") in plans:
                shown[span["claim"]] = shown.get(span["claim"], 0) + 1
        for cid, plan in plans.items():
            if cid in by_id:
                errors += problems(by_id[cid], plan)
                if plan["action"] == "rewrite" and shown.get(cid) and "span" not in plan:
                    errors.append(f"{cid}: the {scope} shows this claim in {shown[cid]} span(s); give span, the "
                                  "narrower phrase it shows, so the page never says more than the claim")
        if errors:
            raise ContractError("not_found" if missing else "validation_failed",
                                f"{len(errors)} problem(s); nothing was repaired", errors)
        changed, retired, spans_rewritten = [], [], 0
        for cid, plan in plans.items():
            claim = by_id[cid]
            history = list(claim.get("repairs") or [])
            entry = {"pass": pid, "round": rnd, "action": plan["action"], "at": stamp,
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
        for span in shown_spans:
            plan = plans.get(span.get("claim"))
            if plan and "span" in plan and span["text"] != plan["span"]:
                span["text"] = plan["span"]
                spans_rewritten += 1
        if rid is None:
            if doc is not None and spans_rewritten:
                doc_errors, _ = check_document(doc)
                if doc_errors:
                    raise ContractError("validation_failed", "the rewritten spans break the document; nothing was "
                                        "repaired", doc_errors)
                doc["revision"] = revision(doc)
            rev = (doc or {}).get("revision")
            store.write_held("map", layer)
        else:
            if spans_rewritten:
                # the answer's text is its spans joined: a narrower span changes it (and its revision), so a follow-up
                # anchored in the old text is re-found by its quote on the page, as on a regenerated map
                response["spans"] = space_sentences(response["spans"])
                response["text"] = spans_text(response["spans"])
                response["revision"] = text_revision(response["text"])
            rev = response.get("revision")
            store.write_held("answers", layer)
        left = [c["id"] for c in claims if c.get("check") == "not_supported" and c.get("freshness") == "current"]
    return {"changed": changed, "retired": retired, "spans_rewritten": spans_rewritten, "revision": rev,
            "still_not_supported": len(left), "pass": pid, "round": rnd,
            "rounds": {cid: len(pass_history(by_id[cid], pid)) for cid in plans},
            **({"response": rid} if rid is not None else {})}

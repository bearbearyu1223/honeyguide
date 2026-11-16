"""Memory and refresh, end to end (T7.5): apply a refresh, retire claims, list claims for the Checker, and the
memory state the page shows ("Refreshing · N claims being re-checked" / "Up to date at <sha>").

Every write here holds the store's lock once for the whole change, so nothing another writer saves in between
is lost, and a refresh is planned from the same data it rewrites.
"""

from __future__ import annotations

import copy
from typing import Any

from .claims import commit_of
from .contract import ContractError, load_side, need, write_side_held
from .gitio import Repo
from .mapdoc import iter_spans
from .refresh import RefreshPlan, apply_result, plan_refresh
from .store import CHECKS, FRESHNESS, Store, all_claims, now_iso

SCOPES = ("map", "answers", "all")
SHORT = 12  # hex digits of a commit shown on the page, as elsewhere in the contract


# -- refresh apply ----------------------------------------------------------------------------


def plan_json(plan: RefreshPlan) -> dict:
    """A plan as JSON (the shape ``refresh-plan --json`` prints)."""
    def loc(path, start, end):
        return f"{path}:{start}-{end}" if start is not None else f"{path}:?"
    return {
        "base": plan.base, "target": plan.target, "warnings": plan.warnings, "counts": plan.counts(),
        "claims": [{"id": c.claim_id, "response": c.response_id, "state": c.state, "reason": c.reason,
                    "anchors": [{"from": loc(a.old.path, a.old.start, a.old.end),
                                 "to": loc(a.path, a.reloc.start, a.reloc.end), "state": a.state,
                                 "reason": a.reloc.reason} for a in c.anchors]} for c in plan.claims],
        "uncovered": [vars(u) for u in plan.uncovered], "unoutlined": plan.unoutlined,
    }


def apply_to_layers(map_layer: dict, answers: dict, plan: RefreshPlan) -> None:
    """Rewrite both layers in place from ``plan`` and advance the map's commit to the plan's target."""
    by_id = {r.claim_id: r for r in plan.claims}

    def fix(claims: list[dict]) -> list[dict]:
        return [apply_result(c, by_id[c["id"]], plan.target) if c["id"] in by_id else c for c in claims]

    map_layer["claims"] = fix(map_layer["claims"])
    for response in answers["responses"]:
        response["claims"] = fix(response["claims"])
    map_layer["commit"] = plan.target


def refresh_apply(repo: Repo, store: Store, data: Any) -> dict:
    """``refresh apply``: plan and apply in one hold of the lock; log the refresh. Input ``{to?, base?, note?}``.

    Writes answers first, then the map (whose commit moving to the target marks the refresh done), then the
    session log. A crash part-way leaves the map's commit behind, so ``status`` says to refresh again, and
    re-running is safe: claims already moved to the target read as unchanged.
    """
    data = data if isinstance(data, dict) else {}
    to = data.get("to") or "HEAD"
    commit_of(repo, to)  # a bad revision is not_found before anything else
    base = data.get("base")
    if base is not None:
        commit_of(repo, base)
    note = data.get("note") or ""
    if not isinstance(note, str):
        raise ContractError("bad_input", "note must be a string")
    map_layer, answers = store.load("map"), store.load("answers")
    if map_layer["commit"] is None and not any(True for _ in all_claims(map_layer, answers)):
        raise ContractError("not_found", "nothing saved for this repo yet: explore first")
    # Warm the file cache outside the lock (git reads are the slow part), so the locked pass is short.
    plan_refresh(repo, all_claims(map_layer, answers), target=to, base=base or map_layer["commit"])

    with store.locked():
        map_layer, answers = store.load("map"), store.load("answers")
        old_commit = map_layer["commit"]
        plan = plan_refresh(repo, all_claims(map_layer, answers), target=to, base=base or old_commit)
        apply_to_layers(map_layer, answers, plan)
        entry = {"at": now_iso(), "base": old_commit, "target": plan.target, "counts": plan.counts(),
                 "uncovered": len(plan.uncovered), "note": note[:500]}
        session = load_side(store, "session")
        session["refresh_log"].append(entry)
        store.write_held("answers", answers)
        store.write_held("map", map_layer)
        write_side_held(store, "session", session)
    return {**plan_json(plan), "applied": True, "previous_commit": old_commit, "entry": entry}


# -- retire -----------------------------------------------------------------------------------


def _ids(data: Any) -> list[str]:
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    if isinstance(data.get("claims"), list):
        ids = data["claims"]
    else:
        ids = [need(data, "claim")]
    if not ids or not all(isinstance(i, str) and i.strip() for i in ids):
        raise ContractError("bad_input", "claims must be a non-empty list of claim ids")
    return list(dict.fromkeys(ids))


def retire_in(claims: list[dict], wanted: dict[str, str], stamp: str) -> list[str]:
    """Retire the claims in ``wanted`` (id -> reason) found in ``claims``; returns the ids newly retired."""
    done = []
    for claim in claims:
        reason = wanted.get(claim["id"])
        if reason is None or claim.get("freshness") == "retired":
            continue
        claim.update(freshness="retired", freshness_reason=reason, retired_at=stamp)
        claim.pop("candidates", None)
        done.append(claim["id"])
    return done


def retire(store: Store, data: Any) -> dict:
    """``claims retire``: ``{claim | claims: [...], reason}``. Retired claims stay in the store (the page
    shows them struck through) and are never retrieved. Retiring a retired claim is a no-op."""
    ids = _ids(data)
    reason = " ".join(need(data, "reason").split())[:500]
    stamp = now_iso()
    with store.locked():
        map_layer, answers = store.load("map"), store.load("answers")
        every = {c["id"]: c for _, c in all_claims(map_layer, answers)}
        missing = [i for i in ids if i not in every]
        if missing:
            raise ContractError("not_found", f"{len(missing)} unknown claim id(s); nothing was retired",
                                [f"{m}: no such claim" for m in missing])
        wanted = dict.fromkeys(ids, reason)
        done = retire_in(map_layer["claims"], wanted, stamp)
        done += [i for r in answers["responses"] for i in retire_in(r["claims"], wanted, stamp)]
        store.write_held("answers", answers)
        store.write_held("map", map_layer)
    return {"retired": done, "already_retired": [i for i in ids if i not in done]}


# -- list -------------------------------------------------------------------------------------


def _filter(data: dict, key: str, allowed: tuple[str, ...]) -> set[str] | None:
    value = data.get(key)
    if value is None:
        return None
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not values or any(v not in allowed for v in values):
        raise ContractError("bad_input", f"{key} must be one of {', '.join(allowed)} (or a list of them)")
    return set(values)


LISTED = ("id", "key", "text", "evidence", "anchors", "check", "check_note", "checked_at", "freshness",
          "freshness_reason", "candidates", "searched", "rechecked_at", "retired_at", "repairs")


def list_claims(store: Store, data: Any) -> dict:
    """``claims list``: ``{scope?: map|answers|all, responses?: [r_...], check?, freshness?, ids?, spans?}``.

    Claims only (text, evidence, anchors, check and freshness, candidates when stale, repairs): never notes or the
    questions' text, so the Checker reads no more than it judges. ``spans: true`` adds ``shown_as`` to each map
    claim: the phrases the map document shows for it (the repair pass rewrites them with the claim).
    """
    data = data if isinstance(data, dict) else {}
    scope = data.get("scope", "all")
    if scope not in SCOPES:
        raise ContractError("bad_input", f"scope must be one of {', '.join(SCOPES)}")
    responses = data.get("responses")
    if responses is not None:
        if not isinstance(responses, list) or not all(isinstance(r, str) for r in responses):
            raise ContractError("bad_input", "responses must be a list of response ids")
        if scope == "map":
            raise ContractError("bad_input", "responses picks answers; use scope answers or all")
        scope = "answers"
    checks = _filter(data, "check", CHECKS)
    freshness = _filter(data, "freshness", FRESHNESS)
    ids = data.get("ids")
    if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
        raise ContractError("bad_input", "ids must be a list of claim ids")
    map_layer, answers = store.load("map"), store.load("answers")
    shown: dict[str, list[str]] = {}
    if data.get("spans"):
        for span in iter_spans(map_layer.get("document")):
            if span.get("claim"):
                shown.setdefault(span["claim"], []).append(span["text"])
    if responses is not None:
        known = {r["id"] for r in answers["responses"]}
        missing = [r for r in responses if r not in known]
        if missing:
            raise ContractError("not_found", "unknown response id(s)", [f"{m}: no such answer" for m in missing])
    out = []
    for response_id, claim in all_claims(map_layer, answers):
        if (scope == "map" and response_id is not None) or (scope == "answers" and response_id is None):
            continue
        if responses is not None and response_id not in responses:
            continue
        if checks is not None and claim.get("check") not in checks:
            continue
        if freshness is not None and claim.get("freshness") not in freshness:
            continue
        if ids is not None and claim["id"] not in ids:
            continue
        row = {k: copy.deepcopy(claim[k]) for k in LISTED if k in claim}
        if data.get("spans") and response_id is None:
            row["shown_as"] = shown.get(claim["id"], [])
        out.append({**row, "response": response_id})
    return {"claims": out, "count": len(out)}


# -- what the page shows ------------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def memory_state(repo: Repo, store: Store) -> dict:
    """The page header's memory line and the counts behind it.

    ``state``: ``empty`` (nothing saved), ``behind`` (the map's commit is not HEAD: refresh not applied yet),
    ``refreshing`` (stale claims still wait for the Checker), ``up_to_date``. ``headline`` is the exact text
    for the header. ``rechecked_since_visit`` counts claims re-checked after going stale (verdict recorded on a
    stale claim) since the previous visit; ``checked_since_visit`` counts every verdict since then.
    """
    map_layer, answers = store.load("map"), store.load("answers")
    claims = [c for _, c in all_claims(map_layer, answers)]
    session = load_side(store, "session")
    since = session.get("previous_visit")
    head = repo.rev("HEAD")
    commit = map_layer.get("commit")
    fresh = {f: sum(1 for c in claims if c.get("freshness") == f) for f in FRESHNESS}
    awaiting = sum(1 for c in claims if c.get("freshness") == "stale" and c.get("check") == "unchecked")
    if commit is None and not claims:
        state, headline = "empty", "Not mapped yet"
    elif commit != head:
        state = "behind"
        headline = f"Map at {(commit or '-')[:SHORT]} · HEAD is {head[:SHORT]}: refresh pending"
    elif awaiting:
        state, headline = "refreshing", f"Refreshing · {_plural(awaiting, 'claim')} being re-checked"
    else:
        state, headline = "up_to_date", f"Up to date at {head[:SHORT]}"
    log = session.get("refresh_log") or []
    return {
        "state": state, "headline": headline, "head": head, "map_commit": commit, "dirty": repo.dirty(),
        "freshness": fresh, "awaiting_recheck": awaiting,
        "stale_not_supported": sum(1 for c in claims if c.get("freshness") == "stale"
                                   and c.get("check") == "not_supported"),
        "previous_visit": since, "last_visit": session.get("last_visit"),
        "rechecked_since_visit": sum(1 for c in claims if since and (c.get("rechecked_at") or "") > since),
        "checked_since_visit": sum(1 for c in claims if since and (c.get("checked_at") or "") > since),
        "last_refresh": log[-1] if log else None,
    }

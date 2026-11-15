"""The question inbox: questions and follow-ups posted from the page, their lifecycle, recording an answer, and
the watcher that wakes the Claude Code session.

Questions and responses share ``answers.json``, so "save the answer and mark the question answered" is one atomic
write: a crash leaves the question unanswered with no response, or answered with exactly one.
"""

from __future__ import annotations

import copy
import sys
import time
from typing import Any, Callable, TextIO

from .claims import build_claims, build_path, commit_of
from .contract import ContractError, check_agent, need
from .docanchor import make_anchor
from .gitio import Repo
from .mapdoc import check_spans, claims_in, plain_text, rewrite_refs, span_ranges, spans_ranges, spans_text, \
    text_revision
from .retrieve import Context, Hit, retrieve
from .store import Store, new_id, now_iso

STATES = ("open", "investigating", "answered", "failed")
MOVES = {
    "open": {"investigating", "answered", "failed"},
    "investigating": {"answered", "failed", "open"},
    "failed": {"open"},
    "answered": set(),
}
MAX_TEXT = 4000


def status_of(question: dict, answered_ids: set[str] | None = None) -> str:
    """Records from before T7 carry no status: answered if a response points at them, else open."""
    status = question.get("status")
    if status in STATES:
        return status
    return "answered" if answered_ids and question["id"] in answered_ids else "open"


def _find(data: dict, question_id: str) -> dict:
    for q in data["questions"]:
        if q["id"] == question_id:
            return q
    raise ContractError("not_found", f"no question {question_id!r}")


def _move(data: dict, question: dict, to: str) -> None:
    answered = {r["parent"] for r in data["responses"]}
    now = status_of(question, answered)
    if to not in MOVES[now]:
        details = []
        if now == "answered":
            details = [f"answered by {r['id']}" for r in data["responses"] if r["parent"] == question["id"]]
        raise ContractError("invalid_transition", f"{question['id']}: {now} -> {to} is not allowed", details)
    question["status"] = to


# -- documents the page annotates --------------------------------------------------------


def document_text(store: Store, doc: str) -> tuple[str, str, list]:
    """``(plain text, revision, span ranges)`` of ``map`` or ``answer:<id>``."""
    if doc == "map":
        document = store.load("map").get("document")
        if not document:
            raise ContractError("not_found", "there is no map yet")
        return plain_text(document), document.get("revision", ""), span_ranges(document)
    if isinstance(doc, str) and doc.startswith("answer:"):
        rid = doc.split(":", 1)[1]
        for r in store.load("answers")["responses"]:
            if r["id"] == rid:
                spans = r.get("spans") or [{"text": r["text"]}]
                return r["text"], r.get("revision") or text_revision(r["text"]), spans_ranges(spans)
        raise ContractError("not_found", f"no answer {rid!r}")
    raise ContractError("bad_input", "doc must be 'map' or 'answer:<id>'")


def page_anchor(store: Store, raw: Any) -> dict | None:
    """A DocumentAnchor from the page's selection, checked against the current text (context filled here)."""
    if raw is None:
        return None
    doc = need(raw, "doc")
    start, end = raw.get("start"), raw.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ContractError("bad_input", "anchor needs integer start and end")
    text, rev, _ = document_text(store, doc)
    if raw.get("revision") != rev:
        raise ContractError("invalid_transition", "the page is showing an older version; reload it")
    try:
        anchor = make_anchor(doc, rev, text, start, end)
    except ValueError as exc:
        raise ContractError("bad_input", str(exc)) from None
    if raw.get("quote") is not None and raw["quote"] != anchor.quote:
        raise ContractError("bad_input", "the quote doesn't match the text at those offsets")
    return anchor.to_dict()


def _text(data: Any) -> str:
    text = need(data, "text").strip()
    if len(text) > MAX_TEXT:
        raise ContractError("bad_input", f"text is longer than {MAX_TEXT} characters")
    return text


def post_question(store: Store, data: Any, author: str = "user") -> dict:
    """A question from the page (or a follow-up when ``parent_response`` is given). Lands ``open``."""
    text = _text(data)
    parent = data.get("parent_response")
    anchor = page_anchor(store, data.get("anchor"))
    if parent is not None:
        if anchor is None or anchor["doc"] != f"answer:{parent}":
            raise ContractError("bad_input", "a follow-up's anchor must be on its parent answer")
    record = {"id": new_id("q"), "kind": "question", "text": text, "anchor": anchor, "author": author,
              "created_at": now_iso(), "parent_response": parent, "status": "open", "agent": None,
              "reopens": 0}
    store.update("answers", lambda d: d["questions"].append(record))
    return record


def post_note(store: Store, data: Any) -> dict:
    text = _text(data)
    anchor = page_anchor(store, data.get("anchor"))
    share = data.get("share_with_agents", False)
    if not isinstance(share, bool):
        raise ContractError("bad_input", "share_with_agents must be true or false")
    from_response = data.get("from_response")
    if from_response is not None and not any(r["id"] == from_response
                                             for r in store.load("answers")["responses"]):
        raise ContractError("not_found", f"no answer {from_response!r}")
    return store.add_note(text, anchor, share_with_agents=share, from_response=from_response)


# -- lifecycle -----------------------------------------------------------------------------


def transition(store: Store, question_id: str, to: str, change: Callable[[dict], None] | None = None) -> dict:
    def apply(data: dict) -> dict:
        q = _find(data, question_id)
        _move(data, q, to)
        if change:
            change(q)
        return copy.deepcopy(q)
    return store.update("answers", apply)


def claim(store: Store, data: Any) -> dict:
    agent = check_agent(data.get("agent") if isinstance(data, dict) else None)
    return transition(store, need(data, "id"), "investigating",
                      lambda q: q.update(agent=agent, claimed_at=now_iso()))


def fail(store: Store, data: Any) -> dict:
    reason = need(data, "reason").strip()[:500]
    return transition(store, need(data, "id"), "failed", lambda q: q.update(failed_at=now_iso(), error=reason))


def release(store: Store, data: Any) -> dict:
    question_id = need(data, "id")
    if status_of(_find(store.load("answers"), question_id)) != "investigating":
        raise ContractError("invalid_transition", f"{question_id}: only an investigating question can be released")
    return transition(store, question_id, "open", lambda q: q.update(agent=None))


def reopen(store: Store, data: Any) -> dict:
    question_id = need(data, "id")
    if status_of(_find(store.load("answers"), question_id)) != "failed":
        raise ContractError("invalid_transition", f"{question_id}: only a failed question can be retried")
    return transition(store, question_id, "open",
                      lambda q: q.update(agent=None, error=None, reopens=int(q.get("reopens") or 0) + 1))


def record_answer(store: Store, repo: Repo, data: Any) -> dict:
    """``answer record``: resolve and validate everything first, then one atomic write."""
    question_id = need(data, "question")
    agent = check_agent(data.get("agent"))
    commit = commit_of(repo, data.get("commit"))
    claims, keys = build_claims(repo, data.get("claims") or [], commit)
    if "spans" in data:
        errors: list[str] = []
        check_spans(data["spans"], "spans", errors)
        if errors:
            raise ContractError("validation_failed", "bad spans", errors)
        spans = rewrite_refs(data["spans"], keys)
        unknown = [s["claim"] for s in spans if s.get("claim") and s["claim"] not in keys.values()]
        if unknown:
            raise ContractError("validation_failed", "spans cite claims not in this answer",
                                [f"spans: claim {u!r} is not a claim key in this answer" for u in unknown])
        text = spans_text(spans)
    else:
        text = _text(data)
        spans = None
    path = build_path(data["path"], keys) if data.get("path") is not None else None
    generation = data.get("generation") or {}
    if not isinstance(generation, dict):
        raise ContractError("bad_input", "generation must be an object")
    stamp = now_iso()
    response = {"id": new_id("r"), "parent": question_id, "agent": agent, "text": text, "spans": spans,
                "revision": text_revision(text), "claims": claims, "path": path, "commit": commit,
                "generation": generation, "created_at": stamp}

    def apply(answers: dict) -> dict:
        q = _find(answers, question_id)
        _move(answers, q, "answered")
        q.update(answered_at=stamp, response=response["id"], agent=agent, error=None)
        answers["responses"].append(response)
        return copy.deepcopy(q)

    question = store.update("answers", apply)
    return {"response": response, "question": question}


# -- reading -------------------------------------------------------------------------------


def inbox(store: Store) -> dict:
    data = store.load("answers")
    answered = {r["parent"] for r in data["responses"]}
    out: dict[str, list] = {"open": [], "investigating": []}
    for q in data["questions"]:
        status = status_of(q, answered)
        if status in out:
            out[status].append({**q, "status": status})
    return out


def _hit(hit: Hit) -> dict:
    return {"claim": hit.claim, "response": hit.response_id, "score": hit.score, "reasons": hit.reasons,
            "marked": hit.marked}


def show(store: Store, data: Any) -> dict:
    """``question show``: the question, its thread (oldest first), and what retrieval hands an agent."""
    question_id = need(data, "id")
    answers = store.load("answers")
    q = _find(answers, question_id)
    responses = {r["id"]: r for r in answers["responses"]}
    questions = {x["id"]: x for x in answers["questions"]}
    thread = []
    parent = q.get("parent_response")
    while parent and parent in responses and len(thread) < 50:
        r = responses[parent]
        asked = questions.get(r["parent"])
        thread.insert(0, {"question": asked, "response": r})
        parent = asked.get("parent_response") if asked else None
    claim_ids: list[str] = []
    anchor = q.get("anchor")
    if anchor:
        try:
            _, _, ranges = document_text(store, anchor["doc"])
            claim_ids = claims_in(ranges, anchor["start"], anchor["end"])
        except ContractError:
            pass
    got = retrieve(store.load("map"), answers, store.load("notes"),
                   Context(text=q["text"] + " " + (anchor or {}).get("quote", ""), claim_ids=claim_ids))
    context = {"selected_claims": claim_ids, "map_claims": [_hit(h) for h in got.map_claims],
               "answers": [{"response": a["response"], "question": a["question"],
                            "hits": [_hit(h) for h in a["hits"]], "has_unservable": a["has_unservable"]}
                           for a in got.answers],
               "notes": got.notes}
    status = status_of(q, {r["parent"] for r in answers["responses"]})
    return {"question": {**q, "status": status}, "thread": thread, "context": context}


def threads(store: Store) -> dict:
    data = store.load("answers")
    answered = {r["parent"] for r in data["responses"]}
    return {"questions": [{**q, "status": status_of(q, answered)} for q in data["questions"]],
            "responses": data["responses"]}


# -- watch ---------------------------------------------------------------------------------


def watch_line(q: dict) -> str:
    kind = "follow-up" if q.get("parent_response") else "question"
    text = " ".join(q["text"].split())
    if len(text) > 120:
        text = text[:119] + "…"
    return f"{q['id']} {kind} {text}"


def watch(store: Store, out: TextIO = sys.stdout, *, interval: float = 1.0, follow: bool = True,
          timeout: float | None = None, should_stop: Callable[[], bool] | None = None) -> int:
    """Print one line per question that becomes open; never writes. Returns 0, or 3 on timeout."""
    seen: set[str] = set()
    start = time.monotonic()
    while True:
        try:
            pending = inbox(store)["open"]
        except Exception as exc:  # an unreadable file must not kill the session's watcher
            print(f"honeyguide watch: {exc}", file=sys.stderr, flush=True)
            pending = []
        new = [q for q in pending if f"{q['id']}:{q.get('reopens') or 0}" not in seen]
        for q in new:
            seen.add(f"{q['id']}:{q.get('reopens') or 0}")
            print(watch_line(q), file=out, flush=True)
        if new and not follow:
            return 0
        if should_stop and should_stop():
            return 0
        if timeout is not None and time.monotonic() - start > timeout:
            return 3
        time.sleep(interval)

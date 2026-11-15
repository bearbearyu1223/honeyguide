"""The activity log the page's avatars read, and session state (last visit, refresh log).

Never needed for correctness: an entry left ``working`` by a crashed agent only shows a stale avatar, which the
page ages out (``STALE_AFTER``) and the Guide can finish.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from .contract import ContractError, check_agent, load_side, need, update_side
from .store import Store, new_id, now_iso

KEEP_ENDED = 200
RECENT_MINUTES = 10
STALE_AFTER = timedelta(minutes=30)
MAX_STATUS = 200


def _status(data: Any) -> str:
    return " ".join(need(data, "status").split())[:MAX_STATUS]


def start(store: Store, data: Any) -> dict:
    agent = check_agent(data.get("agent") if isinstance(data, dict) else None)
    question = data.get("question")
    if question is not None and not isinstance(question, str):
        raise ContractError("bad_input", "question must be a question id")
    stamp = now_iso()
    entry = {"id": new_id("a"), "agent": agent, "question": question, "status": _status(data),
             "state": "working", "started_at": stamp, "updated_at": stamp, "ended_at": None}
    update_side(store, "activity", lambda d: d["entries"].append(entry))
    return entry


def _change(store: Store, entry_id: str, change) -> dict:
    def apply(data: dict) -> dict:
        for entry in data["entries"]:
            if entry["id"] == entry_id:
                change(entry)
                entry["updated_at"] = now_iso()
                ended = [e for e in data["entries"] if e["state"] != "working"]
                if len(ended) > KEEP_ENDED:
                    drop = {e["id"] for e in sorted(ended, key=lambda e: e["ended_at"] or "")[:-KEEP_ENDED]}
                    data["entries"] = [e for e in data["entries"] if e["id"] not in drop]
                return copy.deepcopy(entry)
        raise ContractError("not_found", f"no activity entry {entry_id!r}")
    return update_side(store, "activity", apply)


def update(store: Store, data: Any) -> dict:
    status = _status(data)

    def change(entry: dict) -> None:
        if entry["state"] != "working":
            raise ContractError("invalid_transition", f"{entry['id']} already ended ({entry['state']})")
        entry["status"] = status
    return _change(store, need(data, "id"), change)


def finish(store: Store, data: Any) -> dict:
    state = data.get("state") if isinstance(data, dict) else None
    if state not in ("done", "failed"):
        raise ContractError("bad_input", "state must be done or failed")
    status = _status(data) if isinstance(data.get("status"), str) and data["status"].strip() else None

    def change(entry: dict) -> None:
        if entry["state"] != "working":
            raise ContractError("invalid_transition", f"{entry['id']} already ended ({entry['state']})")
        entry.update(state=state, ended_at=now_iso())
        if status:
            entry["status"] = status
    return _change(store, need(data, "id"), change)


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def listing(store: Store, now: datetime | None = None) -> dict:
    """``working`` (with ``stale`` set when not updated for 30 min) and entries ended in the last 10 minutes."""
    now = now or datetime.now(timezone.utc)
    working, recent = [], []
    for entry in load_side(store, "activity")["entries"]:
        if entry["state"] == "working":
            working.append({**entry, "stale": now - _parse(entry["updated_at"]) > STALE_AFTER})
        elif entry.get("ended_at") and now - _parse(entry["ended_at"]) <= timedelta(minutes=RECENT_MINUTES):
            recent.append(entry)
    recent.sort(key=lambda e: e["ended_at"], reverse=True)
    return {"working": working, "recent": recent}


# -- session -------------------------------------------------------------------------------


def visit(store: Store) -> dict:
    """The page loaded: remember the previous visit (for "N re-checked since your last visit"), stamp now."""
    def apply(data: dict) -> dict:
        data["previous_visit"] = data.get("last_visit")
        data["last_visit"] = now_iso()
        return {"previous_visit": data["previous_visit"], "last_visit": data["last_visit"]}
    return update_side(store, "session", apply)


def add_refresh(store: Store, data: Any) -> dict:
    base, target = need(data, "base"), need(data, "target")
    counts = data.get("counts") or {}
    if not isinstance(counts, dict) or not all(isinstance(v, int) for v in counts.values()):
        raise ContractError("bad_input", "counts must map state names to integers")
    note = data.get("note") or ""
    if not isinstance(note, str):
        raise ContractError("bad_input", "note must be a string")
    entry = {"at": now_iso(), "base": base, "target": target, "counts": counts, "note": note[:500]}
    update_side(store, "session", lambda d: d["refresh_log"].append(entry))
    return entry

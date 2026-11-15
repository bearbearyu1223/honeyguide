"""Shared pieces of the agent contract: the error type every command reports, the agent names, and the
small side files (activity, session) that live beside the three memory layers.

Side files use the store's lock and atomic write, so they get the same crash and concurrency guarantees; they are
kept out of ``store.LAYERS`` so export/import (which iterates the layers) is unchanged.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .store import VERSION, Store, StoreError, atomic_write_text

AGENTS = ("guide", "cartographer", "investigator", "tracer", "checker")
SIDE_FILES = {
    "activity": {"entries": []},
    "session": {"last_visit": None, "previous_visit": None, "refresh_log": []},
}


class ContractError(Exception):
    """A refused call. ``code`` is one of the contract's error codes; ``details`` lists every problem."""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


def need(data: Any, key: str, kind: type = str) -> Any:
    """``data[key]``, required and of ``kind`` (non-empty for strings), else ``bad_input``."""
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    value = data.get(key)
    if not isinstance(value, kind) or (kind is str and not value.strip()):
        raise ContractError("bad_input", f"{key!r} is required ({kind.__name__})")
    return value


def check_agent(agent: Any) -> str:
    if agent not in AGENTS:
        raise ContractError("bad_input", f"unknown agent {agent!r}; one of {', '.join(AGENTS)}")
    return agent


def _side_default(name: str) -> dict:
    return {"schema": f"honeyguide/{name}", "version": VERSION, **json.loads(json.dumps(SIDE_FILES[name]))}


def load_side(store: Store, name: str) -> dict:
    path = store.dir / f"{name}.json"
    data = store._read_json(path)
    if data is None:
        return _side_default(name)
    if not isinstance(data, dict) or data.get("schema") != f"honeyguide/{name}":
        raise StoreError(f"{path}: not a honeyguide/{name} file")
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise StoreError(f"{path}: written by a newer Honeyguide; refusing to touch it")
    for key, default in SIDE_FILES[name].items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


def write_side_held(store: Store, name: str, data: dict) -> None:
    """Write a side file; the caller holds ``store.locked()``."""
    atomic_write_text(store.dir / f"{name}.json", json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def update_side(store: Store, name: str, change: Callable[[dict], Any]) -> Any:
    with store.locked():
        data = load_side(store, name)
        result = change(data)
        write_side_held(store, name, data)
    return result

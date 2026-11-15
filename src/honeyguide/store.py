"""The memory store: ``$HONEYGUIDE_HOME/<repo-id>/`` (default ``~/.honeyguide``), never inside the checkout.

Three layers, one JSON file each: ``map.json`` (the Cartographer's claims), ``answers.json`` (questions,
follow-ups and answers with their claims), ``notes.json`` (personal notes). Every file carries a schema name and
version. Writes are read-modify-write under an exclusive lock and land by temp file + atomic rename, so the page
server and the session can both write, and a crash leaves the old file or the new one, never part of one.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # Windows: writes stay atomic but are not serialized
    fcntl = None  # type: ignore[assignment]

VERSION = 1
LAYERS = {
    "map": {"commit": None, "document": None, "claims": []},
    "answers": {"questions": [], "responses": []},
    "notes": {"notes": []},
}
EVIDENCE = ("read_in_source", "asserted_by_test", "docs", "seen_at_runtime", "inferred",
            "searched_not_found", "general_knowledge")
CHECKS = ("unchecked", "supported", "not_supported", "skipped")
FRESHNESS = ("current", "stale", "retired")
LOCK_TIMEOUT = 10.0


class StoreError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def home() -> Path:
    env = os.environ.get("HONEYGUIDE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".honeyguide"


def atomic_write_text(path: Path, text: str) -> None:
    """``path`` is always either the complete old file or the complete new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):  # directory fsync is unsupported on some filesystems
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def empty_layer(layer: str) -> dict:
    return {"schema": f"honeyguide/{layer}", "version": VERSION, **json.loads(json.dumps(LAYERS[layer]))}


def check_layer(layer: str, data: Any, where: str) -> dict:
    if not isinstance(data, dict) or data.get("schema") != f"honeyguide/{layer}":
        raise StoreError(f"{where}: not a honeyguide/{layer} file")
    version = data.get("version")
    if not isinstance(version, int):
        raise StoreError(f"{where}: no schema version")
    if version > VERSION:
        raise StoreError(f"{where}: written by a newer Honeyguide (version {version}); refusing to touch it")
    for key, default in LAYERS[layer].items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


class Store:
    def __init__(self, repo_id: str, root: Path | None = None) -> None:
        self.repo_id = repo_id
        self.dir = (root or home()) / repo_id

    # -- files ------------------------------------------------------------------------

    def path(self, layer: str) -> Path:
        if layer not in LAYERS and layer != "repo":
            raise KeyError(layer)
        return self.dir / f"{layer}.json"

    def exists(self) -> bool:
        return (self.dir / "repo.json").exists()

    def init(self, identity: dict) -> None:
        """Write ``repo.json`` once; an existing store with another id is an error."""
        with self.locked():
            current = self._read_json(self.path("repo"))
            if current is not None:
                if current.get("id") != identity["id"]:
                    raise StoreError(f"{self.dir}: belongs to {current.get('id')}")
                return
            atomic_write_text(self.path("repo"), json.dumps(
                {"schema": "honeyguide/repo", "version": VERSION, "created_at": now_iso(), **identity},
                indent=1, ensure_ascii=False) + "\n")

    def identity(self) -> dict | None:
        return self._read_json(self.path("repo"))

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoreError(f"{path}: unreadable ({exc}); left as it is") from None

    def load(self, layer: str) -> dict:
        """The layer's current contents (no lock needed: files are replaced atomically)."""
        path = self.path(layer)
        data = self._read_json(path)
        return empty_layer(layer) if data is None else check_layer(layer, data, str(path))

    @contextlib.contextmanager
    def locked(self, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
        """Serialize writers across processes (the page server and the session)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / ".lock", "a+") as handle:
            if fcntl is not None:
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise StoreError(f"{self.dir}: another writer holds the lock") from None
                        time.sleep(0.02)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def update(self, layer: str, change: Callable[[dict], Any]) -> Any:
        """Read, change in place, write back, all under the lock. Returns what ``change`` returns."""
        with self.locked():
            data = self.load(layer)
            result = change(data)
            data["version"] = VERSION
            atomic_write_text(self.path(layer), json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        return result

    # -- records ------------------------------------------------------------------------

    def save_map(self, claims: list[dict], commit: str, document: Any = None) -> None:
        """Replace the map (the Cartographer rebuilds or rewrites it whole)."""
        for claim in claims:
            validate_claim(claim)

        def change(data: dict) -> None:
            data.update(claims=claims, commit=commit)
            if document is not None:
                data["document"] = document
        self.update("map", change)

    def add_question(self, text: str, anchor: dict | None, author: str = "user",
                     parent_response: str | None = None) -> dict:
        record = {"id": new_id("q"), "kind": "question", "text": text, "anchor": anchor, "author": author,
                  "created_at": now_iso(), "parent_response": parent_response}
        self.update("answers", lambda d: d["questions"].append(record))
        return record

    def add_response(self, question_id: str, text: str, claims: list[dict], agent: str,
                     generation: dict | None = None) -> dict:
        for claim in claims:
            validate_claim(claim)
        record = {"id": new_id("r"), "parent": question_id, "agent": agent, "text": text,
                  "claims": claims, "generation": generation or {}, "created_at": now_iso()}

        def change(data: dict) -> None:
            if not any(q["id"] == question_id for q in data["questions"]):
                raise KeyError(question_id)
            data["responses"].append(record)
        self.update("answers", change)
        return record

    def add_note(self, text: str, anchor: dict | None, share_with_agents: bool = False,
                 author: str = "user", from_response: str | None = None) -> dict:
        record = {"id": new_id("n"), "kind": "note", "text": text, "anchor": anchor, "author": author,
                  "created_at": now_iso(), "share_with_agents": bool(share_with_agents),
                  "from_response": from_response}
        self.update("notes", lambda d: d["notes"].append(record))
        return record

    def set_note_sharing(self, note_id: str, share: bool) -> None:
        def change(data: dict) -> None:
            for note in data["notes"]:
                if note["id"] == note_id:
                    note["share_with_agents"] = bool(share)
                    return
            raise KeyError(note_id)
        self.update("notes", change)

    def set_check(self, claim_id: str, verdict: str) -> None:
        """Record the Checker's verdict on a map or answer claim."""
        if verdict not in CHECKS:
            raise ValueError(verdict)

        def apply(claims: list[dict]) -> bool:
            for claim in claims:
                if claim["id"] == claim_id:
                    claim["check"] = verdict
                    claim["checked_at"] = now_iso()
                    return True
            return False

        if self.update("map", lambda d: apply(d["claims"])):
            return
        if not self.update("answers", lambda d: any(apply(r["claims"]) for r in d["responses"])):
            raise KeyError(claim_id)


def make_claim(text: str, evidence: str, anchors: list[dict], **extra: Any) -> dict:
    claim = {"id": new_id("c"), "text": text, "evidence": evidence, "anchors": anchors,
             "check": "unchecked", "freshness": "current", "freshness_reason": "", **extra}
    validate_claim(claim)
    return claim


def validate_claim(claim: dict) -> None:
    for key in ("id", "text", "evidence", "anchors", "check", "freshness"):
        if key not in claim:
            raise ValueError(f"claim {claim.get('id')!r}: missing {key!r}")
    if claim["evidence"] not in EVIDENCE:
        raise ValueError(f"claim {claim['id']!r}: unknown evidence label {claim['evidence']!r}")
    if claim["check"] not in CHECKS or claim["freshness"] not in FRESHNESS:
        raise ValueError(f"claim {claim['id']!r}: bad check or freshness")
    for anchor in claim["anchors"]:
        missing = {"path", "anchor", "start", "end", "commit", "hash"} - set(anchor)
        if missing:
            raise ValueError(f"claim {claim['id']!r}: code anchor without {sorted(missing)}")


def all_claims(map_layer: dict, answers_layer: dict) -> Iterator[tuple[str | None, dict]]:
    """``(response id or None for the map, claim)`` for every saved claim."""
    for claim in map_layer["claims"]:
        yield None, claim
    for response in answers_layer["responses"]:
        for claim in response["claims"]:
            yield response["id"], claim


# -- export / import ----------------------------------------------------------------------


def export_bundle(store: Store, include_private_notes: bool = False) -> dict:
    notes = store.load("notes")
    if not include_private_notes:
        notes["notes"] = [n for n in notes["notes"] if n.get("share_with_agents")]
    return {"schema": "honeyguide/export", "version": VERSION, "exported_at": now_iso(),
            "repo": store.identity(), "map": store.load("map"), "answers": store.load("answers"),
            "notes": notes}


def import_bundle(store: Store, bundle: dict, force: bool = False) -> dict[str, int]:
    """Merge ``bundle`` into ``store`` by record id; the local record wins a clash. Returns counts."""
    if bundle.get("schema") != "honeyguide/export":
        raise StoreError("not a Honeyguide export")
    if not isinstance(bundle.get("version"), int) or bundle["version"] > VERSION:
        raise StoreError("export written by a newer Honeyguide")
    theirs = (bundle.get("repo") or {}).get("id")
    if theirs != store.repo_id and not force:
        raise StoreError(f"export is for {theirs}, this repo is {store.repo_id} (use --force to import anyway)")
    counts = {"added": 0, "kept_local": 0}

    def merge(mine: list[dict], incoming: list[dict]) -> None:
        known = {r["id"] for r in mine}
        for record in incoming:
            if record["id"] in known:
                counts["kept_local"] += 1
            else:
                mine.append(record)
                counts["added"] += 1

    layers = {name: check_layer(name, bundle[name], f"export:{name}") for name in LAYERS}
    for claim in layers["map"]["claims"]:
        validate_claim(claim)

    def merge_map(data: dict) -> None:
        if not data["claims"] and data["commit"] is None:
            data["commit"] = layers["map"]["commit"]
            data["document"] = layers["map"]["document"]
        merge(data["claims"], layers["map"]["claims"])

    store.update("map", merge_map)
    store.update("answers", lambda d: (merge(d["questions"], layers["answers"]["questions"]),
                                       merge(d["responses"], layers["answers"]["responses"])))
    store.update("notes", lambda d: merge(d["notes"], layers["notes"]["notes"]))
    return counts

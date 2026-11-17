"""The map as draft files: the Cartographer writes one JSON file per section, plus its claims, into the
memory store's drafts directory; ``map check`` validates them (structure, claims, readability) and ``map ingest``
saves them. Nothing passes through a shell command line, so the map's size has no limit.

Files in the drafts directory (``honeyguide map draft-dir`` prints and creates it):

- ``meta.json``: ``{"title": ..., "coverage": {deep|scanned|skipped: [{area, why}]}, "commit"?: rev,
  "mode"?: "replace" | "add", "retire"?: [{claim, reason}]}``; ``coverage`` becomes ``document.coverage``
- ``overview.json``, ``modules.json``, ``flows.json``: one section object each (``{id, kind, title, blocks}``);
  ``flows.json`` also holds the path records as ``"flows": [...]``. Other sections: ``section-<name>.json``.
- ``claims.json``, or several ``claims-<name>.json``: a list of claim drafts (or ``{"claims": [...]}``).

Any other ``.json`` file is an error, so a leftover can't slip into the map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contract import ContractError
from .guard import draft_dir_problem
from .store import Store

SECTION_FILES = ("overview.json", "modules.json", "flows.json")
OTHER_SECTION = re.compile(r"^section-[a-z0-9][a-z0-9-]*\.json$")
CLAIMS_FILE = re.compile(r"^claims(?:-[a-z0-9][a-z0-9-]*)?\.json$")


def drafts_root(store: Store) -> Path:
    return store.dir / "drafts"


def map_draft_dir(store: Store, fresh: bool = False) -> Path:
    """The Cartographer's drafts directory for this repo, created if missing; ``fresh`` empties its .json files."""
    d = drafts_root(store) / "map"
    d.mkdir(parents=True, exist_ok=True)
    if fresh:
        for f in d.glob("*.json"):
            if f.is_file() and not f.is_symlink():
                f.unlink()
    return d


AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def agent_draft_dir(store: Store, agent: str, name: str | None = None, fresh: bool = False) -> Path:
    """A scratch directory for one agent's input files: ``drafts/<agent>/[<name>/]``, created if missing.

    Agents write a command's JSON input here with the Write tool and pass ``--input FILE``, so no command line ever
    carries quoted JSON (a pipe or heredoc is a compound command the permission rules refuse). ``name`` keeps
    parallel runs apart (an Investigator per question id). ``fresh`` first removes the .json and .txt files there.
    """
    from .contract import AGENTS
    if agent not in AGENTS:
        raise ContractError("bad_input", f"agent must be one of {', '.join(AGENTS)}")
    if name is not None and not AGENT_NAME.match(name):
        raise ContractError("bad_input", f"name must match {AGENT_NAME.pattern} (a question id is fine)")
    d = drafts_root(store) / agent / (name or "")
    d.mkdir(parents=True, exist_ok=True)
    if fresh:
        for f in list(d.glob("*.json")) + list(d.glob("*.txt")):
            if f.is_file() and not f.is_symlink():
                f.unlink()
    return d


def _load(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.name}: not JSON: {exc}")
    except OSError as exc:
        errors.append(f"{path.name}: can't read: {exc}")
    return None


def assemble(store: Store, path: str | Path) -> tuple[dict, list[str]]:
    """The ``claims save`` input the draft files make, and the files read. Raises ``forbidden`` for a directory
    outside the drafts root, ``validation_failed`` (every problem) for missing or malformed files."""
    why = draft_dir_problem(path, drafts_root(store))
    if why:
        raise ContractError("forbidden", why)
    d = Path(path).expanduser().resolve()
    errors: list[str] = []
    names = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".json" and not f.name.startswith("."))
    unknown = [n for n in names if n != "meta.json" and n not in SECTION_FILES and not OTHER_SECTION.match(n)
               and not CLAIMS_FILE.match(n)]
    errors += [f"{n}: not a draft file (expected meta.json, {', '.join(SECTION_FILES)}, section-<name>.json, "
               "claims[-<name>].json); remove it or rename it" for n in unknown]
    meta = _load(d / "meta.json", errors) if "meta.json" in names else None
    if meta is None and "meta.json" not in names:
        errors.append("meta.json: missing; it holds the map's title: {\"title\": \"<repo name>\"}")
    if meta is not None and not isinstance(meta, dict):
        errors.append("meta.json: must be an object")
        meta = None
    meta = meta or {}
    order = [n for n in SECTION_FILES if n in names] + sorted(n for n in names if OTHER_SECTION.match(n))
    sections, flows = [], []
    for n in order:
        section = _load(d / n, errors)
        if section is None:
            continue
        if not isinstance(section, dict):
            errors.append(f"{n}: must be one section object {{id, kind, title, blocks}}")
            continue
        records = section.pop("flows", None)
        if records is not None:
            if n != "flows.json" or not isinstance(records, list):
                errors.append(f"{n}: path records go in flows.json, as a list under \"flows\"")
            else:
                flows += records
        sections.append(section)
    if "overview.json" not in names:
        errors.append("overview.json: missing; the Overview is required")
    claims: list = []
    claim_files = [n for n in names if CLAIMS_FILE.match(n)]
    if not claim_files:
        errors.append("claims.json: missing; write the claims as a list (or several claims-<name>.json files)")
    for n in claim_files:
        data = _load(d / n, errors)
        if isinstance(data, dict) and isinstance(data.get("claims"), list):
            data = data["claims"]
        if data is not None and not isinstance(data, list):
            errors.append(f"{n}: must be a list of claim drafts (or {{\"claims\": [...]}})")
            continue
        claims += data or []
    if errors:
        raise ContractError("validation_failed", f"{len(errors)} problem(s) in the draft files; nothing was checked",
                            errors)
    document = {"title": meta.get("title"), "sections": sections, "flows": flows}
    if "coverage" in meta:
        document["coverage"] = meta["coverage"]
    data = {"target": "map", "mode": meta.get("mode", "replace"), "document": document, "claims": claims}
    for key in ("commit", "retire"):
        if key in meta:
            data[key] = meta[key]
    return data, names

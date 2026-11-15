"""Source previews for the page: the cited lines at their commit, a few lines around them, and the links.

Read from git at a commit (never the working tree), refused for secret-looking files or lines.
"""

from __future__ import annotations

from typing import Any

from .anchors import check_path
from .claims import commit_of, links_for
from .contract import ContractError
from .gitio import Repo
from .guard import check_secret
from .outline import line_hash
from .store import Store, all_claims

MAX_LINES = 400
MAX_CONTEXT = 20


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ContractError("bad_input", f"{name} must be an integer") from None


def preview(repo: Repo, store: Store, data: Any) -> dict:
    if not isinstance(data, dict):
        raise ContractError("bad_input", "expected a JSON object")
    claim = None
    saved_hash = None
    if data.get("claim"):
        found = [c for _, c in all_claims(store.load("map"), store.load("answers")) if c["id"] == data["claim"]]
        if not found:
            raise ContractError("not_found", f"no claim {data['claim']!r}")
        claim = found[0]
        index = _int(data.get("anchor", 0), "anchor")
        if not 0 <= index < len(claim["anchors"]):
            raise ContractError("not_found", f"{claim['id']} has no anchor {index}")
        a = claim["anchors"][index]
        path, start, end, commit = a["path"], a["start"], a["end"], commit_of(repo, a["commit"])
        saved_hash = a["hash"]
    else:
        path = data.get("path")
        if not isinstance(path, str):
            raise ContractError("bad_input", "give claim, or path with start and end")
        start, end = _int(data.get("start"), "start"), _int(data.get("end", data.get("start")), "end")
        commit = commit_of(repo, data.get("commit"))
    try:
        check_path(path)
    except ValueError as exc:
        raise ContractError("bad_input", str(exc)) from None
    why = check_secret(path)
    if why:
        raise ContractError("secret_refused", why)
    lines = repo.lines_at(commit, path)
    if lines is None:
        raise ContractError("not_found", f"{path} is not in {commit[:12]} (or is binary)")
    if not 1 <= start <= end <= len(lines):
        raise ContractError("bad_input", f"lines {start}-{end} are outside {path} ({len(lines)} lines)")
    if end - start + 1 > MAX_LINES:
        raise ContractError("bad_input", f"at most {MAX_LINES} lines per preview")
    context = max(0, min(_int(data.get("context", 3), "context"), MAX_CONTEXT))
    lo, hi = max(1, start - context), min(len(lines), end + context)
    shown = lines[lo - 1:hi]
    why = check_secret(path, shown, lo)
    if why:
        raise ContractError("secret_refused", why)
    anchor = {"path": path, "anchor": "", "start": start, "end": end, "commit": commit,
              "hash": line_hash(lines[start - 1:end])}
    out = {"path": path, "commit": commit, "start": start, "end": end,
           "lines": [{"n": lo + i, "text": text, "cited": start <= lo + i <= end} for i, text in enumerate(shown)],
           "links": links_for(repo, anchor)}
    if claim is not None:
        out["claim"] = claim["id"]
        out["hash_matches"] = anchor["hash"] == saved_hash
    return out

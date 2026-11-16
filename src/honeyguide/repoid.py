"""Repository identity: normalized remote URL + root commit, so any checkout of a repo finds its memory."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .gitio import Repo

_SCHEMES = ("git+ssh://", "ssh+git://", "ssh://", "https://", "http://", "git://")
_SCP = re.compile(r"^(?:[^/]*@)?([^@:/]+):(?!//)(.+)$")  # git@github.com:owner/repo(.git); userinfo to the last @
_CASE_INSENSITIVE_HOSTS = {"github.com"}


def normalize_remote(url: str) -> str | None:
    """``host/owner/repo`` for a hosted remote; None for a local path or something unrecognisable.

    Drops scheme, credentials, port, ``.git`` and trailing slashes; never returns a password or token.
    """
    url = re.split(r"[?#]", url.strip(), maxsplit=1)[0]  # a query or fragment can carry a token
    if not url:
        return None
    lowered = url.lower()
    rest = None
    for scheme in _SCHEMES:
        if lowered.startswith(scheme):
            rest = url[len(scheme):]
            break
    if rest is None:
        if url.startswith(("/", ".", "~", "file:")) or re.match(r"^[A-Za-z]:[\\/]", url):
            return None
        match = _SCP.match(url)
        if not match:
            return None
        host, path = match.group(1), match.group(2)
    else:
        authority, _, path = rest.partition("/")
        host = authority.rsplit("@", 1)[-1]  # drop user[:password]@
        host = host.split(":", 1)[0]          # drop :port
    host = host.lower()
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    if not host or not path:
        return None
    if host in _CASE_INSENSITIVE_HOSTS:
        path = path.lower()
    return f"{host}/{path}"


def github_slug(url: str) -> tuple[str, str] | None:
    """``(owner, repo)`` if ``url`` is a github.com remote in any form, keeping the remote's spelling."""
    normalized = normalize_remote(url)
    if not normalized or not normalized.startswith("github.com/"):
        return None
    parts = normalized.split("/")
    if len(parts) != 3:
        return None
    # Recover the original case for display: GitHub accepts any case, but the owner's spelling reads better.
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/*$", url.strip(), re.IGNORECASE)
    if match and match.group(1).lower() == parts[1] and match.group(2).lower() == parts[2]:
        return match.group(1), match.group(2)
    return parts[1], parts[2]


def safe_component(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text.replace("/", "__")).strip("._") or "repo"


@dataclass(frozen=True)
class RepoIdentity:
    id: str
    remote_name: str | None
    remote: str | None          # normalized, credential-free
    root_commit: str
    all_roots: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"id": self.id, "remote_name": self.remote_name, "remote": self.remote,
                "root_commit": self.root_commit, "all_roots": list(self.all_roots)}


def choose_remote(remotes: dict[str, str]) -> tuple[str, str] | None:
    """``origin`` if present, else the alphabetically first remote."""
    if not remotes:
        return None
    name = "origin" if "origin" in remotes else sorted(remotes)[0]
    return name, remotes[name]


def make_id(normalized_remote: str | None, root_commit: str) -> str:
    return f"{safe_component(normalized_remote or 'local')}__{root_commit[:12]}"


def identify(repo: Repo) -> RepoIdentity:
    chosen = choose_remote(repo.remotes())
    name = chosen[0] if chosen else None
    normalized = normalize_remote(chosen[1]) if chosen else None
    root = repo.first_parent_root()
    return RepoIdentity(make_id(normalized, root), name, normalized, root, tuple(repo.root_commits()))

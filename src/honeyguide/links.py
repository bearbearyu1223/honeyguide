"""Source links built from a resolved anchor: a GitHub permalink pinned to the commit, and editor links.

The GitHub link is offered only when the remote is github.com and the commit is on that remote. "On the
remote" is checked locally, without network: some remote-tracking branch of that remote contains the commit.
That reflects the last fetch, so a commit pushed by someone else since then reads as not pushed (the link is
hidden, the safe direction).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from .anchors import CodeAnchor, check_path
from .gitio import Repo
from .repoid import choose_remote, github_slug


def line_fragment(start: int, end: int) -> str:
    return f"#L{start}" if start == end else f"#L{start}-L{end}"


def github_permalink(remote_url: str, anchor: CodeAnchor) -> str | None:
    """The pinned URL for a GitHub remote, else None. Pure: doesn't check that the commit is pushed."""
    slug = github_slug(remote_url)
    if slug is None or len(anchor.commit) != 40:
        return None
    path = quote(check_path(anchor.path), safe="/")
    return (f"https://github.com/{slug[0]}/{slug[1]}/blob/{anchor.commit}/{path}"
            f"{line_fragment(anchor.start, anchor.end)}")


def commit_on_remote(repo: Repo, commit: str, remote: str) -> bool:
    out = repo.git("for-each-ref", "--format=%(refname)", "--contains", commit,
                   f"refs/remotes/{remote}/", check=False)
    return any(line.strip() for line in out.splitlines())


def github_link(repo: Repo, anchor: CodeAnchor) -> str | None:
    """The permalink, only if the remote is GitHub and the anchor's commit is on it."""
    chosen = choose_remote(repo.remotes())
    if chosen is None:
        return None
    name, url = chosen
    link = github_permalink(url, anchor)
    if link is None or not commit_on_remote(repo, anchor.commit, name):
        return None
    return link


def editor_links(checkout: Path, anchor: CodeAnchor) -> dict[str, str]:
    """VS Code and Cursor links to the anchor's first line in the local checkout (the working copy)."""
    target = quote(str((Path(checkout) / check_path(anchor.path)).resolve()), safe="/")
    return {scheme: f"{scheme}://file{target}:{anchor.start}:1" for scheme in ("vscode", "cursor")}

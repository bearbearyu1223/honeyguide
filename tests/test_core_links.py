"""Source links: GitHub permalinks only for a GitHub remote that has the commit; editor links."""

from __future__ import annotations

from test_core_fixtures import GitRepo

from honeyguide.anchors import CodeAnchor, resolve
from honeyguide.gitio import Repo
from honeyguide.links import commit_on_remote, editor_links, github_link, github_permalink

SHA = "0123456789abcdef0123456789abcdef01234567"


def anchor(start=5, end=9, path="src/pkg/mod.py"):
    return CodeAnchor(path, "def f(", start, end, SHA, "h" * 16)


def test_permalink_format_pinned_to_commit():
    url = github_permalink("git@github.com:Owner/repo.git", anchor())
    assert url == f"https://github.com/Owner/repo/blob/{SHA}/src/pkg/mod.py#L5-L9"
    assert github_permalink("https://github.com/o/r", anchor(7, 7)).endswith("#L7")
    spaced = github_permalink("https://github.com/o/r", anchor(path="docs/my file.py"))
    assert "/docs/my%20file.py#" in spaced


def test_no_permalink_for_other_hosts_or_short_sha():
    assert github_permalink("https://gitlab.com/o/r", anchor()) is None
    assert github_permalink("/srv/git/r.git", anchor()) is None
    short = CodeAnchor("a.py", "x", 1, 1, "abc123", "h")
    assert github_permalink("https://github.com/o/r", short) is None


def make_pushed_repo(tmp_path):
    """A clone of a local bare repo whose origin URL is then pointed at GitHub (no network is used)."""
    bare = tmp_path / "remote.git"
    seed = GitRepo(tmp_path / "seed")
    seed.write("mod.py", "def f():\n    return 1\n")
    pushed = seed.commit("pushed")
    seed.git("clone", "-q", "--bare", str(seed.root), str(bare))
    clone = GitRepo.__new__(GitRepo)
    clone.root = tmp_path / "clone"
    seed.git("clone", "-q", str(bare), str(clone.root))
    clone.git("remote", "set-url", "origin", "https://github.com/owner/repo.git")
    clone.write("mod.py", "def f():\n    return 2\n")
    local_only = clone.commit("not pushed")
    return Repo.open(clone.root), pushed, local_only


def test_link_only_when_commit_is_on_the_remote(tmp_path):
    repo, pushed, local_only = make_pushed_repo(tmp_path)
    assert commit_on_remote(repo, pushed, "origin")
    assert not commit_on_remote(repo, local_only, "origin")
    a = resolve(repo.lines_at(pushed, "mod.py"), "mod.py", "def f():", pushed, extent="block").anchor
    assert github_link(repo, a) == f"https://github.com/owner/repo/blob/{pushed}/mod.py#L1-L2"
    b = resolve(repo.lines_at(local_only, "mod.py"), "mod.py", "def f():", local_only).anchor
    assert github_link(repo, b) is None


def test_no_link_without_github_remote(tmp_path):
    g = GitRepo(tmp_path / "r")
    g.write("a.py", "x = 1\n")
    sha = g.commit()
    repo = Repo.open(g.root)
    a = resolve(repo.lines_at(sha, "a.py"), "a.py", "x = 1", sha).anchor
    assert github_link(repo, a) is None
    g.git("remote", "add", "origin", "https://gitlab.com/o/r.git")
    assert github_link(repo, a) is None


def test_editor_links(tmp_path):
    checkout = tmp_path / "my repo"
    links = editor_links(checkout, anchor(12, 20))
    target = str(checkout.resolve()).replace(" ", "%20")
    assert links == {"vscode": f"vscode://file{target}/src/pkg/mod.py:12:1",
                     "cursor": f"cursor://file{target}/src/pkg/mod.py:12:1"}

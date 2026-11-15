"""Repo identity: remote URL forms, no remote, several roots."""

from __future__ import annotations

import pytest
from test_core_fixtures import GitRepo

from honeyguide.gitio import Repo
from honeyguide.repoid import github_slug, identify, make_id, normalize_remote


@pytest.mark.parametrize("url", [
    "https://github.com/HuggingFace/smolagents",
    "https://github.com/huggingface/smolagents.git",
    "https://github.com/huggingface/smolagents/",
    "http://github.com/huggingface/smolagents",
    "git@github.com:huggingface/smolagents.git",
    "github.com:huggingface/smolagents",
    "ssh://git@github.com/huggingface/smolagents.git",
    "ssh://git@github.com:22/huggingface/smolagents",
    "git+ssh://git@GitHub.com/huggingface/smolagents.git",
    "https://user:ghp_secret123@github.com/huggingface/smolagents.git",
])
def test_github_forms_normalize_to_one(url):
    assert normalize_remote(url) == "github.com/huggingface/smolagents"


def test_other_hosts_keep_path_case_and_local_paths_are_not_remotes():
    assert normalize_remote("git@gitlab.example.org:Team/Proj.git") == "gitlab.example.org/Team/Proj"
    assert normalize_remote("https://gitlab.com/a/b/c.git") == "gitlab.com/a/b/c"
    for local in ["/srv/git/repo.git", "../repo", "./repo", "file:///srv/repo", "~/repo", "C:\\repo", ""]:
        assert normalize_remote(local) is None


def test_credentials_never_survive():
    assert "secret" not in make_id(normalize_remote("https://me:secret@github.com/o/r"), "f" * 40)


def test_github_slug_keeps_spelling_and_rejects_others():
    assert github_slug("git@github.com:HuggingFace/smolagents.git") == ("HuggingFace", "smolagents")
    assert github_slug("https://gitlab.com/o/r") is None
    assert github_slug("https://github.com/o") is None


def test_identity_no_remote(tmp_path):
    g = GitRepo(tmp_path / "r")
    root = g.commit("root")
    ident = identify(Repo.open(g.root))
    assert ident.id == f"local__{root[:12]}" and ident.remote is None and ident.root_commit == root


def test_identity_same_for_https_and_ssh_checkouts(tmp_path):
    g = GitRepo(tmp_path / "r")
    root = g.commit("root")
    g.git("remote", "add", "origin", "https://github.com/Owner/Repo.git")
    first = identify(Repo.open(g.root)).id
    g.git("remote", "set-url", "origin", "git@github.com:owner/repo")
    assert identify(Repo.open(g.root)).id == first == f"github.com__owner__repo__{root[:12]}"


def test_identity_prefers_origin_then_first_remote(tmp_path):
    g = GitRepo(tmp_path / "r")
    g.commit("root")
    g.git("remote", "add", "zeta", "https://github.com/z/r")
    g.git("remote", "add", "alpha", "https://github.com/a/r")
    assert identify(Repo.open(g.root)).remote == "github.com/a/r"
    g.git("remote", "add", "origin", "https://github.com/o/r")
    assert identify(Repo.open(g.root)).remote_name == "origin"


def test_identity_with_several_roots_follows_first_parent(tmp_path):
    g = GitRepo(tmp_path / "r")
    g.write("a.txt", "a\n")
    main_root = g.commit("main root")
    g.git("checkout", "-q", "--orphan", "other")
    g.git("rm", "-rq", "--cached", ".")
    (g.root / "a.txt").unlink()
    g.write("b.txt", "b\n")
    other_root = g.commit("other root")
    g.git("checkout", "-q", "main")
    g.git("merge", "-q", "--allow-unrelated-histories", "-m", "merge", "other")
    ident = identify(Repo.open(g.root))
    assert set(ident.all_roots) == {main_root, other_root}
    assert ident.root_commit == main_root

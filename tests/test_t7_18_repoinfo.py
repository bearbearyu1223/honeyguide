"""T7.18: ``honeyguide repo-info`` on a git fixture repo: the link, branch, dates, commit count, languages by share,
licence, contributors (names only, never emails), README line, and the GitHub counts only through a signed-in ``gh``
(mocked here by a script on a temporary path); ``map ingest`` stores the card in ``document.repo``."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from honeyguide import cli
from honeyguide.gitio import Repo
from honeyguide.mapdoc import check_document
from honeyguide.repoinfo import (check_repo_info, guess_license, https_link, language_shares, parse_shortlog,
                                 readme_summary, repo_info)

MIT = """MIT License

Copyright (c) 2025 Someone

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction ...

The above copyright notice and this permission notice shall be included in all copies or substantial portions.
"""


def git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, **(env or {})})


def commit(repo, msg, name, email, date):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, env={"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                                             "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
                                             "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})


@pytest.fixture()
def fixture_repo(tmp_path):
    r = tmp_path / "toy"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("# toy\n\n[![ci](x.svg)](y)\n\nA toy trainer that fits in one afternoon of reading.\n")
    (r / "LICENSE").write_text(MIT)
    (r / "train.py").write_text("\n".join(f"x{i} = {i}" for i in range(30)) + "\n")
    commit(r, "first", "Ada Lovelace", "ada@example.com", "2025-01-02T10:00:00+00:00")
    (r / "run.sh").write_text("echo 1\necho 2\n")
    (r / "web").mkdir()
    (r / "web" / "app.js").write_text("a\nb\nc\nd\ne\nf\ng\nh\n")
    (r / "node_modules").mkdir()
    (r / "node_modules" / "dep.js").write_text("x\n" * 500)          # vendored: not counted
    commit(r, "second", "Grace Hopper", "grace@example.com", "2025-02-03T10:00:00+00:00")
    (r / "train.py").write_text((r / "train.py").read_text() + "y = 1\n")
    commit(r, "third", "Ada", "ada@example.com", "2025-03-04T10:00:00+00:00")   # one email, two names: one person
    git(r, "remote", "add", "origin", "git@github.com:Example/Toy.git")
    return r


def fake_gh(tmp_path, signed_in=True, payload=None):
    gh = tmp_path / "gh"
    data = json.dumps(payload or {"stargazers_count": 1234, "forks_count": 56, "open_issues_count": 7,
                                  "topics": ["llm", "training"], "description": "A toy trainer"})
    log = tmp_path / "gh.log"
    gh.write_text("#!/bin/sh\n"
                  f"echo \"$@\" >> '{log}'\n"
                  f"if [ \"$1\" = auth ]; then exit {0 if signed_in else 1}; fi\n"
                  f"if [ \"$1\" = api ] && [ \"$2\" = repos/Example/Toy ]; then cat <<'EOF'\n{data}\nEOF\nexit 0; fi\n"
                  "exit 2\n")
    gh.chmod(0o755)
    return str(gh), log


NOW = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)


def test_git_facts(fixture_repo):
    info = repo_info(Repo.open(fixture_repo), gh=None, now=NOW)
    assert info["name"] == "Example/Toy" and info["url"] == "https://github.com/Example/Toy"
    assert info["default_branch"] == "main"
    assert info["commits"] == 3
    assert info["first_commit_date"].startswith("2025-01-02") and info["last_commit_date"].startswith("2025-03-04")
    assert info["commit"]["date"] == info["last_commit_date"]
    # languages: 31 Python, 8 JavaScript (node_modules left out), 2 Shell lines
    assert [(x["name"], x["lines"]) for x in info["languages"]] == [("Python", 31), ("JavaScript", 8), ("Shell", 2)]
    assert abs(sum(x["share"] for x in info["languages"]) - 1) < 0.005
    assert info["license"] == {"spdx": "MIT", "file": "LICENSE"}
    assert info["readme"] == {"path": "README.md", "title": "toy", "title_line": 1,
                              "description": "A toy trainer that fits in one afternoon of reading.", "description_line": 5}
    # contributors: names only, Ada's two names joined by her one email
    assert info["contributors"] == [{"name": "Ada Lovelace", "commits": 2}, {"name": "Grace Hopper", "commits": 1}]
    assert info["contributor_count"] == 2
    assert "@" not in json.dumps(info["contributors"]) and "example.com" not in json.dumps(info)
    assert info["github"] is None and info["github_note"].startswith("GitHub counts not fetched")
    assert check_repo_info(info) == []


def test_github_counts_only_through_a_signed_in_gh(fixture_repo, tmp_path):
    gh, log = fake_gh(tmp_path)
    info = repo_info(Repo.open(fixture_repo), gh=gh, now=NOW)
    assert info["github"] == {"stars": 1234, "forks": 56, "open_issues": 7, "topics": ["llm", "training"],
                              "description": "A toy trainer", "as_of": "2026-11-16"}
    assert "github_note" not in info
    assert "api repos/Example/Toy" in log.read_text()
    (tmp_path / "out").mkdir()
    out_gh, out_log = fake_gh(tmp_path / "out", signed_in=False)
    info = repo_info(Repo.open(fixture_repo), gh=out_gh, now=NOW)
    assert info["github"] is None and "not signed in" in info["github_note"]
    assert "api" not in out_log.read_text()                       # never asked the API
    info = repo_info(Repo.open(fixture_repo), gh=None, now=NOW)
    assert "not installed" in info["github_note"]


def test_a_remote_not_on_github_never_runs_gh(fixture_repo, tmp_path):
    gh, log = fake_gh(tmp_path)
    git(fixture_repo, "remote", "set-url", "origin", "https://user:secret@gitlab.com/team/toy.git")
    info = repo_info(Repo.open(fixture_repo), gh=gh, now=NOW)
    assert info["url"] == "https://gitlab.com/team/toy" and "secret" not in json.dumps(info)
    assert info["github"] is None and "not on GitHub" in info["github_note"]
    assert not log.exists()


def test_helpers():
    assert https_link("git@github.com:karpathy/nanochat.git") == "https://github.com/karpathy/nanochat"
    assert https_link("/some/local/path") is None
    assert guess_license("Apache License\nVersion 2.0, January 2004") == "Apache-2.0"
    assert guess_license("nothing here") is None
    shares = language_shares({"A": 50, "B": 20, "C": 10, "D": 8, "E": 7, "F": 3, "G": 2})
    assert [x["name"] for x in shares] == ["A", "B", "C", "D", "E", "Other"] and shares[-1]["lines"] == 5
    people, n = parse_shortlog("   10\tAda <a@x.org>\n    3\tAda L <a@x.org>\n    4\tBob <b@y.org>\n")
    assert people == [{"name": "Ada", "commits": 13}, {"name": "Bob", "commits": 4}] and n == 2
    assert readme_summary(["Title", "=====", "", "Short.", "A longer description line."]) == {
        "title": "Title", "title_line": 1, "description": "A longer description line.", "description_line": 5}
    assert check_repo_info({"name": "x", "contributors": [{"name": "a@b.c"}]}) == \
        ["document.repo.contributors: names only (no emails)"]
    assert check_repo_info({"name": "x", "github": {"stars": 1}}) == ["document.repo.github: needs its as_of date"]


def test_cli_prints_json(fixture_repo, capsys):
    assert cli.main(["repo-info", "--repo", str(fixture_repo), "--no-gh"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["name"] == "Example/Toy" and out["github"] is None


def test_a_document_with_a_bad_card_is_refused():
    doc = {"title": "t", "sections": [{"id": "o", "kind": "overview", "title": "Overview",
                                       "blocks": [{"id": "b", "type": "text", "spans": [{"text": "x"}]}]}],
           "repo": {"name": "t", "contributors": [{"name": "x", "email": "x@y"}]}}
    errors, _ = check_document(doc)
    assert errors == ["document.repo.contributors: names only (no emails)"]


def test_repo_info_save_refreshes_the_saved_card(tmp_path, monkeypatch):
    """``repo-info --save`` stores the card in the saved map and changes nothing else (``map ingest`` storing it is
    tested in test_t7_mapdoc_v2)."""
    from t7_page_fixture import build
    from honeyguide.store import Store
    monkeypatch.setenv("HONEYGUIDE_NO_GH", "1")
    info = build(tmp_path, "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    doc = store.load("map")["document"]
    monkeypatch.setenv("HONEYGUIDE_HOME", info["home"])
    # re-save through the CLI's --save path (what ingest does at map time)
    assert cli.main(["repo-info", "--repo", info["repo"], "--save"]) == 0
    doc2 = store.load("map")["document"]
    assert doc2["repo"]["commits"] >= 1 and doc2["repo"]["github"] is None
    assert "HONEYGUIDE_NO_GH" in doc2["repo"]["github_note"]
    assert {k: v for k, v in doc2.items() if k != "repo"} == {k: v for k, v in doc.items() if k != "repo"}

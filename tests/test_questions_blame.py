"""Cutoff tagging: git blame parsing and the before/after rule."""

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "questions"))
from keys import parse_blame, tag_lines  # noqa: E402
from repo import blame_file  # noqa: E402


def ts(day):
    return dt.datetime.fromisoformat(day + "T12:00:00+00:00").timestamp()


def test_tag_lines_majority_rule():
    times = {1: ts("2026-01-01"), 2: ts("2026-07-02"), 3: ts("2026-07-02"), 4: ts("2026-01-01")}
    cut = ts("2026-06-30")
    assert tag_lines(times, [1, 2, 3, 4], cut) == (2, 4, "after")       # half counts
    assert tag_lines(times, [1, 2, 4], cut) == (1, 3, "before")
    # blank lines are not counted
    assert tag_lines(times, [1, 2, 3, 4], cut, nonblank={2, 3}) == (2, 2, "after")
    assert tag_lines(times, [], cut) == (0, 0, "before")


def test_parse_blame_porcelain():
    sha_a, sha_b = "a" * 40, "b" * 40
    text = "\n".join([
        f"{sha_a} 1 1 2", "author X", "committer-time 100", "filename f.py", "\tline one",
        f"{sha_a} 2 2", "committer-time 100", "filename f.py", "\tline two",
        f"{sha_b} 5 3 1", "committer-time 200", "filename f.py", "\tcommitter-time 999",
    ])
    assert parse_blame(text) == {1: 100, 2: 100, 3: 200}


# --------------------------------------------------------------------------
# A real repo: main gets an old file, a branch adds a function before the
# cutoff, and main merges it after the cutoff.

def git(cwd, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date + "T12:00:00+00:00"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def fixture_repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    f = r / "m.py"
    f.write_text("def old():\n    return 1\n")
    git(r, "add", "m.py")
    git(r, "commit", "-q", "-m", "old", date="2026-01-10")
    git(r, "checkout", "-q", "-b", "feature")
    f.write_text("def old():\n    return 1\n\n\ndef new():\n    x = 2\n    return x\n")
    git(r, "commit", "-q", "-am", "new on a branch", date="2026-05-01")
    git(r, "checkout", "-q", "main")
    (r / "other.py").write_text("y = 1\n")
    git(r, "add", "other.py")
    git(r, "commit", "-q", "-m", "unrelated", date="2026-07-01")
    git(r, "merge", "-q", "--no-ff", "-m", "merge", "feature", date="2026-07-02")
    return r, git(r, "rev-parse", "HEAD")


def test_blame_first_parent_dates_merged_lines_by_the_merge(fixture_repo):
    r, head = fixture_repo
    cut = dt.datetime.fromisoformat("2026-06-30T23:59:59+00:00").timestamp()
    fp = blame_file(r, head, "m.py", first_parent=True)
    auth = blame_file(r, head, "m.py", first_parent=False)
    new_lines = [5, 6, 7]
    assert tag_lines(fp, new_lines, cut)[2] == "after"       # landed on main 07-02
    assert tag_lines(auth, new_lines, cut)[2] == "before"    # written 05-01
    assert tag_lines(fp, [1, 2], cut)[2] == "before"         # untouched since 01-10

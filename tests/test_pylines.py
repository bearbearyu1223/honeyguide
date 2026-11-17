"""eval/common/pylines.py: Python lines at a commit, the one method the refresh and June captures share."""

import importlib.util
import os
import subprocess
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "eval" / "common" / "pylines.py"
_spec = importlib.util.spec_from_file_location("eval_common_pylines", SRC)
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)


def test_parse_ls_tree_keeps_regular_py_files():
    text = "\0".join([
        "100644 blob aaa\ta.py",
        "100755 blob bbb\tbin/run.py",
        "120000 blob ccc\tlink.py",          # a symlink: its blob is the target path, not code
        "160000 commit ddd\tsub.py",         # a submodule
        "100644 blob eee\tREADME.md",
        "100644 blob fff\ttests/test_a.py",
    ]) + "\0"
    assert pl.parse_ls_tree(text) == [("aaa", "a.py"), ("bbb", "bin/run.py"), ("fff", "tests/test_a.py")]
    assert pl.parse_ls_tree(text, keep=lambda p: not p.startswith("tests/")) == [("aaa", "a.py"),
                                                                                  ("bbb", "bin/run.py")]


def test_count_lines_is_wc_l():
    assert pl.count_lines(b"") == 0
    assert pl.count_lines(b"x = 1\n") == 1
    assert pl.count_lines(b"x = 1\ny = 2") == 1        # no newline at the end: wc -l does not count it
    assert pl.count_lines(b"\n\n") == 2


def test_parse_batch_splits_objects():
    data = b"s1 blob 6\nx = 1\n\ns2 blob 0\n\ns3 blob 3\na\nb\n"
    assert pl.parse_batch(data) == [b"x = 1\n", b"", b"a\nb"]


def test_py_lines_at_a_commit_ignores_the_working_tree(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def g(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()
    g("init", "-q")
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("def f():\n    pass")     # no final newline
    (tmp_path / "notes.txt").write_text("1\n2\n3\n")
    g("add", ".")
    g("commit", "-qm", "one")
    one = g("rev-parse", "HEAD")
    (tmp_path / "a.py").write_text("x = 1\n" * 100)                    # uncommitted: not counted
    assert pl.py_lines(tmp_path, one) == (2, 3)
    assert pl.py_lines(tmp_path, one, keep=lambda p: p.startswith("pkg/")) == (1, 1)
    assert pl.py_lines(tmp_path, "0" * 40) is None
    assert pl.py_lines(tmp_path / "missing", one) is None
    assert pl.py_lines(tmp_path, None) is None

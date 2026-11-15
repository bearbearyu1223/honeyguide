"""Code anchors: resolution (found, ambiguous, missing), extents, and relocation in a newer file."""

from __future__ import annotations

import pytest

from honeyguide.anchors import CodeAnchor, block_end, check_path, find_text, relocate, resolve
from honeyguide.gitio import split_lines
from honeyguide.outline import enclosing_unit, line_hash, python_units

SHA = "a" * 40
SHA2 = "b" * 40

SOURCE = """\
import os


def load(path):
    with open(path) as f:
        return f.read()


class Agent:
    name = "agent"

    def run(self, task):
        steps = []
        return self.step(task)

    def step(self, task):
        return task


def save(path,
         data):
    return None
"""
LINES = split_lines(SOURCE)


def test_found_single_line_records_lines_hash_and_symbol():
    r = resolve(LINES, "pkg/agent.py", "return self.step(task)", SHA)
    assert r.status == "found"
    a = r.anchor
    assert (a.start, a.end, a.commit, a.symbol) == (14, 14, SHA, "Agent.run")
    assert a.hash == line_hash(["        return self.step(task)"])


def test_ambiguous_is_explicit_with_candidates():
    r = resolve(LINES, "a.py", "return", SHA)
    assert r.status == "ambiguous"
    assert r.candidates == (6, 14, 17, 22)
    assert r.anchor is None


def test_multi_line_anchor_disambiguates():
    r = resolve(LINES, "a.py", "def step(self, task):\n    return task", SHA)
    assert r.status == "found" and (r.anchor.start, r.anchor.end) == (16, 17)


def test_not_found_and_no_file():
    assert resolve(LINES, "a.py", "def missing(", SHA).status == "not_found"
    assert resolve(None, "a.py", "def load(", SHA).status == "no_file"


def test_block_extent_covers_function_and_multiline_signature():
    r = resolve(LINES, "a.py", "def run(self, task):", SHA, extent="block")
    assert (r.anchor.start, r.anchor.end) == (12, 14)
    assert block_end(LINES, 20) == 22  # def save(path,\n data):\n return None


def test_end_anchor():
    r = resolve(LINES, "a.py", "def load(path):", SHA, end_anchor="return f.read()")
    assert (r.anchor.start, r.anchor.end) == (4, 6)
    assert resolve(LINES, "a.py", "def run(", SHA, end_anchor="def load(").status == "not_found"


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x.py", "a/../b.py", "./a.py", "a\\b.py"])
def test_paths_must_be_repo_relative(bad):
    with pytest.raises(ValueError):
        check_path(bad)


def test_split_lines_numbers_like_github():
    assert split_lines("a\fb\nc\r\nd") == ["a\fb", "c", "d"]
    assert split_lines("x\n") == ["x"] and split_lines("") == []


def test_outline_units_and_class_hash_ignores_method_edits():
    units = {u.qualname: u for u in python_units(LINES)}
    assert set(units) == {"load", "Agent", "Agent.run", "Agent.step", "save"}
    assert (units["Agent"].start, units["Agent"].end) == (9, 17)
    edited = python_units(split_lines(SOURCE.replace("return task", "return task * 2")))
    after = {u.qualname: u for u in edited}
    assert after["Agent"].hash == units["Agent"].hash
    assert after["Agent.step"].hash != units["Agent.step"].hash
    assert enclosing_unit(python_units(LINES), 13, 14).qualname == "Agent.run"
    assert python_units(["def broken(:"]) == []


def anchor(text: str, extent: str = "lines") -> CodeAnchor:
    return resolve(LINES, "a.py", text, SHA, extent=extent).anchor


def test_relocate_unchanged_and_moved():
    a = anchor("def run(self, task):", "block")
    assert relocate(a, LINES, "a.py").state == "unchanged"
    shifted = ["# header", "# more"] + LINES
    r = relocate(a, shifted, "a.py")
    assert (r.state, r.start, r.end, r.symbol) == ("moved", 14, 16, "Agent.run")
    renamed = relocate(a, LINES, "b.py")
    assert (renamed.state, renamed.start) == ("moved", 12)


def test_relocate_stale_when_cited_lines_change():
    a = anchor("def load(path):", "block")
    new = split_lines(SOURCE.replace("return f.read()", "return f.read().strip()"))
    r = relocate(a, new, "a.py")
    assert r.state == "stale" and (r.start, r.end) == (4, 6) and r.symbol == "load"


def test_relocate_stale_when_symbol_remains_but_anchor_text_is_gone():
    a = anchor("steps = []")
    new = split_lines(SOURCE.replace("steps = []", "steps = list()"))
    r = relocate(a, new, "a.py")
    assert r.state == "stale" and r.symbol == "Agent.run" and (r.start, r.end) == (12, 14)


def test_relocate_retired_when_code_is_gone():
    a = anchor("def save(path,", "block")
    new = split_lines(SOURCE.split("def save")[0])
    r = relocate(a, new, "a.py")
    assert r.state == "retired" and "save" in r.reason
    assert relocate(a, None, "a.py").state == "retired"


def test_relocate_duplicate_lines_are_ambiguous_not_guessed():
    a = anchor("def step(self, task):", "block")
    dup = LINES[:15] + ["    # moved"] + LINES[15:] + ["", "class Other:", "    def step(self, task):",
                                                       "        return task"]
    # The symbol (Agent.step) narrows two identical spans to one: moved.
    r = relocate(a, dup, "a.py")
    assert r.state == "moved" and r.symbol == "Agent.step" and r.start == 17
    # Without a symbol to narrow it, two identical spans elsewhere: stale, no location.
    bare = CodeAnchor(a.path, a.anchor, a.start, a.end, SHA2, a.hash, None)
    r = relocate(bare, dup, "a.py")
    assert r.state == "stale" and r.start is None and "ambiguous" in r.reason


def test_find_text_window():
    assert find_text(LINES, "return", lo=10, hi=15) == [14]

"""Pure views of a kept path: tree, folding, depth limit, rendering, diffing,
and the capture's anchor and coverage helpers."""

import importlib.util
import sys
from pathlib import Path

import pytest

TRACE = Path(__file__).resolve().parents[1] / "eval" / "trace"
sys.path.insert(0, str(TRACE))
# By path under its own name: eval/runs and eval/refresh have a capture.py too, and a bare
# `import capture` gets whichever one another test module put in sys.modules first.
_spec = importlib.util.spec_from_file_location("eval_trace_capture", TRACE / "capture.py")
_cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cap)
coverage, resolve_anchor = _cap.coverage, _cap.resolve_anchor
from tracer import (  # noqa: E402
    build_tree, collapse, first_difference, fold, path_key, render_rows,
)


def ev(qual, depth, kind="call", thread="main", line=None, file="pkg/m.py",
       caller=None, call_line=None):
    return {"phase": "p", "thread": thread, "kind": kind, "qual": qual,
            "file": file, "line": line if line is not None else len(qual),
            "depth": depth, "caller": caller, "call_line": call_line}


def names(nodes):
    return [(n["e"]["qual"], names(n["children"])) for n in nodes]


def test_build_tree_nests_by_depth_and_rebases():
    events = [ev("a", 3), ev("b", 4), ev("c", 5), ev("d", 4), ev("e", 3)]
    assert names(build_tree(events)) == [
        ("a", [("b", [("c", [])]), ("d", [])]), ("e", [])]


def test_build_tree_depth_jump_attaches_to_nearest_open_node():
    # a filtered-out frame between two kept ones is not possible with kept-
    # only depths, but a jump must still not lose the event
    assert names(build_tree([ev("a", 0), ev("b", 2)])) == [("a", [("b", [])])]


def test_build_tree_empty():
    assert build_tree([]) == []


def test_fold_identical_subtrees():
    events = [ev("blk", 0), ev("lin", 1), ev("blk", 0), ev("lin", 1),
              ev("blk", 0), ev("lin", 1), ev("lin", 1)]
    folded = fold(build_tree(events))
    assert [(n["e"]["qual"], k) for n, k, _ in folded] == [("blk", 2), ("blk", 1)]
    # the third block differs one level down, so it is not folded
    assert [(n["e"]["qual"], k) for n, k, _ in folded[1][2]] == [("lin", 2)]


def test_fold_keeps_call_and_resume_apart():
    events = [ev("g", 0), ev("g", 0, kind="resume")]
    assert [k for _, k, _ in fold(build_tree(events))] == [1, 1]


def test_fold_keeps_threads_apart():
    events = [ev("f", 0), ev("f", 0, thread="worker-1")]
    assert [k for _, k, _ in fold(build_tree(events))] == [1, 1]


def test_collapse_depth_limit_counts_hidden():
    events = [ev("a", 0), ev("b", 1), ev("c", 2), ev("d", 3), ev("e", 2)]
    rows = collapse(events, max_depth=1)
    assert [(d, lab, hid) for d, lab, _, _, hid in rows] == [
        (0, "a", 0), (1, "b", 3)]


def test_collapse_labels_resume_and_thread():
    rows = collapse([ev("g", 0, kind="resume"), ev("w", 1, thread="worker-1")], 5)
    assert [r[1] for r in rows] == ["(resume) g", "[worker-1] w"]


def test_render_rows_width_and_overflow():
    rows = [
        (0, "short", "m.py:1", 1, 0),
        (2, "x" * 50, "pkg/long_file_name.py:1234", 3, 0),
        (8, "y" * 70, "m.py:9", 1, 5),
    ]
    lines = render_rows(rows, width=74, indent=2)
    assert all(len(ln) <= 74 for ln in lines)
    assert lines[0].startswith("short") and lines[0].endswith("m.py:1")
    # name and anchor do not fit: anchor and tag go right-aligned below
    assert lines[1] == "    " + "x" * 50
    assert lines[2].endswith("x3  pkg/long_file_name.py:1234")
    # indented name alone is too wide: depth marker replaces the indent
    assert lines[3] == "8> " + "y" * 70
    assert lines[4].endswith("(+5 deeper)  m.py:9")


@pytest.mark.parametrize("a,b,expected", [
    ([1, 2, 3], [1, 2, 3], None),
    ([1, 2, 3], [1, 9, 3], 1),
    ([1, 2], [1, 2, 3], 2),
    ([], [], None),
])
def test_first_difference(a, b, expected):
    assert first_difference(a, b) == expected


def test_path_key_includes_caller_line():
    a = [ev("f", 0, caller="g", call_line=3)]
    b = [ev("f", 0, caller="g", call_line=4)]
    assert first_difference(path_key(a), path_key(b)) == 0


def test_resolve_anchor():
    text = "a\nneedle one\nb\nneedle two\n"
    assert resolve_anchor(text, "needle") == (2, 2)
    assert resolve_anchor(text, "two") == (4, 1)
    with pytest.raises(ValueError):
        resolve_anchor(text, "absent")


def test_coverage_counts_defs_and_distinct_calls():
    src = "def f():\n    pass\n\nclass C:\n    def m(self):\n        pass\n"
    events = [ev("f", 0, line=1, file="a.py"), ev("f", 0, line=1, file="a.py"),
              ev("f", 0, kind="resume", line=5, file="a.py")]
    assert coverage(events, {"a.py": src}) == [("a.py", 2, 1)]

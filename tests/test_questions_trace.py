"""Trace-derived keys: callers seen at runtime and the flow pre-filter."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "questions"))
from keys import (  # noqa: E402
    FlowRules, Func, entry_subtree, flow_hops, trace_callers,
)


def ev(qual, depth, kind="call", file="p/a.py", thread="main", caller=None,
       call_line=None, phase="ph"):
    return {"phase": phase, "thread": thread, "kind": kind, "qual": qual,
            "file": file, "line": 1, "depth": depth, "caller": caller,
            "call_line": call_line}


def fn(qual, file="p/a.py", decorators=(), trivial=False):
    name = qual.split(".")[-1]
    cls = qual.rsplit(".", 1)[0] if "." in qual and "<locals>" not in qual else None
    return Func(file=file, qual=qual, name=name, cls=cls, start=1, def_line=1, end=9,
                decorators=tuple(decorators), trivial=trivial, body_lines=8)


# --------------------------------------------------------------------------
# Callers from the trace

def test_trace_callers_file_from_open_frame():
    events = [
        ev("A.run", 0, file="p/a.py"),
        ev("helper", 1, file="p/b.py", caller="A.run", call_line=12),
        ev("helper", 1, file="p/b.py", caller="A.run", call_line=14),
        ev("B.go", 0, file="p/c.py"),
        ev("helper", 1, file="p/b.py", caller="B.go", call_line=3),
    ]
    got = trace_callers(events, "p/b.py", "helper")
    assert got == {("p/a.py", "A.run"): [12, 14], ("p/c.py", "B.go"): [3]}


def test_trace_callers_ignores_resumes_and_finds_worker_caller():
    events = [
        ev("gen", 0, file="p/a.py"),
        ev("gen", 0, kind="resume", file="p/a.py"),
        ev("wrapper", 1, file="p/a.py", caller="gen", call_line=5),
        ev("target", 2, file="p/b.py", thread="worker-1", caller="wrapper"),
    ]
    assert trace_callers(events, "p/a.py", "gen") == {}
    assert trace_callers(events, "p/b.py", "target") == {("p/a.py", "wrapper"): []}


# --------------------------------------------------------------------------
# Flow pre-filter

FUNCS = {f.key: f for f in [
    fn("run"), fn("Logger.log"), fn("Logger.fmt"), fn("Thing.prop", decorators=("property",)),
    fn("step"), fn("inner"), fn("Msg.__post_init__"), fn("Msg.__str__"),
    fn("get_x", trivial=True), fn("model"), fn("model_inner"), fn("work"),
    fn("cached", decorators=("lru_cache",)),
]}
RULES = FlowRules(drop_classes=("Logger",))


def quals(hops):
    return [h.qual for h in hops]


def test_drop_rules_splice_or_cut():
    events = [
        ev("run", 0),
        ev("Logger.log", 1), ev("Logger.fmt", 2), ev("work", 2),  # logging: whole subtree
        ev("Thing.prop", 1), ev("step", 2),                         # property: spliced
        ev("Msg.__post_init__", 1), ev("Msg.__str__", 1),
        ev("get_x", 1), ev("inner", 2),                             # trivial: spliced
        ev("cached", 1),
    ]
    hops, dropped, raw = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES)
    assert quals(hops) == ["run", "step", "inner", "cached"]
    assert hops[1].caller == "run"            # its property parent was spliced out
    assert hops[3].cached
    assert raw == 11
    assert dropped == {"dataclass": 1, "dunder": 1, "logging": 1, "property": 1,
                       "trivial": 1, "under logging": 2}


def test_fold_and_merge_repeats():
    events = [
        ev("run", 0),
        ev("model", 1), ev("model_inner", 2), ev("model_inner", 2),
        ev("step", 1),
        ev("model", 1), ev("model_inner", 2),
        ev("step", 1),
    ]
    hops, dropped, _ = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES, fold=["model"])
    assert quals(hops) == ["run", "model", "step"]
    assert [h.calls for h in hops] == [1, 2, 2]
    assert hops[1].folded
    assert dropped == {"repeat": 2, "under fold": 3}


def test_generator_entry_resumes_are_followed():
    # run is a generator consumed by an outer frame: the consumer's own
    # resume (depth 0) comes first, then run's (depth 1)
    events = [
        ev("outer", 0),
        ev("run", 1), ev("step", 2),
        ev("outer", 0, kind="resume"), ev("run", 1, kind="resume"), ev("work", 2),
        ev("outer", 0, kind="resume"), ev("other", 1),
    ]
    sub = entry_subtree(events, "ph", "run")
    assert [e["qual"] for e in sub] == ["run", "step", "run", "work"]
    hops, dropped, _ = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES)
    assert quals(hops) == ["run", "step", "work"]
    assert hops[2].caller == "run"
    assert dropped == {"resume": 1}


def test_resumed_folded_generator_stays_folded():
    events = [
        ev("run", 0),
        ev("model", 1), ev("model_inner", 2),
        ev("model", 1, kind="resume"), ev("model_inner", 2),   # still inside the fold
        ev("step", 1),
    ]
    hops, dropped, _ = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES, fold=["model"])
    assert quals(hops) == ["run", "model", "step"]
    assert dropped == {"resume": 1, "under fold": 2}


def test_worker_thread_under_fold_is_dropped():
    events = [
        ev("run", 0),
        ev("model", 1),
        ev("work", 2, thread="worker-1"),       # started by model, main waits
        ev("step", 1),
        ev("inner", 2, thread="worker-2"),      # started by step: kept
    ]
    hops, _, _ = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES, fold=["model"])
    assert quals(hops) == ["run", "model", "step", "inner"]
    assert hops[3].thread == "worker-2" and hops[3].caller == "step"


def test_several_entries_and_missing_entry():
    events = [ev("run", 0), ev("step", 1), ev("work", 0), ev("inner", 1)]
    hops, _, raw = flow_hops(events, "ph", [("run", 0), ("work", 0)], FUNCS, RULES)
    assert quals(hops) == ["run", "step", "work", "inner"] and raw == 4
    with pytest.raises(ValueError):
        flow_hops(events, "ph", [("run", 1)], FUNCS, RULES)


def test_worker_started_after_a_dropped_subtree_returned_is_kept():
    # run's logging call returns, then run starts a worker (no repo call on
    # the main thread in between, so the logging cut is still set): the
    # worker's depth (1) is not below the cut (1), so it is kept
    events = [
        ev("run", 0),
        ev("Logger.log", 1), ev("Logger.fmt", 2),
        ev("work", 1, thread="worker-1"), ev("inner", 2, thread="worker-1"),
        ev("step", 1),
    ]
    hops, dropped, _ = flow_hops(events, "ph", [("run", 0)], FUNCS, RULES)
    assert quals(hops) == ["run", "work", "inner", "step"]
    assert hops[1].thread == "worker-1" and hops[1].caller == "run"
    assert dropped == {"logging": 1, "under logging": 1}

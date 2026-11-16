"""Review round 1 (T8): flow_hops attributes a worker's top hop to a stale main frame."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "questions"))
from keys import FlowRules, flow_hops  # noqa: E402


def ev(thread, qual, depth, caller, kind="call"):
    return {"phase": "p", "thread": thread, "kind": kind, "qual": qual, "file": "m.py",
            "line": 1, "depth": depth, "caller": caller, "call_line": None}


def test_worker_top_hop_caller_is_the_tracer_recorded_caller():
    """main: entry -> A -> B (B returns) ; A then starts a worker running W.
    The tracer records W's caller as A (main's kept stack when W starts).
    flow_hops ignores e['caller'] and takes main's kept_stack top, which still
    holds B because nothing on main has popped it yet."""
    events = [
        ev("main", "entry", 0, None),
        ev("main", "A", 1, "entry"),
        ev("main", "B", 2, "A"),
        ev("worker-1", "W", 2, "A"),
    ]
    hops, _, _ = flow_hops(events, "p", [("entry", 0)], {}, FlowRules())
    w = [h for h in hops if h.qual == "W"][0]
    assert w.caller == "A"


def test_workers_of_one_wave_share_a_wave_id():
    """Two pool threads that ran with no main-thread event between them were
    one wave (concurrent in the real code): same wave id, and the scorer
    leaves their order open. A worker after main moved on is a new block."""
    events = [
        ev("main", "entry", 0, None),
        ev("main", "run", 1, "entry"),
        ev("worker-1", "a", 2, "run"),
        ev("worker-1", "a2", 3, "a"),
        ev("worker-2", "b", 2, "run"),
        ev("main", "merge", 2, "run"),
        ev("worker-3", "c", 2, "run"),
    ]
    hops, _, _ = flow_hops(events, "p", [("entry", 0)], {}, FlowRules())
    wave = {h.qual: h.wave for h in hops}
    assert wave == {"entry": None, "run": None, "a": "wave-1", "a2": "wave-1",
                    "b": "wave-1", "merge": None, "c": None}

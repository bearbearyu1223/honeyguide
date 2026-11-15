"""The live tracer on a small fixture package: kept vs dropped frames, depth
in kept frames, generator resumes, and a worker thread."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "trace"))
from tracer import FilterRules, Tracer  # noqa: E402

FIXTURE = '''\
import json
from concurrent.futures import ThreadPoolExecutor

from fixturepkg.tests import helper_test


def leaf(x):
    return x + 1


def middle(x):
    # json.dumps is library code, and the lambda a synthetic repo frame,
    # between two repo frames
    json.dumps({1}, default=lambda o: leaf(0))
    return leaf(x)


def gen(n):
    for i in range(n):
        yield leaf(i)


class Box:
    def __init__(self):
        self.v = middle(1)

    def run(self):
        vals = [leaf(i) for i in range(2)]   # comprehension frame on 3.10/3.11
        total = sum(gen(2))
        helper_test()
        with ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(leaf, 5).result()
        return vals, total
'''


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    root = tmp_path / "fixturepkg"
    (root / "tests").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "core.py").write_text(FIXTURE)
    (root / "tests" / "__init__.py").write_text(
        "def helper_test():\n    return 0\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("fixturepkg")]:
        del sys.modules[m]
    core = importlib.import_module("fixturepkg.core")
    tracer = Tracer(FilterRules(roots=(str(root),)), str(tmp_path))
    return core, tracer


def rows(tracer):
    return [(e["thread"], e["kind"], e["qual"], e["depth"], e["caller"],
             e["call_line"]) for e in tracer.events]


def test_kept_path(pkg):
    core, tracer = pkg
    tracer.run_phase("init", lambda: core.Box())
    box = core.Box()  # built untraced
    tracer.run_phase("run", box.run)

    init = [r for r, e in zip(rows(tracer), tracer.events, strict=True) if e["phase"] == "init"]
    assert init == [
        ("main", "call", "Box.__init__", 0, None, None),
        ("main", "call", "middle", 1, "Box.__init__", 25),
        ("main", "call", "leaf", 2, "middle", 14),   # via json and the lambda
        ("main", "call", "leaf", 2, "middle", 15),
    ]
    assert tracer.counts["init"]["dropped_synthetic"] == 1
    run = [r for r, e in zip(rows(tracer), tracer.events, strict=True) if e["phase"] == "run"]
    assert run == [
        ("main", "call", "Box.run", 0, None, None),
        # list comprehension frame dropped; leaf's caller is Box.run
        ("main", "call", "leaf", 1, "Box.run", 28),
        ("main", "call", "leaf", 1, "Box.run", 28),
        # first entry into the generator is a call, re-entries are resumes
        ("main", "call", "gen", 1, "Box.run", 29),
        ("main", "call", "leaf", 2, "gen", 20),
        ("main", "resume", "gen", 1, "Box.run", 29),
        ("main", "call", "leaf", 2, "gen", 20),
        ("main", "resume", "gen", 1, "Box.run", 29),
        # tests/ helper dropped; worker thread nested under Box.run with no
        # call line (which line the main thread is on is a race)
        ("worker-1", "call", "leaf", 1, "Box.run", None),
    ]
    c = tracer.counts["run"]
    assert c["kept_calls"] == 7 and c["kept_resumes"] == 2
    assert c["raw_calls"] > c["kept_calls"] + c["kept_resumes"]
    if sys.version_info >= (3, 11):
        assert c["qualname_checked"] == 9 and c["qualname_mismatches"] == 0
    else:
        assert c["qualname_checked"] == 0


def test_events_carry_repo_relative_file_and_def_line(pkg):
    core, tracer = pkg
    tracer.run_phase("p", lambda: core.leaf(1))
    (e,) = tracer.events
    assert e["file"] == "fixturepkg/core.py" and e["line"] == 7


def test_profile_removed_after_phase(pkg):
    core, tracer = pkg
    tracer.run_phase("p", lambda: core.leaf(1))
    assert sys.getprofile() is None
    core.leaf(2)
    assert len(tracer.events) == 1


def test_phase_exception_still_uninstalls(pkg):
    core, tracer = pkg

    def boom():
        core.leaf(1)
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        tracer.run_phase("p", boom)
    assert sys.getprofile() is None
    assert [e["qual"] for e in tracer.events] == ["leaf"]

"""Tracer thread attribution and generator resumes."""

import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "eval" / "trace"
sys.path.insert(0, str(TRACE))
from tracer import FilterRules, Tracer  # noqa: E402

POOL_SRC = textwrap.dedent('''
    from concurrent.futures import ThreadPoolExecutor

    def work(x):
        return x

    def submit_a(pool):
        return pool.submit(work, 1).result()

    def submit_b(pool):
        return pool.submit(work, 2).result()

    def pooled():
        with ThreadPoolExecutor(max_workers=1) as pool:
            submit_a(pool)
            submit_b(pool)
''')


def _pkg(tmp_path, name, src):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(src)
    sys.path.insert(0, str(tmp_path))
    try:
        return importlib.import_module(name + ".mod"), pkg
    finally:
        sys.path.remove(str(tmp_path))


def test_reused_pool_thread_gets_its_own_caller(tmp_path):
    """A pool thread reused for a second task keeps the caller cached from its
    first task: work() submitted by submit_b is recorded as called by submit_a."""
    mod, pkg = _pkg(tmp_path, "r1pool", POOL_SRC)
    t = Tracer(FilterRules(roots=(str(pkg),)), str(tmp_path))
    t.run_phase("p", mod.pooled)
    work = [e for e in t.events if e["qual"] == "work"]
    assert [e["caller"] for e in work] == ["submit_a", "submit_b"]


PY310 = Path.home() / "Documents/GitHub/honeyguide-targets/nanochat/.venv/bin/python"
GEN_SRC = textwrap.dedent('''
    def inner():
        yield 1
        yield 2

    def outer():
        yield from inner()

    def consume():
        return list(outer())
''')


@pytest.mark.skipif(not PY310.exists(), reason="nanochat's Python 3.10 venv not present")
def test_yield_from_resumes_are_resumes_on_310(tmp_path):
    """nanochat's trace runs on 3.10. There a generator suspended in
    `yield from` stopped on YIELD_FROM, not YIELD_VALUE, so each re-entry of
    outer() is recorded as a new call (3.12 gets it right)."""
    pkg = tmp_path / "r1gen"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(GEN_SRC)
    script = textwrap.dedent(f'''
        import sys, json
        sys.path.insert(0, {str(TRACE)!r}); sys.path.insert(0, {str(tmp_path)!r})
        from tracer import Tracer, FilterRules
        import r1gen.mod as m
        t = Tracer(FilterRules(roots=({str(pkg)!r},)), {str(tmp_path)!r})
        t.run_phase("p", m.consume)
        print(json.dumps([(e["kind"], e["qual"]) for e in t.events]))
    ''')
    out = subprocess.run([str(PY310), "-c", script], capture_output=True, text=True,
                         check=True, env={k: v for k, v in os.environ.items()
                                          if k not in ("PYTHONPATH", "VIRTUAL_ENV")})
    import json
    events = [tuple(e) for e in json.loads(out.stdout)]
    calls_of_outer = [e for e in events if e == ("call", "outer")]
    assert len(calls_of_outer) == 1, events


def test_stopped_on_yield_rule():
    """Pure check of the suspension rule, version-independent: YIELD_VALUE
    at f_lasti, or (3.10) the instruction before YIELD_FROM; f_lasti on
    YIELD_FROM itself means the delegate raised, so the frame finished."""
    from tracer import YIELD_VALUE, stopped_on_yield
    yf = 200                                     # a stand-in opcode number
    code = bytes([1, 0, YIELD_VALUE, 0, 100, 0, yf, 0, 83, 0])
    assert stopped_on_yield(code, 2, yf)
    assert stopped_on_yield(code, 4, yf)         # suspended in yield from (3.10)
    assert not stopped_on_yield(code, 6, yf)     # raised out of YIELD_FROM
    assert not stopped_on_yield(code, 8, yf)     # returned
    assert not stopped_on_yield(code, 4, None)   # 3.11+: no YIELD_FROM
    assert not stopped_on_yield(code, -1, yf)


def test_trace_json_has_no_platform_or_wall_times():
    """The JSON the question sets checksum drops what an OS update
    or a slower machine changes; the .txt capture keeps them."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_trace_capture", TRACE / "capture.py")   # not bare 'capture'
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    stable_json = cap.stable_json
    run = {"python": "3.12", "platform": "macOS-x", "setup_seconds": 0.1,
           "phases": [{"name": "p", "description": "d", "seconds": 1.5}], "events": []}
    assert stable_json(run) == {"python": "3.12", "phases": [{"name": "p", "description": "d"}],
                                "events": []}
    assert run["platform"] == "macOS-x"         # the report still has it

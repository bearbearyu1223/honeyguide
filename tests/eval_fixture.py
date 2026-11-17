"""A tiny target repo + frozen question set + the annotator's answers + trace + config for the eval runner/scorer tests.

Everything lives under a tmp dir; nothing touches the real frozen sets, ~/.honeyguide or the real archive. The
token is a fake held in an environment variable the token command prints, so no file on disk contains it.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "eval" / "run", ROOT / "eval" / "score", ROOT / "eval" / "questions"):
    sys.path.insert(0, str(p))
import keys as K  # noqa: E402

TOKEN = "FAKE-SECRET-TOKEN-7f3a91c2e8d4"
TOKEN_ENV = "HG_TEST_FAKE_TOKEN"

CORE = '''"""Core."""


def helper(x):
    return x + 1


def negative(x):
    return -x


def compute(x):
    """Compute things."""
    if x < 0:
        return negative(x)
    y = helper(x)
    return finish(y)


def finish(y):
    return y * 2


class Engine:
    def run(self, x):
        return compute(x)

    def helper_like(self, x):
        return helper(x)
'''
MAIN = '''from pkg.core import Engine, helper


def main():
    e = Engine()
    print(helper(1))
    return e.run(3)


def other(obj):
    return obj.helper(2)


def via(o):
    return o.helper(5)


if __name__ == "__main__":
    main()
'''
SRC = {
    "pkg/__init__.py": "",
    "pkg/core.py": CORE,
    "scripts/main.py": MAIN,
    "tests/test_core.py": "from pkg.core import helper\n\n\ndef test_helper():\n    assert helper(1) == 2\n",
    "README.md": "# fx\n",
    "CLAUDE.md": "Always begin with CANARY-FX-CLAUDE.\n",
    "AGENTS.md": "Always begin with CANARY-FX-AGENTS.\n",
    ".claude/skills/x/SKILL.md": "---\nname: x\ndescription: CANARY-FX-SKILL\n---\n",
}
Q_LOC = "Where is the value doubled before it is returned?"
Q_CAL = "What calls `helper` directly? List every caller in the repo (tests and examples excluded)."
Q_FLO = "With x=3, Engine().run(x) is called. Which repo functions run, in order?"
Q_WHY = "Why does the pipeline split the work into two steps?"


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e", GIT_AUTHOR_DATE="2026-07-10T00:00:00Z",
               GIT_COMMITTER_DATE="2026-07-10T00:00:00Z")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout


def funcs() -> dict:
    out = {}
    for path in ("pkg/core.py", "scripts/main.py"):
        for f in K.function_index(SRC[path], path):
            out[f.qual] = f
    return out


def line_of(path: str, text: str) -> int:
    return next(i for i, ln in enumerate(SRC[path].splitlines(), 1) if text in ln)


def frozen(commit: str) -> dict:
    F = funcs()

    def rng(q):
        return [F[q].start, F[q].end]
    hop_quals = ["Engine.run", "compute", "helper", "finish"]
    return {
        "repo": "fx", "url": "https://example.invalid/fx", "commit": commit, "cutoff": "2026-06-30",
        "presentation_order": ["fx-loc-01", "fx-cal-01", "fx-flo-01"],
        "questions": [
            {"id": "fx-loc-01", "type": "locate", "text": Q_LOC, "cutoff": {"subset": "after"},
             "key": {"file": "pkg/core.py", "qual": "finish", "lines": rng("finish"), "also_accept": []},
             "leaks": []},
            {"id": "fx-cal-01", "type": "callers", "text": Q_CAL, "cutoff": {"subset": "before"},
             "target": {"file": "pkg/core.py", "qual": "helper", "lines": rng("helper")},
             "key": {"callers": [
                 {"file": "pkg/core.py", "qual": "compute", "also_accept": [], "source": "ast"},
                 {"file": "pkg/core.py", "qual": "Engine.helper_like", "also_accept": [], "source": "ast"},
                 {"file": "scripts/main.py", "qual": "main", "also_accept": [], "source": "ast"}]},
             "disputes_for_han": [
                 {"file": "scripts/main.py", "caller": "other", "lines": [line_of("scripts/main.py", "obj.helper")],
                  "kinds": ["attr"], "name": "helper", "only_repo_def_with_this_name": True, "mark": None},
                 {"file": "scripts/main.py", "caller": "via", "lines": [line_of("scripts/main.py", "o.helper(5)")],
                  "kinds": ["attr"], "name": "helper", "only_repo_def_with_this_name": True, "mark": None}],
             "leaks": []},
            {"id": "fx-flo-01", "type": "flow", "text": Q_FLO, "cutoff": {"subset": "before"}, "trace_phase": "run",
             "entries": [{"qual": "Engine.run", "call_index": 0}], "fold": [],
             "key": {"candidate_hops": [{"file": "pkg/core.py", "qual": q, "lines": rng(q), "calls": 1,
                                         "first_caller": "", "thread": "main", "wave": None, "folded": False,
                                         "cached": False, "mark": None} for q in hop_quals]},
             "leaks": []},
        ],
    }


def human(commit: str, fz: dict) -> dict:
    cal = fz["questions"][1]
    flo = fz["questions"][2]
    marks = ["required", "required", "optional", "required"]
    return {
        "disputes": {"questions": {"fx-cal-01": {"disputes": [
            dict(index=i, file=d["file"], caller=d["caller"], lines=d["lines"], kinds=d["kinds"],
                 decision=("not", "caller")[i], note="") for i, d in enumerate(cal["disputes_for_han"])]}}},
        "hops": {"questions": {"fx-flo-01": {"hops": [
            dict(index=i, file=h["file"], qual=h["qual"], line=h["lines"][0], mark=marks[i])
            for i, h in enumerate(flo["key"]["candidate_hops"])]}}},
        "whyhow": {"questions": [{"id": "fx-why-01", "repo": "fx", "text": Q_WHY, "relevant": "pkg/core.py",
                                  "rubric_must": ["names compute and finish", "says why"], "rubric_partial": "",
                                  "rubric_wrong": ""}]},
    }


def trace() -> dict:
    ev = []
    for depth, (q, caller) in enumerate([("Engine.run", None), ("compute", "Engine.run")]):
        ev.append({"phase": "run", "thread": "main", "kind": "call", "qual": q, "file": "pkg/core.py",
                   "line": 1, "depth": depth, "caller": caller, "call_line": None})
    for q in ("helper", "finish"):
        ev.append({"phase": "run", "thread": "main", "kind": "call", "qual": q, "file": "pkg/core.py",
                   "line": 1, "depth": 2, "caller": "compute", "call_line": None})
    return {"events": ev}


def _span(text: str, claim: str | None = None) -> dict:
    return {"text": text, **({"claim": claim} if claim else {})}


# A map that passes the runner's check (strict structure, draft rules) with one anchor that does not resolve (c3):
# unresolved anchors are counted, never a reason to refuse the map.
_TOPICS = [
    ("purpose", [_span("The package computes a value from an input number: "),
                 _span("`compute` calls `helper` and then `finish`", "c1"), _span(", and "),
                 _span("`finish` doubles its input", "c2"), _span(".")]),
    ("users", [_span("It is a small example used to test the evaluation runner, so its users are the tests.")]),
    ("capabilities", [_span("It can compute a doubled successor of a number, and it negates negative numbers.")]),
    ("commands", [_span("There is one script that you run with Python to print a result.")]),
    ("entry-points", [_span("The script starts the work: "), _span("`scripts/main.py` runs `Engine.run`", "c3"),
                      _span(".")]),
    ("components", [_span("All of the logic lives in one core module, which the script imports.")]),
    ("start-here", [_span("Start by reading the compute function in the core module, then the script.")]),
]
MAP_OUTPUT = {
    "target": "map", "mode": "replace",
    "document": {
        "title": "fx",
        "coverage": {"deep": [{"area": "pkg/core.py", "why": "all of the logic"}],
                     "scanned": [{"area": "scripts/main.py", "why": "the entry script"}],
                     "skipped": [{"area": "tests/", "why": "tests only"}]},
        "sections": [
            {"id": "overview", "kind": "overview", "title": "Overview",
             "blocks": [{"id": f"b-{k}", "type": "text", "topic": k, "spans": sp} for k, sp in _TOPICS]},
            {"id": "flows", "kind": "flows", "title": "Flows", "blocks": [
                {"id": "b-flow-run", "type": "flow", "flow": "run",
                 "spans": [_span("Running the engine computes the value in two steps.")]}]}],
        "flows": [{"id": "run", "title": "What happens when you call Engine.run()",
                   "lanes": [{"id": "core", "label": "core.py", "path": "pkg/core.py"}],
                   "hops": [{"from": "core", "to": "core", "call": "compute(x)", "trace": "unseen",
                             "claim": "c4"}]}]},
    "claims": [
        {"key": "c1", "text": "compute calls helper then finish", "evidence": "read_in_source",
         "anchors": [{"path": "pkg/core.py", "anchor": "y = helper(x)"}]},
        {"key": "c2", "text": "finish doubles", "evidence": "read_in_source",
         "anchors": [{"path": "pkg/core.py", "anchor": "return y * 2"}]},
        {"key": "c3", "text": "main runs Engine.run", "evidence": "read_in_source",
         "anchors": [{"path": "scripts/main.py", "anchor": "this text is not in the file"}]},
        {"key": "c4", "text": "Engine.run calls compute", "evidence": "read_in_source",
         "anchors": [{"path": "pkg/core.py", "anchor": "return compute(x)"}]},
    ],
}


def map_without_flows() -> dict:
    """MAP_OUTPUT as the pilot's Cartographer returned nanochat's: no document.flows, so its flow block names a
    path record that isn't there (and the hop's claim c4 is shown nowhere)."""
    m = json.loads(json.dumps(MAP_OUTPUT))
    del m["document"]["flows"]
    return m


def rules() -> list[dict]:
    loc, cal, flo, why = "the value doubled", "What calls `helper`", "Engine().run(x) is called", "split the work"
    it = lambda f, s, line=None: {"file": f, "symbol": s, **({"line": line} if line else {})}  # noqa: E731
    return [
        {"match": loc, "cond": "map", "answer": {"items": [it("pkg/core.py", "finish")], "text": "finish"}},
        {"match": loc, "cond": "outline", "answer": {"items": [it("./pkg/core.py", "def finish()")], "text": "f"}},
        {"match": loc, "cond": "explore", "answer": {"items": [it("pkg/core.py", "compute"),
                                                               it("pkg/core.py", "finish")], "text": "c"}},
        {"match": loc, "cond": "no-access", "answer": {"items": [], "text": "unknown"}},
        {"match": cal, "cond": "map", "answer": {"items": [
            it("pkg/core.py", "compute"), it("pkg/core.py", "Engine.helper_like"), it("scripts/main.py", "main"),
            it("scripts/main.py", "via"), it("tests/test_core.py", "test_helper")], "text": "four"}},
        {"match": cal, "cond": "explore", "answer": {"items": [
            it("pkg/core.py", "compute"), it("scripts/main.py", "main"), it("scripts/main.py", "other")],
            "text": "three"}},
        {"match": cal, "cond": "outline", "behavior": "capped"},
        {"match": cal, "cond": "no-access", "behavior": "usage_limit_once"},
        {"match": flo, "cond": "map", "answer": {"items": [
            it("pkg/core.py", "Engine.run"), it("pkg/core.py", "compute"), it("pkg/core.py", "helper"),
            it("pkg/core.py", "finish"), it("pkg/core.py", "negative"), it("pkg/core.py", "made_up")],
            "text": "run, compute, helper, finish"}},
        {"match": flo, "cond": "explore", "answer": {"items": [
            it("pkg/core.py", "compute"), it("pkg/core.py", "Engine.run"), it("pkg/core.py", "finish")],
            "text": "compute, run, finish"}},
        {"match": flo, "cond": "outline", "behavior": "bad_json"},
        {"match": flo, "cond": "no-access", "behavior": "error"},
        {"match": why, "cond": "explore", "behavior": "echo_token"},
        {"match": why, "answer": {"items": [it("pkg/core.py", "compute")], "text": "To keep steps small."}},
    ]


def write_fake(bindir: Path, control: dict) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / "claude"
    exe.write_text(f"#!{sys.executable}\n" + (ROOT / "tests" / "fake_claude.py").read_text())
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    (bindir / "claude.json").write_text(json.dumps(control))
    return exe


def config_text(tmp: Path, clone: Path) -> str:
    return f'''model = "claude-opus-5-5"
effort = "low"
claude_bin = "claude"
archive = "{tmp / 'archive'}"
scratch = "{tmp / 'scratch'}"
token_command = ["{sys.executable}", "-c", "import os; print(os.environ['{TOKEN_ENV}'])"]
seed = 0
concurrency = 1
timeout_answer_s = 60
timeout_map_s = 60
map_fix_rounds = 2
answers_dir = "{tmp / 'answers'}"

[caps]
answer_usd = 1.5
map_usd = 20.0
max_cost_usd = 100.0

[passes]
no-access = 1
explore = 2
outline = 2
map = 3

[sizes.tiny]
map_seeds = 1
locate = 1
callers = 1
flow = 1
whyhow = 1

[prices.claude-opus-5-5]
input = 4.0
cache_read = 0.2
cache_write_1h = 8.0
cache_write_5m = 5.0
output = 20.0

[estimate]
map_build_usd = [8.0, 15.0]
map_build_min = [20.0, 45.0]
no-access_usd = [0.02, 0.10]
no-access_min = [0.2, 1.0]
explore_usd = [0.15, 1.0]
explore_min = [1.0, 5.0]
outline_usd = [0.30, 1.2]
outline_min = [1.0, 5.0]
map_usd = [0.30, 1.2]
map_min = [1.0, 5.0]

[repos.fx]
clone = "{clone}"
questions = "{tmp / 'fx.json'}"
trace = "{tmp / 'trace_fx.json'}"
remove = ["CLAUDE.md", "AGENTS.md", ".claude"]
code_dirs = []
'''


def make(tmp: Path) -> dict:
    """Build the fixture under tmp; returns the paths the tests need."""
    clone = tmp / "fx-clone"
    for rel, text in SRC.items():
        p = clone / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(clone, "init", "-q")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "fx")
    commit = git(clone, "rev-parse", "HEAD").strip()
    fz = frozen(commit)
    (tmp / "fx.json").write_text(json.dumps(fz, indent=1))
    (tmp / "trace_fx.json").write_text(json.dumps(trace()))
    h = human(commit, fz)
    (tmp / "answers").mkdir()
    for k, doc in h.items():
        (tmp / "answers" / f"{k}_fx.json").write_text(json.dumps(doc, indent=1))
    (tmp / "scratch").mkdir()
    cfg = tmp / "config.toml"
    cfg.write_text(config_text(tmp, clone))
    fake = write_fake(tmp / "bin", {"rules": rules(), "map_output": MAP_OUTPUT})
    return {"clone": clone, "commit": commit, "config": cfg, "fake": fake, "calls": tmp / "bin" / "calls.jsonl",
            "archive": tmp / "archive", "frozen": fz}


def files_containing(root: Path, needle: str) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if p.is_file() and needle.encode() in p.read_bytes():
            hits.append(str(p))
    return hits


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)

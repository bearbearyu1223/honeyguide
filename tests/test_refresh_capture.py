"""eval/refresh/capture.py: the refresh-receipts capture, on a tiny synthetic archive."""

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "eval" / "refresh" / "capture.py"
_spec = importlib.util.spec_from_file_location("eval_refresh_capture", SRC)   # not 'capture': others exist
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

E2_STORE = "github.com__someone__nanochat__0123456789ab"
E3_STORE = "github.com__someone__waku-agent__0123456789ab"
START = "2026-01-02T00:00:00Z"          # E2's refresh start
BUILD_AT = "2026-01-01T00:30:00Z"       # a time inside the build
LATER = "2026-01-02T00:10:00Z"          # a time inside the refresh
BLOCKS = ["commits", "plan", "cost", "refresh", "current-but-false", "build"]

RUNS_TXT = """Honeyguide runs: receipts
==========================================================================
  archive   honeyguide-targets/_runs (read only)

runs
--------------------------------------------------------------------------
Wall clock from the launcher's start/end files.
  repo        pass           wall min   turns  cost (list)          exit
  nanochat    run 2              31.1      8*       $13.42             0
  waku-agent  run 1      not recorded      12       $13.63  not recorded
  waku-agent  run 2              35.2      2*       $12.43             0
  waku-agent  repair              6.3      19        $2.76             0
  waku-agent  re-check           10.2      21        $4.20             0
  waku-agent  total                                 $33.03

maps
--------------------------------------------------------------------------
  waku-agent  run 2              99.9      99       $99.99             0
"""


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def anchor(path, start, end, commit):
    return {"path": path, "anchor": "x", "start": start, "end": end, "commit": commit, "hash": "h"}


def claim(cid, commit, freshness="current", check="supported", checked_at=BUILD_AT, anchors=None, **extra):
    return {"id": cid, "key": cid, "text": "a claim", "evidence": "read_in_source", "check": check,
            "check_note": "", "checked_at": checked_at, "freshness": freshness, "freshness_reason": "",
            "anchors": anchors if anchors is not None else [anchor("a.py", 1, 2, commit)], **extra}


def rep(rnd, action, at, pid="p_000000000001"):
    return {"pass": pid, "round": rnd, "action": action, "at": at, "check_note": "n", "text": "t",
            "anchors": ["a.py:1-2"]}


def result(cost, minutes, turns, denials=()):
    return {"type": "result", "subtype": "success", "total_cost_usd": cost, "duration_ms": int(minutes * 60000),
            "num_turns": turns, "result_index": 0, "result": "PROSE: 999 claims retired",
            "permission_denials": list(denials),
            "subagent_stats": {"by_type": {"honeyguide:checker": 1}},
            "modelUsage": {"model-a": {"inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 3000,
                                       "cacheCreationInputTokens": 400, "costUSD": cost}}}


def run_dir(d, start, end, res):
    d.mkdir(parents=True)
    (d / "start").write_text(start + "\n")
    (d / "end").write_text(end + "\n")
    (d / "exit").write_text("0\n")
    if res is not None:
        write_json(d / "result.json", res)


def git_repo(path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}
    path.mkdir(parents=True)

    def g(*args, date=None):
        e = dict(env, GIT_AUTHOR_DATE=date or "", GIT_COMMITTER_DATE=date or "") if date else env
        return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                              env=e).stdout.strip()
    g("init", "-q")
    (path / "a.py").write_text("x = 1\n")
    (path / "README.md").write_text("hi\n")
    g("add", ".")
    g("commit", "-qm", "base", date="2026-01-01T00:00:00+00:00")
    base = g("rev-parse", "HEAD")
    (path / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
    g("commit", "-qam", "one", date="2026-01-02T00:00:00+00:00")
    (path / "b.py").write_text("def f():\n    pass\n")
    (path / "README.md").write_text("hello\n")
    g("add", ".")
    g("commit", "-qm", "two", date="2026-01-04T12:00:00+00:00")
    return base, g("rev-parse", "HEAD")


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "_refresh"
    # ---- E2: a build and a refresh, with a git checkout
    e2 = root / "e2"
    base, target = git_repo(e2 / "nanochat")
    run_dir(e2 / "build", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", result(20.0, 60, 27))
    run_dir(e2 / "refresh", START, "2026-01-02T00:30:00Z",
            result(5.0, 30, 28, [{"tool_name": "Write", "tool_input": {
                "file_path": str(tmp_path / "_refresh" / "e2" / "home" / E2_STORE / "drafts" / "x.json")}}]))
    write_json(e2 / "refresh_plan_before.json", {
        "base": base, "target": target, "warnings": [], "counts": {},
        "claims": [{"id": i, "response": None, "state": s, "reason": "", "anchors": []} for i, s in (
            ("c_unch", "unchanged"), ("c_moved", "moved"), ("c_moved2", "moved"), ("c_held", "stale"),
            ("c_gone", "stale"), ("c_ret", "retired"), ("c_unanch", "unanchored"), ("c_built", "unchanged"))],
        "uncovered": [{"path": "b.py", "qualname": "f", "kind": "function", "start": 1, "end": 2, "change": "new"},
                      {"path": "a.py", "qualname": "g", "kind": "function", "start": 50, "end": 60,
                       "change": "changed"}],
        "unoutlined": ["README.md"]})
    claims = [
        claim("c_unch", target),
        claim("c_moved", target),
        claim("c_moved2", target, freshness="retired", retired_at=LATER),        # current but false
        claim("c_held", target, rechecked_at=LATER, checked_at=LATER),
        claim("c_gone", target, freshness="retired", check="not_supported", rechecked_at=LATER, checked_at=LATER,
              retired_at=LATER),
        claim("c_ret", base, freshness="retired", refreshed_to=target),
        claim("c_unanch", target, anchors=[]),
        claim("c_built", target, repairs=[rep(1, "anchor", BUILD_AT), rep(2, "rewrite", BUILD_AT)]),
        claim("c_new1", target, checked_at=LATER, anchors=[anchor("b.py", 1, 1, target)],
              repairs=[rep(1, "anchor", LATER, "p_000000000002")]),
        claim("c_new2", target, checked_at=LATER),
    ]
    store = e2 / "home" / E2_STORE
    write_json(store / "map.json", {"schema": "honeyguide/map", "version": 1, "commit": target,
                                    "document": None, "claims": claims})
    write_json(store / "session.json", {"refresh_log": [{"at": START, "base": base, "target": target,
                                                         "counts": {"unchanged": 2}, "uncovered": 2}]})
    # ---- E3: attempt 1 only (attempt 2's result.json missing), no checkout, no plan
    e3 = root / "e3"
    run_dir(e3 / "run", "2026-01-05T00:00:00Z", "2026-01-05T00:02:00Z", result(0.5, 2, 16))
    run_dir(e3 / "run2", "2026-01-05T00:03:00Z", "2026-01-05T00:13:00Z", None)
    write_json(e3 / "home" / E3_STORE / "map.json", {"schema": "honeyguide/map", "version": 1, "commit": None,
                                                     "claims": []})
    runs = tmp_path / "runs.txt"
    runs.write_text(RUNS_TXT)
    return root, runs, tmp_path


def render(archive):
    root, runs, tmp = archive
    return cap.render(root, runs, tmp / "no-such-worktree")


def section(out, name):
    lines = out.splitlines()
    i = lines.index(name)
    j = next((k for k in range(i + 1, len(lines)) if lines[k] in BLOCKS), len(lines))
    return "\n".join(lines[i:j])


# ---------------------------------------------------------------- pure helpers

def test_parse_runs_block_reads_only_the_runs_table():
    rows = cap.parse_runs_block(RUNS_TXT, "waku-agent")
    assert rows["run 2"] == {"wall": 35.2, "turns": "2*", "cost": 12.43, "exit": "0"}
    assert rows["run 1"]["wall"] is None and rows["run 1"]["exit"] == "not recorded"
    assert rows["re-check"]["cost"] == 4.20
    assert rows["total"]["cost"] == 33.03 and rows["total"]["wall"] is None
    assert cap.parse_runs_block("no runs here", "waku-agent") == {}


def test_run_summary_sums_model_usage_and_marks_missing():
    s = cap.run_summary(result(1.5, 3, 7))
    assert (s["cost"], s["session_min"], s["turns"]) == (1.5, 3.0, 7)
    assert (s["input"], s["cache_read"], s["cache_write"], s["output"]) == (10, 3000, 400, 20)
    empty = cap.run_summary(None)
    assert empty["cost"] is None and empty["input"] is None and empty["models"] == []


def test_refresh_outcome_and_current_but_false(archive):
    root, _, _ = archive
    plan = json.loads((root / "e2" / "refresh_plan_before.json").read_text())
    claims = json.loads((root / "e2" / "home" / E2_STORE / "map.json").read_text())["claims"]
    o = cap.refresh_outcome(plan, claims, START)
    assert o["after"] == {"current": 7, "stale": 0, "retired": 3}
    assert (o["retired_by_apply"], o["retired_by_remap"], o["retired_by_repair"]) == (1, 2, 0)
    assert o["remap_by_class"]["moved"] == 1 and o["remap_by_class"]["stale"] == 1
    assert o["new"] == 2
    assert (o["stale_held"], o["stale_not_held"], o["stale_not_held_retired"]) == (1, 1, 1)
    cbf = cap.current_but_false(plan, claims, START)
    assert cbf["unchanged"] == (0, 2) and cbf["moved"] == (1, 2)
    v = cap.new_claim_verdicts(plan, claims, START)
    assert v["first"]["supported"] == 1 and v["first"]["not_supported"] == 1
    assert v["after"][1]["supported"] == 2 and v["old_repaired"] == 0
    h = cap.build_history(plan, claims, START)
    assert h["flagged"] == {1: 1, 2: 1} and h["unrepaired"] == 7
    assert h["unrepaired_verdicts"]["not recorded"] == 2      # c_held, c_gone re-checked by the refresh
    m = cap.uncovered_mapped(plan, claims, {"c_new1", "c_new2"})
    assert m == {"new": (1, 1), "changed": (0, 1)}


def test_claim_retired_before_the_refresh_is_not_a_new_claim():
    """fbd9a6eca (review round 3): plan_refresh skips claims already retired, so the plan does not list them; a
    claim the build's repair pass (or an earlier refresh apply, which stamps no retired_at) retired is not new."""
    plan = {"target": "t", "claims": [{"id": "c1", "state": "unchanged"}]}
    claims = [
        claim("c1", "t"),
        claim("old", "t", freshness="retired", retired_at=BUILD_AT, repairs=[rep(1, "retire", BUILD_AT)]),
        claim("old_apply", "t", freshness="retired"),                       # retired by an earlier refresh apply
        claim("new_then_retired", "t", freshness="retired", retired_at=LATER, checked_at=LATER),
        claim("new", "t", checked_at=LATER),
    ]
    out = cap.refresh_outcome(plan, claims, START)
    assert out["new"] == 2 and out["retired_before"] == 2
    assert [c["id"] for c in cap.new_claims(plan, claims, START)] == ["new_then_retired", "new"]
    assert out["remap_by_class"]["new"] == 1
    v = cap.new_claim_verdicts(plan, claims, START)
    assert sum(v["first"].values()) == 2


def test_parse_reflog_and_head_at():
    text = ("bbbbbbb1\tHEAD@{2026-11-16T15:23:33-08:00}\n"
            "aaaaaaa1\tHEAD@{2026-11-16T00:20:17-08:00}\n"
            "not a reflog line\n")
    entries = cap.parse_reflog(text)
    assert [s for _, s in entries] == ["bbbbbbb1", "aaaaaaa1"]
    sha_, since = cap.head_at(entries, "2026-11-16T23:23:49Z")             # 16 s after the move to bbbbbbb1
    assert sha_ == "bbbbbbb1" and since.strftime("%Y-%m-%d %H:%M:%S") == "2026-11-16 23:23:33"
    assert cap.head_at(entries, "2026-11-16T23:23:32Z")[0] == "aaaaaaa1"   # one second before it
    assert cap.head_at(entries, "2026-11-16T08:20:16Z") is None             # before the first entry
    assert cap.head_at(entries, None) is None and cap.parse_reflog(None) == []


def test_run_commits_from_the_worktree_reflog(archive, tmp_path):
    root, runs, _ = archive
    wt = tmp_path / "honeyguide-run"
    wt.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def g(*args, date):
        return subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True, text=True,
                              env=dict(env, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)).stdout.strip()
    g("init", "-q", date="2025-12-31T00:00:00+00:00")
    g("commit", "-q", "--allow-empty", "-m", "one", date="2025-12-31T00:00:00+00:00")
    first = g("rev-parse", "HEAD", date="2025-12-31T00:00:00+00:00")
    g("commit", "-q", "--allow-empty", "-m", "two", date="2026-01-03T00:00:00+00:00")   # after E2's runs
    out = cap.render(root, runs, wt)
    commits = section(out, "commits")
    assert f"    E2 build              2026-01-01 00:00:00 {first[:7]}  2025-12-31 00:00:00" in commits
    assert f"    E2 refresh            2026-01-02 00:00:00 {first[:7]}  2025-12-31 00:00:00" in commits
    assert "runs started on the same commit" not in commits                 # E3 ran after the second commit
    assert f"(same Honeyguide commit as the refresh, {first[:7]}, by the reflog;" in " ".join(
        section(out, "cost").split())


def test_retired_by_repair_is_not_a_remap():
    c = claim("c", "t", freshness="retired", retired_at=LATER, repairs=[rep(1, "retire", LATER)])
    assert cap.retired_by_repair(c)
    plan = {"claims": [{"id": "c", "state": "moved"}]}
    o = cap.refresh_outcome(plan, [c], START)
    assert o["retired_by_repair"] == 1 and o["retired_by_remap"] == 0


# ---------------------------------------------------------------- the whole receipt

def test_render_reads_git_store_and_runs_txt(archive):
    out = render(archive)
    for b in BLOCKS:
        assert b in out.splitlines()
    commits = section(out, "commits")
    assert "days apart          3.5" in commits
    assert "commits in between  2" in commits
    assert ".py files changed   2 (+4 / -0 lines)" in commits
    assert "all files changed   3 (+5 / -1 lines)" in commits
    assert ".py lines at base   1 in 1 files" in commits
    assert ".py lines at target 5 in 2 files" in commits
    cost = section(out, "cost")
    assert "$20.00" in cost and "$5.00" in cost
    assert "refresh / rebuild:  $ 0.25, wall minutes 0.50" in cost
    assert re.search(r"rebuild total\s+\$19\.39\s+51\.7", cost)     # E3, from runs.txt's runs block only
    assert "$99.99" not in out and "999" not in out                    # other blocks, and the agent's prose
    assert "denied writes into the store:" in cost and "drafts/x.json x1" in cost
    cbf = section(out, "current-but-false")
    assert "current but false   1 of 4 (unchanged + moved)" in cbf


def test_missing_values_print_not_recorded(archive):
    out = render(archive)
    commits = section(out, "commits")
    e3 = commits[commits.index("E3"):]
    assert "base                not recorded" in e3                      # no plan, no checkout
    assert "commits in between  not recorded" in e3
    assert "    E2 build              2026-01-01 00:00:00 not recorded" in commits   # no worktree, no reflog
    assert "same commit" not in commits
    assert "(Honeyguide commit not recorded; full Explore" in " ".join(section(out, "cost").split())
    cost = section(out, "cost")
    assert "refresh, attempt 2: $ list not recorded, wall min 10.0, session not recorded" in " ".join(
        cost.split())
    assert "refresh, attempt 2: input not recorded" in cost
    assert "rebuild tokens        not recorded" in cost
    refresh = section(out, "refresh")
    assert refresh[refresh.index("E3"):].splitlines()[1].strip() == "not recorded"
    assert "replaced (linked to a new claim)  not recorded" in section(out, "current-but-false")


def test_width_and_no_paths_or_emails(archive):
    out = render(archive)
    _, _, tmp = archive
    for line in out.splitlines():
        assert len(line) <= cap.WIDTH, line
        assert line == line.rstrip()
    assert str(tmp) not in out and str(Path.home()) not in out
    assert not re.search(r"(^|\s)/(Users|home|private|tmp|var)/", out)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", out)


# ---------------------------------------------------------------- review round 4

def test_the_receipt_says_where_the_table_came_from(archive, tmp_path):
    root, runs, _ = archive
    out = cap.render(root, runs, tmp_path / "no-such-worktree")
    assert "Read from the live reflog" in " ".join(section(out, "commits").split())
    rec = {"read_at": "2026-11-17T05:07:22Z", "source": "test",
           "runs": [{"run": "E2 build", "start": "2026-01-01T00:00:00Z", "commit": "c" * 40,
                     "since": "2025-12-31T00:00:00Z"},
                    {"run": "E2 refresh", "start": "2026-01-02T00:00:00Z", "commit": "c" * 40,
                     "since": "2025-12-31T00:00:00Z"}]}
    path = tmp_path / "run_commits.json"
    path.write_text(json.dumps(rec))
    out = cap.render(root, runs, tmp_path / "no-such-worktree", path)
    commits = " ".join(section(out, "commits").split())
    assert "2 of 4 runs read from run_commits.json (frozen from that reflog at 2026-11-17 05:07 UTC)" in commits
    assert "E2 build 2026-01-01 00:00:00 ccccccc 2025-12-31 00:00:00" in commits
    assert "(same Honeyguide commit as the refresh, ccccccc, by the reflog;" in " ".join(section(out, "cost").split())
    for line in out.splitlines():
        assert len(line) <= cap.WIDTH


def test_capture_prints_the_rebuild_less_its_extra_pass(archive):
    cost = section(render(archive), "cost")
    assert re.search(r"^    rebuild less re-check\s+\$15\.19\s+41\.5$", cost, re.M)          # 12.43 + 2.76
    assert "both attempts / rebuild less re-check:" in cost

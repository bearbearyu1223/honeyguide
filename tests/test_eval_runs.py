"""eval/runs/capture.py: the run-receipts capture, on a tiny synthetic archive."""

import importlib.util
import json
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "eval" / "runs" / "capture.py"
_spec = importlib.util.spec_from_file_location("eval_runs_capture", SRC)   # not 'capture': eval/trace has one
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

STORE = "github.com__someone__toy__0123456789ab"
BLOCKS = ["runs", "maps", "checker", "recheck", "readability", "demo", "examples"]
SENTENCE = ("The toy repo trains a tiny model on one machine and writes every result to a single "
            "file so that a reader can follow the whole run from one place.")


def anchor(path, start, end):
    return {"path": path, "anchor": "x", "start": start, "end": end, "commit": "c" * 40, "hash": "h"}


def claim(cid, check="supported", repairs=(), text="a claim", evidence="read_in_source", anchors=None):
    c = {"id": cid, "key": cid, "text": text, "evidence": evidence, "check": check, "check_note": "",
         "freshness": "current", "freshness_reason": "", "anchors": anchors or [anchor("a.py", 1, 1)]}
    if repairs:
        c["repairs"] = list(repairs)
    return c


def rep(rnd, action, text, anchors, at="2026-01-01T00:00:00Z"):
    return {"round": rnd, "action": action, "at": at, "check_note": "n", "text": text, "anchors": anchors}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def result(turns, cost, ms, index=0):
    return {"type": "result", "num_turns": turns, "total_cost_usd": cost, "duration_ms": ms, "result_index": index}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "_runs"
    run1_map = {"document": {"sections": [
        {"id": "overview", "kind": "overview", "title": "Overview",
         "blocks": [{"id": "b1", "type": "text", "spans": [{"text": "A toy. Tiny."}]}]},
        {"id": "modules", "kind": "modules", "title": "Modules",
         "blocks": [{"id": "m1", "type": "module", "path": "a.py", "spans": [{"text": "A."}]}]}],
        "flows": [{"id": "p1", "hops": [{"claim": "c_1"}]}]},
        "claims": [claim("c_1"), claim("c_2", check="not_supported")]}
    write_json(root / "run1" / STORE / "map.json", run1_map)
    (root / "run1" / "start").write_text("2026-01-01T00:00:00Z\n")
    write_json(root / "run1" / "toy-result.json", result(5, 1.5, 600000))
    topics = ["purpose", "users", "capabilities", "commands", "entry-points", "components", "start-here"]
    final_map = {"document": {"sections": [
        {"id": "overview", "kind": "overview", "title": "Overview",
         "blocks": [{"id": f"o{i}", "type": "text", "topic": t, "spans": [{"text": SENTENCE}]}
                    for i, t in enumerate(topics)]},
        {"id": "modules", "kind": "modules", "title": "Modules",
         "blocks": [{"id": "m1", "type": "module", "files": ["a.py", "b.py"], "spans": [{"text": SENTENCE}]}]}],
        "flows": [{"id": "p1", "hops": [{"claim": "c_1"}, {"claim": "c_2"}]}]},
        "claims": [
            claim("c_1"),
            claim("c_2", repairs=[rep(1, "anchor", "a claim", ["a.py:1-1"])], anchors=[anchor("a.py", 1, 5)]),
            claim("c_3", text="narrow", repairs=[rep(1, "anchor", "wide", ["a.py:1-1"]),
                                                 rep(2, "rewrite", "wide", ["a.py:1-3"])]),
            claim("c_4", check="not_supported"),
        ]}
    write_json(root / "after-repair" / STORE / "map.json", final_map)
    # The re-check (rounds at T1, T2): c_1 anchor then rewrite; c_2 (repaired before, so its history labels
    # this pass's round-1 repair as round 2) still not supported; c_3 untouched; c_4 rewritten in round 1.
    t1, t2, later = "2026-01-02T00:10:00Z", "2026-01-02T00:20:00Z", "2026-01-02T00:30:00Z"
    c1, c2, c3, c4 = (json.loads(json.dumps(c)) for c in final_map["claims"])
    c1.update(text="exact", checked_at=later, repairs=[rep(1, "anchor", "a claim", ["a.py:1-1"], t1),
                                                       rep(2, "rewrite", "a claim", ["a.py:1-2"], t2)])
    c2.update(check="not_supported", check_note="still wrong", checked_at=later,
              repairs=c2["repairs"] + [rep(2, "anchor", "a claim", ["a.py:1-5"], t1)])
    c4.update(check="supported", text="fixed", checked_at=later,
              repairs=[rep(1, "rewrite", "a claim", ["a.py:1-1"], t1)])
    write_json(root / "after-recheck" / STORE / "map.json", dict(final_map, claims=[c1, c2, c3, c4]))
    write_json(root / "after-repair" / STORE / "answers.json", {
        "questions": [{"id": "q_1", "text": "Where?", "agent": "tracer", "response": "r_1",
                       "created_at": "2026-01-01T01:00:00Z", "answered_at": "2026-01-01T01:01:30Z"}],
        "responses": [{"id": "r_1", "claims": [claim("c_9"), claim("c_8", check="not_supported")]}]})
    for sub, start, end in (("run2", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"),
                            ("repair", "2026-01-01T00:40:00Z", "2026-01-01T00:46:00Z"),
                            ("recheck", "2026-01-02T00:00:00Z", "2026-01-02T00:12:00Z")):
        d = root / sub / "toy"
        d.mkdir(parents=True)
        (d / "start").write_text(start + "\n")
        (d / "end").write_text(end + "\n")
        (d / "exit").write_text("0\n")
        write_json(d / "result.json", result(3, 2.0, 60000, index=1 if sub == "run2" else 0))
    q = root / "demo" / "live" / "q1"
    q.mkdir(parents=True)
    (q / "qid").write_text("q_1\n")
    ev = [{"t": 1.0, "e": {"type": "system", "subtype": "init"}},
          {"t": 2.0, "e": {**result(4, 0.5, 90000), "subagent_stats": {"by_type": {"honeyguide:tracer": 1}}}}]
    (q / "answer-q1.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n")
    return root


def parse_blocks(text):
    lines = text.splitlines()
    names = [lines[i - 1] for i in range(1, len(lines)) if lines[i] == "-" * cap.WIDTH]
    return names


def test_blocks_parse_and_fit(archive):
    out = cap.render(archive)
    assert parse_blocks(out) == BLOCKS
    assert all(len(line) <= cap.WIDTH and line == line.rstrip() for line in out.splitlines())
    assert str(archive.parent) not in out and str(Path.home()) not in out


def test_deterministic(archive):
    assert cap.render(archive) == cap.render(archive)


def test_numbers(archive):
    out = cap.render(archive)
    assert "  toy         run 1      not recorded       5        $1.50  not recorded" in out
    assert "  toy         run 2              30.0      3*        $2.00             0" in out
    assert "  toy         total                                  $5.50" in out
    # c_2, c_3 repaired in round 1; c_3 again in round 2; c_4 never repaired
    assert "  toy         run 2 before repair            1         3" in out
    assert "  toy         after repair round 1           2         2" in out
    assert "  toy         after repair round 2           3         1" in out
    assert "    Overview topics     7 of 7" in out
    assert "    module blocks       1 (1 with more than one file)" in out
    assert "    Checker           supported 1, not supported 1" in out
    assert "    posted->answered  90 s (answers.json timestamps)" in out
    assert "      c_3 (toy, repair round 2)" in out
    # maps: after repair (3 supported, 1 not) then after re-check (3 and 1, different claims)
    assert out.count("    Checker verdicts    supported 3, not supported 1") == 2
    assert "  toy, run 2 after re-check" in out


def test_recheck_block(archive):
    out = cap.render(archive)
    assert "  toy              12.0      3        $2.00             0" in out
    assert "  toy                   4           3                3                1" in out
    assert "  toy         before repair                  0         3         0       0" in out
    assert "  toy         after repair round 1           1         2         0       0" in out
    assert "  toy         after repair round 2           2         1         0       0" in out
    assert "  toy             1                 2          1        0" in out
    assert "  toy             2                 0          1        0" in out
    assert f"  (e) {cap.WRONGLY_PASSED} after the re-check" in out
    assert f"(f) {cap.RECHECK_REWRITTEN}" not in out   # absent from the toy archive: block omitted


def test_claim_state_rounds():
    c = claim("c", repairs=[rep(1, "anchor", "t", []), rep(2, "anchor", "t", [])])
    assert [cap.claim_state(c, k) for k in (0, 1, 2)] == ["not_supported", "not_supported", "supported"]
    retired = dict(claim("r", repairs=[rep(1, "retire", "t", [])]), freshness="retired")
    assert [cap.claim_state(retired, k) for k in (0, 1)] == ["not_supported", "retired"]


def test_helpers():
    assert cap.repo_of_store("github.com__karpathy__nanochat__3a5e0bc50b12") == "nanochat"
    assert cap.minutes_between("2026-01-01T00:00:00Z", "2026-01-01T00:01:30Z") == 1.5
    assert cap.minutes_between("2026-01-01T00:00:00Z", None) is None
    assert cap.anchor_lines(["a.py:1-3", "a.py:3-3"]) == {("a.py", 1), ("a.py", 2), ("a.py", 3)}
    assert cap.anchor_lines([anchor("b.py", 2, 3)]) == {("b.py", 2), ("b.py", 3)}
    s = cap.repair_summary([claim("c", anchors=[anchor("a.py", 1, 5)], repairs=[rep(1, "anchor", "t", ["a.py:1-1"])])])
    assert s == {1: {"anchor": 1, "rewrite": 0, "retire": 0, "wider": 1}}


def test_recheck_helpers():
    old = [rep(1, "anchor", "t", [])]
    after = claim("c", repairs=old + [rep(2, "rewrite", "t", [], "2026-01-02T00:00:00Z")])
    assert cap.new_repairs(claim("c", repairs=old), after) == after["repairs"][1:]
    assert cap.new_repairs({}, after) == after["repairs"]
    before = [dict(claim("a"), checked_at="2026-01-01T00:00:00Z"), dict(claim("b"), checked_at="2026-01-01T00:00:00Z"),
              dict(claim("c"), checked_at="2026-01-01T00:00:00Z")]
    later = [dict(before[0], checked_at="2026-01-03T00:00:00Z"), dict(before[1], text="changed"), before[2]]
    assert cap.rechecked_ids(before, later) == ["a", "b"]
    reps = [rep(2, "anchor", "t", [], "2026-01-02T00:10:00Z"), rep(1, "anchor", "t", [], "2026-01-02T00:10:00Z"),
            rep(2, "rewrite", "t", [], "2026-01-02T00:20:00Z")]
    assert [r["round"] for r in cap.pass_rounds(reps)] == [1, 1, 2]

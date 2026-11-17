"""The repair pass: ``claims repair`` widens anchors, narrows claims (and the spans that show them) or
retires them, keeping ids and resetting the check, at most twice per claim per repair pass; and the plain flags that let agents call
every write command without piping JSON (``--id``, ``--status``, ``--note-file``, ``drafts dir``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_contract_fixtures import World, a_map

from honeyguide import inbox
from honeyguide.mapdoc import iter_spans, revision
from honeyguide.repair import MAX_ROUNDS, PASS_ID

P1, P2 = "p_0000000000a1", "p_0000000000b2"


def flagged_world(tmp_path, monkeypatch):
    """The toy map saved and checked: ``gen`` and ``call`` not_supported with notes, ``gk`` skipped."""
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data=a_map())
    assert code == 0, out
    ids = {s["key"]: s["id"] for s in out["saved"]}
    code, out = w.call("verdict", "set", data={"verdicts": [
        {"claim": ids["gen"], "verdict": "not_supported", "note": "the cited line is the def only; the loop is lines 9-10"},
        {"claim": ids["call"], "verdict": "not_supported", "note": "true, but cite the def too"},
        {"claim": ids["gk"], "verdict": "skipped"}]})
    assert code == 0, out
    return w, ids


def claim_of(w, cid):
    return next(c for c in w.store.load("map")["claims"] if c["id"] == cid)


def test_claims_list_by_flags_finds_the_flagged(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    code, out = w.call("claims", "list", "--scope", "map", "--check", "not_supported", "--json", "--spans")
    assert code == 0, out
    assert out["count"] == 2 and {c["id"] for c in out["claims"]} == {ids["gen"], ids["call"]}
    by = {c["id"]: c for c in out["claims"]}
    assert by[ids["gen"]]["check_note"].startswith("the cited line")
    assert by[ids["gen"]]["shown_as"] == ["yields three outputs"]
    assert by[ids["call"]]["shown_as"] == []          # shown by a hop only
    # comma lists and repeats both work
    code, out = w.call("claims", "list", "--check", "not_supported,skipped")
    assert out["count"] == 3
    code, out = w.call("claims", "list", "--ids", ids["gen"], "--ids", ids["gk"])
    assert {c["id"] for c in out["claims"]} == {ids["gen"], ids["gk"]}


def test_anchor_rewrite_retire_keep_ids_and_reset_the_check(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    q = inbox.post_question(w.store, {"text": "why three?"})  # unrelated state survives
    before_rev = w.store.load("map")["document"]["revision"]
    old_gen = claim_of(w, ids["gen"])
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [
        {"claim": ids["call"], "action": "anchor",
         "anchors": [{"path": "engine.py", "anchor": "def sample(engine, prompt):", "extent": "block"}]},
        {"claim": ids["gen"], "action": "rewrite", "text": "Engine.generate yields once per loop step",
         "span": "yields once per loop step"}]})
    assert code == 0, out
    assert sorted(out["changed"]) == sorted([ids["call"], ids["gen"]]) and out["retired"] == []
    assert out["spans_rewritten"] == 1 and out["still_not_supported"] == 0
    assert out["rounds"] == {ids["call"]: 1, ids["gen"]: 1}
    call, gen = claim_of(w, ids["call"]), claim_of(w, ids["gen"])
    # ids kept, check reset, history kept
    assert call["check"] == gen["check"] == "unchecked" and call["check_note"] == "" and "checked_at" not in call
    assert call["anchors"][0]["start"] == 13 and call["anchors"][0]["end"] == 14 and call["text"] == "sample calls Engine.generate"
    assert gen["text"] == "Engine.generate yields once per loop step" and gen["anchors"] == old_gen["anchors"]
    assert gen["repairs"] == [{"pass": P1, "round": 1, "action": "rewrite", "at": gen["repairs"][0]["at"],
                               "check_note": "the cited line is the def only; the loop is lines 9-10",
                               "text": "Engine.generate yields three outputs", "anchors": ["engine.py:8-10"]}]
    # the span the map shows is narrowed with it, and the document's revision follows
    doc = w.store.load("map")["document"]
    assert [s["text"] for s in iter_spans(doc) if s.get("claim") == ids["gen"]] == ["yields once per loop step"]
    assert doc["revision"] == revision(doc) != before_rev
    code, out = w.call("map", "validate")
    assert code == 0 and out["valid"], out
    # the Checker's re-check by ids sees exactly the changed claims
    code, out = w.call("claims", "list", "--ids", f"{ids['call']},{ids['gen']}", "--check", "unchecked")
    assert out["count"] == 2
    assert inbox.show(w.store, {"id": q["id"]})["question"]["id"] == q["id"]


def test_retire(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [
        {"claim": ids["gen"], "action": "retire", "reason": "it yields once per step, not three outputs"}]})
    assert code == 0, out
    assert out["retired"] == [ids["gen"]] and out["changed"] == [] and out["still_not_supported"] == 1
    gen = claim_of(w, ids["gen"])
    assert gen["freshness"] == "retired" and gen["freshness_reason"].startswith("repair: it yields")
    assert gen["repairs"][0]["action"] == "retire"


def test_everything_is_checked_before_anything_is_written(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    before = json.dumps(w.store.load("map"), sort_keys=True)
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [
        {"claim": ids["call"], "action": "anchor", "anchors": [{"path": "engine.py", "anchor": "no such text"}]},
        {"claim": ids["gen"], "action": "rewrite", "text": "narrower"},                 # shown by a span: needs span
        {"claim": ids["gk"], "action": "anchor", "anchors": [{"path": "engine.py", "anchor": "class Engine:"}]},
        {"claim": "c_nope", "action": "retire", "reason": "x"},
        {"claim": ids["call"], "action": "retire", "reason": "twice"},
        {"claim": "c_other", "action": "explode"}]})
    assert code == 1 and out["error"]["code"] == "validation_failed"
    details = " | ".join(out["error"]["details"])
    assert "not_found" in details and "repaired twice in one call" in details and "action must be one of" in details
    assert json.dumps(w.store.load("map"), sort_keys=True) == before
    # with the shape fixed, the store-side rules: span required, unknown id, unanchored evidence, wrong check
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [
        {"claim": ids["gen"], "action": "rewrite", "text": "narrower"},
        {"claim": ids["gk"], "action": "anchor", "anchors": [{"path": "engine.py", "anchor": "class Engine:"}]},
        {"claim": "c_nope", "action": "retire", "reason": "x"}]})
    assert code == 1 and out["error"]["code"] == "not_found"
    details = " | ".join(out["error"]["details"])
    assert "give span" in details and "c_nope: no such map claim" in details
    assert "repair takes not_supported claims only" in details      # gk was skipped
    assert json.dumps(w.store.load("map"), sort_keys=True) == before


def test_secrets_are_refused(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [
        {"claim": ids["call"], "action": "anchor", "anchors": [{"path": "config.py", "anchor": "AWS_KEY"}]}]})
    assert code == 1 and out["error"]["code"] == "secret_refused"


def widen_call(ids):
    return [{"claim": ids["call"], "action": "anchor",
             "anchors": [{"path": "engine.py", "anchor": "def sample(engine, prompt):", "extent": "block"}]}]


def repair_and_reject(w, ids, pid, rnd, note):
    """One repair of ``call`` in round ``rnd`` of pass ``pid``; then the Checker re-checks it and still says no."""
    code, out = w.call("claims", "repair", data={"pass": pid, "round": rnd, "repairs": widen_call(ids)})
    assert code == 0, out
    code, v = w.call("verdict", "set", "--id", ids["call"], "--verdict", "not_supported", "--note", note)
    assert code == 0, v
    return out


def test_at_most_two_rounds_per_pass(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    for n in range(1, MAX_ROUNDS + 1):
        out = repair_and_reject(w, ids, P1, n, f"round {n}: still no")
        assert out["rounds"] == {ids["call"]: n} and out["pass"] == P1 and out["round"] == n, out
    # a third repair in the same pass is refused, whatever round it claims
    for rnd in (1, 2):
        code, out = w.call("claims", "repair", data={"pass": P1, "round": rnd, "repairs": widen_call(ids)})
        assert code == 1 and f"already repaired 2 times in pass {P1}; it stays flagged" in out["error"]["details"][0]
    c = claim_of(w, ids["call"])
    assert c["check"] == "not_supported" and [r["check_note"] for r in c["repairs"]][1] == "round 1: still no"


def test_a_later_pass_gets_its_own_two_rounds(tmp_path, monkeypatch):
    """The bug capture.py found: a claim repaired in an earlier pass got one round in the next, saved as "round 2"."""
    w, ids = flagged_world(tmp_path, monkeypatch)
    for pid in (P1, P2):
        for n in (1, 2):
            out = repair_and_reject(w, ids, pid, n, f"{pid} round {n}: still no")
            assert out["rounds"] == {ids["call"]: n}, out
    reps = claim_of(w, ids["call"])["repairs"]
    assert [(r["pass"], r["round"]) for r in reps] == [(P1, 1), (P1, 2), (P2, 1), (P2, 2)]
    code, out = w.call("claims", "repair", data={"pass": P2, "round": 2, "repairs": widen_call(ids)})
    assert code == 1 and f"in pass {P2}" in out["error"]["details"][0]


def test_a_round_is_not_repeated_or_gone_back_to_in_one_pass(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    repair_and_reject(w, ids, P1, 2, "round 2: still no")      # round 2 alone is fine (round 1 left it out)
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": widen_call(ids)})
    assert code == 1 and f"already repaired in round 2 of pass {P1}; this call is round 1" in out["error"]["details"][0]
    w2, ids2 = flagged_world(tmp_path / "two", monkeypatch)
    repair_and_reject(w2, ids2, P1, 1, "round 1: still no")
    code, out = w2.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": widen_call(ids2)})
    assert code == 1 and "already repaired in round 1" in out["error"]["details"][0]


def test_legacy_history_counts_as_one_pass(tmp_path, monkeypatch):
    """History saved before passes existed (no ``pass``) is one legacy pass: it never uses up a new pass's rounds."""
    w, ids = flagged_world(tmp_path, monkeypatch)

    def legacy(layer):
        c = next(c for c in layer["claims"] if c["id"] == ids["call"])
        c["repairs"] = [{"round": n, "action": "anchor", "at": "2026-01-01T00:00:00Z", "check_note": "old",
                         "text": c["text"], "anchors": ["engine.py:14-14"]} for n in (1, 2)]
    w.store.update("map", legacy)
    for n in (1, 2):
        out = repair_and_reject(w, ids, P1, n, f"round {n}")
        assert out["rounds"] == {ids["call"]: n}, out
    reps = claim_of(w, ids["call"])["repairs"]
    assert [(r.get("pass"), r["round"]) for r in reps] == [(None, 1), (None, 2), (P1, 1), (P1, 2)]


def test_pass_and_round_are_required(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    before = json.dumps(w.store.load("map"), sort_keys=True)
    for bad in ({}, {"pass": P1}, {"round": 1}, {"pass": "1", "round": 1}, {"pass": P1, "round": 3},
                {"pass": P1, "round": 0}, {"pass": P1, "round": True}, {"pass": P1, "round": "1"}):
        code, out = w.call("claims", "repair", data={**bad, "repairs": widen_call(ids)})
        assert code == 1 and out["error"]["code"] == "bad_input", (bad, out)
    assert json.dumps(w.store.load("map"), sort_keys=True) == before


def test_repair_pass_mints_unique_ids_and_flags_carry_them(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    minted = set()
    for _ in range(20):
        code, out = w.call("claims", "repair-pass")
        assert code == 0 and PASS_ID.fullmatch(out["pass"]), out
        minted.add(out["pass"])
    assert len(minted) == 20
    pid = minted.pop()
    f = tmp_path / "repair-1.json"
    f.write_text(json.dumps({"repairs": widen_call(ids)}), encoding="utf-8")
    code, out = w.call("claims", "repair", "--input", str(f), "--pass", pid, "--round", "1")
    assert code == 0 and out["pass"] == pid and out["round"] == 1, out
    assert claim_of(w, ids["call"])["repairs"][0]["pass"] == pid


def test_supported_claims_are_not_repaired(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    w.call("verdict", "set", "--id", ids["call"], "--verdict", "supported")
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [{"claim": ids["call"], "action": "retire", "reason": "x"}]})
    assert code == 1 and "check is supported" in out["error"]["details"][0]


# -- plain flags: no quoted JSON on a command line ---------------------------------------------------------------------


def test_activity_question_and_verdict_flags(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    code, out = w.call("activity", "start", "--agent", "cartographer", "--status", "Repairing 2 claims")
    assert code == 0, out
    entry = out["entry"]
    assert entry["agent"] == "cartographer" and entry["status"] == "Repairing 2 claims" and entry["question"] is None
    code, out = w.call("activity", "update", "--id", entry["id"], "--status", "Re-checking 2")
    assert code == 0 and out["entry"]["status"] == "Re-checking 2"
    code, out = w.call("activity", "finish", "--id", entry["id"], "--state", "done")
    assert code == 0 and out["entry"]["state"] == "done"

    q = inbox.post_question(w.store, {"text": "why?"})
    code, out = w.call("question", "claim", "--id", q["id"], "--agent", "guide")
    assert code == 0 and out["question"]["status"] == "investigating"
    code, out = w.call("activity", "start", "--agent", "investigator", "--question", q["id"], "--status", "Looking into it")
    assert code == 0 and out["entry"]["question"] == q["id"]
    code, out = w.call("question", "show", "--id", q["id"])
    assert code == 0 and out["question"]["text"] == "why?"
    code, out = w.call("question", "fail", "--id", q["id"], "--reason", "the tools failed")
    assert code == 0 and out["question"]["status"] == "failed"

    note = tmp_path / "note.txt"
    note.write_text("cites `generate`'s def; the \"loop\" is lines 9-10\n", encoding="utf-8")
    code, out = w.call("verdict", "set", "--id", ids["gen"], "--verdict", "not_supported", "--note-file", str(note))
    assert code == 0, out
    assert claim_of(w, ids["gen"])["check_note"] == "cites `generate`'s def; the \"loop\" is lines 9-10"


def test_flags_never_read_stdin_and_override_input(tmp_path, monkeypatch):
    w, ids = flagged_world(tmp_path, monkeypatch)
    # data on stdin is ignored when flags are given
    code, out = w.call("activity", "start", "--agent", "checker", "--status", "from flags",
                       data={"agent": "tracer", "status": "from stdin"})
    assert code == 0 and out["entry"]["agent"] == "checker" and out["entry"]["status"] == "from flags"
    # --input FILE, with a flag over it
    f = tmp_path / "in.json"
    f.write_text(json.dumps({"agent": "tracer", "status": "from file"}), encoding="utf-8")
    code, out = w.call("activity", "start", "--input", str(f), "--status", "flag wins")
    assert code == 0 and out["entry"]["agent"] == "tracer" and out["entry"]["status"] == "flag wins"
    code, out = w.call("preview", "--claim", ids["call"], "--anchor", "0", "--context", "1")
    assert code == 0 and any(line["cited"] for line in out["lines"])
    code, out = w.call("anchor", "resolve", "--path", "engine.py", "--anchor", "def sample(engine, prompt):")
    assert code == 0 and out["results"][0]["status"] == "found"
    code, out = w.call("claims", "retire", "--id", ids["gen"], "--reason", "by hand")
    assert code == 0 and out["retired"] == [ids["gen"]]


def test_drafts_dir_per_agent(tmp_path, monkeypatch):
    w, _ = flagged_world(tmp_path, monkeypatch)
    code, out = w.call("drafts", "dir", "--agent", "checker")
    assert code == 0, out
    d = out["dir"]
    assert d.endswith("/drafts/checker") and str(w.store.dir) in d
    p = Path(d)
    (p / "verdicts-1.json").write_text("{}")
    (p / "note.txt").write_text("x")
    (p / "keep.md").write_text("x")
    code, out = w.call("drafts", "dir", "--agent", "checker", "--fresh")
    assert sorted(f.name for f in p.iterdir()) == ["keep.md"]
    code, out = w.call("drafts", "dir", "--agent", "investigator", "--name", "q_0123abcd")
    assert code == 0 and out["dir"].endswith("/drafts/investigator/q_0123abcd")
    for bad in (["--agent", "nobody"], ["--agent", "checker", "--name", "../up"]):
        code, out = w.call("drafts", "dir", *bad)
        assert code == 1 and out["error"]["code"] == "bad_input"


@pytest.mark.parametrize("argv", [["verdict", "set", "--input", "/nonexistent/x.json"],
                                  ["verdict", "set", "--id", "c_x", "--verdict", "supported", "--note-file", "/nonexistent"]])
def test_unreadable_input_files_are_bad_input(tmp_path, monkeypatch, argv):
    w, _ = flagged_world(tmp_path, monkeypatch)
    code, out = w.call(*argv)
    assert code == 1 and out["error"]["code"] == "bad_input"

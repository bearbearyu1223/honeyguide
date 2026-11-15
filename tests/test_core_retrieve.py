"""Retrieval: anchor overlap first, keywords only as a fallback, stale claims and private notes held back."""

from __future__ import annotations

from honeyguide.retrieve import Context, keywords, retrieve
from honeyguide.store import empty_layer, make_claim


def anchor(path, start, end, symbol=None):
    a = {"path": path, "anchor": "x", "start": start, "end": end, "commit": "c" * 40, "hash": "h"}
    if symbol:
        a["symbol"] = symbol
    return a


def layers():
    m, ans, notes = empty_layer("map"), empty_layer("answers"), empty_layer("notes")
    run = make_claim("Agent.run loops over steps", "read_in_source", [anchor("agents.py", 10, 30, "Agent.run")])
    step = make_claim("step calls the model", "read_in_source", [anchor("agents.py", 40, 50, "Agent.step")])
    tools = make_claim("tools are validated on load", "read_in_source", [anchor("tools.py", 5, 9, "load")])
    stale = make_claim("run retries three times", "read_in_source", [anchor("agents.py", 12, 14, "Agent.run")],
                       freshness="stale")
    wrong = make_claim("run is async", "inferred", [anchor("agents.py", 10, 11, "Agent.run")],
                       check="not_supported")
    m["claims"] = [run, step, tools, stale, wrong]
    q = {"id": "q_1", "kind": "question", "text": "what does step return?", "anchor": None, "parent_response": None}
    ans["questions"] = [q]
    answer_claim = make_claim("step returns an ActionStep", "read_in_source",
                              [anchor("agents.py", 45, 47, "Agent.step")])
    ans["responses"] = [{"id": "r_1", "parent": "q_1", "agent": "investigator", "text": "an ActionStep",
                         "claims": [answer_claim], "generation": {}}]
    notes["notes"] = [
        {"id": "n_1", "kind": "note", "text": "step is where the model is called", "anchor": None,
         "share_with_agents": False},
        {"id": "n_2", "kind": "note", "text": "step is the hot path", "anchor": {"doc": "answer:r_1"},
         "share_with_agents": True},
    ]
    return m, ans, notes, {"run": run, "step": step, "tools": tools, "stale": stale, "wrong": wrong}


def test_line_overlap_beats_same_file():
    m, ans, notes, c = layers()
    got = retrieve(m, ans, notes, Context(anchors=[anchor("agents.py", 44, 46)]))
    assert [h.claim["id"] for h in got.map_claims] == [c["step"]["id"], c["run"]["id"]]
    assert got.map_claims[0].score == 3 and got.map_claims[1].score == 1
    assert [a["response"]["id"] for a in got.answers] == ["r_1"]


def test_stale_and_unsupported_excluded_unless_asked_then_marked():
    m, ans, notes, c = layers()
    ctx = Context(anchors=[anchor("agents.py", 12, 12)])
    ids = {h.claim["id"] for h in retrieve(m, ans, notes, ctx).map_claims}
    assert c["stale"]["id"] not in ids and c["wrong"]["id"] not in ids and c["run"]["id"] in ids
    marked = {h.claim["id"]: h.marked for h in retrieve(m, ans, notes, ctx, include_stale=True).map_claims}
    assert marked[c["stale"]["id"]] == "stale" and marked[c["wrong"]["id"]] == "not_supported"
    assert marked[c["run"]["id"]] is None


def test_selection_claims_and_mentioned_symbols_and_paths():
    m, ans, notes, c = layers()
    by_claim = retrieve(m, ans, notes, Context(claim_ids=[c["tools"]["id"]]))
    assert [h.claim["id"] for h in by_claim.map_claims] == [c["tools"]["id"]]
    by_symbol = retrieve(m, ans, notes, Context(symbols=["step"]))
    assert c["step"]["id"] in {h.claim["id"] for h in by_symbol.map_claims}
    by_path = retrieve(m, ans, notes, Context(paths=["tools.py"]))
    assert [h.claim["id"] for h in by_path.map_claims] == [c["tools"]["id"]]


def test_keyword_fallback_only_without_anchor_hits():
    m, ans, notes, c = layers()
    got = retrieve(m, ans, notes, Context(text="How are tools validated?"))
    assert [h.claim["id"] for h in got.map_claims] == [c["tools"]["id"]]
    assert got.map_claims[0].reasons[0].startswith("keywords")
    anchored = retrieve(m, ans, notes, Context(text="tools validated", anchors=[anchor("agents.py", 41, 41)]))
    assert c["tools"]["id"] not in {h.claim["id"] for h in anchored.map_claims}


def test_private_notes_never_returned():
    m, ans, notes, c = layers()
    got = retrieve(m, ans, notes, Context(text="where is step called", anchors=[anchor("agents.py", 45, 45)]))
    assert [n["id"] for n in got.notes] == ["n_2"]
    notes["notes"][1]["share_with_agents"] = "yes"  # only a real True shares
    assert retrieve(m, ans, notes, Context(text="step", anchors=[anchor("agents.py", 45, 45)])).notes == []


def test_keywords():
    assert keywords("What does Agent.run_step call?") == {"agent.run_step", "agent", "run_step"}

"""T7.16: answers get the repair pass (``claims repair --response``), the Checker's status counts the real claims, and
an answer whose claim spans are two sentences reads with a space between them."""

from __future__ import annotations

import json

from test_t7_fixtures import World, a_map

from honeyguide import inbox
from honeyguide.mapdoc import space_sentences, spans_text, text_revision
from honeyguide.repair import MAX_ROUNDS

P1, P2 = "p_0000000000a1", "p_0000000000b2"

GEN = {"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"}
CALL = {"path": "engine.py", "anchor": "return list(engine.generate(prompt))"}


def answered(tmp_path, monkeypatch, agent="tracer"):
    """The toy map saved; one question answered by ``agent`` in two sentences (two claim spans, no glue between
    them, as the live Tracer wrote them), three claims, two of them flagged by the Checker."""
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data=a_map())
    assert code == 0, out
    q = inbox.post_question(w.store, {"text": "what does sample do?"})
    data = {"question": q["id"], "agent": agent,
            "spans": [{"text": "sample collects what Engine.generate yields.", "claim": "s1"},
                      {"text": "The generator yields three times, once per loop step.", "claim": "s2"}],
            "claims": [{"key": "s1", "text": "sample collects what Engine.generate yields", "evidence": "read_in_source",
                        "anchors": [CALL]},
                       {"key": "s2", "text": "the generator yields three times, once per loop step",
                        "evidence": "read_in_source", "anchors": [{"path": "engine.py", "anchor": "def generate(self, tokens):"}]},
                       {"key": "s3", "text": "Engine stores its model", "evidence": "read_in_source",
                        "anchors": [{"path": "engine.py", "anchor": "self.model = model"}]}]}
    if agent == "tracer":
        data["path"] = {"id": "p1", "title": "sample()", "lanes": [{"id": "e", "label": "engine.py", "path": "engine.py"}],
                        "hops": [{"from": "e", "to": "e", "call": "engine.generate(prompt)", "trace": "unseen", "claim": "s1"},
                                 {"from": "e", "to": "e", "call": "self.model(tokens)", "trace": "unseen", "claim": "s2"},
                                 {"from": "e", "to": "e", "call": "Engine(model)", "trace": "unseen", "claim": "s3"}]}
    code, out = w.call("answer", "record", data=data)
    assert code == 0, out
    r = out["response"]
    ids = {c["key"]: c["id"] for c in r["claims"]}
    code, out = w.call("verdict", "set", data={"verdicts": [
        {"claim": ids["s1"], "verdict": "supported"},
        {"claim": ids["s2"], "verdict": "not_supported", "note": "the def line shows no loop; the loop is the next line"},
        {"claim": ids["s3"], "verdict": "not_supported", "note": "true, but cite the __init__ too"}]})
    assert code == 0, out
    return w, q, r, ids


def response(w, rid):
    return next(r for r in w.store.load("answers")["responses"] if r["id"] == rid)


# -- 3. two sentences, one space ---------------------------------------------------------------------------------------


def test_two_sentence_answer_gets_a_space(tmp_path, monkeypatch):
    w, q, r, ids = answered(tmp_path, monkeypatch)
    assert r["text"] == ("sample collects what Engine.generate yields. "
                         "The generator yields three times, once per loop step.")
    assert [s.get("claim") for s in r["spans"]] == [ids["s1"], None, ids["s2"]] and r["spans"][1] == {"text": " "}
    assert r["revision"] == text_revision(r["text"])
    # the anchor a follow-up selects is still exact: offsets index the stored text
    text, rev, ranges = inbox.document_text(w.store, f"answer:{r['id']}")
    assert text == r["text"] and [t[2] for t in ranges if t[2]] == [ids["s1"], ids["s2"]]


def test_space_sentences_only_where_a_sentence_meets_a_word():
    def joined(*texts):
        return spans_text(space_sentences([{"text": t} for t in texts]))
    assert joined("ends here.", "Starts here.") == "ends here. Starts here."
    assert joined("see `x.y`.", "`z` next") == "see `x.y`. `z` next"
    assert joined('it says "stop."', "Then") == 'it says "stop." Then'
    assert joined("really?", "(yes)") == "really? (yes)"
    for a, b in [("ends here. ", "Next"), ("ends here.", " Next"), ("calls f", ".")]:
        assert joined(a, b) == a + b                              # already spaced, or glue punctuation
    assert joined("x = 1.", "5") == "x = 1. 5"                     # a digit starts a word too
    assert joined("in gpt.py", "") == "in gpt.py"


# -- 2. the repair pass on an answer -----------------------------------------------------------------------------------


def test_claims_list_scopes_the_flagged_answer_claims(tmp_path, monkeypatch):
    w, q, r, ids = answered(tmp_path, monkeypatch)
    code, out = w.call("claims", "list", "--responses", r["id"], "--check", "not_supported", "--freshness", "current")
    assert code == 0 and {c["id"] for c in out["claims"]} == {ids["s2"], ids["s3"]}
    assert all(c["response"] == r["id"] for c in out["claims"])


def test_repair_an_answer_keeps_ids_resets_the_check_and_rewrites_its_spans(tmp_path, monkeypatch):
    w, q, r, ids = answered(tmp_path, monkeypatch)
    map_before = json.dumps(w.store.load("map"), sort_keys=True)
    f = tmp_path / "repair-1.json"
    f.write_text(json.dumps({"pass": P1, "round": 1, "repairs": [
        {"claim": ids["s2"], "action": "rewrite", "text": "the generator yields once per loop step",
         "span": "The generator yields once per loop step.", "anchors": [GEN]},
        {"claim": ids["s3"], "action": "anchor",
         "anchors": [{"path": "engine.py", "anchor": "def __init__(self, model):", "extent": "block"}]}]}))
    code, out = w.call("claims", "repair", "--response", r["id"], "--input", str(f))
    assert code == 0, out
    assert sorted(out["changed"]) == sorted([ids["s2"], ids["s3"]]) and out["retired"] == []
    assert out["response"] == r["id"] and out["spans_rewritten"] == 1 and out["still_not_supported"] == 0
    assert out["rounds"] == {ids["s2"]: 1, ids["s3"]: 1}
    after = response(w, r["id"])
    by = {c["id"]: c for c in after["claims"]}
    assert by[ids["s2"]]["text"] == "the generator yields once per loop step" and by[ids["s2"]]["check"] == "unchecked"
    assert by[ids["s2"]]["anchors"][0]["end"] > by[ids["s2"]]["anchors"][0]["start"]          # the block now
    assert by[ids["s3"]]["check"] == "unchecked" and by[ids["s3"]]["repairs"][0]["check_note"] == "true, but cite the __init__ too"
    assert by[ids["s1"]]["check"] == "supported" and "repairs" not in by[ids["s1"]]
    # the answer's text is its spans, with the sentence space kept; the revision follows; the path is untouched
    assert after["text"] == "sample collects what Engine.generate yields. The generator yields once per loop step."
    assert after["revision"] == text_revision(after["text"]) != r["revision"] and out["revision"] == after["revision"]
    assert after["path"] == r["path"]
    assert json.dumps(w.store.load("map"), sort_keys=True) == map_before            # the map is not touched
    # the Checker's re-check by ids sees exactly the changed claims
    code, out = w.call("claims", "list", "--ids", f"{ids['s2']},{ids['s3']}", "--check", "unchecked")
    assert out["count"] == 2 and {c["response"] for c in out["claims"]} == {r["id"]}


def test_repair_an_answer_refuses_other_claims_and_stops_after_two_rounds(tmp_path, monkeypatch):
    w, q, r, ids = answered(tmp_path, monkeypatch, agent="investigator")
    before = json.dumps(w.store.load("answers"), sort_keys=True)
    map_claim = w.store.load("map")["claims"][0]["id"]
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "response": r["id"], "repairs": [
        {"claim": map_claim, "action": "retire", "reason": "x"},
        {"claim": ids["s2"], "action": "rewrite", "text": "narrower"},           # shown by a span: needs span
        {"claim": ids["s1"], "action": "retire", "reason": "supported"}]})
    assert code == 1 and out["error"]["code"] == "not_found"
    details = " | ".join(out["error"]["details"])
    assert f"no such claim in answer {r['id']}" in details and "give span" in details
    assert "repair takes not_supported claims only" in details
    assert json.dumps(w.store.load("answers"), sort_keys=True) == before
    # a map repair can't reach an answer's claim, and an unknown answer is not_found
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "repairs": [{"claim": ids["s3"], "action": "retire", "reason": "x"}]})
    assert code == 1 and "no such map claim" in out["error"]["details"][0]
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "response": "r_000000000000",
                                                 "repairs": [{"claim": ids["s3"], "action": "retire", "reason": "x"}]})
    assert code == 1 and out["error"]["code"] == "not_found"
    # at most two rounds per pass, as on the map; the next pass gets its own two, recorded as rounds 1 and 2
    widen = {"response": r["id"], "repairs": [{"claim": ids["s3"], "action": "anchor",
                          "anchors": [{"path": "engine.py", "anchor": "def __init__(self, model):", "extent": "block"}]}]}
    for pid in (P1, P2):
        for n in range(1, MAX_ROUNDS + 1):
            code, out = w.call("claims", "repair", data={**widen, "pass": pid, "round": n})
            assert code == 0 and out["rounds"] == {ids["s3"]: n}, out
            code, out = w.call("verdict", "set", "--id", ids["s3"], "--verdict", "not_supported", "--note", f"round {n}")
            assert code == 0, out
        code, out = w.call("claims", "repair", data={**widen, "pass": pid, "round": MAX_ROUNDS})
        assert code == 1 and f"already repaired 2 times in pass {pid}" in out["error"]["details"][0]
    c = next(c for c in response(w, r["id"])["claims"] if c["id"] == ids["s3"])
    assert [(e["pass"], e["round"]) for e in c["repairs"]] == [(P1, 1), (P1, 2), (P2, 1), (P2, 2)]


def test_retire_an_answer_claim(tmp_path, monkeypatch):
    w, q, r, ids = answered(tmp_path, monkeypatch)
    code, out = w.call("claims", "repair", data={"pass": P1, "round": 1, "response": r["id"], "repairs": [
        {"claim": ids["s2"], "action": "retire", "reason": "the code yields once per step, not three times"}]})
    assert code == 0 and out["retired"] == [ids["s2"]] and out["spans_rewritten"] == 0
    c = next(c for c in response(w, r["id"])["claims"] if c["id"] == ids["s2"])
    assert c["freshness"] == "retired" and c["freshness_reason"].startswith("repair: the code yields")
    assert response(w, r["id"])["text"] == r["text"]                     # retiring changes no text


# -- 7. the Checker's status counts what it will check -----------------------------------------------------------------


def test_checker_count_is_the_claims_list_count(tmp_path, monkeypatch):
    """The Guide's "Checking N claims" is ``claims list``'s count for the scope, not the answer's span count."""
    w, q, r, ids = answered(tmp_path, monkeypatch)
    q2 = inbox.post_question(w.store, {"text": "and again?"})
    claims = [{"key": f"k{i}", "text": f"claim {i}", "evidence": "read_in_source", "anchors": [CALL]} for i in range(13)]
    spans = [{"text": "Thirteen claims. "}] + [{"text": f"claim {i}", "claim": f"k{i}"} for i in range(11)]
    code, out = w.call("answer", "record", data={"question": q2["id"], "agent": "tracer", "spans": spans,
                                                  "claims": claims + [{"key": "gk", "text": "background",
                                                                       "evidence": "general_knowledge"}]})
    assert code == 0, out
    rid = out["response"]["id"]
    code, out = w.call("claims", "list", "--responses", rid, "--check", "unchecked", "--freshness", "current")
    assert code == 0 and out["count"] == 14            # 13 + the general-knowledge claim: what the Checker is handed
    assert sum(1 for s in spans if s.get("claim")) == 11  # what counting the spans (or the hops) would have said

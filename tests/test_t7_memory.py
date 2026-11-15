"""Memory and refresh end to end (T7.5), through the CLI on throwaway repos: map at commit A -> code changes ->
refresh plan -> refresh apply -> the Checker's re-check -> the page's memory state. No stale or retired claim is
ever retrieved or shown as current."""

from __future__ import annotations

from test_t7_fixtures import ENGINE, World, a_map

from honeyguide import inbox, memory
from honeyguide.contract import load_side, update_side
from honeyguide.retrieve import Context, retrieve

ENGINE_B = (ENGINE.replace('"""Toy engine."""\n', '"""Toy engine."""\nimport os\n')
            .replace("range(3)", "range(4)") + "\n\ndef fresh():\n    return 3\n")


def mapped_world(tmp_path, monkeypatch):
    """World at A with the map saved and one answer (two claims: engine __init__, and cli.py)."""
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data=a_map())
    assert code == 0, out
    ids = {s["key"]: s["id"] for s in out["saved"]}
    q = inbox.post_question(w.store, {"text": "How is the engine built?"})
    code, out = w.call("answer", "record", data={
        "question": q["id"], "agent": "investigator", "text": "Engine keeps its model; main runs sample.",
        "claims": [
            {"key": "init", "text": "Engine keeps the model it is given", "evidence": "read_in_source",
             "anchors": [{"path": "engine.py", "anchor": "def __init__(self, model):", "extent": "block"}]},
            {"key": "main", "text": "main calls sample", "evidence": "read_in_source",
             "anchors": [{"path": "cli.py", "anchor": "return sample(Engine(len), [1, 2])"}]}]})
    assert code == 0, out
    response = out["response"]
    ids.update({c["key"]: c["id"] for c in response["claims"]})
    return w, ids, response["id"]


def change_code(w) -> str:
    """B: a line inserted above everything in engine.py, generate's body edited, a new function, cli.py gone."""
    w.git.write("engine.py", ENGINE_B)
    (w.root / "cli.py").unlink()
    return w.git.commit("B")


def claim(w, cid) -> dict:
    return next(c for c in memory.list_claims(w.store, {"ids": [cid]})["claims"])


def served_ids(w) -> set[str]:
    """Every claim retrieval would hand an agent for a question about engine.py or cli.py."""
    got = retrieve(w.store.load("map"), w.store.load("answers"), w.store.load("notes"),
                   Context(text="engine generate sample main", paths=["engine.py", "cli.py"]))
    return {h.claim["id"] for h in got.map_claims} | {h.claim["id"] for a in got.answers for h in a["hits"]}


def test_full_cycle(tmp_path, monkeypatch):
    w, ids, rid = mapped_world(tmp_path, monkeypatch)
    a = w.commit
    code, state = w.call("memory", "state")
    assert code == 0 and state["state"] == "up_to_date" and state["headline"] == f"Up to date at {a[:12]}"

    b = change_code(w)
    code, state = w.call("memory", "state")
    assert state["state"] == "behind" and state["map_commit"] == a and state["head"] == b

    # The dry run and the apply agree; the apply moves the map's commit and logs the refresh.
    code, plan = w.call("refresh-plan", "--json")
    assert code == 0
    states = {c["id"]: c["state"] for c in plan["claims"]}
    assert states == {ids["gen"]: "stale", ids["call"]: "moved", ids["gk"]: "unanchored",
                      ids["init"]: "moved", ids["main"]: "retired"}
    code, out = w.call("refresh", "apply", data={"note": "after B"})
    assert code == 0, out
    assert out["ok"] and out["applied"] and out["previous_commit"] == a and out["target"] == b
    assert {c["id"]: c["state"] for c in out["claims"]} == states
    assert out["counts"] == {"unchanged": 0, "moved": 2, "stale": 1, "retired": 1, "unanchored": 1}
    assert "fresh" in {u["qualname"] for u in out["uncovered"]}
    assert w.store.load("map")["commit"] == b
    log = load_side(w.store, "session")["refresh_log"]
    assert [(e["base"], e["target"], e["counts"]["stale"], e["note"]) for e in log] == [(a, b, 1, "after B")]

    gen = claim(w, ids["gen"])
    assert gen["freshness"] == "stale" and gen["check"] == "unchecked" and gen["anchors"][0]["commit"] == a
    assert gen["candidates"][0]["symbol"] == "Engine.generate" and gen["candidates"][0]["hash"]
    call = claim(w, ids["call"])
    assert call["freshness"] == "current" and call["anchors"][0]["commit"] == b
    assert call["anchors"][0]["start"] == 15                       # one line lower
    assert claim(w, ids["main"])["freshness"] == "retired"

    # The page: refreshing until the Checker has re-checked the one stale claim.
    code, state = w.call("memory", "state")
    assert state["state"] == "refreshing" and state["awaiting_recheck"] == 1
    assert state["headline"] == "Refreshing · 1 claim being re-checked"
    assert state["freshness"] == {"current": 3, "stale": 1, "retired": 1}
    assert state["last_refresh"]["target"] == b

    # Never served as fact: stale and retired claims are not retrieved (only marked, when asked for).
    served = served_ids(w)
    assert ids["gen"] not in served and ids["main"] not in served and ids["call"] in served
    marked = retrieve(w.store.load("map"), w.store.load("answers"), w.store.load("notes"),
                      Context(paths=["engine.py"]), include_stale=True)
    assert {h.claim["id"]: h.marked for h in marked.map_claims}[ids["gen"]] == "stale"

    # The Checker's queue: stale and unchecked, claim text and anchors, no notes.
    code, queue = w.call("claims", "list", data={"freshness": "stale", "check": "unchecked"})
    assert code == 0 and [c["id"] for c in queue["claims"]] == [ids["gen"]]
    assert set(queue) == {"ok", "claims", "count"} and queue["claims"][0]["response"] is None

    # A visit before the re-check, so the page can say "1 re-checked since your last visit".
    update_side(w.store, "session", lambda d: d.update(previous_visit="2000-01-01T00:00:00Z",
                                                        last_visit="2000-01-01T00:00:00Z"))
    w.call("verdict", "set", data={"claim": ids["call"], "verdict": "supported"})

    # supported on a stale claim needs the anchor where it holds now; that makes it current at B.
    code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported"})
    assert code == 1 and out["error"]["code"] == "validation_failed"
    assert claim(w, ids["gen"])["freshness"] == "stale"
    code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported", "anchors": [
        {"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"}]})
    assert code == 0 and out["current_again"] == [ids["gen"]], out
    gen = claim(w, ids["gen"])
    assert gen["freshness"] == "current" and gen["check"] == "supported" and "candidates" not in gen
    assert gen["anchors"][0]["commit"] == b and (gen["anchors"][0]["start"], gen["anchors"][0]["end"]) == (9, 11)

    code, state = w.call("memory", "state")
    assert state["state"] == "up_to_date" and state["headline"] == f"Up to date at {b[:12]}"
    assert state["rechecked_since_visit"] == 1 and state["checked_since_visit"] == 2
    assert ids["gen"] in served_ids(w)

    # Nothing left to do: a second plan and apply change nothing.
    code, out = w.call("refresh", "apply", data={})
    assert out["counts"] == {"unchanged": 3, "moved": 0, "stale": 0, "retired": 0, "unanchored": 1}  # retired: skipped
    assert out["uncovered"] == [] and claim(w, ids["gen"])["check"] == "supported"


def test_stale_not_supported_stays_stale_and_keeps_its_verdict_until_the_code_moves(tmp_path, monkeypatch):
    w, ids, _ = mapped_world(tmp_path, monkeypatch)
    change_code(w)
    w.call("refresh", "apply", data={})
    code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "not_supported",
                                                "note": "now yields four"})
    assert code == 0 and out["current_again"] == []
    gen = claim(w, ids["gen"])
    assert gen["freshness"] == "stale" and gen["check"] == "not_supported" and gen["rechecked_at"]
    assert ids["gen"] not in served_ids(w)
    code, state = w.call("memory", "state")
    assert state["state"] == "up_to_date" and state["stale_not_supported"] == 1 and state["awaiting_recheck"] == 0

    # An unrelated commit: the candidate lines are the same, so the verdict stands.
    w.git.write("README.md", "toy\n")
    w.git.commit("C")
    w.call("refresh", "apply", data={})
    assert claim(w, ids["gen"])["check"] == "not_supported"
    # The candidate lines change: it waits for a re-check again.
    w.git.write("engine.py", ENGINE_B.replace("range(4)", "range(5)"))
    w.git.commit("D")
    w.call("refresh", "apply", data={})
    gen = claim(w, ids["gen"])
    assert gen["freshness"] == "stale" and gen["check"] == "unchecked"


def test_verdict_rules_on_stale_retired_and_current(tmp_path, monkeypatch):
    w, ids, _ = mapped_world(tmp_path, monkeypatch)
    change_code(w)
    w.call("refresh", "apply", data={})
    good = [{"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"}]
    bad = [
        ({"claim": ids["main"], "verdict": "supported"}, "retired"),
        ({"claim": ids["gen"], "verdict": "skipped"}, "re-check it"),
        ({"claim": ids["gen"], "verdict": "not_supported", "anchors": good}, "supported only"),
        ({"claim": ids["call"], "verdict": "supported", "anchors": good}, "only for re-checking"),
    ]
    for item, why in bad:
        code, out = w.call("verdict", "set", data=item)
        assert code == 1 and why in " ".join(out["error"]["details"]), out
    # A batch with one bad item writes nothing.
    code, out = w.call("verdict", "set", data={"verdicts": [
        {"claim": ids["init"], "verdict": "supported"}, {"claim": ids["main"], "verdict": "supported"}]})
    assert code == 1 and claim(w, ids["init"])["check"] == "unchecked"
    # Anchors that don't resolve, or point at a secret, are refused before anything is written.
    code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported",
                                                "anchors": [{"path": "engine.py", "anchor": "no such line"}]})
    assert code == 1 and out["error"]["code"] == "validation_failed"
    code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported",
                                                "anchors": [{"path": ".env", "anchor": "API_TOKEN"}]})
    assert code == 1 and out["error"]["code"] == "secret_refused"
    # Re-running the successful re-check (a retry after a crash) is accepted and changes nothing.
    for _ in range(2):
        code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported", "anchors": good})
        assert code == 0, out
    assert claim(w, ids["gen"])["freshness"] == "current"


def test_retire_keeps_the_claim_and_never_serves_it(tmp_path, monkeypatch):
    w, ids, _ = mapped_world(tmp_path, monkeypatch)
    code, out = w.call("claims", "retire", data={"claims": [ids["call"], "c_nope"], "reason": "x"})
    assert code == 1 and out["error"]["code"] == "not_found"
    assert claim(w, ids["call"])["freshness"] == "current"           # nothing written
    code, out = w.call("claims", "retire", data={"claims": [ids["call"], ids["init"]], "reason": "superseded"})
    assert code == 0 and sorted(out["retired"]) == sorted([ids["call"], ids["init"]])
    code, out = w.call("claims", "retire", data={"claim": ids["call"], "reason": "again"})
    assert out["retired"] == [] and out["already_retired"] == [ids["call"]]
    c = claim(w, ids["call"])
    assert (c["freshness"], c["freshness_reason"]) == ("retired", "superseded") and c["retired_at"]
    assert ids["call"] not in served_ids(w) and ids["init"] not in served_ids(w)
    # Retired claims are skipped by refresh and take no verdict.
    change_code(w)
    code, out = w.call("refresh", "apply", data={})
    assert ids["call"] not in {c["id"] for c in out["claims"]}
    code, listed = w.call("claims", "list", data={"scope": "map", "freshness": "retired"})
    assert [c["id"] for c in listed["claims"]] == [ids["call"]]


def test_claims_save_add_retires_the_claims_it_replaces_in_the_same_write(tmp_path, monkeypatch):
    w, ids, _ = mapped_world(tmp_path, monkeypatch)
    change_code(w)
    w.call("refresh", "apply", data={})
    doc = w.store.load("map")["document"]
    spans = doc["sections"][0]["blocks"][0]["spans"]
    spans[1] = {"text": "yields four outputs", "claim": "gen4"}
    draft = {"target": "map", "mode": "add", "document": doc,
             "claims": [{"key": "gen4", "text": "Engine.generate yields four outputs", "evidence": "read_in_source",
                         "anchors": [{"path": "engine.py", "anchor": "for _ in range(4):"}]}],
             "retire": [{"claim": ids["gen"], "reason": "rewritten after refresh"}]}
    bad = {**draft, "retire": [{"claim": "c_nope", "reason": "x"}]}
    code, out = w.call("claims", "save", data=bad)
    assert code == 1 and out["error"]["code"] == "not_found"
    code, out = w.call("claims", "save", data=draft)
    assert code == 0, out
    assert out["retired"] == [ids["gen"]] and out["warnings"] == []   # no "not shown" warning for retired
    assert claim(w, ids["gen"])["freshness"] == "retired"
    code, state = w.call("memory", "state")
    assert state["state"] == "up_to_date" and state["awaiting_recheck"] == 0
    code, out = w.call("map", "validate")
    assert out["valid"] and out["warnings"] == []


def test_claims_list_filters(tmp_path, monkeypatch):
    w, ids, rid = mapped_world(tmp_path, monkeypatch)
    n = lambda **d: [c["id"] for c in w.call("claims", "list", data=d)[1]["claims"]]  # noqa: E731
    assert n(scope="map") == [ids["gen"], ids["call"], ids["gk"]]
    assert n(scope="answers") == n(responses=[rid]) == [ids["init"], ids["main"]]
    assert len(n()) == 5
    assert n(check=["unchecked"], scope="map") == [ids["gen"], ids["call"], ids["gk"]]
    for bad in ({"scope": "everything"}, {"check": "maybe"}, {"freshness": []}, {"scope": "map", "responses": [rid]}):
        code, out = w.call("claims", "list", data=bad)
        assert code == 1 and out["error"]["code"] == "bad_input", bad
    code, out = w.call("claims", "list", data={"responses": ["r_nope"]})
    assert code == 1 and out["error"]["code"] == "not_found"


def test_refresh_apply_plans_from_what_it_rewrites(tmp_path, monkeypatch):
    """A verdict recorded while a refresh is being planned is not lost: the locked pass re-plans from the saved
    claims, so a stale claim the Checker just re-anchored is not marked stale again."""
    w, ids, _ = mapped_world(tmp_path, monkeypatch)
    change_code(w)
    w.call("refresh", "apply", data={})
    w.git.write("README.md", "toy\n")
    c = w.git.commit("C")
    real = memory.plan_refresh
    calls = []

    def plan_then_checker_writes(*args, **kwargs):
        plan = real(*args, **kwargs)
        if not calls:  # the warm-up pass, outside the lock: the Checker re-checks gen meanwhile
            code, out = w.call("verdict", "set", data={"claim": ids["gen"], "verdict": "supported", "anchors": [
                {"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"}]})
            assert code == 0, out
        calls.append(plan)
        return plan

    monkeypatch.setattr(memory, "plan_refresh", plan_then_checker_writes)
    code, out = w.call("refresh", "apply", data={})
    assert code == 0 and len(calls) == 2
    gen = claim(w, ids["gen"])
    assert (gen["freshness"], gen["check"], gen["anchors"][0]["commit"]) == ("current", "supported", c)
    assert {x["id"]: x["state"] for x in out["claims"]}[ids["gen"]] == "unchanged"


def test_refresh_apply_errors(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("refresh", "apply", data={})
    assert code == 1 and out["error"]["code"] == "not_found"
    w.call("claims", "save", data=a_map())
    code, out = w.call("refresh", "apply", data={"to": "no-such-rev"})
    assert code == 1 and out["error"]["code"] == "not_found"
    # A dirty tree: applied against HEAD with a warning.
    (w.root / "engine.py").write_text(ENGINE_B)
    code, out = w.call("refresh", "apply", data={})
    assert code == 0 and out["warnings"] and "uncommitted" in out["warnings"][0]
    assert out["counts"]["stale"] == 0


def test_status_shows_the_memory_state(tmp_path, monkeypatch, capsys):
    from honeyguide.cli import main
    w, _, _ = mapped_world(tmp_path, monkeypatch)
    b = change_code(w)
    code, out = w.call("status", "--json")
    assert code == 0 and out["memory_state"]["state"] == "behind" and out["memory"].endswith(w.store.repo_id)
    w.call("refresh", "apply", data={})
    capsys.readouterr()
    assert main(["status", "--repo", str(w.root)]) == 0
    text = capsys.readouterr().out
    assert "state        Refreshing · 1 claim being re-checked" in text and f"{b[:12]}  (up to date)" in text

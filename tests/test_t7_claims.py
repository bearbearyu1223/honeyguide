"""Anchor resolution, claims save, the map validator, verdicts and the secret guard, through the CLI."""

from __future__ import annotations

import json

from test_t7_fixtures import World, a_map

from honeyguide.guard import check_secret, secret_path
from honeyguide.mapdoc import claims_in, plain_text, span_ranges


def test_anchor_resolve_found_ambiguous_secret(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("anchor", "resolve", data={"anchors": [
        {"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"},
        {"path": "engine.py", "anchor": "self.model"},
        {"path": "engine.py", "anchor": "no such text"},
        {"path": ".env", "anchor": "API_TOKEN"},
        {"path": "config.py", "anchor": "AWS_KEY"},
        {"path": "../etc/passwd", "anchor": "root"}]})
    assert code == 0
    found, ambiguous, missing, env, key, bad = out["results"]
    assert found["status"] == "found" and found["anchor"]["start"] == 8 and found["anchor"]["end"] == 10
    assert found["anchor"]["symbol"] == "Engine.generate" and found["anchor"]["commit"] == w.commit
    assert found["links"]["vscode"].endswith("engine.py:8:1") and found["links"]["github"] is None
    assert found["links"]["github_title"] == f"pinned to {w.commit[:12]}, lines 8-10"
    assert ambiguous["status"] == "ambiguous" and ambiguous["candidates"] == [6, 10]
    assert missing["status"] == "not_found"
    assert env["status"] == "secret" and key["status"] == "secret" and bad["status"] == "bad_input"


def test_claims_save_resolves_and_maps_keys(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data=a_map())
    assert code == 0, out
    ids = {s["key"]: s["id"] for s in out["saved"]}
    layer = w.store.load("map")
    assert layer["commit"] == w.commit and len(layer["claims"]) == 3
    doc = layer["document"]
    assert doc["revision"] == out["revision"]
    spans = doc["sections"][0]["blocks"][0]["spans"]
    assert spans[1]["claim"] == ids["gen"] and doc["flows"][0]["hops"][0]["claim"] == ids["call"]
    # Offsets in the plain text find the claims under a selection.
    text = plain_text(doc)
    start = text.index("yields three")
    assert claims_in(span_ranges(doc), start, start + 5) == [ids["gen"]]
    assert text.startswith("Overview\n\nThe engine yields three outputs; generators are lazy.\n\nFlows")
    code, out = w.call("map", "validate")
    assert code == 0 and out["valid"] and out["errors"] == [] and out["warnings"] == []


def test_claims_save_rejects_everything_at_once_and_writes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    bad = a_map()
    bad["claims"][0]["anchors"] = []                                   # anchored label, no anchor
    bad["claims"][1]["anchors"][0]["anchor"] = "self.model"           # ambiguous
    bad["claims"][2]["anchors"] = [{"path": "engine.py", "anchor": "class Engine:"}]  # general knowledge + anchor
    bad["document"]["sections"][0]["blocks"][0]["spans"].append({"text": "x", "claim": "nope"})
    code, out = w.call("claims", "save", data=bad)
    assert code == 1 and out["error"]["code"] == "validation_failed"
    details = "\n".join(out["error"]["details"])
    assert "needs at least one code anchor" in details and "ambiguous" in details
    assert "general_knowledge claims cite no code" in details
    assert w.store.load("map")["claims"] == []


def test_validator_rejects_unanchored_and_tampered_claims(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert w.call("claims", "save", data=a_map())[0] == 0

    def tamper(data):
        data["claims"][0]["anchors"] = []                      # read_in_source with nothing cited
        data["claims"][1]["anchors"][0]["hash"] = "0" * 16     # lines don't match
    w.store.update("map", tamper)
    code, out = w.call("map", "validate")
    assert code == 0 and not out["valid"]
    joined = "\n".join(out["errors"])
    assert "read_in_source needs at least one code anchor" in joined
    assert "don't match the saved hash" in joined
    # The draft form: searched_not_found needs no anchor and is valid.
    draft = a_map()
    draft["claims"][2] = {"key": "gk", "text": "No retry loop exists", "evidence": "searched_not_found",
                          "anchors": [], "searched": ["retry", "backoff"]}
    code, out = w.call("map", "validate", "--stdin", data=draft)
    assert code == 0 and out["valid"], out


def test_document_structure_errors(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    bad = a_map()
    flow = bad["document"]["flows"][0]
    flow["hops"].append({"from": "engine", "to": "nowhere", "call": "x()", "trace": "maybe"})
    bad["document"]["sections"][1]["blocks"][0]["flow"] = "p9"
    code, out = w.call("claims", "save", data=bad)
    assert code == 1
    details = "\n".join(out["error"]["details"])
    assert "to 'nowhere' is not a lane" in details and "trace must be one of" in details
    assert "every hop needs a claim" in details and "flow 'p9' is not in document.flows" in details


def test_add_mode_keeps_existing_claims(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.call("claims", "save", data=a_map())
    code, out = w.call("claims", "save", data={"target": "map", "mode": "add", "claims": [
        {"key": "init", "text": "Engine keeps its model", "evidence": "read_in_source",
         "anchors": [{"path": "engine.py", "anchor": "def __init__(self, model):"}]}]})
    assert code == 0 and len(w.store.load("map")["claims"]) == 4
    assert out["warnings"] == ["claim init is not shown by any span or hop"]


def test_secret_guard_on_claims_and_paths(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data={"target": "map", "mode": "replace", "document": a_map()["document"],
                                               "claims": [{"key": "k", "text": "the key", "evidence": "docs",
                                                           "anchors": [{"path": "config.py", "anchor": "AWS_KEY"}]}]})
    assert code == 1 and out["error"]["code"] == "secret_refused"
    assert "looks like a key or token" in out["error"]["details"][0]
    for path in (".env", "deploy/.env.production", "certs/server.pem", "home/.ssh/config", "id_ed25519",
                 ".aws/credentials", "gcp/service-account-prod.json", ".netrc", "secrets.yaml"):
        assert secret_path(path), path
    for path in (".env.example", "engine.py", "docs/keys.md", "src/secretary.py", "tokenizer.py"):
        assert secret_path(path) is None, path
    assert check_secret("a.py", ["x = 1", "-----BEGIN RSA PRIVATE KEY-----"], 10) == \
        "a.py: line 11 looks like a key or token"


def test_verdicts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    _, out = w.call("claims", "save", data=a_map())
    ids = {s["key"]: s["id"] for s in out["saved"]}
    code, out = w.call("verdict", "set", data={"verdicts": [
        {"claim": ids["gen"], "verdict": "supported"}, {"claim": ids["gk"], "verdict": "supported"}]})
    assert code == 1 and "general_knowledge claims are skipped" in out["error"]["details"][0]
    assert all(c["check"] == "unchecked" for c in w.store.load("map")["claims"])  # nothing was set
    code, out = w.call("verdict", "set", data={"claim": "c_000000000000", "verdict": "supported"})
    assert code == 1 and out["error"]["code"] == "not_found"
    code, out = w.call("verdict", "set", data={"verdicts": [
        {"claim": ids["gen"], "verdict": "not_supported", "note": "it yields 3, fine, but via the model"},
        {"claim": ids["gk"], "verdict": "skipped"}]})
    assert code == 0 and out["set"] == 2
    checks = {c["id"]: c for c in w.store.load("map")["claims"]}
    assert checks[ids["gen"]]["check"] == "not_supported" and checks[ids["gen"]]["check_note"]
    assert checks[ids["gk"]]["check"] == "skipped" and checks[ids["call"]]["check"] == "unchecked"


def test_preview(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    _, out = w.call("claims", "save", data=a_map())
    gen = out["saved"][0]["id"]
    code, out = w.call("preview", data={"claim": gen, "context": 1})
    assert code == 0 and out["hash_matches"] and out["start"] == 8
    assert [(row["n"], row["cited"]) for row in out["lines"]] == [(7, False), (8, True), (9, True), (10, True),
                                                                  (11, False)]
    code, out = w.call("preview", data={"path": ".env", "start": 1, "end": 1})
    assert code == 1 and out["error"]["code"] == "secret_refused"
    code, out = w.call("preview", data={"path": "config.py", "start": 2, "end": 2, "context": 3})
    assert code == 1 and out["error"]["code"] == "secret_refused"  # the context would show the key
    code, out = w.call("preview", data={"path": "engine.py", "start": 99, "end": 100})
    assert code == 1 and out["error"]["code"] == "bad_input"


def test_bad_json_input_is_a_json_error(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    f = tmp_path / "in.json"
    f.write_text("{not json")
    code, out = w.call("claims", "save", "--input", str(f))
    assert code == 1 and out["error"]["code"] == "bad_input"
    assert json.dumps(out)  # stdout held exactly one JSON object

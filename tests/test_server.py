"""The page server: same-origin and token checks, the JSON API, and posts landing in the inbox."""

from __future__ import annotations

import http.client
import json
import threading

import pytest
from test_contract_fixtures import World, a_map

from honeyguide import inbox
from honeyguide.mapdoc import plain_text
from honeyguide.server import make_server, server_token


@pytest.fixture
def served(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    server = make_server(w.repo, w.store, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    w.port = server.server_address[1]
    w.token = server_token(w.store)
    yield w
    server.shutdown()
    server.server_close()


def request(w, method: str, path: str, body=None, *, token: bool = True, headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", w.port, timeout=10)
    h = {"Host": f"127.0.0.1:{w.port}"}
    if token:
        h["X-Honeyguide-Token"] = w.token
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except json.JSONDecodeError:
        return resp.status, raw.decode()


def test_page_embeds_token_and_api_needs_it(served):
    w = served
    status, page = request(w, "GET", "/", token=False)
    assert status == 200 and w.token in page and w.store.repo_id in page
    assert request(w, "GET", "/api/state", token=False)[0] == 403
    assert request(w, "GET", "/api/state", token=False, headers={"X-Honeyguide-Token": "0" * 32})[0] == 403
    status, state = request(w, "GET", "/api/state")
    assert status == 200 and state["repo_id"] == w.store.repo_id and state["head"] == w.commit
    assert (w.store.dir / "server-token").stat().st_mode & 0o077 == 0


def test_cross_origin_and_foreign_host_posts_are_rejected(served):
    w = served
    q = {"text": "sneaky"}
    cases = [
        {"Origin": "https://evil.example"},
        {"Origin": "http://localhost:1"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "evil.example"},                                   # DNS rebinding
        {"Content-Type": "text/plain"},                             # a no-preflight form post
    ]
    for headers in cases:
        status, _ = request(w, "POST", "/api/question", q, headers=headers)
        assert status == 403, headers
    assert request(w, "POST", "/api/question", q, token=False)[0] == 403
    assert w.store.load("answers")["questions"] == []
    status, out = request(w, "POST", "/api/question", q, headers={"Origin": f"http://127.0.0.1:{w.port}",
                                                                  "Sec-Fetch-Site": "same-origin"})
    assert status == 200 and out["question"]["status"] == "open"


def test_posts_land_in_the_inbox(served):
    w = served
    w.call("claims", "save", data=a_map())
    doc = w.store.load("map")["document"]
    start = plain_text(doc).index("generators are lazy")
    anchor = {"doc": "map", "revision": doc["revision"], "quote": "generators are lazy", "start": start,
              "end": start + 19}
    status, out = request(w, "POST", "/api/question", {"text": "Lazy how?", "anchor": anchor})
    assert status == 200
    qid = out["question"]["id"]
    assert [q["id"] for q in inbox.inbox(w.store)["open"]] == [qid]
    assert request(w, "POST", "/api/question", {"text": "x", "parent_response": "r_1"})[0] == 400
    status, out = request(w, "POST", "/api/question", {"text": "x", "anchor": dict(anchor, revision="old")})
    assert status == 409
    _, rec = w.call("answer", "record", data={"question": qid, "agent": "investigator", "text": "Values on demand.",
                                              "claims": []})
    rid = rec["response"]["id"]
    fu = {"text": "Example?", "parent_response": rid,
          "anchor": {"doc": f"answer:{rid}", "revision": rec["response"]["revision"], "quote": "Values",
                     "start": 0, "end": 6}}
    status, out = request(w, "POST", "/api/follow-up", fu)
    assert status == 200 and out["question"]["parent_response"] == rid
    status, out = request(w, "POST", "/api/follow-up", dict(fu, anchor=anchor))
    assert status == 400  # a follow-up's anchor must sit on its parent answer
    status, out = request(w, "POST", "/api/note", {"text": "remember this", "anchor": anchor})
    assert status == 200 and out["note"]["share_with_agents"] is False
    status, threads = request(w, "GET", "/api/threads")
    assert [q["status"] for q in threads["questions"]] == ["answered", "open"]
    assert len(request(w, "GET", "/api/notes")[1]["notes"]) == 1
    assert request(w, "GET", "/api/map")[1]["document"]["revision"] == doc["revision"]


def test_retry_visit_activity_preview(served):
    w = served
    q = inbox.post_question(w.store, {"text": "q"})
    assert request(w, "POST", "/api/question/retry", {"id": q["id"]})[0] == 409   # open, not failed
    inbox.fail(w.store, {"id": q["id"], "reason": "x"})
    status, out = request(w, "POST", "/api/question/retry", {"id": q["id"]})
    assert status == 200 and out["question"]["status"] == "open"
    _, first = request(w, "POST", "/api/visit", {})
    _, second = request(w, "POST", "/api/visit", {})
    assert first["previous_visit"] is None and second["previous_visit"] == first["last_visit"]
    w.call("activity", "start", data={"agent": "checker", "status": "re-checking 3 claims"})
    status, act = request(w, "GET", "/api/activity")
    assert status == 200 and act["working"][0]["agent"] == "checker"
    status, prev = request(w, "GET", "/api/preview?path=engine.py&start=8&end=10&context=0")
    assert status == 200 and [r["n"] for r in prev["lines"]] == [8, 9, 10]
    assert request(w, "GET", "/api/preview?path=.env&start=1&end=1")[0] == 403
    assert request(w, "GET", "/api/nothing")[0] == 404
    assert request(w, "POST", "/api/question", "not an object")[0] == 400

"""Question lifecycle, record-the-answer (crash-safe), activity log, concurrent writers, and the watcher."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

from test_contract_fixtures import World, a_map

from honeyguide import activity, inbox
from honeyguide.contract import ContractError
from honeyguide.mapdoc import plain_text

ANSWER_CLAIM = {"key": "a1", "text": "generate loops three times", "evidence": "read_in_source",
                "anchors": [{"path": "engine.py", "anchor": "for _ in range(3):"}]}


def ask(w: World, text: str = "What does generate do?") -> dict:
    return inbox.post_question(w.store, {"text": text})


def answer(w: World, qid: str, **extra) -> tuple[int, dict]:
    data = {"question": qid, "agent": "investigator", "claims": [ANSWER_CLAIM],
            "spans": [{"text": "It "}, {"text": "loops three times", "claim": "a1"}, {"text": "."}], **extra}
    return w.call("answer", "record", data=data)


def test_lifecycle_and_record_answer(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w)
    code, out = w.call("inbox")
    assert [x["id"] for x in out["open"]] == [q["id"]]
    code, out = w.call("question", "claim", data={"id": q["id"], "agent": "investigator"})
    assert code == 0 and out["question"]["status"] == "investigating" and out["question"]["agent"] == "investigator"
    code, out = answer(w, q["id"])
    assert code == 0, out
    response = out["response"]
    assert out["question"]["status"] == "answered" and out["question"]["response"] == response["id"]
    assert response["text"] == "It loops three times." and response["spans"][1]["claim"] == response["claims"][0]["id"]
    assert response["claims"][0]["anchors"][0]["start"] == 9
    # answered is final: no reopen, no second answer, no claim.
    for argv, data in ((("question", "claim"), {"id": q["id"], "agent": "investigator"}),
                       (("question", "fail"), {"id": q["id"], "reason": "x"}),
                       (("question", "reopen"), {"id": q["id"]}),
                       (("question", "release"), {"id": q["id"]})):
        code, out = w.call(*argv, data=data)
        assert code == 1 and out["error"]["code"] == "invalid_transition", argv
    code, out = answer(w, q["id"])
    assert code == 1 and out["error"]["code"] == "invalid_transition"
    assert out["error"]["details"] == [f"answered by {response['id']}"]
    assert len(w.store.load("answers")["responses"]) == 1


def test_fail_retry_release(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w)
    assert w.call("question", "fail", data={"id": q["id"], "reason": "no budget"})[1]["question"]["status"] == "failed"
    code, out = w.call("question", "claim", data={"id": q["id"], "agent": "tracer"})
    assert code == 1 and out["error"]["code"] == "invalid_transition"  # failed -> investigating
    code, out = w.call("question", "reopen", data={"id": q["id"]})
    assert out["question"]["status"] == "open" and out["question"]["reopens"] == 1 and out["question"]["error"] is None
    w.call("question", "claim", data={"id": q["id"], "agent": "tracer"})
    code, out = w.call("question", "release", data={"id": q["id"]})
    assert code == 0 and out["question"]["status"] == "open" and out["question"]["agent"] is None
    code, out = w.call("question", "claim", data={"id": q["id"], "agent": "nobody"})
    assert code == 1 and out["error"]["code"] == "bad_input"
    code, out = w.call("question", "claim", data={"id": "q_missing", "agent": "tracer"})
    assert code == 1 and out["error"]["code"] == "not_found"


def test_legacy_question_without_status(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    old = w.store.add_question("an old question", None)
    assert inbox.inbox(w.store)["open"][0]["id"] == old["id"]
    assert answer(w, old["id"])[0] == 0
    assert inbox.inbox(w.store) == {"open": [], "investigating": []}


def test_answer_validation_writes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w)
    code, out = w.call("answer", "record", data={
        "question": q["id"], "agent": "investigator", "text": "hm",
        "claims": [{"key": "x", "text": "t", "evidence": "inferred", "anchors": []}]})
    assert code == 1 and out["error"]["code"] == "validation_failed"
    code, out = answer(w, q["id"], spans=[{"text": "see", "claim": "zz"}])
    assert code == 1 and "not a claim key in this answer" in out["error"]["details"][0]
    assert w.store.load("answers")["responses"] == []
    assert inbox.inbox(w.store)["open"][0]["id"] == q["id"]


def test_tracer_answer_with_path(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w, "What happens when main() runs?")
    path = {"id": "p1", "title": "main()", "lanes": [{"id": "cli", "label": "cli.py"},
                                                   {"id": "eng", "label": "engine.py"}],
            "loops": [{"id": "l", "label": "x 3"}],
            "hops": [{"from": "cli", "to": "eng", "call": "sample(engine, prompt)", "data": "list[int]",
                      "trace": "seen", "claim": "h1"},
                     {"from": "eng", "to": "eng", "call": "Engine.generate", "loop": "l", "trace": "unseen",
                      "claim": "a1"}]}
    hop = {"key": "h1", "text": "main calls sample", "evidence": "seen_at_runtime",
           "anchors": [{"path": "cli.py", "anchor": "return sample(Engine(len), [1, 2])"}]}
    code, out = w.call("answer", "record", data={"question": q["id"], "agent": "tracer", "text": "Two hops.",
                                                 "claims": [hop, ANSWER_CLAIM], "path": path})
    assert code == 0, out
    ids = {c["key"]: c["id"] for c in out["response"]["claims"]}
    assert [h["claim"] for h in out["response"]["path"]["hops"]] == [ids["h1"], ids["a1"]]
    bad = dict(path, hops=[dict(path["hops"][0], claim="missing")])
    q2 = ask(w)
    code, out = w.call("answer", "record", data={"question": q2["id"], "agent": "tracer", "text": "x",
                                                 "claims": [hop], "path": bad})
    assert code == 1 and "hop claim 'missing'" in out["error"]["details"][0]


def test_crash_mid_record_leaves_old_state(tmp_path, monkeypatch):
    """A process killed between writing the temp file and the rename: answers.json is the old file."""
    w = World(tmp_path, monkeypatch)
    q = ask(w)
    before = (w.store.dir / "answers.json").read_bytes()
    script = (
        "import os, sys\n"
        "import honeyguide.store as s\n"
        "s.os.replace = lambda *a: os._exit(9)\n"     # die at the moment of the rename
        "from honeyguide.cli import main\n"
        "sys.exit(main(['answer', 'record', '--repo', sys.argv[1]]))\n")
    data = {"question": q["id"], "agent": "investigator", "text": "It loops.", "claims": [ANSWER_CLAIM]}
    proc = subprocess.run([sys.executable, "-c", script, str(w.root)], input=json.dumps(data), text=True,
                          capture_output=True, timeout=60, env=os.environ.copy())
    assert proc.returncode == 9
    assert (w.store.dir / "answers.json").read_bytes() == before
    assert inbox.inbox(w.store)["open"][0]["id"] == q["id"]   # still open, loadable, no answer
    assert w.store.load("answers")["responses"] == []
    # The retry works and saves exactly one answer.
    assert answer(w, q["id"])[0] == 0
    assert len(w.store.load("answers")["responses"]) == 1


def test_error_inside_the_write_leaves_old_state(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w)

    def boom(*args):
        raise OSError("disk full")
    monkeypatch.setattr("honeyguide.store.os.fsync", boom)
    code, out = answer(w, q["id"])
    monkeypatch.undo()
    assert code == 1 and out["error"]["code"] == "store_error"
    assert not [p for p in w.store.dir.iterdir() if p.name.endswith(".tmp")]
    assert w.store.load("answers")["responses"] == []


def test_concurrent_writers(tmp_path, monkeypatch):
    """Page posts and agent activity from several processes at once: nothing lost."""
    w = World(tmp_path, monkeypatch)
    script = (
        "import sys\n"
        "from honeyguide import inbox, activity\n"
        "from honeyguide.store import Store\n"
        "s = Store(sys.argv[1])\n"
        "for i in range(5):\n"
        "    inbox.post_question(s, {'text': f'{sys.argv[2]} q{i}'})\n"
        "    activity.start(s, {'agent': 'investigator', 'status': f'{sys.argv[2]} {i}'})\n")
    procs = [subprocess.Popen([sys.executable, "-c", script, w.store.repo_id, f"p{n}"], env=os.environ.copy(),
                              stderr=subprocess.PIPE, text=True) for n in range(8)]
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
    questions = w.store.load("answers")["questions"]
    assert len(questions) == 40 and len({q["text"] for q in questions}) == 40
    assert len(activity.listing(w.store)["working"]) == 40


def test_activity_log(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    q = ask(w)
    code, out = w.call("activity", "start", data={"agent": "tracer", "question": q["id"],
                                                  "status": "reading\nengine.py"})
    entry = out["entry"]
    assert code == 0 and entry["state"] == "working" and entry["status"] == "reading engine.py"
    _, out = w.call("activity", "update", data={"id": entry["id"], "status": "following generate()"})
    assert out["entry"]["status"] == "following generate()"
    _, out = w.call("activity", "list")
    assert [e["id"] for e in out["working"]] == [entry["id"]] and out["working"][0]["stale"] is False
    _, out = w.call("activity", "finish", data={"id": entry["id"], "state": "done"})
    assert out["entry"]["state"] == "done" and out["entry"]["ended_at"]
    code, out = w.call("activity", "update", data={"id": entry["id"], "status": "again"})
    assert code == 1 and out["error"]["code"] == "invalid_transition"
    _, out = w.call("activity", "list")
    assert out["working"] == [] and [e["id"] for e in out["recent"]] == [entry["id"]]
    code, out = w.call("activity", "start", data={"agent": "owl", "status": "x"})
    assert code == 1 and out["error"]["code"] == "bad_input"


def test_question_show_thread_and_context(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    _, saved = w.call("claims", "save", data=a_map())
    doc = w.store.load("map")["document"]
    text = plain_text(doc)
    start = text.index("yields three outputs")
    anchor = {"doc": "map", "revision": doc["revision"], "quote": "yields three outputs",
              "start": start, "end": start + len("yields three outputs")}
    q = inbox.post_question(w.store, {"text": "Why three?", "anchor": anchor})
    assert q["anchor"]["context"]  # filled by the script
    _, rec = answer(w, q["id"])
    rid = rec["response"]["id"]
    fu_anchor = {"doc": f"answer:{rid}", "revision": rec["response"]["revision"], "quote": "three",
                 "start": 9, "end": 14}
    fu = inbox.post_question(w.store, {"text": "Is 3 configurable?", "anchor": fu_anchor, "parent_response": rid})
    code, out = w.call("question", "show", data={"id": fu["id"]})
    assert code == 0 and out["question"]["status"] == "open"
    assert [t["question"]["id"] for t in out["thread"]] == [q["id"]]
    assert out["context"]["selected_claims"] == [rec["response"]["claims"][0]["id"]]
    _, out = w.call("question", "show", data={"id": q["id"]})
    gen = next(s["id"] for s in saved["saved"] if s["key"] == "gen")
    assert out["context"]["selected_claims"] == [gen]
    assert gen in [h["claim"]["id"] for h in out["context"]["map_claims"]]
    # A stale revision or a wrong quote is refused.
    for bad in (dict(anchor, revision="000000000000"), dict(anchor, quote="something else")):
        try:
            inbox.post_question(w.store, {"text": "x", "anchor": bad})
            raise AssertionError("accepted a bad anchor")
        except ContractError:
            pass


def test_watch_one_line_per_new_question(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    before = ask(w, "asked before the watcher started")
    out = io.StringIO()
    steps = iter([
        lambda: None,
        lambda: ask(w, "first new"),
        lambda: (ask(w, "second\nnew, on two lines"), ask(w, "third new")),
        lambda: inbox.claim(w.store, {"id": before["id"], "agent": "investigator"}),  # not open: silent
        lambda: inbox.fail(w.store, {"id": before["id"], "reason": "x"}),
        lambda: inbox.reopen(w.store, {"id": before["id"]}),                           # open again: one line
        lambda: None, lambda: None,
    ])
    done = []

    def should_stop() -> bool:
        step = next(steps, None)
        if step is None:
            done.append(True)
            return True
        step()
        return False

    assert inbox.watch(w.store, out, interval=0.01, should_stop=should_stop) == 0 and done
    lines = out.getvalue().splitlines()
    assert len(lines) == 5
    assert lines[0] == f"{before['id']} question asked before the watcher started"
    assert [line.split(" ", 2)[2] for line in lines[1:]] == [
        "first new", "second new, on two lines", "third new", "asked before the watcher started"]


def test_watch_cli_process(tmp_path, monkeypatch):
    """The real command, as the session's Monitor runs it: one flushed line per question, then the timeout."""
    w = World(tmp_path, monkeypatch)
    proc = subprocess.Popen([sys.executable, "-m", "honeyguide.cli", "watch", "--follow", "--interval", "0.05",
                             "--timeout", "3", "--repo", str(w.root)], stdout=subprocess.PIPE, text=True,
                            env=os.environ.copy())
    time.sleep(0.5)
    ask(w, "one")
    ask(w, "two")
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 3
    assert [line.split(" ", 2)[1:] for line in out.splitlines()] == [["question", "one"], ["question", "two"]]

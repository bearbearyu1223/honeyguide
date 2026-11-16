"""Shots 4-6: the live loop, recorded while a real Claude Code session answers the question.

    uv run --project .. python shoot_live.py OUT --tag q1 --a "The window pattern is the trap" --b "sees all of it" \
        --question "..."
    uv run --project .. python shoot_live.py OUT --tag q2 --parent q_... --a "..." --b "..." --question "What happens when ..."

Take A (one Chrome, under alarm 120): select the passage (on the map, or in the parent question's answer), Ask,
type the question, send it; the page shows it waiting. Then answer.sh starts the batch Claude session that answers
it, and the recording keeps going while the Guide routes it. Takes B, C, ... (one Chrome each, under alarm 120,
reopened on the same thread at the same scroll position) keep recording at 4 frames/s until the answer has landed
and the Checker has finished. The gaps between takes (a Chrome restart, ~3 s) are logged and shown as cuts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from rec import Rec, phrase

DEMO = Path(__file__).resolve().parent
HGBIN = Path.home() / "Documents/GitHub/honeyguide-run/.venv/bin/honeyguide"
REPO = Path.home() / "Documents/GitHub/honeyguide-targets/nanochat"


def inbox() -> dict:
    return json.loads(subprocess.run([str(HGBIN), "inbox", "--repo", str(REPO)], capture_output=True, text=True).stdout)


def thread_state(c, qid):
    return c.js(f"""(() => {{ const q = D.threads.questions.find(x => x.id === {json.dumps(qid)});
      return {{status: q && q.status, response: q && q.response,
               working: D.activity.working.filter(w => w.question === {json.dumps(qid)} && !w.stale).map(w => w.agent)}}; }})()""")


def take_a(out: Path, a, url, scroll_to_gpt=True):
    with Rec(out / "A", dark=a.dark) as c:
        t_launch = time.monotonic()
        c.goto(url + (f"#q={a.parent}" if a.parent else ""))
        c.pump(1.0)
        if a.parent:
            root = "document.getElementById('pbody')"
        else:
            c.js("[...document.querySelectorAll('#col h3')].find(h=>h.textContent.startsWith('nanochat/gpt.py'))"
                 ".closest('.mod').scrollIntoView({block:'start'}); document.getElementById('main').scrollBy(0,330)")
            root = "document.getElementById('col')"
        c.pump(0.6)
        c.cursor = (1000, 640)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(0.8)
        p = phrase(c, root, a.a, a.b)
        assert p, "phrase not found"
        c.drag_select(p["x0"], p["y0"], p["x1"], p["y1"], 1100)
        c.pump(0.6)
        r = c.rect("document.querySelector('#tb [data-act=ask]')")
        c.click_at(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2, 600)
        c.pump(0.7)
        r = c.rect("document.getElementById('cin')")
        c.click_at(r["x"] + 60, r["y"] + r["h"] / 2, 500)
        c.type_slow(a.question, 24)
        c.pump(0.6)
        before = {q["id"] for q in inbox()["open"]}
        r = c.rect("document.getElementById('send')")
        c.click_at(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2, 500)
        c.pump(1.5)
        new = [q for q in inbox()["open"] if q["id"] not in before]
        assert len(new) == 1, new
        qid = new[0]["id"]
        c.note("asked", id=qid, text=new[0]["text"])
        c.move(c.cursor[0] - 260, c.cursor[1] - 120, 900)   # out of the way
        c.pump(2.5)
        # the real session that answers it
        jsonl = out / f"answer-{a.tag}.jsonl"
        proc = subprocess.Popen(["zsh", str(DEMO / "answer.sh"), str(jsonl)], start_new_session=True)
        c.note("claude_start", pid=proc.pid)
        (out / "pid").write_text(str(proc.pid))
        c.min_dt = 0.25
        while time.monotonic() - t_launch < 108 and proc.poll() is None:
            c.pump(1.0)
            c.note("state", **thread_state(c, qid))
        scroll = c.js("document.getElementById('main').scrollTop")
        pscroll = c.js("document.getElementById('pbody').scrollTop")
        c.stop()
    return qid, proc, scroll, pscroll


def take_b(out: Path, k: int, a, url, qid, proc, scroll, pscroll) -> bool:
    """One more take; True when the answer is in and nobody is working on the question any more."""
    with Rec(out / f"B{k:02d}", dark=a.dark) as c:
        t_launch = time.monotonic()
        c.goto(url + f"#q={qid}")
        c.js(f"document.getElementById('main').scrollTop = {scroll}")
        c.pump(0.8)
        c.cursor = (740, 380)
        c.mouse("mouseMoved", *c.cursor)
        c.min_dt = 0.25
        c.start()
        done_at = None
        while time.monotonic() - t_launch < 108:
            c.pump(1.0)
            s = thread_state(c, qid)
            c.note("state", **s)
            finished = proc.poll() is not None      # the session has ended: answer recorded and checked
            if finished and done_at is None:
                done_at = time.monotonic()
            if done_at and time.monotonic() - done_at > 6:
                c.stop()
                return True
        c.stop()
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--parent", help="a question id: select in its answer and ask a follow-up")
    ap.add_argument("--url", default="http://127.0.0.1:8782/")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--max-takes", type=int, default=20)
    a = ap.parse_args()
    out = Path(a.out) / a.tag
    out.mkdir(parents=True, exist_ok=True)
    qid, proc, scroll, pscroll = take_a(out, a, a.url)
    (out / "qid").write_text(qid)
    print("asked", qid, flush=True)
    for k in range(1, a.max_takes + 1):
        if take_b(out, k, a, a.url, qid, proc, scroll, pscroll):
            break
    proc.wait()
    print("done", qid, "exit", proc.returncode, flush=True)


if __name__ == "__main__":
    main()

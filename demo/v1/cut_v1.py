"""The edit: every segment of the demo, in order, with its source times taken from the takes' own logs.

    uv run --project .. --with pillow python cut.py REC_DIR OUT.mp4

REC_DIR holds cards/, take1/{payoff,tour,answer}/ and live/{q1,q2}/ as written by cards.py, shoot_tour.py,
shoot_answer.py and shoot_live.py. Prints each segment's output start time and what it covers (the shot list in
README.md comes from this).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from compose import FPS, H, Takes, Writer, card, take
from term import events

PIP = dict(x=24, y=H - 500 - 24, w=900, h=500, size=17, title="Claude Code · the Guide · nanochat (batch session)")
TOP = 64            # caption height when the PiP holds the bottom-left


def checks(d: Path) -> str:
    """'N of M claims pass', from the saved answer's claims (the honeyguide CLI, read-only)."""
    import subprocess
    qid = (d / "qid").read_text().strip()
    hg = [str(Path.home() / "Documents/GitHub/honeyguide-run/.venv/bin/honeyguide"), "--repo",
          str(Path.home() / "Documents/GitHub/honeyguide-targets/nanochat")]
    q = json.loads(subprocess.run(hg[:1] + ["question", "show"] + hg[1:] + ["--id", qid], capture_output=True, text=True).stdout)
    rid = q["question"]["response"]
    cl = json.loads(subprocess.run(hg[:1] + ["claims", "list"] + hg[1:] + ["--responses", rid, "--json"],
                                   capture_output=True, text=True).stdout)["claims"]
    ok = sum(c.get("check") == "supported" for c in cl)
    return f"{ok} of {len(cl)} claims pass"


def states(tk: Takes) -> list[dict]:
    return [n for n in tk.notes if n["kind"] == "state"]


def first_state(tk: Takes, pred) -> float:
    return next(n["t"] for n in states(tk) if pred(n))


def live_q(w: Writer, d: Path, tag: str, intro_caps, wait_cap, land_cap, check_cap, speed=20, landed_hold=3.2,
           intro_speed=1.0, log=print) -> dict:
    """One live question: take A (select, Ask, type, send) at x1, then the wait at xN with the PiP, the answer landing
    at x1, the Checker at xN."""
    takes = sorted(p for p in d.iterdir() if p.is_dir() and (p.name == "A" or p.name.startswith("B")))
    tk = Takes(*takes)
    a0 = tk.first("start")["t"]
    cs = tk.first("claude_start")["t"]
    evs = events(d / f"answer-{tag}.jsonl")
    t_end = evs[-1]["t"]
    t_answer = first_state(tk, lambda n: n["status"] == "answered")      # first poll that saw it answered
    t_land = t_answer - 1.2
    pip = dict(PIP, events=evs, t0=cs)
    log(f"{w.n / FPS:6.1f}  {tag}: select, Ask, type, send (x{intro_speed:g})")
    take(w, tk, a0, cs, intro_speed, captions=intro_caps)
    log(f"{w.n / FPS:6.1f}  {tag}: the session picks it up and works (x{speed}), {t_land - cs:.0f} s real")
    take(w, tk, cs, t_land, speed, pip=pip, cursor=False, captions=[(0.3, (t_land - cs) / speed - 0.2, wait_cap)],
         cap_y=TOP)
    log(f"{w.n / FPS:6.1f}  {tag}: the answer lands (x1)")
    take(w, tk, t_land, t_land + landed_hold, 1.0, pip=pip, cursor=False, captions=[(0.3, landed_hold - 0.1, land_cap)],
         cap_y=TOP)
    t_chk_end = min(t_end + 3, tk.ft[-1])
    log(f"{w.n / FPS:6.1f}  {tag}: the Checker (x{speed}), {t_chk_end - t_land - landed_hold:.0f} s real")
    if check_cap:
        take(w, tk, t_land + landed_hold, t_chk_end, speed, pip=pip, cursor=False,
             captions=[(0.3, (t_chk_end - t_land - landed_hold) / speed - 0.2, check_cap)], cap_y=TOP)
    res = next(e for e in reversed(evs) if e["kind"] == "done")
    t_quiet = max(n["t"] for n in states(tk) if n["working"])           # the last poll that saw an agent working
    return {"checked_after_s": t_quiet - t_answer + 1, "tag": tag, "claude_start": cs, "end": t_end, "answered_seen": t_answer, "wall_s": round(t_end - cs, 1),
            "duration_ms": res.get("duration_ms"), "cost_usd": res.get("cost"), "turns": res.get("num_turns")}


def main() -> None:
    rec, out = Path(sys.argv[1]), Path(sys.argv[2])
    only = sys.argv[3] if len(sys.argv) > 3 else None
    w = Writer(out)
    facts = []

    def log(s):
        print(s, flush=True)

    def want(name):
        return only is None or only == name

    if want("intro"):
        log(f"{w.n / FPS:6.1f}  title card")
        card(w, rec / "cards/title.png", 3.0)
        pay = Takes(rec / "take1/payoff")
        p0 = pay.first("start")["t"]
        log(f"{w.n / FPS:6.1f}  payoff: the finished map")
        take(w, pay, p0 + 0.1, p0 + 4.1, 1.0, captions=[(0.2, 3.9, "A map of karpathy/nanochat. Every sentence cites its lines.")])
        log(f"{w.n / FPS:6.1f}  install card")
        card(w, rec / "cards/install.png", 4.6)
        log(f"{w.n / FPS:6.1f}  clock card (the explore and repair runs)")
        card(w, rec / "cards/clock.png", 5.4)

    if want("tour"):
        tour = Takes(rec / "take1/tour")
        t0, t1 = tour.first("start")["t"], tour.first("stop")["t"]
        tc = tour.clicks[0][0]                       # the "Modules" click
        tg = tour.first("github")["t"]
        log(f"{w.n / FPS:6.1f}  tour: Start here, gpt.py Design, chip preview (x1)")
        take(w, tour, t0 + 0.6, t1 - 1.0, 1.0, captions=[
            (2.0, tc - t0 - 0.9, "Start here: what to read first, and why."),
            (tc - t0 + 2.4, tg - t0 - 3.6, "Design: why it's built this way, or the sharp edge you'd hit first."),
            (tg - t0 - 3.3, t1 - t0 - 1.7, "Every citation opens its lines, pinned to the commit on GitHub."),
        ])

    if want("q1"):
        facts.append(live_q(
            w, rec / "live/q1", "q1",
            intro_caps=[(0.4, 11.0, "Select any sentence and Ask."), (11.4, 16.4, "The question waits for your Claude Code session.")],
            wait_cap="Claude Code picks it up. Honey, the Guide, routes it to the Tracer.",
            land_cap="The answer lands beside your highlight.",
            check_cap="Then the Checker re-reads every cited line.", log=log))

    if want("answer"):
        an = Takes(rec / "take1/answer")
        a0, a1 = an.first("start")["t"], an.first("stop")["t"]
        fh = an.first("flag_hover")["t"]
        dg = an.clicks[-1][0]                         # "View as diagram"
        log(f"{w.n / FPS:6.1f}  the answer: hops, a flag, the diagram (x1)")
        take(w, an, a0 + 1.0, a1 - 1.3, 1.0, captions=[
            (0.2, fh - a0 - 4.1, "Each hop cites its lines."),
            (fh - a0 - 3.9, dg - a0 - 3.3, f"{checks(rec / 'live/q1')}. Each flag says what its lines don't show."),
            (dg - a0 - 1.0, a1 - a0 - 2.4, "A Tracer answer is also a diagram."),
        ])

    if want("q2") and (rec / "live/q2/qid").exists():
        facts.append(live_q(
            w, rec / "live/q2", "q2",
            intro_caps=[(0.3, 8.2, "Select words in the answer to ask a follow-up.")], intro_speed=2.0,
            wait_cap="A follow-up. Honey sends this one to the Investigator.",
            land_cap="The follow-up lands under the answer.",
            check_cap="", log=log))
        fu = Takes(rec / "take1/followup")
        f0, f1 = fu.first("start")["t"], fu.first("stop")["t"]
        q2 = facts[-1]
        log(f"{w.n / FPS:6.1f}  the follow-up, after its check (recorded after the run, x1)")
        take(w, fu, f0 + 0.2, f1, 1.0, captions=[
            (0.2, 3.4, f"Checked {q2['checked_after_s']:.0f} s after it landed: {checks(rec / 'live/q2')}."),
            (3.6, f1 - f0 - 0.5, "It found the map's own slip: one claim still says 768."),
        ])

    if want("close"):
        log(f"{w.n / FPS:6.1f}  closing card")
        card(w, rec / "cards/close.png", 5.0, fout=12)
    log(f"{w.n / FPS:6.1f}  end")
    w.close()
    for f in facts:
        print(json.dumps(f))




def poster(rec: Path, out: Path) -> None:
    """The poster: the first answer just landed beside its highlight, with the real session in the PiP (no caption)."""
    from term import Term, frame_shadowed
    d = rec / "live/q1"
    tk = Takes(*sorted(p for p in d.iterdir() if p.is_dir() and (p.name == "A" or p.name.startswith("B"))))
    cs = tk.first("claude_start")["t"]
    t = first_state(tk, lambda n: n["status"] == "answered") + 1.0
    img = tk.frame(t).convert("RGBA")
    term = Term(PIP["w"], PIP["h"], PIP["size"], PIP["title"])
    ti = frame_shadowed(term.render(events(d / "answer-q1.jsonl"), t, cs))
    img.paste(ti, (PIP["x"], PIP["y"]), ti)
    img.convert("RGB").save(out)


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "poster":
        poster(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        main()

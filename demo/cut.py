"""The edit (v2, UX v4): every segment of the demo, in order, with its source times taken from the takes' own logs.

    uv run --project .. --with pillow python cut.py REC_DIR OUT.mp4
    uv run --project .. --with pillow python cut.py REC_DIR poster.png poster
    uv run --project .. --with pillow python cut.py REC_DIR gif-source.mp4 gif     # then ffmpeg -> the GIF (README)

REC_DIR holds cards/ (cards.py), take/{payoff,nav,flow}/ (shoot_v4.py) and live/q1/ (shoot_live.py --component).
Prints each segment's output start time and what it covers (the shot list in README.md comes from this), then the
live run's facts as JSON. The v1 edit is kept as v1/cut_v1.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from compose import FPS, H, Takes, Writer, card, take
from shoot_live import B_CURSOR
from term import events

PIP = dict(x=24, y=H - 500 - 24, w=900, h=500, size=17, title="Claude Code · the Guide · nanochat (batch session)")
TOP = 64            # caption height when the bottom of the frame is busy
HG = [str(Path.home() / "Documents/GitHub/honeyguide-run/.venv/bin/honeyguide")]
REPO = ["--repo", str(Path.home() / "Documents/GitHub/honeyguide-targets/nanochat")]


def hg(*args) -> dict:
    return json.loads(subprocess.run(HG + list(args) + REPO, capture_output=True, text=True).stdout)


def answer_facts(d: Path) -> dict:
    """The live answer as saved: its response id and its claims' checks (honeyguide CLI, read-only)."""
    qid = (d / "qid").read_text().strip()
    q = hg("question", "show", "--id", qid)
    rid = q["question"]["response"]
    cl = hg("claims", "list", "--responses", rid, "--json")["claims"]
    return {"qid": qid, "rid": rid, "claims": len(cl), "repaired": sum(bool(c.get("repairs")) for c in cl),
            "supported": sum(c.get("check") == "supported" for c in cl),
            "not_supported": sum(c.get("check") == "not_supported" for c in cl)}


def checked_caption(f: dict) -> str:
    n, rep, ok = f["claims"], f["repaired"], f["supported"]
    if rep:
        return f"{n - rep} of {n} passed at once; {rep} repaired and re-checked. Now {ok} of {n} pass."
    return f"Checked: {ok} of {n} claims pass." + ("" if ok == n else " The rest are flagged.")


def states(tk: Takes) -> list[dict]:
    return [n for n in tk.notes if n["kind"] == "state"]


def note_t(tk: Takes, kind: str) -> float:
    return tk.first(kind)["t"]


def speed_for(seconds: float, target: float = 6.0) -> int:
    """A round speed-up that plays ``seconds`` of waiting in about ``target`` seconds (at least x10)."""
    s = max(10, seconds / target)
    return int(round(s / 5) * 5) if s > 12 else int(round(s))


def live_takes(d: Path) -> Takes:
    """The live take A and its B.. reopens on one clock. Takes recorded before shoot_live logged the parked pointer
    get it added: it sat at B_CURSOR from each reopen's start (that pointer is what holds the map's hover tooltip)."""
    takes = sorted(p for p in d.iterdir() if p.is_dir() and (p.name == "A" or p.name.startswith("B")))
    tk = Takes(*takes)
    for b in takes[1:]:
        lines = (b / "log.jsonl").read_text().splitlines()
        if not any('"cursor"' in line for line in lines):
            tk.cursor.append((json.loads(lines[0])["t"], *B_CURSOR, False))
    tk.cursor.sort()
    tk.ct = [c[0] for c in tk.cursor]
    return tk


def live(w: Writer, d: Path, log=print) -> dict:
    tk = live_takes(d)
    a0 = note_t(tk, "start")
    tg, tf, tq = note_t(tk, "toc_graph"), note_t(tk, "focus"), note_t(tk, "gask")
    ts = note_t(tk, "asked")
    cs = note_t(tk, "claude_start")
    evs = events(d / "answer-q1.jsonl")
    t_end = evs[-1]["t"]
    t_answer = next(n["t"] for n in states(tk) if n["status"] == "answered")      # first poll that saw it answered
    t_land = t_answer - 0.5
    pip = dict(PIP, events=evs, t0=cs)
    f = answer_facts(d)
    log(f"{w.n / FPS:6.1f}  component map, focus, Ask about this component, send (x1)")
    take(w, tk, a0 + 0.4, cs, 1.0, captions=[
        (tg - a0 - 0.2, tf - a0 - 0.6, "The component map: the main paths between the parts.", TOP),
        (tf - a0 - 0.3, tq - a0 - 1.2, "Click one: focus mode keeps its callers and callees.", TOP),
        (tq - a0 - 0.6, ts - a0 - 0.6, "Ask about this component: the question is written for you.", TOP),
        (ts - a0 - 0.4, cs - a0 - 0.6, "Ask. It waits for your Claude Code session.", TOP),
    ])
    sp1 = speed_for(t_land - cs)
    log(f"{w.n / FPS:6.1f}  the session claims, routes and answers (x{sp1}), {t_land - cs:.0f} s real")
    take(w, tk, cs, t_land, sp1, pip=pip,
         captions=[(0.3, (t_land - cs) / sp1 - 0.2, "Your Claude Code session picks it up. Honey routes it.", TOP)])
    log(f"{w.n / FPS:6.1f}  the answer lands (x1)")
    take(w, tk, t_land, t_land + 3.4, 1.0, pip=pip,
         captions=[(0.3, 3.3, "The answer lands in the thread, every sentence cited.", TOP)])
    t_last = min(t_end + 2.0, tk.ft[-1] - 0.5)
    sp2 = speed_for(t_last - t_land - 3.4)
    log(f"{w.n / FPS:6.1f}  the Checker and the repair pass (x{sp2}), {t_last - t_land - 3.4:.0f} s real")
    take(w, tk, t_land + 3.4, t_last, sp2, pip=pip,
         captions=[(0.3, (t_last - t_land - 3.4) / sp2 - 0.2, "The Checker re-reads every cited line. Flagged claims get repaired.", TOP)])
    log(f"{w.n / FPS:6.1f}  the checked answer (x1, still)")
    take(w, tk, t_last, t_last + 1 / FPS, 1.0, pip=pip, hold=3.4, captions=[(0.2, 3.4, checked_caption(f), TOP)])
    res = next(e for e in reversed(evs) if e["kind"] == "done")
    return {**f, "claude_start": cs, "asked": ts, "answered_seen": t_answer, "end": t_end, "wall_s": round(t_end - cs, 1),
            "speed_wait": sp1, "speed_check": sp2, "duration_ms": res.get("duration_ms"), "cost_usd": res.get("cost"),
            "turns": res.get("num_turns")}


def main() -> None:
    rec, out = Path(sys.argv[1]), Path(sys.argv[2])
    w = Writer(out)
    facts = []

    def log(s):
        print(s, flush=True)

    log(f"{w.n / FPS:6.1f}  title card")
    card(w, rec / "cards/title.png", 3.0)

    pay = Takes(rec / "take/payoff")
    p0 = pay.first("start")["t"]
    log(f"{w.n / FPS:6.1f}  payoff: the page top, the repo card (x1)")
    take(w, pay, p0 + 0.3, p0 + 5.3, 1.0, captions=[(0.2, 4.8, "A map of karpathy/nanochat. It opens on the repo card.")])

    log(f"{w.n / FPS:6.1f}  install card")
    card(w, rec / "cards/install.png", 4.4)
    log(f"{w.n / FPS:6.1f}  clock card (run 2, repair, re-check; from outputs/runs.txt)")
    card(w, rec / "cards/clock.png", 6.0)

    nv = Takes(rec / "take/nav")
    n0, n1 = nv.first("start")["t"], nv.first("stop")["t"]
    sl, fg, fe, ch = (nv.first(k)["t"] - n0 for k in ("slash", "find_go", "find_esc", "chip"))
    log(f"{w.n / FPS:6.1f}  navigate: scroll-spy, Find (/), the Design paragraph, a chip's preview (x1)")
    take(w, nv, n0 + 0.4, n1 - 0.2, 1.0, captions=[
        (0.4, sl - 1.2, "The outline follows you as you read."),
        (sl - 0.6, fg - 0.2, "Press / to find any term in the map."),
        (fe - 0.2, ch - 0.8, "Design: the sharp edge you'd hit first."),
        (ch - 0.4, n1 - n0 - 0.8, "Every citation opens its lines, pinned to the commit.", TOP),
    ])

    facts.append(live(w, rec / "live/q1", log))

    fl = Takes(rec / "take/flow")
    f0, f1 = fl.first("start")["t"], fl.first("stop")["t"]
    fs, zb, ft = (fl.first(k)["t"] - f0 for k in ("fs", "zoom_btn", "fit"))
    log(f"{w.n / FPS:6.1f}  a flow swimlane: Expand, zoom, pan, Fit (x1)")
    take(w, fl, f0 + 0.3, f1 - 0.3, 1.0, captions=[
        (0.3, fs - 0.6, "A traced flow, as a swimlane."),
        (fs - 0.4, zb - 0.6, "Every diagram opens full screen."),
        (zb - 0.4, ft - 0.4, "Zoom with + or Ctrl+scroll at the pointer. Drag to pan."),
        (ft - 0.2, f1 - f0 - 0.7, "Fit, and Esc to go back."),
    ])

    log(f"{w.n / FPS:6.1f}  closing card")
    card(w, rec / "cards/close.png", 5.0, fout=12)
    log(f"{w.n / FPS:6.1f}  end")
    w.close()
    for f in facts:
        print(json.dumps(f))


def poster(rec: Path, out: Path) -> None:
    """The poster: the checked answer in the panel beside the component map, the real session's last lines (done,
    5.3 min, cost) in the PiP, the pointer where it was parked (no caption)."""
    from compose import draw_cursor
    from term import Term, frame_shadowed
    d = rec / "live/q1"
    tk = live_takes(d)
    cs = tk.first("claude_start")["t"]
    evs = events(d / "answer-q1.jsonl")
    t = min(evs[-1]["t"] + 2.0, tk.ft[-1] - 0.5)
    img = tk.frame(t).convert("RGBA")
    term = Term(PIP["w"], PIP["h"], PIP["size"], PIP["title"])
    ti = frame_shadowed(term.render(evs, t, cs))
    img.paste(ti, (PIP["x"], PIP["y"]), ti)
    img = img.convert("RGB")
    p = tk.pointer(t)
    if p:
        draw_cursor(img, p[1], p[2])
    img.save(out)


def gif_source(rec: Path, out: Path) -> None:
    """The README GIF's source (1920x1200 MP4): focus on gpt.py (x1, then x2 while the page scrolls to the focus
    card), Ask about this component and send (x1), the session's work (x40), the answer landing (x1), the Checker
    and repair (x60), the checked answer. Same take, same run as the video; every speed-up carries its badge."""
    d = rec / "live/q1"
    w = Writer(out)
    tk = live_takes(d)
    tf, tq, ts = note_t(tk, "focus"), note_t(tk, "gask"), note_t(tk, "asked")
    cs = note_t(tk, "claude_start")
    evs = events(d / "answer-q1.jsonl")
    t_land = next(n["t"] for n in states(tk) if n["status"] == "answered") - 0.5
    t_last = min(evs[-1]["t"] + 2.0, tk.ft[-1] - 0.5)
    pip = dict(PIP, events=evs, t0=cs)
    f = answer_facts(d)
    a = tf - 0.7
    take(w, tk, a, tf + 2.0, 1.0, captions=[(0.0, 2.7, "Click a component: focus mode.", TOP)])
    take(w, tk, tf + 2.0, tq - 0.6, 2.0, captions=[(0.0, (tq - tf - 2.6) / 2, "Click a component: focus mode.", TOP)])
    take(w, tk, tq - 0.6, ts + 0.8, 1.0, captions=[(0.0, ts - tq + 1.4, "Ask about this component.", TOP)])
    take(w, tk, ts + 0.8, t_land, 40, pip=pip, captions=[(0.2, (t_land - ts - 0.8) / 40, "Your Claude Code session answers.", TOP)])
    take(w, tk, t_land, t_land + 2.6, 1.0, pip=pip, captions=[(0.0, 2.6, "The answer lands, cited.", TOP)])
    take(w, tk, t_land + 2.6, t_last, 60, pip=pip, captions=[(0.2, (t_last - t_land - 2.6) / 60, "The Checker re-reads every line.", TOP)])
    take(w, tk, t_last, t_last + 1 / FPS, 1.0, pip=pip, hold=2.2,
         captions=[(0.0, 2.2, f"{f['supported']} of {f['claims']} claims pass.", TOP)])
    w.close()
    print(f"gif source: {w.n / FPS:.1f} s")


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "poster":
        poster(Path(sys.argv[1]), Path(sys.argv[2]))
    elif len(sys.argv) > 3 and sys.argv[3] == "gif":
        gif_source(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        main()

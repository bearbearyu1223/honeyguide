"""Shots 1, 3 and 6 of the UX v4 demo, on the real page: the page top with the repo card (payoff); navigating
(the outline's scroll-spy, Find with "/", the GPT model card's Design paragraph, a code chip's preview pinned to
the commit); and a flow swimlane in full screen (zoom and pan).

    uv run --project .. python shoot_v4.py OUT [--url http://127.0.0.1:8782/] [--only payoff|nav|flow] [--dark]

Writes OUT/payoff/, OUT/nav/, OUT/flow/ (frames/*.jpg + log.jsonl), one Chrome per take, each under alarm 120.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rec import Rec, phrase


def fresh(c: Rec, url: str) -> None:
    """A clean page: no stored panel width or theme, the discussion panel closed."""
    c.goto(url)
    c.js("localStorage.clear(); localStorage.setItem('honeyguide.panelWidth', '408')")
    c.goto(url)
    c.pump(0.8)
    c.js("document.getElementById('pclose')?.click()")
    c.pump(0.3)


def scroll_main_by(c: Rec, dy: float, ms: float = 1100) -> None:
    if c.cursor[0] < 300:                  # wheel over the contents would scroll the contents
        c.move(900, c.cursor[1], 450)
    c.smooth_scroll(dy, ms)
    c.pump(0.3)


def payoff(out: Path, url: str, dark: bool) -> None:
    with Rec(out, dark=dark) as c:
        fresh(c, url)
        c.cursor = (1180, 620)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(0.8)
        c.move(1000, 300, 1500)             # drift over the repo card, as a reader would
        c.pump(0.6)
        c.move(1060, 590, 1200)
        c.pump(2.2)
        c.stop()


def nav(out: Path, url: str, dark: bool) -> None:
    with Rec(out, dark=dark) as c:
        fresh(c, url)
        c.cursor = (900, 560)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(0.6)
        # down the Overview cards: the contents' scroll-spy follows
        for _ in range(3):
            scroll_main_by(c, 560, 1100)
            c.pump(0.5)
        c.note("spy", sub=c.js("document.querySelector('#toc a[data-sub].on')?.textContent || ''"))
        c.move(160, 300, 700)               # towards the Find box
        c.pump(0.3)
        c.key("/", "Slash")                 # "/" focuses Find
        c.note("slash")
        c.pump(0.5)
        c.type_slow("window pattern", 14)
        c.pump(1.2)
        n = c.js("FIND.hits.length")
        gi = c.js("[...document.querySelectorAll('#findres [data-fgo]')].findIndex(b => /trap/.test(b.textContent))")
        c.note("find", hits=n, pick=gi)
        b = c.rect(f"document.querySelectorAll('#findres [data-fgo]')[{max(gi, 0)}]")
        c.move(b["x"] + 60, b["y"] + b["h"] / 2, 700)
        c.pump(0.8)
        c.click_at(b["x"] + 60, b["y"] + b["h"] / 2, 200)
        c.note("find_go")
        c.pump(1.8)
        # leave Find (Esc in the box): the full outline returns, its scroll-spy on the card we jumped to
        f = c.rect("document.getElementById('find')")
        c.click_at(f["x"] + 120, f["y"] + f["h"] / 2, 700)
        c.key("Escape")
        c.note("find_esc")
        c.pump(1.4)
        c.note("spy", sub=c.js("document.querySelector('#toc a[data-sub].on')?.textContent || ''"))
        # read along the trap sentence in the Design paragraph
        p = phrase(c, "document.querySelector('#m-mod-gpt .design')", "The window pattern is the trap", "sees all of it")
        c.note("design", top=p["top"])
        c.move(1240, p["top"] + 6, 900)             # beside the trap sentence (over it, the pointer would open chips)
        c.note("read")
        c.pump(2.4)
        # hover the chip that cites it -> preview; then point at its GitHub link
        chip = c.rect("[...document.querySelectorAll('#m-mod-gpt .design .chip')]"
                      ".find(e => e.textContent.trim() === 'nanochat/gpt.py:301–313')")
        c.move(chip["x"] + chip["w"] / 2, chip["y"] + chip["h"] / 2, 700)
        c.note("chip")
        c.pump(1.8)
        gh = c.rect("[...document.querySelectorAll('#prev a')].find(a => /GitHub/.test(a.textContent))")
        if gh:
            c.move(gh["x"] + gh["w"] / 2, gh["y"] + gh["h"] / 2, 800)
            c.note("github", href=c.js("[...document.querySelectorAll('#prev a')].find(a => /GitHub/.test(a.textContent)).href"))
        c.pump(2.6)
        c.stop()


def flow(out: Path, url: str, dark: bool, fid: str = "chat-reply") -> None:
    with Rec(out, dark=dark) as c:
        fresh(c, url)
        c.cursor = (900, 560)
        c.mouse("mouseMoved", *c.cursor)
        # start with the Flows section in view, so the shot opens on the flow cards
        c.js(f"(() => {{ const e = document.querySelector('.flow[data-flow=\"{fid}\"]'), m = document.getElementById('main'); "
             "m.scrollTop += e.getBoundingClientRect().top - 260; })()")
        c.pump(0.6)
        c.start()
        c.pump(0.6)
        if not c.js(f"document.querySelector('.flow[data-flow=\"{fid}\"]').classList.contains('open')"):
            h = c.rect(f"document.querySelector('.flow[data-flow=\"{fid}\"] .flow-h')")
            c.click_at(h["x"] + 120, h["y"] + h["h"] / 2, 800)       # open the flow card
            c.note("open")
            c.pump(1.4)
        else:
            c.move(700, 420, 900)                                     # read its caption a moment
            c.pump(0.8)
        fs = c.rect(f"document.querySelector('.fig[data-key=\"map:{fid}\"] [data-z=\"fs\"]')")
        c.click_at(fs["x"] + fs["w"] / 2, fs["y"] + fs["h"] / 2, 800)   # Expand
        c.note("fs")
        c.pump(1.6)
        zin = c.rect("document.querySelector('.fig.fs [data-z=\"in\"]')")
        c.click_at(zin["x"] + zin["w"] / 2, zin["y"] + zin["h"] / 2, 800)
        c.note("zoom_btn", zl=c.js("document.querySelector('.fig.fs .zl').textContent"))
        c.pump(0.9)
        # Ctrl + scroll zooms at the pointer: over the calculator hop inside the loop
        lab = "[...document.querySelectorAll('.fig.fs svg text')].find(t => t.textContent.startsWith('tokenizer.decode(state'))"
        r = c.rect(lab)
        x, y = r["x"] + 40, r["y"] + r["h"] / 2
        c.move(x, y, 900)
        c.pump(0.2)
        for _ in range(5):
            c.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=-30, modifiers=2)
            c.pump(0.09)
        c.note("zoom_wheel", zl=c.js("document.querySelector('.fig.fs .zl').textContent"))
        c.pump(1.0)
        # drag to pan: pull the lanes left to follow the call into engine.py and the model
        c.move(1150, 640, 600)
        c.pump(0.2)
        c.mouse("mousePressed", 1150, 640, buttons=1)
        c.note("press", x=1150, y=640)
        c.move(560, 560, 2000, buttons=1)
        c.mouse("mouseReleased", 560, 560)
        c.note("pan")
        c.pump(1.6)
        fit = c.rect("document.querySelector('.fig.fs [data-z=\"fit\"]')")
        c.click_at(fit["x"] + fit["w"] / 2, fit["y"] + fit["h"] / 2, 900)
        c.note("fit", zl=c.js("document.querySelector('.fig.fs .zl').textContent"))
        c.pump(1.8)
        c.key("Escape")
        c.note("esc")
        c.pump(1.2)
        c.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--url", default="http://127.0.0.1:8782/")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--only", choices=["payoff", "nav", "flow"])
    a = ap.parse_args()
    out = Path(a.out)
    for name, f in (("payoff", payoff), ("nav", nav), ("flow", flow)):
        if a.only in (None, name):
            f(out / name, a.url, a.dark)


if __name__ == "__main__":
    main()

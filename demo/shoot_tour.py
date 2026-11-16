"""Shots 1 and 3: the finished nanochat map (payoff), then a short tour - Overview's "Start here", the gpt.py
Design paragraph (the window-pattern trap), and a code chip's preview with its GitHub link pinned to the commit.

    uv run --project .. python shoot_tour.py OUT [--url http://127.0.0.1:8782/] [--dark]

Writes OUT/payoff/ and OUT/tour/ (frames/*.jpg + log.jsonl), one Chrome per take, each under alarm 120.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rec import Rec, phrase


def h3(c, prefix):
    return c.rect(f"[...document.querySelectorAll('#col h3')].find(h => h.textContent.startsWith({prefix!r}))")


def scroll_main_to(c, doc_y, ms=1100):
    if c.cursor[0] < 330:                  # wheel over the sidebar would scroll the sidebar
        c.move(900, c.cursor[1], 500)
    cur = c.js("document.getElementById('main').scrollTop")
    c.smooth_scroll(doc_y - cur, ms)
    c.pump(0.3)


def payoff(out: Path, url: str, dark: bool) -> None:
    with Rec(out, dark=dark) as c:
        c.goto(url)
        c.pump(1.2)
        c.cursor = (1250, 640)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(1.0)
        c.move(1080, 560, 1400)       # drift over the Overview, as a reader would
        c.pump(2.4)
        c.stop()


def tour(out: Path, url: str, dark: bool) -> None:
    with Rec(out, dark=dark) as c:
        c.goto(url)
        c.pump(1.2)
        c.cursor = (1080, 560)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(0.6)
        # Overview -> "Start here"
        top = c.js("document.getElementById('main').scrollTop")
        r = h3(c, "Start here")
        scroll_main_to(c, top + r["y"] - 110, 1500)
        c.move(760, 330, 700)
        c.pump(3.0)
        # Modules -> gpt.py, its Design paragraph
        m = c.rect("document.querySelector('#toc a[data-sec=modules]')")
        c.click_at(m["x"] + 40, m["y"] + m["h"] / 2, 650)      # the "Modules" entry in the sidebar
        c.pump(1.2)
        top = c.js("document.getElementById('main').scrollTop")
        r = h3(c, "nanochat/gpt.py")
        scroll_main_to(c, top + r["y"] - 40 + 330, 1300)
        p = phrase(c, "document.getElementById('col')", "The window pattern is the trap", "sees all of it")
        c.move(p["x0"] + 40, p["bottom"] + 8, 700)
        c.move(p["x1"] - 30, p["bottom"] + 8, 1800)   # read along the trap sentence
        c.pump(1.4)
        # hover the chip that cites it -> preview; then point at its GitHub link
        chip = c.rect("[...document.querySelectorAll('#col .chip')]"
                      ".find(e => e.textContent.trim() === 'nanochat/gpt.py:302')")
        c.move(chip["x"] + chip["w"] / 2, chip["y"] + chip["h"] / 2, 700)
        c.pump(1.6)
        gh = c.rect("[...document.querySelectorAll('#prev a')].find(a => /GitHub/.test(a.textContent))")
        if gh:
            c.move(gh["x"] + gh["w"] / 2, gh["y"] + gh["h"] / 2, 800)
            c.note("github", href=c.js("[...document.querySelectorAll('#prev a')].find(a => /GitHub/.test(a.textContent)).href"))
        c.pump(2.8)
        c.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--url", default="http://127.0.0.1:8782/")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--only", choices=["payoff", "tour"])
    a = ap.parse_args()
    out = Path(a.out)
    if a.only in (None, "payoff"):
        payoff(out / "payoff", a.url, a.dark)
    if a.only in (None, "tour"):
        tour(out / "tour", a.url, a.dark)


if __name__ == "__main__":
    main()

"""Screenshots of T7.16 on the real nanochat map (karpathy/nanochat at 92d63d4, the T7.14 demo's map, with its two live
answers): the module graph laid out top to bottom, the live Tracer answer at a 408px panel (two sentences now spaced,
"read in source, not run", a "not supported" flag and its tooltip inside the panel), and that answer's diagram in the
overlay.

Serve a copy of the map first (never the live store: serving writes the session file), e.g.

    cp -R ~/.honeyguide/github.com__karpathy__nanochat__3a5e0bc50b12 $SCRATCH/home/
    HONEYGUIDE_HOME=$SCRATCH/home uv run honeyguide serve --repo ~/Documents/GitHub/honeyguide-targets/nanochat --port 8791
    uv run python docs/screens/shoot_t7_16.py [--url http://127.0.0.1:8791/] [--only NAME ...] [--out docs/screens/t7.16]

Headless Chrome under perl's ``alarm 60`` (tests/cdp.py), 2x, light and dark, one Chrome per shot.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from cdp import Chrome  # noqa: E402

Q_TRACER = "q_d7c4fd23c771"     # "Where is the quarter computed, and how does each layer's window size reach ..."
SHOTS = {}


def shot(name: str):
    def deco(f):
        SHOTS[name] = f
        return f
    return deco


def settle(c: Chrome, ms: int = 400) -> None:
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def open_at(c: Chrome, url: str, hash_: str = "", width: int = 1440, height: int = 900, panel: int = 408) -> None:
    c.viewport(width, height, 2)
    c.goto(url)
    c.js(f"localStorage.setItem('honeyguide.panelWidth', '{panel}')")
    c.goto(url + hash_)
    settle(c, 500)


def clip_of(c: Chrome, expr: str, pad: int = 16) -> dict:
    b = c.js(f"(() => {{ const r = ({expr}); return {{x: r.left, y: r.top, width: r.width, height: r.height}}; }})()")
    return {"x": max(0, b["x"] - pad), "y": max(0, b["y"] - pad), "width": b["width"] + 2 * pad,
            "height": b["height"] + 2 * pad, "scale": 1}


@shot("graph-top-to-bottom")
def s_graph(c, url):
    open_at(c, url, height=1200)
    c.js("document.getElementById('pclose')?.click()")
    c.js("document.getElementById('ovgraph').scrollIntoView({block: 'start'}); document.getElementById('main').scrollTop -= 24")
    settle(c)
    return clip_of(c, """(() => { const a = document.getElementById('ovgraph').getBoundingClientRect(),
      b = (document.getElementById('ovgraph-iso') || document.getElementById('ovgraph')).getBoundingClientRect();
      return {left: a.left, top: a.top, width: a.width, height: b.bottom - a.top}; })()""")


def answer_host() -> str:
    return "[...document.querySelectorAll('#pbody .ans[data-doc]')].find(a => a.querySelector('.path'))"


@shot("answer-two-sentences")
def s_answer(c, url):
    open_at(c, url, f"#q={Q_TRACER}")
    c.js(f"{answer_host()}.scrollIntoView({{block: 'start'}}); document.getElementById('pbody').scrollTop -= 12")
    settle(c)
    return clip_of(c, """(() => { const p = document.getElementById('panel').getBoundingClientRect(), a = %s.querySelector('.atext').getBoundingClientRect();
      return {left: p.left, top: Math.max(p.top, a.top), width: p.width, height: Math.min(560, a.height + 24)}; })()""" % answer_host(), pad=0)


@shot("panel-flag-408")
def s_flag(c, url):
    open_at(c, url, f"#q={Q_TRACER}")
    # the flag the live run showed past the panel's edge: two long chips and a "not supported" pill in one cite
    sel = f"[...{answer_host()}.querySelectorAll('.flag')].find(f => f.closest('.cite') && f.closest('.cite').querySelectorAll('.chip').length >= 2)"
    c.js(f"{sel}.scrollIntoView({{block: 'center'}})")
    settle(c, 900)                     # the panel's scroll event hides tooltips: let it pass before hovering
    box = c.js(f"(() => {{ const r = {sel}.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    c.mouse("mouseMoved", box[0], box[1])
    settle(c, 600)
    return clip_of(c, """(() => { const p = document.getElementById('panel').getBoundingClientRect(), f = %s.getBoundingClientRect(),
      t = document.getElementById('tip').getBoundingClientRect(); const top = Math.min(t.top, f.top) - 120, bottom = Math.max(t.bottom, f.bottom) + 120;
      return {left: p.left - 40, top, width: p.width + 40, height: bottom - top}; })()""" % sel, pad=0)


@shot("overlay")
def s_overlay(c, url):
    open_at(c, url, f"#q={Q_TRACER}", width=1600, height=1000)
    c.js("document.querySelector('[data-dgview]').click()")
    settle(c, 500)
    return {"x": 0, "y": 0, "width": 1600, "height": 1000, "scale": 1}


@shot("overlay-panel-closed")
def s_overlay_wide(c, url):
    open_at(c, url, f"#q={Q_TRACER}", width=1920, height=1000)
    c.js("document.querySelector('[data-dgview]').click()")
    settle(c, 300)
    c.js("document.getElementById('pclose').click()")
    settle(c, 500)
    return {"x": 0, "y": 0, "width": 1920, "height": 1000, "scale": 1}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8791/")
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.16"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--themes", nargs="*", default=["light", "dark"])
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in args.only or list(SHOTS):
        for theme in args.themes:
            t = time.monotonic()
            with Chrome(alarm=60) as c:
                c.media(dark=theme == "dark")
                clip = SHOTS[name](c, args.url)
                path = out / f"{name}-{theme}.png"
                data = c.call("Page.captureScreenshot", format="png", clip=clip, captureBeyondViewport=True)["data"]
                path.write_bytes(base64.b64decode(data))
                errors = c.console_errors()
            print(f"{path.name}  {time.monotonic() - t:.1f}s{'  ERRORS: ' + '; '.join(errors) if errors else ''}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

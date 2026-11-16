"""Screenshots of the flow diagrams and the module graph (T7.4) against the fixture store, served by the real
``honeyguide serve``.

    uv run python docs/screens/shoot_t7_4.py [--only NAME ...] [--out docs/screens/t7.4]

Same setup as shoot_t7_3.py (whose helpers it reuses): the base fixture variant in a temp dir, headless Chrome under
perl's ``alarm 60``, 1440x900 at 2x, light and dark, one Chrome per shot.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shoot_t7_3 import ROOT, Chrome, build, scroll_map_to, serve, settle, tip_on  # noqa: E402

SHOTS = {}


def shot(name: str):
    def deco(f):
        SHOTS[name] = f
        return f
    return deco


def open_flow(c, flow: str) -> None:
    c.js(f"document.querySelector('.flow[data-flow=\"{flow}\"] .flow-h').click()")
    settle(c, 150)


@shot("flow-step")
def s_step(c, url, ids):
    c.goto(url)
    open_flow(c, "f-step")
    scroll_map_to(c, '.flow[data-flow="f-step"]', 24)


@shot("flow-generate")
def s_gen(c, url, ids):
    c.goto(url)
    open_flow(c, "f-gen")
    scroll_map_to(c, '.flow[data-flow="f-gen"] .fbar', 24)


@shot("graph-hover")
def s_graph(c, url, ids):
    c.goto(url)
    scroll_map_to(c, "#ovgraph", 60)
    tip_on(c, '#ovgraph .dg-e[data-from="train.py"][data-to="model.py"] .gcnt')


@shot("hop-pinned")
def s_pinned(c, url, ids):
    c.goto(url)
    open_flow(c, "f-step")
    scroll_map_to(c, '.flow[data-flow="f-step"] .fig', -10)
    c.click_el('.fig[data-key="map:f-step"] .dg-a[data-kind="call"][data-hop="2"] .fn')
    settle(c, 600)


@shot("view-as-diagram")
def s_view(c, url, ids):
    c.goto(url + f"#q={ids['q3a']}")
    settle(c, 250)
    c.click_el(f'[data-dgview="resp:{ids["r3a"]}"]')
    settle(c, 200)   # mid-flash, as a reader sees it


@shot("overlay")
def s_overlay(c, url, ids):
    c.goto(url + f"#q={ids['q1c']}")
    settle(c, 250)
    c.click_el(f'[data-dgview="resp:{ids["r1c"]}"]')


@shot("panel-beside")
def s_beside(c, url, ids):
    c.goto(url + f"#q={ids['q2']}")
    open_flow(c, "f-gen")
    scroll_map_to(c, '.flow[data-flow="f-gen"] .fbar', 24)


@shot("panel-narrow-steps")
def s_narrow(c, url, ids):
    c.goto(url)
    c.js("localStorage.setItem('honeyguide.panelWidth', '720')")
    c.goto(url + f"#q={ids['q2']}")
    open_flow(c, "f-step")
    scroll_map_to(c, '.flow[data-flow="f-step"]', 24)
    c.js("localStorage.removeItem('honeyguide.panelWidth')")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.4"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--themes", nargs="*", default=["light", "dark"])
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    info = build(Path(tempfile.mkdtemp(prefix="hg-shots-")), "base")
    proc, url = serve(info)
    try:
        for name in args.only or list(SHOTS):
            for theme in args.themes:
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark")
                    SHOTS[name](c, url, info["ids"])
                    settle(c)
                    path = out / f"{name}-{theme}.png"
                    c.screenshot(path)
                    errors = c.console_errors()
                print(f"{path.name}  {time.monotonic() - t:.1f}s{'  ERRORS: ' + '; '.join(errors) if errors else ''}",
                      flush=True)
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Screenshots of the T7.13 map: the Overview's topic groups (lists, facts, commands as code) and a module's facts,
folded and expanded, against the fixture's ``v2`` variant, served by the real ``honeyguide serve``.

    uv run python docs/screens/shoot_t7_13.py [--only NAME ...] [--out docs/screens/t7.13]

Same setup as shoot_t7_3.py (whose helpers it reuses): a temp fixture, headless Chrome under perl's ``alarm 60``
(tests/cdp.py), 1440x900 at 2x, light and dark, one Chrome per shot. Overview and module shots are full-height
crops of the reading column, so a whole topic run or module reads in one image.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shoot_t7_3 import ROOT, Chrome, build, serve, settle  # noqa: E402

SHOTS = {}


def shot(name: str, **opts):
    def deco(f):
        SHOTS[name] = (f, opts)
        return f
    return deco


def column_clip(c: Chrome, first: str, last: str, pad: int = 20) -> dict:
    """A clip from the top of ``first`` to the bottom of ``last`` across the reading column, after growing the
    viewport so both are on screen (CSS pixels)."""
    box = c.js("""(() => {
      const a = document.querySelector(%s).getBoundingClientRect(), b = document.querySelector(%s).getBoundingClientRect();
      const col = document.getElementById('col').getBoundingClientRect();
      /* wide figures (the module graph) break out of the column: include them */
      let l = col.left, r = col.right;
      for (const f of document.querySelectorAll('#col .fig.wide')) {
        const fr = f.getBoundingClientRect();
        if (fr.height && fr.bottom > a.top && fr.top < b.bottom) { l = Math.min(l, fr.left); r = Math.max(r, fr.right); }
      }
      return {x: l, y: a.top, width: r - l, height: b.bottom - a.top};
    })()""" % (json.dumps(first), json.dumps(last)))
    return {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad), "width": box["width"] + 2 * pad,
            "height": box["height"] + 2 * pad, "scale": 1}


def tall(c: Chrome, url: str, height: int) -> None:
    """A viewport tall enough to hold the whole crop (the map column scrolls inside #main)."""
    c.viewport(1440, height, 2)
    c.goto(url)
    settle(c, 500)
    c.js("document.getElementById('main').scrollTop = 0")


@shot("overview")
def s_overview(c, url, ids):
    tall(c, url, 2600)
    return column_clip(c, '#s-overview h2', '#s-overview > :last-child')


@shot("modules-folded")
def s_folded(c, url, ids):
    tall(c, url, 2600)
    c.js("document.getElementById('s-modules').scrollIntoView()")
    settle(c, 200)
    return column_clip(c, '#s-modules h2', '.mod[data-block="m-data"]')


@shot("module-expanded")
def s_expanded(c, url, ids):
    tall(c, url, 1400)
    c.js("document.getElementById('s-modules').scrollIntoView()")
    c.js("document.querySelector('.mod[data-block=\"m-model\"] .more').click()")
    settle(c, 250)
    return column_clip(c, '.mod[data-block="m-train"]', '.mod[data-block="m-model"]')


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.13"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--themes", nargs="*", default=["light", "dark"])
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(SHOTS)
    tmp = Path(tempfile.mkdtemp(prefix="hg-shots-"))
    info = build(tmp, "v2")
    proc, url = serve(info)
    try:
        for name in names:
            func, _ = SHOTS[name]
            for theme in args.themes:
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark")
                    clip = func(c, url, info["ids"])
                    path = out / f"{name}-{theme}.png"
                    data = c.call("Page.captureScreenshot", format="png", clip=clip, captureBeyondViewport=True)["data"]
                    path.write_bytes(base64.b64decode(data))
                    errors = c.console_errors()
                print(f"{path.name}  {time.monotonic() - t:.1f}s{'  ERRORS: ' + '; '.join(errors) if errors else ''}",
                      flush=True)
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Screenshots of the T7.13b Modules section: components with titles, file chips, design paragraphs and related
links, folded and one expanded, and the "What this map covers" note, against the fixture's ``v2`` variant, served by
the real ``honeyguide serve``.

    uv run python docs/screens/shoot_t7_13b.py [--only NAME ...] [--out docs/screens/t7.13b]

Same setup as shoot_t7_13.py (whose helpers it reuses): a temp fixture, headless Chrome under perl's ``alarm 60``
(tests/cdp.py), 2x, light and dark, one Chrome per shot. Each shot is a full-height crop of the reading column.
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shoot_t7_3 import ROOT, Chrome, build, serve, settle  # noqa: E402
from shoot_t7_13 import column_clip, tall  # noqa: E402

SHOTS = {}


def shot(name: str):
    def deco(f):
        SHOTS[name] = f
        return f
    return deco


def fold_all(c: Chrome) -> None:
    """Close every module (m-train opens by itself: a question sits on one of its folded facts)."""
    c.js("document.querySelectorAll('.mod.open .more').forEach(b => b.click())")
    settle(c, 200)


@shot("modules-folded")
def s_folded(c, url):
    tall(c, url, 3200)
    fold_all(c)
    c.js("document.getElementById('s-modules').scrollIntoView()")
    settle(c, 200)
    return column_clip(c, '#s-modules h2', '.mod[data-block="m-tok"]')


@shot("module-expanded")
def s_expanded(c, url):
    tall(c, url, 2400)
    c.js("document.getElementById('s-modules').scrollIntoView()")
    if not c.js("document.querySelector('.mod[data-block=\"m-train\"]').classList.contains('open')"):
        c.js("document.querySelector('.mod[data-block=\"m-train\"] .more').click()")
    settle(c, 250)
    return column_clip(c, '#s-modules h2', '.mod[data-block="m-train"]')


@shot("coverage")
def s_coverage(c, url):
    tall(c, url, 3200)
    fold_all(c)
    c.js("document.querySelector('#s-modules .cov').scrollIntoView()")
    settle(c, 200)
    return column_clip(c, '.mod[data-block="m-tok"]', '#s-modules .cov')


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.13b"))
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
            for theme in args.themes:
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark")
                    clip = SHOTS[name](c, url)
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

"""Screenshots of T7.15 on the fixture's ``v2`` map (three claims the Checker flagged): the module graph by component,
a not-supported claim at rest and on hover, and the sidebar's "Needs a look" list, served by the real ``honeyguide
serve``.

    uv run python docs/screens/shoot_t7_15.py [--only NAME ...] [--out docs/screens/t7.15]

Same setup as shoot_t7_13b.py: a temp fixture, headless Chrome under perl's ``alarm 60`` (tests/cdp.py), 2x, light
and dark, one Chrome per shot.
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
from shoot_t7_13 import column_clip, tall  # noqa: E402

SHOTS = {}


def shot(name: str):
    def deco(f):
        SHOTS[name] = f
        return f
    return deco


def claim_sel(ids: dict, key: str) -> str:
    return f'#col .claim[data-claim="{ids[key]}"]'


def around(c: Chrome, selector: str, extra_selector: str | None = None, pad: int = 24) -> dict:
    """A clip around ``selector``'s block (and the tooltip, when it is showing), across the reading column."""
    box = c.js("""(() => {
      const el = document.querySelector(%s).closest('.bfacts,.blist,.mod,p.blk') || document.querySelector(%s);
      const r = el.getBoundingClientRect(), col = document.getElementById('col').getBoundingClientRect();
      let top = r.top, bottom = r.bottom;
      const tip = document.getElementById('tip');
      if (tip.classList.contains('on')) { const t = tip.getBoundingClientRect(); top = Math.min(top, t.top); bottom = Math.max(bottom, t.bottom); }
      return {x: col.left, y: top, width: col.width, height: bottom - top};
    })()""" % (json.dumps(selector), json.dumps(selector)))
    return {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad), "width": box["width"] + 2 * pad,
            "height": box["height"] + 2 * pad, "scale": 1}


@shot("graph-by-component")
def s_graph(c, url, ids):
    tall(c, url, 1800)
    c.js("document.getElementById('ovgraph').scrollIntoView({block: 'center'})")
    settle(c, 300)
    return column_clip(c, "#ovgraph", "#ovcap")


@shot("not-supported-rest")
def s_rest(c, url, ids):
    tall(c, url, 1400)
    sel = claim_sel(ids, "deps")
    c.js(f"document.querySelector('{sel}').scrollIntoView({{block: 'center'}})")
    settle(c, 300)
    c.mouse("mouseMoved", 2, 2)
    settle(c, 200)
    return around(c, sel)


@shot("not-supported-hover")
def s_hover(c, url, ids):
    tall(c, url, 1400)
    sel = claim_sel(ids, "deps")
    c.js(f"document.querySelector('{sel}').scrollIntoView({{block: 'center'}})")
    settle(c, 300)
    c.hover_el(sel)
    settle(c, 350)
    return around(c, sel)


@shot("needs-a-look")
def s_needs(c, url, ids):
    tall(c, url, 900)
    c.click_el("#needs .nd-h")
    settle(c, 200)
    c.hover_el(f'#ndl a[data-ns="{ids["m-io"]}"]')
    settle(c, 350)
    box = c.js("""(() => { const s = document.getElementById('side').getBoundingClientRect(),
      n = document.getElementById('needs').getBoundingClientRect(), t = document.getElementById('tip').getBoundingClientRect();
      return {x: 0, y: 0, width: Math.max(s.right, t.right) + 16, height: Math.max(n.bottom, t.bottom) + 24}; })()""")
    return {**box, "scale": 1}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.15"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--themes", nargs="*", default=["light", "dark"])
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(SHOTS)
    tmp = Path(tempfile.mkdtemp(prefix="hg-shots-"))
    info = build(tmp, "v2")
    from honeyguide.store import Store
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    ids = {c["key"]: c["id"] for c in store.load("map")["claims"]}
    proc, url = serve(info)
    try:
        for name in names:
            for theme in args.themes:
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark")
                    clip = SHOTS[name](c, url, ids)
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

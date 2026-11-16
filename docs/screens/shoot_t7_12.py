"""Screenshots of the logo, favicon and agent avatars on the map page (T7.12), against the fixture store, served by
the real ``honeyguide serve``.

    uv run python docs/screens/shoot_t7_12.py [--only NAME ...] [--out docs/screens/t7.12]

Same setup as shoot_t7_3.py (whose helpers it reuses): fixture variants in a temp dir, headless Chrome under perl's
``alarm 60``, 1440x900 at 2x, light and dark, one Chrome per shot. Each shot is a crop around the part it shows
(``clip``), so the avatars are big enough to judge.

A headless Chrome has no tab strip, so ``favicon`` draws one: a plain page (about:blank) with a mock tab holding the
served /favicon.svg (fetched from the server, shown as a data: URL) at 16px, and the same file at 32 and 64px. Everything else is the real page.

``base`` gets two extra questions before it is served: one open (nobody has picked it up: the waiting state) and one
failed (the failed state).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shoot_t7_3 import ROOT, Chrome, build, scroll_panel_to, serve, settle  # noqa: E402
from t7_page_fixture import waiting_and_failed  # noqa: E402

SHOTS = {}


def shot(name: str, variant: str, **opts):
    def deco(f):
        SHOTS[name] = (variant, f, opts)
        return f
    return deco


def box(c: Chrome, selector: str, pad: int = 12) -> dict:
    """The element's box plus ``pad`` on every side, in CSS pixels (the crop)."""
    b = c.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); "
             "return {x: r.left, y: r.top, width: r.width, height: r.height}; })()")
    return {"x": max(0, b["x"] - pad), "y": max(0, b["y"] - pad), "width": b["width"] + 2 * pad,
            "height": b["height"] + 2 * pad, "scale": 1}


@shot("brand", "base")
def s_brand(c, url, ids):
    c.goto(url)
    return {"x": 0, "y": 0, "width": 240, "height": 76, "scale": 1}


@shot("favicon", "base")
def s_favicon(c, url, ids):
    with urllib.request.urlopen(url + "favicon.svg", timeout=10) as r:   # the served bytes, as a data: URL
        fav = "data:image/svg+xml;base64," + base64.b64encode(r.read()).decode()
    c.call("Page.navigate", url="about:blank")
    c.wait("document.readyState === 'complete' && location.href === 'about:blank'", 10)
    dark = c.js("matchMedia('(prefers-color-scheme: dark)').matches")
    bar, tab, ink = ("#202124", "#35363A", "#E8EAED") if dark else ("#DEE1E6", "#FFFFFF", "#202124")
    c.js("""(() => {
      document.body.style.cssText = 'margin:0;background:%(bar)s;font:12px -apple-system,BlinkMacSystemFont,sans-serif';
      document.body.innerHTML = `
        <div style="display:flex;align-items:flex-end;height:40px;padding:0 8px">
          <div style="display:flex;align-items:center;gap:8px;width:220px;height:32px;padding:0 12px;background:%(tab)s;
                      border-radius:8px 8px 0 0;color:%(ink)s"><img src="%(fav)s" width="16" height="16">Honeyguide
            <span style="margin-left:auto;opacity:.6">×</span></div></div>
        <div style="display:flex;align-items:center;gap:20px;padding:16px 20px;background:%(tab)s;color:%(ink)s">
          <img src="%(fav)s" width="16" height="16"><img src="%(fav)s" width="32" height="32">
          <img src="%(fav)s" width="64" height="64"><span style="opacity:.7">/favicon.svg at 16, 32 and 64px
          (a mock tab: headless Chrome has no tab strip)</span></div>`;
      return Promise.all([...document.images].map(i => i.decode()));
    })()""" % {"bar": bar, "tab": tab, "ink": ink, "fav": fav})
    return {"x": 0, "y": 0, "width": 720, "height": 140, "scale": 1}


@shot("answer-header", "base")
def s_answer(c, url, ids):
    c.goto(url + f"#q={ids['q3a']}")
    settle(c, 2500)   # after the hop: the done pose it holds
    return box(c, f'.nd[data-id="{ids["q3a"]}"] > .nd-b > .by', 16) | {"width": 380}


@shot("answer-header-hop", "base")
def s_answer_hop(c, url, ids):
    c.goto(url + f"#q={ids['q3a']}")
    settle(c, 380)    # mid-hop
    return box(c, f'.nd[data-id="{ids["q3a"]}"] > .nd-b > .by', 16) | {"width": 380}


@shot("at-work", "working")
def s_work(c, url, ids):
    c.goto(url + f"#q={ids['q5']}")
    scroll_panel_to(c, f'.nd[data-id="{ids["q5"]}"]', 60)
    settle(c, 900)
    return box(c, f'.nd[data-id="{ids["q5"]}"]', 8)


@shot("at-work-reduced", "working", reduced=True)
def s_work_rm(c, url, ids):
    return s_work(c, url, ids)


@shot("busy", "working")
def s_busy(c, url, ids):
    c.goto(url)
    settle(c, 700)
    return box(c, "#top", 16)


@shot("waiting", "base")
def s_wait(c, url, ids):
    c.goto(url + f"#q={ids['qwait']}")
    settle(c, 600)
    return box(c, f'.nd[data-id="{ids["qwait"]}"]', 8)


@shot("failed", "base")
def s_failed(c, url, ids):
    c.goto(url + f"#q={ids['qfail']}")
    return box(c, f'.nd[data-id="{ids["qfail"]}"]', 8)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.12"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--themes", nargs="*", default=["light", "dark"])
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(SHOTS)
    tmp = Path(tempfile.mkdtemp(prefix="hg-shots-"))
    infos, servers = {}, []
    try:
        for variant in sorted({SHOTS[n][0] for n in names}):
            info = build(tmp, variant)
            if variant == "base":
                waiting_and_failed(info)
            proc, url = serve(info)
            servers.append(proc)
            infos[variant] = (info, url)
        for name in names:
            variant, func, opts = SHOTS[name]
            info, url = infos[variant]
            for theme in args.themes:
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark", reduced_motion=bool(opts.get("reduced")))
                    clip = func(c, url, info["ids"])
                    path = out / f"{name}-{theme}.png"
                    data = c.call("Page.captureScreenshot", format="png", clip=clip)["data"]
                    path.write_bytes(base64.b64decode(data))
                    errors = c.console_errors()
                print(f"{path.name}  {time.monotonic() - t:.1f}s{'  ERRORS: ' + '; '.join(errors) if errors else ''}",
                      flush=True)
    finally:
        for proc in servers:
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

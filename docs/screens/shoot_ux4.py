"""Screenshots of UX v4 (T7.17 + T7.18) on the REAL maps: nanochat (karpathy/nanochat at 92d63d4, with its two live
answers) and waku-agent (ShenSeanChen/waku-agent at 2c7e7e6), light and dark, 1440x900 at 2x.

Serve copies of the maps first (never the live store: serving writes the session file), with the repo card stored:

    cp -R ~/.honeyguide/github.com__karpathy__nanochat__3a5e0bc50b12 $SCRATCH/home/
    cp -R ~/.honeyguide/github.com__shenseanchen__waku-agent__427d2ad20744 $SCRATCH/home/
    HONEYGUIDE_HOME=$SCRATCH/home uv run honeyguide repo-info --repo <nanochat checkout> --save
    HONEYGUIDE_HOME=$SCRATCH/home uv run honeyguide serve --repo <nanochat checkout> --port 8792
    HONEYGUIDE_HOME=$SCRATCH/home uv run honeyguide serve --repo <waku-agent checkout> --port 8793
    uv run python docs/screens/shoot_ux4.py [--only NAME ...] [--maps nanochat waku] [--out docs/screens/ux4]

Then ``--compose BEFORE_DIR`` writes the design-*.png before/after pairs (the T7.16 page's shots of the same views,
taken before this change, on the left).

Headless Chrome under perl's ``alarm 60`` (tests/cdp.py), one Chrome per shot.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from cdp import Chrome  # noqa: E402

# url, answered question, module, flow, component for full screen / the panel, component for focus mode
# (review r2: focus on gpt.py, as the demo GIF does, so the post's tour follows one component)
MAPS = {"nanochat": ("http://127.0.0.1:8792/", "q_d7c4fd23c771", "mod-gpt", "chat-reply", "mod-engine", "mod-gpt"),
        "waku": ("http://127.0.0.1:8793/", None, "mod-loop", "turn", "mod-loop", "mod-loop")}
SHOTS = {}
# review r2: a window as tall as the swimlane needs once the whole of it is on screen (no empty lower third)
FLOW_H = {"chat-reply": 680}


def shot(name: str):
    def deco(f):
        SHOTS[name] = f
        return f
    return deco


def settle(c: Chrome, ms: int = 450) -> None:
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def open_at(c: Chrome, url: str, hash_: str = "", width: int = 1440, height: int = 900) -> None:
    c.viewport(width, height, 2)
    c.goto(url)
    c.js("localStorage.clear(); localStorage.setItem('honeyguide.panelWidth', '408')")
    c.goto(url + hash_)
    settle(c, 600)
    if not hash_:
        c.js("document.getElementById('pclose')?.click()")
        settle(c, 200)


def scroll_to(c: Chrome, sel: str, off: int = 72) -> None:
    c.js(f"(() => {{ const e = document.querySelector({sel!r}); const m = document.getElementById('main'); "
         f"m.scrollTop += e.getBoundingClientRect().top - m.getBoundingClientRect().top - {off}; }})()")
    settle(c)


def comp_id(c: Chrome, want: str) -> str:
    """The component id on the map (falls back to the busiest component when the guess is not on it)."""
    return c.js(f"""(() => {{ const s = document.querySelector('#ovgraph .dgwrap > svg');
      if (s.querySelector('.dg-node[data-comp="{want}"]')) return '{want}';
      const n = {{}}; for (const e of s.querySelectorAll('.dg-e')) {{ n[e.dataset.from] = (n[e.dataset.from] || 0) + 1; n[e.dataset.to] = (n[e.dataset.to] || 0) + 1; }}
      return Object.entries(n).sort((a, b) => b[1] - a[1])[0][0]; }})()""")


@shot("top")
def s_top(c, m):
    open_at(c, m[0])


@shot("contents-scrollspy")
def s_spy(c, m):
    open_at(c, m[0])
    c.js("document.querySelectorAll('#toc a[data-sub^=\"m-\"]')[3].click()")
    settle(c, 600)


@shot("module")
def s_module(c, m):
    open_at(c, m[0])
    scroll_to(c, f"#m-{m[2]}", 72)
    c.js(f"document.querySelector('#m-{m[2]} [data-more]')?.click()")
    settle(c)


@shot("graph")
def s_graph(c, m):
    open_at(c, m[0], height=1100)
    scroll_to(c, "#t-graph", 60)


@shot("graph-focus")
def s_focus(c, m):
    """The whole map (every band and every lit curve) just under the sticky section header, the focus card below it
    (review r2: the T7.17 shot scrolled to the component and cut off the Entry points band and its callers)."""
    open_at(c, m[0], height=1100)
    cid = comp_id(c, m[5])
    c.js(f"document.querySelector('#ovgraph .dg-node[data-comp=\"{cid}\"]').dispatchEvent(new MouseEvent('click', {{bubbles: true}}))")
    settle(c)
    c.js("(() => { const s = document.querySelector('#ovgraph .dgwrap > svg'), m = document.getElementById('main'), "
         "h = document.querySelector('#main .sh'); const top = h ? h.getBoundingClientRect().height : 54; "
         "m.scrollTop += s.getBoundingClientRect().top - m.getBoundingClientRect().top - top - 2; })()")
    settle(c)


@shot("graph-fullscreen-zoomed")
def s_fs(c, m):
    open_at(c, m[0])
    c.js("document.querySelector('#ovgraph [data-z=\"fs\"]').click()")
    settle(c, 500)
    cid = comp_id(c, m[4])
    c.js(f"document.querySelector('#ovgraph .dg-node[data-comp=\"{cid}\"]').dispatchEvent(new MouseEvent('click', {{bubbles: true}}))")
    settle(c)
    c.js("document.querySelector('#ovgraph [data-z=\"in\"]').click()")
    settle(c)
    c.js(f"(() => {{ const n = document.querySelector('#ovgraph .dg-node[data-comp=\"{cid}\"]'), w = document.querySelector('#ovgraph .dgwrap'); "
         "const r = n.getBoundingClientRect(), wr = w.getBoundingClientRect(); w.scrollLeft += r.left + r.width / 2 - (wr.left + wr.width / 2); "
         "w.scrollTop += r.top + r.height / 2 - (wr.top + wr.height / 2); })()")
    settle(c)


@shot("flow-fullscreen")
def s_flow(c, m):
    open_at(c, m[0], height=FLOW_H.get(m[3], 900))
    c.js(f"document.querySelector('.flow[data-flow=\"{m[3]}\"] .flow-h').click()")
    settle(c)
    c.js(f"document.querySelector('.fig[data-key=\"map:{m[3]}\"] [data-z=\"fs\"]').click()")
    settle(c, 600)
    # review r2: at Fit a wide swimlane stops at the readable floor (85%) and its right-hand lanes run off the screen;
    # zoom out (the toolbar's minus) until the whole swimlane is on screen
    fig = f".fig[data-key=\"map:{m[3]}\"]"
    c.js(f"document.querySelector('{fig} [data-z=\"fit\"]').click()")
    settle(c, 300)
    for _ in range(6):
        if c.js(f"(() => {{ const w = document.querySelector('{fig} .dgwrap'); return w.scrollWidth <= w.clientWidth + 1 && w.scrollHeight <= w.clientHeight + 1; }})()"):
            break
        c.js(f"document.querySelector('{fig} [data-z=\"out\"]').click()")
        settle(c, 300)
    settle(c, 300)


@shot("panel")
def s_panel(c, m):
    if m[1]:
        open_at(c, m[0], f"#q={m[1]}")
        settle(c, 400)
        c.js("document.getElementById('pbody').scrollTop = 0")
        # when the question's passage is no longer in the map (it was rewritten since), the page cannot scroll to it:
        # show the module the question is about beside the panel, as the passage's own scroll would
        if not c.js("!!document.querySelector('#main .hl, #main mark, #main [data-cur]')"):
            scroll_to(c, f"#m-{m[2]}", 72)
            c.js(f"(() => {{ const w = [...document.querySelectorAll('#m-{m[2]} .design, #m-{m[2]} [class*=design]')][0]; "
                 "if (w) { const mm = document.getElementById('main'); mm.scrollTop += w.getBoundingClientRect().top - 140; } })()")
            settle(c)
    else:   # no answers on this map: the panel as "Ask about this component" opens it
        open_at(c, m[0])
        cid = comp_id(c, m[4])
        c.js(f"document.querySelector('#ovgraph .dg-node[data-comp=\"{cid}\"]').dispatchEvent(new MouseEvent('click', {{bubbles: true}}))")
        settle(c)
        c.js("document.querySelector('#gfocus [data-gask]').click()")
        settle(c)
        c.js("document.activeElement.blur()")
    settle(c, 500)


def capture(c: Chrome, path: Path) -> None:
    data = c.call("Page.captureScreenshot", format="png")["data"]
    path.write_bytes(base64.b64decode(data))


COMPOSE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;background:#E9E6E0;font:600 22px -apple-system,Inter,sans-serif;color:#24272B}
.row{display:flex;gap:24px;padding:24px}.c{flex:1}.c img{width:100%%;display:block;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.12)}
.t{margin:0 0 10px 4px}.t span{font-weight:400;color:#66717D}
</style></head><body><div class="row"><div class="c"><p class="t">Before <span>· T7.16 page</span></p><img src="%s"></div>
<div class="c"><p class="t">After <span>· UX v4</span></p><img src="%s"></div></div></body></html>"""


def compose(before: Path, out: Path) -> None:
    pairs = {"design-overview-top": ("overview-light.png", "nanochat-top-light.png"),
             "design-module": ("module-light.png", "nanochat-module-light.png"),
             "design-component-graph": ("graph-light.png", "nanochat-graph-light.png")}
    for name, (b, a) in pairs.items():
        html = out / f".{name}.html"
        html.write_text(COMPOSE % ((before / b).resolve().as_uri(), (out / a).resolve().as_uri()))
        with Chrome(width=2000, height=700, alarm=60) as c:
            c.viewport(2000, 700, 1)
            c.call("Page.navigate", url=html.resolve().as_uri())
            c.wait("document.readyState === 'complete' && [...document.images].every(i => i.complete && i.naturalWidth)", 20)
            h = c.js("document.body.scrollHeight")
            c.viewport(2000, h, 1)
            settle(c, 200)
            capture(c, out / f"{name}.png")
        html.unlink()
        print(f"{name}.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--maps", nargs="*", default=list(MAPS))
    ap.add_argument("--url", nargs="*", default=[], metavar="MAP=URL", help="serve a map on another port, e.g. nanochat=http://127.0.0.1:8795/")
    ap.add_argument("--out", default=str(ROOT / "docs/screens/ux4"))
    ap.add_argument("--compose", help="the directory of the before shots: write the design-*.png pairs and stop")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.compose:
        compose(Path(args.compose), out)
        return 0
    urls = dict(u.split("=", 1) for u in args.url)
    for mname in args.maps:
        m = (urls.get(mname, MAPS[mname][0]),) + MAPS[mname][1:]
        for name, f in SHOTS.items():
            if args.only and name not in args.only:
                continue
            for dark in (False, True):
                with Chrome(alarm=60) as c:
                    c.media(dark=dark)
                    f(c, m)
                    errs = c.console_errors()
                    capture(c, out / f"{mname}-{name}-{'dark' if dark else 'light'}.png")
                    print(f"{mname}-{name}-{'dark' if dark else 'light'}.png" + (f"  ERRORS {errs}" if errs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

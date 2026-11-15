"""Screenshots of the map page (T7.3) against the fixture store, served by the real ``honeyguide serve``.

    uv run python docs/screens/shoot_t7_3.py [--only NAME ...] [--out docs/screens/t7.3]

Builds every fixture variant (tests/t7_page_fixture.py) in a temp dir, serves each, and drives headless Chrome
(tests/cdp.py; every Chrome under perl's ``alarm 60``) at 1440x900, 2x, light and dark. One Chrome per shot, so no
state leaks between shots.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from cdp import Chrome  # noqa: E402
from t7_page_fixture import build, set_visits  # noqa: E402

from honeyguide.store import Store  # noqa: E402


def serve(info: dict) -> tuple[subprocess.Popen, str]:
    env = dict(os.environ, HONEYGUIDE_HOME=info["home"])
    proc = subprocess.Popen([sys.executable, "-m", "honeyguide.cli", "serve", "--repo", info["repo"], "--port", "0"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    return proc, json.loads(proc.stdout.readline())["url"]


def settle(c: Chrome, ms: int = 450) -> None:
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def select_text(c: Chrome, root: str, phrase: str) -> None:
    """Select ``phrase`` inside ``root`` and release the mouse, as a reader would."""
    c.js("""(() => {
      const root = document.querySelector(%s), phrase = %s;
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const nodes = []; let t = "";
      while (w.nextNode()) { nodes.push([w.currentNode, t.length]); t += w.currentNode.data; }
      const i = t.indexOf(phrase); const at = k => { for (let j = nodes.length - 1; j >= 0; j--) if (nodes[j][1] <= k) return [nodes[j][0], k - nodes[j][1]]; };
      const r = document.createRange(); const [a, ao] = at(i); const [b, bo] = at(i + phrase.length - 1);
      r.setStart(a, ao); r.setEnd(b, bo + 1);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      r.startContainer.parentElement.scrollIntoView({block: "center"});
    })()""" % (json.dumps(root), json.dumps(phrase)))
    settle(c, 100)
    c.js("document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))")


def scroll_map_to(c: Chrome, selector: str, off: int = 160) -> None:
    c.js(f"(() => {{ const m = document.getElementById('main'), e = document.querySelector({json.dumps(selector)}); "
         f"m.scrollTop += e.getBoundingClientRect().top - m.getBoundingClientRect().top - {off}; }})()")


def scroll_panel_to(c: Chrome, selector: str, off: int = 40) -> None:
    c.js(f"(() => {{ const b = document.getElementById('pbody'), e = document.querySelector({json.dumps(selector)}); "
         f"b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top - {off}; }})()")


def tip_on(c: Chrome, selector: str) -> None:
    settle(c, 150)
    c.hover_el(selector)
    settle(c, 200)


SHOTS = {}


def shot(name: str, variant: str, **opts):
    def deco(f):
        SHOTS[name] = (variant, f, opts)
        return f
    return deco


@shot("default", "base")
def s_default(c, url, ids):
    c.goto(url)


@shot("answer", "base")
def s_answer(c, url, ids):
    c.goto(url + f"#q={ids['q1']}")
    c.click_el(f'.nd[data-id="{ids["q1"]}"] > .nd-q [data-node]')  # select the root answer (not the latest follow-up)
    for q in ("q1a", "q1b", "q1c"):
        c.click_el(f'[data-tog="{ids[q]}"]')
    scroll_panel_to(c, f'.nd[data-id="{ids["q1"]}"]', 60)
    tip_on(c, ".panel .flag")


@shot("branch", "base")
def s_branch(c, url, ids):
    c.goto(url + f"#q={ids['q1a']}")
    c.click_el(f'[data-tog="{ids["q1b"]}"]')
    c.click_el(f'[data-tog="{ids["q1c"]}"]')
    scroll_panel_to(c, f'.nd[data-id="{ids["q1"]}"] .ans', 120)
    c.click_el(f'.nd[data-id="{ids["q1a"]}"] .chip')
    settle(c, 600)


@shot("preview", "base")
def s_preview(c, url, ids):
    c.goto(url)
    scroll_map_to(c, '[data-block="m-engine"]', 260)
    c.click_el('[data-block="m-engine"] .chip')
    settle(c, 600)
    tip_on(c, ".prev a.lk[href^='https://github.com']")


@shot("select", "base")
def s_select(c, url, ids):
    c.goto(url)
    select_text(c, '[data-block="b-data"]', "Each GPU reads its own interleaved slice of every shard")


@shot("notes", "base")
def s_notes(c, url, ids):
    c.goto(url)
    c.click_el("#top")
    settle(c, 300)   # the panel slides in
    c.click_el('[data-tab="notes"]')


@shot("discussions", "working")
def s_nav(c, url, ids):
    c.goto(url)
    c.click_el("#top")
    settle(c, 300)   # the panel slides in
    c.click_el('[data-tab="nav"]')


@shot("working", "working")
def s_working(c, url, ids):
    c.goto(url + f"#q={ids['q5']}")
    c.click_el(f'[data-tog="{ids["q1a"]}"]')
    c.click_el(f'[data-tog="{ids["q1b"]}"]')
    c.click_el(f'[data-tog="{ids["q1c"]}"]')
    scroll_panel_to(c, f'.nd[data-id="{ids["q4"]}"]', 60)


@shot("working-reduced", "working", reduced=True)
def s_working_rm(c, url, ids):
    s_working(c, url, ids)


@shot("busy", "working")
def s_busy(c, url, ids):
    c.goto(url)
    scroll_map_to(c, "#s-modules", 40)


@shot("narrow", "base", storage={"panelWidth": "320"})
def s_narrow(c, url, ids):
    c.goto(url + f"#q={ids['q2']}")


@shot("wide", "base", storage={"panelWidth": "720", "rail": "1"})
def s_wide(c, url, ids):
    c.goto(url + f"#q={ids['q1c']}")
    c.click_el(f'[data-tog="{ids["q1a"]}"]')
    c.click_el(f'[data-tog="{ids["q1b"]}"]')
    scroll_panel_to(c, f'.nd[data-id="{ids["q1c"]}"]', 50)


@shot("refreshed", "refreshed", fresh_visit=True)
def s_refreshed(c, url, ids):
    c.goto(url)


@shot("refreshed-modules", "refreshed", fresh_visit=True)
def s_refreshed_mod(c, url, ids):
    c.goto(url)
    scroll_map_to(c, "#s-modules", 40)
    tip_on(c, '[data-block="m-train"] .rck')


@shot("empty", "empty")
def s_empty(c, url, ids):
    c.goto(url)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs/screens/t7.3"))
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
            proc, url = serve(info)
            servers.append(proc)
            infos[variant] = (info, url)
        for name in names:
            variant, func, opts = SHOTS[name]
            info, url = infos[variant]
            for theme in args.themes:
                if opts.get("fresh_visit"):   # the page posts a visit on load: put the last visit before the refresh
                    st = Store(Path(info["store"]).name, root=Path(info["home"]))
                    set_visits(st, **info["visits"])
                t = time.monotonic()
                with Chrome() as c:
                    c.media(dark=theme == "dark", reduced_motion=bool(opts.get("reduced")))
                    if opts.get("storage"):
                        c.goto(url)
                        c.js("localStorage.clear();" + "".join(
                            f"localStorage.setItem('honeyguide.{k}', {json.dumps(v)});" for k, v in opts["storage"].items()))
                        if opts.get("fresh_visit"):
                            set_visits(st, **info["visits"])
                    func(c, url, info["ids"])
                    settle(c)
                    path = out / f"{name}-{theme}.png"
                    c.screenshot(path)
                    errors = c.console_errors()
                print(f"{path.name}  {time.monotonic() - t:.1f}s{'  ERRORS: ' + '; '.join(errors) if errors else ''}",
                      flush=True)
    finally:
        for proc in servers:
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

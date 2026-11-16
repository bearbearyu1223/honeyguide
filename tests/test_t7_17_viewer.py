"""T7.17 + T7.18 (UX v4) on the map page, against the real server and the v2 fixture store, in headless Chrome:

- the component map: focus mode (callers and callees stay, the rest fades; the focus card lists the calls with code
  chips; Esc and a click on empty space reset), the show-all toggle, Tab through nodes and Enter to focus, "Ask about
  this component" (the panel opens anchored to the module, the question prefilled, nothing sent);
- the viewer on every diagram: zoom (buttons, Ctrl/Cmd + scroll at the pointer, + / - / 0), drag to pan, fit, full
  screen open and close (Esc) for the component map, a flow swimlane and the Tracer overlay; at fit no text in the
  component map is under 12 px;
- the contents outline: sub-sections, scroll-spy on both levels; Find filters the outline and finds text in the map;
- the repo card from ``document.repo`` (names only, "as of" on GitHub counts, nothing fetched); light and dark;
- nothing inline: no style attribute in any diagram (the CSP), and every resource is the page's own.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import build

from honeyguide.gitio import Repo
from honeyguide.server import make_server
from honeyguide.store import Store

REPO_CARD = {"schema": 1, "name": "example/tinytrain", "url": "https://github.com/example/tinytrain", "host": "github.com",
             "generated_at": "2026-11-16T05:00:00Z", "default_branch": "main",
             "commit": {"sha": "0123456789abcdef0123456789abcdef01234567", "date": "2026-11-01T10:00:00+00:00"},
             "first_commit_date": "2025-01-02T10:00:00+00:00", "last_commit_date": "2026-11-01T10:00:00+00:00",
             "commits": 1234, "languages": [{"name": "Python", "lines": 900, "share": 0.9},
                                            {"name": "Shell", "lines": 100, "share": 0.1}],
             "source_lines": 1000, "license": {"spdx": "MIT", "file": "LICENSE"},
             "contributors": [{"name": "Ada Lovelace", "commits": 30}, {"name": "Grace Hopper", "commits": 4}],
             "contributor_count": 9, "readme": {"path": "README.md", "title": "tinytrain", "title_line": 1,
                                                "description": "A tiny GPT trainer you can read in one sitting.",
                                                "description_line": 3},
             "github": {"stars": 4321, "forks": 87, "open_issues": 5, "topics": ["llm", "teaching"],
                        "description": None, "as_of": "2026-11-16"}}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("t717"), "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    store.update("map", lambda layer: layer["document"].__setitem__("repo", REPO_CARD))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info.update(store_obj=store, url=f"http://127.0.0.1:{server.server_address[1]}/")
    yield info
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=120) as c:
        yield c


def settle(c, ms=150):
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def fresh(c, url, width=1440, height=900, dark=False):
    c.viewport(width, height)
    c.media(dark=dark)
    c.goto(url)
    c.js("localStorage.clear()")
    c.goto(url)
    settle(c, 200)


SVG = "#ovgraph .dgwrap > svg"


def classes(c, sel):
    return c.js(f"Object.fromEntries([...document.querySelectorAll({json.dumps(sel)})].map(e => [e.dataset.comp || (e.dataset.from + '>' + e.dataset.to), [...e.classList].join(' ')]))")


# -- the component map: focus, show all, keyboard, ask --------------------------------------------------------------


def test_focus_mode_keeps_callers_and_callees_and_resets(site, chrome):
    c = chrome
    fresh(c, site["url"])
    c.click_el('#ovgraph [data-gall="1"]')                      # every call, so every neighbour's line is drawn
    c.click_el(f'{SVG} .dg-node[data-comp="m-model"] .gbox')
    assert c.js(f"document.querySelector('{SVG}').classList.contains('focus')")
    nodes = classes(c, f"{SVG} .dg-node")
    on = {k for k, v in nodes.items() if " on" in f" {v}"}
    assert on == {"m-model", "m-train", "m-engine"}             # model.py, its two callers; data.py fades
    assert "sel" in nodes["m-model"].split() and "on" not in nodes["m-data"].split()
    settle(c, 300)                                                # the fade's 160 ms transition
    assert c.js(f"getComputedStyle(document.querySelector('{SVG} .dg-node[data-comp=\"m-data\"]')).opacity") == "0.14"
    edges = classes(c, f"{SVG} .dg-e")
    assert {k for k, v in edges.items() if "on" in v.split()} == {"m-train>m-model", "m-engine>m-model"}
    # the focus card: kind, name, its callers with their calls as code chips, the two actions
    card = c.js("document.getElementById('gfocus').innerText")
    low = card.lower()
    assert "model.py" in card and "called by" in low and "ask about this component" in low and "open its module" in low
    assert "calls 1" not in low and "\ncalls" not in low          # model.py calls nothing traced
    assert c.js("document.querySelectorAll('#gfocus .chip[data-claim]').length") >= 3
    c.click_el("#gfocus .chip[data-claim]")                       # a chip opens the code preview, as everywhere
    c.wait("document.getElementById('prev').style.display === 'block' && !!document.querySelector('#prev pre')", 5)
    c.key("Escape")                                              # first Esc: the pinned preview
    assert c.js(f"document.querySelector('{SVG}').classList.contains('focus')")
    c.key("Escape")                                              # then the focus
    assert not c.js(f"document.querySelector('{SVG}').classList.contains('focus')")
    assert c.js("document.getElementById('gfocus').hidden")
    # a click on empty space in the map resets it too
    c.click_el(f'{SVG} .dg-node[data-comp="m-data"] .gbox')
    assert c.js(f"document.querySelector('{SVG}').classList.contains('focus')")
    box = c.box(f"{SVG} .bandbg")
    c.click(box["x"] + 30, box["y"] + box["h"] - 6)
    assert not c.js(f"document.querySelector('{SVG}').classList.contains('focus')")


def test_show_all_toggle(site, chrome):
    c = chrome
    fresh(c, site["url"])
    shown = f"[...document.querySelectorAll('{SVG} .dg-e')].filter(e => getComputedStyle(e).display !== 'none').length"
    total = c.js(f"document.querySelectorAll('{SVG} .dg-e').length")
    main = c.js(shown)
    assert c.js(f"document.querySelector('{SVG}').dataset.view") == "main" and main < total
    label = c.js("document.querySelector('#ovgraph .gview').innerText")
    assert f"Main paths · {main} of {total} links" in label and "Show all 5 calls" in label
    c.click_el('#ovgraph [data-gall="1"]')
    assert c.js(f"document.querySelector('{SVG}').dataset.view") == "all" and c.js(shown) == total
    assert c.js("document.activeElement.dataset.gall") == "0"   # focus stays on the toggle
    c.click_el('#ovgraph [data-gall="0"]')
    assert c.js(shown) == main


def test_tab_through_nodes_and_enter_focuses(site, chrome):
    c = chrome
    fresh(c, site["url"])
    tabbable = c.js(f"[...document.querySelectorAll('{SVG} [tabindex]')].filter(e => e.tabIndex >= 0).map(e => e.matches('.dg-node') ? 'node' : e.matches('.gexp') ? 'exp' : 'other')")
    assert set(tabbable) <= {"node", "exp"} and tabbable.count("node") == 4      # edges are reached through the card
    c.js(f"document.querySelector('{SVG} .dg-node[data-comp=\"m-engine\"]').focus()")
    c.key("Enter")
    assert c.js(f"document.querySelector('{SVG} .dg-node.sel').dataset.comp") == "m-engine"
    assert c.js("document.activeElement.dataset.comp") == "m-engine"
    c.key("Escape")


def test_ask_about_this_component_prefills_the_ask_box(site, chrome):
    c = chrome
    fresh(c, site["url"])
    before = len(site["store_obj"].load("answers")["questions"])
    c.click_el(f'{SVG} .dg-node[data-comp="m-engine"] .gbox')
    c.click_el("#gfocus [data-gask]")
    c.wait("document.body.classList.contains('popen')", 5)
    assert c.js("document.activeElement.id") == "cin"
    assert c.js("document.getElementById('cin').value").startswith("What does engine.py do")
    ctx = c.js("document.getElementById('ctx').innerText")
    assert ctx.startswith("ASK ABOUT") or ctx.lower().startswith("ask about")
    # anchored to the module's own text: the pending mark is inside the engine module card
    assert c.js("!!document.querySelector('.mod[data-block=\"m-engine\"] .mk.pend')")
    assert len(site["store_obj"].load("answers")["questions"]) == before      # nothing sent until Ask
    c.js("document.querySelector('[data-cancel]').click()")


def test_ask_about_a_multi_file_component_names_it_without_the_badge(site, chrome):
    # train.py + optim.py: the box shows "train.py" and a "+1" badge; the question is built from the files, so the
    # badge never leaks into it ("What does train.py +1 do" was the bug)
    c = chrome
    fresh(c, site["url"])
    c.click_el(f'{SVG} .dg-node[data-comp="m-train"] .gbox')
    c.click_el("#gfocus [data-gask]")
    c.wait("document.body.classList.contains('popen')", 5)
    q = c.js("document.getElementById('cin').value")
    assert q == "What does train.py (and 1 more file) do, and how do the components around it use it?"
    assert "+1" not in q and "+ 1" not in q
    assert c.js("!!document.querySelector('.mod[data-block=\"m-train\"] .mk.pend')")
    c.js("document.querySelector('[data-cancel]').click()")
    # single-file: unchanged
    c.click_el(f'{SVG} .dg-node[data-comp="m-engine"] .gbox')
    c.click_el("#gfocus [data-gask]")
    c.wait("document.body.classList.contains('popen')", 5)
    assert c.js("document.getElementById('cin').value") == "What does engine.py do, and how do the components around it use it?"
    c.js("document.querySelector('[data-cancel]').click()")


# -- the viewer: zoom, pan, fit, full screen ------------------------------------------------------------------------


def scale(c, fig):
    return c.js(f"+document.querySelector({json.dumps(fig)}).dataset.scale")


def test_zoom_pan_and_fit(site, chrome):
    c = chrome
    fresh(c, site["url"])
    fig = "#ovgraph"
    s0 = scale(c, fig)
    assert 0.9 < s0 <= 1
    c.click_el(f'{fig} [data-z="in"]')
    assert abs(scale(c, fig) - s0 * 1.25) < 0.01
    assert c.js(f"document.querySelector('{fig} .zl').textContent") == f"{round(s0 * 1.25 * 100)}%"
    c.click_el(f'{fig} [data-z="out"]')
    assert abs(scale(c, fig) - s0) < 0.01
    # Ctrl + scroll zooms at the pointer; a plain scroll does not
    b = c.box(f"{fig} .dgwrap")
    cx, cy = b["x"] + b["w"] / 2, b["y"] + min(b["h"], 400) / 2
    c.call("Input.dispatchMouseEvent", type="mouseWheel", x=cx, y=cy, deltaX=0, deltaY=-200, modifiers=2)
    settle(c)
    s1 = scale(c, fig)
    assert s1 > s0 * 1.1
    c.call("Input.dispatchMouseEvent", type="mouseWheel", x=cx, y=cy, deltaX=0, deltaY=-200)
    settle(c)
    assert scale(c, fig) == s1
    # drag to pan: the viewport scrolls under the pointer
    c.js(f"document.querySelector('{fig} .dgwrap').scrollLeft = 0")
    b = c.box(f"{fig} .dgwrap")
    y = b["y"] + 8
    c.drag(b["x"] + b["w"] - 40, y, b["x"] + b["w"] - 240, y)
    assert c.js(f"document.querySelector('{fig} .dgwrap').scrollLeft") > 100
    # keys, with the focus in the figure: + zooms, - zooms out, 0 fits
    c.js(f"document.querySelector('{fig} [data-z=\"fit\"]').focus()")
    c.key("0", code="Digit0")
    assert abs(scale(c, fig) - s0) < 0.01 and not c.js(f"document.querySelector('{fig}').classList.contains('zoomed')")
    c.key("+", code="Equal")
    assert scale(c, fig) > s0
    c.key("-", code="Minus")
    assert abs(scale(c, fig) - s0) < 0.01
    c.click_el(f'{fig} [data-z="fit"]')
    assert abs(scale(c, fig) - s0) < 0.01


def check_fullscreen(c, fig, opener=None):
    if opener:
        opener()
    c.click_el(f'{fig} [data-z="fs"]')
    settle(c, 200)
    r = c.js(f"(() => {{ const f = document.querySelector('{fig}'), r = f.getBoundingClientRect(); return [f.classList.contains('fs'), r.left, r.top, r.width, r.height, innerWidth, innerHeight, document.activeElement.dataset.z, f.querySelector('.fig-tt').textContent]; }})()")
    assert r[0] and r[1] <= 0.5 and r[2] <= 0.5 and r[3] >= r[5] - 1 and r[4] >= r[6] - 1, r
    assert r[7] == "fs" and r[8]                                 # the close button has the focus; a title shows
    # nothing of the page sits on top of it
    top = c.js(f"(() => {{ const f = document.querySelector('{fig} .dgwrap'), b = f.getBoundingClientRect(); const e = document.elementFromPoint(b.left + b.width / 2, b.top + 20); return !!e && document.querySelector('{fig}').contains(e); }})()")
    assert top
    c.click_el(f'{fig} [data-z="in"]')
    assert scale(c, fig) > 0
    c.key("Escape")
    settle(c, 100)
    assert not c.js(f"document.querySelector('{fig}').classList.contains('fs')")
    assert not c.js("document.body.classList.contains('fs-on')")


def test_full_screen_for_the_map_a_flow_and_the_overlay(site, chrome):
    c = chrome
    fresh(c, site["url"])
    check_fullscreen(c, "#ovgraph")
    # a flow swimlane
    c.js("document.querySelector('.flow[data-flow=\"f-step\"] .flow-h').click()")
    settle(c)
    check_fullscreen(c, '.fig[data-key="map:f-step"]')
    # the Tracer overlay: full screen, then Esc closes full screen first and the overlay on the next Esc
    c.goto(site["url"] + f"#q={site['ids']['q1c']}")
    settle(c, 250)
    c.click_el(f'[data-dgview="resp:{site["ids"]["r1c"]}"]')
    assert c.js("document.getElementById('dgov').classList.contains('on')")
    check_fullscreen(c, "#dgovfig")
    assert c.js("document.getElementById('dgov').classList.contains('on')")
    c.key("Escape")
    assert not c.js("document.getElementById('dgov').classList.contains('on')")


def test_component_map_text_is_never_under_12px_at_fit(site, chrome):
    c = chrome
    for width in (1440, 1180):
        fresh(c, site["url"], width=width)
        sizes = c.js(f"(() => {{ const s = document.querySelector('{SVG}'), k = s.getScreenCTM().a; return [...s.querySelectorAll('text')].map(t => parseFloat(getComputedStyle(t).fontSize) * k); }})()")
        assert min(sizes) >= 12 - 1e-6, (width, min(sizes))
        # and no style attribute inside any diagram (the page's CSP)
        assert c.js("[...document.querySelectorAll('.dgwrap > svg')].reduce((n, s) => n + s.querySelectorAll('[style]').length, 0)") == 0


# -- contents, scroll-spy, Find ----------------------------------------------------------------------------------------


def test_contents_outline_and_scroll_spy(site, chrome):
    c = chrome
    fresh(c, site["url"])
    subs = c.js("[...document.querySelectorAll('#toc a[data-sub]')].map(a => [a.dataset.in, a.textContent])")
    secs = [s for s, _ in subs]
    assert "Component map" in [t for _, t in subs] and "Purpose" in [t for _, t in subs]
    assert secs.count("modules") >= 4 and secs.count("flows") >= 2
    c.click_el('#toc a[data-sub="m-m-engine"]')
    settle(c, 200)
    on = c.js("[document.querySelector('#toc a[data-sec].on')?.dataset.sec, document.querySelector('#toc a[data-sub].on')?.dataset.sub]")
    assert on == ["modules", "m-m-engine"]
    top = c.js("document.getElementById('m-m-engine').getBoundingClientRect().top")
    assert 40 <= top <= 140                                      # under the sticky section header, not behind it
    hdr = c.js("(() => { const h = document.querySelector('#s-modules h2.sh'); return [getComputedStyle(h).position, Math.round(h.getBoundingClientRect().top)]; })()")
    assert hdr == ["sticky", 0]
    c.js("document.getElementById('main').scrollTop = 0")
    settle(c)
    assert c.js("document.querySelector('#toc a[data-sec].on').dataset.sec") == "overview"


def test_find_filters_the_outline_and_finds_text(site, chrome):
    c = chrome
    fresh(c, site["url"])
    c.key("/", code="Slash")
    assert c.js("document.activeElement.id") == "find"
    c.type("key-value cache")
    settle(c, 300)
    n = c.js("document.querySelectorAll('#col .fd').length")
    assert n >= 1
    res = c.js("document.getElementById('findres').innerText")
    assert "match" in res
    c.key("Enter")
    settle(c, 150)
    cur = c.js("(() => { const e = document.querySelector('#col .fd.cur'); const r = e.getBoundingClientRect(); return [e.textContent.toLowerCase(), r.top > 0 && r.bottom < innerHeight]; })()")
    assert "key-value cache".startswith(cur[0]) or cur[0] in "key-value cache"
    assert cur[1]
    # the outline keeps only what matches (a section stays while its text has a match)
    hidden = c.js("[...document.querySelectorAll('#toc li.ts')].filter(l => l.hidden).length")
    visible = c.js("[...document.querySelectorAll('#toc li.ts')].filter(l => !l.hidden).length")
    assert visible >= 1 and hidden + visible >= 3
    c.key("Escape")
    assert c.js("document.getElementById('find').value") == "" and c.js("document.querySelectorAll('#col .fd').length") == 0
    # find marks never change the text: selection offsets come from the leaves, as before
    assert c.js("[...document.querySelectorAll('#toc li.ts')].every(l => !l.hidden)")


def test_outline_filter_matches_titles_not_the_initial_or_badge(site, chrome):
    # the Modules entry renders as "M" (its initial) + "Modules" + a count badge; "mm" is in that text but not in
    # any title or label, so filtering on it (with no text hits) hides the section
    c = chrome
    fresh(c, site["url"])
    assert "mm" in c.js("document.querySelector('#toc a[data-sec=\"modules\"]').textContent").lower()
    shown = c.js("(() => { FIND.q = 'mm'; FIND.hits = []; applyFindFilter(); const r = !document.querySelector('#toc a[data-sec=\"modules\"]').closest('li').hidden; FIND.q = ''; applyFindFilter(); return r; })()")
    assert shown is False
    kept = c.js("(() => { FIND.q = 'training loop'; FIND.hits = []; applyFindFilter(); const li = document.querySelector('#toc a[data-sec=\"modules\"]').closest('li'); const r = [li.hidden, [...li.querySelectorAll('.tsub li')].filter(x => !x.hidden).map(x => x.querySelector('a').dataset.sub)]; FIND.q = ''; applyFindFilter(); return r; })()")
    assert kept == [False, ["m-m-train"]]


# -- the repo card -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dark", [False, True])
def test_repo_card(site, chrome, dark):
    c = chrome
    fresh(c, site["url"], dark=dark)
    card = c.js("document.querySelector('.repocard').innerText")
    assert c.js("document.querySelector('h1').textContent") == "tinytrain"
    assert "github.com/example/tinytrain" in card
    assert "A tiny GPT trainer you can read in one sitting." in card
    assert "Python 90%" in " ".join(card.split()) and "Shell 10%" in " ".join(card.split())
    assert "MIT" in card and "Ada Lovelace, Grace Hopper" in card and "and 7 more" in card
    assert "4.3k stars" in " ".join(card.split()) and "87 forks" in " ".join(card.split()) and "as of 2026-11-16" in card
    assert "created 2025-01-02" in card and "last commit 2026-11-01" in card and "1.2k commits" in card
    assert "mapped at 0123456" in " ".join(card.split())
    assert "@" not in card                                       # names only
    assert c.js("document.querySelector('.rlink').getAttribute('href')") == "https://github.com/example/tinytrain"
    assert c.js("document.querySelectorAll('.langbar rect').length") == 2
    # the memory line still lives in the card
    assert c.js("!!document.querySelector('.repocard #mem') && document.getElementById('mem').innerText.length > 10")
    # nothing fetched but the page and its API
    base = site["url"].rstrip("/")
    for u in c.js("performance.getEntriesByType('resource').map(e => e.name)"):
        assert u.startswith(base + "/"), u
    assert c.console_errors() == []


def test_a_map_without_a_repo_card_keeps_its_header(tmp_path_factory, chrome):
    info = build(tmp_path_factory.mktemp("norepo"), "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        c = chrome
        fresh(c, f"http://127.0.0.1:{server.server_address[1]}/")
        assert c.js("document.querySelector('.repocard h1').textContent") == "tinytrain"
        assert c.js("!!document.querySelector('.repocard #mem')") and not c.js("!!document.querySelector('.langbar')")
    finally:
        server.shutdown()
        server.server_close()

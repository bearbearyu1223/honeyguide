"""The map page's quieter "not supported" (T7.15), on the fixture's ``v2`` map, where the Checker flagged three map
claims (MAP_FLAGS_V2): no inline red pill on the map; the claim keeps a faint dotted underline and the dashed mark in
place of its evidence shape; the red flag and the Checker's note show on hover or focus; the note is the claim's
accessible description; and the sidebar's "Needs a look (3)" lists them and leads to each. Answers keep their pill.
Headless Chrome under perl's alarm; skipped without Chrome."""

from __future__ import annotations

import re

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import MAP_FLAGS_V2, build
from test_t7_page_v2 import serve


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = serve(build(tmp_path_factory.mktemp("ns"), "v2"))
    info["ids"] = {c["key"]: c["id"] for c in info["store"].load("map")["claims"]}
    yield info
    info["server"].shutdown()
    info["server"].server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=60) as c:
        yield c


def settle(c, ms=150):
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def deco(c, sel):
    return c.js(f"(() => {{ const s = getComputedStyle(document.querySelector({sel!r})); "
                "return [s.textDecorationLine, s.textDecorationStyle, s.textDecorationColor]; })()")


def color(c, var):
    return c.js(f"(() => {{ const d = document.createElement('span'); d.style.color = 'var({var})'; document.body.appendChild(d); "
                "const v = getComputedStyle(d).color; d.remove(); return v; })()")


def near(a, b, tol=3):
    """Two computed rgb() colours, equal within ``tol`` per channel (a transition can end a unit off)."""
    pa, pb = (list(map(float, re.findall(r"[\d.]+", x)))[:3] for x in (a, b))
    return all(abs(x - y) <= tol for x, y in zip(pa, pb, strict=True))


def test_no_inline_pill_on_the_map_and_the_mark_is_replaced(site, chrome):
    c = chrome
    c.goto(site["url"])
    assert c.console_errors() == []
    assert c.js("document.querySelectorAll('#col .flag').length") == 0
    deps = site["ids"]["deps"]
    sel = f'#col .claim[data-claim="{deps}"]'
    assert c.js(f"document.querySelector('{sel}').classList.contains('quiet')")
    # the evidence shape is withdrawn; the dashed mark stands in its place
    cite = c.js(f"[...document.querySelector('{sel}').nextElementSibling.querySelectorAll('.dot')].map(d => d.className)")
    assert cite == ["dot unsup"]
    assert c.js("getComputedStyle(document.querySelector('#col .dot.unsup')).borderTopStyle") == "dashed"
    # at rest: a faint dotted underline
    line, style, col = deco(c, sel)
    assert line == "underline" and style == "dotted" and near(col, color(c, "--faint"))
    # supported map claims keep their evidence shape
    assert c.js("document.querySelectorAll('#col .cite .dot[class*=\"ev-\"]').length") > 20


def test_hover_shows_the_red_flag_and_the_checkers_note(site, chrome):
    c = chrome
    c.goto(site["url"])
    deps = site["ids"]["deps"]
    sel = f'#col .claim[data-claim="{deps}"]'
    c.js(f"document.querySelector('{sel}').scrollIntoView({{block: 'center'}})")
    c.hover_el(sel)
    settle(c, 300)
    assert near(deco(c, sel)[2], color(c, "--flag"))
    tip = c.js("document.getElementById('tip').innerText")
    assert tip.startswith("Not supported") and "nothing cited shows that uv sync is what" in tip
    assert c.js("getComputedStyle(document.querySelector('#tip .tflag')).color") == color(c, "--flag-tip")


def test_the_note_is_the_accessible_description_and_focus_shows_it(site, chrome):
    c = chrome
    c.goto(site["url"])
    deps = site["ids"]["deps"]
    sel = f'#col .claim[data-claim="{deps}"]'
    assert c.js(f"document.querySelector('{sel}').getAttribute('tabindex')") == "0"
    desc = c.js(f"document.getElementById(document.querySelector('{sel}').getAttribute('aria-describedby')).textContent")
    assert desc == "Not supported: " + MAP_FLAGS_V2["deps"]
    # every description id is unique
    ids = c.js("[...document.querySelectorAll('#col [aria-describedby]')].map(e => e.getAttribute('aria-describedby'))")
    assert len(ids) == len(set(ids)) >= 2
    # keyboard focus: Tab onto the claim shows the note and the red underline (the mouse parked out of the way, so a
    # scroll under it can't move the tooltip)
    c.mouse("mouseMoved", 2, 2)
    c.js(f"(() => {{ const el = document.querySelector('{sel}'); el.scrollIntoView({{block: 'center'}}); "
         "const prev = el.previousElementSibling || el.parentElement; prev.setAttribute('tabindex', '-1'); prev.focus(); })()")
    for _ in range(12):
        c.key("Tab")
        if c.js(f"document.activeElement === document.querySelector('{sel}')"):
            break
    assert c.js(f"document.activeElement === document.querySelector('{sel}')")
    settle(c, 300)
    assert c.js("document.getElementById('tip').classList.contains('on')")
    assert "Not supported" in c.js("document.getElementById('tip').innerText")
    assert near(deco(c, sel)[2], color(c, "--flag"))


def test_needs_a_look_lists_them_and_leads_to_each(site, chrome):
    c = chrome
    c.goto(site["url"])
    head = c.js("document.querySelector('#needs .nd-h').innerText")
    assert " ".join(head.split()) == "Needs a look 3 ▸"
    assert c.js("document.getElementById('ndl').hidden")
    c.click_el("#needs .nd-h")
    assert c.js("document.querySelector('#needs .nd-h').getAttribute('aria-expanded')") == "true"
    items = c.js("[...document.querySelectorAll('#ndl a')].map(a => [a.dataset.ns, a.querySelector('.ns-t').innerText, a.querySelector('.ns-s').innerText])")
    ids = site["ids"]
    assert [i[0] for i in items] == [ids["deps"], ids["m-io"], ids["h5"]]
    assert [i[2] for i in items] == ["Overview", "Modules", "Flows"]
    assert items[2][1] == "opt.step()"
    # a claim in a folded module fact: the module opens, the claim is shown with its note
    c.click_el(f'#ndl a[data-ns="{ids["m-io"]}"]')
    settle(c, 250)
    el = f'#col .claim[data-claim="{ids["m-io"]}"]'
    assert c.js(f"document.querySelector('{el}').closest('.mod').classList.contains('open')")
    assert c.js(f"(() => {{ const r = document.querySelector('{el}').getBoundingClientRect(); return r.height > 0 && r.top >= 0 && r.top < innerHeight; }})()")
    assert "forward(self, idx, ...)" in c.js("document.getElementById('tip').innerText")
    # a claim shown only by a flow hop: the flow opens on its steps, the hop is flashed, with the dashed node
    c.click_el(f'#ndl a[data-ns="{ids["h5"]}"]')
    settle(c, 250)
    hop = f'.flow[data-flow="f-step"] .hop[data-claim="{ids["h5"]}"]'
    assert c.js("document.querySelector('.flow[data-flow=\"f-step\"]').classList.contains('open')")
    assert c.js(f"document.querySelector('{hop}').classList.contains('flashed')")
    assert c.js(f"document.querySelector('{hop} .node').classList.contains('unsup')")
    assert c.js(f"document.querySelector('{hop}').innerText").count("not supported") == 0   # no pill on the map rail
    assert c.js(f"document.querySelector('{hop} .sr').textContent").startswith("Not supported: The cited line")
    # collapsed again on a second click; the rail hides it
    c.click_el("#needs .nd-h")
    assert c.js("document.getElementById('ndl').hidden")


def test_answers_keep_their_pill_and_the_legend_shows_the_mark(site, chrome):
    c = chrome
    c.goto(site["url"])
    assert "not supported" in c.js("document.getElementById('legend').innerText")
    assert c.js("!!document.querySelector('#legend .dot.unsup')")
    # the training-loop answer has one claim the Checker flagged: in the panel it keeps the red pill
    c.js("document.querySelector('.mm[data-g]')?.click()")
    c.wait("document.body.classList.contains('popen')", 5)
    flags = c.js("(() => { for (const m of document.querySelectorAll('.mm[data-g]')) { m.click(); "
                 "if (document.querySelector('#pbody .flag')) return document.querySelector('#pbody .flag').textContent; } return null; })()")
    assert flags == "not supported"

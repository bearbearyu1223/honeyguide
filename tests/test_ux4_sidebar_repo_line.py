"""UX v4: the sidebar's repo line under "Honeyguide", against the real server and the v2 fixture store, in headless
Chrome:

- it reads "<repo>" and below it "mapped at <short sha>", the map's commit, the sha linking to that commit on GitHub
  (new tab, rel noopener) with a tooltip naming the 12-character sha and its date; plain text off GitHub;
- it is never clipped: its box keeps its full height, sits inside the sidebar and above the Find box, at short
  windows and at other sidebar widths, light and dark (it was a flex item with overflow:hidden and shrank to 3 px);
- sidebar chrome is never selectable: no selection, Find mark or note mark inside the sidebar after Find or after
  a drag from the map up into it (the amber in the reported screenshot was ::selection, which paints in the note colour);
- the collapsed rail hides it.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import build
from test_t7_17_viewer import REPO_CARD

from honeyguide.gitio import Repo
from honeyguide.server import make_server
from honeyguide.store import Store


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("repoline"), "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    card = copy.deepcopy(REPO_CARD)
    card["commit"] = {"sha": info["commit"], "date": "2026-11-01T10:00:00+00:00"}   # the card made at map time
    store.update("map", lambda layer: layer["document"].__setitem__("repo", card))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info.update(url=f"http://127.0.0.1:{server.server_address[1]}/")
    yield info
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=90) as c:
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


def geometry(c):
    return c.js("""(() => { const r = document.getElementById('repo'), b = r.getBoundingClientRect(),
        s = document.getElementById('side').getBoundingClientRect(), f = document.querySelector('.find').getBoundingClientRect();
        const kids = [...r.children].map(k => { const x = k.getBoundingClientRect(); return [x.top, x.bottom, k.scrollHeight, x.height, k.scrollWidth <= k.clientWidth || getComputedStyle(k).textOverflow === 'ellipsis']; });
        return {top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: b.height, sh: r.scrollHeight,
                side: [s.top, s.bottom, s.left, s.right], findTop: f.top, kids}; })()""")


def assert_whole(g):
    assert g["h"] >= g["sh"] - 0.5, g                       # nothing cut off at the bottom
    assert g["h"] >= 30, g                                  # two lines
    st, sb, sl, sr = g["side"]
    assert st <= g["top"] and g["bottom"] <= sb and sl <= g["left"] and g["right"] <= sr + 0.5, g
    assert g["bottom"] <= g["findTop"] - 8, g               # clear of the Find box, never under it
    for top, bottom, sh, h, fits in g["kids"]:
        assert g["top"] - 0.5 <= top and bottom <= g["bottom"] + 0.5 and h >= sh - 0.5 and fits, g


@pytest.mark.parametrize("dark", [False, True])
def test_label_link_and_tooltip(site, chrome, dark):
    c = chrome
    fresh(c, site["url"], dark=dark)
    sha = site["commit"]
    assert c.js("document.querySelector('#repo .repo-n').textContent") == "tinytrain"
    assert c.js("document.querySelector('#repo .repo-at').textContent") == f"mapped at {sha[:7]}"
    a = c.js("(() => { const a = document.querySelector('#repo .repo-at a'); return [a.getAttribute('href'), a.target, a.rel, a.dataset.tip, a.textContent]; })()")
    assert a[0] == f"https://github.com/example/tinytrain/commit/{sha}"
    assert a[1] == "_blank" and "noopener" in a[2].split()
    assert a[3] == f"This map describes the code at commit <code>{sha[:12]}</code> (2026-11-01)"
    assert a[4] == sha[:7]
    # consistent with the repo card's "mapped at" (this card was made at the map's commit)
    assert f"mapped at {sha[:7]}" in " ".join(c.js("document.querySelector('.repocard').innerText").split())
    # the tooltip opens below the line, so it never covers the repo's name
    c.hover_el("#repo .repo-at a")
    settle(c, 200)
    t = c.js("(() => { const t = document.getElementById('tip'), r = t.getBoundingClientRect(), n = document.querySelector('#repo .repo-at').getBoundingClientRect(); return [t.classList.contains('on'), t.textContent, r.top >= n.bottom]; })()")
    assert t[0] and t[1] == f"This map describes the code at commit {sha[:12]} (2026-11-01)" and t[2], t
    c.mouse("mouseMoved", 900, 600)
    assert_whole(geometry(c))
    assert c.console_errors() == []


def test_plain_text_off_github_and_no_date_for_another_commit(site, chrome):
    c = chrome
    fresh(c, site["url"])
    gl = {"url": "https://gitlab.com/team/toy", "host": "gitlab.com", "commit": {"sha": "f" * 40, "date": "2026-01-02T00:00:00Z"}}
    html = c.js(f"repoLineHTML('toy', {json.dumps('a' * 40)}, {json.dumps(gl)})")
    assert "<a " not in html and "mapped at <span" in html and "aaaaaaa</code>" in html
    assert "aaaaaaaaaaaa&lt;/code&gt;\"" in html                        # no date: the card is about another commit
    assert c.js("repoLineHTML('toy', null, null)") == '<div class="repo-n">toy</div>'


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("size", [(1440, 900), (1280, 640), (1024, 480)])
def test_never_clipped(site, chrome, size, dark):
    c = chrome
    fresh(c, site["url"], width=size[0], height=size[1], dark=dark)
    assert_whole(geometry(c))
    # at other sidebar widths too (the line ellipses sideways; it never loses height)
    for side in ("200px", "320px"):
        c.js(f"document.documentElement.style.setProperty('--side', '{side}')")
        settle(c, 250)
        assert_whole(geometry(c))
    c.js("document.documentElement.style.removeProperty('--side')")


SIDE_MARKS = "document.querySelectorAll('#side .fd, #side .mk, #repo mark').length"
SEL_IN_SIDE = """(() => { const s = getSelection(); if (!s.rangeCount) return false;
  const side = document.getElementById('side');
  return [...side.querySelectorAll('*')].some(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim() && s.containsNode(n, true))
         && getComputedStyle(e).userSelect !== 'none'); })()"""


def test_no_highlight_in_the_sidebar_after_find_or_a_selection(site, chrome):
    c = chrome
    fresh(c, site["url"])
    assert c.js("getComputedStyle(document.getElementById('repo')).userSelect") == "none"
    assert c.js("getComputedStyle(document.getElementById('find')).userSelect") != "none"   # Find still takes text
    # Find: the sha and the name are in the sidebar only, never marked there
    sha7 = site["commit"][:7]
    for q in (sha7[3:], "tinytrain", "mapped"):
        c.js("document.getElementById('find').focus()")
        c.js("document.getElementById('find').value = ''")
        c.type(q)
        settle(c, 300)
        assert c.js(SIDE_MARKS) == 0, q
        assert c.js("document.getElementById('repo').innerHTML.includes('<mark')") is False
        c.key("Escape")
    # a drag across the repo line selects nothing
    b = c.box("#repo .repo-at")
    c.drag(b["x"] + 1, b["y"] + b["h"] / 2, b["x"] + b["w"] - 1, b["y"] + b["h"] / 2)
    settle(c)
    assert c.js("getSelection().toString()") == ""
    assert c.js("getComputedStyle(document.getElementById('tb')).display") == "none"
    # a drag from the map's text up into the sidebar: the selection never takes in sidebar text
    p = c.box("#col .card p, #col p")
    c.drag(p["x"] + 40, p["y"] + p["h"] / 2, b["x"] + 30, b["y"] + b["h"] / 2, steps=12)
    settle(c)
    assert c.js("getSelection().toString().length") > 0                    # the map's text is selected
    assert c.js("document.getElementById('side').contains(getSelection().anchorNode)") is False
    assert c.js(SEL_IN_SIDE) is False                                       # nothing selectable in the sidebar is in it
    assert "Find in the map" not in c.js("getSelection().toString()")
    assert c.js(SIDE_MARKS) == 0
    c.js("getSelection().removeAllRanges()")
    assert c.console_errors() == []


def test_the_rail_hides_it(site, chrome):
    c = chrome
    fresh(c, site["url"])
    assert c.js("getComputedStyle(document.getElementById('repo')).display") != "none"
    c.click_el("#railbtn")
    settle(c, 300)
    assert c.js("document.documentElement.classList.contains('rail')")
    assert c.js("getComputedStyle(document.getElementById('repo')).display") == "none"
    c.click_el("#railbtn")
    settle(c, 300)
    assert c.js("getComputedStyle(document.getElementById('repo')).display") != "none"
    assert_whole(geometry(c))

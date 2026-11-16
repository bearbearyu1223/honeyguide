"""The map page (T7.3) against a real server and the sample store, driven by headless Chrome with real mouse events.

Every leaf of rendered text shows exactly its slice of the server's plain text; a selection asked about lands in
/api/threads with the right anchor; a follow-up and a note from an answer land too; the panel's width survives a
reload; the page can't use the API without its token. Skipped when Chrome isn't installed.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import build

from honeyguide import inbox
from honeyguide.gitio import Repo
from honeyguide.mapdoc import plain_text
from honeyguide.server import PAGE_CSP, make_server, server_token
from honeyguide.store import Store


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("page"), "base")
    from pathlib import Path
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    info.update(store=store, port=port, url=f"http://127.0.0.1:{port}/", token=server_token(store))
    yield info
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=60) as c:
        yield c


def get(site, path, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", site["port"], timeout=10)
    headers = {"Host": f"127.0.0.1:{site['port']}"}
    if token:
        headers["X-Honeyguide-Token"] = site["token"]
    conn.request("GET", path, headers=headers)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), body


def threads(site):
    return inbox.threads(site["store"])


SEL_RECT = """((sel, phrase) => {
  const root = document.querySelector(sel);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const nodes = []; let t = "";
  while (w.nextNode()) { nodes.push([w.currentNode, t.length]); t += w.currentNode.data; }
  const i = t.indexOf(phrase); if (i < 0) return null;
  const at = k => { for (let j = nodes.length - 1; j >= 0; j--) if (nodes[j][1] <= k) return [nodes[j][0], k - nodes[j][1]]; };
  const [a, ao] = at(i), [b, bo] = at(i + phrase.length - 1);
  const box = a.parentElement.getBoundingClientRect();
  if (box.top < 80 || box.bottom > innerHeight - 80) a.parentElement.scrollIntoView({block: "center"});
  const r1 = document.createRange(); r1.setStart(a, ao); r1.setEnd(a, ao + 1);
  const r2 = document.createRange(); r2.setStart(b, bo); r2.setEnd(b, bo + 1);
  const x = r1.getClientRects()[0], y = r2.getClientRects()[0];
  return {x0: x.left + 1, y0: x.top + x.height / 2, x1: y.right - 1, y1: y.top + y.height / 2};
})(%s, %s)"""


def drag_select(c, selector, phrase):
    c.js(SEL_RECT % (json.dumps(selector), json.dumps(phrase)))   # scroll it into view first
    c.js("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    rect = c.js(SEL_RECT % (json.dumps(selector), json.dumps(phrase)))
    assert rect, phrase
    c.drag(rect["x0"], rect["y0"], rect["x1"], rect["y1"])
    c.wait("getComputedStyle(document.getElementById('tb')).display === 'flex'", 5)
    return c.js("getSelection().toString()")


def test_page_and_assets_are_served_with_a_strict_policy(site):
    status, headers, body = get(site, "/", token=False)
    page = body.decode()
    assert status == 200 and site["token"] in page and site["store"].repo_id in page
    assert headers["Content-Security-Policy"] == PAGE_CSP and "script-src 'self'" in PAGE_CSP
    assert "<script>" not in page and " style=" not in page          # nothing inline for the policy to block
    for path, kind in (("/page.js", "javascript"), ("/page.css", "css"), ("/boot.js", "javascript"), ("/diagrams.js", "javascript"),
                       ("/favicon.svg", "svg")):
        status, headers, _ = get(site, path, token=False)
        assert status == 200 and kind in headers["Content-Type"], path
    assert get(site, "/../server.py", token=False)[0] == 404
    assert get(site, "/page/page.js", token=False)[0] == 404
    assert get(site, "/api/map", token=False)[0] == 403


def test_page_renders_the_map_with_offsets_that_match_the_server(site, chrome):
    c = chrome
    c.goto(site["url"])
    assert c.console_errors() == []
    assert c.js("document.querySelector('h1').textContent") == "tinytrain"
    # every leaf shows exactly plain_text[o : o + len] (code points), the invariant anchors rely on
    text = plain_text(site["store"].load("map")["document"])
    leaves = c.js("[...document.querySelectorAll('#col .lf')].map(e => [+e.dataset.o, e.textContent])")
    assert len(leaves) > 40
    for o, shown in leaves:
        assert text[o:o + len(shown)] == shown, (o, shown)
    # the three seeded discussions and two map notes are overlaid; claims carry their evidence marks
    assert c.js("document.querySelectorAll('.mm:not(.note)').length") == 3
    assert c.js("document.querySelectorAll('.mm.note').length") == 2
    assert c.js("document.querySelectorAll('#col .dot').length") >= 20
    assert "Up to date at" in c.js("document.getElementById('mem').innerText")


def test_selection_asked_about_lands_in_the_inbox_with_its_anchor(site, chrome):
    c = chrome
    c.goto(site["url"])
    phrase = "Shard order is reshuffled every epoch"
    assert drag_select(c, '[data-block="m-data"]', phrase).strip() == phrase
    c.click_el('#tb [data-act="ask"]')
    c.wait("document.body.classList.contains('popen') && document.activeElement.id === 'cin'", 5)
    assert c.js("document.querySelector('#ctx .cq').textContent") == f"“{phrase}”"
    c.type("Why seed by the epoch?")
    c.key("Enter")
    c.wait("document.querySelector('.nd.cur .qt') && document.querySelector('.nd.cur .qt').textContent.includes('seed by the epoch')", 5)
    qs = [q for q in threads(site)["questions"] if q["text"] == "Why seed by the epoch?"]
    assert len(qs) == 1 and qs[0]["status"] == "open" and qs[0]["parent_response"] is None
    a = qs[0]["anchor"]
    text = plain_text(site["store"].load("map")["document"])
    assert a["doc"] == "map" and a["quote"] == phrase and text[a["start"]:a["end"]] == phrase
    # the new thread shows at once, waiting for the Guide, with a margin marker beside the passage
    assert "Waiting for the" in c.js("document.querySelector('.nd.cur .nd-b').innerText")
    assert c.js("document.querySelectorAll('.mm:not(.note)').length") == 4


def test_follow_up_and_note_from_an_answer(site, chrome):
    c = chrome
    c.goto(site["url"] + f"#q={site['ids']['q3']}")
    c.js("new Promise(r => setTimeout(r, 250))")
    rid = site["ids"]["r3"]
    phrase = "once per outer step"
    drag_select(c, f'.ans[data-doc="answer:{rid}"] .atext', phrase)
    c.click_el('#tb [data-act="ask"]')
    c.type("Even with one micro-batch?")
    c.key("Enter")
    c.wait("[...document.querySelectorAll('.qt')].some(e => e.textContent.includes('one micro-batch'))", 5)
    q = [q for q in threads(site)["questions"] if q["text"] == "Even with one micro-batch?"][0]
    resp = next(r for r in threads(site)["responses"] if r["id"] == rid)
    assert q["parent_response"] == rid and q["anchor"]["doc"] == f"answer:{rid}"
    assert resp["text"][q["anchor"]["start"]:q["anchor"]["end"]] == phrase
    # annotate other words in the same answer: a note, never a question
    drag_select(c, f'.ans[data-doc="answer:{rid}"] .atext', "summed gradient")
    c.click_el('#tb [data-act="note"]')
    c.type("Check this against nanochat.")
    c.key("Enter")
    c.wait("document.getElementById('toast').textContent.includes('Saved to your notes')", 5)
    notes = site["store"].load("notes")["notes"]
    assert any(n["text"] == "Check this against nanochat." and n["anchor"]["quote"] == "summed gradient" for n in notes)
    assert not any(q["text"] == "Check this against nanochat." for q in threads(site)["questions"])


def test_panel_resize_persists_resets_and_takes_keys(site, chrome):
    c = chrome
    c.goto(site["url"] + f"#q={site['ids']['q2']}")
    c.js("localStorage.removeItem('honeyguide.panelWidth')")
    c.js("new Promise(r => setTimeout(r, 250))")
    width = "Math.round(document.getElementById('panel').getBoundingClientRect().width)"
    assert c.js(width) == 408
    g = c.box("#grip")
    c.drag(g["x"] + 4, 400, g["x"] + 4 - 120, 400)
    dragged = c.js(width)
    assert abs(dragged - 528) <= 1 and c.js("localStorage.getItem('honeyguide.panelWidth')") == str(dragged)
    c.goto(site["url"] + f"#q={site['ids']['q2']}")
    assert c.js(width) == dragged                              # remembered across visits
    c.js("document.getElementById('grip').focus()")
    c.key("ArrowLeft")
    assert c.js(width) == dragged + 16
    c.key("ArrowRight", shift=True)
    assert c.js(width) == dragged + 16 - 64
    g = c.box("#grip")
    c.click(g["x"] + 4, 400, clicks=1)
    c.click(g["x"] + 4, 400, clicks=2)                          # double-click resets
    assert c.js(width) == 408 and c.js("localStorage.getItem('honeyguide.panelWidth')") == "408"
    c.drag(g["x"] + 4, 400, 0, 400)                             # never wider than 720, nor squeezing the map
    assert c.js(width) <= 720 and c.js("document.getElementById('col').getBoundingClientRect().width") >= 560
    c.js("localStorage.removeItem('honeyguide.panelWidth')")


def test_api_needs_the_token_even_from_the_page(site, chrome):
    c = chrome
    c.goto(site["url"])
    status = c.js("fetch('/api/state').then(r => r.status)")
    bad = c.js("fetch('/api/state', {headers: {'X-Honeyguide-Token': '0'.repeat(32)}}).then(r => r.status)")
    good = c.js(f"fetch('/api/state', {{headers: {{'X-Honeyguide-Token': {json.dumps(site['token'])}}}}}).then(r => r.status)")
    post = c.js("fetch('/api/question', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
                "body: JSON.stringify({text: 'sneaky'})}).then(r => r.status)")
    assert (status, bad, good, post) == (403, 403, 200, 403)
    assert not any(q["text"] == "sneaky" for q in threads(site)["questions"])

"""The map page (T7.3, and T7.12's logo, favicon and agent avatars) against a real server and the sample store, driven by headless Chrome with real mouse events.

Every leaf of rendered text shows exactly its slice of the server's plain text; a selection asked about lands in
/api/threads with the right anchor; a follow-up and a note from an answer land too; the panel's width survives a
reload; the page can't use the API without its token. Skipped when Chrome isn't installed.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import A, C, answer, ask, build, map_anchor, waiting_and_failed

from honeyguide import inbox
from honeyguide.gitio import Repo
from honeyguide.mapdoc import plain_text
from honeyguide.server import PAGE_CSP, make_server, server_token
from honeyguide.store import Store


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("page"), "base")
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
                       ("/favicon.svg", "svg"), ("/hg-avatars.js", "javascript"), ("/avatars.css", "css")):
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


# ---------------------------------------------------------------------------------------------------------------
# T7.12: the logo, the favicon and the agent avatars (assets/avatars/INTEGRATION.md)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src/honeyguide/page"
AGENTS = ("guide", "cartographer", "investigator", "tracer", "checker")
# every avatar on the page: [where, agent, size attribute, rendered width, classes, animations running]
AVATARS = """[...document.querySelectorAll('svg.hg-av')].map(s => [
  s.closest('.agn') ? 'text' : s.closest('.by') ? 'by' : s.closest('.wait') ? 'wait' : s.closest('.failed') ? 'failed' : s.closest('#pelse') ? 'else'
    : s.closest('.work') ? 'work' : s.closest('#top') ? 'top' : s.closest('.nv-m .av') ? 'nav-busy' : s.closest('.nv-m') ? 'nav'
    : s.closest('.flow-h') ? 'flow' : 'other',
  [...s.classList].find(c => /^hg-av-(guide|cartographer|investigator|tracer|checker)$/.test(c)).slice(6),
  s.getAttribute('width'), Math.round(s.getBoundingClientRect().width), s.getAttribute('class'),
  s.getAnimations({subtree: true}).filter(a => a.playState === 'running').length])"""


def avatars(c):
    return [dict(zip(("where", "agent", "size", "shown", "cls", "running"), a, strict=True)) for a in c.js(AVATARS)]


def wait_ms(c, ms):
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


@pytest.fixture(scope="module")
def busy(tmp_path_factory):
    """The ``working`` variant (four agents at work) plus a question waiting for the Guide and one that failed."""
    info = waiting_and_failed(build(tmp_path_factory.mktemp("busy"), "working"))
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info.update(store=store, url=f"http://127.0.0.1:{server.server_address[1]}/")
    yield info
    server.shutdown()
    server.server_close()


def test_page_owns_copies_of_the_logo_favicon_and_avatars():
    assets = ROOT / "assets"
    for page, source in (("hg-avatars.js", "avatars/hg-avatars.js"), ("avatars.css", "avatars/avatars.css"),
                         ("favicon.svg", "favicon.svg")):
        assert (PAGE / page).read_bytes() == (assets / source).read_bytes(), f"{page} differs from assets/{source}"
    # the sidebar logo is Honey: exactly hgAv("guide", "idle", 24) from assets/avatars/hg-avatars.js, inline (no
    # style attribute: the CSP allows none; avatars.css colours and animates it)
    src = json.loads(re.search(r"const HG_AV = (\{.*?\});\n", (assets / "avatars/hg-avatars.js").read_text(), re.S)[1])
    honey24 = src["guide"].replace("hg-av-idle", "hg-av-idle hg-av-24", 1).replace("<svg ", '<svg width="24" height="24" ', 1)
    index = (PAGE / "index.html").read_text()
    start = index.index('<span class="logo">') + len('<span class="logo">')
    side = index[start:index.index("</svg>", start) + len("</svg>")]
    assert side == honey24 and index[start + len(side):].startswith('</span><span class="brand-t">Honeyguide</span>')
    assert "style=" not in index and "<script>" not in index
    assert set(re.findall(r'https?://[^"\\ ]+', side)) == {"http://www.w3.org/2000/svg"}   # a namespace, never fetched
    assert index.index('src="/hg-avatars.js"') < index.index('src="/page.js"')
    js = (PAGE / "hg-avatars.js").read_text()
    assert set(re.findall(r'https?://[^"\\ ]+', js)) == {"http://www.w3.org/2000/svg"}   # a namespace, never fetched
    assert "style=" not in js and "<script" not in js
    page = (PAGE / "page.js").read_text()
    assert not re.search("[\U0001F5FA\U0001F9ED\U0001F526\U0001F9F5]", page)   # 🗺 🧭 🔦 🧵 are gone
    assert page.count("✅") == 1 and '<span class="em">✅</span>${sup} of ${tot} supported' in page   # the result mark stays


def test_every_agent_call_site_draws_its_avatar_at_its_size(busy, chrome):
    c = chrome
    c.goto(busy["url"] + f"#q={busy['ids']['q5']}")
    for q in ("q1a", "q1b", "q1c", "q4"):
        c.click_el(f'[data-tog="{busy["ids"][q]}"]')   # closed nodes show their meta line: agent, then counts
    seen = avatars(c)
    for a in seen:   # the size attribute, its tuning class and the drawn box agree (0: on a line not shown)
        assert a["agent"] in AGENTS and f"hg-av-{a['size']}" in a["cls"] and a["shown"] in (0, int(a["size"])), a
    assert sum(a["shown"] > 0 for a in seen) >= 10
    want = {"by": ("28", "hg-av-done"), "work": ("40", "hg-av-working"), "else": ("22", "hg-av-working"),
            "top": ("24", "hg-av-working"), "text": ("20", "hg-av-static")}
    for where, (size, state) in want.items():
        found = [a for a in seen if a["where"] == where]
        assert found and all(a["size"] == size and state in a["cls"] for a in found), (where, found)
    working = [a for a in seen if "hg-av-working" in a["cls"]]
    assert {a["agent"] for a in working} >= {"investigator", "checker", "tracer", "cartographer"}
    assert all("hg-av-static" not in a["cls"] for a in working)
    assert all(a["running"] for a in working if a["shown"])               # working: animated (when it is shown)
    assert all(not a["running"] for a in seen if "hg-av-static" in a["cls"])                 # prose: never moves
    assert c.js("[...document.querySelectorAll('.av')].every(a => getComputedStyle(a).animationName === 'none' "
                "&& getComputedStyle(a).boxShadow === 'none')")                                # no halo
    assert not re.search("[\U0001F5FA\U0001F9ED\U0001F526\U0001F9F5]", c.js("document.body.innerText"))
    # the discussions: busy rows at 24 (working), the rest a still row of 20s
    c.click_el('[data-tab="nav"]')
    nav = avatars(c)
    assert any(a["where"] == "nav-busy" and a["size"] == "24" and a["running"] for a in nav)
    assert any(a["where"] == "nav" and a["size"] == "20" and "hg-av-static" in a["cls"] for a in nav)
    # notes name the answer's agent with a still 20px avatar
    c.click_el('[data-tab="notes"]')
    assert any(a["where"] == "text" and a["size"] == "20" for a in avatars(c))
    # waiting for the Guide: Honey dozing at 28, "Honey, the Guide" on hover, and the name alone in the sentence
    c.goto(busy["url"] + f"#q={busy['ids']['qwait']}")
    w = [a for a in avatars(c) if a["where"] == "wait"]
    assert len(w) == 1 and w[0]["agent"] == "guide" and w[0]["size"] == "28" and "hg-av-waiting" in w[0]["cls"]
    assert c.js("document.querySelector('.wait .av').dataset.tip") == "Honey, the Guide"
    assert "Waiting for the Guide. Your Claude Code session" in c.js("document.querySelector('.wait').innerText")
    # a failed question: the agent that tried, greyed at 20
    c.goto(busy["url"] + f"#q={busy['ids']['qfail']}")
    f = [a for a in avatars(c) if a["where"] == "failed"]
    assert len(f) == 1 and f[0]["agent"] == "investigator" and f[0]["size"] == "20" and "hg-av-failed" in f[0]["cls"]
    assert c.console_errors() == []


def test_reduced_motion_stops_every_avatar_and_keeps_the_badge(busy, chrome):
    c = chrome
    try:
        c.media(reduced_motion=True)
        c.goto(busy["url"] + f"#q={busy['ids']['q5']}")
        wait_ms(c, 300)
        seen = avatars(c)
        assert seen and not any(a["running"] for a in seen)
        assert c.js("document.documentElement.classList.contains('rm')")
        badge = "getComputedStyle(document.querySelector('#pbody .av.working'), '::after')"
        assert c.js(f"{badge}.content") != "none" and c.js(f"{badge}.width") == "10px"   # the still "…" badge
        # the still pose: the Investigator's lens held over an eye
        assert c.js("getComputedStyle(document.querySelector('#pbody .av.working .hg-av-lens')).transform") != "none"
    finally:
        c.media()


def test_the_sidebar_logo_is_honey_at_24_beside_the_name(busy, chrome):
    c = chrome
    c.goto(busy["url"])
    logo = "document.querySelector('.brand .logo > svg')"
    assert c.js(f"[...{logo}.classList].join(' ')") == "hg-av hg-av-guide hg-av-idle hg-av-24"
    r = c.js(f"(() => {{ const a = {logo}.getBoundingClientRect(), b = document.querySelector('.brand-t').getBoundingClientRect(),"
             " p = document.querySelector('#repo').getBoundingClientRect();"
             " return [a.width, a.height, a.top + a.height / 2 - (b.top + b.height / 2), b.left - p.left]; })()")
    assert r[:2] == [24, 24] and abs(r[2]) <= 1 and abs(r[3]) <= 1, r   # centred on the name; the repo lines up under it
    assert c.js(f"{logo}.getAnimations({{subtree: true}}).filter(a => a.playState === 'running').length") > 0  # idle
    assert c.js("document.querySelector('link[rel=icon]').getAttribute('href')") == "/favicon.svg"


def test_the_done_hop_plays_once_per_answer(busy, chrome):
    c = chrome
    by = "document.querySelector('.nd[data-id=\"%s\"] > .nd-b > .by .av > svg')"
    q2 = by % busy["ids"]["q2"]
    c.goto(busy["url"] + f"#q={busy['ids']['q2']}")
    assert c.js(f"{q2}.classList.contains('hg-av-done') && !{q2}.classList.contains('hg-av-static')")
    assert c.js(f"{q2}.getAnimations({{subtree: true}}).length") > 0                 # the hop
    c.js(f"window.__hop = {q2}")
    c.js("render()")                                    # a poll with nothing new: the same nodes, nothing replays
    assert c.js(f"window.__hop === {q2}")
    c.js("render(true)")                                # a forced rebuild: the done pose, still
    assert c.js(f"window.__hop !== {q2} && {q2}.classList.contains('hg-av-static') && {q2}.classList.contains('hg-av-done')")
    assert c.js(f"{q2}.getAnimations({{subtree: true}}).length") == 0
    # an answer that arrives while the page is open hops once, when it first shows; the thread it joins (q1's
    # passage) is rebuilt around it, and the answers already there, which hopped when it opened, stay still
    st = busy["store"]
    doc = st.load("map")["document"]
    q = ask(st, "Is the KV cache allocated once?", map_anchor(doc, doc["revision"], "caches keys and values per layer"))
    c.goto(busy["url"] + f"#q={q['id']}")
    assert c.js("document.querySelector('.nd.cur .wait') !== null")
    before = c.js("[...UI.hopped]")
    assert len(before) >= 4 and c.js("document.querySelectorAll('#pbody .by .av > svg:not(.hg-av-static)').length") == len(before)
    answer(st, Repo.open(busy["repo"]), q, "investigator", [
        C("t1", "Yes: `generate` builds it once with `max_len=cfg.block_size`", "read_in_source",
          A("engine.py", "        cache = self._cache or KVCache(cfg, batch=1, max_len=cfg.block_size)"))])
    new = by % q["id"]
    c.wait(f"{new} !== null", 8)
    assert c.js(f"!{new}.classList.contains('hg-av-static') && {new}.getAnimations({{subtree: true}}).length > 0")
    rid = c.js(f"{new}.parentElement.dataset.hop")
    assert c.js("[...UI.hopped]") == before + [rid]
    assert c.js("[...document.querySelectorAll('#pbody .by .av > svg:not(.hg-av-static)')].map(s => s.parentElement.dataset.hop)") == [rid]


def test_nothing_inline_runs_and_nothing_is_fetched_with_the_avatars(busy, chrome):
    c = chrome
    c.call("Page.addScriptToEvaluateOnNewDocument", source=(
        "window.__csp = []; document.addEventListener('securitypolicyviolation', "
        "e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"))
    c.goto(busy["url"] + f"#q={busy['ids']['q5']}")
    for tab in ("nav", "notes", "thread"):
        c.click_el(f'[data-tab="{tab}"]')
    c.hover_el("#pbody .av.working")
    wait_ms(c, 300)
    assert c.js("window.__csp") == []                  # no inline script or style was blocked (nor needed)
    base = busy["url"].rstrip("/")
    for u in c.js("performance.getEntriesByType('resource').map(e => e.name)"):
        path = u[len(base):].split("?")[0] if u.startswith(base + "/") else u
        assert path in ("/page.css", "/page.js", "/boot.js", "/diagrams.js", "/favicon.svg", "/avatars.css",
                        "/hg-avatars.js") or path.startswith("/api/"), u
    assert c.js("[...document.querySelectorAll('svg.hg-av')].every(s => !/(href|src)=|url\\(/.test(s.outerHTML))")

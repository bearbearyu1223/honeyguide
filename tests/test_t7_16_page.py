"""T7.16 on the map page, against the real server and the fixture store, in headless Chrome (under perl's alarm):

- 3. an answer whose two claim spans are two sentences reads with a space between them, both when ``answer record``
  stored the space and for an answer recorded before it did (a display-only space, offsets unchanged);
- 4. a path with no runtime trace says "read in source, not run", never "not in the runtime trace" or "trace blind
  spot"; a traced path keeps those words;
- 5. at a 408px panel, a claim's "not supported" flag and chips stay inside the panel, and its tooltip inside the
  viewport;
- 6. the overlay for a Tracer answer is as wide as its diagram up to its own room (not the column's 1000px), scales
  down to 0.85 at most, then scrolls; tested with the live nanochat answer's path;
- 9. the nanochat module graph (10 boxes, 17 arrows) is laid out top to bottom: under 1000px, at most 3 boxes a row,
  the T7.4/T7.15 label and text checks hold, and the crossings it reports are the crossings drawn.

Also: a follow-up anchored in an answer that a repair later narrowed is re-found by its quote.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_16_nanochat import NANOCHAT_COMPS, NANOCHAT_EDGES, NANOCHAT_ISO, NANOCHAT_STARTS, NANOCHAT_WINDOW_PATH
from t7_page_fixture import A, C, S, answer, answer_anchor, ask, build, check_all
from test_t7_diagrams import check_graph, collect

from honeyguide.gitio import Repo
from honeyguide.mapdoc import text_revision
from honeyguide.server import make_server
from honeyguide.store import Store

ENGINE_ANCHORS = [A("engine.py", "    def advance(self, t):"), A("engine.py", "class Engine:"),
                  A("engine.py", "        self._cache = None"), A("engine.py", "def sample(logits, temperature):")]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("t716"), "base")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    repo = Repo.open(info["repo"])
    ids = info["ids"]
    doc = store.load("map")["document"]
    from t7_page_fixture import map_anchor
    rev = doc["revision"]
    # an answer in two sentences (two claim spans, nothing between them), one claim citing four places, flagged
    q = ask(store, "Where does the cache live?", map_anchor(doc, rev, "caches keys and values per layer"))
    r = answer(store, repo, q, "investigator",
               [C("s1", "Engine keeps the cache on self._cache", "read_in_source", A("engine.py", "        self._cache = None")),
                C("s2", "KVCache.advance moves pos on after every step", "read_in_source", *ENGINE_ANCHORS)],
               spans=[S("The cache lives on self._cache.", "s1"), S("The pos counter moves on after every step.", "s2")])
    check_all(store, r, {"s2": "advance only adds t to pos; the four cited places don't show it runs after every step"})
    # the same answer as it was stored before answer record spaced sentences: no glue span, the text run together
    q_old = ask(store, "And before the fix?", map_anchor(doc, rev, "caches keys and values per layer"))
    r_old = answer(store, repo, q_old, "investigator",
                   [C("o1", "Engine keeps the cache on self._cache", "read_in_source", A("engine.py", "        self._cache = None")),
                    C("o2", "KVCache.advance adds t to pos", "read_in_source", A("engine.py", "    def advance(self, t):"))],
                   spans=[S("The cache lives on self._cache.", "o1"), S("The pos counter grows by t.", "o2")])

    def legacy(d):
        for resp in d["responses"]:
            if resp["id"] == r_old["id"]:
                resp["spans"] = [s for s in resp["spans"] if s.get("claim")]
                resp["text"] = "".join(s["text"] for s in resp["spans"])
                resp["revision"] = text_revision(resp["text"])
    store.update("answers", legacy)
    check_all(store, next(x for x in store.load("answers")["responses"] if x["id"] == r_old["id"]))
    # a follow-up on the two-sentence answer, then the answer narrowed by a repair: the follow-up is re-found
    r_now = next(x for x in store.load("answers")["responses"] if x["id"] == r["id"])
    q_fu = ask(store, "Which step?", answer_anchor(r_now, "after every step"), r["id"])
    # a Tracer answer with no runtime trace: every hop read, one into code a trace can't see
    q_t = ask(store, "What happens when generate runs?", map_anchor(doc, rev, "caches keys and values per layer"))
    r_t = answer(store, repo, q_t, "tracer",
                 [C("t1", "generate runs the model on the prompt", "read_in_source", A("engine.py", "        logits = self.model(x, cache=cache)  # prefill")),
                  C("t2", "sample draws from the softmax", "read_in_source", A("engine.py", "    return torch.multinomial(probs, 1)"))],
                 path={"id": "pt", "title": "What happens when generate runs",
                       "lanes": [{"id": "e", "label": "engine.py · Engine", "path": "engine.py"},
                                 {"id": "m", "label": "model.py · GPT", "path": "model.py"}],
                       "hops": [{"from": "e", "to": "m", "call": "self.model(x, cache=cache)", "trace": "unseen", "claim": "t1"},
                                {"from": "e", "to": "e", "call": "torch.multinomial(probs, 1)", "trace": "blind_spot", "claim": "t2"}]},
                 spans=[S("generate runs the model, then samples.", "t1")])
    check_all(store, r_t)
    ids.update(q_two=q["id"], r_two=r["id"], q_old=q_old["id"], r_old=r_old["id"], q_fu=q_fu["id"], q_t=q_t["id"], r_t=r_t["id"])
    server = make_server(repo, store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info.update(store_obj=store, server=server, url=f"http://127.0.0.1:{server.server_address[1]}/")
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


def prose(c, host):
    """An answer's words as the reader sees them, without the citation marks after each claim."""
    return c.js(f"(() => {{ const x = document.querySelector('{host} .atext').cloneNode(true); "
                "x.querySelectorAll('.cite,.sr').forEach(e => e.remove()); return x.textContent; })()")


def open_at(c, url, hash_, panel=408, width=1440):
    c.viewport(width, 900)
    c.goto(url)
    c.js(f"localStorage.setItem('honeyguide.panelWidth', '{panel}')")
    c.goto(url + hash_)
    settle(c, 250)


# -- 3. two sentences --------------------------------------------------------------------------------------------------


def test_a_two_sentence_answer_reads_with_a_space(site, chrome):
    c = chrome
    store = site["store_obj"]
    r = next(x for x in store.load("answers")["responses"] if x["id"] == site["ids"]["r_two"])
    assert "self._cache. The pos" in r["text"]                       # stored with the space (answer record)
    open_at(c, site["url"], f"#q={site['ids']['q_two']}")
    text = prose(c, f'.ans[data-doc="answer:{r["id"]}"]')
    assert "self._cache. The pos counter" in text and "_cache.The" not in text
    assert c.js(f"document.querySelectorAll('.ans[data-doc=\"answer:{r['id']}\"] .sgap').length") == 0   # none needed


def test_an_answer_stored_without_the_space_shows_one_and_keeps_its_offsets(site, chrome):
    c = chrome
    store = site["store_obj"]
    r = next(x for x in store.load("answers")["responses"] if x["id"] == site["ids"]["r_old"])
    assert "self._cache.The pos" in r["text"]                         # as recorded before T7.16
    open_at(c, site["url"], f"#q={site['ids']['q_old']}")
    host = f'.ans[data-doc="answer:{r["id"]}"]'
    assert "self._cache. The pos counter" in prose(c, host)
    assert c.js(f"document.querySelectorAll('{host} .sgap').length") == 1
    # selecting "The pos" gives the stored text's offsets, as before: the space is not part of the answer
    got = c.js(f"""(() => {{ const el = [...document.querySelectorAll('{host} .atext .lf')].find(l => l.textContent.startsWith('The pos'));
      const rg = document.createRange(); rg.setStart(el.firstChild, 0); rg.setEnd(el.firstChild, 7);
      getSelection().removeAllRanges(); getSelection().addRange(rg); const s = readSelection(); getSelection().removeAllRanges();
      return [s.start, s.end, s.quote]; }})()""")
    start = r["text"].index("The pos")
    assert got == [start, start + 7, "The pos"]


def test_a_follow_up_is_refound_after_a_repair_narrows_its_answer(site, chrome):
    c = chrome
    store = site["store_obj"]
    rid = site["ids"]["r_two"]
    before = next(x for x in store.load("answers")["responses"] if x["id"] == rid)

    def narrow(d):   # what claims repair --response does to the text: a span rewritten, text and revision follow
        for resp in d["responses"]:
            if resp["id"] == rid:
                resp["spans"][0]["text"] = "The cache is on self._cache."
                resp["text"] = "".join(s["text"] for s in resp["spans"])
                resp["revision"] = text_revision(resp["text"])
    store.update("answers", narrow)
    try:
        open_at(c, site["url"], f"#q={site['ids']['q_two']}")
        marks = c.js(f"[...document.querySelectorAll('.ans[data-doc=\"answer:{rid}\"] .fmk')].map(m => m.textContent).join('')")
        assert marks == "after every step"
    finally:
        store.update("answers", lambda d: [resp.update(before) for resp in d["responses"] if resp["id"] == rid])


# -- 4. trace wording ----------------------------------------------------------------------------------------------------


def test_a_path_with_no_trace_says_read_not_run(site, chrome):
    c = chrome
    open_at(c, site["url"], f"#q={site['ids']['q_t']}")
    host = f'.ans[data-doc="answer:{site["ids"]["r_t"]}"]'
    words = c.js(f"[...document.querySelectorAll('{host} .hop-l .tr')].map(t => t.textContent)")
    assert words == ["read in source, not run", "read in source, not run"]
    text = c.js(f"document.querySelector('{host}').innerText")
    assert "not in the runtime trace" not in text and "trace blind spot" not in text.lower()
    assert "Not traceable:" in c.js(f"document.querySelector('{host} .hop-blind').textContent")
    c.click_el(f'[data-dgview="resp:{site["ids"]["r_t"]}"]')
    settle(c)
    key = c.js("[...document.querySelectorAll('#dgovfig .dg-key .lgt')].map(t => t.textContent).join(' | ')")
    assert "call into code a Python trace can't see (not run)" in key and "trace blind spot" not in key
    c.click_el('#dgovfig .dg-a[data-kind="call"][data-hop="0"] .fn')
    c.wait("!!document.querySelector('#prev .snip-ctx')", 5)
    assert "read in source, not run" in c.js("document.querySelector('#prev .snip-ctx').innerText")
    c.key("Escape")


def test_a_traced_path_keeps_the_trace_words(site, chrome):
    c = chrome
    open_at(c, site["url"], f"#q={site['ids']['q3a']}")
    host = f'.ans[data-doc="answer:{site["ids"]["r3a"]}"]'
    words = c.js(f"[...document.querySelectorAll('{host} .hop-l .tr')].map(t => t.textContent)")
    assert "not in the runtime trace" in words and "trace blind spot" in words


# -- 5. flags inside the panel at 408px ----------------------------------------------------------------------------------


def test_flags_and_chips_stay_inside_the_panel_at_408(site, chrome):
    c = chrome
    open_at(c, site["url"], f"#q={site['ids']['q_two']}", panel=408)
    assert c.js("Math.round(document.getElementById('panel').getBoundingClientRect().width)") == 408
    out = c.js("""(() => { const p = document.getElementById('panel').getBoundingClientRect();
      return [...document.querySelectorAll('#pbody .ans .flag, #pbody .ans .chip, #pbody .ans .ok')].map(e => {
        const r = e.getBoundingClientRect(); return [e.className, e.textContent, r.left >= p.left - 0.5 && r.right <= p.right - 8]; }); })()""")
    assert out and all(ok for _, _, ok in out), [x for x in out if not x[2]]
    host = f'.ans[data-doc="answer:{site["ids"]["r_two"]}"]'
    assert c.js(f"document.querySelectorAll('{host} .chip').length") >= 5         # the four-place cite is drawn
    # the flag's tooltip opens inside the viewport
    c.js(f"document.querySelector('{host} .flag').scrollIntoView({{block: 'center'}})")
    settle(c, 200)                     # the panel's scroll event hides any tooltip: let it pass first
    c.hover_el(f"{host} .flag")
    settle(c, 200)
    tip = c.js("(() => { const t = document.getElementById('tip'); const r = t.getBoundingClientRect(); return [t.classList.contains('on'), r.left, r.right, innerWidth, t.innerText]; })()")
    assert tip[0] and tip[1] >= 0 and tip[2] <= tip[3] and "advance only adds t to pos" in tip[4]


# -- 6. the overlay is as wide as its diagram ------------------------------------------------------------------------------

OVERLAY = """((path) => {
  const key = 'resp:t716';
  FIGS.set(key, diagramModel(path, new Map(), true, key));
  const fig = viewDiagram(key);
  return new Promise(r => setTimeout(() => {
    const ov = document.getElementById('dgov').getBoundingClientRect(), box = document.querySelector('#dgov .dgov-c').getBoundingClientRect();
    const svg = fig.querySelector('svg'), panel = document.getElementById('panel').getBoundingClientRect();
    r({ov: [ov.left, ov.right], box: [box.left, box.right], svg: svg.getBoundingClientRect().width, natural: +svg.dataset.natural,
       scrolls: fig.classList.contains('scrolls'), panelLeft: document.body.classList.contains('popen') ? panel.left : null,
       scrollW: fig.querySelector('.dgwrap').scrollWidth, clientW: fig.querySelector('.dgwrap').clientWidth});
  }, 250));
})(%s)"""


def test_the_overlay_is_as_wide_as_its_diagram(site, chrome):
    c = chrome
    path = json.dumps(NANOCHAT_WINDOW_PATH)
    # a wide screen, the panel closed: the overlay spends its room on the diagram, past the column's 1000px
    open_at(c, site["url"], "", width=1920)
    o = c.js(OVERLAY % path)
    room = o["ov"][1] - o["ov"][0] - 64
    assert o["natural"] > room                                    # the nanochat answer's diagram is wider than any screen
    assert abs((o["box"][1] - o["box"][0]) - room) <= 1 and o["box"][1] - o["box"][0] > 1000
    scale = o["svg"] / o["natural"]
    assert (scale >= 0.85 - 1e-3 and not o["scrolls"]) or (abs(scale - 0.85) < 0.01 and o["scrolls"] and o["scrollW"] > o["clientW"])
    c.key("Escape")
    # the panel open at 408px: never over the panel, the same rule in less room
    open_at(c, site["url"], f"#q={site['ids']['q_two']}", width=1440)
    o = c.js(OVERLAY % path)
    assert o["panelLeft"] is not None and o["ov"][1] <= o["panelLeft"] + 0.5
    assert abs((o["box"][1] - o["box"][0]) - (o["ov"][1] - o["ov"][0] - 64)) <= 1
    assert o["scrolls"] and abs(o["svg"] / o["natural"] - 0.85) < 0.01
    c.key("Escape")
    # a diagram narrower than the room: the overlay shrinks to it, shown at full size
    small = {**NANOCHAT_WINDOW_PATH, "lanes": NANOCHAT_WINDOW_PATH["lanes"][:2],
             "hops": [{"from": "train", "to": "gpt", "call": "GPT(config)", "trace": "unseen", "claim": "x"}]}
    lanes = {h_["from"] for h_ in small["hops"]} | {h_["to"] for h_ in small["hops"]}
    small["lanes"] = [ln for ln in NANOCHAT_WINDOW_PATH["lanes"] if ln["id"] in lanes] or small["lanes"]
    open_at(c, site["url"], "", width=1920)
    o = c.js(OVERLAY % json.dumps(small))
    assert o["natural"] < 1000 and o["svg"] >= o["natural"] - 2 and not o["scrolls"]
    assert o["box"][1] - o["box"][0] <= max(560, o["natural"] + 2) + 1
    c.key("Escape")


# -- 9. the nanochat module graph, top to bottom --------------------------------------------------------------------------

GRAPH = """((comps, edges, starts, iso) => {
  const gm = {comps: comps.map(([id, name, role, entry]) => ({id, name, role, entry, files: [name], module: null, title: ''})),
    edges: edges.map(([from, to, n]) => ({from, to, calls: [...Array(n)].map((_, i) => ({fn: 'f' + i, flow: 'map:x', title: 'x', hop: i}))})),
    starts: starts.map(([comp, label]) => ({comp, label, flow: 'map:x'})), iso, flows: 5};
  FIGS.set('graph', gm);
  renderFigs(true);
  const lr = HGD.layoutGraphLR(gm, 1000), tb = HGD.layoutGraphTB(gm, 1000);
  const svg = document.querySelector('#ovgraph svg');
  const rows = {};
  for (const n of svg.querySelectorAll('.dg-node .gbox')) rows[n.getAttribute('y')] = (rows[n.getAttribute('y')] || 0) + 1;
  return {lr: lr.natural, tb: tb.natural, dir: svg.dataset.dir, crossings: +svg.dataset.crossings, rows: Object.values(rows),
          boxes: svg.querySelectorAll('.dg-node').length, arrows: svg.querySelectorAll('.dg-e').length,
          shown: svg.getBoundingClientRect().width, vb: svg.viewBox.baseVal.width};
})(%s)"""


def test_the_nanochat_graph_is_laid_out_top_to_bottom(site, chrome):
    c = chrome
    open_at(c, site["url"], "", width=1440)
    c.js("document.getElementById('pclose')?.click()")
    assert c.js("document.querySelector('#ovgraph svg').dataset.dir") == "lr"      # the fixture's small graph: as before
    args = ", ".join(json.dumps(x) for x in (NANOCHAT_COMPS, NANOCHAT_EDGES, NANOCHAT_STARTS, NANOCHAT_ISO))
    out = c.js(GRAPH % args)
    assert out["boxes"] == 10 and out["arrows"] == 17
    assert 1000 / out["lr"] < 0.8                     # left to right would shrink it (to 57%)
    assert out["dir"] == "tb" and out["tb"] <= 1000 and out["shown"] >= out["tb"] - 1   # it fits, at full size
    assert max(out["rows"]) <= 3 and sum(out["rows"]) == 10
    g = collect(c, "#ovgraph svg")
    drawn = []
    got = check_graph(c, g, crossings=drawn)
    want = {(a, b): n for a, b, n in NANOCHAT_EDGES}
    assert {(a, b): n for a, b, n, _, _ in got} == want
    # the crossings the layout reports are the ones drawn (pairs of different components' lines that meet)
    assert len(drawn) == out["crossings"], (len(drawn), out["crossings"], drawn)
    print(f"nanochat graph, top to bottom: {out['tb']}px wide (left to right: {out['lr']}px), rows {out['rows']}, "
          f"{out['crossings']} crossing(s)")


def test_the_top_to_bottom_layout_has_no_crossings_when_none_are_needed(site, chrome):
    """A chain with a long edge and a fan: drawable without a crossing, so it is drawn without one."""
    c = chrome
    open_at(c, site["url"], "", width=1440)
    comps = [("a", "a.py", "the entry", True), ("b", "b.py", "step two", False), ("c", "c.py", "step three", False),
             ("d", "d.py", "the end", False), ("e", "e.py", "a side branch", False)]
    edges = [("a", "b", 2), ("b", "c", 1), ("c", "d", 1), ("a", "d", 1), ("a", "e", 3), ("e", "d", 1)]
    out = c.js("""((comps, edges) => {
      const gm = {comps: comps.map(([id, name, role, entry]) => ({id, name, role, entry, files: [name], module: null, title: ''})),
        edges: edges.map(([from, to, n]) => ({from, to, calls: [...Array(n)].map((_, i) => ({fn: 'f' + i, flow: 'map:x', title: 'x', hop: i}))})),
        starts: [{comp: 'a', label: 'main', flow: 'map:x'}], iso: [], flows: 1};
      const G = HGD.layoutGraphTB(gm, 1000);
      document.querySelector('#ovgraph .dgwrap').innerHTML = HGD.renderGraph(G);
      return G.crossings; })(%s, %s)""" % (json.dumps(comps), json.dumps(edges)))
    assert out == 0
    drawn = []
    check_graph(c, collect(c, "#ovgraph svg"), crossings=drawn)
    assert drawn == []


def test_the_top_to_bottom_layout_draws_a_cycle(site, chrome):
    """A call back up (a cycle) runs from the caller's bottom up beside the rows to the callee's top; the label and
    text checks hold and the crossings reported are the ones drawn."""
    c = chrome
    open_at(c, site["url"], "", width=1440)
    comps = [("a", "a.py", "the entry", True), ("b", "b.py", "the worker", False), ("c", "c.py", "a helper", False)]
    edges = [("a", "b", 2), ("b", "c", 1), ("c", "a", 1), ("b", "a", 1)]
    out = c.js("""((comps, edges) => {
      const gm = {comps: comps.map(([id, name, role, entry]) => ({id, name, role, entry, files: [name], module: null, title: ''})),
        edges: edges.map(([from, to, n]) => ({from, to, calls: [...Array(n)].map((_, i) => ({fn: 'f' + i, flow: 'map:x', title: 'x', hop: i}))})),
        starts: [{comp: 'a', label: 'main', flow: 'map:x'}], iso: [], flows: 1};
      const G = HGD.layoutGraphTB(gm, 1000);
      document.querySelector('#ovgraph .dgwrap').innerHTML = HGD.renderGraph(G);
      return [G.crossings, document.querySelectorAll('#ovgraph .dg-e').length]; })(%s, %s)""" % (json.dumps(comps), json.dumps(edges)))
    assert out[1] == 4
    drawn = []
    check_graph(c, collect(c, "#ovgraph svg"), crossings=drawn)
    assert len(drawn) == out[0]

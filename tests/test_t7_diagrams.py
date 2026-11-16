"""The flow diagrams and the module graph on the map page (T7.4), against the real server and the fixture store,
in headless Chrome. These are the v3.1 mockup's hard checks, run on real contract data:

- every hop is one call arrow; the diagram and the Steps rail agree on labels, order, anchors, evidence and data;
- line style follows the hop (solid = read in source or seen at runtime, dashed = inferred, dotted = blind spot);
- loop hops sit inside their frame, the others outside; no text box touches a foreign line; no two labels overlap;
  only safe characters; lane roles are the Modules headings;
- module graph: counts are the flows' cross-file calls, weight ordered like counts, no crossing lines, one entry
  point, and every "N calls" label sits on its own line and nearer to it than to any other line by a label height;
- previews on hover / click / Enter with the hop line and links; Steps toggle; View as diagram (map flow: scroll
  and flash; not a map flow: an overlay over the map, never the panel, Escape closes it); graph clicks; with the
  panel open and too little room, steps instead of a shrunken diagram (choice 7); nothing fetched;
- the header is memory.memory_state, as /api/state returns it.

Text boxes are the browser's own (getBBox), not the layout's estimates, so a font wider than estimated fails here.
"""

from __future__ import annotations

import json
import threading
from itertools import combinations
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import DOCUMENT, FLOWS, MAP_CLAIMS, build, set_visits

from honeyguide.gitio import Repo
from honeyguide.mapdoc import check_document
from honeyguide.memory import memory_state
from honeyguide.server import make_server, state
from honeyguide.store import Store

READ_OR_SEEN = {"read_in_source", "asserted_by_test", "seen_at_runtime"}
EVIDENCE = {c["key"]: c["evidence"] for c in MAP_CLAIMS}


def serve(tmp, variant):
    info = build(tmp, variant)
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    repo = Repo.open(info["repo"])
    server = make_server(repo, store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info.update(store_obj=store, repo_obj=repo, server=server, url=f"http://127.0.0.1:{server.server_address[1]}/")
    return info


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = serve(tmp_path_factory.mktemp("dg"), "base")
    yield info
    info["server"].shutdown()
    info["server"].server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=90) as c:
        yield c


def settle(c, ms=120):
    c.js(f"new Promise(r => setTimeout(r, {ms}))")


def open_flows(c, url):
    c.goto(url)
    c.js("localStorage.removeItem('honeyguide.panelWidth')")
    c.js("document.querySelectorAll('.flow-h').forEach(b => b.click())")
    settle(c)


# -- geometry from the page ------------------------------------------------------------------------------------------

COLLECT = r"""((sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  const own = el => { const g = el.closest('.dg-a,.dg-e,.dg-node'); return g ? {kind: g.dataset.kind || (g.matches('.dg-e') ? 'edge' : 'node'), hop: g.dataset.hop ?? null, lane: g.dataset.lane ?? null, from: g.dataset.from ?? null, to: g.dataset.to ?? null} : null; };
  const texts = [...svg.querySelectorAll('text')].map(t => { const b = t.getBBox(); return {cls: t.getAttribute('class') || '', text: t.textContent, box: [b.x, b.y, b.width, b.height], owner: own(t), key: !!t.closest('.dg-key')}; });
  const segs = [];
  const add = (el, x1, y1, x2, y2) => segs.push({cls: el.getAttribute('class') || '', x1, y1, x2, y2, owner: own(el), lane: el.dataset.lane ?? null, key: !!el.closest('.dg-key'), from: el.dataset.from ?? null});
  for (const l of svg.querySelectorAll('line')) add(l, +l.getAttribute('x1'), +l.getAttribute('y1'), +l.getAttribute('x2'), +l.getAttribute('y2'));
  for (const p of svg.querySelectorAll('path.ln, path.gw')) {
    let x = 0, y = 0;
    for (const [, op, args] of p.getAttribute('d').matchAll(/([MHVL])([^MHVLZ]*)/g)) {
      const v = args.trim().split(/[\s,]+/).map(Number);
      if (op === 'M') { x = v[0]; y = v[1]; }
      else if (op === 'H') { add(p, x, y, v[0], y); x = v[0]; }
      else if (op === 'V') { add(p, x, y, x, v[0]); y = v[0]; }
      else { add(p, x, y, v[0], v[1]); x = v[0]; y = v[1]; }
    }
  }
  const frames = [...svg.querySelectorAll('rect.frame[data-loop]')].map(r => ({loop: r.dataset.loop, y0: +r.getAttribute('y'), y1: +r.getAttribute('y') + +r.getAttribute('height')}));
  const calls = [...svg.querySelectorAll('.dg-a[data-kind="call"]')].map(g => ({hop: +g.dataset.hop, loop: g.dataset.loop || null, style: g.dataset.style, ev: g.dataset.ev, claim: g.dataset.claim,
    fn: g.querySelector('.fn').textContent, anc: g.querySelector('.anc').textContent, y: +(g.querySelector('line.ln')?.getAttribute('y1') ?? g.querySelector('.fn').getAttribute('y'))}));
  const pills = [...svg.querySelectorAll('.dg-a[data-kind="ret"], .dg-a[data-kind="data"]')].map(g => ({hop: +g.dataset.hop, kind: g.dataset.kind, text: g.querySelector('text.ptx').textContent}));
  return {texts, segs, frames, calls, pills, lanes: [...svg.querySelectorAll('.lane-h')].map(h => [h.querySelector('.lane-n').textContent, h.querySelector('.lane-s')?.textContent || '']),
          styled: svg.querySelectorAll('[style]').length, w: svg.viewBox.baseVal.width, shown: svg.getBoundingClientRect().width};
})(%s)"""


def collect(c, selector):
    out = c.js(COLLECT % json.dumps(selector))
    assert out, selector
    return out


def seg_hits_box(s, box, pad=0.5):
    """An axis-aligned (or any) segment intersects the box shrunk by ``pad``."""
    x, y, w, h = box
    x0, y0, x1, y1 = x + pad, y + pad, x + w - pad, y + h - pad
    if x1 <= x0 or y1 <= y0:
        return False
    ax, ay, bx, by = s["x1"], s["y1"], s["x2"], s["y2"]
    steps = max(2, int(max(abs(bx - ax), abs(by - ay))))   # sample along the segment, one point per unit
    return any(x0 <= ax + (bx - ax) * t / steps <= x1 and y0 <= ay + (by - ay) * t / steps <= y1 for t in range(steps + 1))


def seg_box_distance(s, box):
    x, y, w, h = box
    best = 1e9
    ax, ay, bx, by = s["x1"], s["y1"], s["x2"], s["y2"]
    steps = max(2, int(max(abs(bx - ax), abs(by - ay))))
    for t in range(steps + 1):
        px, py = ax + (bx - ax) * t / steps, ay + (by - ay) * t / steps
        dx, dy = max(x - px, 0, px - (x + w)), max(y - py, 0, py - (y + h))
        best = min(best, (dx * dx + dy * dy) ** 0.5)
    return best


def boxes_overlap(a, b, pad=0.5):
    return a[0] + pad < b[0] + b[2] - pad and b[0] + pad < a[0] + a[2] - pad and \
        a[1] + pad < b[1] + b[3] - pad and b[1] + pad < a[1] + a[3] - pad


def segs_cross(s, t):
    """Two axis-aligned segments share a point."""
    def rng(a, b):
        return min(a, b), max(a, b)
    sx, sy, tx, ty = rng(s["x1"], s["x2"]), rng(s["y1"], s["y2"]), rng(t["x1"], t["x2"]), rng(t["y1"], t["y2"])
    return sx[0] <= tx[1] + 0.01 and tx[0] <= sx[1] + 0.01 and sy[0] <= ty[1] + 0.01 and ty[0] <= sy[1] + 0.01


SAFE = set(range(0x20, 0x7F)) | set(range(0xA0, 0x180)) | set(range(0x2010, 0x2070)) | set(range(0x2190, 0x2200)) \
    | set(range(0x2200, 0x2300))


def expected_style(hop, evidence=EVIDENCE):
    if hop["trace"] == "blind_spot":
        return "dotted"
    return "solid" if hop["trace"] == "seen" or evidence.get(hop["claim"]) in READ_OR_SEEN else "dashed"


def edge_text(hop):
    if hop.get("returns") and hop.get("data"):
        return f"{hop['returns']} {hop['data']}"
    if hop.get("returns"):
        return f"returns {hop['returns']}"
    return f"data {hop['data']}" if hop.get("data") else None


def check_sequence(g, flow, evidence=EVIDENCE):
    """The geometric hard checks for one rendered sequence diagram (``g`` from COLLECT)."""
    hops = flow["hops"]
    # call arrows = hops, in order; line style follows the hop
    assert [x["hop"] for x in g["calls"]] == list(range(len(hops)))
    assert [x["fn"] for x in g["calls"]] == [h["call"] for h in hops]
    assert [x["style"] for x in g["calls"]] == [expected_style(h, evidence) for h in hops]
    # every rail edge is drawn, once, with the same words
    want = {i: edge_text(h) for i, h in enumerate(hops) if edge_text(h)}
    got = {p["hop"]: " ".join(p["text"].split()) for p in g["pills"]}
    assert got == {i: " ".join(t.split()) for i, t in want.items()}
    # loop hops inside their frame, the others outside every frame
    for x in g["calls"]:
        inside = [f["loop"] for f in g["frames"] if f["y0"] < x["y"] < f["y1"]]
        assert inside == ([x["loop"]] if x["loop"] else []), (x["fn"], inside)
    assert sorted({f["loop"] for f in g["frames"]}) == sorted({h["loop"] for h in hops if h.get("loop")})
    # no text box touches a foreign line (a pill's own return line and its own lane's lifeline excepted)
    lines = [s for s in g["segs"] if not s["key"]]
    for t in (t for t in g["texts"] if not t["key"]):
        for s in lines:
            o, so = t["owner"] or {}, s["owner"] or {}
            if o.get("kind") == "ret" and so.get("kind") == "ret" and o.get("hop") == so.get("hop"):
                continue
            if o.get("kind") == "data" and "life" in s["cls"] and s["lane"] == o.get("lane"):
                continue
            assert not seg_hits_box(s, t["box"]), (t["text"], s)
    # no two labels overlap (tspans live inside one text, so each text is one label)
    for a, b in combinations(g["texts"], 2):
        assert not boxes_overlap(a["box"], b["box"]), (a["text"], b["text"])
    # safe characters only (no tofu): ASCII, Latin-1, general punctuation, arrows, maths
    for t in g["texts"]:
        assert all(ord(ch) in SAFE for ch in t["text"]), t["text"]
    assert g["styled"] == 0                      # nothing for the page's CSP to block


# -- the tests ---------------------------------------------------------------------------------------------------------

def test_contract_additions_validate():
    errors, _ = check_document(DOCUMENT)
    assert errors == []
    bad = json.loads(json.dumps(DOCUMENT))
    bad["sections"][1]["blocks"][0]["role"] = "two\nlines"
    bad["sections"][1]["blocks"][1]["entry"] = "yes"
    bad["sections"][0]["blocks"][0]["role"] = "a role on a text block"
    bad["flows"][0]["hops"][0]["note"] = 3
    errors, _ = check_document(bad)
    assert len(errors) == 4 and any("note must be a string" in e for e in errors)
    assert sum("role" in e for e in errors) == 2 and any("entry" in e for e in errors)


def test_state_carries_memory_state(site):
    s = state(site["repo_obj"], site["store_obj"])
    m = memory_state(site["repo_obj"], site["store_obj"])
    assert {k: v for k, v in s["memory"].items() if k != "last_visit"} == {k: v for k, v in m.items() if k != "last_visit"}
    assert s["memory"]["state"] == "up_to_date"


def test_sequence_diagrams_hold_the_hard_checks(site, chrome):
    c = chrome
    open_flows(c, site["url"])
    assert c.console_errors() == []
    roles = {b["path"]: b.get("role", "") for b in DOCUMENT["sections"][1]["blocks"]}
    for flow in FLOWS:
        sel = f'.fig[data-key="map:{flow["id"]}"] svg'
        g = collect(c, sel)
        check_sequence(g, flow)
        # lane headers: the lane's label and, where the Modules section has the file, its role, as on the page
        used = list(dict.fromkeys(x for h in flow["hops"] for x in (h["from"], h["to"])))
        lanes = {l["id"]: l for l in flow["lanes"]}
        assert g["lanes"] == [[lanes[i]["label"], roles.get(lanes[i].get("path"), "")] for i in used]
        page_roles = c.js("Object.fromEntries([...document.querySelectorAll('.mod[data-path]')].map(m => [m.dataset.path, m.querySelector('.role')?.textContent || '']))")
        assert all(sub == page_roles.get(lanes[i].get("path"), "") for (_, sub), i in zip(g["lanes"], used, strict=True))
        # the Steps rail says the same: labels, order, anchors, evidence, data
        rail = c.js(f"""[...document.querySelectorAll('.flow[data-flow="{flow['id']}"] .rail .hop')].map(h => ({{
            fn: h.querySelector('.fn').textContent, chip: h.querySelector('.chip')?.textContent || '',
            ev: ([...h.querySelector('.node').classList].find(k => k.startsWith('ev-')) || '').slice(3),
            style: [...h.classList].find(k => k.startsWith('s-')).slice(2)}}))""")
        assert [r["fn"] for r in rail] == [x["fn"] for x in g["calls"]]
        assert [r["chip"] for r in rail] == [x["anc"] for x in g["calls"]]
        assert [r["ev"] for r in rail] == [x["ev"] for x in g["calls"]]
        assert [r["ev"] for r in rail] == [EVIDENCE[h["claim"]] for h in flow["hops"]]
        assert [r["style"] for r in rail] == [x["style"] for x in g["calls"]]
        edges = c.js(f"""[...document.querySelectorAll('.flow[data-flow="{flow['id']}"] .rail .edge span')].map(e => e.querySelector('b').textContent + ' ' + e.textContent.slice(e.querySelector('b').textContent.length))""")
        assert [" ".join(e.split()) for e in edges] == [" ".join(p["text"].split()) for p in sorted(g["pills"], key=lambda p: p["hop"])]
    # the fixture exercises what the diagram has to handle
    step = collect(c, '.fig[data-key="map:f-step"] svg')
    assert {x["style"] for x in step["calls"]} == {"solid", "dashed", "dotted"}
    assert c.js("""document.querySelector('.fig[data-key="map:f-step"] .k-call.s-dotted .dnote').textContent""").startswith("Trace blind spot: autograd")
    ret = c.js("""(() => { const l = document.querySelector('.fig[data-key="map:f-step"] .dg-a[data-kind="ret"][data-hop="1"] line'); return [+l.getAttribute('x1'), +l.getAttribute('x2')]; })()""")
    data_x = c.js("""+document.querySelector('.fig[data-key="map:f-step"] .life[data-lane="data"]').getAttribute('x1')""")
    assert min(ret) < data_x < max(ret)          # a return that crosses another lane
    gen = collect(c, '.fig[data-key="map:f-gen"] svg')
    assert c.js("""document.querySelectorAll('.fig[data-key="map:f-gen"] .k-call path.ln').length""") == 3   # self-calls
    assert len(gen["frames"]) == 1 and [x["loop"] for x in gen["calls"]] == [None, None, "tok", "tok", None]


def test_module_graph_counts_lines_and_labels(site, chrome):
    c = chrome
    c.goto(site["url"])
    g = collect(c, "#ovgraph svg")
    # counts = the flows' calls between two different files (lanes with a path)
    want = {}
    for f in FLOWS:
        files = {l["id"]: l.get("path") for l in f["lanes"]}
        for h in f["hops"]:
            a, b = files[h["from"]], files[h["to"]]
            if a and b and a != b:
                want[(a, b)] = want.get((a, b), 0) + 1
    got = c.js("[...document.querySelectorAll('#ovgraph .dg-e')].map(e => [e.dataset.from, e.dataset.to, +e.dataset.n, +e.querySelector('.gdrop').getAttribute('stroke-width'), e.querySelector('.gcnt').textContent])")
    assert {(a, b): n for a, b, n, _, _ in got} == want
    assert all(lab == f"{n} call{'s' if n > 1 else ''}" for _, _, n, _, lab in got)
    assert all((n1 < n2) == (w1 < w2) for (_, _, n1, w1, _), (_, _, n2, w2, _) in combinations(got, 2))
    # the defect T7.4 fixes: two lines into model.py, each with a "2 calls" label
    assert sorted(n for a, b, n, _, _ in got if b == "model.py") == [2, 2]
    # one entry point
    assert c.js("[...document.querySelectorAll('#ovgraph .gtag')].map(t => t.closest('.dg-node').dataset.file)") == ["train.py"]
    # no crossing lines: segments of different sources never meet (a source's own stub, bus and drops do)
    segs = [s for s in g["segs"] if not s["key"]]

    def source(s):
        o = s["owner"] or {}
        return o.get("from") or s.get("from") or ("start", s["y1"])
    for s, t in combinations(segs, 2):
        if source(s) != source(t):
            assert not segs_cross(s, t), (s, t)
    # every count label sits on its own drop (right of the bus, left of the arrowhead), within 6px of it, and
    # every other line is farther than its own by at least one label height
    for e in c.js("""[...document.querySelectorAll('#ovgraph .dg-e')].map(e => { const b = e.querySelector('.gcnt').getBBox();
        return {from: e.dataset.from, to: e.dataset.to, box: [b.x, b.y, b.width, b.height]}; })"""):
        mine = [s for s in segs if (s["owner"] or {}).get("from") == e["from"] and (s["owner"] or {}).get("to") == e["to"]]
        assert len(mine) == 1
        own = mine[0]
        d_own = seg_box_distance(own, e["box"])
        assert d_own <= 6 and not seg_hits_box(own, e["box"])
        assert min(own["x1"], own["x2"]) < e["box"][0] and e["box"][0] + e["box"][2] < max(own["x1"], own["x2"])
        for s in segs:
            if s is own:
                continue
            assert seg_box_distance(s, e["box"]) >= d_own + e["box"][3], (e, s)
    # and no text in the graph touches a line or another text
    for t in (t for t in g["texts"] if not t["key"]):
        for s in segs:
            assert not seg_hits_box(s, t["box"]), (t["text"], s)
    for a, b in combinations(g["texts"], 2):
        assert not boxes_overlap(a["box"], b["box"]), (a["text"], b["text"])
    assert g["styled"] == 0


def test_previews_open_on_hover_click_and_enter(site, chrome):
    c = chrome
    open_flows(c, site["url"])
    blind = '.fig[data-key="map:f-step"] .dg-a[data-kind="call"][data-hop="2"]'
    c.hover_el(blind + " .fn")
    c.wait("document.getElementById('prev').style.display === 'block' && !!document.querySelector('#prev pre')", 5)
    text = c.js("document.getElementById('prev').innerText")
    assert "Hop 3 of 4" in text and "loss.backward()" in text and "Trace blind spot:" in text and "train.py" in text
    assert c.js("document.querySelector('#prev .ln.hl').textContent").strip().endswith("loss.backward()")
    assert c.js("!!document.querySelector('#prev a.lk[href^=\"https://github.com/example/tinytrain/blob/\"]')")
    c.click_el(blind + " .fn")
    assert c.js(f"document.querySelector('{blind}').classList.contains('pin')")
    c.key("Escape")
    assert c.js("document.getElementById('prev').style.display") == "none"
    # a return pill is a button too; Enter pins it, its preview names the hop and what it returns
    ret = '.fig[data-key="map:f-step"] .dg-a[data-kind="ret"][data-hop="0"]'
    c.js(f"document.querySelector('{ret}').focus()")
    c.key("Enter")
    c.wait("document.getElementById('prev').innerText.includes('Hop 1 of 4')", 5)
    assert c.js(f"document.querySelector('{ret}').classList.contains('pin')")
    assert "Hop 1 of 4" in c.js("document.getElementById('prev').innerText") and "returns" in c.js("document.getElementById('prev').innerText")
    c.key("Escape")


def test_steps_toggle_and_rail(site, chrome):
    c = chrome
    open_flows(c, site["url"])
    f = '.flow[data-flow="f-gen"]'
    assert c.js(f"getComputedStyle(document.querySelector('{f} .fig')).display") == "block"
    assert c.js(f"getComputedStyle(document.querySelector('{f} .rail')).display") == "none"
    c.click_el(f + ' [data-fview="list"]')
    assert c.js(f"getComputedStyle(document.querySelector('{f} .fig')).display") == "none"
    assert c.js(f"getComputedStyle(document.querySelector('{f} .rail')).display") == "block"
    assert c.js(f"document.querySelector('{f} [data-fview=\"list\"]').getAttribute('aria-pressed')") == "true"
    c.click_el(f + ' .fviews [data-fview="dg"]')
    assert c.js(f"getComputedStyle(document.querySelector('{f} .fig')).display") == "block"


def test_view_as_diagram_for_a_map_flow_scrolls_and_flashes(site, chrome):
    c = chrome
    c.media(reduced_motion=False)
    c.goto(site["url"] + f"#q={site['ids']['q3a']}")
    settle(c, 250)
    c.click_el(f'[data-dgview="resp:{site["ids"]["r3a"]}"]')
    fig = '.flow[data-flow="f-step"] .fig'
    assert c.js(f"document.querySelector('{fig}').classList.contains('flashfig')")
    assert c.js("document.querySelector('.flow[data-flow=\"f-step\"]').classList.contains('open')")
    top = c.js(f"document.querySelector('{fig}').getBoundingClientRect().top")
    assert 0 <= top <= 200
    assert not c.js("document.getElementById('dgov').classList.contains('on')")
    # the panel stays open beside the diagram, which keeps its width rule
    assert c.js("document.body.classList.contains('popen')")
    right = c.js(f"document.querySelector('{fig}').getBoundingClientRect().right")
    assert right <= c.js("document.getElementById('panel').getBoundingClientRect().left")


def test_view_as_diagram_under_reduced_motion_is_a_still_ring(site, chrome):
    c = chrome
    c.media(reduced_motion=True)
    try:
        c.goto(site["url"] + f"#q={site['ids']['q3a']}")
        settle(c, 250)
        c.click_el(f'[data-dgview="resp:{site["ids"]["r3a"]}"]')
        fig = '.flow[data-flow="f-step"] .fig'
        assert c.js(f"getComputedStyle(document.querySelector('{fig}')).outlineStyle") == "solid"
        assert c.js(f"getComputedStyle(document.querySelector('{fig}')).animationName") == "none"
    finally:
        c.media(reduced_motion=False)


def test_tracer_path_that_is_not_a_map_flow_opens_an_overlay(site, chrome):
    c = chrome
    c.goto(site["url"] + f"#q={site['ids']['q1c']}")
    settle(c, 250)
    scroll = c.js("document.getElementById('main').scrollTop")
    flows_before = c.js("[...document.querySelectorAll('.flow.open')].length")
    c.click_el(f'[data-dgview="resp:{site["ids"]["r1c"]}"]')
    assert c.js("document.getElementById('dgov').classList.contains('on')")
    ov = c.js("(() => { const r = document.getElementById('dgov').getBoundingClientRect(); return [r.left, r.right]; })()")
    assert ov[1] <= c.js("document.getElementById('panel').getBoundingClientRect().left") + 0.5
    assert ov[0] >= c.js("document.getElementById('side').getBoundingClientRect().right") - 0.5
    resp = next(r for r in site["store_obj"].load("answers")["responses"] if r["id"] == site["ids"]["r1c"])
    g = collect(c, "#dgovfig svg")
    check_sequence(g, resp["path"], {x["id"]: x["evidence"] for x in resp["claims"]})
    assert [x["loop"] for x in g["calls"]] == [h.get("loop") for h in resp["path"]["hops"]]
    c.click_el('#dgovfig .dg-a[data-kind="call"][data-hop="4"] .fn')
    c.wait("!!document.querySelector('#prev .snip-ctx')", 5)
    assert "Hop 5 of 6" in c.js("document.getElementById('prev').innerText")
    c.key("Escape")                       # first Escape unpins and closes the overlay
    assert not c.js("document.getElementById('dgov').classList.contains('on')")
    assert c.js("document.getElementById('main').scrollTop") == scroll
    assert c.js("[...document.querySelectorAll('.flow.open')].length") == flows_before
    assert c.js("document.body.classList.contains('popen')")


def test_graph_clicks_lead_to_modules_and_calls(site, chrome):
    c = chrome
    c.goto(site["url"])
    c.click_el('#ovgraph .dg-node[data-file="data.py"] .gbox')
    top = c.js("document.querySelector('.mod[data-path=\"data.py\"]').getBoundingClientRect().top")
    assert 0 <= top <= 200 and c.js("document.querySelector('.mod[data-path=\"data.py\"]').classList.contains('flashed')")
    c.js("document.getElementById('main').scrollTop = 0")
    c.click_el('#ovgraph .dg-e[data-from="train.py"][data-to="model.py"] .gcnt')
    hl = c.js("[...document.querySelectorAll('.dg-a.hl')].map(g => g.closest('svg').dataset.key + ':' + g.dataset.hop)")
    assert sorted(hl) == ["map:f-step:1", "map:f-step:2"]
    assert c.js("document.querySelector('.flow[data-flow=\"f-step\"]').classList.contains('open')")
    # hovering an arrow lists its calls
    c.hover_el('#ovgraph .dg-e[data-from="engine.py"][data-to="model.py"] .gcnt')
    settle(c)
    tip = c.js("document.getElementById('tip').innerText")
    assert "engine.py calls model.py" in tip and "model(nxt, cache=cache)" in tip


def test_panel_open_and_too_narrow_shows_steps(site, chrome):
    c = chrome
    c.goto(site["url"])
    c.js("localStorage.setItem('honeyguide.panelWidth', '720')")
    try:
        c.goto(site["url"] + f"#q={site['ids']['q2']}")
        c.js("document.querySelector('.flow[data-flow=\"f-step\"] .flow-h').click()")
        f = '.flow[data-flow="f-step"]'
        w = c.js("+document.documentElement.style.getPropertyValue('--fw').replace('px', '')")
        natural = c.js("HGD.layoutSeq(FIGS.get('map:f-step'), 1).natural")
        assert w / natural < 0.85
        assert c.js(f"document.querySelector('{f}').classList.contains('view-auto')")
        assert c.js(f"getComputedStyle(document.querySelector('{f} .rail')).display") == "block"
        assert c.js(f"getComputedStyle(document.querySelector('{f} .fnarrow')).display") == "block"
        c.click_el(f + " .fnarrow button")
        assert c.js(f"getComputedStyle(document.querySelector('{f} .fig')).display") == "block"
        # closing the panel gives the diagram its room back
        c.click_el("#pclose")
        c.js("document.querySelector('.flow[data-flow=\"f-gen\"] .flow-h').click()")
        assert not c.js("document.querySelector('.flow[data-flow=\"f-gen\"]').classList.contains('view-auto')")
    finally:
        c.js("localStorage.removeItem('honeyguide.panelWidth')")


def test_nothing_is_fetched_but_the_page_and_its_api(site, chrome):
    c = chrome
    open_flows(c, site["url"])
    c.hover_el('.fig[data-key="map:f-gen"] .dg-a[data-kind="call"][data-hop="1"] .fn')
    settle(c, 500)
    urls = c.js("performance.getEntriesByType('resource').map(e => e.name)")
    base = site["url"].rstrip("/")
    for u in urls:
        assert u.startswith(base + "/"), u
        path = u[len(base):].split("?")[0]
        assert path in ("/page.css", "/page.js", "/boot.js", "/diagrams.js", "/favicon.svg") or path.startswith("/api/"), u
    assert any(u.endswith("/diagrams.js") for u in urls)


def test_header_uses_memory_state(tmp_path_factory, chrome):
    info = serve(tmp_path_factory.mktemp("dgr"), "refreshed")
    try:
        c = chrome
        set_visits(info["store_obj"], **info["visits"])
        c.goto(info["url"])
        m = memory_state(info["repo_obj"], info["store_obj"])
        assert m["state"] == "refreshing" and m["rechecked_since_visit"] >= 1
        mem = c.js("document.getElementById('mem').innerText")
        assert " ".join(m["headline"].split()) in " ".join(mem.split())
        assert "Up to date" not in mem
        n = m["rechecked_since_visit"]
        assert f"{n} claim{'s' if n != 1 else ''} re-checked since your last visit" in mem
        live = m["freshness"]["current"] + m["freshness"]["stale"]
        assert f"{live} claims" in mem and f"{m['freshness']['stale']} stale" in mem
    finally:
        info["server"].shutdown()
        info["server"].server_close()

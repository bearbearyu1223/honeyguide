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
        sel = f'.fig[data-key="map:{flow["id"]}"] .dgwrap > svg'
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
    step = collect(c, '.fig[data-key="map:f-step"] .dgwrap > svg')
    assert {x["style"] for x in step["calls"]} == {"solid", "dashed", "dotted"}
    assert c.js("""document.querySelector('.fig[data-key="map:f-step"] .k-call.s-dotted .dnote').textContent""").startswith("Trace blind spot: autograd")
    ret = c.js("""(() => { const l = document.querySelector('.fig[data-key="map:f-step"] .dg-a[data-kind="ret"][data-hop="1"] line'); return [+l.getAttribute('x1'), +l.getAttribute('x2')]; })()""")
    data_x = c.js("""+document.querySelector('.fig[data-key="map:f-step"] .life[data-lane="data"]').getAttribute('x1')""")
    assert min(ret) < data_x < max(ret)          # a return that crosses another lane
    gen = collect(c, '.fig[data-key="map:f-gen"] .dgwrap > svg')
    assert c.js("""document.querySelectorAll('.fig[data-key="map:f-gen"] .k-call path.ln').length""") == 3   # self-calls
    assert len(gen["frames"]) == 1 and [x["loop"] for x in gen["calls"]] == [None, None, "tok", "tok", None]


def component_of(document):
    """path -> the module block (component) holding it: the block listing the file, else the one whose directory holds
    it; a lane no module covers is its own component, ``file:<path>`` (T7.15; diagrams.js resolver)."""
    comps = [(b["id"], b.get("files") or [b["path"]]) for sec in document["sections"] for b in sec["blocks"]
             if b.get("type") == "module"]

    def of(path):
        for cid, files in comps:
            if path in files:
                return cid
        dirs = sorted(((f if f.endswith("/") else f + "/", cid) for cid, files in comps for f in files),
                      key=lambda x: -len(x[0]))
        return next((cid for d, cid in dirs if path.startswith(d)), "file:" + path)
    return of


def expected_edges(flows, document):
    of = component_of(document)
    want = {}
    for f in flows:
        files = {l["id"]: l.get("path") for l in f["lanes"]}
        for h in f["hops"]:
            a, b = files[h["from"]], files[h["to"]]
            if a and b and of(a) != of(b):
                want[(of(a), of(b))] = want.get((of(a), of(b)), 0) + 1
    return want


MAP_COLLECT = r"""((sel, view) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  if (view) svg.dataset.view = view;
  const vis = el => getComputedStyle(el).display !== 'none' && !el.closest('[style*="display: none"]');
  const edges = [...svg.querySelectorAll('.dg-e')].filter(vis).map(e => {
    const p = e.querySelector('.gw'), n = p.getTotalLength(), pts = [];
    for (let i = 0; i <= Math.max(24, Math.ceil(n / 4)); i++) { const q = p.getPointAtLength(n * i / Math.max(24, Math.ceil(n / 4))); pts.push([q.x, q.y]); }
    const hb = e.querySelector('.gh').getBBox();
    return {from: e.dataset.from, to: e.dataset.to, n: +e.dataset.n, main: e.dataset.main === '1', w: +p.getAttribute('stroke-width'), pts, head: [hb.x, hb.y, hb.width, hb.height]};
  });
  const boxes = [...svg.querySelectorAll('.dg-node')].map(g => { const r = g.querySelector('.gbox'); return {id: g.dataset.comp, box: [+r.getAttribute('x'), +r.getAttribute('y'), +r.getAttribute('width'), +r.getAttribute('height')]}; });
  const texts = [...svg.querySelectorAll('text')].map(t => { const b = t.getBBox(); return {cls: t.getAttribute('class') || '', text: t.textContent, box: [b.x, b.y, b.width, b.height], node: t.closest('.dg-node')?.dataset.comp || null, key: !!t.closest('.dg-key'), size: parseFloat(getComputedStyle(t).fontSize)}; });
  const ctm = svg.getScreenCTM();
  return {edges, boxes, texts, styled: svg.querySelectorAll('[style]').length - (svg.hasAttribute('style') ? 0 : 0), scale: ctm ? ctm.a : 1,
          crossings: +svg.dataset.crossings, view: svg.dataset.view};
})(%s, %s)"""


def hover_path(c, selector):
    """Move the pointer onto the middle of an edge's drawn line (a curve's box centre is often off the line)."""
    pt = c.js(f"""(() => {{ const p = document.querySelector({json.dumps(selector)}); p.scrollIntoView({{block: 'center'}});
      const n = p.getTotalLength(), q = p.getPointAtLength(n / 2), m = p.getScreenCTM(); return [m.a * q.x + m.e, m.d * q.y + m.f]; }})()""")
    c.mouse("mouseMoved", pt[0], pt[1])


def collect_map(c, selector="#ovgraph .dgwrap > svg", view=None):
    out = c.js(MAP_COLLECT % (json.dumps(selector), json.dumps(view)))
    assert out, selector
    return out


def _seg_cross(a, b, c_, d):
    r = (b[0] - a[0], b[1] - a[1]); s_ = (d[0] - c_[0], d[1] - c_[1])
    den = r[0] * s_[1] - r[1] * s_[0]
    if abs(den) < 1e-9:
        return None
    t = ((c_[0] - a[0]) * s_[1] - (c_[1] - a[1]) * s_[0]) / den
    u = ((c_[0] - a[0]) * r[1] - (c_[1] - a[1]) * r[0]) / den
    return (a[0] + t * r[0], a[1] + t * r[1]) if 0 <= t <= 1 and 0 <= u <= 1 else None


def drawn_crossings(edges):
    """Points where two drawn edges cross, from the browser's own path geometry (each point once per pair)."""
    out = []
    for i, j in combinations(range(len(edges)), 2):
        A, B = edges[i]["pts"], edges[j]["pts"]
        pts = []
        for a in range(len(A) - 1):
            for b in range(len(B) - 1):
                p = _seg_cross(A[a], A[a + 1], B[b], B[b + 1])
                if p and not any(abs(p[0] - q[0]) + abs(p[1] - q[1]) < 4 for q in pts):
                    pts.append(p)
        out += [((edges[i]["from"], edges[i]["to"]), (edges[j]["from"], edges[j]["to"]), p) for p in pts]
    return out


def _dist_to_polyline(p, pts):
    best = 1e9
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        t = 0 if dx == dy == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, ((ax + t * dx - p[0]) ** 2 + (ay + t * dy - p[1]) ** 2) ** 0.5)
    return best


def longest_shared_run(A, B, tol=0.6):
    """The longest stretch (in px along A) over which A stays within ``tol`` of B: a crossing gives a few px at most,
    a shared bus segment its whole length."""
    best = run = 0.0
    for i, p in enumerate(A):
        if _dist_to_polyline(p, B) < tol:
            if i:
                run += ((p[0] - A[i - 1][0]) ** 2 + (p[1] - A[i - 1][1]) ** 2) ** 0.5
            best = max(best, run)
        else:
            run = 0.0
    return best


def inside(p, box, pad=1.0):
    x, y, w, h = box
    return x + pad < p[0] < x + w - pad and y + pad < p[1] < y + h - pad


def check_map(c, g):
    """The component map's guarantees (T7.17), on the browser's geometry: weights ordered like counts; no count label
    on a line (counts are on hover); every edge has its own ports (no shared segment: no two edges share a start or
    an end point, and no two edges run along each other); no line through a box but its own ends; no line through
    text; no two texts overlapping; nothing styled inline (CSP)."""
    E = g["edges"]
    assert all((a["n"] < b["n"]) == (a["w"] < b["w"]) for a, b in combinations(E, 2))
    assert not any(t["cls"] == "gcnt" for t in g["texts"])
    starts = [tuple(round(v) for v in e["pts"][0]) for e in E]
    ends = [tuple(round(v) for v in e["pts"][-1]) for e in E]
    assert len(set(starts)) == len(starts) and len(set(ends)) == len(ends), "two edges share a port"
    for a, b in combinations(E, 2):     # no shared run: two lines may cross, never run along each other
        run = longest_shared_run(a["pts"], b["pts"])
        assert run < 12, ("shared segment", a["from"], a["to"], b["from"], b["to"], run)
    for e in E:
        for b in g["boxes"]:
            hits = [p for p in e["pts"][1:-1] if inside(p, b["box"], 2)]
            assert not hits, ("line through a box", e["from"], e["to"], b["id"])
        for t in g["texts"]:
            if t["key"]:
                continue
            assert not any(inside(p, t["box"], 0.5) for p in e["pts"]), ("line through text", e["from"], e["to"], t["text"])
    body = [t for t in g["texts"] if not t["key"]]
    for a, b in combinations(body, 2):
        assert not boxes_overlap(a["box"], b["box"]), (a["text"], b["text"])
    for t in g["texts"]:
        assert all(ord(ch) in SAFE for ch in t["text"]), t["text"]
    return {(e["from"], e["to"]): e["n"] for e in E}


def test_module_graph_counts_lines_and_labels(site, chrome):
    """An older map whose modules are single files (``path``): each file is a component, as before T7.15. T7.17: the
    component map shows the main paths by default and every call with "Show all"; counts are on hover only."""
    c = chrome
    c.goto(site["url"])
    g = collect_map(c, view="all")
    got = check_map(c, g)
    # counts = the flows' calls between two different components
    assert got == expected_edges(FLOWS, DOCUMENT)
    # the defect T7.4 fixed stays fixed: two lines into model.py, each its own
    assert sorted(n for (a, b), n in got.items() if b == "m-model") == [2, 2]
    # boxes are named by their file; one entry point
    names = c.js("Object.fromEntries([...document.querySelectorAll('#ovgraph .dg-node')].map(n => [n.dataset.comp, n.querySelector('.gname').textContent]))")
    assert names == {"m-train": "train.py", "m-data": "data.py", "m-model": "model.py", "m-optim": "optim.py",
                     "m-engine": "engine.py"}
    assert c.js("[...document.querySelectorAll('#ovgraph .gtag')].map(t => t.closest('.dg-node').dataset.comp)") == ["m-train"]
    # a count shows on hover, not on the line
    c.click_el('#ovgraph [data-gall="1"]')         # engine -> model is not a main path: show every call
    hover_path(c, '#ovgraph .dg-e[data-from="m-engine"][data-to="m-model"] .gw')
    settle(c)
    assert "2 calls in 1 traced flow" in c.js("document.getElementById('tip').innerText")
    # a component in no traced flow gets no box: one quiet line under the graph, linking to its module
    assert c.js("document.getElementById('ovgraph-iso').innerText") == "Not in a traced flow: Tiktoken's gpt2 encoding"
    c.click_el('#ovgraph-iso a[data-gomod="m-tok"]')
    assert c.js("document.querySelector('.mod[data-block=\"m-tok\"]').classList.contains('flashed')")
    c.js("document.getElementById('main').scrollTop = 0")


def test_module_graph_by_component_on_the_v2_map(tmp_path_factory, chrome):
    """T7.15: one box per component (``train.py`` + ``optim.py`` is one box, its own calls inside it dropped), the
    role as its subtitle, the files on hover and (T7.17) in the expanded node; the map's guarantees hold."""
    info = serve(tmp_path_factory.mktemp("dgv2"), "v2")
    try:
        from t7_page_fixture import DOCUMENT_V2
        c = chrome
        c.goto(info["url"])
        g = collect_map(c, view="all")
        got = check_map(c, g)
        want = expected_edges(FLOWS, DOCUMENT_V2)
        assert got == want
        assert ("m-train", "m-train") not in want and want == {("m-train", "m-data"): 1, ("m-train", "m-model"): 2,
                                                               ("m-engine", "m-model"): 2}
        nodes = c.js("""[...document.querySelectorAll('#ovgraph .dg-node')].map(n => [n.dataset.comp, n.querySelector('.gname').textContent,
            n.querySelector('.grole')?.textContent || '', n.dataset.files])""")
        assert sorted(nodes) == sorted([["m-train", "train.py", "the training loop", "train.py optim.py"],
                                        ["m-data", "data.py", "the sharded token loader", "data.py"],
                                        ["m-model", "model.py", "GPT, attention blocks", "model.py"],
                                        ["m-engine", "engine.py", "sampling with a KV cache", "engine.py"]])
        c.hover_el('#ovgraph .dg-node[data-comp="m-train"] .gbox')
        settle(c)
        tip = c.js("document.getElementById('tip').innerText")
        assert "Files: train.py, optim.py" in tip and "Click to focus" in tip
        # the node expands to list its files, and folds again
        assert c.js("document.querySelector('#ovgraph .gexp[data-expand=\"m-train\"] text').textContent") == "+1 file"
        c.click_el('#ovgraph .gexp[data-expand="m-train"] rect')
        settle(c)
        assert c.js("[...document.querySelectorAll('#ovgraph .dg-node[data-comp=\"m-train\"] .gfile')].map(t => t.textContent)") == ["train.py", "optim.py"]
        check_map(c, collect_map(c, view="all"))
        c.click_el('#ovgraph .gexp[data-expand="m-train"] rect')
        settle(c)
        assert c.js("document.querySelectorAll('#ovgraph .gfile').length") == 0
        assert c.js("document.getElementById('ovgraph-iso').innerText") == "Not in a traced flow: Tiktoken's gpt2 encoding"
        assert c.js("document.querySelector('#ovgraph .dgwrap > svg').getAttribute('aria-label')") == \
            "Component map: 4 components and the calls between them"
    finally:
        info["server"].shutdown()
        info["server"].server_close()


def test_graph_model_resolves_directories_and_uncovered_files(site, chrome):
    """The pure model: a directory component takes the files under it, the deepest directory wins, a lane no
    component covers is its own box, and calls inside a component are not edges."""
    c = chrome
    c.goto(site["url"])
    out = c.js("""(() => {
      const comps = [{id: "tasks", files: ["tasks/", "scripts/chat_eval.py"], role: "chat tasks"},
                     {id: "sub", files: ["tasks/deep/"], role: "a deeper directory"},
                     {id: "gpt", files: ["nanochat/gpt.py"], role: "the model", entry: true},
                     {id: "bench", files: ["scripts/bench.py"], role: "benchmark"}];
      const lanes = {a: {file: "scripts/chat_eval.py"}, b: {file: "tasks/humaneval.py"}, c: {file: "nanochat/gpt.py"},
                     d: {file: "tasks/deep/x.py"}, e: {file: "nanochat/other.py"}, f: {file: null}};
      const M = {key: "map:x", title: "x", lanes, hops: [{from: "a", to: "b", fn: "inside"}, {from: "a", to: "c", fn: "one"},
        {from: "b", to: "c", fn: "two"}, {from: "a", to: "d", fn: "deep"}, {from: "c", to: "e", fn: "loose"}, {from: "c", to: "f", fn: "nofile"}]};
      const gm = HGD.graphModel([M], comps);
      return {edges: gm.edges.map(e => [e.from, e.to, e.calls.length]), iso: gm.iso, starts: gm.starts.map(s => s.comp),
              names: gm.comps.map(HGD.compName)};
    })()""")
    assert sorted(map(tuple, out["edges"])) == [("gpt", "file:nanochat/other.py", 1), ("tasks", "gpt", 2), ("tasks", "sub", 1)]
    assert out["iso"] == ["bench"] and out["starts"] == ["tasks"]
    assert out["names"] == ["tasks/ +1", "tasks/deep/", "gpt.py", "bench.py", "nanochat/other.py"]


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
    g = collect(c, "#dgovfig .dgwrap > svg")
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


def test_graph_clicks_focus_components_and_lead_to_calls(site, chrome):
    """T7.17: a box click focuses the component (its focus card leads to its module); an arrow click still opens the
    flows and highlights its calls; hovering an arrow lists its calls."""
    c = chrome
    c.goto(site["url"])
    c.click_el('#ovgraph .dg-node[data-comp="m-data"] .gbox')
    assert c.js("document.querySelector('#ovgraph .dgwrap > svg').classList.contains('focus')")
    c.click_el('#gfocus a[data-gomod="m-data"]')
    top = c.js("document.querySelector('.mod[data-path=\"data.py\"]').getBoundingClientRect().top")
    assert 0 <= top <= 200 and c.js("document.querySelector('.mod[data-path=\"data.py\"]').classList.contains('flashed')")
    c.key("Escape")
    c.js("document.getElementById('main').scrollTop = 0")
    c.js("""document.querySelector('#ovgraph .dg-e[data-from="m-train"][data-to="m-model"]').dispatchEvent(new MouseEvent('click', {bubbles: true}))""")
    hl = c.js("[...document.querySelectorAll('.dg-a.hl')].map(g => g.closest('svg').dataset.key + ':' + g.dataset.hop)")
    assert sorted(hl) == ["map:f-step:1", "map:f-step:2"]
    assert c.js("document.querySelector('.flow[data-flow=\"f-step\"]').classList.contains('open')")
    # hovering an arrow lists its calls
    c.js("document.getElementById('main').scrollTop = 0")
    c.click_el('#ovgraph [data-gall="1"]')
    hover_path(c, '#ovgraph .dg-e[data-from="m-engine"][data-to="m-model"] .gw')
    settle(c)
    tip = c.js("document.getElementById('tip').innerText")
    assert "engine.py (sampling with a KV cache) calls model.py (GPT, attention blocks)" in tip
    assert "model(nxt, cache=cache)" in tip


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
        assert path in ("/page.css", "/page.js", "/boot.js", "/diagrams.js", "/favicon.svg", "/avatars.css",
                        "/hg-avatars.js") or path.startswith("/api/"), u
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
        # review r2: the count says which claims are the map's and which are in answers
        on_map = sum(c.get("freshness") in ("current", "stale") for c in info["store_obj"].load("map")["claims"])
        said = f"{on_map} claim{'s' if on_map != 1 else ''} on the map" + (f", {live - on_map} in answers" if live > on_map else "")
        assert said in " ".join(mem.split()) and f"{m['freshness']['stale']} stale" in mem
        # the refresh row: the Checker re-checking, its avatar at 22 and at work (T7.12)
        rf = c.js("(() => { const s = document.querySelector('.rf-w .av.working > svg'); "
                  "return s && [s.getAttribute('width'), s.getAttribute('class'), s.getAnimations({subtree: true}).length]; })()")
        assert rf and rf[0] == "22" and "hg-av-checker hg-av-working hg-av-22" in rf[1] and rf[2] > 0, rf
    finally:
        info["server"].shutdown()
        info["server"].server_close()

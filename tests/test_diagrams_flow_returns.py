"""A flow's return arrow goes back to the hop's own caller.

nanochat's chat-reply flow, row 7: ``engine -> tok`` (``tokenizer.decode(state.python_expr_tokens)``), then row 8 is
called from the root lane (``cli -> tok``). The page drew row 7's return to whoever acted next, the chat_cli.py lane,
though the call came from engine.py. diagrams.js is pure (no DOM), so it runs as is in a blank headless Chrome page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path

SRC = (Path(__file__).resolve().parents[1] / "src/honeyguide/page/diagrams.js").read_text()

# the shape of nanochat's chat-reply flow (lanes and edges only; the text is irrelevant to where an arrow points)
HOPS = [("cli", "ckpt", True, None), ("cli", "tok", True, None), ("cli", "engine", True, None),
        ("engine", "gpt", True, None), ("gpt", "attn", True, "gen"), ("engine", "gpt", True, "gen"),
        ("engine", "tok", True, "gen"), ("cli", "tok", True, "gen")]


def model(hops):
    lanes = sorted({x for h in hops for x in h[:2]})
    return {"key": "t", "id": "t", "title": "t", "lanes": {k: {"name": k, "sub": ""} for k in lanes},
            "loops": {"gen": "per token"}, "evNames": {},
            "hops": [{"fn": f"call{i}()", "a": f"x.py:{i + 1}", "ev": None, "style": "solid", "note": None, "d": "",
                      "from": f, "to": t, "edge": ["returns", "v"] if e else None, "loop": lp, "claim": f"c{i}",
                      "chip": None, "search": ""} for i, (f, t, e, lp) in enumerate(hops)]}


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=60) as c:
        yield c


def run(c, body: str, m):
    return c.js(f"(() => {{ {SRC}\n const M = {json.dumps(m)}; {body} }})()")


def test_edge_of_returns_to_the_caller(chrome):
    m = model(HOPS)
    got = run(chrome, "return M.hops.map((h, i) => HGD.edgeOf(M.hops, i));", m)
    want = [{"kind": "ret", "from": "ckpt", "to": "cli"},
            {"kind": "ret", "from": "tok", "to": "cli"},
            {"kind": "data", "lane": "engine"},           # engine makes the next hop: its data stays on its lane
            {"kind": "data", "lane": "gpt"},
            {"kind": "ret", "from": "attn", "to": "gpt"},  # was: to engine, the next hop's caller
            {"kind": "ret", "from": "gpt", "to": "engine"},
            {"kind": "ret", "from": "tok", "to": "engine"},  # row 7: was to cli
            {"kind": "ret", "from": "tok", "to": "cli"}]
    assert got == want
    # every return goes back to the lane that made the call
    for h, e in zip(m["hops"], got, strict=True):
        if e["kind"] == "ret":
            assert (e["from"], e["to"]) == (h["to"], h["from"])


def test_self_call_keeps_its_data(chrome):
    m = model([("a", "a", True, None), ("b", "c", False, None), ("a", "a", True, None)])
    assert run(chrome, "return M.hops.map((h, i) => HGD.edgeOf(M.hops, i));", m) == [
        {"kind": "data", "lane": "a"}, None, {"kind": "data", "lane": "a"}]


def test_drawn_return_arrow_ends_at_the_caller_lane(chrome):
    """The layout's arrow for row 7 runs from the tokenizer lane to the engine lane, not to chat_cli's."""
    m = model(HOPS)
    out = run(chrome, """const L = HGD.layoutSeq(M, 900), x = {}; L.lanes.forEach(l => (x[l.id] = l.x));
      return {x, rets: L.items.filter(it => it.kind === 'ret').map(it => ({hop: it.hop, x1: it.x1, x2: it.x2})),
              svg: HGD.renderSeq(L, M).length};""", m)
    x, rets = out["x"], {r["hop"]: r for r in out["rets"]}
    bar = 5   # D.bar: the arrow stops at the activation bar's edge
    for i, h in enumerate(m["hops"]):
        if i not in rets:
            continue
        r = rets[i]
        assert abs(r["x1"] - x[h["to"]]) <= bar and abs(r["x2"] - x[h["from"]]) <= bar, (i, r)
    assert abs(rets[6]["x2"] - x["engine"]) <= bar and abs(rets[6]["x2"] - x["cli"]) > bar
    assert out["svg"] > 0

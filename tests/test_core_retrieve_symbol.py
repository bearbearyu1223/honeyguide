"""``retrieve()`` scores 'same symbol' across different files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeyguide.retrieve import Context, retrieve  # noqa: E402


def claim(cid, path, symbol):
    return {"id": cid, "text": "t", "evidence": "read_in_source", "check": "supported",
            "freshness": "current",
            "anchors": [{"path": path, "anchor": "x", "start": 1, "end": 2, "commit": "c",
                         "hash": "h", "symbol": symbol}]}


def test_same_symbol_in_another_file_is_not_a_symbol_match():
    """Asking about scripts/a.py main must not pull a claim about
    scripts/b.py main as 'same symbol'."""
    m = {"claims": [claim("c1", "scripts/b.py", "main")]}
    ctx = Context(anchors=[{"path": "scripts/a.py", "start": 10, "end": 12, "symbol": "main"}])
    got = retrieve(m, {"questions": [], "responses": []}, {"notes": []}, ctx)
    assert got.map_claims == []

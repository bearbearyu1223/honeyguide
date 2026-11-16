"""Review r2 (f50781ad6, f6de4f933): the memory line at the repo card's foot says which claims it counts.

nanochat's card read "282 claims, every anchor resolved" while the map has 260: the count included the 22 claims in
its two live answers. It now reads "260 claims on the map, 22 in answers, every anchor resolved".
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import build

from honeyguide.gitio import Repo
from honeyguide.server import make_server
from honeyguide.store import Store

LIVE = ("current", "stale")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("r2count"), "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
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
    with Chrome(alarm=60) as c:
        yield c


def test_count_splits_map_and_answers(site, chrome):
    st = site["store_obj"]
    on_map = sum(c.get("freshness") in LIVE for c in st.load("map")["claims"])
    in_answers = sum(c.get("freshness") in LIVE for r in st.load("answers")["responses"] for c in r["claims"])
    assert on_map and in_answers                              # the fixture exercises both
    chrome.goto(site["url"])
    text = " ".join(chrome.js("document.getElementById('mem').innerText").split())
    assert f"{on_map} claims on the map, {in_answers} in answers" in text, text
    assert not re.search(rf"\b{on_map + in_answers} claims\b", text)   # the old, unlabelled total is gone

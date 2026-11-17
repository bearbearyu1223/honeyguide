"""The focus card names a multi-file component as its box does, first file plus "+N files".

On nanochat, the component holding scripts/chat_sft.py and scripts/chat_rl.py is drawn "chat_sft.py" with a "+1 file"
chip, but the focus card named it "chat_sft.py" alone, so a call it lists from scripts/chat_rl.py:106 read as a
misattribution. The grouping is right (both scripts are one module); the card's name dropped the badge. Here the v2
fixture's m-train holds train.py and optim.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from page_fixture import build

from honeyguide.gitio import Repo
from honeyguide.server import make_server
from honeyguide.store import Store

SVG = "#ovgraph .dgwrap > svg"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = build(tmp_path_factory.mktemp("card"), "v2")
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
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
    with Chrome(alarm=60) as c:
        yield c


def focus(c, url, comp):
    c.goto(url)
    c.js("localStorage.clear()")
    c.goto(url)
    c.click_el(f'{SVG} .dg-node[data-comp="{comp}"] .gbox')
    c.js("new Promise(r => setTimeout(r, 150))")


def test_caller_keeps_its_files_badge(site, chrome):
    focus(chrome, site["url"], "m-model")
    row = chrome.js("""(() => { const b = document.querySelector('#gfocus .gf-c[data-gfocus="m-train"]');
      const m = b.querySelector('.gf-more'); return {name: b.querySelector('code').textContent, more: m && m.textContent,
      title: m && m.title, box: document.querySelector('#ovgraph .dg-node[data-comp="m-train"]').textContent}; })()""")
    assert row["name"] == "train.py"
    assert row["more"] == "+1 file" and row["title"] == "train.py, optim.py"
    assert "+1 file" in row["box"]                      # the same badge the box carries
    # a one-file component gets no badge
    assert chrome.js("document.querySelector('#gfocus .gf-t .gf-more')") is None


def test_card_title_keeps_its_files_badge(site, chrome):
    focus(chrome, site["url"], "m-train")
    got = chrome.js("[...document.querySelectorAll('#gfocus .gf-t > *')].map(e => e.textContent)")
    assert got == ["train.py", "+1 file"]

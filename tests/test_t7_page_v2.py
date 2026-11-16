"""The map page on a T7.13 map (the fixture's ``v2`` variant): Overview topic headings, lists and facts, module facts
folded except the responsibility, "More" to expand; selection, Ask, Annotate and previews on the new blocks; and an
old map (the ``base`` variant) still renders. Headless Chrome under perl's alarm; skipped without Chrome.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from cdp import Chrome, chrome_path
from t7_page_fixture import build
from test_t7_page import drag_select

from honeyguide import inbox
from honeyguide.gitio import Repo
from honeyguide.mapdoc import plain_text
from honeyguide.server import make_server, server_token
from honeyguide.store import Store


def serve(info):
    store = Store(Path(info["store"]).name, root=Path(info["home"]))
    server = make_server(Repo.open(info["repo"]), store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    info.update(store=store, port=port, url=f"http://127.0.0.1:{port}/", token=server_token(store), server=server)
    return info


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    info = serve(build(tmp_path_factory.mktemp("v2"), "v2"))
    yield info
    info["server"].shutdown()
    info["server"].server_close()


@pytest.fixture(scope="module")
def chrome():
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=60) as c:
        yield c


def leaves_match(c, store) -> int:
    text = plain_text(store.load("map")["document"])
    leaves = c.js("[...document.querySelectorAll('#col .lf')].map(e => [+e.dataset.o, e.textContent])")
    for o, shown in leaves:
        assert text[o:o + len(shown)] == shown, (o, shown)
    return len(leaves)


def test_overview_topics_lists_and_facts_render_with_matching_offsets(site, chrome):
    c = chrome
    c.goto(site["url"])
    assert c.console_errors() == []
    assert leaves_match(c, site["store"]) > 80
    assert c.js("[...document.querySelectorAll('#s-overview h3.topic')].map(h => h.textContent)") == [
        "Purpose", "Who it's for", "What it can do", "Commands", "Entry points", "Components", "Start here"]
    assert c.js("document.querySelectorAll('#s-overview .blist li').length") == 9
    assert c.js("document.querySelector('[data-block=\"ov-start\"] ol') !== null")
    # commands render as code, component keys that name files too; the module graph follows Components
    assert c.js("document.querySelector('[data-block=\"ov-cmds\"] dd code').textContent") == "uv sync"
    assert c.js("document.querySelector('[data-block=\"ov-parts\"] dt code').textContent") == "model.py"
    assert c.js("document.querySelector('[data-block=\"ov-parts\"]').nextElementSibling.id") == "ovgraph"
    # every claim in a list item or a facts row carries its evidence mark and chips
    assert c.js("document.querySelectorAll('[data-block=\"ov-cmds\"] .claim').length") == 3
    assert c.js("document.querySelectorAll('[data-block=\"ov-cmds\"] .chip').length") >= 3


def test_module_facts_fold_except_responsibility_and_more_expands(site, chrome):
    c = chrome
    c.goto(site["url"])
    shown = "[...document.querySelectorAll('.mod[data-block=\"m-model\"] dt')].filter(e => e.offsetParent).map(e => e.textContent)"
    assert c.js(shown) == ["Responsibility"]
    assert c.js("document.querySelector('.mod[data-block=\"m-model\"] .more').getAttribute('aria-expanded')") == "false"
    c.click_el('.mod[data-block="m-model"] .more')
    assert c.js(shown) == ["Responsibility", "Key symbols", "Interfaces", "Inputs and outputs", "Tests"]
    assert c.js("document.querySelector('.mod[data-block=\"m-model\"] .more .mt').textContent") == "Less"
    c.click_el('.mod[data-block="m-model"] .more')
    assert c.js(shown) == ["Responsibility"]
    # a question on a folded fact opens its module, so its mark is visible
    assert c.js("document.querySelector('.mod[data-block=\"m-train\"]').classList.contains('open')")
    assert c.js("[...document.querySelectorAll('.mk')].some(m => m.offsetParent && m.closest('dd.fx'))")


@pytest.mark.parametrize("block, phrase, act", [
    ("ov-can", "so no shard is ever loaded whole", "ask"),
    ("ov-cmds", "which build a two-layer model on the CPU", "ask"),
    ("m-engine", "the cache is allocated once and never grows", "note"),
])
def test_selection_on_list_items_and_facts_lands_with_its_anchor(site, chrome, block, phrase, act):
    c = chrome
    c.goto(site["url"])
    if block.startswith("m-"):
        c.click_el(f'.mod[data-block="{block}"] .more')
    assert drag_select(c, f'[data-block="{block}"]', phrase).strip() == phrase
    c.click_el(f'#tb [data-act="{act}"]')
    c.wait("document.body.classList.contains('popen') && document.activeElement.id === 'cin'", 5)
    words = f"About {block}: {act}"
    c.type(words)
    c.key("Enter")
    text = plain_text(site["store"].load("map")["document"])
    if act == "ask":
        c.wait(f"[...document.querySelectorAll('.qt')].some(e => e.textContent.includes({words!r}))", 5)
        anchor = next(q for q in inbox.threads(site["store"])["questions"] if q["text"] == words)["anchor"]
    else:
        c.wait("document.getElementById('toast').textContent.includes('Saved to your notes')", 5)
        anchor = next(n for n in site["store"].load("notes")["notes"] if n["text"] == words)["anchor"]
    assert anchor["doc"] == "map" and anchor["quote"] == phrase and text[anchor["start"]:anchor["end"]] == phrase


def test_preview_opens_from_a_facts_row(site, chrome):
    c = chrome
    c.goto(site["url"])
    c.click_el('[data-block="ov-cmds"] .chip')
    c.wait("getComputedStyle(document.getElementById('prev')).display !== 'none' && "
           "document.getElementById('prev').innerText.includes('pyproject.toml')", 5)


def test_an_old_map_still_renders(tmp_path_factory, chrome):
    info = serve(build(tmp_path_factory.mktemp("old"), "base"))
    try:
        c = chrome
        c.goto(info["url"])
        assert c.console_errors() == []
        assert leaves_match(c, info["store"]) > 40
        assert c.js("document.querySelectorAll('h3.topic, .facts, .more, .blist').length") == 0
        assert c.js("document.querySelectorAll('.mod').length") == 6
        assert c.js("document.querySelector('#s-overview p.blk').nextElementSibling.id") == "ovgraph"
    finally:
        info["server"].shutdown()
        info["server"].server_close()

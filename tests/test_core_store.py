"""The memory store: layout, schema versions, crash safety, the lock, export/import."""

from __future__ import annotations

import json
import multiprocessing
import os

import pytest

from honeyguide import store as store_mod
from honeyguide.store import Store, StoreError, export_bundle, home, import_bundle, make_claim

ANCHOR = {"path": "a.py", "anchor": "def f(", "start": 1, "end": 2, "commit": "c" * 40, "hash": "h" * 16}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYGUIDE_HOME", str(tmp_path / "hg"))
    s = Store("github.com__o__r__abc")
    s.init({"id": "github.com__o__r__abc", "remote": "github.com/o/r", "root_commit": "abc"})
    return s


def test_home_override_and_layout(store, tmp_path):
    assert home() == tmp_path / "hg"
    assert store.dir == tmp_path / "hg" / "github.com__o__r__abc"
    store.save_map([make_claim("f loads", "read_in_source", [ANCHOR])], "c" * 40)
    store.add_note("mine", None)
    q = store.add_question("why?", None)
    store.add_response(q["id"], "because", [make_claim("b", "inferred", [ANCHOR])], "investigator")
    for layer in ("repo", "map", "answers", "notes"):
        data = json.loads((store.dir / f"{layer}.json").read_text())
        assert data["schema"] == f"honeyguide/{layer}" and data["version"] == 1


def test_records_round_trip(store):
    claim = make_claim("f loads", "read_in_source", [ANCHOR], section="modules")
    store.save_map([claim], "c" * 40)
    assert store.load("map")["claims"] == [claim]
    q = store.add_question("why?", {"doc": "map", "revision": "1", "quote": "f", "start": 0, "end": 1,
                                    "context": "x"})
    follow = store.add_question("and?", None, parent_response="r_x")
    r = store.add_response(q["id"], "because", [], "investigator", {"model": "m"})
    answers = store.load("answers")
    assert [x["id"] for x in answers["questions"]] == [q["id"], follow["id"]]
    assert answers["responses"][0]["parent"] == q["id"] and answers["responses"][0]["id"] == r["id"]
    with pytest.raises(KeyError):
        store.add_response("q_missing", "x", [], "investigator")
    store.set_check(claim["id"], "supported")
    assert store.load("map")["claims"][0]["check"] == "supported"
    with pytest.raises(ValueError):
        make_claim("x", "vibes", [])
    with pytest.raises(ValueError):
        make_claim("x", "read_in_source", [{"path": "a.py"}])


def test_interrupted_write_leaves_old_file_intact(store, monkeypatch):
    store.add_note("first", None)
    before = (store.dir / "notes.json").read_bytes()

    def crash(*args, **kwargs):
        raise OSError("power cut")

    monkeypatch.setattr(store_mod.os, "replace", crash)
    with pytest.raises(OSError):
        store.add_note("second", None)
    assert (store.dir / "notes.json").read_bytes() == before
    assert not [p for p in os.listdir(store.dir) if p.endswith(".tmp")]


def test_crash_mid_write_and_stray_temp_files_are_harmless(store, monkeypatch):
    store.add_note("first", None)
    before = (store.dir / "notes.json").read_bytes()
    real_fsync = os.fsync

    def die_after_partial(fd):
        raise KeyboardInterrupt  # killed after the temp file was written, before the rename

    monkeypatch.setattr(store_mod.os, "fsync", die_after_partial)
    with pytest.raises(KeyboardInterrupt):
        store.add_note("second", None)
    monkeypatch.setattr(store_mod.os, "fsync", real_fsync)
    assert (store.dir / "notes.json").read_bytes() == before
    (store.dir / ".notes.json.abandoned.tmp").write_text("{half")
    assert [n["text"] for n in store.load("notes")["notes"]] == ["first"]


def test_newer_or_unreadable_files_are_refused_not_overwritten(store):
    path = store.dir / "notes.json"
    path.write_text(json.dumps({"schema": "honeyguide/notes", "version": 99, "notes": []}))
    with pytest.raises(StoreError, match="newer"):
        store.add_note("x", None)
    path.write_text("{not json")
    with pytest.raises(StoreError, match="unreadable"):
        store.load("notes")
    assert path.read_text() == "{not json"
    path.write_text(json.dumps({"notes": []}))
    with pytest.raises(StoreError):
        store.load("notes")


def test_init_refuses_another_repo(store):
    with pytest.raises(StoreError):
        store.init({"id": "someone_else"})


def _add_notes(home_dir: str, count: int) -> None:
    os.environ["HONEYGUIDE_HOME"] = home_dir
    s = Store("github.com__o__r__abc")
    for i in range(count):
        s.add_note(f"n{i}", None)


def test_concurrent_writers_lose_nothing(store, tmp_path):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_add_notes, args=(str(tmp_path / "hg"), 15)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert len(store.load("notes")["notes"]) == 60


def test_lock_times_out_instead_of_hanging(store):
    with store.locked():
        other = Store(store.repo_id)
        with pytest.raises(StoreError, match="lock"):
            with other.locked(timeout=0.1):
                pass


def test_export_import_round_trip(store, tmp_path, monkeypatch):
    claim = make_claim("f loads", "read_in_source", [ANCHOR])
    store.save_map([claim], "c" * 40, document={"title": "map"})
    q = store.add_question("why?", None)
    store.add_response(q["id"], "because", [make_claim("b", "inferred", [ANCHOR])], "investigator")
    shared = store.add_note("shared", None, share_with_agents=True)
    store.add_note("private", None)

    bundle = json.loads(json.dumps(export_bundle(store)))
    assert [n["text"] for n in bundle["notes"]["notes"]] == ["shared"]
    full = export_bundle(store, include_private_notes=True)
    assert len(full["notes"]["notes"]) == 2

    monkeypatch.setenv("HONEYGUIDE_HOME", str(tmp_path / "elsewhere"))
    fresh = Store(store.repo_id)
    fresh.init(bundle["repo"])
    assert import_bundle(fresh, bundle) == {"added": 4, "kept_local": 0}
    for layer in ("map", "answers"):
        assert fresh.load(layer) == store.load(layer)
    assert fresh.load("notes")["notes"] == [shared]
    assert import_bundle(fresh, bundle) == {"added": 0, "kept_local": 4}

    other = Store("another_repo")
    with pytest.raises(StoreError, match="force"):
        import_bundle(other, bundle)
    assert import_bundle(other, bundle, force=True)["added"] == 4

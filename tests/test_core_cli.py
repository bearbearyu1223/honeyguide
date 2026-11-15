"""The CLI end to end on a throwaway repo: status, refresh-plan, export, import."""

from __future__ import annotations

import json

from test_core_fixtures import GitRepo

from honeyguide.anchors import resolve
from honeyguide.cli import main
from honeyguide.gitio import Repo
from honeyguide.repoid import identify
from honeyguide.store import Store, make_claim


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYGUIDE_HOME", str(tmp_path / "hg"))
    g = GitRepo(tmp_path / "r")
    g.write("m.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    a = g.commit("A")
    repo = Repo.open(g.root)
    ident = identify(repo).to_dict()
    store = Store(ident["id"])
    store.init(ident)
    claims = [make_claim(f"{name} returns", "read_in_source",
                         [resolve(repo.lines_at(a, "m.py"), "m.py", f"def {name}():", a,
                                  extent="block").anchor.to_dict()]) for name in ("f", "g")]
    store.save_map(claims, a)
    store.add_note("private", None)
    g.write("m.py", "def f():\n    return 1\n\n\ndef g():\n    return 3\n\n\ndef h():\n    return 4\n")
    g.commit("B")
    return g, store


def test_status_and_refresh_plan(tmp_path, monkeypatch, capsys):
    g, store = setup(tmp_path, monkeypatch)
    assert main(["status", "--repo", str(g.root)]) == 0
    out = capsys.readouterr().out
    assert store.repo_id in out and "behind HEAD" in out and "map claims   2" in out
    assert "0 shared with agents, 1 private" in out
    assert main(["refresh-plan", "--repo", str(g.root)]) == 0
    out = capsys.readouterr().out
    assert "unchanged 1  moved 0  stale 1  retired 0  unanchored 0" in out
    assert "m.py:9-10  h (function, new)" in out
    assert main(["refresh-plan", "--repo", str(g.root), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["counts"]["stale"] == 1 and plan["uncovered"][0]["qualname"] == "h"
    # The dry run changed nothing.
    assert all(c["freshness"] == "current" for c in store.load("map")["claims"])


def test_export_import(tmp_path, monkeypatch, capsys):
    g, store = setup(tmp_path, monkeypatch)
    out_file = tmp_path / "memory.json"
    assert main(["export", "--repo", str(g.root), "-o", str(out_file)]) == 0
    bundle = json.loads(out_file.read_text())
    assert bundle["notes"]["notes"] == []  # private notes stay home by default
    monkeypatch.setenv("HONEYGUIDE_HOME", str(tmp_path / "other-home"))
    capsys.readouterr()
    assert main(["import", str(out_file), "--repo", str(g.root)]) == 0
    assert "2 added" in capsys.readouterr().out
    assert len(Store(store.repo_id).load("map")["claims"]) == 2


def test_errors_go_to_stderr(tmp_path, capsys):
    assert main(["status", "--repo", str(tmp_path)]) == 1
    assert "honeyguide:" in capsys.readouterr().err

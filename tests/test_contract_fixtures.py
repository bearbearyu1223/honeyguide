"""A throwaway repo and memory home for the contract tests, and a JSON-calling wrapper around the CLI."""

from __future__ import annotations

import io
import json
import sys

from test_core_fixtures import GitRepo

from honeyguide.cli import main
from honeyguide.gitio import Repo
from honeyguide.repoid import identify
from honeyguide.store import Store

ENGINE = '''"""Toy engine."""


class Engine:
    def __init__(self, model):
        self.model = model

    def generate(self, tokens):
        for _ in range(3):
            yield self.model(tokens)


def sample(engine, prompt):
    return list(engine.generate(prompt))
'''

CLI = '''from engine import Engine, sample


def main():
    return sample(Engine(len), [1, 2])
'''


class World:
    """A repo with code, a credential file and a file holding a key, plus a fresh HONEYGUIDE_HOME."""

    def __init__(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HONEYGUIDE_HOME", str(tmp_path / "hg"))
        self.git = GitRepo(tmp_path / "repo")
        self.git.write("engine.py", ENGINE)
        self.git.write("cli.py", CLI)
        self.git.write(".env", "API_TOKEN=hunter2\n")
        self.git.write("config.py", "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\nDEBUG = True\n")
        self.commit = self.git.commit("A")
        self.root = self.git.root
        self.repo = Repo.open(self.root)
        identity = identify(self.repo).to_dict()
        self.store = Store(identity["id"])
        self.store.init(identity)

    def call(self, *argv: str, data=None, monkeypatch=None) -> tuple[int, dict]:
        """Run ``honeyguide <argv>`` with ``data`` on stdin; returns (exit code, parsed stdout)."""
        out, old_in, old_out = io.StringIO(), sys.stdin, sys.stdout
        sys.stdin = io.StringIO("" if data is None else json.dumps(data))
        sys.stdout = out
        try:
            code = main([*argv, "--repo", str(self.root)])
        finally:
            sys.stdin, sys.stdout = old_in, old_out
        return code, json.loads(out.getvalue())


def a_map() -> dict:
    """A valid ``claims save`` input: two anchored claims, one general-knowledge claim, one flow."""
    return {
        "target": "map", "mode": "replace",
        "claims": [
            {"key": "gen", "text": "Engine.generate yields three outputs", "evidence": "read_in_source",
             "anchors": [{"path": "engine.py", "anchor": "def generate(self, tokens):", "extent": "block"}]},
            {"key": "call", "text": "sample calls Engine.generate", "evidence": "read_in_source",
             "anchors": [{"path": "engine.py", "anchor": "return list(engine.generate(prompt))"}]},
            {"key": "gk", "text": "Generators are lazy", "evidence": "general_knowledge", "anchors": []},
        ],
        "document": {
            "title": "toy",
            "sections": [
                {"id": "overview", "kind": "overview", "title": "Overview",
                 "blocks": [{"id": "b1", "type": "text",
                             "spans": [{"text": "The engine "}, {"text": "yields three outputs", "claim": "gen"},
                                       {"text": "; "}, {"text": "generators are lazy", "claim": "gk"},
                                       {"text": "."}]}]},
                {"id": "flows", "kind": "flows", "title": "Flows",
                 "blocks": [{"id": "f1", "type": "flow", "flow": "p1",
                             "spans": [{"text": "sample() runs the engine"}]}]},
            ],
            "flows": [{"id": "p1", "title": "What happens when you call sample()",
                       "lanes": [{"id": "engine", "label": "engine.py", "path": "engine.py"}],
                       "loops": [{"id": "tok", "label": "x 3"}],
                       "hops": [{"from": "engine", "to": "engine", "call": "Engine.generate(prompt)",
                                 "returns": "generator", "loop": "tok", "trace": "unseen", "claim": "call"}]}],
        },
    }


def test_world_builds(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert w.store.exists() and len(w.commit) == 40
    code, out = w.call("inbox")
    assert code == 0 and out == {"ok": True, "open": [], "investigating": []}

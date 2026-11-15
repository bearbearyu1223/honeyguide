"""The refresh classifier on real throwaway git repos: every state, renames, deletion, uncovered code."""

from __future__ import annotations

from test_core_fixtures import GitRepo

from honeyguide.anchors import resolve
from honeyguide.gitio import Repo
from honeyguide.refresh import apply_result, combine, plan_refresh
from honeyguide.store import make_claim

AGENT = """\
def load(path):
    return open(path).read()


def parse(text):
    return text.split()


def helper():
    return 1


class Agent:
    def run(self):
        return 2
"""

UTIL = """\
def shout(text):
    return text.upper()
"""


def claim_at(repo: Repo, commit: str, path: str, text: str, extent: str = "block") -> dict:
    r = resolve(repo.lines_at(commit, path), path, text, commit, extent=extent)
    assert r.status == "found", r.message
    return make_claim(f"claim about {text}", "read_in_source", [r.anchor.to_dict()])


def build(tmp_path):
    g = GitRepo(tmp_path / "r")
    g.write("pkg/agent.py", AGENT)
    g.write("pkg/util.py", UTIL)
    g.write("pkg/other.py", "def keep():\n    return 0\n")
    g.write("notes.txt", "alpha\nbeta\n")
    a = g.commit("A")
    repo = Repo.open(g.root)
    claims = {
        "load": claim_at(repo, a, "pkg/agent.py", "def load(path):"),
        "parse": claim_at(repo, a, "pkg/agent.py", "def parse(text):"),
        "helper": claim_at(repo, a, "pkg/agent.py", "def helper():"),
        "shout": claim_at(repo, a, "pkg/util.py", "def shout(text):"),
        "keep": claim_at(repo, a, "pkg/other.py", "def keep():"),
        "beta": claim_at(repo, a, "notes.txt", "beta", extent="lines"),
    }
    # B: insert lines above load (moves everything), edit parse's body, delete helper, add a new function,
    # rename util.py, delete notes.txt; other.py untouched.
    new_agent = ("import os\n\n\n" + AGENT.replace("return text.split()", "return text.split(',')")
                 .replace("def helper():\n    return 1\n\n\n", "")
                 + "\n\ndef fresh():\n    return 3\n")
    g.write("pkg/agent.py", new_agent)
    g.git("mv", "pkg/util.py", "pkg/text_util.py")
    (g.root / "notes.txt").unlink()
    b = g.commit("B")
    return g, repo, a, b, claims


def test_every_state(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    plan = plan_refresh(repo, [(None, c) for c in claims.values()])
    assert plan.target == b and plan.base == a and not plan.warnings
    state = {next(k for k, v in claims.items() if v["id"] == c.claim_id): c for c in plan.claims}
    assert state["keep"].state == "unchanged"
    assert state["load"].state == "moved"
    assert (state["load"].anchors[0].reloc.start, state["load"].anchors[0].reloc.end) == (4, 5)
    assert state["parse"].state == "stale"
    assert state["helper"].state == "retired"
    assert state["shout"].state == "moved"
    assert state["shout"].anchors[0].path == "pkg/text_util.py"
    assert state["beta"].state == "retired" and "file deleted" in state["beta"].reason
    assert plan.counts() == {"unchanged": 1, "moved": 2, "stale": 1, "retired": 2, "unanchored": 0}
    # Uncovered: the new function only. parse changed but its stale claim still covers it; Agent didn't change.
    assert [(u.qualname, u.change) for u in plan.uncovered] == [("fresh", "new")]
    assert plan.unoutlined == []


def test_uncovered_includes_changed_unit_nobody_cites(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    plan = plan_refresh(repo, [(None, claims["keep"])], base=a)
    names = {(u.path, u.qualname, u.change) for u in plan.uncovered}
    assert ("pkg/agent.py", "parse", "changed") in names
    assert ("pkg/agent.py", "fresh", "new") in names
    assert ("pkg/agent.py", "load", "changed") not in names  # moved, not changed
    assert not any(u.qualname.startswith("Agent") for u in plan.uncovered)


def test_apply_updates_moved_and_marks_stale(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    plan = plan_refresh(repo, [(None, c) for c in claims.values()])
    results = {c.claim_id: c for c in plan.claims}
    moved = apply_result(claims["load"], results[claims["load"]["id"]], b)
    assert moved["anchors"][0]["start"] == 4 and moved["anchors"][0]["commit"] == b
    assert moved["anchors"][0]["hash"] == claims["load"]["anchors"][0]["hash"]
    assert moved["freshness"] == "current"
    claims["parse"]["check"] = "supported"
    stale = apply_result(claims["parse"], results[claims["parse"]["id"]], b)
    assert stale["freshness"] == "stale" and stale["check"] == "unchecked"
    assert stale["anchors"] == claims["parse"]["anchors"]  # what was checked stays on record
    assert stale["candidates"][0]["symbol"] == "parse"
    renamed = apply_result(claims["shout"], results[claims["shout"]["id"]], b)
    assert renamed["anchors"][0]["path"] == "pkg/text_util.py"
    # Refreshing again from the applied state is a no-op for the moved claim.
    again = plan_refresh(repo, [(None, moved)])
    assert again.claims[0].state == "unchanged"


def test_dirty_tree_warns_and_reads_head(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    g.write("pkg/other.py", "def keep():\n    return 'edited, not committed'\n")
    plan = plan_refresh(repo, [(None, claims["keep"])])
    assert plan.warnings and "HEAD" in plan.warnings[0]
    assert plan.claims[0].state == "unchanged"


def test_anchors_refresh_from_their_own_commits(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    late = claim_at(repo, b, "pkg/agent.py", "def parse(text):")  # saved after B: already current
    g.write("pkg/other.py", "def keep():\n    return 0\n\n\ndef more():\n    return 5\n")
    g.commit("C")
    plan = plan_refresh(repo, [(None, claims["parse"]), ("r_1", late)])
    by_id = {c.claim_id: c for c in plan.claims}
    assert by_id[claims["parse"]["id"]].state == "stale"
    assert by_id[late["id"]].state == "unchanged"
    assert by_id[late["id"]].response_id == "r_1"


def test_combine():
    assert combine([]) == "unanchored"
    assert combine(["unchanged", "unchanged"]) == "unchanged"
    assert combine(["unchanged", "moved"]) == "moved"
    assert combine(["retired", "retired"]) == "retired"
    assert combine(["moved", "retired"]) == "stale"
    assert combine(["moved", "stale"]) == "stale"


def test_unanchored_claims_and_retired_ones_are_skipped(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    general = make_claim("Python lists are dynamic arrays", "general_knowledge", [])
    gone = dict(claims["helper"], freshness="retired")
    plan = plan_refresh(repo, [(None, general), (None, gone)], base=a)
    assert [c.state for c in plan.claims] == ["unanchored"]


def test_commit_missing_from_clone_is_stale_not_a_crash(tmp_path):
    g, repo, a, b, claims = build(tmp_path)
    foreign = dict(claims["keep"], anchors=[dict(claims["keep"]["anchors"][0], commit="e" * 40)])
    plan = plan_refresh(repo, [(None, foreign), (None, claims["load"])], base="e" * 40)
    assert plan.claims[0].state == "stale" and "not in this clone" in plan.claims[0].reason
    assert plan.claims[1].state == "moved"
    assert any("not in this clone" in w for w in plan.warnings)

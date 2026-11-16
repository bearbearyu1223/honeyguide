"""Review round 1 (T8): apply_plan applies a plan computed before it took the lock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from honeyguide.anchors import resolve  # noqa: E402
from honeyguide.gitio import Repo  # noqa: E402
from honeyguide.refresh import apply_plan, plan_refresh  # noqa: E402
from honeyguide.store import Store, make_claim  # noqa: E402
from test_core_fixtures import GitRepo  # noqa: E402

A = "def f():\n    return 1\n"
B = "def f():\n    return 2\n"


def test_claim_reanchored_after_planning_is_not_marked_stale(tmp_path):
    """The plan says f's claim is stale. Before apply_plan runs, the Checker re-anchors it at B (current).
    apply_plan then marks it stale again from the old plan, and resets its check: a lost update."""
    g = GitRepo(tmp_path / "r")
    g.write("m.py", A)
    a = g.commit()
    repo = Repo.open(g.root)
    claim = make_claim("f returns a number", "read_in_source",
                       [resolve(repo.lines_at(a, "m.py"), "m.py", "def f():", a, extent="block").anchor.to_dict()])
    store = Store("t", tmp_path / "hg")
    store.save_map([claim], a)
    g.write("m.py", B)
    b = g.commit()
    plan = plan_refresh(repo, [(None, claim)])
    assert plan.claims[0].state == "stale"
    fresh = resolve(repo.lines_at(b, "m.py"), "m.py", "def f():", b, extent="block").anchor.to_dict()

    def recheck(data):
        data["claims"][0].update(anchors=[fresh], check="supported", freshness="current")
    store.update("map", recheck)
    apply_plan(store, plan)
    saved = store.load("map")["claims"][0]
    assert (saved["freshness"], saved["check"], saved["anchors"]) == ("current", "supported", [fresh])

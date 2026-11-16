"""eval/run map check and fix rounds, after the review of eb6fdf2 (fake `claude`, no model call):

- the check adds the waived re-check's errors to the first pass's: a label error on a claim whose quote did not
  resolve still blocks; only not_found / ambiguous quotes are waived (malformed, missing-file and secret anchors
  block);
- what the build and finished fix rounds billed survives an interruption mid-fix (cost_so_far.json, counted once
  by Archive.spent, in runs/ or attempts/) and a runner-side failure in a fix round (kept in the error meta);
- the scorer says what a map run's cost covers ("build + N fix rounds", and the build alone);
- the real pilot map (read-only, skipped when the archive or the nanochat clone is missing) is refused for its 5
  document errors only.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_fixture as FX  # noqa: E402
import evalrun  # noqa: E402
import evalscore as ES  # noqa: E402
import maprender as M  # noqa: E402

PILOT = Path.home() / "Documents/GitHub/honeyguide-targets/_eval/pilot-nanochat"
CLONE = Path.home() / "Documents/GitHub/honeyguide-targets/nanochat"
FAKE_COST = (10 * 4 + 1000 * 0.2 + 500 * 8 + 100 * 20) / 1e6      # what fake_claude reports per call


@pytest.fixture
def fx(tmp_path, monkeypatch):
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    return FX.make(tmp_path)


def _args(fx, *extra):
    return ["--repo", "fx", "--size", "tiny", "--config", str(fx["config"]), "--claude-bin", str(fx["fake"]),
            *extra]


def _set_control(fx, **kw):
    ctl = fx["fake"].parent / "claude.json"
    ctl.write_text(json.dumps(dict(json.loads(ctl.read_text()), **kw)))


def _billed(root: Path) -> float:
    """Every claude result the archive holds (build, fix rounds, answers; current and earlier attempts)."""
    return sum(float(json.loads(p.read_text()).get("total_cost_usd") or 0.0) for p in root.rglob("result.json"))


# ------------------------------------------------------------------------------------------------------------
# the check, on the fixture repo (c3's quote is on no line)

def test_anchor_error_waives_only_unresolved_quotes():
    """The wording of honeyguide.claims.build_claims: only not_found and ambiguous are waived."""
    waived = ["claims[3] (c3).anchors[0]: not_found: scripts/main.py: 'x' is on no line",
              "claims[3].anchors[1]: ambiguous: a.py: 'x' matches 2 places (lines 1, 4); quote more lines to make "
              "it unique (candidates: lines 1, 4)",
              "claims[0] (k).anchors[0]: not_found: a.py: end 'y' not at or after line 3"]
    kept = ["claims[0] (k).anchors[0]: bad_input: an anchor needs path and anchor (the quoted text)",
            "claims[0] (k).anchors[0]: bad_input: '../x': not a normalized repository-relative path",
            "claims[0] (k).anchors[0]: bad_input: extent must be lines or block",
            "claims[0] (k).anchors[0]: secret: .env: looks like a secrets file",
            "claims[0] (k).anchors[0]: no_file: gone.py: not in commit 0123456789ab (or binary)",
            "claims[0] (k): general_knowledge claims cite no code; drop the anchors or change the label"]
    assert all(M.ANCHOR_ERROR.match(e) for e in waived)
    assert not any(M.ANCHOR_ERROR.match(e) for e in kept)


def test_fixture_label_error_on_unresolved_claim_blocks(fx):
    m = copy.deepcopy(FX.MAP_OUTPUT)
    m["claims"][2]["evidence"] = "general_knowledge"            # c3: its only quote does not resolve
    v = M.validate_map(fx["clone"], fx["commit"], m)
    label = "claims[2] (c3): general_knowledge claims cite no code; drop the anchors or change the label"
    assert label in v["draft_errors"] and v["blocking_errors"] == [label] and not v["usable"]
    m["claims"][2]["evidence"] = "read_in_sourc"
    v = M.validate_map(fx["clone"], fx["commit"], m)
    assert [e for e in v["blocking_errors"] if "evidence must be one of" in e]
    assert M.validate_map(fx["clone"], fx["commit"], FX.MAP_OUTPUT)["usable"]     # c3 alone never blocks


def test_fixture_malformed_anchor_blocks(fx):
    m = copy.deepcopy(FX.MAP_OUTPUT)
    m["claims"][0]["anchors"][0] = {"path": "../etc/passwd", "anchor": "root"}
    v = M.validate_map(fx["clone"], fx["commit"], m)
    assert [e for e in v["blocking_errors"] if ": bad_input: " in e] and not v["usable"]
    assert not any("c3" in e for e in v["blocking_errors"])        # the unresolved quote is still waived


# ------------------------------------------------------------------------------------------------------------
# (1) ANCHOR_ERROR / waive_unresolved against the real refused map (read-only)

@pytest.fixture(scope="module")
def real():
    if not (PILOT / "maps/seed1/map.json").exists() or not CLONE.exists():
        pytest.skip("first pilot's map or the nanochat clone not here")
    commit = json.loads((PILOT / "plan.json").read_text())["commit"]
    m = json.loads((PILOT / "maps/seed1/map.json").read_text())
    base = M.validate_map(CLONE, commit, m)
    return {"commit": commit, "map": m, "base": base}


def _break_all_anchors(m: dict, i: int) -> dict:
    out = copy.deepcopy(m)
    for a in out["claims"][i]["anchors"]:
        a["anchor"] = "zzz this quote is on no line zzz"
    return out


def test_real_map_refused_for_its_document_errors_only(real):
    b = real["base"]
    assert not b["usable"] and b["anchors_resolved"] == b["anchors_total"] == 452
    assert len(b["blocking_errors"]) == 5
    assert sum("is not in document.flows" in e for e in b["blocking_errors"]) == 4


def test_real_map_unresolved_anchor_neither_blocks_nor_hides(real):
    v = M.validate_map(CLONE, real["commit"], _break_all_anchors(real["map"], 0))
    assert v["anchors_resolved"] == 451
    assert v["blocking_errors"] == real["base"]["blocking_errors"]


def test_label_error_on_claim_with_unresolved_anchor_still_blocks(real):
    m = _break_all_anchors(real["map"], 0)
    m["claims"][0]["evidence"] = "general_knowledge"
    v = M.validate_map(CLONE, real["commit"], m)
    label = [e for e in v["draft_errors"] if "general_knowledge claims cite no code" in e]
    assert label, "precondition: Honeyguide reports the label error"
    assert label[0] in v["blocking_errors"]


def test_invalid_evidence_label_with_unresolved_anchor_still_blocks(real):
    m = _break_all_anchors(real["map"], 0)
    m["claims"][0]["evidence"] = "read_in_sourc"
    v = M.validate_map(CLONE, real["commit"], m)
    bad = [e for e in v["draft_errors"] if "evidence must be one of" in e]
    assert bad and bad[0] in v["blocking_errors"]


def test_malformed_anchor_is_not_an_unresolved_anchor(real):
    m = copy.deepcopy(real["map"])
    m["claims"][0]["anchors"][0] = {"path": "../etc/passwd", "anchor": "root"}
    v = M.validate_map(CLONE, real["commit"], m)
    assert any(": bad_input: " in e for e in v["draft_errors"])
    assert any(": bad_input: " in e for e in v["blocking_errors"])


# ------------------------------------------------------------------------------------------------------------
# (2)/(3) cost accounting across an interruption or a runner-side failure inside a fix round

def test_spent_keeps_build_and_fix_cost_after_interruption_mid_fix(fx, monkeypatch):
    """The build and fix round 1 finished and were billed; the process dies in fix round 2. The run stays
    unfinished (no meta.json), is restarted on resume, and its billed cost is counted once from attempts/."""
    _set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.map_without_flows()])
    orig = evalrun.Runner._fix_round
    state = {"armed": True}

    def dying(self, item, fd, prev, errors, n, rounds, budget):
        if n == 2 and state["armed"]:
            state["armed"] = False
            (fd / "started").write_text("x\n")
            raise KeyboardInterrupt
        return orig(self, item, fd, prev, errors, n, rounds, budget)

    monkeypatch.setattr(evalrun.Runner, "_fix_round", dying)
    with pytest.raises(KeyboardInterrupt):
        evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))
    root = fx["archive"] / "r"
    run = root / "runs/map-s1"
    assert not (run / "meta.json").exists()
    assert _billed(root) == pytest.approx(2 * FAKE_COST)            # build + fix round 1, both billed
    so_far = json.loads((run / evalrun.COST_SO_FAR).read_text())
    assert so_far["usage"]["cost_usd"] == pytest.approx(2 * FAKE_COST) and len(so_far["fix_rounds"]) == 1
    assert evalrun.Archive(root).spent() == pytest.approx(2 * FAKE_COST)
    assert evalrun.Archive(root).meta("map-s1") is None              # a partial map run is not finished
    evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))      # resume: the map run is restarted
    assert (root / "attempts/map-s1/1/fix/1/result.json").exists()
    assert any(e["event"] == "restart_after_interruption" for e in
               map(json.loads, (root / "log.jsonl").read_text().splitlines()))
    assert evalrun.Archive(root).spent() == pytest.approx(_billed(root))
    assert evalrun.Archive(root).spent() == pytest.approx(5 * FAKE_COST)   # 2 kept + build and 2 rounds again


def test_runner_error_in_fix_round_keeps_the_build_cost(fx, monkeypatch):
    _set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.map_without_flows()])
    orig = evalrun.Runner._fix_round

    def boom(self, item, fd, prev, errors, n, rounds, budget):
        if n == 2:
            raise RuntimeError("disk full")
        return orig(self, item, fd, prev, errors, n, rounds, budget)

    monkeypatch.setattr(evalrun.Runner, "_fix_round", boom)
    evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))
    meta = json.loads((fx["archive"] / "r/runs/map-s1/meta.json").read_text())
    assert meta["status"] == "error" and "disk full" in meta["reason"]
    assert meta["usage"]["cost_usd"] == pytest.approx(2 * FAKE_COST)            # build + round 1
    assert meta["build_usage"]["cost_usd"] == pytest.approx(FAKE_COST) and len(meta["fix_rounds"]) == 1
    assert evalrun.Archive(fx["archive"] / "r").spent() == pytest.approx(2 * FAKE_COST)


def test_runner_error_in_first_fix_round_keeps_the_build_cost(fx, monkeypatch):
    _set_control(fx, map_output=FX.map_without_flows())

    def boom(self, *a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(evalrun.Runner, "_fix_round", boom)
    evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))
    meta = json.loads((fx["archive"] / "r/runs/map-s1/meta.json").read_text())
    assert meta["status"] == "error"
    assert meta["usage"]["cost_usd"] == pytest.approx(FAKE_COST)


# ------------------------------------------------------------------------------------------------------------
# (5) the final round's map is what map runs read; the scorer labels what the map cost covers

def test_final_round_map_rendered_and_stale_text_removed(fx):
    _set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.MAP_OUTPUT])
    evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))
    md = fx["archive"] / "r/maps/seed1"
    assert json.loads((md / "map.json").read_text()) == FX.MAP_OUTPUT
    assert "## Flow run:" in (md / "map.md").read_text()
    _set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.map_without_flows()])
    (fx["archive"] / "r/runs/map-s1/meta.json").unlink()            # as if interrupted after _save_map
    evalrun.main(_args(fx, "--run-id", "r", "--max-runs", "1"))
    assert not (md / "map.md").exists()


def test_build_label():
    assert ES.build_label({}) == ES.build_label({"fix_rounds": []}) == "build"
    assert ES.build_label({"fix_rounds": [{}]}) == "build + 1 fix round"
    assert ES.build_label({"fix_rounds": [{}, {}]}) == "build + 2 fix rounds"


def test_capture_says_build_plus_fix_rounds(fx, capsys):
    _set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.MAP_OUTPUT])
    a = _args(fx, "--run-id", "r")
    evalrun.main(a)
    assert evalrun.main(a) == 0                      # resumed past the fixture's usage-limit stop
    capsys.readouterr()
    assert ES.main(["--run-id", "r", "--config", str(fx["config"])]) == 0
    out = capsys.readouterr().out
    meta = json.loads((fx["archive"] / "r/runs/map-s1/meta.json").read_text())
    total, alone = meta["wall_s"] / 60, meta["build_wall_s"] / 60
    assert f"              build + 1 fix round {total:.1f} min, {ES.money(2 * FAKE_COST)} list; tokens in " in out
    assert f"              build alone {alone:.1f} min, {ES.money(FAKE_COST)} list\n" in out
    assert all(len(ln) <= ES.WIDTH for ln in out.splitlines())

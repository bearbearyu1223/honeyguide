"""Review round 4 fixes: head_at's same-second tie, the frozen run-commit record, E3's ratio without the re-check
(capture and figure), refresh-flow's layout (no band behind a bar or label, the edge cases check() used to let
through, the re-map's retired still-held claims as their own band), repair-loop's title and round notes, and the
adhoc-vs-map guard on a not_supported change."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_figures_v2 import load, receipt  # noqa: E402
from test_refresh_capture import cap  # noqa: E402

rf, rr, rl, av = (load(n) for n in ("refresh_flow", "refresh_vs_rebuild", "repair_loop", "adhoc_vs_map"))


# -- head_at: a same-second tie goes to the later reflog entry ---------------------------------------------------------

# The honeyguide-run reflog's real tie: two checkouts in one second, the newer (5492b2d) listed first.
REAL_TIE = ("aa42ce5db4d4517617c6931b40024db9745ab1c2\tHEAD@{2026-11-15T20:07:52-08:00}\n"
            "5492b2de37a13560f31bc9c25dde2d9c4b934645\tHEAD@{2026-11-15T17:27:21-08:00}\n"
            "1b6eb04cc3a3cd91f2dbd574d698fb3dd712778f\tHEAD@{2026-11-15T17:27:21-08:00}\n"
            "0e857b2b1862f322d2a59a0ba334801c446566c2\tHEAD@{2026-11-15T16:09:42-08:00}\n")


def test_head_at_same_second_takes_the_later_move_not_the_larger_sha():
    when = "2026-11-16T01:30:00Z"                       # 17:30 -08:00, after the pair, before aa42ce5
    assert cap.head_at(cap.parse_reflog(REAL_TIE), when)[0].startswith("5492b2d")
    # the same pattern with the shas swapped: the newer move now has the smaller sha, and must still win
    a, b = "5492b2de37a13560f31bc9c25dde2d9c4b934645", "1b6eb04cc3a3cd91f2dbd574d698fb3dd712778f"
    swapped = REAL_TIE.replace(a, "X").replace(b, a).replace("X", b)
    assert cap.head_at(cap.parse_reflog(swapped), when)[0].startswith("1b6eb04")


# -- the frozen run-commit record --------------------------------------------------------------------------------------


def test_freeze_and_prefer_the_record():
    reflog = cap.parse_reflog(REAL_TIE)
    runs = [("E9 build", "2026-11-16T01:30:00Z"), ("E9 refresh", "2026-11-15T00:00:00Z")]   # second: before all
    rec = cap.freeze_run_commits(runs, reflog, datetime(2026, 11, 17, 5, 7, 22, tzinfo=timezone.utc))
    assert rec["read_at"] == "2026-11-17T05:07:22Z"
    assert rec["runs"][0] == {"run": "E9 build", "start": "2026-11-16T01:30:00Z",
                              "commit": "5492b2de37a13560f31bc9c25dde2d9c4b934645", "since": "2026-11-16T01:27:21Z"}
    assert rec["runs"][1]["commit"] is None
    # with the reflog gone, the record still answers; a run it does not hold (or holds no commit for) falls back
    heads = cap.run_heads(runs, [], rec)
    assert heads["E9 build"][1] == "record" and heads["E9 build"][0][0].startswith("5492b2d")
    assert heads["E9 refresh"] == (None, "reflog")
    assert cap.run_heads([("E9 build", "2026-11-16T01:31:00Z")], [], rec)["E9 build"] == (None, "reflog")  # moved


def test_the_committed_record_matches_todays_runs():
    """eval/refresh/run_commits.json holds a commit for every run in the receipt, and the receipt says it read
    the table from it."""
    rec = json.loads((Path(cap.__file__).parent / "run_commits.json").read_text())
    assert rec["read_at"].endswith("Z") and all(r["commit"] and len(r["commit"]) == 40 for r in rec["runs"])
    text = receipt("refresh.txt")
    assert "Read from eval/refresh/run_commits.json, frozen from that reflog at" in " ".join(text.split())
    for r in rec["runs"]:
        start = r["start"].replace("T", " ").rstrip("Z")
        assert re.search(rf"^    {re.escape(r['run'])}\s+{start} {r['commit'][:7]}  ", text, re.M), r["run"]


# -- E3's ratio without the re-check -----------------------------------------------------------------------------------


def test_figure_title_gives_both_fractions():
    text = receipt("refresh.txt")
    day, big = rr.parse(text)
    assert (day.extra, day.less_usd, day.less_min) == ("re-check", 15.19, 41.5)
    assert (day.less_ratio_usd, day.less_ratio_min) == (0.26, 0.23)
    assert (day.fraction, day.fraction_less, day.fractions) == (5, 4, "1/5 to 1/4")
    assert big.extra == "" and big.fractions == "1/2"
    assert rr.takeaway((day, big)).startswith("Keeping the map current costs about 1/5 to 1/4 of a rebuild for")
    foot = " ".join(rr.footnote((day, big)).split())
    assert "Its re-check (above the dashed line) has no counterpart in nanochat's one-run rebuild" in foot
    assert "about 1/5 with it, 1/4 without it" in foot
    # a printed ratio the rows don't give is refused; so is a 'less' row that is not the total less the pass
    with pytest.raises(ValueError, match="rebuild less re-check in \\$"):
        rr.parse(text.replace("rebuild less re-check:  $ 0.26", "rebuild less re-check:  $ 0.36"))
    with pytest.raises(ValueError, match="not the rebuild total less that pass"):
        rr.parse(text.replace("rebuild less re-check    $15.19", "rebuild less re-check    $16.19"))


# -- refresh-flow ------------------------------------------------------------------------------------------------------


def _flow(**kw):
    base = dict(repo="r", target_date=datetime(2026, 7, 3).date(),
                before={"unchanged": 10, "moved": 10, "stale": 10, "retired": 2, "unanchored": 2},
                after_total=34, after={"current": 0, "stale": 0, "retired": 0}, by_apply=2, by_remap=0,
                remap_by_class={"unchanged": 0, "moved": 0, "stale": 0, "retired": 0, "unanchored": 0, "new": 0},
                new=0, stale_rechecked=10, held=5, held_retired=0, not_held=5, not_held_retired=5, left_stale=0)
    base.update(kw)
    return rf.RefreshFlow(**base)


def conserved(f, lay):
    """Every target span is filled exactly by the bands into it, and no two bands share a target range."""
    into = {}
    for src, dst, _ in lay["bands"]:
        assert src[1] - src[0] == pytest.approx(dst[1] - dst[0])
        into.setdefault(dst, 0)
        into[dst] += 1
    assert all(n == 1 for n in into.values()), into
    for side in ("ret", "cur"):
        for name, (a, b) in lay[side].items():
            if name == "new":
                continue
            filled = sum(d[1] - d[0] for _, d, _ in lay["bands"] if a <= d[0] and d[1] <= b)
            assert filled == pytest.approx(b - a), (side, name)
    assert sum(b - a for a, b in lay["ret"].values()) == f.after["retired"]
    assert sum(b - a for a, b in lay["cur"].values()) == f.after["current"]


def test_unchanged_claims_the_remap_retired_are_drawn_as_gap():
    """Edge case 1 (round 4): check() let re-map retirements of 'unchanged' claims through but layout() had no slot
    for them. They are now drawn, as part of the gap (their hashes matched too)."""
    remap = {"unchanged": 1, "moved": 0, "stale": 5, "retired": 0, "unanchored": 0, "new": 0}
    f = _flow(by_remap=6, remap_by_class=remap, after={"current": 26, "stale": 0, "retired": 8})
    rf.check(f)
    lay = rf.layout(f)
    conserved(f, lay)
    assert lay["ret"]["unchanged"][1] - lay["ret"]["unchanged"][0] == 1
    assert any(kind == "gap" and s[1] - s[0] == 1 for s, _, kind in lay["bands"])
    assert rf.gap_note(f).startswith("The gap (hatched): 1 unchanged claims.")


def test_stale_not_held_but_kept_has_room_on_the_right():
    """Edge case 2 (round 4): a stale claim the Checker found not supported that the re-map kept went into a
    current slot sized for held claims only. The slot is now every stale claim kept."""
    f = _flow(not_held_retired=4, after={"current": 28, "stale": 0, "retired": 6}, by_remap=4,
              remap_by_class={"unchanged": 0, "moved": 0, "stale": 4, "retired": 0, "unanchored": 0, "new": 0})
    rf.check(f)
    lay = rf.layout(f)
    into = sum(s[1] - s[0] for s, _, kind in lay["bands"] if kind == "kept-mid")
    assert into == lay["cur"]["held"][1] - lay["cur"]["held"][0] == f.kept("stale") == 6
    conserved(f, lay)


def test_check_still_refuses_what_the_figure_cannot_draw():
    with pytest.raises(ValueError, match="new or already-retired"):
        rf.check(_flow(by_remap=1, after={"current": 29, "stale": 0, "retired": 3},
                       remap_by_class={"unchanged": 0, "moved": 0, "stale": 0, "retired": 0, "unanchored": 0,
                                       "new": 1}))
    with pytest.raises(ValueError, match="more re-checked claims than there were"):
        rf.check(_flow(held_retired=6, not_held_retired=0, by_remap=6,
                       after={"current": 26, "stale": 0, "retired": 8},
                       remap_by_class={"unchanged": 0, "moved": 0, "stale": 6, "retired": 0, "unanchored": 0,
                                       "new": 0}))


def test_real_receipt_layout_has_no_crossings_and_its_own_held_band():
    f = rf.parse(receipt("refresh.txt"))
    lay = rf.layout(f)
    conserved(f, lay)
    assert rf.crossings(lay) == []
    held = [(s, d) for s, d, kind in lay["bands"] if kind == "held-mid"]
    assert len(held) == 1 and held[0][1] == lay["ret"]["held"] and lay["ret"]["held"][1] - lay["ret"]["held"][0] == 2
    # the retired segments are drawn apart, so each one (and its label) can be found
    spans = sorted(s for s in lay["ret"].values() if s[1] > s[0])
    assert all(b[0] - a[1] > 0 for a, b in zip(spans, spans[1:], strict=False))
    note = rf.gap_note(f)
    assert note.startswith("The gap (hatched): 3 moved and 6 unanchored claims.\n")
    assert all(line.rstrip()[-1] in ".,;)" for line in note.splitlines())


def test_crossings_finds_a_band_behind_the_node():
    """Put the stale block below the moved block (the round-3 order): the moved gap band then crosses the node."""
    f = rf.parse(receipt("refresh.txt"))
    lay = rf.layout(f)
    m0, m1 = lay["mid"]["not held"][0], lay["mid"]["held"][1]
    shifted = dict(lay, mid={k: (a + 200, b + 200) for k, (a, b) in lay["mid"].items()})
    assert (m0, m1) != (shifted["mid"]["not held"][0], shifted["mid"]["held"][1])
    assert any("re-check node" in c for c in rf.crossings(shifted))


# -- repair-loop -------------------------------------------------------------------------------------------------------


def test_repair_loop_title_and_round_notes():
    loop = rl.parse(receipt("runs.txt"))
    assert rl.title(loop) == "The Checker and the repair pass on nanochat's map (run 2)"
    assert rl.round_note(loop, 0) == "85 anchors replaced (all 85 cite more lines), 17 rewritten, 0 retired"
    assert rl.round_note(loop, 1) == "5 anchors replaced (all 5 cite more lines), 2 rewritten, 0 retired"
    fewer = rl.RepairLoop("r", (1, 2, 3), (3, 2, 1), (2, 1), (1, 0), (1, 1), (0, 0))
    assert rl.round_note(fewer, 0).startswith("2 anchors replaced (1 cite more lines)")


def test_status_colours_are_not_condition_colours():
    """Orange (map) and green (outline) mean conditions in the post: the status figures use neither."""
    conditions = {"#2a78d6", "#eb6834", "#1baf7a", "#3987e5", "#d95926", "#199e70"}
    for th in (*rl.THEMES,):
        assert not {th.yes, th.no} & conditions
    for th in rf.THEMES:
        assert not {th.ret, th.kept, th.new} & conditions


# -- adhoc-vs-map: the 'too lenient' guard sees a not_supported change -------------------------------------------------


def test_none_lenient_refuses_a_change_on_not_supported():
    """A change on a 'not_supported' verdict could be toward 'wrong' (the Checker too lenient), and the review does
    not record its direction, so the guard refuses it. Here one 'agree' becomes a 'change', in the total row and
    in the ad-hoc arm's row."""
    text = receipt("adhoc_check.txt")
    assert av.parse(text).review.none_lenient
    total = "  not_supported        6      2       0           4"
    arm = "  ad-hoc answers  not_supported        5      2       0           3"
    assert total in text and arm in text
    changed = av.parse(text.replace(total, "  not_supported        6      1       1           4")
                       .replace(arm, "  ad-hoc answers  not_supported        5      1       1           3"))
    assert changed.review.rows["not_supported"] == (6, 1, 1, 4)
    assert not changed.review.none_lenient
    with pytest.raises(ValueError, match="a change on a 'not_supported' one"):
        av.review_note(changed)
    # borderline calls alone stay allowed (today's receipt has 4)
    assert av.parse(text).review.rows["not_supported"][3] == 4

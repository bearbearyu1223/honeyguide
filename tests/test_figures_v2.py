"""eval/figures: the outline-v2 figures (team-before-after, pilot-scores, adhoc-vs-map, refresh-vs-rebuild).

Each parser is run against its real receipt in outputs/; "no typed numbers" is checked two ways: a receipt with a
number changed changes what the parser returns and the text the figure draws (title, note, footnote), and no
script holds a value the receipt prints as a literal in its source.
"""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "eval" / "figures"
OUT = ROOT / "outputs"


def load(name):
    spec = importlib.util.spec_from_file_location(f"eval_figures_{name}", FIG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod      # dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod


ps, av, rr, tb = (load(n) for n in ("pilot_scores", "adhoc_vs_map", "refresh_vs_rebuild", "team_before_after"))


def receipt(name):
    path = OUT / name
    if not path.exists():
        pytest.skip(f"no outputs/{name}")
    return path.read_text()


def literals(mod):
    """Every number written in a script's source."""
    tree = ast.parse(Path(mod.__file__).read_text())
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}


def distinctive(values):
    """Receipt values specific enough that finding one in the source means it was typed: not small integers, not
    round thresholds, and not 100 (the scripts' percent scale; the map arm's sample of 100 claims would match it)."""
    return {v for v in values if (isinstance(v, int) and v >= 10 and v != 100)
            or (isinstance(v, float) and round(v, 1) != v)}


# -- pilot-scores ------------------------------------------------------------------------------------------------------


def test_pilot_parses_the_real_receipt():
    p = ps.parse(receipt("eval_pilot_nanochat.txt"))
    assert p.conditions == ("no-access", "explore", "outline", "map")
    assert [(t.qtype, t.questions) for t in p.types] == [("locate", 6), ("callers", 5), ("flow", 4), ("whyhow", 5)]
    assert p.row("locate").means == {"no-access": 0.5, "explore": 1.0, "outline": 1.0, "map": 1.0}
    assert p.row("flow").means["map"] == 0.942 and p.row("whyhow").means["map"] == 1.0
    d = p.diff("map", "explore")
    assert (d.mean, d.lo, d.hi, d.n) == (0.022, -0.010, 0.075, 20)
    assert [(x.a, x.b) for x in p.diffs] == [("map", "explore"), ("map", "outline"), ("explore", "no-access")]
    assert p.grader == "GPT-6" and p.resamples == 10000
    assert ps.takeaway(p).startswith("On lookups")


def test_pilot_follows_the_receipt():
    text = receipt("eval_pilot_nanochat.txt")
    p = ps.parse(text.replace("+0.022  [-0.010, +0.075]", "+0.031  [-0.012, +0.080]")
                 .replace("ChatGPT (GPT-6)", "ChatGPT (GPT-9)"))
    assert (p.diff("map", "explore").mean, p.diff("map", "explore").hi) == (0.031, 0.080)
    assert p.grader == "GPT-9"
    # the title is checked: a lookup row where no-access is not the gap refuses to draw
    bad = ps.parse(text.replace("  locate            6       0.500", "  locate            6       1.000"))
    with pytest.raises(ValueError, match="no-access is not the gap"):
        ps.takeaway(bad)
    with pytest.raises(ValueError, match="no 'by type' block"):
        ps.parse("nothing here\n")


def test_pilot_has_no_typed_numbers():
    p = ps.parse(receipt("eval_pilot_nanochat.txt"))
    vals = {v for t in p.types for v in t.means.values()} | {t.questions for t in p.types}
    vals |= {x for d in p.diffs for x in (d.mean, d.lo, d.hi, d.n)} | {p.resamples}
    assert not distinctive(vals) & literals(ps)


# -- adhoc-vs-map ------------------------------------------------------------------------------------------------------


def test_adhoc_parses_the_real_receipt():
    c = av.parse(receipt("adhoc_check.txt"))
    assert (c.adhoc.bad, c.adhoc.claims, c.adhoc.share) == (10, 489, 0.020)
    assert (c.map.bad, c.map.claims, c.map.share) == (1, 100, 0.010)
    assert (c.diff, c.lo, c.hi) == (0.010, -0.016, 0.033)
    assert c.answers == 18 and c.review.reviewer == "GPT-6"
    assert c.review.rows["supported"] == (14, 14, 0, 0) and c.review.strict
    assert av.strict_note(c).endswith("agreed with 14/14 'supported' verdicts")
    assert av.takeaway(c).startswith("Ad-hoc answers and unchecked map claims are about equally")


def test_adhoc_follows_the_receipt():
    text = receipt("adhoc_check.txt")
    c = av.parse(text.replace("supported           14     14", "supported           13     13"))
    assert "13/13" in av.strict_note(c)
    # counts that don't give the printed share are refused
    with pytest.raises(ValueError, match="is not the printed"):
        av.parse(text.replace("479         5     5          0   0.020", "479         5     5          0   0.030"))
    # a CI that excludes zero would make the title false: it refuses
    c = av.parse(text.replace("+0.010, 95% CI [-0.016, +0.033]", "+0.010, 95% CI [+0.002, +0.033]"))
    with pytest.raises(ValueError, match="does not span zero"):
        av.takeaway(c)


def test_adhoc_has_no_typed_numbers():
    c = av.parse(receipt("adhoc_check.txt"))
    vals = {c.diff, c.lo, c.hi, c.answers}
    for a in (c.adhoc, c.map):
        vals |= {a.units, a.claims, a.supported, a.share}
    assert not distinctive(vals) & literals(av)


# -- refresh-vs-rebuild ------------------------------------------------------------------------------------------------


def test_refresh_parses_the_real_receipt():
    day, big = rr.parse(receipt("refresh.txt"))
    assert (day.repo, day.commits, day.days) == ("waku-agent", 2, 1.7)
    assert (day.rebuild_usd, day.rebuild_min, day.refresh_usd, day.refresh_min) == (19.39, 51.7, 3.92, 9.7)
    assert (day.ratio_usd, day.ratio_min, day.attempts) == (0.20, 0.19, 2)
    assert day.rebuild_passes == ("run 2", "repair", "re-check") and day.fraction == 5
    assert (big.repo, big.commits, big.days) == ("nanochat", 60, 59.8)
    assert (big.rebuild_usd, big.rebuild_min, big.refresh_usd, big.refresh_min) == (21.03, 52.5, 10.69, 25.2)
    assert (big.ratio_usd, big.ratio_min, big.attempts, big.rebuild_passes) == (0.51, 0.48, 1, ())
    assert big.fraction == 2
    assert rr.takeaway((day, big)) == ("Keeping the map current costs about 1/5 of a rebuild for an ordinary day,\n"
                                       "and about 1/2 across a 60-commit rewrite")
    assert "as 3 separate runs (build, repair, re-check)" in rr.footnote((day, big))


def test_refresh_follows_the_receipt():
    text = receipt("refresh.txt")
    _, big = rr.parse(text.replace("commits in between  60", "commits in between  61"))
    assert big.commits == 61 and "61-commit" in rr.takeaway(rr.parse(text.replace("between  60", "between  61")))
    # a printed ratio that the $ rows don't give is refused
    with pytest.raises(ValueError, match="the receipt says"):
        rr.parse(text.replace("$ 0.51, wall minutes 0.48", "$ 0.41, wall minutes 0.48"))
    # rebuild passes that don't sum to the total are refused
    with pytest.raises(ValueError, match="rebuild passes sum"):
        rr.parse(text.replace("repair                    $2.76", "repair                    $2.86"))


def test_refresh_has_no_typed_numbers():
    vals = set()
    for e in rr.parse(receipt("refresh.txt")):
        vals |= {e.days, e.commits, e.rebuild_usd, e.rebuild_min, e.refresh_usd, e.refresh_min, e.ratio_usd,
                 e.ratio_min}
    assert not distinctive(vals) & literals(rr)


# -- team-before-after (no numbers; Honey from the SVG) ----------------------------------------------------------------


def test_path_segments():
    segs = tb.path_segments("M1 2 3 4C5 6 7 8 9 10S11 12 13 14Q1 1 2 2H5V6Z")
    assert segs[0] == ("M", ((1.0, 2.0),)) and segs[1] == ("L", ((3.0, 4.0),))
    assert segs[3] == ("C", ((11.0, 12.0), (11.0, 12.0), (13.0, 14.0)))    # S reflects (7, 8) about (9, 10)
    assert segs[4][0] == "Q" and segs[5] == ("L", ((5.0, 2.0),)) and segs[6] == ("L", ((5.0, 6.0),))
    assert segs[-1] == ("Z", ())
    with pytest.raises(ValueError, match="relative"):
        tb.path_segments("m1 2l3 4")


def test_honey_svg_parses_to_its_resting_pose():
    svg = ROOT / "assets" / "avatars" / "honey.svg"
    box, shapes = tb.parse_honey(svg.read_text())
    assert box == (0.0, 0.0, 48.0, 48.0)
    fills = {s.fill for s in shapes}
    assert "#FFEDD2" in fills and "#E2A33C" in fills          # the body, the beak and satchel
    assert "#B8862A" not in fills                              # the trail is hidden at rest
    assert all(s.opacity > 0 for s in shapes)

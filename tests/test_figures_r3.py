"""eval/figures: the round-3 figures (cutoff-split, refresh-flow) and the refresh-vs-rebuild footnote's source.

Each parser runs against its real receipt in outputs/; a receipt with a number changed changes what it returns, sums
that don't add up are refused, and no script holds a value the receipt prints as a literal in its source.
"""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_figures_v2 import distinctive, load, receipt  # noqa: E402

STYLE_KEYWORDS = {"fontsize", "size", "s", "ms", "lw", "linewidths", "mutation_scale", "pad", "dpi", "gap"}


def literals(mod):
    """Every number in a script's source, less the values of styling keywords (font sizes, marker sizes, line
    widths), which are not data: a 12-point label is not the 12 unanchored claims."""
    tree = ast.parse(Path(mod.__file__).read_text())
    style = {id(k.value) for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords
             if k.arg in STYLE_KEYWORDS and isinstance(k.value, ast.Constant)}
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and id(n) not in style
            and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}

cs, rf, rr = (load(n) for n in ("cutoff_split", "refresh_flow", "refresh_vs_rebuild"))


# -- cutoff-split ------------------------------------------------------------------------------------------------------


def test_cutoff_parses_the_real_receipt():
    c = cs.parse(receipt("eval_pilot_nanochat.txt"))
    assert c.conditions == ("no-access", "explore", "outline", "map") and c.month == "June 2026"
    before, after = c.subset("before"), c.subset("after")
    assert (before.questions, after.questions) == (10, 5)
    assert before.means == {"no-access": 0.893, "explore": 0.95, "outline": 0.983, "map": 0.943}
    assert after.means == {"no-access": 0.2, "explore": 1.0, "outline": 1.0, "map": 1.0}
    d = c.diffs[("explore", "no-access", "after")]
    assert (d.mean, d.lo, d.hi, d.n) == (0.8, 0.4, 1.0, 5)
    assert cs.takeaway(c).startswith("With no access, the model knows nanochat's older code")
    assert cs.footnote(c).startswith("why/how questions carry no cutoff tag")


def test_cutoff_follows_the_receipt_and_checks_its_title():
    text = receipt("eval_pilot_nanochat.txt")
    with pytest.raises(ValueError, match="the means don't give"):
        cs.parse(text.replace("  after             5       0.200", "  after             5       0.300"))
    c = cs.parse(text.replace("explore - no-access, after      +0.800  [+0.400, +1.000]",
                              "explore - no-access, after      +0.800  [-0.100, +1.000]"))
    with pytest.raises(ValueError, match="reaches zero"):
        cs.takeaway(c)
    c = cs.parse(text.replace("cutoff 2026-06-30", "cutoff 2026-09-30"))
    assert c.month == "September 2026"


def test_cutoff_has_no_typed_numbers():
    c = cs.parse(receipt("eval_pilot_nanochat.txt"))
    vals = {v for s in c.subsets for v in s.means.values()} | {s.questions for s in c.subsets}
    vals |= {x for d in c.diffs.values() for x in (d.mean, d.lo, d.hi, d.n)}
    assert not distinctive(vals) & literals(cs)


# -- refresh-flow ------------------------------------------------------------------------------------------------------


def test_refresh_flow_parses_the_real_receipt():
    f = rf.parse(receipt("refresh.txt"))
    assert f.repo == "nanochat" and f.target_date.month == 7
    assert f.before == {"unchanged": 88, "moved": 128, "stale": 50, "retired": 32, "unanchored": 12}
    assert (f.total_before, f.new, f.after_total) == (310, 87, 397)
    assert f.after == {"current": 319, "stale": 0, "retired": 78}
    assert (f.by_apply, f.by_remap) == (32, 46)
    assert (f.held, f.held_retired, f.not_held, f.not_held_retired) == (15, 2, 35, 35)
    assert f.gap == {"moved": 3, "unanchored": 6}
    assert [f.kept(c) for c in rf.CLASSES] == [88, 125, 13, 0, 6]
    assert rf.takeaway(f) == "What a refresh did to nanochat's map across its July rewrite"
    assert rf.gap_note(f).startswith("the gap: 3 moved + 6 unanchored claims")


def test_refresh_flow_layout_conserves_claims():
    f = rf.parse(receipt("refresh.txt"))
    lay = rf.layout(f)
    out = {}
    for src, dst, _ in lay["bands"]:
        assert src[1] - src[0] == pytest.approx(dst[1] - dst[0])
        out[dst] = out.get(dst, 0) + (src[1] - src[0])
    for name, span in {**lay["ret"], **{k: v for k, v in lay["cur"].items() if k != "new"}}.items():
        assert out.get(span, 0) == pytest.approx(span[1] - span[0]), name
    assert sum(b - a for a, b in lay["ret"].values()) == f.after["retired"]
    assert sum(b - a for a, b in lay["cur"].values()) == f.after["current"]


def test_refresh_flow_refuses_sums_that_do_not_add_up():
    text = receipt("refresh.txt")
    with pytest.raises(ValueError, match="before \\+ 87 new"):
        rf.parse(text.replace("claims after        397", "claims after        398"))
    with pytest.raises(ValueError, match="does not add up"):
        rf.parse(text.replace("      by the re-map                         46", "      by the re-map                         47"))
    with pytest.raises(ValueError, match="no E9 section"):
        rf.parse(text, "E9")


def test_refresh_flow_has_no_typed_numbers():
    f = rf.parse(receipt("refresh.txt"))
    vals = set(f.before.values()) | set(f.after.values()) | {f.total_before, f.after_total, f.by_apply, f.by_remap,
                                                             f.new, f.held, f.not_held, f.held_retired}
    assert not distinctive(vals) & literals(rf)


# -- refresh-vs-rebuild: 'same Honeyguide code' comes from the receipt's reflog line ----------------------------------


def test_refresh_footnote_needs_the_reflog_line():
    text = receipt("refresh.txt")
    _, big = rr.parse(text)
    assert big.same_code
    assert "on the same Honeyguide code" in rr.footnote(rr.parse(text))
    flat = text.replace("same Honeyguide commit as the refresh", "a different Honeyguide commit from the refresh")
    with pytest.raises(ValueError, match="does not say its rebuild ran on the refresh's Honeyguide commit"):
        rr.footnote(rr.parse(flat))

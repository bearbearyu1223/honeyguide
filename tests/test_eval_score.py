"""eval/score: per-type scoring, paired bootstrap, blind grading, and the capture, end to end on a fake-claude
run archive (plan -> run -> resume -> score -> capture; no model call).
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_fixture as FX  # noqa: E402
import evalrun  # noqa: E402
import evalscore as ES  # noqa: E402
import grading as G  # noqa: E402
import pairstats as S  # noqa: E402
import scoring as SC  # noqa: E402

FUNCS = {"a.py": [SC.Fn("a.py", "f", 1, 10), SC.Fn("a.py", "f.<locals>.g", 3, 5), SC.Fn("a.py", "K.run", 12, 20),
                  SC.Fn("a.py", "L.run", 22, 30), SC.Fn("a.py", "K.helper", 32, 34)],
         "b.py": [SC.Fn("b.py", "main", 1, 9)]}


# ------------------------------------------------------------------------------------------------------------
# resolving items

@pytest.mark.parametrize("item, want", [
    ({"file": "a.py", "symbol": "f"}, ("a.py", "f")),
    ({"file": "./a.py", "symbol": "`def f(x)`"}, ("a.py", "f")),
    ({"file": "/private/tmp/hg-eval-x/work/a.py", "symbol": "K.run"}, ("a.py", "K.run")),
    ({"file": "a.py", "symbol": "pkg.a.K.run"}, ("a.py", "K.run")),
    ({"file": "a.py", "symbol": "helper"}, ("a.py", "K.helper")),          # unique suffix
    ({"file": "a.py", "symbol": "run"}, ("a.py", None)),                   # ambiguous, no line
    ({"file": "a.py", "symbol": "run", "line": 25}, ("a.py", "L.run")),    # ambiguous, line decides
    ({"file": "a.py", "symbol": "nope", "line": 4}, ("a.py", "f.<locals>.g")),   # innermost by line
    ({"file": "a.py", "symbol": "nope"}, ("a.py", None)),
    ({"file": "b.py", "symbol": "top-level"}, ("b.py", "<module>")),
])
def test_resolve_item(item, want):
    assert SC.resolve_item(item, FUNCS, "/private/tmp/hg-eval-x/work") == want


def test_locate_first_item_function_level():
    key = {"file": "a.py", "qual": "f", "also_accept": []}
    s = SC.score_locate({"items": [{"file": "a.py", "symbol": "f"}]}, key, FUNCS)
    assert s["score"] == 1.0 and s["file_ok"]
    s = SC.score_locate({"items": [{"file": "a.py", "symbol": "g", "line": 4}]}, key, FUNCS)
    assert s["score"] == 1.0                                    # nested in the key function
    s = SC.score_locate({"items": [{"file": "a.py", "symbol": "K.run"}, {"file": "a.py", "symbol": "f"}]}, key, FUNCS)
    assert s["score"] == 0.0 and s["file_ok"] and s["any_item_func_ok"]
    s = SC.score_locate({"items": [{"file": "b.py", "symbol": "f"}]}, key, FUNCS)
    assert s["score"] == 0.0 and not s["file_ok"]
    assert SC.score_locate({"items": []}, key, FUNCS)["score"] == 0.0


def test_callers_prf_with_decided_disputes():
    q = {"key": {"callers": [{"file": "a.py", "qual": "f", "also_accept": []},
                             {"file": "b.py", "qual": "main", "also_accept": []}]},
         "disputes_for_han": [{"file": "a.py", "caller": "K.run"}, {"file": "a.py", "caller": "L.run"},
                              {"file": "a.py", "caller": "K.helper"}]}
    dec = [{"decision": "caller"}, {"decision": "not"}, {"decision": None}]
    pos, neg = SC.callers_key(q, dec)
    assert len(pos) == 3 and neg == [("a.py", "L.run")]

    def score(*pairs):
        items = [{"file": f, "symbol": s} for f, s in pairs]
        return SC.score_callers({"items": items}, q, dec, FUNCS, lambda p: not p.startswith("tests/"))
    s = score(("a.py", "f"), ("b.py", "main"), ("a.py", "K.run"))
    assert (s["precision"], s["recall"], s["score"]) == (1.0, 1.0, 1.0)
    s = score(("a.py", "f"), ("a.py", "L.run"), ("tests/t.py", "test_x"))
    assert s["tp"] == 1 and s["fp"] == 1 and s["fp_decided_not"] == 1 and s["ignored_out_of_scope"] == 1
    assert s["score"] == pytest.approx(2 * 0.5 * (1 / 3) / (0.5 + 1 / 3))
    s = score(("a.py", "f"), ("a.py", "f"))                     # named twice: counted once
    assert s["tp"] == 1 and s["fp"] == 0
    assert score()["score"] == 0.0
    empty = {"key": {"callers": []}, "disputes_for_han": []}
    assert SC.score_callers({"items": []}, empty, [], FUNCS, lambda p: True)["score"] == 1.0


def test_lcs():
    assert SC.lcs([1, 2, 3], [1, 2, 3]) == 3
    assert SC.lcs([2, 1, 3], [1, 2, 3]) == 2
    assert SC.lcs([], [1]) == 0 and SC.lcs([3, 2, 1], [1, 2, 3]) == 1


def test_flow_order_recall_and_item_classes():
    hops = [{"file": "a.py", "qual": q} for q in ("K.run", "f", "K.helper", "L.run")]
    marks = ["required", "required", "optional", "excluded"]
    trace = {("a.py", "K.run"), ("a.py", "f"), ("b.py", "main")}
    reach = {("a.py", "K.run"), ("a.py", "f"), ("a.py", "f.<locals>.g")}

    def score(*syms):
        items = [{"file": f, "symbol": s} for f, s in syms]
        return SC.score_flow({"items": items}, hops, marks, FUNCS, trace, reach)
    s = score(("a.py", "K.run"), ("a.py", "f"))
    assert s["score"] == 1.0 and s["recall"] == 1.0
    s = score(("a.py", "f"), ("a.py", "K.run"), ("a.py", "K.helper"), ("a.py", "L.run"))
    assert s["score"] == 0.5 and s["recall"] == 1.0 and s["optional_named"] == 1 and s["invented"] == 0
    s = score(("a.py", "K.run"), ("b.py", "main"), ("a.py", "g"), ("a.py", "made_up"), ("c.py", "x"))
    assert (s["trace"], s["other path"], s["invented"]) == (1, 1, 2) and s["score"] == 0.5


# ------------------------------------------------------------------------------------------------------------
# analysis

def test_bootstrap_is_seeded_and_brackets_the_mean():
    d = [0.0, 0.5, 1.0, 0.25, 0.75, 0.0, 1.0]
    a, b = S.bootstrap_ci(d, 2000, 0), S.bootstrap_ci(d, 2000, 0)
    assert a == b and a[0] <= S.mean(d) <= a[1]
    assert S.bootstrap_ci([0.2] * 5, 500, 1) == (pytest.approx(0.2), pytest.approx(0.2))
    assert all(math.isnan(x) for x in S.bootstrap_ci([], 10, 0))


def test_paired_and_question_scores():
    qs = S.question_scores({("q1", "map"): [1.0, 0.0, 1.0], ("q1", "explore"): [0.0, 1.0],
                            ("q2", "map"): [1.0], ("q3", "explore"): [0.0]})
    assert qs["q1"]["map"] == pytest.approx(2 / 3) and qs["q1"]["explore"] == 0.5
    assert S.paired(qs, "map", "explore") == [pytest.approx(2 / 3 - 0.5)]      # q2, q3 lack a pair


def test_break_even():
    # build $10; map $0.5 per exact answer at 50% accuracy, explore $1.5: 10 / (0.5 * 1.0) = 20 questions
    assert S.break_even(10.0, 0.5, 1.5, 0.5) == pytest.approx(20.0)
    assert S.break_even(10.0, 2.0, 1.5, 0.5) is None and S.break_even(10.0, 0.5, 1.5, 0.0) is None


# ------------------------------------------------------------------------------------------------------------
# blind grading

def test_policy_and_grades_round_trip():
    text, scale = G.policy_of({})
    assert scale == G.DEFAULT_SCALE and "No grading_policy" in text
    text, scale = G.policy_of({"grading_policy": {"text": "Han's rule", "scale": {"full": 1, "half": 0.5,
                                                                                  "none": 0}}})
    assert text == "Han's rule" and scale == {"full": 1.0, "half": 0.5, "none": 0.0}
    qs = [{"id": "w1", "text": "Why?", "rubric_must": ["a", "b"]}]
    answers = [{"run_id": f"w1__{c}__p1", "qid": "w1", "answer": {"text": f"answer {i}", "items": []}}
               for i, c in enumerate(("map", "explore", "outline", "no-access"))]
    sheet, key = G.build_sheet(qs, answers, 0, text, scale)
    blob = json.dumps(sheet)
    for c in ("map", "explore", "outline", "no-access", "__p1"):
        assert c not in blob                       # the condition never shows on the sheet
    assert sorted(key.values()) == sorted(a["run_id"] for a in answers)
    assert G.build_sheet(qs, answers, 0, text, scale) == (sheet, key)
    order = [a["text"] for a in sheet["questions"][0]["answers"]]
    assert order != [a["answer"]["text"] for a in sorted(answers, key=lambda a: a["run_id"])] or len(order) < 3
    grades = {"grades": {b: "full" for b in key} | {"w1-Z": "full"}}
    first = sorted(key)[0]
    grades["grades"][first] = "great"
    scores, problems = G.read_grades(grades, key, scale)
    assert len(scores) == 3 and len(problems) == 2
    assert "## Grading policy" in G.sheet_markdown(sheet)


# ------------------------------------------------------------------------------------------------------------
# end to end

@pytest.fixture
def scored(tmp_path, monkeypatch):
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    fx = FX.make(tmp_path)
    a = ["--repo", "fx", "--size", "tiny", "--config", str(fx["config"]), "--claude-bin", str(fx["fake"]),
         "--run-id", "r"]
    assert evalrun.main(a) == 3          # usage limit
    assert evalrun.main(a) == 0          # resumed to the end
    return fx


def run_score(fx, capsys, *extra):
    assert ES.main(["--run-id", "r", "--config", str(fx["config"]), *extra]) == 0
    return capsys.readouterr().out


def test_capture_end_to_end(scored, capsys):
    out = run_score(scored, capsys)
    assert out == run_score(scored, capsys)                       # deterministic
    assert all(len(ln) <= ES.WIDTH and ln == ln.rstrip() for ln in out.splitlines())
    lines = out.splitlines()

    def row(prefix, after="scores by condition"):
        start = next(i for i, ln in enumerate(lines) if ln.startswith(after))
        return next(ln for ln in lines[start:] if ln.startswith(prefix)).split()
    # per condition: runs, scored, mean, exact, capped, error, invalid (why/how ungraded: left out)
    assert row("  map ") == ["map", "12", "9", "1.000", "9", "0", "0", "0"]
    assert row("  outline ") == ["outline", "8", "6", "0.333", "2", "2", "0", "2"]
    assert row("  no-access ")[:2] == ["no-access", "4"] and row("  no-access ")[5:7] == ["0", "1"]
    # by type: explore callers F1 = 2PR/(P+R) with P 2/3, R 2/4; flow LCS 2 of 3 required
    assert row("  callers ")[2:4] == ["0.000", "0.571"] and row("  flow ")[2:4] == ["0.000", "0.667"]
    assert "other path 3, invented 3" in out and "decided are not callers 2" in out
    assert "anchors 3/4 resolved" in out and "unresolved: c3 scripts/main.py (not_found)" in out
    assert "map - explore" in out and "n=3" in out
    assert "fx-cal-01__outline__p1 capped (error_max_budget_usd)" in out
    assert "graded 0 of 6 finished answers" in out and "awaiting grades" in out
    assert "within 0.0% of the CLI's total_cost_usd" in out
    assert "used: (no result) x2, claude-opus-5-5 x31" in out
    assert "re-run after an interruption or usage limit 1" in out
    assert FX.TOKEN not in out


def test_grading_round_trip_changes_scores(scored, capsys):
    root = scored["archive"] / "r" / "grading"
    run_score(scored, capsys, "--grading-sheet")
    sheet = json.loads((root / "sheet.json").read_text())
    key = json.loads((root / "blind_key.json").read_text())
    assert len(key) == 6 and "explore" not in (root / "sheet.md").read_text()   # explore whyhow runs failed
    grades = json.loads((root / "grades.json").read_text())
    for b, rid in key.items():
        grades["grades"][b] = "correct" if "__map__" in rid else "wrong"
    (root / "grades.json").write_text(json.dumps(grades))
    out = run_score(scored, capsys)
    assert "graded 6 of 6 finished answers" in out and "awaiting grades (left out of" in out
    row = next(ln for ln in out.splitlines() if ln.startswith("  whyhow ")).split()
    assert row[1:] == ["1", "0.000", "0.000", "0.000", "1.000"]   # explore: both runs failed (token) = 0
    assert sheet["questions"][0]["rubric_must"] == ["names compute and finish", "says why"]
    # re-running the sheet keeps Han's grades file
    run_score(scored, capsys, "--grading-sheet")
    assert json.loads((root / "grades.json").read_text()) == grades


def test_leakage_flags_key_names_in_the_question():
    q = {"type": "locate", "text": "x", "leaks": ["finish"]}
    assert ES.leakage(q, []) == ["finish"]                                               # frozen with the question
    q = dict(FX.frozen("c" * 40)["questions"][1])
    assert ES.leakage(q, [{"decision": "not"}, {"decision": "caller"}]) == []            # target named on purpose
    q["text"] += " Is compute one? And via?"
    assert ES.leakage(q, [{"decision": "not"}, {"decision": "caller"}]) == ["compute", "via"]
    assert ES.leakage(q, [{"decision": "not"}, {"decision": "not"}]) == ["compute"]      # via decided not a caller
    q["text"] += " Engine?"
    assert ES.leakage(q, [{"decision": "not"}, {"decision": "not"}]) == ["Engine", "compute"]


def test_class_index_lets_a_class_body_caller_resolve():
    src = "class A:\n    x = f()\n\n    class B:\n        y = 1\n\n\ndef g():\n    class C:\n        pass\n"
    got = [(c.qual, c.start, c.end) for c in ES.class_index(src, "m.py")]
    assert got == [("A", 1, 5), ("A.B", 4, 5), ("g.<locals>.C", 9, 10)]
    funcs = {"m.py": ES.class_index(src, "m.py")}
    assert SC.resolve_item({"file": "m.py", "symbol": "A"}, funcs) == ("m.py", "A")


def test_grader_label_reads_the_grades_file():
    import evalscore as ES
    assert ES.grader_label({"grader": "ChatGPT (GPT-6)", "how": "sheet only"}) == ("ChatGPT (GPT-6)", "sheet only")
    assert ES.grader_label({"grades": {}}) == ("not recorded", "")
    assert ES.grader_label(None) == ("not recorded", "")


def test_cost_per_exact_answer_has_three_decimals_and_the_gap(scored, capsys):
    """Review round 4: '$0.17' for both outline and map hid the gap the break-even divides by. Costs per exact
    answer print to a tenth of a cent, and a finite break-even prints the per-answer gap it comes from."""
    out = run_score(scored, capsys)
    block = out[out.index("cost per exact answer"):]
    rows = [ln for ln in block.splitlines()[1:5] if "exact of" in ln]
    assert rows and all(re.search(r"\$\d+\.\d{3}  \(\d+ exact of \d+ runs\)", ln) for ln in rows)
    flat = " ".join(block.split())
    for m in re.finditer(r"break-even vs \w+: (\d+) questions asked", flat):
        assert re.match(r" \(map answers \$\d+\.\d{4} cheaper per exact answer\)", flat[m.end():])


def test_real_pilot_break_even_follows_from_the_printed_gap():
    """The pilot receipt's outline break-even is the build over (map accuracy x the printed gap), to the gap's
    rounding (half of $0.0001), so a reader can rebuild it from the receipt."""
    path = Path(__file__).resolve().parents[1] / "outputs" / "eval_pilot_nanochat.txt"
    if not path.exists():
        pytest.skip("no outputs/eval_pilot_nanochat.txt")
    flat = " ".join(path.read_text().split())
    build = float(re.search(r"map build: \$([\d.]+) list per map", flat).group(1))
    exact, runs = (int(x) for x in re.search(r"map \$[\d.]+ \((\d+) exact of (\d+) runs\)", flat).groups())
    n, gap = re.search(r"break-even vs outline: (\d+) questions asked \(map answers \$([\d.]+) cheaper", flat).groups()
    gap = float(gap)
    lo, hi = (build / (exact / runs * (gap + d)) for d in (0.00005, -0.00005))
    assert lo <= int(n) <= hi

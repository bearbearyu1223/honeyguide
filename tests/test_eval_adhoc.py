"""eval/adhoc (E1): the splitter, the check's isolation, resume, stops, the evidence pass and the capture, with a
fake `claude` (no model call anywhere) and a synthetic source archive built on the eval fixture's tiny repo.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "eval" / "adhoc"))
import adhoc as A  # noqa: E402
import adhoc_report as R  # noqa: E402
import adhoc_split as S  # noqa: E402
import eval_fixture as FX  # noqa: E402
import evalcfg as C  # noqa: E402
import isolate  # noqa: E402
import workdirs as W  # noqa: E402

ALLOWED_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_OAUTH_TOKEN",
               "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER", "HOME", "LANG", "PATH", "TERM", "TMPDIR",
               "__CF_USER_TEXT_ENCODING"}
HERE_ADHOC = ROOT / "eval" / "adhoc"
PILOT = Path("~/Documents/GitHub/honeyguide-targets/_eval/pilot-nanochat-2").expanduser()


def texts(t: str) -> list[str]:
    return [u.text for u in S.split_units("r", t)]


# ------------------------------------------------------------------------------------------------------------
# the splitter (cases from the pilot's explore answers)

def test_split_code_spans_paths_decimals_and_abbreviations():
    t = ("Muon groups: all the transformer block matrices (`self.transformer.h.parameters()`), grouped by shape. "
         "norm (gpt.py:42, a wrapper around F.rms_norm) normalizes the embeddings (line 473). "
         "wte is drawn from a normal distribution with std 0.8; lm_head from a normal with std 0.001. "
         "those should all be optimized by a standard method (e.g. AdamW), i.e. element-wise. "
         "It scales by (model_dim/768)^-0.5. model_dim comes from depth, so this scaling does too.")
    assert texts(t) == [
        "Muon groups: all the transformer block matrices (`self.transformer.h.parameters()`), grouped by shape.",
        "norm (gpt.py:42, a wrapper around F.rms_norm) normalizes the embeddings (line 473).",
        "wte is drawn from a normal distribution with std 0.8; lm_head from a normal with std 0.001.",
        "those should all be optimized by a standard method (e.g. AdamW), i.e. element-wise.",
        "It scales by (model_dim/768)^-0.5.",
        "model_dim comes from depth, so this scaling does too."]


def test_split_code_span_ending_a_sentence_and_ellipsis():
    t = ("1. `last_step = step == num_iterations`. The loop runs num_iterations+1 times (line 417).\n"
         "2. The SDPA fallback writes k/v into cache positions 0..9, slices the cache. Rank r reads r, r+W, ... "
         "and so on. It also logs etc. and more. Then stops, etc. Done.")
    assert texts(t) == ["`last_step = step == num_iterations`.",
                        "The loop runs num_iterations+1 times (line 417).",
                        "The SDPA fallback writes k/v into cache positions 0..9, slices the cache.",
                        "Rank r reads r, r+W, ... and so on.",
                        "It also logs etc. and more.", "Then stops, etc.", "Done."]


def test_split_lists_each_item_a_unit_with_levels():
    t = ("Order of calls inside GPT.forward (nanochat/gpt.py:459):\n\n"
         "1. It slices the cached cos/sin down to T=16.\n"
         "2. norm (gpt.py:42) normalizes the embeddings\n"
         "4. Then Block.forward (gpt.py:150) runs:\n"
         "   - norm, then CausalSelfAttention.forward (gpt.py:84):\n"
         "     - Linear.forward three times, for c_q, c_k and c_v\n"
         "     - apply_rotary_emb on q, then on k (line 101).\n"
         "   a. `norm`, then the MLP\n"
         "   - At i == n_layer//2 (layer 1), it saves the output as x_backout.\n"
         "5. After the loop it subtracts backout_lambda * x_backout.\n\n"
         "Functions not called: GPT.generate.")
    us = S.split_units("nc-flo-02__explore__p1", t)
    assert [(u.kind, u.level, u.text) for u in us] == [
        ("para", 0, "Order of calls inside GPT.forward (nanochat/gpt.py:459):"),
        ("item", 0, "It slices the cached cos/sin down to T=16."),
        ("item", 0, "norm (gpt.py:42) normalizes the embeddings"),
        ("item", 0, "Then Block.forward (gpt.py:150) runs:"),
        ("item", 1, "norm, then CausalSelfAttention.forward (gpt.py:84):"),
        ("item", 2, "Linear.forward three times, for c_q, c_k and c_v"),
        ("item", 2, "apply_rotary_emb on q, then on k (line 101)."),
        ("item", 1, "`norm`, then the MLP"),
        ("item", 1, "At i == n_layer//2 (layer 1), it saves the output as x_backout."),
        ("item", 0, "After the loop it subtracts backout_lambda * x_backout."),
        ("para", 0, "Functions not called: GPT.generate.")]
    assert [u.id for u in us][:2] == ["nc-flo-02__explore__p1#s1", "nc-flo-02__explore__p1#s2"]
    assert S.split_units("nc-flo-02__explore__p1", t) == us            # stable


def test_split_bold_lead_in_kept_with_its_sentence_and_bold_line_alone():
    t = ("**Setup before the loop.** If the run is fresh, step=0. If resuming, values come from the checkpoint.\n\n"
         "**Order inside each iteration.**\n"
         "6. **Exit check.** If `last_step` is true, the loop breaks here (line 502).\n"
         "2. **Validation bpb** (line 421) runs when `step % eval_every == 0`.\n\n"
         "**Resuming:** when restarting, the loader takes the saved `rg_idx`. It then starts later.")
    assert texts(t) == [
        "**Setup before the loop.** If the run is fresh, step=0.",
        "If resuming, values come from the checkpoint.",
        "**Order inside each iteration.**",
        "**Exit check.** If `last_step` is true, the loop breaks here (line 502).",
        "**Validation bpb** (line 421) runs when `step % eval_every == 0`.",
        "**Resuming:** when restarting, the loader takes the saved `rg_idx`.",
        "It then starts later."]


def test_split_wrapped_lines_headings_and_fences():
    t = ("# Heading\nA paragraph that\nwraps over lines. Second one.\n- an item that\n  continues here.\n\n"
         "```python\nx = 1. \ny = 2\n```\nAfter.")
    us = S.split_units("r", t)
    assert [(u.kind, u.text) for u in us] == [
        ("heading", "Heading"), ("para", "A paragraph that wraps over lines."), ("para", "Second one."),
        ("item", "an item that continues here."), ("code", "```python\nx = 1. \ny = 2\n```"), ("para", "After.")]


@pytest.mark.skipif(not PILOT.exists(), reason="the pilot archive is local")
def test_split_real_pilot_answers_keep_every_word():
    """Every word of every in-scope pilot answer lands in exactly one unit, in order (markers aside)."""
    _, answers, skipped = A.source_answers(PILOT, A.DEFAULT_TYPES)
    assert len(answers) == 18 and skipped == []
    for a in answers:
        us = S.split_units(a["id"], a["text"])
        words = " ".join(u.text for u in us).split()
        body = []
        for ln in a["text"].splitlines():
            m = S.ITEM.match(ln)
            body.append(m.group(2) if m else ln)
        assert words == " ".join(body).split(), a["id"]


# ------------------------------------------------------------------------------------------------------------
# pure helpers

UNITS = [{"id": f"a#s{k}", "text": f"t{k}", "kind": "para", "level": 0} for k in (1, 2, 3)]


def test_parse_verdicts_ids_paths_and_problems():
    res = {"structured_output": {"units": [
        {"id": "s1", "verdict": "supported", "note": "ok",
         "evidence": [{"path": "/private/tmp/hg-eval-x/work/pkg/core.py", "start": 1, "end": 2},
                      {"path": "./scripts/main.py", "start": 3, "end": 3}]},
        {"id": "s1", "verdict": "wrong", "note": "dup", "evidence": []},
        {"id": "s9", "verdict": "wrong", "note": "", "evidence": []},
        {"id": "s2", "verdict": "maybe", "note": "", "evidence": []}]}}
    rows, how, problems = A.parse_verdicts(res, UNITS, ("/private/tmp/hg-eval-x/work",))
    assert how == "structured_output"
    # s1 twice with different verdicts: flagged and left without a verdict, never merged
    assert [r["verdict"] for r in rows] == [None, None, None]
    assert problems == ["s1: repeated with different verdicts (supported, wrong): no verdict",
                        "entry 2: unknown id 's9'", "entry 3: malformed",
                        "s1: no verdict", "s2: no verdict", "s3: no verdict"]
    res["structured_output"]["units"][1]["verdict"] = "supported"      # the same verdict twice: first kept
    rows, how, problems = A.parse_verdicts(res, UNITS, ("/private/tmp/hg-eval-x/work",))
    assert [r["verdict"] for r in rows] == ["supported", None, None]
    assert rows[0]["evidence"] == [{"path": "pkg/core.py", "start": 1, "end": 2},
                                   {"path": "scripts/main.py", "start": 3, "end": 3}]
    assert problems[0] == "s1: repeated with the same verdict (supported; first kept)"
    assert A.parse_verdicts({"structured_output": {"items": []}, "result": "x"}, UNITS)[0] is None
    assert A.parse_verdicts(None, UNITS)[0] is None


def test_evidence_check():
    files = {"pkg/core.py": ["l"] * 10}
    rows = [{"unit": "a#s1", "verdict": "supported", "evidence": [{"path": "pkg/core.py", "start": 2, "end": 10}]},
            {"unit": "a#s2", "verdict": "wrong", "evidence": [{"path": "pkg/core.py", "start": 9, "end": 11},
                                                              {"path": "pkg/none.py", "start": 1, "end": 1}]},
            {"unit": "a#s3", "verdict": "supported", "evidence": [{"path": "/abs/x.py", "start": 1, "end": 1},
                                                                  {"path": "pkg/core.py", "start": 0, "end": 1},
                                                                  {"path": "pkg/core.py", "start": 5, "end": 4}]},
            {"unit": "a#s4", "verdict": "not_a_claim", "evidence": []}]
    out = A.check_evidence(rows, files.get)
    assert [e["ranges"] for e in out] == [1, 2, 3, 0]
    assert [[b["why"] for b in e["bad"]] for e in out] == [
        [], ["lines out of range (file has 10)", "no such file"],
        ["bad path", "lines out of range (file has 10)", "lines out of range (file has 10)"], []]


def test_check_command_is_isolated_read_grep_glob_only(tmp_path):
    cfg = C.load_config()
    spec = A.check_spec(cfg, prompt="p", workdir=tmp_path / "work", config_dir=tmp_path / "cfg",
                        home_dir=tmp_path / "home", claude_bin="claude")
    run = isolate.build_run(spec, {"CLAUDE_CODE_OAUTH_TOKEN": "t", "LANG": "C", "USER": "x", "ANTHROPIC_API_KEY": "k"})
    a = run.argv
    assert a[a.index("--tools") + 1] == "Read,Grep,Glob" and not any("Bash" in x for x in a)
    assert "--add-dir" not in a and a[a.index("--max-budget-usd") + 1] == "1.5"
    assert a[a.index("--model") + 1] == "claude-opus-5-5" and a[a.index("--effort") + 1] == "medium"
    assert json.loads(a[a.index("--json-schema") + 1]) == json.loads(A.SCHEMA.read_text())
    assert a[a.index("--output-format") + 1] == "stream-json" and a[a.index("--setting-sources") + 1] == ""
    assert run.cwd == tmp_path / "work" and set(run.env) <= ALLOWED_ENV and "USER" not in run.env


MAP_TXT = """checker
--------------------------------------------------------------------------
Map claims by Checker verdict.
  repo        stage                  supported not supp. unchecked retired
  fx          run 2 before repair          158       102         0       0
  fx          after repair round 1         253         7         0       0

maps
--------------------------------------------------------------------------
  fx, run 2 after re-check
    claims              260
    Checker verdicts    supported 256, not supported 4

recheck
--------------------------------------------------------------------------
After the repair pass, a batch run re-checked every map claim that states
a value under the Checker's new "Compute, don't quote" rule, then ran the
repair pass.
  repo         map claims  re-checked  newly not supp.  still not supp.
  fx                  260         117               39                4

  Re-checked claims by state:
  repo        stage                  supported not supp. unchecked retired
  fx          before repair                 78        39         0       0

demo
--------------------------------------------------------------------------
  q1
    repo              fx
    answer claims     13
    Checker           supported 4, not supported 9

examples
--------------------------------------------------------------------------
"""


def test_runs_txt_parsers():
    assert R.parse_map_checker(MAP_TXT) == [
        {"repo": "fx", "stage": "run 2 before repair", "supported": 158, "not_supported": 102},
        {"repo": "fx", "stage": "after repair round 1", "supported": 253, "not_supported": 7}]
    assert R.parse_demo_answers(MAP_TXT) == [{"q": "q1", "repo": "fx", "claims": 13, "supported": 4,
                                              "not_supported": 9}]
    assert R.parse_map_checker("nothing here\n") == []
    assert R.parse_recheck(MAP_TXT) == {
        "rule_new": True, "summary": [{"repo": "fx", "map_claims": 260, "rechecked": 117, "newly": 39, "still": 4}],
        "states": [{"repo": "fx", "stage": "before repair", "supported": 78, "not_supported": 39}]}
    mrs, rcs, _ = R.map_rows(MAP_TXT)
    assert [(m["stage"], m["rule"]) for m in mrs] == [("run 2 before repair", "before"),
                                                     ("after repair round 1", "before"),
                                                     ("run 2 after re-check", "mixed")]
    assert [(m["stage"], m["rule"]) for m in rcs] == [("before repair", "with")]
    no_rule = MAP_TXT.replace('new "Compute, don\'t quote" rule', "rule")
    assert {m["rule"] for m in R.map_rows(no_rule)[0][:2]} == {"?"}
    real = ROOT / "outputs" / "runs.txt"
    if real.exists():
        rows = R.parse_map_checker(real.read_text())
        assert {(r["repo"], r["stage"]) for r in rows} >= {("nanochat", "run 2 before repair"),
                                                           ("waku-agent", "run 2 before repair")}
        rc = R.parse_recheck(real.read_text())
        assert rc["rule_new"] and {(x["repo"], x["rechecked"]) for x in rc["summary"]} >= {("nanochat", 117)}
        assert ("nanochat", "before repair", 78, 39) in {(x["repo"], x["stage"], x["supported"], x["not_supported"])
                                                         for x in rc["states"]}


def test_sample_is_seeded_and_round_robin():
    rows = [{"unit": f"a#s{k}", "verdict": v} for k, v in enumerate(
        ["supported"] * 30 + ["wrong"] * 2 + ["not_supported"] * 5 + ["not_a_claim"] * 4)]
    s = R.sample(rows, 0)
    assert len(s) == 20 and R.sample(rows, 0) == s and len({r["unit"] for r in s}) == 20
    assert [r["verdict"] for r in s[:4]] == ["supported", "not_supported", "wrong", "not_a_claim"]
    assert sum(r["verdict"] == "wrong" for r in s) == 2


# ------------------------------------------------------------------------------------------------------------
# end to end with the fake claude

FLOW_TEXT = ("I read pkg/core.py; I did not run it.\n\n1. `Engine.run` calls `compute` (pkg/core.py:24).\n"
             "2. `compute` calls `helper`, then `finish`, which triples the value.")
WHY_TEXT = "The work is split so each step stays small. `finish` doubles its input (pkg/core.py:20)."


def _ev(path, s, e):
    return {"path": path, "start": s, "end": e}


def check_rules() -> list[dict]:
    flow = {"units": [
        {"id": "s1", "verdict": "not_a_claim", "note": "framing", "evidence": []},
        {"id": "s2", "verdict": "wrong", "note": "line reference: Engine.run is at line 23",
         "evidence": [_ev("pkg/core.py", 23, 24)]},
        {"id": "s3", "verdict": "wrong", "note": "finish doubles (return y * 2)",
         "evidence": [_ev("pkg/core.py", 900, 901)]}]}
    flow_p2 = {"units": [
        {"id": "s1", "verdict": "not_a_claim", "note": "framing", "evidence": []},
        {"id": "s2", "verdict": "supported", "note": "ok", "evidence": [_ev("./pkg/core.py", 23, 24)]}]}
    why = {"units": [
        {"id": "s1", "verdict": "not_supported", "note": "no design note found", "evidence": []},
        {"id": "s2", "verdict": "supported", "note": "return y * 2", "evidence": [_ev("pkg/nope.py", 1, 2)]}]}
    return [{"match": "which triples the value", "answer": flow},
            {"match": "[s2] `Engine.run` calls `compute` (pkg/core.py:23)", "answer": flow_p2},
            {"match": "each step stays small", "answer": why}]


MAP_CLAIMS = (
    [{"key": f"r{k}", "evidence": "read_in_source", "text": f"claim r{k}: `finish` doubles its input ({k})",
      "anchors": [{"path": "pkg/core.py", "anchor": f"ANCHOR-SECRET-{k}"}]} for k in range(6)]
    + [{"key": f"d{k}", "evidence": "docs", "text": f"claim d{k}: the README says so ({k})",
        "anchors": [{"path": "README.md", "anchor": f"ANCHOR-SECRET-d{k}"}]} for k in range(2)]
    + [{"key": "i0", "evidence": "inferred", "text": "claim i0: main reaches finish", "anchors": []},
       {"key": "n0", "evidence": "searched_not_found", "text": "claim n0: no HTTP server", "anchors": [],
        "searched": ["flask"]}])
MAP_ANSWER = {"units": [
    {"id": "s1", "verdict": "supported", "note": "ok", "evidence": [_ev("pkg/core.py", 20, 21)]},
    {"id": "s2", "verdict": "wrong", "note": "it triples", "evidence": [_ev("pkg/core.py", 20, 21)]},
    {"id": "s3", "verdict": "not_supported", "note": "not found", "evidence": []}]}
MAP_RULE = {"match": "There is no question.", "answer": MAP_ANSWER}


def make_source(fx: dict, tmp: Path) -> Path:
    """A source run archive like pilot-nanochat-2: explore answers for flow, why/how and locate questions; one
    flow pass that failed (left out of scope)."""
    src = tmp / "archive" / "src"
    qs = [{"id": "fx-flo-01", "type": "flow", "text": FX.Q_FLO, "subset": "before"},
          {"id": "fx-why-01", "type": "whyhow", "text": FX.Q_WHY, "subset": "none"},
          {"id": "fx-loc-01", "type": "locate", "text": FX.Q_LOC, "subset": "after"}]
    answers = {("fx-flo-01", 1): ("ok", FLOW_TEXT),
               ("fx-flo-01", 2): ("ok", "I read pkg/core.py; I did not run it.\n\n"
                                        "1. `Engine.run` calls `compute` (pkg/core.py:23)."),
               ("fx-flo-01", 3): ("error", ""),
               ("fx-why-01", 1): ("ok", WHY_TEXT),
               ("fx-loc-01", 1): ("ok", "In `finish`. It doubles."),
               ("fx-flo-01", 9): ("ok", "a no-access answer")}
    items = []
    for (qid, k), (st, text) in answers.items():
        q = next(q for q in qs if q["id"] == qid)
        cond = "no-access" if k == 9 else "explore"
        rid = f"{qid}__{cond}__p{k}"
        items.append({"id": rid, "kind": "answer", "repo": "fx", "qid": qid, "qtype": q["type"],
                      "subset": q["subset"], "condition": cond, "pass_no": k, "map_seed": 0})
        d = src / "runs" / rid
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({
            "id": rid, "status": st, "answer": {"items": [], "text": text} if st == "ok" else None,
            "usage": {"cost_usd": 0.05}, "wall_s": 12.0}))
    (src / "maps" / "seed1").mkdir(parents=True)
    (src / "maps" / "seed1" / "map.json").write_text(json.dumps({"target": "map", "mode": "replace",
                                                                  "document": {}, "claims": MAP_CLAIMS}))
    (src / "plan.json").write_text(json.dumps({"run_id": "src", "repo": "fx", "commit": fx["commit"],
                                               "url": FX.frozen(fx["commit"])["url"], "questions": qs,
                                               "items": items}))
    return src


@pytest.fixture
def ah(tmp_path, monkeypatch):
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    fx = FX.make(tmp_path)
    FX.write_fake(tmp_path / "bin", {"rules": check_rules() + [MAP_RULE], "map_output": FX.MAP_OUTPUT})
    fx["src"] = make_source(fx, tmp_path)
    fx["out"] = tmp_path / "archive" / "src-adhoc"
    fx["tmp"] = tmp_path
    return fx


def args(fx, *extra):
    return ["--run-id", "src", "--config", str(fx["config"]), "--claude-bin", str(fx["fake"]), *extra]


def calls(fx):
    return [json.loads(ln) for ln in fx["calls"].read_text().splitlines()] if fx["calls"].exists() else []


def events(fx):
    return [json.loads(ln) for ln in (fx["out"] / "log.jsonl").read_text().splitlines()]


def set_rules(fx, rules):
    p = fx["fake"].parent / "claude.json"
    ctl = json.loads(p.read_text())
    ctl["rules"] = rules + ([MAP_RULE] if MAP_RULE not in rules else [])
    p.write_text(json.dumps(ctl))


def test_dry_run_scope_units_prompt_estimate(ah, capsys, monkeypatch):
    monkeypatch.delenv(FX.TOKEN_ENV)
    assert A.main(args(ah, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "3 answers (flow 2, whyhow 1); left out: locate" in out
    assert "skipped (not ok in the source): fx-flo-01__explore__p3: error" in out
    assert "units      7 in 3 answers" in out
    assert "mean $0.050 and 12 s each" in out and "assumed 3-6x: $0.15-$0.30 per answer" in out
    assert "an estimate, not measured" in out and "<set, hidden>" in out and FX.TOKEN not in out
    assert "--tools Read,Grep,Glob" in out and "--add-dir" not in out
    assert "[s3] `compute` calls `helper`, then `finish`, which triples the value." in out
    assert not ah["calls"].exists() and not ah["out"].exists()
    assert A.main(args(ah, "--dry-run", "--types", "locate")) == 0
    assert "1 answers (locate 1)" in capsys.readouterr().out


def test_end_to_end_isolation_archive_and_capture(ah, capsys):
    assert A.main(args(ah)) == 0
    out = capsys.readouterr().out
    assert "3 of 3 answers checked; ok 3" in out
    seen = calls(ah)
    assert len(seen) == 3
    for c in seen:
        a = c["argv"]
        assert a[a.index("--tools") + 1] == "Read,Grep,Glob" and not any("Bash" in x for x in a)
        assert "--add-dir" not in a and c["cond"] == "explore"
        assert set(c["env"]) <= ALLOWED_ENV and c["token_present"] and c["path"] == "/usr/bin:/bin:/usr/sbin:/sbin"
        assert c["cwd"].startswith(str(ah["tmp"] / "scratch")) and c["cwd"].endswith("/work")
        assert "pkg/core.py" in c["files"] and not any(Path(f).name in W.AGENT_NAMES for f in c["files"])
    assert len({c["cwd"] for c in seen}) == 3                         # a fresh copy per check
    assert list((ah["tmp"] / "scratch").iterdir()) == []              # scratch roots removed
    assert FX.files_containing(ah["tmp"], FX.TOKEN) == []
    assert (ah["src"] / "runs").exists() and not (ah["src"] / "adhoc").exists()
    d = ah["out"] / "runs" / "fx-flo-01__explore__p1"
    for f in ("prompt.txt", "command.txt", "transcript.jsonl", "result.json", "meta.json"):
        assert (d / f).exists(), f
    meta = json.loads((d / "meta.json").read_text())
    assert meta["counts"] == {"supported": 0, "not_supported": 0, "wrong": 2, "not_a_claim": 1, "no verdict": 0}
    assert meta["usage"]["cost_usd"] > 0 and meta["problems"] == []
    assert "<set, hidden>" in (d / "command.txt").read_text()
    plan = json.loads((ah["out"] / "plan.json").read_text())
    assert [i["id"] for i in plan["items"]] == ["fx-flo-01__explore__p1", "fx-flo-01__explore__p2",
                                                "fx-why-01__explore__p1"]
    # the capture
    rt = ah["tmp"] / "runs.txt"
    rt.write_text(MAP_TXT)
    assert A.main(args(ah, "--capture", "--runs-txt", str(rt))) == 0
    cap = capsys.readouterr().out
    assert all(len(ln) <= R.WIDTH and ln == ln.rstrip() for ln in cap.splitlines())
    flat = [" ".join(ln.split()) for ln in cap.splitlines()]
    # units, claims, supported, not supported, wrong, not a claim
    assert "all 7 5 2 1 2 2" in flat and "flow 5 3 1 0 2 2" in flat and "why/how 2 2 1 1 0 0" in flat
    assert "all 5 0 0.400 0.200 0.400 0.600" in flat                   # shares of claims (no verdict 0)
    assert "ad-hoc answers 7 5 2 1 2 0 0.600" in flat and "map claims not run yet" in flat
    assert "fx-flo-01 flow 5 3 1 0 2 0.333" in flat
    assert "[WRONG] fx-flo-01__explore__p1#s3" in cap and "[not supp.] fx-why-01__explore__p1#s1" in cap
    joined = " ".join(cap.split())
    assert 'faulted only for a line reference (the note starts "line reference:"): 1 of the 3 units' in joined
    assert "ranges cited 4; ranges that don't exist at the commit 2 (lines out of range 1, no such file 1)" in joined
    assert "verdicts citing at least one range that doesn't exist: 2 (supported 1, wrong 1)" in joined
    assert "fx run 2 before repair 260 158 102 0.392 before" in flat
    assert "fx run 2 after re-check 260 256 4 0.015 mixed" in flat and "fx before repair 117 78 39 0.333 with" in flat
    assert "fx 117 of 260 claims judged under the rule, 143 before it" in joined
    assert "live answer q1 (fx, Honeyguide's own answer): 13 claims" in joined
    assert "spot check for Han: 7 units" in cap and "pkg/core.py#L23-L24" in cap
    assert A.main(args(ah, "--capture", "--runs-txt", str(ah["tmp"] / "none.txt"))) == 0
    assert "see runs.txt" in capsys.readouterr().out
    assert A.main(args(ah, "--spot-check")) == 0
    md = (ah["out"] / "spot_check.md").read_text()
    assert f"https://example.invalid/fx/blob/{ah['commit']}/pkg/core.py#L23-L24" in md


def test_resume_after_interruption_and_usage_limit(ah, capsys):
    rules = check_rules()
    rules[2] = {**rules[2], "behavior": "usage_limit_once"}
    set_rules(ah, rules)
    assert A.main(args(ah)) == 3
    out = capsys.readouterr().out
    assert "stopped: usage limit hit at fx-why-01__explore__p1" in out
    assert "resume with: uv run python eval/adhoc/adhoc.py --run-id src" in out
    n = len(calls(ah))
    # the seeded run order puts the why check second: the stop leaves the third unstarted
    assert json.loads((ah["out"] / "plan.json").read_text())["run_order"] == [
        "fx-flo-01__explore__p1", "fx-why-01__explore__p1", "fx-flo-01__explore__p2"]
    assert n == 2 and not (ah["out"] / "runs" / "fx-flo-01__explore__p2").exists()
    # an interrupted check: started, no meta
    (ah["out"] / "runs" / "fx-flo-01__explore__p1" / "meta.json").unlink()
    assert A.main(args(ah)) == 0
    assert "3 of 3 answers checked; ok 3" in capsys.readouterr().out
    assert len(calls(ah)) == n + 3                                     # the interrupted, the stopped, the unstarted
    ev = [e["event"] for e in events(ah)]
    assert "resume_after_usage_limit" in ev and "restart_after_interruption" in ev and "stop" in ev
    assert (ah["out"] / "attempts" / "fx-why-01__explore__p1" / "1" / "meta.json").exists()
    assert A.main(args(ah)) == 0 and len(calls(ah)) == n + 3           # nothing finished is repeated


def test_cap_stops(ah, capsys):
    # --max-cost: stops starting checks once the archive's spend reaches it
    assert A.main(args(ah, "--max-cost", "0.005")) == 3
    out = capsys.readouterr().out
    assert "stopped: max cost reached" in out and "1 of 3 answers checked" in out
    assert len(calls(ah)) == 1
    # the per-answer cap: a capped check is final and not re-run
    rules = check_rules()
    rules[2] = {**rules[2], "behavior": "capped"}
    set_rules(ah, rules)
    assert A.main(args(ah)) == 0
    meta = json.loads((ah["out"] / "runs" / "fx-why-01__explore__p1" / "meta.json").read_text())
    assert meta["status"] == "capped" and meta["reason"] == "error_max_budget_usd"
    n = len(calls(ah))
    assert A.main(args(ah, "--retry-failed")) == 0 and len(calls(ah)) == n
    capsys.readouterr()
    assert A.main(args(ah, "--capture")) == 0
    assert "gaps        answers: 2 units in checks that returned no verdicts" in capsys.readouterr().out


def test_refuses_changed_plan_and_source_dir(ah, capsys):
    assert A.main(args(ah, "--max-runs", "1")) == 3
    with pytest.raises(SystemExit, match="differs from this one"):
        A.main(args(ah, "--types", "flow"))
    with pytest.raises(SystemExit, match="must be a new folder"):
        A.main(args(ah, "--out-id", "src/sub"))
    shutil.rmtree(ah["out"])


# ------------------------------------------------------------------------------------------------------------
# review of e523906 (moved from tests/review/test_review_adhoc_e1.py)

# 1. A check that leaves units out is partial, never final ok; the shares count its missing units.
def test_partial_check_is_not_final_ok(ah, capsys):
    rules = check_rules()
    # the flow p1 check answers only s1 and s2 of its 3 units (s3, the wrong "triples" unit, is left out)
    rules[0] = {**rules[0], "answer": {"units": rules[0]["answer"]["units"][:2]}}
    set_rules(ah, rules)
    # was 0 ("3 of 3 answers checked"); a partial check is resumable, so the run is not finished: 3
    assert A.main(args(ah)) == 3
    meta = json.loads((ah["out"] / "runs" / "fx-flo-01__explore__p1" / "meta.json").read_text())
    assert meta["problems"] == ["s3: no verdict"]
    assert meta["status"] != "ok", "a check missing a unit's verdict is final ok, so --retry-failed skips it"


def test_shares_of_claims_count_units_without_a_verdict(ah, capsys):
    rules = check_rules()
    rules[0] = {**rules[0], "answer": {"units": rules[0]["answer"]["units"][:2]}}
    set_rules(ah, rules)
    A.main(args(ah))
    capsys.readouterr()
    A.main(args(ah, "--capture", "--runs-txt", str(ah["tmp"] / "none.txt")))
    cap = capsys.readouterr().out
    shares = cap.split("shares of claims", 1)[1].split("faulted only", 1)[0]
    assert "no verdict" in shares or "all 5" in " ".join(shares.split()), shares
    flat = [" ".join(ln.split()) for ln in cap.splitlines()]
    assert "all 4 1 0.500 0.250 0.250 0.500" in flat
    assert "ad-hoc answers 7 4 2 1 1 1 0.500" in flat
    joined = " ".join(cap.split())
    assert "ns + wrong with them counted as not supported 0.600, left out 0.500" in joined


# 2. Ids echoed the way the prompt shows them ("[s1]") or with another case.
def test_parse_verdicts_accepts_ids_as_the_prompt_shows_them():
    res = {"structured_output": {"units": [
        {"id": "[s1]", "verdict": "supported", "note": "", "evidence": []},
        {"id": "S2", "verdict": "wrong", "note": "", "evidence": []},
        {"id": " s3 ", "verdict": "not_a_claim", "note": "", "evidence": []}]}}
    rows, _, problems = A.parse_verdicts(res, UNITS)
    assert [r["verdict"] for r in rows] == ["supported", "wrong", "not_a_claim"], problems
    assert [A.norm_id(x) for x in ("[s1]", "S1", " s1 ", "a#s1", "[ S12 ]")] == ["s1", "s1", "s1", "s1", "s12"]
    dup = {"structured_output": {"units": [{"id": "s1", "verdict": "supported", "note": "", "evidence": []},
                                           {"id": "[S1]", "verdict": "wrong", "note": "", "evidence": []}]}}
    rows, _, problems = A.parse_verdicts(dup, UNITS[:1])
    assert rows[0]["verdict"] is None and problems[0].startswith("s1: repeated with different verdicts")


# 3. The comparison rows say which Checker rule judged them.
def test_map_comparison_says_which_checker_rule_judged_it():
    real = (ROOT / "outputs" / "runs.txt").read_text()
    data = {"plan": {"repo": "nanochat", "run_id": "x", "source_run_id": "s", "commit": "0" * 40,
                     "url": "https://github.com/karpathy/nanochat", "types": ["flow"], "model": "m",
                     "effort": "medium", "answer_cap_usd": 1.5, "seed": 0, "skipped": [], "items": []},
            "metas": {}, "attempts": [], "rows": [], "not_checked": 0}
    cap = R.capture(data, [], real)
    comp = cap.split("for comparison:", 1)[1].split("spot check for Han", 1)[0]
    flat = " ".join(comp.split())
    assert "nanochat after repair round 2 260 260 0 0.000" in flat       # what is printed today
    assert "compute, don't quote" in flat.lower() or "re-check" in flat.lower(), comp
    assert "nanochat after repair round 2 260 260 0 0.000 before" in flat
    assert "nanochat run 2 after re-check 260 256 4 0.015 mixed" in flat
    assert "nanochat before repair 117 78 39 0.333 with" in flat
    assert "Not the main comparison (that is the control above)" in flat


# 4. Splitter: nesting survives a blank line inside a list item (nc-why-05__explore__p2 item 8).
def test_split_keeps_nesting_after_a_blank_line_inside_an_item():
    t = ("8. **Optimizer update.** Schedules are computed from `step`:\n"
         "   - `get_weight_decay`: cosine decay to zero.\n\n"
         "   These values are written into each param group (lines 520-527). Then:\n"
         "   - Without a scaler, it just calls `optimizer.step()`.\n\n"
         "After the list.")
    us = S.split_units("r", t)
    assert [(u.kind, u.level) for u in us] == [("item", 0), ("item", 1), ("para", 1), ("para", 1), ("item", 1),
                                               ("para", 0)], [(u.kind, u.level, u.text) for u in us]


# ------------------------------------------------------------------------------------------------------------
# the control (map claims), the repeat, the trial, follow-ups, cost

def test_allocate_sample_batches_order_pick():
    assert A.allocate({"read_in_source": 166, "docs": 32, "inferred": 11, "asserted_by_test": 6}, 100) == {
        "read_in_source": 77, "docs": 15, "inferred": 5, "asserted_by_test": 3}
    assert A.allocate({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}
    import random
    s1, st = A.stratified_sample(MAP_CLAIMS, 6, random.Random(0))
    s2, _ = A.stratified_sample(MAP_CLAIMS, 6, random.Random(0))
    assert s1 == s2 and len(s1) == 6
    assert st["sampled"] == {"read_in_source": 4, "docs": 1, "inferred": 1}
    assert st["in_map"]["searched_not_found"] == 1 and st["in_map"]["general_knowledge"] == 0
    assert not any(c["evidence"] in A.MAP_EXCLUDE for c in s1)
    assert [len(b) for b in A.batch(list(range(100)), 25)] == [25, 25, 25, 25]
    assert [len(b) for b in A.batch(list(range(7)), 3)] == [4, 3]
    assert sum(A.batch(list(range(7)), 3), []) == list(range(7)) and A.batch([], 3) == []
    ids = [f"a{k}" for k in range(10)]
    assert sorted(A.run_order(ids, 0)) == ids and A.run_order(ids, 0) == A.run_order(ids[::-1], 0)
    assert A.run_order(ids, 0) != ids
    assert A.repeat_pick(ids, 3, 0) == A.repeat_pick(ids, 3, 0) and len(A.repeat_pick(ids, 3, 0)) == 3


def test_bootstrap_diff_and_agreement():
    a = [(1, 4), (2, 4), (0, 4)]
    lo, hi = R.bootstrap_diff(a, [(0, 4), (0, 4)], n_boot=2000, seed=0)
    assert lo <= 0.25 <= hi and lo >= 0 and (lo, hi) == R.bootstrap_diff(a, [(0, 4), (0, 4)], n_boot=2000, seed=0)
    lo, hi = R.bootstrap_diff([(2, 4)], [(1, 4)], n_boot=100)
    assert lo == hi == 0.25
    assert all(x != x for x in R.bootstrap_diff([], a))                  # nan when an arm is empty
    f = [{"unit": "u1", "verdict": "supported"}, {"unit": "u2", "verdict": "wrong"},
         {"unit": "u3", "verdict": None}, {"unit": "u4", "verdict": "not_a_claim"}]
    s = [{"unit": "u1", "verdict": "supported"}, {"unit": "u2", "verdict": "not_supported"},
         {"unit": "u3", "verdict": "wrong"}, {"unit": "u4", "verdict": "not_a_claim"}]
    ag = R.agreement(f, s)
    assert (ag["units"], ag["both"], ag["agree"]) == (4, 3, 2)
    assert ag["confusion"] == {("supported", "supported"): 1, ("wrong", "not_supported"): 1, (None, "wrong"): 1,
                               ("not_a_claim", "not_a_claim"): 1}


def test_brief_is_shared_and_follows_checker_md():
    brief = A.BRIEF.read_text()
    checker = (ROOT / "agents" / "checker.md").read_text()
    assert "**Compute, don't quote.**" in brief and "Worked example: compute, don't quote" in brief
    for line in ("MAX_JOBS = 1536                              # 1536 / 64 = 24 per queue",
                 "    per = -(-MAX_JOBS // workers // 3)         # leave room for retries (was // 2)"):
        assert line in brief and line in checker
    assert "choose the other" not in brief and "The units cite no lines" not in brief
    assert "a summary that only repeats" not in brief and "repeats earlier units: judge it" in " ".join(brief.split())
    assert "When unsure, `not_supported` with a note saying why" in brief
    units = [{"id": "x#s1", "text": "`finish` doubles", "kind": "para", "level": 0}]
    pa, pm = A.check_prompt("c0", "Q?", units, "answers"), A.check_prompt("c0", "Q?", units, "map")
    strip = [A.SOURCE_LINE["answers"], A.SOURCE_LINE["map"], A.CONTEXT["answers"].replace("{question}", "Q?"),
             A.CONTEXT["map"]]
    for x in strip:
        pa, pm = pa.replace(x, ""), pm.replace(x, "")
    assert pa == pm                                                       # the rules are the same text
    assert (HERE_ADHOC / "BRIEF_NOTES.md").exists()


def test_followup_checks_only_missing_units_and_merges(ah, capsys):
    rules = check_rules()
    rules[0] = {**rules[0], "answer": {"units": rules[0]["answer"]["units"][:2]}}
    set_rules(ah, rules)
    assert A.main(args(ah)) == 3
    out = capsys.readouterr().out
    assert "1 partial checks (units without a verdict): 1 get a follow-up" in out
    n = len(calls(ah))
    # the follow-up's prompt holds only s3; the check echoes its id as the prompt shows it
    follow = {"match": "## The units\n\n[s3]", "answer": {"units": [
        {"id": "[S3]", "verdict": "wrong", "note": "finish doubles", "evidence": [_ev("pkg/core.py", 20, 21)]}]}}
    set_rules(ah, [follow] + rules)
    assert A.main(args(ah)) == 0
    assert len(calls(ah)) == n + 1
    d = ah["out"] / "runs" / "fx-flo-01__explore__p1"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["status"] == "ok" and meta["followup_of"] == 1 and meta["units_asked"] == 1
    assert [r["verdict"] for r in meta["verdicts"]] == ["not_a_claim", "wrong", "wrong"]
    assert "[s1]" not in (d / "prompt.txt").read_text() and "[s3]" in (d / "prompt.txt").read_text()
    first = json.loads((ah["out"] / "attempts" / "fx-flo-01__explore__p1" / "1" / "meta.json").read_text())
    assert first["status"] == "partial"
    assert "followup_missing_units" in [e["event"] for e in events(ah)]


def test_partial_stops_after_its_followups(ah, capsys):
    rules = check_rules()
    rules[0] = {**rules[0], "answer": {"units": rules[0]["answer"]["units"][:2]}}
    set_rules(ah, rules)
    assert A.main(args(ah)) == 3
    assert A.main(args(ah)) == 3                       # follow-up 1: s3 still missing
    assert A.main(args(ah)) == 0                       # follow-up 2: still missing; no more follow-ups
    out = capsys.readouterr().out
    assert f"used their {A.MAX_FOLLOWUPS} follow-ups" in out
    n = len(calls(ah))
    assert A.main(args(ah)) == 0 and len(calls(ah)) == n
    meta = json.loads((ah["out"] / "runs" / "fx-flo-01__explore__p1" / "meta.json").read_text())
    assert meta["status"] == "partial" and meta["counts"]["no verdict"] == 1


def test_run_order_is_the_plans_seeded_shuffle(ah, capsys):
    assert A.main(args(ah)) == 0
    plan = json.loads((ah["out"] / "plan.json").read_text())
    assert plan["run_order"] == A.run_order([i["id"] for i in plan["items"]], 0)
    by_sha = {}
    for i in plan["items"]:
        p = (ah["out"] / "runs" / i["id"] / "prompt.txt").read_text()
        by_sha[hashlib.sha256(p.encode()).hexdigest()] = i["id"]
    assert [by_sha[c["prompt_sha"]] for c in calls(ah)] == plan["run_order"]


def test_timeout_keeps_known_cost_and_a_killed_check_counts(ah, capsys):
    cfg_text = ah["config"].read_text().replace("timeout_answer_s = 60", "timeout_answer_s = 2")
    ah["config"].write_text(cfg_text)
    rules = check_rules()
    rules[2] = {**rules[2], "behavior": "hang"}
    set_rules(ah, rules)
    assert A.main(args(ah)) == 0
    capsys.readouterr()
    meta = json.loads((ah["out"] / "runs" / "fx-why-01__explore__p1" / "meta.json").read_text())
    assert meta["status"] == "error" and meta["reason"] == "timeout"
    want = (1000 * 4 + 1000 * 20) / 1e6
    assert meta["usage"]["cost_usd"] == pytest.approx(want) and "rebuilt" in meta["usage"]["cost_source"]
    fake_cost = (10 * 4 + 1000 * 0.2 + 500 * 8 + 100 * 20) / 1e6
    assert A.ER.Archive(ah["out"]).spent() == pytest.approx(2 * fake_cost + want)
    # a check killed with the runner: started, cost_so_far.json, no meta.json
    d = ah["out"] / "runs" / "fx-flo-01__explore__p2"
    (d / "meta.json").unlink()
    (d / A.ER.COST_SO_FAR).write_text(json.dumps({"usage": {"cost_usd": 0.5}}))
    assert A.ER.Archive(ah["out"]).spent() == pytest.approx(fake_cost + want + 0.5)
    assert A.main(args(ah)) == 0                                     # re-run; the killed try kept as attempt
    assert (ah["out"] / "attempts" / "fx-flo-01__explore__p2" / "1" / A.ER.COST_SO_FAR).exists()
    assert A.ER.Archive(ah["out"]).spent() == pytest.approx(2 * fake_cost + want + 0.5)
    capsys.readouterr()
    A.main(args(ah, "--capture", "--runs-txt", str(ah["tmp"] / "none.txt")))
    assert "(earlier attempts $0.50" in " ".join(capsys.readouterr().out.split())


def test_usage_tracker_counts_each_message_once():
    t = A.UsageTracker({"input": 4.0, "cache_read": 0.2, "cache_write_1h": 8.0, "cache_write_5m": 5.0,
                        "output": 20.0})
    ev = {"type": "assistant", "message": {"id": "m1", "model": "x", "usage": {"input_tokens": 100,
                                                                                "output_tokens": 10}}}
    assert t.add(json.dumps(ev)) and t.add(json.dumps(ev))
    ev["message"]["usage"]["output_tokens"] = 50
    t.add(json.dumps(ev))
    assert not t.add("not json") and not t.add(json.dumps({"type": "result"}))
    s = t.summary()
    assert s["tokens"]["input_tokens"] == 100 and s["tokens"]["output_tokens"] == 50 and s["messages"] == 1
    assert s["cost_usd"] == pytest.approx((100 * 4 + 50 * 20) / 1e6) and s["models"] == ["x"]


def test_map_arm_repeat_trial_and_side_by_side_capture(ah, capsys, monkeypatch):
    # the dry run shows both arms and the repeat, and an assumed estimate before any check ran
    monkeypatch.delenv(FX.TOKEN_ENV)
    assert A.main(args(ah, "--dry-run", "--map-n", "6", "--batch-size", "3")) == 0
    out = capsys.readouterr().out
    assert "ARM 1      ad-hoc answers" in out and "ARM 2      map claims (the control)" in out
    assert "sample     6 of 9 eligible claims (seed 0), stratified by evidence label; left out: " \
           "general_knowledge 0, searched_not_found 1" in out
    assert "units      6 claims in 2 checks of about 3" in out and "REPEAT     3 answers re-checked" in out
    assert "an estimate, not measured" in out and "map arm and repeat (13 units)" in out
    assert not (ah["tmp"] / "archive" / "src-adhoc-map").exists()
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    # the trial: one check, then the dry run projects from its measured cost
    assert A.main(args(ah, "--only", "fx-why-01__explore__p1")) == 3
    assert len(calls(ah)) == 1
    capsys.readouterr()
    assert A.main(args(ah, "--dry-run", "--map-n", "6", "--batch-size", "3")) == 0
    out = capsys.readouterr().out
    fake_cost = (10 * 4 + 1000 * 0.2 + 500 * 8 + 100 * 20) / 1e6
    assert "ESTIMATE   measured-based" in out and f"answers: 1 check(s), 2 units, ${fake_cost:.2f}" in out
    assert f"pooled ${fake_cost / 2:.4f}" in out
    assert "answers     7 units,    5 left" in out and "map         6 units,    6 left" in out
    assert "a projection from measured checks, not a result" in out
    with pytest.raises(SystemExit, match="not a check of the answers arm"):
        A.main(args(ah, "--only", "map-b01"))
    # the full runs: answers (skips the trial), the control, the repeat
    assert A.main(args(ah)) == 0 and len(calls(ah)) == 3
    assert A.main(args(ah, "--source", "map", "--map-n", "6", "--batch-size", "3")) == 0
    out = capsys.readouterr().out
    assert "2 of 2 batches checked; ok 2" in out
    mout = ah["tmp"] / "archive" / "src-adhoc-map"
    mplan = json.loads((mout / "plan.json").read_text())
    assert [len(i["units"]) for i in mplan["items"]] == [3, 3] and mplan["arm"] == "map"
    for i in mplan["items"]:
        p = (mout / "runs" / i["id"] / "prompt.txt").read_text()
        assert "ANCHOR-SECRET" not in p and "There is no question." in p and "## The question" not in p
        assert all(u["text"] in p for u in i["units"]) and not any(f"key {u['key']}" in p for u in i["units"])
    assert A.main(args(ah, "--repeat", "1")) == 0
    rplan = json.loads((ah["tmp"] / "archive" / "src-adhoc-repeat" / "plan.json").read_text())
    assert rplan["arm"] == "repeat" and len(rplan["items"]) == 1 and rplan["repeat_of"] == "src-adhoc"
    capsys.readouterr()
    # the capture: the two arms side by side, the CI, the repeat's agreement
    rt = ah["tmp"] / "runs.txt"
    rt.write_text(MAP_TXT)
    assert A.main(args(ah, "--capture", "--runs-txt", str(rt))) == 0
    cap = capsys.readouterr().out
    assert all(len(ln) <= R.WIDTH and ln == ln.rstrip() for ln in cap.splitlines())
    flat = [" ".join(ln.split()) for ln in cap.splitlines()]
    joined = " ".join(cap.split())
    assert "ad-hoc answers 7 5 2 1 2 0 0.600" in flat and "map claims 6 6 2 2 2 0 0.667" in flat
    assert "difference in ns+w, ad-hoc minus map: -0.067, 95% CI [" in joined
    assert "(3 answers), map claims resampled one by one (" in joined and "seed 0" in joined
    assert "never checked (the eval map was never Checker-passed)" in joined
    assert "both judged by the same Checker" in joined
    rid = rplan["items"][0]["id"]
    nu = len(rplan["items"][0]["units"])
    assert f"per-unit agreement: {nu} of the {nu} units with a verdict in both passes (1.000)" in joined
    assert "first \\ repeat" in cap
    assert "read_in_source" in cap and "spot check for Han, map claims: 6 units" in cap
    assert f"answers: {rid}" in joined
    assert A.main(args(ah, "--spot-check")) == 0
    md = (ah["out"] / "spot_check.md").read_text()
    assert "## map claims (the control): 6 units" in md and "Evidence label" in md


def test_review_block_names_the_reviewer_and_counts_from_rows():
    import adhoc_report as R
    rev = {"reviewer": "GPT-6", "how": "from the sheet only", "items": [
        {"n": 1, "verdict": "supported", "review": "agree"},
        {"n": 2, "verdict": "wrong", "review": "change", "note": "minor"},
        {"n": 3, "verdict": "not_supported", "review": "borderline", "note": "inference"}]}
    out = "\n".join(R.review_block(rev))
    assert "reviewer: GPT-6; from the sheet only" in out
    assert "items 3; agree 1, would change 1, borderline 1" in out
    assert "#2 wrong (change): minor" in out
    assert all(len(x) <= 74 for x in out.splitlines())
    assert "not recorded (no spot_check_review.json)" in "\n".join(R.review_block(None))


def test_review_block_splits_the_counts_by_arm():
    """ff73b70f0 (review round 3): the 'supported' items came from both arms; the block says how many from each."""
    import adhoc_report as R
    rev = {"reviewer": "GPT-6", "how": "sheet", "items": [
        {"n": 1, "unit": "a#s1", "verdict": "supported", "review": "agree"},
        {"n": 2, "unit": "a#s2", "verdict": "not_supported", "review": "borderline", "note": "x"},
        {"n": 3, "unit": "map-b01#s1", "verdict": "supported", "review": "agree"},
        {"n": 4, "unit": "map-b01#s2", "verdict": "supported", "review": "agree"},
        {"n": 5, "unit": "lost#s1", "verdict": "wrong", "review": "agree"}]}
    arms = {"a#s1": "ad-hoc answers", "a#s2": "ad-hoc answers", "map-b01#s1": "map claims",
            "map-b01#s2": "map claims"}
    out = R.review_block(rev, arms)
    assert "  ad-hoc answers  supported            1      1       0           0" in out
    assert "  ad-hoc answers  not_supported        1      0       0           1" in out
    assert "  map claims      supported            2      2       0           0" in out
    assert "  not recorded    wrong                1      1       0           0" in out
    assert all(len(x) <= 74 for x in out)
    assert not any(x.startswith("  by arm") for x in R.review_block(rev))     # no arms: the old block


def test_review_arms_are_the_spot_check_samples():
    import adhoc_report as R
    rows = [{"unit": f"u{i}", "verdict": v} for i, v in enumerate(["supported", "wrong", "not_supported"] * 3)]
    mrows = [{"unit": f"m{i}", "verdict": "supported"} for i in range(12)]
    data, mdata = {"plan": {"seed": 7}, "rows": rows}, {"rows": mrows}
    arms = R.review_arms(data, mdata)
    assert {u for u, a in arms.items() if a == "ad-hoc answers"} == {r["unit"] for r in R.sample(rows, 7)}
    assert {u for u, a in arms.items() if a == "map claims"} == {r["unit"] for r in R.sample(mrows, 7, R.MAP_SAMPLE)}

"""eval/adhoc (E1): the splitter, the check's isolation, resume, stops, the evidence pass and the capture, with a
fake `claude` (no model call anywhere) and a synthetic source archive built on the eval fixture's tiny repo.
"""

from __future__ import annotations

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
    assert [r["verdict"] for r in rows] == ["supported", None, None]
    assert rows[0]["evidence"] == [{"path": "pkg/core.py", "start": 1, "end": 2},
                                   {"path": "scripts/main.py", "start": 3, "end": 3}]
    assert problems == ["s1: repeated (first kept)", "entry 2: unknown id 's9'", "entry 3: malformed",
                        "s2: no verdict", "s3: no verdict"]
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

recheck
--------------------------------------------------------------------------
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
    real = ROOT / "outputs" / "runs.txt"
    if real.exists():
        rows = R.parse_map_checker(real.read_text())
        assert {(r["repo"], r["stage"]) for r in rows} >= {("nanochat", "run 2 before repair"),
                                                           ("waku-agent", "run 2 before repair")}


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
    (src / "plan.json").write_text(json.dumps({"run_id": "src", "repo": "fx", "commit": fx["commit"],
                                               "url": FX.frozen(fx["commit"])["url"], "questions": qs,
                                               "items": items}))
    return src


@pytest.fixture
def ah(tmp_path, monkeypatch):
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    fx = FX.make(tmp_path)
    FX.write_fake(tmp_path / "bin", {"rules": check_rules(), "map_output": FX.MAP_OUTPUT})
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
    ctl["rules"] = rules
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
    assert "all 5 0.400 0.200 0.400 0.600" in flat                     # shares of claims
    assert "fx-flo-01 flow 5 3 1 0 2 0.333" in flat
    assert "[WRONG] fx-flo-01__explore__p1#s3" in cap and "[not supp.] fx-why-01__explore__p1#s1" in cap
    joined = " ".join(cap.split())
    assert 'faulted only for a line reference (the note starts "line reference:"): 1 of the 3 units' in joined
    assert "ranges cited 4; ranges that don't exist at the commit 2 (lines out of range 1, no such file 1)" in joined
    assert "verdicts citing at least one range that doesn't exist: 2 (supported 1, wrong 1)" in joined
    assert "fx run 2 before repair 260 158 102 0.392" in flat
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
    assert n == 3
    # an interrupted check: started, no meta
    (ah["out"] / "runs" / "fx-flo-01__explore__p2" / "meta.json").unlink()
    assert A.main(args(ah)) == 0
    assert "3 of 3 answers checked; ok 3" in capsys.readouterr().out
    assert len(calls(ah)) == n + 2                                     # only those two ran again
    ev = [e["event"] for e in events(ah)]
    assert "resume_after_usage_limit" in ev and "restart_after_interruption" in ev and "stop" in ev
    assert (ah["out"] / "attempts" / "fx-why-01__explore__p1" / "1" / "meta.json").exists()
    assert A.main(args(ah)) == 0 and len(calls(ah)) == n + 2           # nothing finished is repeated


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
    assert "gaps        2 units in checks that did not finish ok" in capsys.readouterr().out


def test_refuses_changed_plan_and_source_dir(ah, capsys):
    assert A.main(args(ah, "--max-runs", "1")) == 3
    with pytest.raises(SystemExit, match="differs from this one"):
        A.main(args(ah, "--types", "flow"))
    with pytest.raises(SystemExit, match="must be a new folder"):
        A.main(args(ah, "--out-id", "src/sub"))
    shutil.rmtree(ah["out"])

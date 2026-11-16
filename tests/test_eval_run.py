"""eval/run: plan, isolation, run, resume, retry, stops, with a fake `claude` (no model call anywhere).

- the plan's run count and order; the dry run prints every command, runs nothing and reads no token;
- every command line carries the isolation flags; explore / outline / map differ only in the prompt; no-access
  has no tools and an empty dir; the repo's agent files are gone from every working dir;
- the run stops at a usage limit and resumes; failed runs stay failed until --retry-failed (earlier attempt
  kept); an interrupted run is restarted and logged; --max-runs and --max-cost stop cleanly;
- the token never reaches a file (the whole tmp tree is searched), even when the child prints it;
- the eval map is used only if it passes the check; a failing map gets up to map_fix_rounds isolated fix rounds
  (errors verbatim, previous map through --add-dir, the rest of the map cap), each archived and costed;
- pure helpers: outline size matching, status classification, answer parsing, list-price rebuild.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_fixture as FX  # noqa: E402
import evalcfg as C  # noqa: E402
import evalrun  # noqa: E402
import maprender as M  # noqa: E402
import outline_build as OB  # noqa: E402
import runplan as P  # noqa: E402
import runresult as RR  # noqa: E402
import workdirs as W  # noqa: E402

ISOLATION = ("--setting-sources", "--restricted", "--strict-mcp-config", "--no-session-persistence",
             "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--tools", "--json-schema",
             "--max-budget-usd", "--effort", "--model")
ALLOWED_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_OAUTH_TOKEN",
               "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER", "HOME", "LANG", "PATH", "TERM", "TMPDIR",
               "__CF_USER_TEXT_ENCODING"}   # the last one is added by macOS to every process


@pytest.fixture
def fx(tmp_path, monkeypatch):
    monkeypatch.setenv(FX.TOKEN_ENV, FX.TOKEN)
    return FX.make(tmp_path)


def args(fx, *extra):
    return ["--repo", "fx", "--size", "tiny", "--config", str(fx["config"]), "--claude-bin", str(fx["fake"]),
            *extra]


def calls(fx):
    return [json.loads(ln) for ln in fx["calls"].read_text().splitlines()] if fx["calls"].exists() else []


def events(fx, run_id):
    return [json.loads(ln) for ln in (fx["archive"] / run_id / "log.jsonl").read_text().splitlines()]


# ------------------------------------------------------------------------------------------------------------
# plan

def test_plan_counts_and_order(fx):
    cfg = C.load_config(fx["config"])
    qs = C.select_questions(cfg, "fx", "tiny")
    assert [q.type for q in qs] == ["locate", "callers", "flow", "whyhow"]
    items = P.build_items(cfg, "fx", "tiny", qs)
    n = P.counts(items)
    assert n == {"map builds": 1, "no-access": 4, "explore": 8, "outline": 8, "map": 12, "answer runs": 32,
                 "total": 33}
    assert items[0].kind == "map" and all(i.kind == "answer" for i in items[1:])
    assert len({i.id for i in items}) == len(items)
    assert P.build_items(cfg, "fx", "tiny", qs) == items          # the shuffle is seeded
    assert {i.map_seed for i in items if i.condition == "map"} == {1}


def test_real_pilot_plan_is_160_answer_runs_plus_one_map():
    cfg = C.load_config()
    qs = C.select_questions(cfg, "nanochat", "pilot")
    n = P.counts(P.build_items(cfg, "nanochat", "pilot", qs))
    assert len(qs) == 20 and n["answer runs"] == 160 and n["map builds"] == 1 and n["total"] == 161
    full = P.counts(P.build_items(cfg, "nanochat", "full", C.select_questions(cfg, "nanochat", "full")))
    assert full["map builds"] == 3 and full["map"] == 3 * full["no-access"]


def test_map_seed_rotation():
    assert [C.map_seed_for_pass(k, 3) for k in (1, 2, 3)] == [1, 2, 3]
    assert [C.map_seed_for_pass(k, 1) for k in (1, 2, 3)] == [1, 1, 1]


def test_dry_run_runs_nothing_and_reads_no_token(fx, capsys, monkeypatch):
    monkeypatch.delenv(FX.TOKEN_ENV)      # a token read would fail loudly
    assert evalrun.main(args(fx, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "1 no-access + 2 explore + 2 outline + 3 map = 8" in out and "= 33 runs" in out
    assert not fx["calls"].exists() and not fx["archive"].exists()
    assert out.count("argv: ") == 34 and "<set, hidden>" in out and FX.TOKEN not in out    # + the fix-round shape
    assert "map fix    up to 2 fix round(s) per build" in out and "--add-dir" in out
    for flag in ISOLATION:
        assert flag in out
    assert "ESTIMATE" in out and "not measured" in out


# ------------------------------------------------------------------------------------------------------------
# isolation on the command lines the fake saw

def test_isolation_flags_env_and_workdirs(fx):
    evalrun.main(args(fx, "--run-id", "r"))
    evalrun.main(args(fx, "--run-id", "r"))
    seen = calls(fx)
    assert len(seen) == 34     # 33 runs, one of them twice (stopped by the usage limit, then resumed)
    for c in seen:
        for flag in ISOLATION:
            assert flag in c["argv"], (flag, c["cond"])
        assert c["argv"][c["argv"].index("--setting-sources") + 1] == ""
        assert "--add-dir" not in c["argv"] and "--fallback-model" not in c["argv"]
        assert c["argv"][c["argv"].index("--model") + 1] == "claude-opus-5-5"
        assert set(c["env"]) <= ALLOWED_ENV and c["token_present"]
        assert c["path"] == "/usr/bin:/bin:/usr/sbin:/sbin"
        assert c["home"].startswith(str(fx["archive"].parent / "scratch"))
        assert not any(Path(f).name in W.AGENT_NAMES for f in c["files"])
        if c["cond"] == "no-access":
            assert c["files"] == [] and c["argv"][c["argv"].index("--tools") + 1] == ""
        else:
            assert "pkg/core.py" in c["files"] and c["argv"][c["argv"].index("--tools") + 1] == "Read,Grep,Glob"
    # explore, outline and map: the same command line apart from the prompt
    by = {}
    for c in seen:
        if c["cond"] in ("explore", "outline", "map"):
            by.setdefault(c["cond"], set()).add(json.dumps(c["argv"]))
    assert len(by) == 3 and len(set.union(*by.values())) == 1
    # the scratch roots are gone
    assert list((fx["archive"].parent / "scratch").iterdir()) == []


def test_workdir_refuses_leftover_agent_files(tmp_path, fx):
    with pytest.raises(RuntimeError, match="agent files remain"):
        W.make_repo_workdir(fx["clone"], fx["commit"], ["CLAUDE.md"], tmp_path / "w")
    info = W.make_repo_workdir(fx["clone"], fx["commit"], ["CLAUDE.md", "AGENTS.md", ".claude"], tmp_path / "w2")
    assert sorted(info["removed"]) == [".claude", "AGENTS.md", "CLAUDE.md"]
    assert not (tmp_path / "w2" / ".git").exists() and (tmp_path / "w2" / "pkg" / "core.py").exists()


def test_extra_text_never_in_workdir(fx):
    evalrun.main(args(fx, "--run-id", "r"))
    for c in calls(fx):
        assert not any(f.endswith((".md",)) and f != "README.md" for f in c["files"])


# ------------------------------------------------------------------------------------------------------------
# run, stop, resume, retry

def test_usage_limit_stops_and_resume_finishes(fx, capsys):
    assert evalrun.main(args(fx, "--run-id", "r")) == 3
    out = capsys.readouterr().out
    assert "stopped: usage limit hit at fx-cal-01__no-access__p1" in out
    assert "resume with: uv run python eval/run/evalrun.py --repo fx --size tiny --run-id r" in out
    n_first = len(calls(fx))
    assert evalrun.main(args(fx, "--run-id", "r")) == 0
    out = capsys.readouterr().out
    assert "33 of 33 runs finished" in out and "failed runs stay failed" in out
    ev = [e["event"] for e in events(fx, "r")]
    assert "resume_after_usage_limit" in ev and "stop" in ev
    # only the stopped run and those never started ran again; no finished run was repeated
    ran = [c["prompt_sha"] for c in calls(fx)]
    assert len(ran) - n_first == 33 - (n_first - 1)
    assert (fx["archive"] / "r" / "attempts" / "fx-cal-01__no-access__p1" / "1" / "meta.json").exists()


def test_failed_runs_stay_failed_until_retry(fx, capsys):
    evalrun.main(args(fx, "--run-id", "r"))
    evalrun.main(args(fx, "--run-id", "r"))
    n = len(calls(fx))
    assert evalrun.main(args(fx, "--run-id", "r")) == 0
    assert len(calls(fx)) == n                      # nothing re-run silently
    meta = json.loads((fx["archive"] / "r" / "runs" / "fx-flo-01__no-access__p1" / "meta.json").read_text())
    assert meta["status"] == "error"
    # the cause is fixed; --retry-failed re-runs the errors only (not capped, not invalid answers)
    control = json.loads((fx["fake"].parent / "claude.json").read_text())
    control["rules"] = [r for r in control["rules"] if r.get("behavior") != "error"]
    (fx["fake"].parent / "claude.json").write_text(json.dumps(control))
    capsys.readouterr()
    evalrun.main(args(fx, "--run-id", "r", "--retry-failed"))
    retried = [e for e in events(fx, "r") if e["event"] == "retry_failed"]
    assert {e["id"] for e in retried} == {"fx-flo-01__no-access__p1", "fx-why-01__explore__p1",
                                          "fx-why-01__explore__p2"}
    assert len(calls(fx)) == n + 3
    meta = json.loads((fx["archive"] / "r" / "runs" / "fx-flo-01__no-access__p1" / "meta.json").read_text())
    assert meta["status"] == "ok"
    old = fx["archive"] / "r" / "attempts" / "fx-flo-01__no-access__p1" / "1" / "meta.json"
    assert json.loads(old.read_text())["status"] == "error"


def test_interrupted_run_is_restarted_and_logged(fx):
    evalrun.main(args(fx, "--run-id", "r"))
    evalrun.main(args(fx, "--run-id", "r"))
    d = fx["archive"] / "r" / "runs" / "fx-loc-01__map__p1"
    (d / "meta.json").unlink()                       # as if killed after it started
    n = len(calls(fx))
    assert evalrun.main(args(fx, "--run-id", "r")) == 0
    assert len(calls(fx)) == n + 1
    assert any(e["event"] == "restart_after_interruption" and e["id"] == "fx-loc-01__map__p1"
               for e in events(fx, "r"))


def test_max_runs_and_max_cost_stop_cleanly(fx, capsys):
    assert evalrun.main(args(fx, "--run-id", "a", "--max-runs", "2")) == 3
    assert "max runs reached" in capsys.readouterr().out and len(calls(fx)) == 2
    assert evalrun.main(args(fx, "--run-id", "b", "--max-cost", "0.02")) == 3
    out = capsys.readouterr().out
    assert "max cost reached" in out
    spent = evalrun.Archive(fx["archive"] / "b").spent()
    assert 0.02 <= spent < 0.02 + 0.01        # stops at the first run that crosses the cap


def test_changed_config_refuses_resume(fx):
    evalrun.main(args(fx, "--run-id", "r", "--max-runs", "1"))
    fx["config"].write_text(fx["config"].read_text().replace('effort = "low"', 'effort = "high"'))
    with pytest.raises(SystemExit, match="differs"):
        evalrun.main(args(fx, "--run-id", "r"))


def test_token_never_on_disk(fx, tmp_path):
    evalrun.main(args(fx, "--run-id", "r"))
    evalrun.main(args(fx, "--run-id", "r"))
    # the child printed the token (echo_token rule): the run is an error and its output is withheld
    meta = json.loads((fx["archive"] / "r" / "runs" / "fx-why-01__explore__p1" / "meta.json").read_text())
    assert meta["status"] == "error" and "token" in meta["reason"]
    assert FX.files_containing(tmp_path, FX.TOKEN) == []


def test_map_build_validated_and_rendered(fx):
    evalrun.main(args(fx, "--run-id", "r"))
    md = fx["archive"] / "r" / "maps" / "seed1"
    v = json.loads((md / "validation.json").read_text())
    # the one unresolved anchor makes draft_valid false but does not refuse the map (measured, not fixed)
    assert v["anchors_total"] == 4 and v["anchors_resolved"] == 3 and not v["draft_valid"]
    assert v["usable"] and v["blocking_errors"] == [] and v["structure_errors"] == []
    assert v["unresolved"][0]["claim"] == "c3"
    text = (md / "map.md").read_text()
    assert "[pkg/core.py:" in text and "[scripts/main.py: quote not found]" in text
    o = json.loads((fx["archive"] / "r" / "outline" / "outline.json").read_text())
    assert o["target_tokens"] == v["tokens_est"]
    meta = json.loads((fx["archive"] / "r" / "runs" / "map-s1" / "meta.json").read_text())
    assert meta["status"] == "ok" and meta["models_used"] == ["claude-opus-5-5"]
    assert meta["agent_files_removed"] == ["CLAUDE.md", "AGENTS.md", ".claude"]
    # (c) a map that passes on the first try runs no fix round
    assert meta["fix_rounds"] == [] and meta["totals"]["fix_rounds"] == 0
    assert meta["usage"]["cost_usd"] == meta["build_usage"]["cost_usd"]
    assert not (fx["archive"] / "r" / "runs" / "map-s1" / "fix").exists()
    assert not any(c["cond"] == "mapfix" for c in calls(fx))
    assert not any(e["event"] == "map_fix" for e in events(fx, "r"))


def test_map_prompt_is_the_cartographer_brief_in_eval_mode(tmp_path):
    p = P.map_prompt(tmp_path / "work")
    assert p.startswith("MODE: explore\nREPO: " + str(tmp_path / "work"))
    assert "## Eval mode (no Bash tool)" in p and "name: cartographer" not in p


def test_answer_prompt_same_brief_for_all_conditions():
    fz = {"url": "u", "commit": "c" * 40}
    a = P.answer_prompt(fz, "r", "Q?", None)
    b = P.answer_prompt(fz, "r", "Q?", "# Map\nx")
    c = P.answer_prompt(fz, "r", "Q?", "# Outline of r\ny")
    for t in (b, c):
        assert P.NOTES_HEAD in t and t.endswith("Question: Q?\n")
    assert b.split(P.NOTES_HEAD)[0] == c.split(P.NOTES_HEAD)[0] == a.split("\nQuestion:")[0] + "\n"
    assert "{" + "notes}" not in a


# ------------------------------------------------------------------------------------------------------------
# pure helpers

SRC = {"a/x.py": 'import os\n\n\ndef f(a, b=1):\n    """Do f.\n\n    More."""\n    return a\n\n\nclass K(Base):\n'
                 '    """A K."""\n    N = 3\n\n    def m(self) -> int:\n        def inner():\n            return 1\n'
                 '        return inner()\n',
       "a/y.py": "def g():\n    pass\n"}


def test_outline_levels_and_size_match():
    lv = [OB.file_outline("a/x.py", SRC["a/x.py"], k) for k in range(OB.LEVELS)]
    assert "def f  L4" in lv[0] and "def f(a, b=1)  L4" in lv[1] and "imports: os" in lv[2]
    assert "# Do f." in lv[3] and "# More." not in lv[3] and "# More." in lv[4]
    assert "N = 3  L13" in lv[5] and "def inner()" in lv[5] and "def inner" not in lv[4]
    sizes = [OB.est_tokens(OB.build_outline("r", "c" * 40, SRC, t).text) for t in (90, 130, 200, 10000)]
    for t, s in zip((90, 130, 200), sizes[:3], strict=True):
        assert s <= t
    big = OB.build_outline("r", "c" * 40, SRC, 10000)
    assert set(big.levels.values()) == {OB.LEVELS - 1} and big.left_out == 0
    tiny = OB.build_outline("r", "c" * 40, SRC, 5)
    assert tiny.left_out == 2 and "2 more files left out" in tiny.text
    assert OB.build_outline("r", "c" * 40, SRC, 80).text == OB.build_outline("r", "c" * 40, SRC, 80).text


def test_classify_statuses():
    ok = {"subtype": "success", "is_error": False}
    assert RR.classify(0, ok, "", True) == ("ok", "")
    assert RR.classify(0, ok, "", False)[0] == "invalid_answer"
    assert RR.classify(1, {"subtype": "error_max_budget_usd", "is_error": True}, "", False)[0] == "capped"
    assert RR.classify(1, {"subtype": "error_max_turns", "is_error": True}, "", False)[0] == "capped"
    assert RR.classify(1, None, "boom", False) == ("error", "no result event (exit 1)")
    assert RR.classify(None, None, "", False, timed_out=True) == ("error", "timeout")
    lim = {"subtype": "success", "is_error": True, "result": "Claude AI usage limit reached|1794777040"}
    assert RR.classify(1, lim, "", False)[0] == "usage_limit"
    assert RR.classify(1, {"is_error": True, "api_error_status": 429}, "", False)[0] == "usage_limit"
    assert RR.classify(1, None, "Error: 5-hour limit reached, resets at 3pm", False)[0] == "usage_limit"
    assert RR.classify(0, ok, "warning: rate limit, retrying", True)[0] == "ok"   # a finished run is not stopped


def test_parse_answer():
    a, how = RR.parse_answer({"structured_output": {"items": [{"file": "a.py", "symbol": "f", "line": 3},
                                                              {"file": 1}], "text": "t"}})
    assert how == "structured_output" and a == {"items": [{"file": "a.py", "symbol": "f", "line": 3}], "text": "t"}
    a, how = RR.parse_answer({"result": '```json\n{"items": [], "text": "x"}\n```'})
    assert how == "result text" and a == {"items": [], "text": "x"}
    assert RR.parse_answer({"result": "train.py"})[0] is None
    assert RR.parse_answer({"result": '{"text": "no items"}'})[0] is None


def test_price_table_rebuilds_the_t2_pilot_costs():
    """outputs/pilot_isolation.txt r01 and r06: in 2/4, cache read 3001/4386, 1h write 1117/4524, out 4/214."""
    cfg = C.load_config()
    prices = cfg["prices"][cfg["model"]]
    for (i, cr, w, o, cost) in ((2, 3001, 1117, 4, 0.0096242), (4, 4386, 4524, 214, 0.0413652)):
        s = {"tokens": {"input_tokens": i, "cache_read_input_tokens": cr, "cache_creation_input_tokens": w,
                        "output_tokens": o}, "cache_write_1h": w, "cache_write_5m": 0}
        n = RR.notional_cost(s, prices)
        assert n["rebuilt_with_cache"] == pytest.approx(cost, rel=1e-9)
        assert n["without_cache"] == pytest.approx((i + cr + w) * 4e-6 + o * 20e-6)


def test_parse_stream_counts_tools_and_keeps_last_result():
    lines = [json.dumps({"type": "system", "subtype": "init", "model": "m"}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"},
                                                                     {"type": "text", "text": "x"}]}}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Grep"},
                                                                     {"type": "tool_use", "name": "Read"}]}}),
             "not json", json.dumps({"type": "result", "result_index": 0}),
             json.dumps({"type": "result", "result_index": 1})]
    p = RR.parse_stream("\n".join(lines))
    assert p["tool_calls"] == 3 and p["tool_names"] == {"Grep": 1, "Read": 2}
    assert p["init"]["model"] == "m" and p["result"]["result_index"] == 1


def test_extract_map_json():
    assert M.extract_json({"structured_output": {"document": {}}}) == ({"document": {}}, "structured_output")
    assert M.extract_json({"result": '```json\n{"a": 1}\n```'}) == ({"a": 1}, "result text")
    assert M.extract_json({"result": "no"})[0] is None
    assert M.extract_json({})[0] is None


def test_block_pieces_follow_mapdoc_segment_order():
    from honeyguide.mapdoc import block_segments
    block = {"id": "m", "type": "module", "spans": [{"text": "s"}], "design": [{"text": "d"}],
             "facts": [{"key": "io", "spans": [{"text": "f"}]}]}
    pieces = M.block_pieces(block)
    assert [p[1] for p in pieces] == block_segments(block)
    assert [p[0] for p in pieces] == ["", "Design: ", "- io: "]


def test_unusable_map_blocks_map_and_outline_runs_until_retried(fx, capsys):
    ctl = fx["fake"].parent / "claude.json"
    control = json.loads(ctl.read_text())
    ctl.write_text(json.dumps(dict(control, map_behavior="bad_json")))
    assert evalrun.main(args(fx, "--run-id", "r")) == 3
    evalrun.main(args(fx, "--run-id", "r"))            # usage-limit resume
    out = capsys.readouterr().out
    assert "blocked: 20 runs need a usable map" in out
    assert {c["cond"] for c in calls(fx)} == {"mapbuild", "explore", "no-access"}
    n = len(calls(fx))
    assert evalrun.main(args(fx, "--run-id", "r")) == 3 and len(calls(fx)) == n    # still blocked, nothing re-run
    ctl.write_text(json.dumps(control))
    assert evalrun.main(args(fx, "--run-id", "r", "--retry-failed")) == 0
    assert any(e["event"] == "retry_failed" and e["id"] == "map-s1" for e in events(fx, "r"))
    assert {c["cond"] for c in calls(fx)[n:]} >= {"mapbuild", "map", "outline"}


# ------------------------------------------------------------------------------------------------------------
# the map check and its fix rounds

FAKE_COST = (10 * 4 + 1000 * 0.2 + 500 * 8 + 100 * 20) / 1e6      # what fake_claude reports per call


def set_control(fx, **kw):
    ctl = fx["fake"].parent / "claude.json"
    control = json.loads(ctl.read_text())
    ctl.write_text(json.dumps(dict(control, **kw)))


def run_to_end(fx, run_id="r"):
    evalrun.main(args(fx, "--run-id", run_id))
    return evalrun.main(args(fx, "--run-id", run_id))       # resume after the fixture's usage-limit stop


def test_map_missing_flows_is_refused_then_fixed(fx, capsys, tmp_path):
    """(a) the pilot's failure: no document.flows. The map is refused, one fix round returns a valid map, the map
    is used, and the round is archived and costed."""
    bad = FX.map_without_flows()
    set_control(fx, map_output=bad, fix_outputs=[FX.MAP_OUTPUT])
    assert run_to_end(fx) == 0
    run = fx["archive"] / "r" / "runs" / "map-s1"
    build_v = json.loads((run / "validation.json").read_text())
    err = "sections[1].blocks[0]: flow 'run' is not in document.flows"
    assert not build_v["usable"] and build_v["blocking_errors"] == [err]
    fixes = [c for c in calls(fx) if c["cond"] == "mapfix"]
    assert len(fixes) == 1
    f = fixes[0]
    # isolated like the build: same flags, tools, model; a fresh repo copy; the previous map through --add-dir only
    for flag in ISOLATION:
        assert flag in f["argv"]
    assert f["argv"][f["argv"].index("--tools") + 1] == "Read,Grep,Glob"
    assert f["argv"][f["argv"].index("--model") + 1] == "claude-opus-5-5"
    assert f["argv"][f["argv"].index("--max-budget-usd") + 1] == f"{P.fix_budget(20.0, FAKE_COST):g}" == "19.99"
    assert json.loads(f["argv"][f["argv"].index("--json-schema") + 1]) == json.loads(P.MAP_SCHEMA.read_text())
    assert set(f["env"]) <= ALLOWED_ENV and f["token_present"]
    assert "pkg/core.py" in f["files"] and not any(Path(x).name in W.AGENT_NAMES for x in f["files"])
    assert f["add_dir_files"] == ["map.json"] and Path(f["previous"]).parent == Path(f["add_dir"])
    assert not Path(f["previous"]).is_relative_to(f["cwd"])
    assert f["previous_map"] == bad
    assert f"\n- {err}\n" in f["prompt"] and "fix round 1 of 2" in f["prompt"]
    assert "general_knowledge" in f["prompt"] and "document.flows" in f["prompt"]
    # archived as its own attempt
    fd = run / "fix" / "1"
    for name in ("prompt.txt", "command.txt", "transcript.jsonl", "stderr.txt", "result.json", "meta.json",
                 "map.json", "validation.json"):
        assert (fd / name).exists(), name
    fm = json.loads((fd / "meta.json").read_text())
    assert fm["status"] == "ok" and fm["budget_usd"] == 19.99 and fm["errors_in"] == [err]
    assert "<token>" in (fd / "command.txt").read_text() or "<set, hidden>" in (fd / "command.txt").read_text()
    # the map run: usable, the last round's map saved, the round recorded, cost = build + fix
    meta = json.loads((run / "meta.json").read_text())
    assert meta["status"] == "ok"
    assert [{k: r[k] for k in ("round", "errors_in", "errors_out", "status")} for r in meta["fix_rounds"]] == [
        {"round": 1, "errors_in": 1, "errors_out": 0, "status": "ok"}]
    assert meta["fix_rounds"][0]["cost"] == pytest.approx(FAKE_COST)
    assert meta["usage"]["cost_usd"] == pytest.approx(2 * FAKE_COST)
    assert meta["usage"]["tokens"]["output_tokens"] == 200 and meta["totals"]["fix_rounds"] == 1
    md = fx["archive"] / "r" / "maps" / "seed1"
    assert json.loads((md / "map.json").read_text()) == FX.MAP_OUTPUT
    assert json.loads((md / "validation.json").read_text())["usable"]
    assert "## Flow run:" in (md / "map.md").read_text()
    ev = [e for e in events(fx, "r") if e["event"] == "map_fix"]
    assert len(ev) == 1 and ev[0]["errors_in"] == 1 and ev[0]["errors_out"] == 0
    assert {"map", "outline"} <= {c["cond"] for c in calls(fx)}
    # the archive's spent total counts the fix round once
    by_meta = sum(float(json.loads(p.read_text())["usage"]["cost_usd"])
                  for p in (fx["archive"] / "r").glob("runs/*/meta.json"))
    assert evalrun.Archive(fx["archive"] / "r").spent() == pytest.approx(by_meta)
    assert FX.files_containing(tmp_path, FX.TOKEN) == []
    assert list((fx["archive"].parent / "scratch").iterdir()) == []


def test_map_still_invalid_after_two_rounds_blocks_map_runs(fx, capsys):
    """(b) every fix round returns a failing map: two rounds, then the map run is invalid_answer and every map and
    outline run is blocked; the runner prints why."""
    set_control(fx, map_output=FX.map_without_flows(), fix_outputs=[FX.map_without_flows()])
    assert run_to_end(fx) == 3
    out = capsys.readouterr().out
    assert "map seed 1: not usable after 2 fix round(s): map: 1 validation error(s); still failing after 2 fix " \
           "round(s)" in out
    assert "blocked: 20 runs need a usable map" in out
    assert [c["cond"] for c in calls(fx)].count("mapfix") == 2
    assert {c["cond"] for c in calls(fx)} == {"mapbuild", "mapfix", "explore", "no-access"}
    run = fx["archive"] / "r" / "runs" / "map-s1"
    meta = json.loads((run / "meta.json").read_text())
    assert meta["status"] == "invalid_answer"
    assert [(r["round"], r["errors_in"], r["errors_out"]) for r in meta["fix_rounds"]] == [(1, 1, 1), (2, 1, 1)]
    assert meta["usage"]["cost_usd"] == pytest.approx(3 * FAKE_COST)
    budgets = [c["argv"][c["argv"].index("--max-budget-usd") + 1] for c in calls(fx) if c["cond"] == "mapfix"]
    assert budgets == ["19.99", "19.98"]                     # what is left of the map cap each time
    for n in (1, 2):
        assert not json.loads((run / "fix" / str(n) / "validation.json").read_text())["usable"]
    md = fx["archive"] / "r" / "maps" / "seed1"
    assert (md / "validation.json").exists() and not (md / "map.md").exists()
    assert [e["round"] for e in events(fx, "r") if e["event"] == "map_fix"] == [1, 2]


def test_failed_fix_round_stops_the_rounds(fx, capsys):
    set_control(fx, map_output=FX.map_without_flows(), fix_behaviors=["error"])
    assert run_to_end(fx) == 3
    meta = json.loads((fx["archive"] / "r" / "runs" / "map-s1" / "meta.json").read_text())
    assert meta["status"] == "invalid_answer" and "fix round 1: error" in meta["reason"]
    assert len(meta["fix_rounds"]) == 1 and meta["fix_rounds"][0]["errors_out"] is None
    assert [c["cond"] for c in calls(fx)].count("mapfix") == 1


def test_no_fix_rounds_when_configured_zero(fx):
    fx["config"].write_text(fx["config"].read_text().replace("map_fix_rounds = 2", "map_fix_rounds = 0"))
    set_control(fx, map_output=FX.map_without_flows())
    assert run_to_end(fx) == 3
    meta = json.loads((fx["archive"] / "r" / "runs" / "map-s1" / "meta.json").read_text())
    assert meta["status"] == "invalid_answer" and meta["fix_rounds"] == []
    assert "mapfix" not in {c["cond"] for c in calls(fx)}


def test_map_schema_requires_flows():
    """(d) the --json-schema every map build and fix round gets requires document.flows (and title, sections, coverage),
    with hops shaped as the draft validator wants them."""
    schema = json.loads(P.MAP_SCHEMA.read_text())
    doc = schema["properties"]["document"]
    assert set(doc["required"]) == {"title", "sections", "flows", "coverage"}
    flow = doc["properties"]["flows"]["items"]
    assert set(flow["required"]) == {"id", "title", "lanes", "hops"}
    hop = flow["properties"]["hops"]["items"]
    assert set(hop["required"]) == {"from", "to", "call", "trace", "claim"}
    assert hop["properties"]["trace"]["enum"] == ["seen", "unseen", "blind_spot"]
    cfg = C.load_config()
    item = P.Item(id="map-s1", kind="map", repo="nanochat", pass_no=1, map_seed=1)
    spec = P.run_spec(cfg, item, prompt="p", workdir=Path("/w/work"), config_dir=Path("/w/cfg"),
                      home_dir=Path("/w/home"), claude_bin="claude")
    assert json.loads(spec.json_schema) == schema


def test_check_ignores_unresolved_anchors_but_not_what_they_hide(fx):
    """An unresolved anchor stops Honeyguide's draft check at the claims; the runner's check still sees the rest
    (here a span citing a claim key that does not exist)."""
    m = json.loads(json.dumps(FX.MAP_OUTPUT))
    m["document"]["sections"][0]["blocks"][1]["spans"][0]["claim"] = "nope"
    v = M.validate_map(fx["clone"], fx["commit"], m)
    assert all(M.ANCHOR_ERROR.match(e) for e in v["draft_errors"])          # all Honeyguide reported
    assert v["blocking_errors"] == ["document: claim 'nope' is not a saved claim"] and not v["usable"]
    assert M.validate_map(fx["clone"], fx["commit"], {"claims": []})["blocking_errors"]


def test_fix_budget_and_usage_sum():
    assert P.fix_budget(20.0, 13.42) == 6.58 and P.fix_budget(20.0, 19.999) == 0.0
    assert P.fix_budget(20.0, 25.0) == 0.0 and P.fix_budget(1.5, 0.0) == 1.5
    a = RR.usage_summary({"usage": {"input_tokens": 1, "output_tokens": 2}, "total_cost_usd": 0.5,
                          "modelUsage": {"m1": {}}, "num_turns": 3})
    b = RR.usage_summary({"usage": {"input_tokens": 10, "cache_creation": {"ephemeral_1h_input_tokens": 4}},
                          "total_cost_usd": 0.25, "modelUsage": {"m2": {}}, "num_turns": 1})
    s = RR.sum_usage([a, b])
    assert s["tokens"]["input_tokens"] == 11 and s["tokens"]["output_tokens"] == 2 and s["cache_write_1h"] == 4
    assert s["cost_usd"] == 0.75 and s["models"] == ["m1", "m2"] and s["num_turns"] == 4
    assert RR.sum_usage([]) == RR.usage_summary(None)


def test_map_fix_prompt_and_isolation_spec(tmp_path):
    errs = ["sections[2].blocks[0]: flow 'pretrain-step' is not in document.flows", "x: y"]
    p = P.map_fix_prompt(tmp_path / "work", tmp_path / "prev" / "map.json", 812, errs, 2, 2)
    assert p.startswith(f"MODE: fix\nREPO: {tmp_path / 'work'}\nPREVIOUS: {tmp_path / 'prev' / 'map.json'}\n")
    assert "fix round 2 of 2" in p and "812 lines" in p and "2 error(s)" in p
    assert "".join(f"- {e}\n" for e in errs) in p and p.endswith(P.cartographer_body())
    cfg = C.load_config()
    spec = P.fix_run_spec(cfg, prompt=p, workdir=tmp_path / "work", map_file=tmp_path / "prev" / "map.json",
                          budget=6.58, config_dir=tmp_path / "cfg", home_dir=tmp_path / "home", claude_bin="claude")
    item = P.Item(id="map-s1", kind="map", repo="nanochat", pass_no=1, map_seed=1)
    run = P.build_command(cfg, item, spec, {"CLAUDE_CODE_OAUTH_TOKEN": "t"}, budget=6.58)
    assert run.argv[run.argv.index("--add-dir") + 1] == str(tmp_path / "prev")
    assert run.argv[run.argv.index("--max-budget-usd") + 1] == "6.58"
    assert run.argv[run.argv.index("--tools") + 1] == "Read,Grep,Glob"
    with pytest.raises(ValueError, match="outside the working dir"):     # isolate still refuses a file inside it
        P.isolate.build_run(P.fix_run_spec(cfg, prompt=p, workdir=tmp_path, map_file=tmp_path / "map.json",
                                           budget=1, config_dir=tmp_path.parent / "c",
                                           home_dir=tmp_path.parent / "h", claude_bin="claude"), {})


def test_config_map_fix_rounds_validated():
    cfg = C.load_config()
    assert cfg["map_fix_rounds"] == 2 and C.load_config(C.HERE / "config_smoke.toml")["map_fix_rounds"] == 2
    for bad in (None, -1, 6, "2", True):
        with pytest.raises(ValueError, match="map_fix_rounds"):
            C.validate_config(dict(cfg, map_fix_rounds=bad))


def test_estimate_allows_the_fix_rounds():
    cfg = C.load_config()
    item = P.Item(id="map-s1", kind="map", repo="nanochat", pass_no=1, map_seed=1)
    e = P.estimate(cfg, [item])
    lo, hi = cfg["estimate"]["map_build_usd"]
    assert e["usd"] == (lo, min(cfg["caps"]["map_usd"], hi * 3))
    assert e["minutes_sequential"][1] == cfg["estimate"]["map_build_min"][1] * 3
    assert P.estimate(dict(cfg, map_fix_rounds=0), [item])["usd"] == (lo, hi)

"""eval/run: plan, isolation, run, resume, retry, stops, with a fake `claude` (no model call anywhere).

- the plan's run count and order; the dry run prints every command, runs nothing and reads no token;
- every command line carries the isolation flags; explore / outline / map differ only in the prompt; no-access
  has no tools and an empty dir; the repo's agent files are gone from every working dir;
- the run stops at a usage limit and resumes; failed runs stay failed until --retry-failed (earlier attempt
  kept); an interrupted run is restarted and logged; --max-runs and --max-cost stop cleanly;
- the token never reaches a file (the whole tmp tree is searched), even when the child prints it;
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
    assert out.count("argv: ") == 33 and "<set, hidden>" in out and FX.TOKEN not in out
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
    assert v["anchors_total"] == 3 and v["anchors_resolved"] == 2 and not v["draft_valid"]
    assert v["unresolved"][0]["claim"] == "c3"
    text = (md / "map.md").read_text()
    assert "[pkg/core.py:" in text and "[scripts/main.py: quote not found]" in text
    o = json.loads((fx["archive"] / "r" / "outline" / "outline.json").read_text())
    assert o["target_tokens"] == v["tokens_est"]
    meta = json.loads((fx["archive"] / "r" / "runs" / "map-s1" / "meta.json").read_text())
    assert meta["status"] == "ok" and meta["models_used"] == ["claude-opus-5-5"]
    assert meta["agent_files_removed"] == ["CLAUDE.md", "AGENTS.md", ".claude"]


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

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "pilot"))
import isolate  # noqa: E402

ROOT = Path("/private/tmp/hg-run-test")
PARENT = {
    "CLAUDE_CODE_OAUTH_TOKEN": "tok-secret",
    "LANG": "en_US.UTF-8",
    "PATH": "/Users/someone/bin:/usr/bin",
    "HOME": "/Users/someone",
    "USER": "someone",
    "CLAUDECODE": "1",
    "CLAUDE_CODE_SESSION_ID": "parent-session",
    "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/sock",
    "ANTHROPIC_API_KEY": "sk-should-not-pass",
}


def spec(**kw):
    base = dict(condition="explore", working_dir=ROOT / "work", tools=isolate.EXPLORE_TOOLS, extra_file=None,
                model="claude-opus-5-5", effort="low", budget_usd=0.25, config_dir=ROOT / "cfg",
                home_dir=ROOT / "home", prompt="hi")
    base.update(kw)
    return isolate.RunSpec(**base)


def flag(argv, name):
    return argv[argv.index(name) + 1]


def test_argv_has_every_isolation_flag():
    argv = isolate.build_run(spec(), PARENT).argv
    assert argv[:3] == ["claude", "-p", "hi"]
    for f in ("--restricted", "--strict-mcp-config", "--no-session-persistence",
              "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands"):
        assert f in argv
    assert flag(argv, "--setting-sources") == ""
    assert flag(argv, "--tools") == "Read,Grep,Glob"
    assert flag(argv, "--model") == "claude-opus-5-5"
    assert flag(argv, "--effort") == "low"
    assert flag(argv, "--max-budget-usd") == "0.25"
    assert flag(argv, "--output-format") == "json"
    assert "--add-dir" not in argv and "--verbose" not in argv and "--bare" not in argv
    assert "--mcp-config" not in argv and "--fallback-model" not in argv


def test_env_is_an_allowlist():
    run = isolate.build_run(spec(), PARENT)
    assert run.env["CLAUDE_CONFIG_DIR"] == str(ROOT / "cfg")
    assert run.env["HOME"] == str(ROOT / "home")
    assert run.env["PATH"] == isolate.SAFE_PATH
    assert run.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert run.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-secret"
    for k in ("USER", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "ANTHROPIC_API_KEY"):
        assert k not in run.env
    assert run.cwd == ROOT / "work"
    assert run.redact == ("tok-secret",)


def test_no_token_means_no_token_var():
    run = isolate.build_run(spec(), {"LANG": "C"})
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in run.env and run.redact == ()


def test_describe_hides_token():
    run = isolate.build_run(spec(prompt="say tok-secret"), PARENT)
    text = "\n".join(isolate.describe(run))
    assert "tok-secret" not in text
    assert "CLAUDE_CODE_OAUTH_TOKEN=<set, hidden>" in text
    assert '--setting-sources ""' in text


def test_no_access_gets_no_tools():
    argv = isolate.build_run(spec(condition="no-access", tools=()), PARENT).argv
    assert flag(argv, "--tools") == ""
    with pytest.raises(ValueError):
        isolate.build_run(spec(condition="no-access"), PARENT)


def test_map_adds_only_the_extra_files_dir():
    extra = ROOT / "extra" / "map.md"
    argv = isolate.build_run(spec(condition="map", extra_file=extra), PARENT).argv
    assert flag(argv, "--add-dir") == str(ROOT / "extra")
    with pytest.raises(ValueError):
        isolate.build_run(spec(condition="map"), PARENT)
    with pytest.raises(ValueError):  # the map must live outside the working dir
        isolate.build_run(spec(condition="outline", extra_file=ROOT / "work" / "map.md"), PARENT)
    with pytest.raises(ValueError):
        isolate.build_run(spec(extra_file=extra), PARENT)  # explore gets no extra file


def test_stream_json_and_schema():
    argv = isolate.build_run(spec(output_format="stream-json", json_schema='{"type":"object"}'), PARENT).argv
    assert flag(argv, "--output-format") == "stream-json" and "--verbose" in argv
    assert flag(argv, "--json-schema") == '{"type":"object"}'


@pytest.mark.parametrize("kw", [dict(model="opus"), dict(effort="huge"), dict(budget_usd=0), dict(budget_usd=9),
                                dict(condition="other"), dict(config_dir=ROOT / "work" / "cfg"),
                                dict(home_dir=ROOT / "work")])
def test_rejects_bad_specs(kw):
    with pytest.raises(ValueError):
        isolate.build_run(spec(**kw), PARENT)


def test_leak_scan_counts_only_hits():
    text = "path /Users/someone/x and CANARY-CLAUDEMD-7Q4X twice CANARY-CLAUDEMD-7Q4X"
    assert isolate.leak_scan(text) == {"someone": 1, "CANARY-CLAUDEMD-7Q4X": 2}
    assert isolate.leak_scan("ok") == {}
    assert isolate.leak_scan("ZEBRA-41", ("ZEBRA-41",)) == {"ZEBRA-41": 1}


def test_canary_dir(tmp_path):
    isolate.make_canary_dir(tmp_path)
    for rel, canary in isolate.CANARIES.items():
        assert canary in (tmp_path / rel).read_text()
    assert not (tmp_path / ".git").exists()


def test_summarize_and_key_paths():
    obj = {"type": "result", "is_error": False, "num_turns": 2, "total_cost_usd": 0.01,
           "usage": {"input_tokens": 3, "cache_read_input_tokens": 5},
           "modelUsage": {"claude-opus-5-5": {"inputTokens": 3, "costUSD": 0.01}}}
    s = isolate.summarize_result(obj)
    assert s["num_turns"] == 2 and s["modelUsage"]["claude-opus-5-5"]["costUSD"] == 0.01
    assert "usage.cache_read_input_tokens: int" in isolate.key_paths(obj)

"""The plugin layer (T7.2) can't drift from the contract (T7.1).

Parses every agent and skill file's frontmatter, checks the manifests, and checks that every ``honeyguide
<command> [<action>] [--flag ...]`` the briefs, the skill and the README name exists in the CLI's parser.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from honeyguide.cli import build_parser
from honeyguide.contract import AGENTS
from honeyguide.mapdoc import TRACE
from honeyguide.store import EVIDENCE

ROOT = Path(__file__).resolve().parent.parent
AGENT_FILES = sorted((ROOT / "agents").glob("*.md"))
SKILL_FILES = sorted((ROOT / "skills").glob("*/SKILL.md"))
SUBAGENTS = ("cartographer", "investigator", "tracer", "checker")
READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "Bash"}

# The commands each file must name: the contract's loop, pinned so a rewrite can't silently drop a step.
MUST_NAME = {
    "cartographer": {"anchor resolve", "map validate", "claims save", "refresh-plan", "claims list",
                     "activity update", "map draft-dir", "map check", "map ingest", "drafts dir", "claims repair"},
    "investigator": {"anchor resolve", "answer record", "activity update", "drafts dir", "claims list", "claims repair",
                     "preview"},
    "tracer": {"anchor resolve", "answer record", "activity update", "drafts dir", "claims list", "claims repair",
               "preview"},
    "checker": {"claims list", "preview", "verdict set", "drafts dir"},
    # refresh apply logs the refresh itself (T7.5), so the skill no longer names refresh-log add.
    "honeyguide": {"status", "inbox", "question release", "question claim", "question show", "question fail",
                   "activity start", "activity finish", "serve", "watch", "refresh-plan", "refresh apply",
                   "memory state", "claims retire", "claims list"},
}


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: no frontmatter"
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        assert sep and key.strip() and not key.startswith(" "), f"{path.name}: bad frontmatter line {line!r}"
        meta[key.strip()] = value.strip().strip('"')
    return meta, body


def code_texts(markdown: str) -> list[str]:
    """Every line of every fenced block, and every inline code span (which may wrap a line)."""
    out: list[str] = []
    fence = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)  # list items indent fences
    for block in fence.findall(markdown):
        out += block.splitlines()
    prose = fence.sub("", markdown)
    out += [" ".join(span.split()) for span in re.findall(r"`([^`]+)`", prose)]
    return out


INVOCATION = re.compile(r"(?<![\w/:@.-])honeyguide((?:[ \t]+\S+)*)")


def invocations(markdown: str) -> list[tuple[list[str], list[str]]]:
    """``(words, flags)`` per ``honeyguide ...`` in code: subcommand words, then the ``--flags`` used."""
    found = []
    for text in code_texts(markdown):
        for match in INVOCATION.finditer(text):
            rest = re.split(r"\s(?:<<|\||2>|>)", " " + match.group(1))[0].split()
            words = []
            for token in rest:
                if not re.fullmatch(r"[a-z][a-z-]*", token):
                    break
                words.append(token)
            flags = [t.split("=")[0] for t in rest if t.startswith("--")] + [t for t in rest if t == "-h"]
            found.append((words, flags))
    return found


def subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def resolve_command(words: list[str]) -> tuple[str, argparse.ArgumentParser]:
    """The command named by ``words`` and its parser, or an AssertionError naming what doesn't exist."""
    parser, used = build_parser(), []
    for word in words:
        choices = subcommands(parser)
        if not choices:
            break
        assert word in choices, f"honeyguide {' '.join(used + [word])}: no such command (have {sorted(choices)})"
        parser = choices[word]
        used.append(word)
    assert not subcommands(parser), f"honeyguide {' '.join(used)}: names a group, not a command"
    return " ".join(used), parser


def all_files() -> list[Path]:
    return AGENT_FILES + SKILL_FILES + [ROOT / "README.md"]


# -- frontmatter ---------------------------------------------------------------------------------


def test_the_four_subagents_exist():
    assert sorted(p.stem for p in AGENT_FILES) == sorted(SUBAGENTS)


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_frontmatter(path):
    meta, body = frontmatter(path)
    assert {"name", "description", "tools"} <= set(meta), f"{path.name}: missing keys"
    assert meta["name"] == path.stem
    assert meta["name"] in AGENTS, "agent name must be one the contract accepts"
    assert "Use " in meta["description"], "the description must tell the Guide when to use it"
    tools = {t.strip() for t in meta["tools"].split(",")}
    # Only the CLI writes the store, so no subagent can edit the target repo by accident. Write is for input files
    # only: the Cartographer's draft map (T7.13) and, since T7.15, every agent's --input files, in its drafts
    # directory (its brief says so; no command line carries quoted JSON).
    allowed = READ_ONLY_TOOLS | {"Write"}
    assert tools <= allowed, f"{path.name}: tools beyond the minimum: {tools - allowed}"
    if "Write" in tools:
        flat = " ".join(body.split())
        assert "only** place" in flat and "you may write" in flat and "drafts dir" in flat
    assert len(body.strip()) > 1000


def test_skill_frontmatter():
    assert [p.parent.name for p in SKILL_FILES] == ["honeyguide"]
    meta, body = frontmatter(SKILL_FILES[0])
    assert meta["name"] == "honeyguide"
    assert meta["description"] and "argument-hint" in meta
    # The Guide is the main session: the skill must not fork into a subagent.
    assert "context" not in meta and "agent" not in meta
    assert "$ARGUMENTS" in body


def test_skill_dispatches_only_real_subagents():
    _, body = frontmatter(SKILL_FILES[0])
    named = set(re.findall(r"honeyguide:([a-z-]+)", body))
    assert named == set(SUBAGENTS)


# -- commands named in briefs exist ----------------------------------------------------------------


@pytest.mark.parametrize("path", all_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_named_command_exists(path):
    _, body = frontmatter(path) if path.name != "README.md" else ({}, path.read_text(encoding="utf-8"))
    named = invocations(body)
    assert named, f"{path.name}: names no honeyguide command"
    for words, flags in named:
        if not words:
            parser = build_parser()
        else:
            _, parser = resolve_command(words)
        for flag in flags:
            assert flag in parser._option_string_actions, \
                f"{path.name}: honeyguide {' '.join(words)} has no option {flag}"


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES,
                         ids=lambda p: p.stem if p.name != "SKILL.md" else "skill")
def test_each_file_names_its_steps(path):
    meta, body = frontmatter(path)
    named = {resolve_command(words)[0] for words, _ in invocations(body) if words}
    missing = MUST_NAME[meta["name"]] - named
    assert not missing, f"{path.name}: doesn't name {sorted(missing)}"


def test_json_agent_names_are_contract_agents():
    for path in AGENT_FILES + SKILL_FILES:
        for name in re.findall(r'"agent":\s*"([^"<]+)"', path.read_text(encoding="utf-8")):
            assert name in AGENTS, f"{path.name}: agent {name!r} is not one of {AGENTS}"


@pytest.mark.parametrize("stem", ["cartographer", "investigator", "tracer", "checker"])
def test_briefs_list_every_evidence_label(stem):
    body = (ROOT / "agents" / f"{stem}.md").read_text(encoding="utf-8")
    missing = [label for label in EVIDENCE if f"`{label}`" not in body]
    assert not missing, f"{stem}: evidence labels not listed: {missing}"


@pytest.mark.parametrize("stem", ["cartographer", "tracer"])
def test_path_briefs_list_every_trace_value(stem):
    body = (ROOT / "agents" / f"{stem}.md").read_text(encoding="utf-8")
    assert all(f'"{v}"' in body or f"`{v}`" in body for v in TRACE)


def test_drift_check_catches_a_bad_command():
    with pytest.raises(AssertionError):
        resolve_command(["question", "answer"])
    with pytest.raises(AssertionError):
        resolve_command(["claims"])
    assert invocations("run `honeyguide watch --follow --repo R 2>&1`") == [(["watch"], ["--follow", "--repo"])]
    indented = "1. Install:\n\n   ```bash\n   honeyguide --help\n   ```\n\n   then `honeyguide status`.\n"
    assert invocations(indented) == [([], ["--help"]), (["status"], [])]


# -- manifests -------------------------------------------------------------------------------------


def test_plugin_manifest():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "honeyguide"
    assert manifest["version"] == "0.1.0"
    assert manifest["description"]
    assert manifest["author"]["name"] == "Han Yu"


def test_marketplace_points_at_the_plugin():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["name"] and market["owner"]["name"]
    [entry] = market["plugins"]
    assert entry["name"] == "honeyguide"
    plugin_dir = (ROOT / entry["source"]).resolve()
    assert json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())["name"] == "honeyguide"
    assert (plugin_dir / "agents").is_dir() and (plugin_dir / "skills").is_dir()


# -- no quoted JSON on a command line (T7.15) --------------------------------------------------------------------------
# The permission rule Bash(honeyguide:*) allows a command that starts with honeyguide; a pipe or heredoc makes it a
# compound command, which it refuses. So every brief passes input as plain flags or --input FILE.

PIPED = ("| honeyguide", "|honeyguide", "<<", "echo '{", 'echo "{')


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES,
                         ids=lambda p: p.stem if p.name != "SKILL.md" else "skill")
def test_no_brief_pipes_json_into_a_command(path):
    text = path.read_text(encoding="utf-8")
    found = [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1) for bad in PIPED if bad in line]
    assert not found, f"{path.name}: input piped into a command (use flags or --input FILE): {found}"


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES,
                         ids=lambda p: p.stem if p.name != "SKILL.md" else "skill")
def test_no_brief_names_a_json_input_without_flags_or_a_file(path):
    """Every write command a brief names in code carries its input: plain flags or --input (no stdin)."""
    _, body = frontmatter(path)
    writes = {"verdict set", "answer record", "claims repair", "activity start", "activity update", "activity finish",
              "question claim", "question fail", "question release", "claims retire"}
    for words, flags in invocations(body):
        name = " ".join(words)
        if name in writes:
            assert flags and set(flags) - {"--repo"}, f"{path.name}: `honeyguide {name}` with no input flags"


def test_the_pipe_check_catches_a_heredoc():
    bad = "```bash\nhoneyguide verdict set --repo R <<'JSON'\n{}\nJSON\n```\n"
    assert any(p in bad for p in PIPED)
    assert any(p in "echo '{\"id\": 1}' | honeyguide activity update" for p in PIPED)


# -- T7.16 -------------------------------------------------------------------------------------------------------------

COMPOUND = re.compile(r"&&|\|\||(?<![<>&0-9])\|(?!\|)|;")


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES + [ROOT / "README.md"],
                         ids=lambda p: p.stem if p.name != "SKILL.md" else "skill")
def test_no_command_example_chains_commands(path):
    """One honeyguide command per Bash call: a line of code that runs honeyguide never chains another command with
    ``&&``, ``;`` or ``|`` (the permission rules refuse compound commands; the Guide was refused live)."""
    body = path.read_text(encoding="utf-8")
    bad = [t for t in code_texts(body) if INVOCATION.search(t) and COMPOUND.search(t.replace("2>&1", ""))]
    assert not bad, f"{path.name}: chained command(s) in an example: {bad}"


def test_the_chain_check_catches_and_and():
    for bad in ("honeyguide status --repo R && honeyguide inbox --repo R", "honeyguide inbox --repo R; ls",
                "honeyguide claims list --repo R | head"):
        md = f"run `{bad}`\n"
        assert [t for t in code_texts(md) if INVOCATION.search(t) and COMPOUND.search(t.replace("2>&1", ""))], bad
    ok = "`honeyguide watch --follow --repo R 2>&1`"
    assert not [t for t in code_texts(ok) if INVOCATION.search(t) and COMPOUND.search(t.replace("2>&1", ""))]


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES,
                         ids=lambda p: p.stem if p.name != "SKILL.md" else "skill")
def test_every_brief_says_one_command_per_bash_call(path):
    flat = " ".join(path.read_text(encoding="utf-8").split())
    assert "One `honeyguide` command per Bash call" in flat or "One command per Bash call" in flat
    assert "`&&`, `;` or `|`" in flat


def checker_flat() -> str:
    return " ".join((ROOT / "agents" / "checker.md").read_text(encoding="utf-8").split())


def test_checker_computes_values_and_never_trusts_a_comment():
    flat = checker_flat()
    assert "**Compute, don't quote.**" in flat and "### Worked example: compute, don't quote" in flat
    assert "only if the cited **code** produces that value" in flat
    assert "A comment or docstring that states the value is not evidence for it, except for a claim labelled `docs`" in flat
    assert "When the code and a comment disagree, the claim must follow the code" in flat
    assert "naming the line that computes the value" in flat
    # the worked example is a made-up repo, and its arithmetic is right: the stale comment says 24, the code gives 8
    body = (ROOT / "agents" / "checker.md").read_text(encoding="utf-8")
    example = body.split("### Worked example: compute, don't quote", 1)[1].split("\n## ", 1)[0]
    assert "pool/config.py" in example and "nanochat" not in example
    max_jobs, workers = 1536, 64
    assert max(-(-max_jobs // workers // 3), 8) == 8 and max_jobs // workers == 24
    assert "-(-1536 // 64 // 3) = 8" in " ".join(example.split())


def test_checker_reads_anchors_through_preview_only():
    flat = checker_flat()
    assert "**This is how you read a cited anchor, always**: not the Read tool, not `git show`" in flat
    assert "hash_matches" in flat
    assert "git -C REPO show" not in flat           # the old "for a range too long, git show" escape hatch is gone
    assert "never for reading a cited anchor (use `preview`)" in flat


def test_checker_status_count_comes_from_claims_list():
    flat = checker_flat()
    assert "`claims list`'s `count` for your `SCOPE`" in flat
    skill = " ".join(SKILL_FILES[0].read_text(encoding="utf-8").split())
    step = skill.split("6. **Check**", 1)[1].split("7. **Repair**", 1)[0]
    assert "`N` = the `count` of `honeyguide claims list --repo REPO --responses <response id> --check unchecked --freshness current`" in step
    assert step.index("claims list") < step.index('"Checking N claims"')


def test_answers_get_the_repair_pass():
    skill = " ".join(SKILL_FILES[0].read_text(encoding="utf-8").split())
    assert "## 8. Repair pass on an answer" in skill
    sec = skill.split("## 8. Repair pass on an answer", 1)[1].split("## Never", 1)[0]
    for must in ("`MODE: repair`", "`RESPONSE: <response id>`", "`ROUND: R`", "--responses <response id> --check not_supported",
                 "claims repair --response <response id>", "Re-check** only the changed claims", "Stop after round 2"):
        assert must in sec, must
    assert "the repair pass on an answer (section 8)" in skill
    for stem in ("investigator", "tracer"):
        flat = " ".join((ROOT / "agents" / f"{stem}.md").read_text(encoding="utf-8").split())
        assert "## Repair (`MODE: repair`)" in flat and "`MODE`: `answer`" in flat
        assert "honeyguide claims repair --repo REPO --response RESPONSE --input INPUTS/repair-ROUND.json" in flat
        assert "**Never broader**" in flat and "Run `claims repair` outside `MODE: repair`" in flat


def test_tracer_says_read_not_run_without_a_trace():
    flat = " ".join((ROOT / "agents" / "tracer.md").read_text(encoding="utf-8").split())
    assert "**No `TRACE`, nothing was run.**" in flat and '"read in source, not run"' in flat
    assert 'never "not in the trace", "the trace skips this" or "trace blind spot"' in flat

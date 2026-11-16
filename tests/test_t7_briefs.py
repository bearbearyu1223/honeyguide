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
                     "activity update", "map draft-dir", "map check", "map ingest"},
    "investigator": {"anchor resolve", "answer record", "activity update"},
    "tracer": {"anchor resolve", "answer record", "activity update"},
    "checker": {"claims list", "preview", "verdict set"},
    # refresh apply logs the refresh itself (T7.5), so the skill no longer names refresh-log add.
    "honeyguide": {"status", "inbox", "question release", "question claim", "question show", "question fail",
                   "activity start", "activity finish", "serve", "watch", "refresh-plan", "refresh apply",
                   "memory state", "claims retire"},
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
    # Only the CLI writes, so no subagent can edit the target repo by accident. One exception (T7.13): the
    # Cartographer writes its draft map with Write, into the drafts directory only (its brief says so, and
    # map check / ingest refuse any other directory).
    allowed = READ_ONLY_TOOLS | ({"Write"} if meta["name"] == "cartographer" else set())
    assert tools <= allowed, f"{path.name}: tools beyond the minimum: {tools - allowed}"
    if "Write" in tools:
        assert "only** place you may write" in body and "map draft-dir" in body
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

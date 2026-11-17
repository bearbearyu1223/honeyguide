"""eval/runs/commits.py: commit count and Claude co-author trailers up to the frozen commit."""

import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "eval" / "runs" / "commits.py"
_spec = importlib.util.spec_from_file_location("eval_runs_commits", SRC)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)


def test_trailer_any_case_any_model():
    assert cm.has_claude_trailer("Fix\n\nBody.\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n")
    assert cm.has_claude_trailer("Fix\n\nco-authored-by: claude sonnet 4 <x@y>")
    assert cm.has_claude_trailer("Fix\n\nSigned-off-by: A <a@b>\nCO-AUTHORED-BY:Claude <x@y>")


def test_trailer_must_be_claude_and_in_last_paragraph():
    assert not cm.has_claude_trailer("Fix\n\nCo-Authored-By: Alice <a@b>")
    assert not cm.has_claude_trailer("Fix\n\nCo-Authored-By: Claudette <a@b>")
    assert not cm.has_claude_trailer("Co-Authored-By: Claude <x@y>")            # a subject, not a trailer
    assert not cm.has_claude_trailer("Fix\n\nCo-Authored-By: Claude <x@y>\n\nLater paragraph.")
    assert not cm.has_claude_trailer("Fix\n\nMentions Co-Authored-By: Claude inline")


def test_parse_log_and_summarize():
    text = ("bbb\n2026-11-16T10:00:00-08:00\nSecond\n\nCo-Authored-By: Claude X <x@y>\n\0"
            "\naaa\n2026-11-15T12:00:00-08:00\nFirst\n\0")
    commits = cm.parse_log(text)
    assert [c[0] for c in commits] == ["bbb", "aaa"]
    assert cm.summarize(commits) == (2, 1, ("aaa", "2026-11-15T12:00:00-08:00"))
    assert cm.summarize([]) == (0, 0, (None, None))


def test_frozen_commit_is_pinned():
    assert cm.FROZEN == "f1b52e9"

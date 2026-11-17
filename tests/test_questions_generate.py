"""The cutoff tags in generate.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "questions"))
from generate import Tagger, _key_ranges  # noqa: E402


class FakeRepo:
    def nonblank(self, path):
        return {1, 2, 3}

    def blame(self, path, first_parent=True):
        return {1: 0, 2: 2_000_000_000, 3: 2_000_000_000}

    def functions(self):
        return {}


def test_no_key_lines_is_none_not_before():
    """The report has a 'none' column ('none = no key lines to blame'), but
    Tagger.tag returns 'before' when no line is counted, so 'none' is always
    0 and an empty key is silently counted as before-cutoff."""
    t = Tagger(FakeRepo(), "2026-06-30")
    assert t.tag({})["subset"] == "none"


def test_alt_cutoff_table_uses_the_same_lines_as_the_tag():
    """build_callers tags callers questions on key callers AND open dispute
    lines; _key_ranges (used for the 'other cutoffs' table) drops the
    disputes. nc-cal-01 and wk-cal-03 (empty keys, disputes only) are tagged
    'after' in the JSON but count as nothing in that table at any cutoff."""
    q = {"type": "callers", "key": {"callers": []},
         "disputes_for_han": [{"file": "m.py", "caller": "f", "lines": [2, 3]}]}
    assert _key_ranges(q, FakeRepo())


def test_dispute_marked_not_leaves_the_tag_lines():
    """Once the annotator marks a dispute 'not', its lines no longer count, so a key
    with no callers left is tagged 'none'."""
    from generate import Tagger, key_ranges
    q = {"type": "callers", "key": {"callers": []},
         "disputes_for_han": [{"file": "m.py", "caller": "f", "lines": [2, 3], "mark": "not"}]}
    assert key_ranges(q, {}) == {}
    assert Tagger(FakeRepo(), "2026-06-30").tag(key_ranges(q, {}))["subset"] == "none"


def test_class_body_call_accepts_the_class():
    """wk-cal-09: resolve_home() in a Settings field default is keyed to
    <module>; an answer naming Settings is right too. A plain module-level
    call, or one inside a method, gets no alias."""
    import ast
    import textwrap
    from keys import class_body_aliases
    tree = ast.parse(textwrap.dedent('''
        from dataclasses import dataclass, field
        x = resolve_home()

        @dataclass
        class Settings:
            home: str = field(default_factory=lambda: resolve_home())

            def again(self):
                return resolve_home()
    ''').lstrip("\n"))
    assert class_body_aliases(tree, "<module>", [6]) == ["Settings"]
    assert class_body_aliases(tree, "<module>", [2]) == []
    assert class_body_aliases(tree, "<module>", [9]) == []
    assert class_body_aliases(tree, "Settings.again", [9]) == []

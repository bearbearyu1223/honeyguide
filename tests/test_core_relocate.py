"""``relocate()``: its fallback order."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeyguide.anchors import relocate, resolve  # noqa: E402

OLD = ["def foo():", "    return 1", ""]
NEW = ["def bar():", "    return 1", "", "def foo():", "    return 1", ""]


def test_same_text_at_old_position_in_another_function_is_not_unchanged():
    """A one-line anchor in foo; a new function bar inserted above whose line
    2 has the same text. The same-position hash check runs first, so the
    claim is 'unchanged' (served as current) while now pointing into bar."""
    a = resolve(OLD, "m.py", "return 1", "c" * 40).anchor
    assert a.symbol == "foo"
    r = relocate(a, NEW, "m.py")
    assert (r.state, r.start, r.symbol) == ("moved", 5, "foo")

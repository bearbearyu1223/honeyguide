"""Document anchors re-found after the map or an answer is regenerated; failures are explicit."""

from __future__ import annotations

import pytest

from honeyguide.docanchor import DocumentAnchor, make_anchor, reanchor

TEXT = "The agent calls the model. Then the agent calls the tool. Done."


def test_same_revision_is_untouched():
    a = make_anchor("map", "1", TEXT, 4, 9)
    assert a.quote == "agent"
    assert reanchor(a, "anything", "1").status == "same"
    assert DocumentAnchor.from_dict(a.to_dict()) == a


def test_moved_quote_is_resolved():
    a = make_anchor("map", "1", TEXT, TEXT.index("the tool"), TEXT.index("the tool") + 8)
    new = "Intro. " + TEXT
    r = reanchor(a, new, "2")
    assert r.status == "resolved" and new[r.anchor.start:r.anchor.end] == "the tool" and r.anchor.revision == "2"


def test_repeated_quote_uses_context_or_stays_unresolved():
    second = TEXT.index("agent calls the tool")
    a = make_anchor("answer:r_1", "1", TEXT, second, second + len("agent calls"))
    r = reanchor(a, "Intro. " + TEXT, "2")
    assert r.status == "resolved" and r.anchor.start == second + 7
    changed = TEXT.replace("Then the agent calls the tool", "Later the agent calls a tool")
    assert reanchor(a, changed, "2").status == "unresolved"


def test_missing_quote_is_unresolved_and_bad_offsets_raise():
    a = make_anchor("map", "1", TEXT, 0, 3)
    assert reanchor(a, "Nothing like it here.", "2").status == "unresolved"
    with pytest.raises(ValueError):
        make_anchor("map", "1", TEXT, 5, 5)

"""Review round 1 (T8): one rule for "shared with agents" across retrieve and export."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeyguide.retrieve import Context, retrieve  # noqa: E402
from honeyguide.store import Store, export_bundle  # noqa: E402


def test_export_and_retrieve_agree_on_a_truthy_non_boolean_flag(tmp_path):
    store = Store("t", tmp_path)
    store.add_note("about the engine loop", None, share_with_agents=True)
    store.update("notes", lambda d: d["notes"].append(
        {"id": "n_odd", "kind": "note", "text": "engine loop too", "anchor": None, "share_with_agents": "yes"}))
    exported = {n["id"] for n in export_bundle(store)["notes"]["notes"]}
    got = retrieve(store.load("map"), store.load("answers"), store.load("notes"), Context(text="engine loop"))
    assert exported == {n["id"] for n in got.notes}
    assert "n_odd" not in exported

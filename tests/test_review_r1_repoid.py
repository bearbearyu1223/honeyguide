"""Review round 1 (T8): normalize_remote keeps a token passed in the URL query."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeyguide.repoid import normalize_remote  # noqa: E402


def test_query_token_not_kept():
    got = normalize_remote("https://github.com/o/r.git?private_token=SECRET")
    assert got == "github.com/o/r"

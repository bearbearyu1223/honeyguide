"""``normalize_remote`` never keeps userinfo, in any form."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeyguide.repoid import normalize_remote  # noqa: E402


def test_scp_password_with_at_sign_is_dropped():
    assert normalize_remote("user:p@ss@github.com:Owner/Repo.git") == "github.com/owner/repo"


def test_https_userinfo_query_and_fragment_are_dropped():
    assert normalize_remote("https://u:t0ken@gitlab.example.com/g/r.git#frag") == "gitlab.example.com/g/r"
    assert normalize_remote("git@github.com:o/r.git?x=1") == "github.com/o/r"

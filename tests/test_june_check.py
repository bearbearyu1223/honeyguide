"""eval/cutoff/june_check.py: the June 2026 key-line count's pure helpers, and the receipt itself."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "eval" / "cutoff" / "june_check.py"
_spec = importlib.util.spec_from_file_location("eval_june_check", SRC)
jc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jc)
TARGETS = Path.home() / "Documents" / "GitHub" / "honeyguide-targets"


def test_month_bounds_match_the_cutoff_day():
    lo, hi = jc.month_bounds("2026-06")
    assert lo == 1780272000 and hi == 1782863999   # 2026-06-01 00:00:00 and 2026-06-30 23:59:59 UTC
    sys.path.insert(0, str(ROOT / "eval" / "questions"))
    from generate import cutoff_ts
    assert hi == cutoff_ts("2026-06-30")
    assert jc.month_bounds("2026-12") == (1796083200, 1798761599)


def test_split_lines_counts_non_blank_lines_by_window():
    lo, hi = 100, 200
    times = {1: 50, 2: 100, 3: 200, 4: 201, 5: 150}
    assert jc.split_lines(times, [1, 2, 3, 4, 5, 6], {1, 2, 3, 4, 6}, lo, hi) == {"before": 2, "in": 2, "after": 1}
    assert jc.add({"in": 1}, {"in": 2, "after": 3}) == {"in": 3, "after": 3}


@pytest.mark.skipif(not all((TARGETS / r).exists() for r in jc.REPOS), reason="target clones not present")
def test_receipt_matches_the_frozen_tags_and_is_saved():
    out = subprocess.run([sys.executable, str(SRC)], capture_output=True, text=True, check=True).stdout
    assert "MISMATCH" not in out and out.count(": match") == 2
    assert all(len(line) <= jc.WIDTH for line in out.splitlines())
    assert (ROOT / "outputs" / "june_check.txt").read_text() == out

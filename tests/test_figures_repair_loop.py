"""eval/figures/repair_loop.py: the repair-loop figure's numbers come from the checker block of runs.txt, parsed."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("eval_figures_repair_loop", ROOT / "eval" / "figures" / "repair_loop.py")
rl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rl          # dataclasses look their module up
_spec.loader.exec_module(rl)

CHECKER = """runs
--------------------------------------------------------------------------
  nanochat    run 2 before repair          999       999         0       0

checker
--------------------------------------------------------------------------
Map claims by Checker verdict.
  repo        stage                  supported not supp. unchecked retired
  nanochat    run 1 (no repair)            129        20         0       0
  nanochat    run 2 before repair          158       102         0       0
  nanochat    after repair round 1         253         7         0       0
  nanochat    after repair round 2         260         0         0       0
  waku-agent  run 2 before repair          219        47         0       0
  waku-agent  after repair round 1         265         1         0       0
  waku-agent  after repair round 2         266         0         0       0

  What repair did, per round (one row per repair action taken):
  repo        round  anchors replaced  cite more lines  rewritten  retired
  nanochat        1                85               85         17        0
  nanochat        2                 5                5          2        0
  waku-agent      1                45               45          2        0
  waku-agent      2                 1                1          0        0

recheck
--------------------------------------------------------------------------
  nanochat    before repair                 78        39         0       0
  nanochat        1                27         12        0
"""


def test_parse_reads_the_checker_block_only():
    loop = rl.parse(CHECKER, "nanochat")
    assert loop.supported == (158, 253, 260) and loop.not_supported == (102, 7, 0)
    assert loop.anchors == (85, 5) and loop.more_lines == (85, 5) and loop.rewritten == (17, 2) and loop.retired == (0, 0)
    assert loop.total == 260 and loop.back_supported == (95, 7)
    w = rl.parse(CHECKER, "waku-agent")
    assert w.total == 266 and w.not_supported == (47, 1, 0) and w.anchors == (45, 1)


def test_parse_refuses_counts_that_dont_add_up():
    with pytest.raises(ValueError, match="round 1"):
        rl.parse(CHECKER.replace("85         17", "85         16"), "nanochat")
    with pytest.raises(ValueError, match="no 'smol run 2 before repair' row"):
        rl.parse(CHECKER, "smol")
    with pytest.raises(ValueError, match="no 'checker' block"):
        rl.parse("runs\n----------\n", "nanochat")


def test_the_real_receipt_parses():
    runs = ROOT / "outputs" / "runs.txt"
    if not runs.exists():
        pytest.skip("no outputs/runs.txt")
    loop = rl.parse(runs.read_text(), "nanochat")
    assert loop.supported[2] + loop.not_supported[2] == loop.total

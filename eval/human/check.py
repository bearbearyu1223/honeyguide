"""Print what's complete and what's left in Han's human eval chores, from eval/human/answers/.

    uv run python eval/human/check.py            # the summary, as the Done tab shows it
    uv run python eval/human/check.py --json     # the same, as JSON (what later steps read)

Exit status: 0 when every chore is complete for every repo and the frozen sets match MANIFEST.txt, else 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chores  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--answers", default=str(chores.ANSWERS), help="the answers directory")
    args = ap.parse_args(argv)
    s = chores.summarize(Path(args.answers))
    sys.stdout.write(chores.dumps(s) if args.json else chores.summary_text(s))
    return 0 if s["done"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Shot 6b: the follow-up's finished answer (after its live run and check), read down to its Checker summary.

    uv run --project .. python shoot_followup.py OUT --q q_...
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rec import Rec, phrase


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--q", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8782/")
    ap.add_argument("--dark", action="store_true")
    a = ap.parse_args()
    with Rec(Path(a.out), dark=a.dark) as c:
        c.goto(a.url + f"#q={a.q}")
        c.wait("(document.getElementById('pbody').innerText || '').includes('Does anything else')", 10)
        c.pump(0.5)
        # start with the follow-up's question at the top of the panel
        p = phrase(c, "document.getElementById('pbody')", "Does anything else", "this map?")
        c.js(f"document.getElementById('pbody').scrollTop += {p['top']} - document.getElementById('pbody').getBoundingClientRect().top - 90")
        c.pump(0.5)
        c.cursor = (1210, 560)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(2.0)
        end = c.js("""(() => { const b = document.getElementById('pbody'); return b.scrollHeight - b.clientHeight - b.scrollTop; })()""")
        c.smooth_scroll(min(end, 900), 2600)
        c.pump(2.5)
        c.stop()


if __name__ == "__main__":
    main()

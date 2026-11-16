"""Shot 5b: the finished Tracer answer (after the live run): scroll its hops, with the Checker's marks and flags,
hover a flag to read the Checker's note, then "View as diagram" and pan across its lanes.

    uv run --project .. python shoot_answer.py OUT --q q_...
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rec import Rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--q", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8782/")
    ap.add_argument("--dark", action="store_true")
    a = ap.parse_args()
    with Rec(Path(a.out), dark=a.dark) as c:
        c.goto(a.url + f"#q={a.q}")
        c.pump(1.0)
        c.cursor = (1210, 520)
        c.mouse("mouseMoved", *c.cursor)
        c.start()
        c.pump(1.2)
        # down the answer's hops (wheel over the panel)
        for _ in range(3):
            c.smooth_scroll(330, 900)
            c.pump(0.7)
        # a flag: hover it for the Checker's note
        flag = c.rect("[...document.querySelectorAll('#pbody .flag')].find(e => { const r = e.getBoundingClientRect(); "
                      "return r.top > 160 && r.bottom < 640 && r.right < 1420; })")
        if flag:
            c.move(flag["x"] + flag["w"] / 2, flag["y"] + flag["h"] / 2, 650)
            c.pump(2.6)
            c.note("flag_hover", tip=c.js("document.getElementById('tip').className + ' | ' + document.getElementById('tip').innerText"))
        # to the end of the answer, then make room and open the diagram
        c.move(1210, 520, 500)
        c.smooth_scroll(2400, 1300)
        c.pump(0.6)
        rb = c.rect("document.getElementById('railbtn')")
        c.click_at(rb["x"] + rb["w"] / 2, rb["y"] + rb["h"] / 2, 800)
        c.pump(0.8)
        dv = c.rect("document.querySelector('#pbody [data-dgview]')")
        c.click_at(dv["x"] + dv["w"] / 2, dv["y"] + dv["h"] / 2, 900)
        c.pump(2.4)
        # pan the swimlane: shift-wheel inside the diagram
        c.move(240, 236, 600)
        steps = 70
        for i in range(steps):
            c.call("Input.dispatchMouseEvent", type="mouseWheel", x=240, y=236, deltaX=19, deltaY=0)
            c.call("Input.dispatchMouseEvent", type="mouseWheel", x=240, y=236, deltaX=0, deltaY=3)
            c.pump(0.035)
        c.pump(2.0)
        c.stop()


if __name__ == "__main__":
    main()

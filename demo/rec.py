"""Recording helpers for the Honeyguide demo: headless Chrome over CDP (Honeyguide's own tests/cdp.py client), plus
a screencast recorder that saves every frame with its timestamp and a log of where the (drawn) cursor is.

Headless Chrome has no cursor. Every pointer move goes through ``Rec.move`` (eased, as a person moves) which sends
real ``Input.dispatchMouseEvent`` events and logs the position; ``cursor.py`` draws the cursor and click ripples
into the frames afterwards from that log.

Every Chrome launch runs under ``perl -e 'alarm N; exec @ARGV'`` (the cdp.Chrome default), N <= 120.
"""

from __future__ import annotations

import base64
import json
import math
import socket
import sys
import time
from pathlib import Path

HG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HG / "tests"))

from cdp import Chrome  # noqa: E402


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class Rec(Chrome):
    """A Chrome whose screencast frames are written to ``out/frames/<n>.jpg`` with a timing log ``out/log.jsonl``."""

    def __init__(self, out: Path, alarm: int = 120, dark: bool = False, **kw) -> None:
        super().__init__(alarm=alarm, **kw)
        self.out = Path(out)
        (self.out / "frames").mkdir(parents=True, exist_ok=True)
        self.log = open(self.out / "log.jsonl", "a")
        self.n = len(list((self.out / "frames").glob("*.jpg")))
        self.cursor = (720.0, 450.0)
        self.recording = False
        self.min_dt = 0.0          # >0: keep at most one frame per min_dt seconds (long waits)
        self._last_kept = 0.0
        self.media(dark=dark)

    # every message that is not our reply goes through here, so frames are saved and acked while we wait
    def call(self, method: str, **params):
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg: dict) -> None:
        if msg.get("method") == "Page.screencastFrame":
            p = msg["params"]
            if self.recording and time.time() - self._last_kept >= self.min_dt:
                self._last_kept = time.time()
                self.n += 1
                (self.out / "frames" / f"{self.n:06d}.jpg").write_bytes(base64.b64decode(p["data"]))
                self.note("frame", n=self.n, ts=p["metadata"].get("timestamp"))
            self.ws.send(json.dumps({"id": 10 ** 9 + p["sessionId"], "method": "Page.screencastFrameAck",
                                     "params": {"sessionId": p["sessionId"]}}))
        elif msg.get("id", 0) >= 10 ** 9:
            pass
        else:
            self.events.append(msg)

    def note(self, kind: str, **kw) -> None:
        self.log.write(json.dumps({"t": time.time(), "kind": kind, **kw}) + "\n")
        self.log.flush()

    def pump(self, seconds: float) -> None:
        """Wait, saving frames as they arrive."""
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            self.ws.sock.settimeout(min(left, 0.25))
            try:
                if not self.ws.buf:
                    chunk = self.ws.sock.recv(1 << 20)
                    if not chunk:
                        raise ConnectionError("closed")
                    self.ws.buf += chunk
                self.ws.sock.settimeout(30)
                self._event(json.loads(self.ws.recv()))
            except socket.timeout:
                pass
            finally:
                self.ws.sock.settimeout(30)

    def start(self, quality: int = 85) -> None:
        self.recording = True
        self.note("start")
        self.call("Page.startScreencast", format="jpeg", quality=quality, maxWidth=2880, maxHeight=1800, everyNthFrame=1)

    def stop(self) -> None:
        self.call("Page.stopScreencast")
        self.recording = False
        self.note("stop")

    # -- a person's pointer ---------------------------------------------------------------------------

    def move(self, x: float, y: float, ms: float = 550, buttons: int = 0) -> None:
        x0, y0 = self.cursor
        steps = max(6, int(ms / 16))
        t0 = time.monotonic()
        for i in range(1, steps + 1):
            k = ease(i / steps)
            cx, cy = x0 + (x - x0) * k, y0 + (y - y0) * k
            self.mouse("mouseMoved", cx, cy, buttons=buttons)
            self.cursor = (cx, cy)
            self.note("cursor", x=cx, y=cy, down=bool(buttons))
            target = t0 + ms / 1000 * i / steps
            self.pump(max(0.0, target - time.monotonic()))

    def click_at(self, x: float, y: float, ms: float = 550) -> None:
        self.move(x, y, ms)
        self.pump(0.12)
        self.mouse("mousePressed", x, y, buttons=1)
        self.note("click", x=x, y=y)
        self.pump(0.08)
        self.mouse("mouseReleased", x, y)
        self.pump(0.1)

    def drag_select(self, x0: float, y0: float, x1: float, y1: float, ms: float = 900) -> None:
        self.move(x0, y0, 500)
        self.pump(0.15)
        self.mouse("mousePressed", x0, y0, buttons=1)
        self.note("press", x=x0, y=y0)
        self.move(x1, y1, ms, buttons=1)
        self.mouse("mouseReleased", x1, y1)
        self.note("release", x=x1, y=y1)
        self.pump(0.2)

    def type_slow(self, text: str, cps: float = 18) -> None:
        for ch in text:
            self.call("Input.insertText", text=ch)
            self.pump(1 / cps)

    def rect(self, expr: str) -> dict | None:
        """``expr`` evaluates to an element; returns its viewport rect."""
        return self.js(f"(() => {{ const e = {expr}; if (!e) return null; const r = e.getBoundingClientRect(); "
                       f"return {{x: r.left, y: r.top, w: r.width, h: r.height}}; }})()")

    def smooth_scroll(self, dy: float, ms: float = 900) -> None:
        """Scroll the main column by ``dy`` px with wheel events (eased), at the cursor."""
        steps = max(8, int(ms / 16))
        done = 0.0
        t0 = time.monotonic()
        x, y = self.cursor
        for i in range(1, steps + 1):
            want = dy * ease(i / steps)
            d = want - done
            done = want
            self.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=d)
            self.pump(max(0.0, t0 + ms / 1000 * i / steps - time.monotonic()))


PHRASE_JS = r"""
(function (root, a, b) {
  /* the viewport points just inside the first character of ``a`` and just after the last character of ``b``
     (``b`` searched after ``a``), across text nodes under ``root`` */
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = []; let text = '';
  while (walker.nextNode()) { nodes.push([walker.currentNode, text.length]); text += walker.currentNode.data; }
  const i = text.indexOf(a); if (i < 0) return null;
  const j = text.indexOf(b, i); if (j < 0) return null;
  const at = (k) => { for (let n = nodes.length - 1; n >= 0; n--) if (nodes[n][1] <= k) return [nodes[n][0], k - nodes[n][1]]; };
  const charRect = (k) => { const [n, o] = at(k); const r = document.createRange(); r.setStart(n, o); r.setEnd(n, o + 1); return r.getBoundingClientRect(); };
  const s = charRect(i), e = charRect(j + b.length - 1);
  return {x0: s.left + 1, y0: s.top + s.height / 2, x1: e.right - 0.5, y1: e.top + e.height / 2, top: s.top, bottom: e.bottom};
})
"""


def phrase(c: Chrome, root_expr: str, a: str, b: str):
    return c.js(f"{PHRASE_JS}({root_expr}, {json.dumps(a)}, {json.dumps(b)})")

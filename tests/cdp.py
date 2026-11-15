"""Drive headless Chrome over the DevTools protocol, standard library only (a minimal WebSocket client).

Chrome always runs under ``perl -e 'alarm N; exec @ARGV'`` (macOS has no GNU timeout; a hung headless Chrome once
blocked a run for 15 minutes), so no session can outlive its alarm. Used by the map page's interaction tests and by
the screenshot script.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_path() -> str | None:
    for path in (os.environ.get("HONEYGUIDE_CHROME"), CHROME, shutil.which("google-chrome"), shutil.which("chromium")):
        if path and Path(path).exists():
            return path
    return None


class WebSocket:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str, opcode: int = 1) -> None:
        data = text.encode() if isinstance(text, str) else text
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            head += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        self.sock.sendall(head + mask + masked)

    def recv(self) -> str:
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            payload = self._read(n)
            op = b0 & 0x0F
            if op == 9:          # ping
                self.send(payload, opcode=10)
                continue
            if op == 8:
                raise ConnectionError("websocket closed by Chrome")
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts).decode()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Chrome:
    """One headless Chrome with one page. ``with Chrome() as c: c.goto(url); c.js("1+1")``."""

    def __init__(self, width: int = 1440, height: int = 900, scale: float = 2, alarm: int = 60) -> None:
        exe = chrome_path()
        if exe is None:
            raise RuntimeError("Chrome not found (set HONEYGUIDE_CHROME)")
        self.profile = tempfile.mkdtemp(prefix="hg-chrome-")
        self.proc = subprocess.Popen(
            ["perl", "-e", "alarm shift; exec @ARGV", str(alarm), exe, "--headless=new", "--remote-debugging-port=0",
             f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
             "--disable-gpu", "--disable-extensions", "--mute-audio", f"--window-size={width},{height}",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.profile) / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not port_file.exists() or not port_file.read_text().strip():
            if time.monotonic() > deadline or self.proc.poll() is not None:
                self.close()
                raise RuntimeError("Chrome did not start")
            time.sleep(0.05)
        port = int(port_file.read_text().split()[0])
        targets = []
        while not targets and time.monotonic() < deadline:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                targets = [t for t in json.load(r) if t.get("type") == "page"]
        self.ws = WebSocket(targets[0]["webSocketDebuggerUrl"])
        self.next_id = 0
        self.events: list[dict] = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.viewport(width, height, scale)

    # -- protocol --------------------------------------------------------------------------------------

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
            self.events.append(msg)

    def js(self, expression: str, await_promise: bool = True):
        out = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if out.get("exceptionDetails"):
            raise RuntimeError(f"page error: {out['exceptionDetails'].get('exception', {}).get('description') or out['exceptionDetails']}")
        return out.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 10.0, interval: float = 0.05):
        deadline = time.monotonic() + timeout
        while True:
            value = self.js(expression)
            if value:
                return value
            if time.monotonic() > deadline:
                raise TimeoutError(f"waited {timeout}s for: {expression}")
            time.sleep(interval)

    def console_errors(self) -> list[str]:
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown":
                out.append(e["params"]["exceptionDetails"].get("exception", {}).get("description", "exception"))
            if e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error":
                out.append(" ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"]))
        return out

    # -- page ------------------------------------------------------------------------------------------

    def viewport(self, width: int, height: int, scale: float = 2) -> None:
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=False)

    def media(self, dark: bool = False, reduced_motion: bool = False) -> None:
        self.call("Emulation.setEmulatedMedia", features=[
            {"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced_motion else "no-preference"}])

    def goto(self, url: str, ready: str = "document.documentElement.dataset.ready === '1'", timeout: float = 15) -> None:
        self.call("Page.navigate", url="about:blank")   # a hash-only change wouldn't reload the page
        self.wait("document.readyState === 'complete' && location.href === 'about:blank'", timeout)
        self.call("Page.navigate", url=url)
        self.wait(ready, timeout)

    def screenshot(self, path: str | Path) -> None:
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)["data"]
        Path(path).write_bytes(base64.b64decode(data))

    # -- input (real events, as a person would) ---------------------------------------------------------

    def mouse(self, kind: str, x: float, y: float, buttons: int = 0, clicks: int = 1) -> None:
        params = {"type": kind, "x": x, "y": y, "buttons": buttons}
        if kind in ("mousePressed", "mouseReleased"):
            params.update(button="left", clickCount=clicks)
        elif buttons:
            params["button"] = "left"   # a drag: Chrome extends the selection only when the move names the button
        self.call("Input.dispatchMouseEvent", **params)

    def drag(self, x0: float, y0: float, x1: float, y1: float, steps: int = 8) -> None:
        self.mouse("mouseMoved", x0, y0)
        self.mouse("mousePressed", x0, y0, buttons=1)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, buttons=1)
        self.mouse("mouseReleased", x1, y1)

    def click(self, x: float, y: float, clicks: int = 1) -> None:
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y, buttons=1, clicks=clicks)
        self.mouse("mouseReleased", x, y, clicks=clicks)

    def click_el(self, selector: str) -> None:
        box = self.box(selector)
        self.click(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)

    def hover_el(self, selector: str) -> None:
        box = self.box(selector)
        self.mouse("mouseMoved", box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)

    def box(self, selector: str) -> dict:
        b = self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; "
                    f"e.scrollIntoView({{block: 'nearest'}}); const r = e.getBoundingClientRect(); "
                    f"return {{x: r.left, y: r.top, w: r.width, h: r.height}}; }})()")
        if b is None:
            raise LookupError(selector)
        return b

    def key(self, key: str, code: str | None = None, shift: bool = False) -> None:
        mods = 8 if shift else 0
        vk = {"ArrowLeft": 37, "ArrowRight": 39, "Enter": 13, "Escape": 27, "Home": 36, "End": 35}.get(key, 0)
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code or key, modifiers=mods,
                      windowsVirtualKeyCode=vk)

    def type(self, text: str) -> None:
        self.call("Input.insertText", text=text)

    # -- teardown --------------------------------------------------------------------------------------

    def close(self) -> None:
        if getattr(self, "ws", None):
            self.ws.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self) -> "Chrome":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

"""Cut the demo: cards and recorded takes -> one 1920x1200, 30 fps H.264 MP4, every frame drawn here.

The takes are CDP screencast frames (2880x1800) with a log of when each arrived and where the pointer was. For an
output frame at segment time u, the source time is ``src_from + u * speed`` and the frame shown is the last one
received by then; the cursor is drawn at its logged position, and a click draws a ripple. A sped-up stretch carries
a visible "xN" badge. The terminal picture-in-picture is term.py's rendering of the real session's events up to the
same source time.
"""

from __future__ import annotations

import bisect
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from term import Term, events, frame_shadowed

W, H, FPS = 1920, 1200, 30
K = W / 1440                      # CSS px -> output px
SANS = "/System/Library/Fonts/HelveticaNeue.ttc"
CAP_FONT = ImageFont.truetype(SANS, 36, index=10) if False else ImageFont.truetype(SANS, 36, index=1)
BADGE_FONT = ImageFont.truetype(SANS, 30, index=1)


class Takes:
    """One or more take folders (frames/ + log.jsonl) on one clock."""

    def __init__(self, *dirs: Path) -> None:
        self.frames: list[tuple[float, Path]] = []
        self.cursor: list[tuple[float, float, float, bool]] = []
        self.clicks: list[tuple[float, float, float]] = []
        self.notes: list[dict] = []
        for d in dirs:
            d = Path(d)
            for line in (d / "log.jsonl").read_text().splitlines():
                r = json.loads(line)
                k = r["kind"]
                if k == "frame":
                    self.frames.append((r["t"], d / "frames" / f"{r['n']:06d}.jpg"))
                elif k == "cursor":
                    self.cursor.append((r["t"], r["x"], r["y"], r.get("down", False)))
                elif k in ("click",):
                    self.clicks.append((r["t"], r["x"], r["y"]))
                else:
                    self.notes.append(r)
        self.frames.sort()
        self.cursor.sort()
        self.ft = [f[0] for f in self.frames]
        self.ct = [c[0] for c in self.cursor]
        self._cache: tuple[Path, Image.Image] | None = None

    def first(self, kind: str, **match) -> dict:
        return next(n for n in self.notes if n["kind"] == kind and all(n.get(k) == v for k, v in match.items()))

    def frame(self, t: float) -> Image.Image:
        i = max(0, bisect.bisect_right(self.ft, t) - 1)
        p = self.frames[i][1]
        if not self._cache or self._cache[0] != p:
            self._cache = (p, Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS))
        return self._cache[1].copy()

    def pointer(self, t: float):
        i = bisect.bisect_right(self.ct, t) - 1
        return None if i < 0 else self.cursor[i]


ARROW = [(0, 0), (0, 25), (6, 19), (10.5, 29), (14.5, 27.3), (10.2, 17.8), (18, 17.6)]


def draw_cursor(img: Image.Image, x: float, y: float) -> None:
    s = 1.25
    pts = [(x * K + px * s, y * K + py * s) for px, py in ARROW]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(a + 2, b + 3) for a, b in pts], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(3))
    img.paste(shadow, (0, 0), shadow)
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(255, 255, 255), outline=(20, 20, 20))
    d.line(pts + [pts[0]], fill=(20, 20, 20), width=2)


def draw_ripple(img: Image.Image, x: float, y: float, age: float) -> None:
    if not 0 <= age < 0.5:
        return
    r = 10 + 46 * age / 0.5
    a = int(170 * (1 - age / 0.5))
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([x * K - r, y * K - r, x * K + r, y * K + r], outline=(184, 134, 42, a), width=5)
    img.paste(ov, (0, 0), ov)


def pill(img: Image.Image, text: str, cx: float, cy: float, font=CAP_FONT, fg=(255, 255, 255), bg=(22, 24, 29, 222),
         pad=(30, 16), alpha: float = 1.0) -> None:
    if not text or alpha <= 0:
        return
    tw = font.getlength(text)
    asc, desc = font.getmetrics()
    w, h = tw + 2 * pad[0], asc + desc + 2 * pad[1]
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], h / 2, fill=bg[:3] + (int(bg[3] * alpha),))
    d.text((cx - tw / 2, cy - h / 2 + pad[1]), text, font=font, fill=fg + (int(255 * alpha),))
    img.paste(ov, (0, 0), ov)


def badge(img: Image.Image, text: str, x: float = W - 40, y: float = 40) -> None:
    """Top-right speed badge, e.g. 'x16'."""
    if not text:
        return
    f = BADGE_FONT
    tw = f.getlength(text)
    asc, desc = f.getmetrics()
    w, h = tw + 36, asc + desc + 18
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle([x - w, y, x, y + h], 12, fill=(226, 194, 92, 240))
    d.text((x - w + 18, y + 9), text, font=f, fill=(27, 20, 12))
    img.paste(ov, (0, 0), ov)


class Writer:
    def __init__(self, path: Path) -> None:
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-tune", "stillimage",
             "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
        self.n = 0
        self.marks: list[tuple[float, str]] = []

    def put(self, img: Image.Image) -> None:
        self.p.stdin.write(img.convert("RGB").tobytes())
        self.n += 1

    def mark(self, label: str) -> None:
        self.marks.append((self.n / FPS, label))

    def close(self) -> None:
        self.p.stdin.close()
        self.p.wait()


def fade(i: int, n: int, fin: int = 8, fout: int = 8) -> float:
    return min(1.0, (i + 1) / fin if fin else 1.0, (n - i) / fout if fout else 1.0)


def card(w: Writer, png: Path, secs: float, caption: str = "", fin: int = 8, fout: int = 8) -> None:
    base = Image.open(png).convert("RGB").resize((W, H), Image.LANCZOS)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    n = int(secs * FPS)
    for i in range(n):
        img = Image.blend(black, base, fade(i, n, fin, fout))
        pill(img, caption, W / 2, H - 90)
        w.put(img)


def take(w: Writer, tk: Takes, t0: float, t1: float, speed: float = 1.0, captions=(), cursor: bool = True,
         pip: dict | None = None, badge_text: str | None = None, fin: int = 0, fout: int = 0, cap_y: float = H - 90,
         hold: float = 0.0) -> None:
    """``captions``: [(u_from, u_to, text)] in output seconds from the segment start. ``hold``: extra output
    seconds on the last frame (a still, so no badge)."""
    n = int(round((t1 - t0) / speed * FPS))
    nh = int(round(hold * FPS))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    term = None
    if pip:
        term = Term(pip.get("w", 860), pip.get("h", 470), pip.get("size", 17), pip.get("title", ""))
        evs = pip["events"]
    for i in range(n + nh):
        u = i / FPS
        s = t0 + min(i, n) / FPS * speed
        img = tk.frame(s)
        if cursor:
            p = tk.pointer(s)
            if p:
                for (ct, cx, cy) in tk.clicks:
                    draw_ripple(img, cx, cy, (s - ct) / speed if speed > 1 else s - ct)
                draw_cursor(img, p[1], p[2])
        if term:
            ti = frame_shadowed(term.render(evs, s, pip["t0"], badge=(f"x{speed:g}" if speed > 1 else "")))
            img.paste(ti, (pip["x"], pip["y"]), ti)
        if speed > 1 and i < n:
            badge(img, badge_text or f"x{speed:g}")
        for (a, b, text) in captions:
            if a <= u < b:
                al = min(1.0, (u - a) / 0.25, (b - u) / 0.25)
                pill(img, text, W / 2, cap_y, alpha=al)
        if fin or fout:
            img = Image.blend(black, img, fade(i, n + nh, fin, fout))
        w.put(img)

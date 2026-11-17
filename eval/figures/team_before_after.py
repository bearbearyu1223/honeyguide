# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""The team problem, as a figure (mechanism, no numbers). Before: every engineer asks their own agent, which searches
the code again, and each answer stays private, unchecked and gone after the chat. After: one map, built once, every
claim citing its lines and checked, and kept current by a refresh as the code changes (both measured in the post,
solid arrows); everyone reading it is the aim, untested (dashed arrows, with a key). Questions asked on it (the aim, dashed) feed back
in from the shared line all the engineers hang off.

Honey, the Honeyguide mascot, is drawn from ``assets/avatars/honey.svg`` itself (its idle pose: the layers the SVG
shows at rest), so the figure carries the page's own artwork, crisp at any size and on either theme. The SVG reader
is standard library only, so the tests import it without matplotlib. Light and dark, in the house style of the
series' figures (llm-architectures-refresher's plotting.py), with the post's condition colours: the agents on the
left are the explore condition's (blue), the map the map's (orange).

    uv run --script eval/figures/team_before_after.py [--honey assets/avatars/honey.svg] [--people 5] [--out docs/figures]

writes ``team-before-after-light.png`` and ``team-before-after-dark.png``.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SVG = "{http://www.w3.org/2000/svg}"


# -- Honey, read from the SVG ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """One visible SVG shape. ``kind`` 'path': ``segs`` is a list of (code, points) with codes M, L, C, Q, Z in
    absolute SVG coordinates; 'ellipse': ``geom`` is (cx, cy, rx, ry, rotation in degrees, clockwise in SVG)."""

    kind: str
    fill: str | None
    stroke: str | None
    width: float
    opacity: float
    segs: tuple = ()
    geom: tuple = ()


def path_segments(d: str) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
    """An SVG path's ``d`` as absolute segments: M, L, C (cubic), Q (quadratic), Z. Handles M L H V C S Q Z and their
    implicit repeats; relative commands raise (honey.svg uses none)."""
    toks = re.findall(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", d)
    out: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    i, cmd = 0, None
    cur = start = (0.0, 0.0)
    last_ctrl = None

    def nums(k: int) -> list[float]:
        nonlocal i
        vals = [float(t) for t in toks[i:i + k]]
        if len(vals) != k or any(re.fullmatch(r"[A-Za-z]", t) for t in toks[i:i + k]):
            raise ValueError(f"path: {cmd} needs {k} numbers at token {i}")
        i += k
        return vals

    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd.islower() and cmd != "z":
                raise ValueError(f"path: relative command '{cmd}' not supported")
        elif cmd is None:
            raise ValueError("path: numbers before a command")
        if cmd in "Zz":
            out.append(("Z", ()))
            cur, last_ctrl = start, None
            cmd = None
            continue
        if cmd == "M":
            x, y = nums(2)
            out.append(("M", ((x, y),)))
            cur = start = (x, y)
            cmd, last_ctrl = "L", None       # pairs after an M are line-tos
        elif cmd in "LHV":
            if cmd == "L":
                x, y = nums(2)
            elif cmd == "H":
                x, y = nums(1)[0], cur[1]
            else:
                x, y = cur[0], nums(1)[0]
            out.append(("L", ((x, y),)))
            cur, last_ctrl = (x, y), None
        elif cmd in "CS":
            if cmd == "C":
                x1, y1, x2, y2, x, y = nums(6)
            else:
                x2, y2, x, y = nums(4)
                x1, y1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
            out.append(("C", ((x1, y1), (x2, y2), (x, y))))
            cur, last_ctrl = (x, y), (x2, y2)
        elif cmd == "Q":
            x1, y1, x, y = nums(4)
            out.append(("Q", ((x1, y1), (x, y))))
            cur, last_ctrl = (x, y), None
        else:
            raise ValueError(f"path: command '{cmd}' not supported")
    return out


def parse_honey(text: str) -> tuple[tuple[float, float, float, float], tuple[Shape, ...]]:
    """honey.svg's viewBox and the shapes it shows at rest, in document order. Anything under an ``opacity="0"``
    layer (the trail, the other eyes and mouths, the sparkles, the honey drop) is left out, as is the style sheet."""
    root = ET.fromstring(text)
    box = tuple(float(v) for v in root.get("viewBox").split())
    shapes: list[Shape] = []

    def walk(el, opacity: float) -> None:
        op = opacity * float(el.get("opacity", "1"))
        if op == 0:
            return
        tag = el.tag.replace(SVG, "")
        fill, stroke = el.get("fill"), el.get("stroke")
        fill = None if fill in (None, "none") else fill
        stroke = None if stroke in (None, "none") else stroke
        width = float(el.get("stroke-width", "1"))
        if tag == "path":
            shapes.append(Shape("path", fill, stroke, width, op, tuple(path_segments(el.get("d")))))
        elif tag in ("ellipse", "circle"):
            cx, cy = float(el.get("cx")), float(el.get("cy"))
            rx = float(el.get("rx", el.get("r", "0")))
            ry = float(el.get("ry", el.get("r", "0")))
            rot = 0.0
            m = re.match(r"rotate\(([-\d.]+)", el.get("transform", ""))
            if m:
                rot = float(m.group(1))
            shapes.append(Shape("ellipse", fill, stroke, width, op, geom=(cx, cy, rx, ry, rot)))
        for child in el:
            if child.tag.replace(SVG, "") != "style":
                walk(child, op)

    walk(root, 1.0)
    if not shapes:
        raise ValueError("honey.svg: no visible shapes")
    return box, tuple(shapes)


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``agent`` is slot 1 (blue, the explore
    condition: an agent searching the code), ``map`` slot 2 (orange, the map condition)."""

    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    box: str
    edge: str
    agent: str
    map: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#f1f0ec", "#c3c2b7", "#2a78d6", "#eb6834")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#252524", "#383835", "#3987e5", "#d95926")
THEMES = (LIGHT, DARK)


def draw(honey: tuple, people: int, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, PathPatch, Wedge
    from matplotlib.path import Path as MPath

    rc = {"figure.facecolor": theme.surface, "savefig.facecolor": theme.surface, "text.color": theme.ink,
          "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
          "font.size": 12}
    W, H, FW, Y0 = 24.0, 11.4, 13.0, 0.3
    pt_per_unit = FW / W * 72
    with plt.rc_context(rc):
        fig, ax = plt.subplots(figsize=(FW, FW * (H - Y0) / W))
        fig.subplots_adjust(0, 0, 1, 1)
        ax.set_xlim(0, W)
        ax.set_ylim(Y0, H)
        ax.set_axis_off()

        def text(x, y, s, size=12, color=None, bold=False, ha="center", va="center", **kw):
            ax.text(x, y, s, ha=ha, va=va, fontsize=size, color=color or theme.ink,
                    fontweight="bold" if bold else "normal", linespacing=1.3, zorder=5, **kw)

        def rbox(x0, y0, w, h, fc=None, ec=None, lw=1.3, ls="-", r=0.18, z=2, alpha=1.0):
            ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc or theme.box,
                                        ec=ec or theme.edge, lw=lw, ls=ls, zorder=z, alpha=alpha))

        def arrow(a, b, color, lw=1.8, ls="-", rad=0.0):
            ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=15, color=color, lw=lw, ls=ls,
                                         connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0, zorder=3))

        def dashed_arrow(a, b, color, lw=1.8, head=0.32):
            """A dashed shaft with a solid head (a dashed FancyArrowPatch dashes its head too). Horizontal only."""
            ax.plot([a[0], b[0] - head], [a[1], b[1]], color=color, lw=lw, ls=(0, (4, 3)), zorder=3)
            arrow((b[0] - head - 0.02, b[1]), b, color, lw=lw)

        def person(x, y, color):
            ax.add_patch(Circle((x, y + 0.3), 0.26, fc=color, ec="none", zorder=4))
            ax.add_patch(Wedge((x, y - 0.38), 0.48, 0, 180, fc=color, ec="none", zorder=4))

        def lines(x0, y, w, n, color, gap=0.26, lw=3.0, alpha=1.0):
            for k in range(n):
                ax.plot([x0, x0 + w * (1.0 if k < n - 1 else 0.6)], [y - k * gap] * 2, color=color, lw=lw,
                        solid_capstyle="round", zorder=4, alpha=alpha)

        def tick(x, y, color, s=0.17):
            ax.plot([x - s, x - s * 0.25, x + s * 1.1], [y, y - s * 0.8, y + s * 0.9], color=color, lw=2.4,
                    solid_capstyle="round", solid_joinstyle="round", zorder=5)

        def mascot(cx, cy, size):
            (bx, by, bw, bh), shapes = honey
            k = size / bw

            def to(p):
                return (cx - size / 2 + (p[0] - bx) * k, cy + size / 2 - (p[1] - by) * k)

            for s in shapes:
                lw = s.width * k * pt_per_unit
                if s.kind == "ellipse":
                    ex, ey, rx, ry, rot = s.geom
                    patch = Ellipse(to((ex, ey)), 2 * rx * k, 2 * ry * k, angle=-rot)
                else:
                    verts, codes = [], []
                    for code, pts in s.segs:
                        if code == "Z":
                            verts.append(verts[-1] if verts else (0, 0))
                            codes.append(MPath.CLOSEPOLY)
                            continue
                        verts += [to(p) for p in pts]
                        codes += {"M": [MPath.MOVETO], "L": [MPath.LINETO], "C": [MPath.CURVE4] * 3,
                                  "Q": [MPath.CURVE3] * 2}[code]
                    patch = PathPatch(MPath(verts, codes))
                patch.set(fc=s.fill or "none", ec=s.stroke or "none", lw=lw if s.stroke else 0, alpha=s.opacity,
                          joinstyle="round", capstyle="round", zorder=6)
                ax.add_patch(patch)

        rows = [9.0 - i * (6.0 / max(people - 1, 1)) for i in range(people)]
        mid = (rows[0] + rows[-1]) / 2

        # ---- before -----------------------------------------------------------------------------------------------
        text(0.3, 10.75, "Before: everyone asks their own agent", size=16, bold=True, ha="left")
        text(1.0, 9.9, "engineer", size=11.5, color=theme.secondary)
        text(3.65, 9.9, "own agent", size=11.5, color=theme.secondary)
        text(7.55, 9.9, "private answer", size=11.5, color=theme.secondary)
        for y in rows:
            person(1.0, y, theme.muted)
            arrow((1.65, y), (2.45, y), theme.muted)
            rbox(2.45, y - 0.42, 2.4, 0.84, ec=theme.agent, lw=1.6)
            text(3.65, y + 0.12, "searches", size=11)
            text(3.65, y - 0.2, "the code again", size=11, color=theme.secondary)
            arrow((4.85, y), (5.75, y), theme.muted)
            rbox(5.75, y - 0.45, 3.6, 0.9, fc=theme.surface, ec=theme.muted, lw=1.3, ls=(0, (4, 3)))
            lines(6.05, y + 0.17, 2.4, 2, theme.edge, gap=0.34)
            text(9.05, y, "?", size=15, bold=True, color=theme.muted)
        text(5.6, 1.35, "Each answer: checked by no one, seen by one person,\ngone when the chat ends",
             size=13, bold=True)

        # divider
        ax.plot([11.75, 11.75], [0.7, 10.9], color=theme.edge, lw=1.2, zorder=1)

        # ---- after ------------------------------------------------------------------------------------------------
        text(12.3, 10.75, "The aim: one shared map", size=16, bold=True, ha="left")
        # the code, and the two ways into the map
        rbox(14.3, 9.15, 2.9, 0.95, ec=theme.edge)
        text(15.75, 9.62, "the code", size=12.5, bold=True)
        mx0, mx1, my0, my1 = 13.0, 19.9, mid - 2.15, mid + 2.15
        arrow((15.0, 9.15), (15.0, my1), theme.map, lw=2.4)
        text(14.8, (9.15 + my1) / 2, "built once", size=12, bold=True, ha="right", color=theme.ink)
        arrow((16.5, 9.15), (16.5, my1), theme.map, lw=2.0)
        text(16.7, (9.15 + my1) / 2, "refreshed as\nthe code changes", size=12, ha="left", color=theme.ink)
        # the map card
        rbox(mx0, my0, mx1 - mx0, my1 - my0, fc=theme.box, ec=theme.map, lw=2.4, r=0.3)
        mascot(mx0 + 0.95, my1 - 0.85, 1.35)
        text(mx0 + 1.85, my1 - 0.62, "one shared map", size=14, bold=True, ha="left")
        text(mx0 + 1.85, my1 - 1.0, "every claim cites its lines\nand is checked", size=11, ha="left",
             va="top", color=theme.secondary)
        for k in range(4):
            yy = my1 - 2.2 - k * 0.56
            tick(mx0 + 0.75, yy, theme.map)
            lines(mx0 + 1.3, yy, 3.0 - 0.45 * (k % 2), 1, theme.edge)
            rbox(mx0 + 4.75, yy - 0.2, 1.4, 0.4, fc=theme.surface, ec=theme.map, lw=1.1, r=0.12)
            text(mx0 + 5.45, yy, "cited lines", size=9.5, color=theme.secondary)
        # read by all (the aim, untested): stub -> bus -> one dashed arrow into each engineer
        bus, px = 20.75, 23.2
        ax.plot([mx1, bus], [mid, mid], color=theme.map, lw=2.0, ls=(0, (4, 3)), zorder=3)
        ax.plot([bus, bus], [rows[-1], rows[0]], color=theme.map, lw=2.0, ls=(0, (4, 3)), zorder=3)
        for y in rows:
            dashed_arrow((bus, y), (px - 0.62, y), theme.map, lw=1.8)
            person(px, y, theme.muted)
        text(21.75, rows[0] + 0.85, "read by all", size=12, bold=True)
        # questions asked on it feed back in: from the shared bus all five hang off, not from any one engineer
        fy = 1.95
        # a team adding questions back is the aim too (untested), so it is dashed like "read by all"
        ax.plot([bus, bus, (mx0 + mx1) / 2], [rows[-1], fy, fy], color=theme.map, lw=1.6, zorder=3,
                ls=(0, (4, 3)))
        cx = (mx0 + mx1) / 2   # vertical: dashed shaft, then a short solid segment for the head
        ax.plot([cx, cx], [fy, my0 - 0.45], color=theme.map, lw=1.6, ls=(0, (4, 3)), zorder=3)
        arrow((cx, my0 - 0.5), (cx, my0), theme.map, lw=1.6)
        text(18.0, 1.35, "questions asked on it, and their checked answers, are added to it", size=12.5,
             bold=True)
        # key: which arrows this post measures
        ky = 0.62
        arrow((16.5, ky), (17.4, ky), theme.map, lw=2.0)
        text(17.6, ky, "measured here", size=11.5, color=theme.secondary, ha="left")
        dashed_arrow((20.1, ky), (21.0, ky), theme.map, lw=2.0)
        text(21.2, ky, "the aim, untested", size=11.5, color=theme.secondary, ha="left")

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--honey", default=str(ROOT / "assets" / "avatars" / "honey.svg"))
    ap.add_argument("--people", type=int, default=5, help="engineers drawn per side (the post's opening has five)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    honey = parse_honey(Path(args.honey).read_text())
    for theme in THEMES:
        print(draw(honey, args.people, theme, Path(args.out) / f"team-before-after-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

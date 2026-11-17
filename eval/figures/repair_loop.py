# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""The repair loop, as a figure: a claim the Checker turns down goes back to the Cartographer for repair, at most
two rounds per pass, and a claim still not supported after that is flagged under "Needs a look".

Every number on it is parsed from the ``checker`` block of ``outputs/runs.txt`` (the post's runs-checker receipt),
nanochat's run 2; none is typed here. Light and dark, in the house style of the series' figures
(llm-architectures-refresher's plotting.py: the same surfaces, inks and categorical colours).

    uv run --script eval/figures/repair_loop.py [--runs outputs/runs.txt] [--repo nanochat] [--out docs/figures]

writes ``repair-loop-light.png`` and ``repair-loop-dark.png``. The parsing is standard library only, so the tests
import it without matplotlib.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# -- the numbers, parsed from the receipt ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairLoop:
    """One repo's run 2 through the repair pass: verdicts before repair and after each round, and what each round did."""

    repo: str
    supported: tuple[int, int, int]      # before repair, after round 1, after round 2
    not_supported: tuple[int, int, int]
    anchors: tuple[int, int]             # anchors replaced, rounds 1 and 2
    more_lines: tuple[int, int]          # of those, the new anchors cover more source lines
    rewritten: tuple[int, int]
    retired: tuple[int, int]

    @property
    def total(self) -> int:
        return self.supported[0] + self.not_supported[0]

    @property
    def back_supported(self) -> tuple[int, int]:
        """Claims that came back supported in round 1 and in round 2."""
        return (self.supported[1] - self.supported[0], self.supported[2] - self.supported[1])


def block(text: str, name: str) -> str:
    """The body of a runs.txt block: from its ``name`` line over a rule of dashes to the next block's heading."""
    m = re.search(rf"^{re.escape(name)}\n-+\n(.*?)(?=^\S[^\n]*\n-{{10,}}\n|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no '{name}' block")
    return m.group(1)


def parse(text: str, repo: str = "nanochat") -> RepairLoop:
    """The ``checker`` block's run 2 rows for ``repo``; raises if a row is missing or the counts don't add up."""
    body = block(text, "checker")
    num = r"\s+(\d+)"

    def stage(label: str) -> tuple[int, int, int, int]:
        m = re.search(rf"^\s+{re.escape(repo)}\s+{re.escape(label)}{num * 4}\s*$", body, re.M)
        if not m:
            raise ValueError(f"checker: no '{repo} {label}' row")
        return tuple(int(x) for x in m.groups())

    def did(rnd: int) -> tuple[int, int, int, int]:
        m = re.search(rf"^\s+{re.escape(repo)}\s+{rnd}{num * 4}\s*$", body, re.M)
        if not m:
            raise ValueError(f"checker: no '{repo}' repair row for round {rnd}")
        return tuple(int(x) for x in m.groups())

    s0, s1, s2 = (stage(x) for x in ("run 2 before repair", "after repair round 1", "after repair round 2"))
    d1, d2 = did(1), did(2)
    loop = RepairLoop(repo, (s0[0], s1[0], s2[0]), (s0[1], s1[1], s2[1]), (d1[0], d2[0]), (d1[1], d2[1]),
                      (d1[2], d2[2]), (d1[3], d2[3]))
    # every claim not supported going into a round takes exactly one repair action in it
    for r in (0, 1):
        acted = loop.anchors[r] + loop.rewritten[r] + loop.retired[r]
        if acted != loop.not_supported[r]:
            raise ValueError(f"round {r + 1}: {acted} repair actions for {loop.not_supported[r]} claims not supported")
    return loop


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``yes`` / ``no`` are its slot 3 (green) and
    slot 2 (orange), the one colour each for supported and not supported."""

    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    box: str
    edge: str
    yes: str
    no: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#f1f0ec", "#c3c2b7", "#1baf7a", "#eb6834")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#252524", "#383835", "#199e70", "#d95926")
THEMES = (LIGHT, DARK)


def draw(loop: RepairLoop, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

    rc = {"figure.facecolor": theme.surface, "savefig.facecolor": theme.surface, "text.color": theme.ink,
          "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
          "font.size": 11}
    with plt.rc_context(rc):
        fig, ax = plt.subplots(figsize=(13.5, 5.6))
        ax.set_xlim(0, 18)
        ax.set_ylim(0, 7.4)
        ax.set_axis_off()

        def box(cx, cy, w, h, title, sub=None, edge=None, lw=1.2):
            ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.18",
                                        fc=theme.box, ec=edge or theme.edge, lw=lw, zorder=2))
            if sub:
                ax.text(cx, cy + 0.2, title, ha="center", va="center", fontsize=12, fontweight="bold", zorder=3)
                ax.text(cx, cy - 0.28, sub, ha="center", va="center", fontsize=10, color=theme.secondary, zorder=3)
            else:
                ax.text(cx, cy, title, ha="center", va="center", fontsize=12, fontweight="bold", zorder=3)

        def arrow(a, b, color, rad=0.0, lw=1.6, ls="-"):
            ax.add_patch(FancyArrowPatch(a, b, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>", mutation_scale=16,
                                         color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0, zorder=1))

        def note(x, y, s, color=None, bold=False, size=10, ha="center", va="center"):
            ax.text(x, y, s, ha=ha, va=va, fontsize=size, color=color or theme.secondary,
                    fontweight="bold" if bold else "normal", linespacing=1.35, zorder=3)

        y = 5.3
        # a claim -> the Checker -> supported? -> yes: its evidence shape
        box(1.75, y, 2.9, 1.3, "A claim", "and the lines it cites")
        box(5.9, y, 3.1, 1.3, "The Checker", "re-reads the cited lines")
        dx, dy, hw, hh = 9.6, y, 1.2, 0.85
        ax.add_patch(Polygon([(dx - hw, dy), (dx, dy + hh), (dx + hw, dy), (dx, dy - hh)], closed=True,
                             fc=theme.box, ec=theme.edge, lw=1.2, zorder=2))
        note(dx, dy, "supported?", color=theme.ink, bold=True, size=11.5)
        ex = 14.6
        box(ex, y, 4.0, 1.3, "Its evidence shape", "on the page", edge=theme.yes, lw=1.8)

        arrow((3.2, y), (4.35, y), theme.muted)
        note(3.775, y + 0.55, f"{loop.total}", color=theme.ink, bold=True, size=11)
        note(3.775, y + 0.25, "claims", size=9.5)
        arrow((7.45, y), (dx - hw, y), theme.muted)
        arrow((dx + hw, y), (ex - 2.0, y), theme.yes, lw=2.2)
        note((dx + hw + ex - 2.0) / 2, y + 0.3, "yes", color=theme.yes, bold=True, size=11)
        b1, b2 = loop.back_supported
        note(ex, y + 0.95, f"{loop.supported[2]} of {loop.total} at the end", color=theme.yes, bold=True,
             va="bottom")
        note(ex, y - 0.9, f"{loop.supported[0]} at once, +{b1} after round 1, +{b2} after round 2", va="top",
             size=9.5)

        # no -> the Cartographer repairs it
        ry, rw, rh = 1.75, 8.9, 2.3
        rcx = dx
        top = ry + rh / 2
        arrow((dx, dy - hh), (dx, top), theme.no, lw=2.2)
        note(dx + 0.2, (dy - hh + top) / 2, "no", color=theme.no, bold=True, size=11, ha="left")
        note(dx + 0.65, (dy - hh + top) / 2, f"{loop.not_supported[0]} of {loop.total}", ha="left")
        ax.add_patch(FancyBboxPatch((rcx - rw / 2, ry - rh / 2), rw, rh, boxstyle="round,pad=0,rounding_size=0.18",
                                    fc=theme.box, ec=theme.no, lw=1.8, zorder=2))
        note(rcx, ry + 0.78, "The Cartographer repairs it", color=theme.ink, bold=True, size=12)
        note(rcx, ry + 0.36, "cite more lines  ·  narrow the claim  ·  retire it", size=10.5)
        a, m, w, r = loop.anchors, loop.more_lines, loop.rewritten, loop.retired
        x0 = rcx - rw / 2 + 0.35
        for i, yy in ((0, ry - 0.2), (1, ry - 0.68)):
            more = (f" (all {m[i]} cite more lines)" if m[i] == a[i] else f" ({m[i]} cite more lines)") if i == 0 else ""
            note(x0, yy, f"round {i + 1}", color=theme.no, bold=True, ha="left")
            note(x0 + 0.95, yy, f"{a[i]} anchors replaced{more}, {w[i]} rewritten, {r[i]} retired",
                 color=theme.ink, ha="left")

        # back to the Checker: only the claims that changed, at most two rounds per pass
        arrow((rcx - rw / 2, ry), (5.9, y - 0.65), theme.no, rad=-0.3, lw=1.8)
        note(2.6, 3.1, "re-check only the\nclaims that changed", color=theme.ink, bold=True, size=10.5)
        note(2.6, 2.3, "at most 2 rounds per pass", size=10)
        note(2.6, 1.65, f"not supported after round 1: {loop.not_supported[1]}\n"
             f"after round 2: {loop.not_supported[2]}", color=theme.no)

        # still not supported after round 2 -> flagged
        fx = 16.7
        box(fx, ry, 2.5, 1.5, "Flagged", "under Needs a look", edge=theme.no)
        arrow((rcx + rw / 2, ry), (fx - 1.25, ry), theme.no, ls=(0, (4, 3)))
        note((rcx + rw / 2 + fx - 1.25) / 2, ry + 0.42, "still no after\nround 2", size=9.5)
        note(fx, ry - 0.95, f"{loop.not_supported[2]} on {loop.repo}'s run 2", color=theme.no, bold=True, va="top")

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", default=str(ROOT / "outputs" / "runs.txt"))
    ap.add_argument("--repo", default="nanochat")
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    loop = parse(Path(args.runs).read_text(), args.repo)
    for theme in THEMES:
        print(draw(loop, theme, Path(args.out) / f"repair-loop-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

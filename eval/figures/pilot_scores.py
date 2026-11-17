# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""The pilot's scores, as a figure: on lookup questions every condition that can read the code ties near the
ceiling, and the gap is the condition that cannot (no-access).

Left: the mean score per run for each question type and condition (the ``by type`` block). Right: the paired
differences over questions with their 95% CIs (the ``paired differences by question`` block). The capture prints no
per-type CIs, so the left panel draws none. Every number is parsed from ``outputs/eval_pilot_nanochat.txt``; none is
typed here. Light and dark, in the house style of the series' figures (llm-architectures-refresher's plotting.py:
the same surfaces, inks and categorical colours), one colour per condition across the post: grey no-access,
blue explore, green outline, orange map.

    uv run --script eval/figures/pilot_scores.py [--eval outputs/eval_pilot_nanochat.txt] [--out docs/figures]

writes ``pilot-scores-light.png`` and ``pilot-scores-dark.png``. The parsing is standard library only, so the tests
import it without matplotlib.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LOOKUPS = ("locate", "callers", "flow")          # the types scored against a key; why/how is graded
TYPE_LABEL = {"locate": "locate", "callers": "callers", "flow": "flow", "whyhow": "why/how"}


# -- the numbers, parsed from the receipt ------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeRow:
    qtype: str
    questions: int
    means: dict[str, float]              # condition -> mean score per run


@dataclass(frozen=True)
class Diff:
    a: str
    b: str
    mean: float
    lo: float
    hi: float
    n: int


@dataclass(frozen=True)
class Pilot:
    conditions: tuple[str, ...]          # in the receipt's column order
    types: tuple[TypeRow, ...]
    diffs: tuple[Diff, ...]
    grader: str                          # who graded why/how blind
    resamples: int

    def row(self, qtype: str) -> TypeRow:
        for r in self.types:
            if r.qtype == qtype:
                return r
        raise KeyError(qtype)

    def diff(self, a: str, b: str) -> Diff:
        for d in self.diffs:
            if (d.a, d.b) == (a, b):
                return d
        raise KeyError(f"{a} - {b}")


def block(text: str, heading: str) -> str:
    """The body of a capture block whose heading line starts with ``heading``: from below its rule of dashes to the
    next block's heading."""
    m = re.search(rf"^{re.escape(heading)}[^\n]*\n-{{10,}}\n(.*?)(?=^\S[^\n]*\n-{{10,}}\n|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no '{heading}' block")
    return m.group(1)


def parse(text: str) -> Pilot:
    body = block(text, "by type")
    head = re.search(r"^\s+type\s+questions\s+(.+?)\s*$", body, re.M)
    if not head:
        raise ValueError("by type: no header row")
    conditions = tuple(head.group(1).split())
    num = r"\s+([\d.]+)"
    types = []
    for qtype in TYPE_LABEL:
        m = re.search(rf"^\s+{qtype}\s+(\d+){num * len(conditions)}\s*$", body, re.M)
        if not m:
            raise ValueError(f"by type: no '{qtype}' row")
        types.append(TypeRow(qtype, int(m.group(1)), dict(zip(conditions, (float(x) for x in m.groups()[1:]), strict=True))))

    body = block(text, "paired differences by question")
    sgn = r"([+-]\d+\.\d+)"
    diffs = tuple(Diff(a, b, float(m_), float(lo), float(hi), int(n)) for a, b, m_, lo, hi, n in re.findall(
        rf"^\s+(\S+) - (\S+)\s+{sgn}\s+\[{sgn}, {sgn}\]\s+n=(\d+)\s*$", body, re.M))
    if not diffs:
        raise ValueError("paired differences: no rows")
    rs = re.search(r"95% CI from (\d+) bootstrap resamples", re.sub(r"\s+", " ", body))
    if not rs:
        raise ValueError("paired differences: no resample count")
    for d in diffs:
        if not d.lo <= d.mean <= d.hi:
            raise ValueError(f"{d.a} - {d.b}: mean {d.mean} outside its CI")
        if {d.a, d.b} - set(conditions):
            raise ValueError(f"{d.a} - {d.b}: not a condition of the by type block")

    g = re.search(r"grader: ChatGPT \(([^)]+)\)", block(text, "why/how (graded blind)"))
    if not g:
        raise ValueError("why/how (graded blind): no grader")
    return Pilot(conditions, tuple(types), diffs, g.group(1), int(rs.group(1)))


def takeaway(p: Pilot) -> str:
    """The title, checked against the numbers: on every lookup type the conditions with the code sit within 0.1 of
    each other at 0.9 or above, and no-access sits below all of them."""
    for t in LOOKUPS:
        r = p.row(t)
        access = [v for c, v in r.means.items() if c != "no-access"]
        if min(access) < 0.9 or max(access) - min(access) > 0.1:
            raise ValueError(f"{t}: the conditions with the code don't tie near the ceiling: {r.means}")
        if r.means["no-access"] >= min(access):
            raise ValueError(f"{t}: no-access is not the gap: {r.means}")
    return "On lookups, every agent that can read the code ties near the ceiling; the gap is no-access"


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces, inks and the categorical slots from llm-architectures-refresher's plotting.py; the conditions take
    slot 1 (blue) explore, slot 3 (green) outline, slot 2 (orange) map, and the muted grey no-access."""

    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    axis: str
    cond: dict


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7",
              {"no-access": "#898781", "explore": "#2a78d6", "outline": "#1baf7a", "map": "#eb6834"})
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835",
             {"no-access": "#898781", "explore": "#3987e5", "outline": "#199e70", "map": "#d95926"})
THEMES = (LIGHT, DARK)
MARKER = {"no-access": "o", "explore": "s", "outline": "D", "map": "^"}


def style(theme: Theme) -> dict:
    """plotting.styled()'s rcParams for one theme."""
    return {"figure.facecolor": theme.surface, "axes.facecolor": theme.surface, "savefig.facecolor": theme.surface,
            "axes.edgecolor": theme.axis, "axes.labelcolor": theme.secondary, "axes.titlecolor": theme.ink,
            "axes.grid": True, "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
            "grid.color": theme.grid, "grid.linewidth": 0.8, "xtick.color": theme.muted, "ytick.color": theme.muted,
            "xtick.labelcolor": theme.secondary, "ytick.labelcolor": theme.secondary, "text.color": theme.ink,
            "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
            "font.size": 12, "axes.titlesize": 13.5, "axes.titleweight": "bold", "legend.frameon": False,
            "legend.fontsize": 11.5, "axes.unicode_minus": False}


def draw(p: Pilot, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    title = takeaway(p)
    with plt.rc_context(style(theme)):
        fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.5, 6.4), gridspec_kw={"width_ratios": [1.55, 1], "wspace": 0.42})
        fig.subplots_adjust(top=0.78)
        fig.suptitle(title, x=0.06, ha="left", y=0.995, fontsize=15, fontweight="bold")

        # left: mean score per question type, one dot per condition, dodged so ties stay visible
        order = [t.qtype for t in p.types]
        k = len(p.conditions)
        step = 0.19
        for i, t in enumerate(p.types):
            y0 = len(order) - 1 - i
            for j, c in enumerate(p.conditions):
                y = y0 + (k - 1) / 2 * step - j * step
                v = t.means[c]
                ax.scatter([v], [y], s=78, marker=MARKER[c], color=theme.cond[c], zorder=3,
                           edgecolors=theme.surface, linewidths=0.8)
                ax.text(v - 0.018, y, f"{v:.2f}", ha="right", va="center", fontsize=9.5, color=theme.secondary)
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels([f"{TYPE_LABEL[t.qtype]}\n{t.questions} questions" for t in reversed(p.types)],
                           fontsize=12)
        for lbl in ax.get_yticklabels():
            lbl.set_color(theme.ink)
        lo = min(min(t.means.values()) for t in p.types)
        ax.set_xlim(max(0.0, lo - 0.17), 1.04)
        ax.set_ylim(-0.6, len(order) - 0.4)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("mean score per run (0 to 1)")
        # why/how sits apart: it is graded, not keyed
        wh = len(order) - 1 - order.index("whyhow")
        ax.axhline(wh + 0.5, color=theme.axis, lw=1.0, ls=(0, (4, 3)))
        why = p.row("whyhow")
        ax.text(0.015, wh - 0.5, f"why/how: graded blind by {p.grader}, {why.questions} questions",
                transform=ax.get_yaxis_transform(), ha="left", va="bottom", fontsize=10.5, color=theme.secondary,
                fontstyle="italic")
        ax.set_title("Mean score by question type", loc="left", pad=34)
        handles = [Line2D([], [], ls="", marker=MARKER[c], ms=9, color=theme.cond[c], label=c) for c in p.conditions]
        ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=len(handles), borderaxespad=0.3,
                  handletextpad=0.3, columnspacing=1.2)

        # right: the paired differences over all questions, with 95% CIs
        for i, d in enumerate(p.diffs):
            y = len(p.diffs) - 1 - i
            col = theme.cond[d.a]
            bx.plot([d.lo, d.hi], [y, y], color=col, lw=2.6, solid_capstyle="butt", zorder=2)
            for e in (d.lo, d.hi):
                bx.plot([e, e], [y - 0.09, y + 0.09], color=col, lw=2.0, zorder=2)
            bx.scatter([d.mean], [y], s=80, marker=MARKER[d.a], color=col, zorder=3, edgecolors=theme.surface,
                       linewidths=0.8)
            bx.text(d.mean, y + 0.2, f"{d.mean:+.3f}  [{d.lo:+.3f}, {d.hi:+.3f}]", ha="center", va="bottom",
                    fontsize=10.5, color=theme.ink)
        bx.axvline(0, color=theme.muted, lw=1.1, zorder=1)
        bx.set_yticks(range(len(p.diffs)))
        bx.set_yticklabels([f"{d.a} - {d.b}\n{d.n} questions" for d in reversed(p.diffs)], fontsize=12)
        for lbl in bx.get_yticklabels():
            lbl.set_color(theme.ink)
        span = max(max(abs(d.lo), abs(d.hi)) for d in p.diffs)
        bx.set_xlim(-0.25 * span, 1.15 * span)
        bx.set_ylim(-0.55, len(p.diffs) - 0.25)
        bx.grid(axis="y", visible=False)
        bx.set_xlabel("difference in mean score, all questions")
        bx.set_title("Paired difference, 95% CI", loc="left", pad=34)
        bx.text(0.0, 1.02, f"per question, then bootstrap over questions ({p.resamples:,} resamples)",
                transform=bx.transAxes, ha="left", va="bottom", fontsize=10, color=theme.secondary)

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--eval", default=str(ROOT / "outputs" / "eval_pilot_nanochat.txt"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    p = parse(Path(args.eval).read_text())
    for theme in THEMES:
        print(draw(p, theme, Path(args.out) / f"pilot-scores-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

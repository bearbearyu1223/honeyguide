# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Before and after the training cutoff, as a figure: with no access the model knows nanochat's older code but not
its newer code, and every condition that reads the repo scores the same on both.

One dot per condition in two rows (questions whose key lines last changed before the cutoff, and after it), with
the paired difference explore - no-access on the after row as a bracket. Every number is parsed from the ``learning
vs remembering`` block of ``outputs/eval_pilot_nanochat.txt`` (the cutoff date from its header); none is typed here.
Light and dark, with pilot-scores' theme, markers and condition colours (imported from pilot_scores.py, so the two
figures cannot drift apart).

    uv run --script eval/figures/cutoff_split.py [--eval outputs/eval_pilot_nanochat.txt] [--out docs/figures]

writes ``cutoff-split-light.png`` and ``cutoff-split-dark.png``. The parsing is standard library only, so the tests
import it without matplotlib.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import pilot_scores as ps  # noqa: E402

SUBSETS = ("before", "after")
NO_ACCESS = "no-access"


# -- the numbers, parsed from the receipt ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Subset:
    name: str                            # before / after
    questions: int
    means: dict[str, float]              # condition -> mean score per run


@dataclass(frozen=True)
class CutoffSplit:
    cutoff: date
    conditions: tuple[str, ...]          # in the receipt's column order
    subsets: tuple[Subset, ...]
    diffs: dict[tuple[str, str, str], ps.Diff]     # (a, b, subset) -> the paired difference
    untagged_note: bool                  # the receipt says why/how questions are in neither subset

    def subset(self, name: str) -> Subset:
        for s in self.subsets:
            if s.name == name:
                return s
        raise KeyError(name)

    @property
    def month(self) -> str:
        return self.cutoff.strftime("%B %Y")


def parse(text: str) -> CutoffSplit:
    c = re.search(r"cutoff (\d{4})-(\d{2})-(\d{2})", text)
    if not c:
        raise ValueError("header: no cutoff date")
    body = ps.block(text, "learning vs remembering")
    head = re.search(r"^\s+subset\s+questions\s+(.+?)\s*$", body, re.M)
    if not head:
        raise ValueError("learning vs remembering: no header row")
    conditions = tuple(head.group(1).split())
    if NO_ACCESS not in conditions or len(conditions) < 2:
        raise ValueError(f"learning vs remembering: conditions {conditions}")
    subsets = []
    cells = r"\s+([\d.]+)" * len(conditions)
    for name in SUBSETS:
        m = re.search(rf"^\s+{name}\s+(\d+){cells}\s*$", body, re.M)
        if not m:
            raise ValueError(f"learning vs remembering: no '{name}' row")
        subsets.append(Subset(name, int(m.group(1)),
                              dict(zip(conditions, (float(x) for x in m.groups()[1:]), strict=True))))
    sgn = r"([+-]\d+\.\d+)"
    diffs = {}
    for a, b, sub, mean, lo, hi, n in re.findall(
            rf"^\s+(\S+) - (\S+), (\S+)\s+{sgn}\s+\[{sgn}, {sgn}\]\s+n=(\d+)\s*$", body, re.M):
        d = ps.Diff(a, b, float(mean), float(lo), float(hi), int(n))
        if not d.lo <= d.mean <= d.hi:
            raise ValueError(f"{a} - {b}, {sub}: mean {d.mean} outside its CI")
        diffs[(a, b, sub)] = d
    out = CutoffSplit(date(*(int(x) for x in c.groups())), conditions, tuple(subsets), diffs,
                      "why/how questions carry no cutoff tag" in re.sub(r"\s+", " ", body))
    for s in out.subsets:
        d = out.diffs.get(("explore", NO_ACCESS, s.name))
        if d is None:
            raise ValueError(f"learning vs remembering: no 'explore - no-access, {s.name}' row")
        if d.n != s.questions:
            raise ValueError(f"explore - no-access, {s.name}: n={d.n} but {s.questions} questions")
        if f"{s.means['explore'] - s.means[NO_ACCESS]:+.3f}" != f"{d.mean:+.3f}":
            raise ValueError(f"explore - no-access, {s.name}: the means don't give the printed {d.mean:+.3f}")
    return out


def takeaway(c: CutoffSplit) -> str:
    """The title, checked against the numbers: before the cutoff no-access is within 0.1 of explore (it knows the
    older code); after it, explore - no-access has a CI above zero (it does not know the newer code); and every
    condition that reads the repo scores 0.9 or more on both."""
    before, after = c.subset("before"), c.subset("after")
    if before.means["explore"] - before.means[NO_ACCESS] > 0.1:
        raise ValueError(f"before the cutoff no-access is not close to explore: {before.means}")
    d = c.diffs[("explore", NO_ACCESS, "after")]
    if d.lo <= 0:
        raise ValueError(f"after the cutoff explore - no-access's CI [{d.lo}, {d.hi}] reaches zero")
    for s in (before, after):
        low = {k: v for k, v in s.means.items() if k != NO_ACCESS and v < 0.9}
        if low:
            raise ValueError(f"{s.name}: a condition with the repo scores under 0.9: {low}")
    return "With no access, the model knows nanochat's older code and not its newer code"


def footnote(c: CutoffSplit) -> str:
    if not c.untagged_note:
        raise ValueError("learning vs remembering: the receipt no longer says why/how questions are untagged")
    return "why/how questions carry no cutoff tag and are in neither row"


# -- the figure --------------------------------------------------------------------------------------------------------


def draw(c: CutoffSplit, theme: ps.Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    title, note = takeaway(c), footnote(c)
    with plt.rc_context(ps.style(theme)):
        fig, ax = plt.subplots(figsize=(11.5, 5.6))
        fig.subplots_adjust(top=0.80, bottom=0.2, left=0.25)
        fig.suptitle(title, x=0.03, ha="left", y=0.995, fontsize=15, fontweight="bold")

        k = len(c.conditions)
        step = 0.16
        rows = {"before": 1.15, "after": 0.0}
        ys = {}
        for s in c.subsets:
            for j, cond in enumerate(c.conditions):
                y = rows[s.name] + (k - 1) / 2 * step - j * step
                ys[(s.name, cond)] = y
                v = s.means[cond]
                ax.scatter([v], [y], s=82, marker=ps.MARKER[cond], color=theme.cond[cond], zorder=3,
                           edgecolors=theme.surface, linewidths=0.8)
                ax.text(v - 0.022, y, f"{v:.2f}", ha="right", va="center", fontsize=10, color=theme.secondary)
        ax.set_yticks([rows[s.name] for s in c.subsets])
        ax.set_yticklabels([f"{s.name} the cutoff\n{s.questions} questions" for s in c.subsets], fontsize=12.5)
        for lbl in ax.get_yticklabels():
            lbl.set_color(theme.ink)
        ax.set_xlim(-0.02, 1.08)
        ax.set_ylim(-0.42, 1.57)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("mean score per run (0 to 1)")

        # the after row's gap: a bracket from no-access to explore, above the row's highest dot
        d = c.diffs[("explore", NO_ACCESS, "after")]
        after = c.subset("after")
        x0, x1 = after.means[NO_ACCESS], after.means["explore"]
        yb = max(ys[("after", cond)] for cond in c.conditions) + 0.16
        ax.plot([x0, x0, x1, x1], [yb - 0.05, yb, yb, yb - 0.05], color=theme.ink, lw=1.4, zorder=2)
        ax.text((x0 + x1) / 2, yb + 0.04, f"explore - no-access  {d.mean:+.3f}  [{d.lo:+.3f}, {d.hi:+.3f}]",
                ha="center", va="bottom", fontsize=11, color=theme.ink,
                bbox={"fc": theme.surface, "ec": "none", "pad": 1.5}, zorder=4)
        # between the rows: under the before row's lowest dot, above the bracket's label
        ax.axhline((min(ys[("before", cond)] for cond in c.conditions) + yb + 0.14) / 2, color=theme.axis, lw=1.0,
                   ls=(0, (4, 3)))

        ax.set_title(f"Questions split by whether their code last changed before or after the training cutoff "
                     f"({c.month})",
                     loc="left", pad=34, fontsize=12.5)
        handles = [Line2D([], [], ls="", marker=ps.MARKER[cond], ms=9, color=theme.cond[cond], label=cond)
                   for cond in c.conditions]
        ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=len(handles),
                  borderaxespad=0.3, handletextpad=0.3, columnspacing=1.2)
        fig.text(0.03, 0.02, note, ha="left", va="bottom", fontsize=10.5, color=theme.secondary,
                 fontstyle="italic")

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--eval", default=str(ROOT / "outputs" / "eval_pilot_nanochat.txt"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    c = parse(Path(args.eval).read_text())
    for theme in ps.THEMES:
        print(draw(c, theme, Path(args.out) / f"cutoff-split-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Ad-hoc answers against unchecked map claims, as a figure: the same Checker finds about the same small share of
claims not supported or wrong in each, and the difference's 95% CI spans zero.

Left: the share not supported + wrong per arm, with its counts. Right: the difference (ad-hoc minus map) with its
95% CI. The spot-check review of the Checker's own verdicts is not drawn (the post explains it later, beside its
receipt), but it is still parsed and checked: ``review_note`` is the sentence the post's prose rests on, and it
refuses to say no disagreement called the Checker too lenient unless that holds. Every number is parsed from
``outputs/adhoc_check.txt`` (the comparison block and the spot-check review block); none is typed here. Light and
dark, in the house style of the series' figures (llm-architectures-refresher's plotting.py), with the post's
condition colours: the ad-hoc answers are the explore condition's (blue), the map claims the map's (orange).

    uv run --script eval/figures/adhoc_vs_map.py [--adhoc outputs/adhoc_check.txt] [--out docs/figures]

writes ``adhoc-vs-map-light.png`` and ``adhoc-vs-map-dark.png``. The parsing is standard library only, so the tests
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
class Arm:
    name: str
    units: int
    claims: int
    supported: int
    not_supported: int
    wrong: int
    share: float                         # the receipt's ns+w

    @property
    def bad(self) -> int:
        return self.not_supported + self.wrong


VERDICTS = ("supported", "not_supported", "wrong", "not_a_claim")
ARMS = ("ad-hoc answers", "map claims")
NONE = (0, 0, 0, 0)


@dataclass(frozen=True)
class Review:
    """The spot-check review of the Checker's verdicts: per verdict, items and how many the reviewer agreed with,
    in total and per arm (the spot-check sample each item came from)."""

    reviewer: str
    rows: dict[str, tuple[int, int, int, int]]     # verdict -> items, agree, change, borderline
    arms: dict[str, dict[str, tuple[int, int, int, int]]]     # arm -> verdict -> the same

    def arm(self, arm: str, verdict: str) -> tuple[int, int, int, int]:
        return self.arms.get(arm, {}).get(verdict, NONE)

    @property
    def none_lenient(self) -> bool:
        """No disagreement says the Checker was too lenient: the reviewer agreed with every 'supported' verdict and
        with every 'not_a_claim' (no change, nothing borderline), and would change no 'not_supported' verdict (a
        change there could be toward 'wrong'; the review does not record its direction). What is left is changes
        of 'wrong' verdicts and 'not_supported' ones called borderline, each on a verdict that already faults the
        claim."""
        items, agree, change, border = self.rows["supported"]
        nac = self.rows.get("not_a_claim", NONE)
        ns = self.rows.get("not_supported", NONE)
        return agree == items > 0 and change == border == 0 and nac[2] == nac[3] == 0 and ns[2] == 0


@dataclass(frozen=True)
class AdhocCheck:
    adhoc: Arm
    map: Arm
    diff: float
    lo: float
    hi: float
    answers: int                         # the ad-hoc answers the units came from
    review: Review


def block(text: str, heading: str) -> str:
    """The body of a capture block whose heading line starts with ``heading``: from below its rule of dashes to the
    next block's heading."""
    m = re.search(rf"^{re.escape(heading)}[^\n]*\n-{{10,}}\n(.*?)(?=^\S[^\n]*\n-{{10,}}\n|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no '{heading}' block")
    return m.group(1)


COUNT = r"\s+(\d+)"


def parse(text: str) -> AdhocCheck:
    body = block(text, "the comparison: ad-hoc answers against map claims")
    arms = {}
    for name in ("ad-hoc answers", "map claims"):
        m = re.search(rf"^\s+{re.escape(name)}{COUNT * 6}\s+([\d.]+)\s*$", body, re.M)
        if not m:
            raise ValueError(f"comparison: no '{name}' row")
        units, claims, supp, ns, wrong, _none, share = m.groups()
        arm = Arm(name, int(units), int(claims), int(supp), int(ns), int(wrong), float(share))
        if arm.supported + arm.bad != arm.claims:
            raise ValueError(f"{name}: {arm.supported} + {arm.bad} verdicts for {arm.claims} claims")
        if f"{arm.bad / arm.claims:.3f}" != f"{arm.share:.3f}":
            raise ValueError(f"{name}: {arm.bad} / {arm.claims} is not the printed {arm.share}")
        arms[name] = arm
    flat = re.sub(r"\s+", " ", body)
    sgn = r"([+-]\d+\.\d+)"
    d = re.search(rf"difference in ns\+w, ad-hoc minus map: {sgn}, 95% CI \[{sgn}, {sgn}\]", flat)
    if not d:
        raise ValueError("comparison: no difference line")
    diff, lo, hi = (float(x) for x in d.groups())
    if not lo <= diff <= hi:
        raise ValueError(f"difference {diff} outside its CI [{lo}, {hi}]")
    a = re.search(r"clustered by answer \((\d+) answers\)", flat)
    if not a:
        raise ValueError("comparison: no answer count")

    body = block(text, "spot-check review of the Checker's verdicts")
    r = re.search(r"reviewer: ChatGPT \(([^)]+)\)", body)
    if not r:
        raise ValueError("spot-check review: no reviewer")
    rows = {v: tuple(int(x) for x in m.groups()) for v in VERDICTS
            for m in [re.search(rf"^\s+{v}\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", body, re.M)] if m}
    if len(rows) != 4:
        raise ValueError(f"spot-check review: verdict rows {sorted(rows)}")
    by_arm: dict[str, dict[str, tuple[int, int, int, int]]] = {}
    for arm, v, *nums in re.findall(rf"^\s+({'|'.join(map(re.escape, ARMS))})\s+(\S+){COUNT * 4}\s*$", body, re.M):
        by_arm.setdefault(arm, {})[v] = tuple(int(x) for x in nums)
    if not by_arm:
        raise ValueError("spot-check review: no per-arm rows")
    for v in VERDICTS:
        summed = tuple(sum(xs) for xs in zip(*(by_arm.get(a, {}).get(v, NONE) for a in ARMS), strict=True))
        if summed != rows[v]:
            raise ValueError(f"spot-check review: {v}: the arms sum to {summed}, the total row says {rows[v]}")
    return AdhocCheck(arms["ad-hoc answers"], arms["map claims"], diff, lo, hi, int(a.group(1)),
                      Review(r.group(1), rows, by_arm))


def takeaway(c: AdhocCheck) -> str:
    """The title, checked against the numbers: the difference's CI must span zero."""
    if not c.lo < 0 < c.hi:
        raise ValueError(f"the difference's CI [{c.lo}, {c.hi}] does not span zero: the arms are not about equal")
    return "Ad-hoc answers and unchecked map claims are about equally accurate"


def review_note(c: AdhocCheck) -> str:
    """The note on the Checker's own verdicts, checked: it says no disagreement called the Checker too lenient only
    when that holds (Review.none_lenient), and gives the 'supported' items per arm, since they came from both."""
    rv = c.review
    if not rv.none_lenient:
        raise ValueError(f"the spot-check review has a disagreement on a 'supported' or 'not_a_claim' verdict, or "
                         f"a change on a 'not_supported' one: {rv.rows}")
    items, agree, _, _ = rv.rows["supported"]
    adhoc, mapc = (rv.arm(a, "supported")[0] for a in ARMS)
    w_items, _, w_change, _ = rv.rows["wrong"]
    n_items, _, _, n_border = rv.rows["not_supported"]
    return (f"Spot check by a second model ({rv.reviewer}), from a sheet without the source: it agreed with "
            f"{agree} of {items} 'supported' verdicts ({adhoc} ad-hoc, {mapc} map),\nso no disagreement said the "
            f"Checker was too lenient; it would change {w_change} of {w_items} 'wrong' verdicts and called "
            f"{n_border} of {n_items} 'not supported' borderline")


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``adhoc`` is slot 1 (blue, the explore
    condition, whose answers these are), ``map`` slot 2 (orange, the map condition)."""

    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    axis: str
    adhoc: str
    map: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6", "#eb6834")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#3987e5", "#d95926")
THEMES = (LIGHT, DARK)


def style(theme: Theme) -> dict:
    """plotting.styled()'s rcParams for one theme."""
    return {"figure.facecolor": theme.surface, "axes.facecolor": theme.surface, "savefig.facecolor": theme.surface,
            "axes.edgecolor": theme.axis, "axes.labelcolor": theme.secondary, "axes.titlecolor": theme.ink,
            "axes.grid": True, "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
            "grid.color": theme.grid, "grid.linewidth": 0.8, "xtick.color": theme.muted, "ytick.color": theme.muted,
            "xtick.labelcolor": theme.secondary, "ytick.labelcolor": theme.secondary, "text.color": theme.ink,
            "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
            "font.size": 12, "axes.titlesize": 13.5, "axes.titleweight": "bold", "legend.frameon": False,
            "axes.unicode_minus": False}


def pct(x: float) -> str:
    return f"{x * 100:+.1f}" if x else "0"


def draw(c: AdhocCheck, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    title = takeaway(c)
    with plt.rc_context(style(theme)):
        fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 5.4), gridspec_kw={"width_ratios": [1.25, 1], "wspace": 0.35})
        fig.subplots_adjust(top=0.82, bottom=0.2)
        fig.suptitle(title, x=0.06, ha="left", y=0.995, fontsize=15, fontweight="bold")

        # left: the share not supported + wrong, one bar per arm
        arms = (c.adhoc, c.map)
        cols = (theme.adhoc, theme.map)
        labels = (f"ad-hoc answers\nfrom {c.answers} answers,\nnever checked",
                  f"map claims\n{c.map.claims} sampled, before\nany Checker pass")
        top = max(a.share for a in arms) * 100
        for i, (a, col) in enumerate(zip(arms, cols, strict=True)):
            ax.bar(i, a.share * 100, width=0.55, color=col, zorder=2)
            ax.text(i, a.share * 100 + top * 0.04, f"{a.share * 100:.1f}%", ha="center", va="bottom", fontsize=15,
                    fontweight="bold", color=theme.ink)
            ax.text(i, a.share * 100 + top * 0.04 + top * 0.17, f"{a.bad} of {a.claims} claims", ha="center",
                    va="bottom", fontsize=11.5, color=theme.secondary)
        ax.set_xticks(range(len(arms)))
        ax.set_xticklabels(labels, fontsize=11.5)
        for lbl in ax.get_xticklabels():
            lbl.set_color(theme.ink)
        ax.set_xlim(-0.6, len(arms) - 0.4)
        ax.set_ylim(0, top * 1.6)
        ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
        ax.set_ylabel("claims not supported or wrong")
        ax.set_title("Share the Checker faulted", loc="left", pad=12)

        # right: the difference with its 95% CI, against zero
        y = 0
        col = theme.ink
        bx.plot([c.lo * 100, c.hi * 100], [y, y], color=col, lw=2.6, solid_capstyle="butt", zorder=2)
        for e in (c.lo, c.hi):
            bx.plot([e * 100, e * 100], [y - 0.07, y + 0.07], color=col, lw=2.0, zorder=2)
        bx.scatter([c.diff * 100], [y], s=90, color=col, zorder=3, edgecolors=theme.surface, linewidths=0.8)
        bx.text(c.diff * 100, y + 0.14, f"{pct(c.diff)} points", ha="center", va="bottom", fontsize=14,
                fontweight="bold", bbox={"fc": theme.surface, "ec": "none", "pad": 1.5}, zorder=4)
        bx.text(c.diff * 100, y - 0.14, f"95% CI [{pct(c.lo)}, {pct(c.hi)}]", ha="center", va="top", fontsize=12,
                color=theme.secondary, bbox={"fc": theme.surface, "ec": "none", "pad": 1.5}, zorder=4)
        bx.axvline(0, color=theme.muted, lw=1.1, zorder=1)
        bx.text(0, 0.62, "no difference", ha="center", va="bottom", fontsize=10.5, color=theme.secondary,
                bbox={"fc": theme.surface, "ec": "none", "pad": 1.5}, zorder=4)
        span = max(abs(c.lo), abs(c.hi)) * 100
        bx.set_xlim(-1.5 * span, 1.5 * span)
        bx.set_ylim(-0.6, 0.75)
        bx.set_yticks([])
        bx.spines["left"].set_visible(False)
        bx.grid(axis="y", visible=False)
        bx.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: pct(v / 100)))
        bx.set_xlabel("ad-hoc minus map, percentage points")
        bx.set_title("Difference, 95% CI", loc="left", pad=12)

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--adhoc", default=str(ROOT / "outputs" / "adhoc_check.txt"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    c = parse(Path(args.adhoc).read_text())
    for theme in THEMES:
        print(draw(c, theme, Path(args.out) / f"adhoc-vs-map-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

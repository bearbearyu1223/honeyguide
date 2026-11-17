# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""What keeping a shared map current costs, as a figure: refreshing it costs a fraction of rebuilding it, small for an
ordinary day and larger across a rewrite.

Two panels, $ at list price and wall-clock minutes; in each, one pair of bars (rebuild, refresh) per experiment,
annotated with the commits and days between the map's commit and the new one. Every number is parsed from the
``commits`` and ``cost`` blocks of ``outputs/refresh.txt``; none is typed here. Light and dark, in the house style of
the series' figures (llm-architectures-refresher's plotting.py), in the post's map colour (orange): a rebuild drawn
hollow, a refresh filled. When the receipt also prints a ratio against the rebuild less one pass (E3's re-check, a
pass E2's one-run rebuild has no counterpart for), the title gives both fractions as a range, a dashed line in the
rebuild bar marks where that pass starts, and the footnote says which ratio is which.

    uv run --script eval/figures/refresh_vs_rebuild.py [--refresh outputs/refresh.txt] [--out docs/figures]

writes ``refresh-vs-rebuild-light.png`` and ``refresh-vs-rebuild-dark.png``. The parsing is standard library only,
so the tests import it without matplotlib.
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
class Experiment:
    key: str                             # the receipt's id (E2, E3); not drawn
    repo: str
    what: str                            # the receipt's description after the repo name
    days: float
    commits: int
    rebuild_usd: float
    rebuild_min: float
    refresh_usd: float
    refresh_min: float
    ratio_usd: float                     # the receipt's refresh / rebuild
    ratio_min: float
    attempts: int                        # refresh runs summed into refresh_*
    rebuild_passes: tuple[str, ...]      # separate runs summed into rebuild_*; () if one build run
    same_code: bool = False              # the receipt says (from the run worktree's reflog) the rebuild ran on the
                                         # same Honeyguide commit as the refresh
    extra: str = ""                      # a rebuild pass the receipt also leaves out ('re-check'), or ''
    less_usd: float | None = None        # the rebuild less that pass
    less_min: float | None = None
    less_ratio_usd: float | None = None  # the receipt's refresh / rebuild less that pass
    less_ratio_min: float | None = None

    @property
    def fraction(self) -> int:
        """The refresh's cost as 1/k of a rebuild, k from $ and minutes alike (raises if they disagree)."""
        return one_in(self.key, self.ratio_usd, self.ratio_min)

    @property
    def fraction_less(self) -> int | None:
        """The same against the rebuild less its extra pass, or None when the receipt prints no such ratio."""
        if not self.extra:
            return None
        return one_in(f"{self.key} less {self.extra}", self.less_ratio_usd, self.less_ratio_min)

    @property
    def fractions(self) -> str:
        """'1/k', or '1/k to 1/j' when leaving out the extra pass gives a different k (larger fraction last)."""
        ks = sorted({self.fraction, self.fraction_less or self.fraction}, reverse=True)
        return " to ".join(f"1/{k}" for k in ks)


def one_in(what: str, ratio_usd: float, ratio_min: float) -> int:
    """k for a refresh that costs about 1/k of a rebuild, from $ and minutes alike (raises if they disagree)."""
    k_usd, k_min = round(1 / ratio_usd), round(1 / ratio_min)
    if k_usd != k_min:
        raise ValueError(f"{what}: $ says 1/{k_usd} of a rebuild, minutes say 1/{k_min}")
    return k_usd


def block(text: str, heading: str) -> str:
    """The body of a capture block whose heading line starts with ``heading``: from below its rule of dashes to the
    next block's heading."""
    m = re.search(rf"^{re.escape(heading)}[^\n]*\n-{{10,}}\n(.*?)(?=^\S[^\n]*\n-{{10,}}\n|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no '{heading}' block")
    return m.group(1)


def sections(body: str) -> dict[str, tuple[str, str, str]]:
    """A block's per-experiment sections: id -> (heading after the id, e.g. 'nanochat: ...', its body)."""
    parts = re.split(r"^  (E\d+)\s+(.+)$", body, flags=re.M)
    return {parts[i]: (parts[i + 1].strip(), parts[i + 2]) for i in range(1, len(parts), 3)}


def parse(text: str) -> tuple[Experiment, ...]:
    commits = sections(block(text, "commits"))
    cost = sections(block(text, "cost"))
    if not commits or set(commits) != set(cost):
        raise ValueError(f"experiments: commits {sorted(commits)}, cost {sorted(cost)}")
    out = []
    for key, (head, body) in commits.items():
        m = re.match(r"(\S+?):? (.+)$", head)
        repo, rest = m.group(1).rstrip(":"), m.group(2)
        what = rest[len(repo):].lstrip(", ") if rest.startswith(repo) else rest
        d = re.search(r"^\s+days apart\s+([\d.]+)\s*$", body, re.M)
        n = re.search(r"^\s+commits in between\s+(\d+)\s*$", body, re.M)
        if not (d and n):
            raise ValueError(f"commits: {key} has no days apart or commits in between")

        cb = cost[key][1]
        rows = {name.strip(): (float(usd), float(mins)) for name, usd, mins in
                re.findall(r"^ {4}(\S[^$\n]*?)\s+\$([\d.]+)\s+([\d.]+)", cb, re.M)}
        rebuild = rows.get("rebuild total") or rows.get("build")
        refresh = rows.get("refresh total") or rows.get("refresh")
        if not (rebuild and refresh):
            raise ValueError(f"cost: {key} has no rebuild or refresh row ({sorted(rows)})")
        attempts = sum(1 for r in rows if re.fullmatch(r"refresh, attempt \d+", r)) or 1
        if attempts > 1:
            summed = sum(v[0] for r, v in rows.items() if r.startswith("refresh, attempt"))
            if abs(summed - refresh[0]) > 0.011:
                raise ValueError(f"cost: {key}'s refresh attempts sum to ${summed:.2f}, not ${refresh[0]:.2f}")
        passes = ()
        pb = re.search(r"^\s+rebuild pass\b[^\n]*\n(.*?)^\s+rebuild total", cb, re.S | re.M)
        if pb:
            passes = tuple(re.findall(r"^\s+(\S.*?)\s+\$[\d.]+", pb.group(1), re.M))
            summed = sum(float(x) for x in re.findall(r"\$([\d.]+)", pb.group(1)))
            if abs(summed - rebuild[0]) > 0.011:
                raise ValueError(f"cost: {key}'s rebuild passes sum to ${summed:.2f}, not ${rebuild[0]:.2f}")
        r = re.search(r"^\s+refresh(?: \([^)]*\))? / rebuild:\s+\$ ([\d.]+), wall minutes ([\d.]+)", cb, re.M)
        if not r:
            raise ValueError(f"cost: {key} has no refresh / rebuild line")
        ratio_usd, ratio_min = float(r.group(1)), float(r.group(2))
        for got, want, unit in ((refresh[0] / rebuild[0], ratio_usd, "$"), (refresh[1] / rebuild[1], ratio_min, "min")):
            if f"{got:.2f}" != f"{want:.2f}":
                raise ValueError(f"cost: {key}'s refresh / rebuild in {unit} is {got:.3f}, the receipt says {want}")
        less = {}
        lr = re.search(r"^\s+(?:both attempts|refresh) / rebuild less (\S+):\s+\$ ([\d.]+), wall minutes ([\d.]+)",
                       cb, re.M)
        if lr:
            extra = lr.group(1)
            row = rows.get(f"rebuild less {extra}")
            if not row or extra not in passes:
                raise ValueError(f"cost: {key}'s ratio leaves out '{extra}', but no rebuild pass or row is named so")
            full = dict(zip(passes, re.findall(r"^\s+\S.*?\s+\$([\d.]+)", pb.group(1), re.M), strict=True))
            if abs(rebuild[0] - float(full[extra]) - row[0]) > 0.011:
                raise ValueError(f"cost: {key}'s rebuild less {extra} is not the rebuild total less that pass")
            for got, want, unit in ((refresh[0] / row[0], lr.group(2), "$"), (refresh[1] / row[1], lr.group(3), "min")):
                if f"{got:.2f}" != f"{float(want):.2f}":
                    raise ValueError(f"cost: {key}'s refresh / rebuild less {extra} in {unit} is {got:.3f}, the "
                                     f"receipt says {want}")
            less = {"extra": extra, "less_usd": row[0], "less_min": row[1], "less_ratio_usd": float(lr.group(2)),
                    "less_ratio_min": float(lr.group(3))}
        out.append(Experiment(key, repo, what, float(d.group(1)), int(n.group(1)), rebuild[0], rebuild[1],
                              refresh[0], refresh[1], ratio_usd, ratio_min, attempts, passes,
                              "same Honeyguide commit as the refresh" in " ".join(cb.split()), **less))
    return tuple(sorted(out, key=lambda e: e.commits))


def takeaway(exps: tuple[Experiment, ...]) -> str:
    """The title: each experiment's refresh as about 1/k of its rebuild, smallest change first."""
    if len(exps) != 2:
        raise ValueError(f"the title is written for two experiments, got {len(exps)}")
    day, big = exps
    return (f"Keeping the map current costs about {day.fractions} of a rebuild for {day.what},\n"
            f"and about {big.fractions} across a {big.commits}-commit rewrite")


def footnote(exps: tuple[Experiment, ...]) -> str:
    lines = []
    for e in exps:
        if e.rebuild_passes:
            names = ", ".join(re.sub(r"^run \d+$", "build", x) for x in e.rebuild_passes)
            lines.append(f"{e.repo}'s rebuild ran earlier, on older Honeyguide code, as {len(e.rebuild_passes)} "
                         f"separate runs ({names})")
        elif e.same_code:
            lines.append(f"{e.repo}'s rebuild is the full build at the older commit, on the same Honeyguide code")
        else:
            raise ValueError(f"{e.key}: the receipt does not say its rebuild ran on the refresh's Honeyguide commit")
        if e.attempts > 1:
            lines[-1] += f"; its refresh took {e.attempts} attempts, both counted"
        if e.extra:
            others = " and ".join(f"{o.repo}'s" for o in exps if o is not e and not o.rebuild_passes)
            lines.append(f"Its {e.extra} (above the dashed line) has no counterpart in {others or 'a'} one-run "
                         f"rebuild: refresh / rebuild is about 1/{e.fraction} with it, 1/{e.fraction_less} without it")
    return ".\n".join(lines) + "."


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``map`` is slot 2 (orange), the post's
    colour for the map."""

    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    axis: str
    map: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#eb6834")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#d95926")
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
            "legend.fontsize": 12, "axes.unicode_minus": False}


def draw(exps: tuple[Experiment, ...], theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    title, foot = takeaway(exps), footnote(exps)
    with plt.rc_context(style(theme)):
        fig, axes = plt.subplots(1, 2, figsize=(12, 7.0), gridspec_kw={"wspace": 0.28})
        fig.subplots_adjust(top=0.77, bottom=0.36)
        fig.suptitle(title, x=0.06, ha="left", y=0.995, fontsize=15, fontweight="bold", linespacing=1.3)
        w = 0.36
        panels = (("Cost, $ at list price", lambda e: (e.rebuild_usd, e.refresh_usd), lambda v: f"${v:.2f}",
                   lambda e: e.ratio_usd, lambda e: e.less_usd, lambda e: e.less_ratio_usd),
                  ("Wall-clock minutes", lambda e: (e.rebuild_min, e.refresh_min), lambda v: f"{v:.1f} min",
                   lambda e: e.ratio_min, lambda e: e.less_min, lambda e: e.less_ratio_min))
        for ax, (name, vals, fmt, ratio, less, less_ratio) in zip(axes, panels, strict=True):
            top = max(max(vals(e)) for e in exps)
            for i, e in enumerate(exps):
                rb, rf = vals(e)
                ax.bar(i - w / 2, rb, width=w, fc=theme.surface, ec=theme.map, lw=2.0, hatch=None, zorder=2)
                if e.extra:
                    cut = less(e)
                    ax.plot([i - w, i], [cut, cut], color=theme.map, lw=1.4, ls=(0, (3, 2)), zorder=3)
                    ax.text(i - w / 2, (cut + rb) / 2, e.extra, ha="center", va="center", fontsize=10.5,
                            color=theme.secondary, zorder=3)
                ax.bar(i + w / 2, rf, width=w, color=theme.map, ec=theme.map, lw=2.0, zorder=2)
                for x, v in ((i - w / 2, rb), (i + w / 2, rf)):
                    ax.text(x, v + top * 0.02, fmt(v), ha="center", va="bottom", fontsize=11.5)
                r = f"{ratio(e):.2f}" + (f" to {less_ratio(e):.2f}" if e.extra else "")
                ax.text(i, top * 1.1, f"refresh / rebuild\n{r}", ha="center", va="bottom",
                        fontsize=11.5, fontweight="bold", linespacing=1.3)
            ax.set_xticks(range(len(exps)))
            ax.set_xticklabels([f"{e.repo}\n{e.what}\n{e.commits} commits,\n{e.days:g} days apart" for e in exps],
                               fontsize=11.5, linespacing=1.3)
            for lbl in ax.get_xticklabels():
                lbl.set_color(theme.ink)
            ax.set_xlim(-0.6, len(exps) - 0.4)
            ax.set_ylim(0, top * 1.32)
            ax.grid(axis="x", visible=False)
            ax.set_title(name, loc="left", pad=10)
        handles = [Patch(fc=theme.surface, ec=theme.map, lw=2.0, label="rebuild the whole map"),
                   Patch(fc=theme.map, ec=theme.map, lw=2.0, label="refresh: only what changed")]
        fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 0.875), ncol=2, columnspacing=2.0)
        fig.text(0.06, 0.03, foot, ha="left", va="bottom", fontsize=10.5, color=theme.secondary, fontstyle="italic",
                 linespacing=1.4)

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", default=str(ROOT / "outputs" / "refresh.txt"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    exps = parse(Path(args.refresh).read_text())
    for theme in THEMES:
        print(draw(exps, theme, Path(args.out) / f"refresh-vs-rebuild-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""What a refresh did to nanochat's claims, as a flow: the plan's classes before the refresh on the left, what each
became on the right (current or retired), the stale claims through the Checker's re-check in the middle, and the
re-map's new claims entering from below. The gap is marked: claims the hash check kept current (moved) or could not
check (unanchored) that the re-map then retired.

Every number is parsed from ``outputs/refresh.txt`` (E2's ``commits``, ``plan`` and ``refresh`` blocks); none is
typed here. The band sizes are derived from those counts, and the parser raises unless they add up to the printed
totals (claims before + new = claims after; retired by refresh apply + by the re-map = retired after; current after
= the kept part of every class + the new claims). Light and dark, in the house style of the series' figures
(llm-architectures-refresher's plotting.py): grey for claims kept current, the series orange for retired ones,
hatched orange for the gap.

    uv run --script eval/figures/refresh_flow.py [--refresh outputs/refresh.txt] [--experiment E2] [--out docs/figures]

writes ``refresh-flow-light.png`` and ``refresh-flow-dark.png``. The parsing is standard library only, so the tests
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

CLASSES = ("unchanged", "moved", "stale", "retired", "unanchored")      # the plan's classes, as refresh.txt prints


# -- the numbers, parsed from the receipt ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RefreshFlow:
    repo: str
    target_date: date
    before: dict[str, int]               # plan class -> claims
    after_total: int
    after: dict[str, int]                # current / stale / retired after the refresh
    by_apply: int                        # retired by refresh apply (the plan's 'retired' class)
    by_remap: int
    remap_by_class: dict[str, int]       # plan class (and 'new') -> retired by the re-map
    new: int
    stale_rechecked: int
    held: int                            # stale claims the Checker still found supported
    held_retired: int                    # ... that the re-map then retired
    not_held: int
    not_held_retired: int
    left_stale: int

    @property
    def total_before(self) -> int:
        return sum(self.before.values())

    def kept(self, cls: str) -> int:
        """Claims of a plan class still current after the refresh (all but those retired)."""
        if cls == "retired":
            return 0
        if cls == "stale":
            return self.held - self.held_retired + self.not_held - self.not_held_retired
        return self.before[cls] - self.remap_by_class[cls]

    @property
    def gap(self) -> dict[str, int]:
        """The claims the hash check could not flag that the re-map retired: moved (cited lines hash the same) and
        unanchored (no anchors to hash)."""
        return {c: self.remap_by_class[c] for c in ("moved", "unanchored")}


def block(text: str, heading: str) -> str:
    m = re.search(rf"^{re.escape(heading)}[^\n]*\n-{{10,}}\n(.*?)(?=^\S[^\n]*\n-{{10,}}\n|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"no '{heading}' block")
    return m.group(1)


def section(body: str, key: str) -> tuple[str, str]:
    """(the heading after the id, the body) of one experiment's part of a block."""
    parts = re.split(r"^  (E\d+)\s+(.+)$", body, flags=re.M)
    found = {parts[i]: (parts[i + 1].strip(), parts[i + 2]) for i in range(1, len(parts), 3)}
    if key not in found:
        raise ValueError(f"no {key} section (found {sorted(found)})")
    return found[key]


def num(pattern: str, text: str, what: str) -> tuple[int, ...]:
    m = re.search(pattern, text, re.M)
    if not m:
        raise ValueError(f"refresh.txt: no {what}")
    return tuple(int(x) for x in m.groups())


def parse(text: str, key: str = "E2") -> RefreshFlow:
    head, commits = section(block(text, "commits"), key)
    repo = head.split(":")[0]
    t = re.search(r"^\s+target\s+\S+\s+(\d{4})-(\d{2})-(\d{2})", commits, re.M)
    if not t:
        raise ValueError(f"commits: {key} has no target date")

    _, plan = section(block(text, "plan"), key)
    before = {c: num(rf"^\s+{c}\s+(\d+)\s*$", plan, f"plan row '{c}'")[0] for c in CLASSES}
    (total,) = num(r"^\s+claims\s+(\d+)\s*$", plan, "plan claims total")
    if sum(before.values()) != total:
        raise ValueError(f"plan: classes sum to {sum(before.values())}, the receipt says {total}")

    _, rb = section(block(text, "refresh"), key)
    flat = " ".join(rb.split())
    m = re.search(r"claims after (\d+): current (\d+), stale (\d+), retired (\d+)", flat)
    if not m:
        raise ValueError("refresh: no 'claims after' line")
    after_total, cur, stale, ret = (int(x) for x in m.groups())
    rc = re.search(r"re-map retirements by plan class: (.+?)(?= new claims )", flat)
    if not rc:
        raise ValueError("refresh: no 're-map retirements by plan class' line")
    remap = {k: int(v) for k, v in re.findall(r"(\w+) (\d+)", rc.group(1))}
    if set(remap) != {*CLASSES, "new"}:
        raise ValueError(f"refresh: re-map retirements by class {sorted(remap)}")
    stale_n, rechecked = num(r"^\s+stale claims\s+(\d+), re-checked in the refresh (\d+)\s*$", rb, "stale claims line")
    flow = RefreshFlow(
        repo, date(*(int(x) for x in t.groups())), before, after_total,
        {"current": cur, "stale": stale, "retired": ret},
        num(r"^\s+by refresh apply \(plan: retired\)\s+(\d+)\s*$", rb, "'by refresh apply' line")[0],
        num(r"^\s+by the re-map\s+(\d+)\s*$", rb, "'by the re-map' line")[0], remap,
        num(r"^\s+new claims\s+(\d+)\s*$", rb, "'new claims' line")[0], rechecked,
        *num(r"^\s+still held \(supported\)\s+(\d+)\s+(\d+)\s*$", rb, "'still held' row"),
        *num(r"^\s+no longer held \(not supported\)\s+(\d+)\s+(\d+)\s*$", rb, "'no longer held' row"),
        num(r"^\s+left stale after the refresh\s+(\d+)\s*$", rb, "'left stale' row")[0])
    if stale_n != before["stale"]:
        raise ValueError(f"refresh: {stale_n} stale claims, the plan says {before['stale']}")
    check(flow)
    return flow


def check(f: RefreshFlow) -> None:
    """Every band adds up to the printed totals, or raise."""
    problems = []
    if f.total_before + f.new != f.after_total:
        problems.append(f"{f.total_before} before + {f.new} new != {f.after_total} after")
    if sum(f.after.values()) != f.after_total:
        problems.append(f"after: {f.after} does not sum to {f.after_total}")
    if f.by_apply + f.by_remap != f.after["retired"]:
        problems.append(f"{f.by_apply} by refresh apply + {f.by_remap} by the re-map != {f.after['retired']} retired")
    if f.by_apply != f.before["retired"]:
        problems.append(f"refresh apply retired {f.by_apply}, the plan classed {f.before['retired']} retired")
    if sum(f.remap_by_class.values()) != f.by_remap:
        problems.append(f"re-map retirements by class {f.remap_by_class} do not sum to {f.by_remap}")
    if f.held + f.not_held != f.stale_rechecked:
        problems.append(f"held {f.held} + not held {f.not_held} != {f.stale_rechecked} re-checked")
    if f.held_retired + f.not_held_retired != f.remap_by_class["stale"]:
        problems.append(f"stale claims retired {f.held_retired} + {f.not_held_retired} != the re-map's "
                        f"{f.remap_by_class['stale']}")
    if f.remap_by_class["new"] or f.remap_by_class["retired"]:
        problems.append(f"the figure draws no re-map retirement of new or already-retired claims: "
                        f"{f.remap_by_class}")
    kept = sum(f.kept(c) for c in CLASSES) + f.new
    if kept != f.after["current"]:
        problems.append(f"kept {kept} != current {f.after['current']}")
    if problems:
        raise ValueError("refresh flow does not add up: " + "; ".join(problems))


def takeaway(f: RefreshFlow) -> str:
    """The title, checked: every stale claim was re-checked and none left stale (else the refresh did not do what
    the figure says)."""
    if f.stale_rechecked != f.before["stale"] or f.left_stale or f.after["stale"]:
        raise ValueError(f"not every stale claim was re-checked and settled: {f}")
    return f"What a refresh did to {f.repo}'s map across its {f.target_date.strftime('%B')} rewrite"


def gap_note(f: RefreshFlow) -> str:
    g = f.gap
    if not sum(g.values()):
        raise ValueError("no gap: the re-map retired no moved or unanchored claim")
    return (f"the gap: {g['moved']} moved + {g['unanchored']} unanchored claims\n"
            "hashes matched (or there were none),\nso the refresh kept them current;\nthe re-map retired them later")


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``kept`` is the muted grey, ``ret`` slot 2
    (the series orange)."""

    name: str
    surface: str
    ink: str
    secondary: str
    kept: str
    new: str
    ret: str
    box: str
    edge: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#b9b8b2", "#898781", "#eb6834", "#f1f0ec", "#c3c2b7")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#5a5955", "#898781", "#d95926", "#252524", "#383835")
THEMES = (LIGHT, DARK)


def layout(f: RefreshFlow, gap: float = 34.0) -> dict:
    """Vertical positions in claim units (y down from 0): the left stacks, the middle re-check, the right stacks,
    and every band as (source (top, bottom), target (top, bottom), kind). Pure, so the tests can check it."""
    order_left = ("retired", "stale", "moved", "unanchored", "unchanged")
    right_ret = [("apply", f.by_apply), ("not held", f.not_held_retired), ("held", f.held_retired),
                 ("moved", f.remap_by_class["moved"]), ("unanchored", f.remap_by_class["unanchored"])]
    right_cur = [("held", f.held - f.held_retired), ("moved", f.kept("moved")),
                 ("unanchored", f.kept("unanchored")), ("unchanged", f.kept("unchanged")), ("new", f.new)]
    right_h = f.after["retired"] + 2 * gap + f.after["current"]
    left_h = f.total_before + gap * (len(order_left) - 1)
    y = (right_h - left_h) / 2 - 20
    left = {}
    for c in order_left:
        left[c] = (y, y + f.before[c])
        y += f.before[c] + gap

    def stack(items, y0):
        out = {}
        for name, n in items:
            out[name] = (y0, y0 + n)
            y0 += n
        return out, y0
    ret, y_end = stack(right_ret, 0.0)
    cur, _ = stack(right_cur, y_end + 2 * gap)
    # middle: the stale claims' re-check, level with their left block: not held on top, held below
    s0 = left["stale"][0]
    mid = {"not held": (s0, s0 + f.not_held), "held": (s0 + f.not_held, s0 + f.not_held + f.held)}
    bands = []

    def split(src, parts):
        y0 = src[0]
        for n, dst, kind in parts:
            if n:
                bands.append(((y0, y0 + n), dst, kind))
            y0 += n
    split(left["retired"], [(f.by_apply, ret["apply"], "retired")])
    split(left["moved"], [(f.remap_by_class["moved"], ret["moved"], "gap"),
                          (f.kept("moved"), cur["moved"], "kept")])
    split(left["unanchored"], [(f.remap_by_class["unanchored"], ret["unanchored"], "gap"),
                               (f.kept("unanchored"), cur["unanchored"], "kept")])
    split(left["unchanged"], [(f.kept("unchanged"), cur["unchanged"], "kept")])
    mid_bands = [(left["stale"], (mid["not held"][0], mid["held"][1]), "stale")]
    split(mid["not held"], [(f.not_held_retired, ret["not held"], "retired-mid"),
                            (f.not_held - f.not_held_retired, cur["held"], "kept-mid")])
    split(mid["held"], [(f.held_retired, ret["held"], "retired-mid"),
                        (f.held - f.held_retired, cur["held"], "kept-mid")])
    return {"left": left, "mid": mid, "ret": ret, "cur": cur, "bands": bands, "mid_bands": mid_bands,
            "height": max(right_h, left["unchanged"][1])}


def draw(f: RefreshFlow, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle

    title, note = takeaway(f), gap_note(f)
    lay = layout(f)
    rc = {"figure.facecolor": theme.surface, "savefig.facecolor": theme.surface, "text.color": theme.ink,
          "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
          "font.size": 11, "hatch.color": theme.surface, "hatch.linewidth": 1.4}
    XL, XM, XR, W = 0.0, 4.2, 8.4, 0.32           # left, middle and right columns, bar width
    new_src = lay["left"]["unchanged"][1] + 40    # the new claims' source, below the left column
    with plt.rc_context(rc):
        fig, ax = plt.subplots(figsize=(13.0, 8.4))
        ax.set_xlim(-3.3, 12.6)
        ax.set_ylim(max(new_src + f.new, lay["height"]) + 20, -150)
        ax.set_axis_off()
        fig.suptitle(title, x=0.04, ha="left", y=0.985, fontsize=15, fontweight="bold")

        def band(x0, src, x1, dst, color, hatch=None, alpha=0.75, edge=None):
            xs = np.linspace(x0, x1, 80)
            t = (xs - x0) / (x1 - x0)
            s = 3 * t ** 2 - 2 * t ** 3
            top = src[0] + (dst[0] - src[0]) * s
            bot = src[1] + (dst[1] - src[1]) * s
            ax.fill_between(xs, top, bot, color=color, alpha=alpha, lw=0, hatch=hatch, zorder=1)
            if edge:
                ax.plot(xs, top, color=edge, lw=1.1, zorder=2)
                ax.plot(xs, bot, color=edge, lw=1.1, zorder=2)

        def bar(x, span, color, hatch=None):
            ax.add_patch(Rectangle((x, span[0]), W, span[1] - span[0], fc=color, ec="none", hatch=hatch, zorder=3))

        def label(x, y, s, ha, color=None, bold=False, size=11, boxed=False):
            ax.text(x, y, s, ha=ha, va="center", fontsize=size, color=color or theme.ink,
                    fontweight="bold" if bold else "normal", zorder=4, linespacing=1.3,
                    bbox={"fc": theme.surface, "ec": "none", "pad": 1.2, "alpha": 0.9} if boxed else None)

        colors = {"kept": theme.kept, "kept-mid": theme.kept, "retired": theme.ret, "retired-mid": theme.ret,
                  "gap": theme.ret}
        for src, dst, kind in lay["bands"]:
            x0 = XM + W if kind.endswith("-mid") else XL + W
            band(x0, src, XR, dst, colors[kind], hatch="////" if kind == "gap" else None,
                 alpha=1.0 if kind == "gap" else 0.55, edge=theme.ink if kind == "gap" else None)
        for src, dst, _ in lay["mid_bands"]:
            band(XL + W, src, XM, dst, theme.kept, alpha=0.55)
        cur_new = lay["cur"]["new"]
        band(XM + W, (new_src, new_src + f.new), XR, cur_new, theme.new, alpha=0.45)

        # left: the plan's classes
        ax.text(XL + W / 2, -60, f"before the refresh\n{f.total_before} claims, by the plan's class", ha="center",
                va="bottom", fontsize=12, fontweight="bold", linespacing=1.3)
        for c, span in lay["left"].items():
            bar(XL, span, theme.ret if c == "retired" else theme.kept)
            label(XL - 0.15, sum(span) / 2, f"{c}  {f.before[c]}", "right")

        # middle: the stale claims' re-check
        mid = lay["mid"]
        ax.text(XM + W / 2, mid["not held"][0] - 5, f"Checker re-check of all {f.stale_rechecked} stale",
                ha="center", va="bottom", fontsize=10.5, fontweight="bold", zorder=4)
        bar(XM, mid["not held"], theme.ret)
        bar(XM, mid["held"], theme.kept)
        label(XM - 0.1, sum(mid["not held"]) / 2, f"no longer held {f.not_held}", "right", size=10, boxed=True)
        label(XM - 0.1, sum(mid["held"]) / 2 + 3, f"still held {f.held}", "right", size=10, boxed=True)
        # the new claims' source
        bar(XM, (new_src, new_src + f.new), theme.new)
        label(XM - 0.15, new_src + f.new / 2, f"new claims\nfrom the re-map  {f.new}", "right")

        # right: after the refresh
        ret, cur = lay["ret"], lay["cur"]
        ax.text(XR + W / 2, -60, f"after the refresh\n{f.after_total} claims, {f.after['stale']} stale",
                ha="center", va="bottom",
                fontsize=12, fontweight="bold", linespacing=1.3)
        for name, span in ret.items():
            bar(XR, span, theme.ret, hatch="////" if name in ("moved", "unanchored") else None)
        for name, span in cur.items():
            bar(XR, span, theme.new if name == "new" else theme.kept)
        r0 = ret["apply"][0]
        c0, c1 = cur["held"][0], cur["new"][1]
        ax.text(XR + W + 0.15, r0 - 4, f"retired  {f.after['retired']}", ha="left", va="top", fontsize=12,
                color=theme.ret, fontweight="bold", zorder=4)
        ax.text(XR + W + 0.15, r0 + 22,
                f"by refresh apply {f.by_apply} (plan: retired)\nby the re-map {f.by_remap}: stale "
                f"{f.remap_by_class['stale']}, moved {f.remap_by_class['moved']},\nunanchored "
                f"{f.remap_by_class['unanchored']}", ha="left", va="top", fontsize=10, color=theme.secondary,
                linespacing=1.3, zorder=4)
        label(XR + W + 0.15, (c0 + c1) / 2 - 12.5, f"current  {f.after['current']}", "left", bold=True, size=12)
        label(XR + W + 0.15, (c0 + c1) / 2 + 13.5, f"{f.after['current'] - f.new} kept, {f.new} new", "left",
              theme.secondary, size=10)

        # the gap callout, in the empty space above the middle, with a leader to the hatched bands
        gy = (ret["moved"][0] + ret["unanchored"][1]) / 2
        ax.text(XM + W / 2, -60, note, ha="center", va="bottom", fontsize=10, color=theme.ink, linespacing=1.3,
                zorder=4, bbox={"fc": theme.surface, "ec": theme.ret, "lw": 1.2, "boxstyle": "round,pad=0.4"})
        ax.annotate("", xy=(XR - 0.05, gy), xytext=(XM + 1.9, -52),
                    arrowprops={"arrowstyle": "-|>", "color": theme.ret, "lw": 1.2, "shrinkA": 0, "shrinkB": 0})

        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", default=str(ROOT / "outputs" / "refresh.txt"))
    ap.add_argument("--experiment", default="E2")
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = ap.parse_args(argv)
    f = parse(Path(args.refresh).read_text(), args.experiment)
    for theme in THEMES:
        print(draw(f, theme, Path(args.out) / f"refresh-flow-{theme.name}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
(llm-architectures-refresher's plotting.py): grey for claims kept current and a status colour (berry) for retired
ones, hatched for the gap. The status colour is outside the four condition colours (blue explore, orange map, green
outline, grey no access), so a colour keeps one meaning across the post. No band passes behind a bar or a label:
``crossings`` checks the layout, and ``draw`` refuses one that has any.

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
GAP = ("unchanged", "moved", "unanchored")      # classes the refresh keeps current without a re-check


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
        """The claims the hash check could not flag that the re-map retired: unchanged and moved (cited lines hash
        the same) and unanchored (no anchors to hash)."""
        return {c: self.remap_by_class[c] for c in GAP}


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
    if f.held_retired > f.held or f.not_held_retired > f.not_held:
        problems.append(f"the re-map retired more re-checked claims than there were: held {f.held_retired} of "
                        f"{f.held}, not held {f.not_held_retired} of {f.not_held}")
    if any(f.remap_by_class[c] > f.before[c] for c in GAP):
        problems.append(f"the re-map retired more claims of a class than the plan had: {f.remap_by_class}")
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
    """The callout on the gap, punctuated, naming only the classes the re-map retired claims of."""
    g = [(n, c) for c, n in f.gap.items() if n]
    if not g:
        raise ValueError("no gap: the re-map retired no unchanged, moved or unanchored claim")
    parts = [f"{n} {c}" for n, c in g]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return (f"The gap (hatched): {listed} claims.\n"
            "Their hashes matched (or there were none),\nso the refresh kept them current;\n"
            "the re-map retired them later.")


# -- the figure --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """Surfaces and inks from llm-architectures-refresher's plotting.py; ``kept`` is a muted grey, ``ret`` the
    status colour (berry), chosen outside the post's four condition colours."""

    name: str
    surface: str
    ink: str
    secondary: str
    kept: str
    new: str
    ret: str
    box: str
    edge: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#b9b8b2", "#898781", "#9e1f63", "#f1f0ec", "#c3c2b7")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#5a5955", "#898781", "#d1609c", "#252524", "#383835")
THEMES = (LIGHT, DARK)

# columns, in x units: the left bars, the middle re-check node (wide enough to hold its labels), the right bars
XL, XM, XR = 0.0, 3.9, 8.4
W, WM = 0.32, 1.9
TITLE_ROOM = 24.0             # claim units above the middle node for its title
LABEL_ROOM = (2.7, 11.0)      # the new claims' label, left of their bar: width in x units, overhang in claim units


def band_x(kind: str) -> tuple[float, float]:
    """Where a band of each kind starts and ends, in x units."""
    if kind == "stale":
        return XL + W, XM
    if kind == "new":
        return XM + W, XR
    if kind.endswith("-mid"):
        return XM + WM, XR
    return XL + W, XR


def layout(f: RefreshFlow, gap: float = 34.0, sep: float = 14.0, split: float = 120.0) -> dict:
    """Vertical positions in claim units (y down from 0): the left stacks, the middle re-check, the right stacks,
    and every band as (source (top, bottom), target (top, bottom), kind). Pure, so the tests can check it.

    The stale claims are the left column's top block, level with the middle node, so the bands that skip the
    re-check all run below it. On the right, the retired segments are drawn ``sep`` apart so each one (and its
    label) can be found, the re-map's retirements of re-checked claims on top; ``split`` leaves room between the
    retired and current stacks for the gap callout."""
    order_left = ("stale", "retired", "moved", "unanchored", "unchanged")
    right_ret = [("not held", f.not_held_retired), ("held", f.held_retired), ("apply", f.by_apply),
                 *((c, f.remap_by_class[c]) for c in GAP)]
    right_cur = [("held", f.kept("stale")), ("moved", f.kept("moved")), ("unanchored", f.kept("unanchored")),
                 ("unchanged", f.kept("unchanged")), ("new", f.new)]
    left, y = {}, 0.0
    for c in order_left:
        left[c] = (y, y + f.before[c])
        y += f.before[c] + gap

    ret, y = {}, 0.0
    for name, n in right_ret:
        if n and any(ret[k][1] > ret[k][0] for k in ret):
            y += sep
        ret[name] = (y, y + n)
        y += n
    cur, y = {}, y + split
    for name, n in right_cur:
        cur[name] = (y, y + n)
        y += n
    s0 = left["stale"][0]
    mid = {"not held": (s0, s0 + f.not_held), "held": (s0 + f.not_held, s0 + f.not_held + f.held)}
    new_src = (left["unchanged"][1] + 40, left["unchanged"][1] + 40 + f.new)

    bands = []
    fill = {}                                    # how much of each target span earlier bands have used

    def split_(src, parts):
        y0 = src[0]
        for n, side, name, kind in parts:
            if n:
                dst = side[name]
                d0 = dst[0] + fill.get((id(side), name), 0)
                bands.append(((y0, y0 + n), (d0, d0 + n), kind))
                fill[(id(side), name)] = fill.get((id(side), name), 0) + n
            y0 += n
    split_(left["retired"], [(f.by_apply, ret, "apply", "retired")])
    for c in ("moved", "unanchored", "unchanged"):
        split_(left[c], [(f.remap_by_class[c], ret, c, "gap"), (f.kept(c), cur, c, "kept")])
    split_(mid["not held"], [(f.not_held_retired, ret, "not held", "retired-mid"),
                             (f.not_held - f.not_held_retired, cur, "held", "kept-mid")])
    split_(mid["held"], [(f.held_retired, ret, "held", "held-mid"),
                         (f.held - f.held_retired, cur, "held", "kept-mid")])
    mid_bands = [(left["stale"], (mid["not held"][0], mid["held"][1]), "stale")]
    return {"left": left, "mid": mid, "ret": ret, "cur": cur, "bands": bands, "mid_bands": mid_bands,
            "new_src": new_src, "new_band": (new_src, cur["new"], "new"),
            "height": max(cur["new"][1], new_src[1])}


def band_edges(src, dst, x0, x1, xs):
    """The band's top and bottom at each x in ``xs`` (a smoothstep from source to target)."""
    out = []
    for x in xs:
        t = (x - x0) / (x1 - x0)
        s = 3 * t ** 2 - 2 * t ** 3
        out.append((src[0] + (dst[0] - src[0]) * s, src[1] + (dst[1] - src[1]) * s))
    return out


def obstacles(lay: dict) -> dict[str, tuple[float, float, float, float]]:
    """The bars and labels no band may pass behind, as (x0, x1, y0, y1): the middle node with its title above it,
    and the new claims' bar with its label to its left."""
    m0, m1 = lay["mid"]["not held"][0], lay["mid"]["held"][1]
    n0, n1 = lay["new_src"]
    lw, over = LABEL_ROOM
    return {"the re-check node and its title": (XM, XM + WM, m0 - TITLE_ROOM, m1),
            "the new claims' bar and label": (XM - lw, XM + W, n0 - over, n1 + over)}


def crossings(lay: dict, steps: int = 400) -> list[str]:
    """Every band that passes behind an obstacle (strictly inside its x range, overlapping its y range)."""
    found = []
    every = [*lay["bands"], *lay["mid_bands"], lay["new_band"]]
    for name, (ox0, ox1, oy0, oy1) in obstacles(lay).items():
        for src, dst, kind in every:
            x0, x1 = band_x(kind)
            xs = [x0 + (x1 - x0) * i / steps for i in range(steps + 1)]
            for x, (top, bot) in zip(xs, band_edges(src, dst, x0, x1, xs), strict=True):
                if ox0 < x < ox1 and top < oy1 and bot > oy0:
                    found.append(f"a {kind} band ({src[1] - src[0]:g} claims) crosses {name}")
                    break
    return found


def draw(f: RefreshFlow, theme: Theme, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle

    title, note = takeaway(f), gap_note(f)
    lay = layout(f)
    bad = crossings(lay)
    if bad:
        raise ValueError("refresh flow: " + "; ".join(bad))
    rc = {"figure.facecolor": theme.surface, "savefig.facecolor": theme.surface, "text.color": theme.ink,
          "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
          "font.size": 11, "hatch.color": theme.surface, "hatch.linewidth": 1.4}
    ret, cur, mid = lay["ret"], lay["cur"], lay["mid"]
    new_src = lay["new_src"]
    with plt.rc_context(rc):
        fig, ax = plt.subplots(figsize=(13.0, 8.8))
        ax.set_xlim(-2.6, 12.9)
        ax.set_ylim(lay["height"] + 20, -100)
        ax.set_axis_off()
        fig.suptitle(title, x=0.04, ha="left", y=0.985, fontsize=15, fontweight="bold")

        def band(kind, src, dst, color, hatch=None, alpha=0.55, edge=None, ls="-"):
            x0, x1 = band_x(kind)
            xs = np.linspace(x0, x1, 120)
            top, bot = (np.array(v) for v in zip(*band_edges(src, dst, x0, x1, xs), strict=True))
            ax.fill_between(xs, top, bot, color=color, alpha=alpha, lw=0, hatch=hatch, zorder=1)
            if edge:
                ax.plot(xs, top, color=edge, lw=1.0, ls=ls, zorder=2)
                ax.plot(xs, bot, color=edge, lw=1.0, ls=ls, zorder=2)

        def bar(x, span, color, hatch=None, w=W):
            ax.add_patch(Rectangle((x, span[0]), w, span[1] - span[0], fc=color, ec="none", hatch=hatch, zorder=3))

        def text(x, y, s, ha="left", color=None, bold=False, size=11, va="center"):
            ax.text(x, y, s, ha=ha, va=va, fontsize=size, color=color or theme.ink,
                    fontweight="bold" if bold else "normal", zorder=4, linespacing=1.3)

        def ink_on(fill):
            r, g, b = (int(fill[i:i + 2], 16) / 255 for i in (1, 3, 5))
            lum = sum(k * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
                      for k, c in zip((0.2126, 0.7152, 0.0722), (r, g, b), strict=True))
            return "#0b0b0b" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#ffffff"

        # bands, under the bars
        for src, dst, kind in lay["bands"]:
            if kind == "gap":
                band(kind, src, dst, theme.ret, hatch="////", alpha=1.0, edge=theme.ink)
            elif kind == "held-mid":
                band(kind, src, dst, theme.ret, alpha=1.0, edge=theme.ink, ls=(0, (2, 1.5)))
            else:
                band(kind, src, dst, theme.ret if kind.startswith("retired") else theme.kept)
        for src, dst, kind in lay["mid_bands"]:
            band(kind, src, dst, theme.kept)
        band("new", *lay["new_band"][:2], theme.new, alpha=0.45)

        # left: the plan's classes
        ax.text(XL + W / 2, -48, f"before the refresh\n{f.total_before} claims, by the plan's class", ha="center",
                va="bottom", fontsize=12, fontweight="bold", linespacing=1.3)
        for c, span in lay["left"].items():
            bar(XL, span, theme.ret if c == "retired" else theme.kept)
            text(XL - 0.15, sum(span) / 2, f"{c}  {f.before[c]}", "right")

        # middle: the stale claims' re-check, labelled inside its segments
        text(XM + WM / 2, mid["not held"][0] - 6, f"Checker re-check of all {f.stale_rechecked} stale", "center",
             bold=True, size=10.5, va="bottom")
        for key, fill, label in (("not held", theme.ret, f"no longer held {f.not_held}"),
                                 ("held", theme.kept, f"still held {f.held}")):
            span = mid[key]
            bar(XM, span, fill, w=WM)
            if span[1] > span[0]:
                text(XM + WM / 2, sum(span) / 2, label, "center", color=ink_on(fill), size=10)
        # the new claims' source
        bar(XM, new_src, theme.new)
        text(XM - 0.15, sum(new_src) / 2, f"new claims\nfrom the re-map  {f.new}", "right")

        # right: after the refresh
        xt = XR + W + 0.18
        ax.text(XR + W / 2, -48, f"after the refresh\n{f.after_total} claims, {f.after['stale']} stale",
                ha="center", va="bottom", fontsize=12, fontweight="bold", linespacing=1.3)
        text(xt, -31, f"retired  {f.after['retired']}", color=theme.ret, bold=True, size=12)
        text(xt, -10, f"{f.by_apply} by refresh apply, {f.by_remap} by the re-map", color=theme.secondary, size=10)
        names = {"not held": "stale, no longer held", "held": "stale, still held", "apply": "plan: retired",
                 **{c: f"{c} (the gap)" for c in GAP}}
        for name, span in ret.items():
            if span[1] > span[0]:
                bar(XR, span, theme.ret, hatch="////" if name in GAP else None)
                text(xt, sum(span) / 2, f"{span[1] - span[0]:g}  {names[name]}", size=10)
        for name, span in cur.items():
            bar(XR, span, theme.new if name == "new" else theme.kept)
        c0, c1 = cur["held"][0], cur["new"][1]
        text(xt, (c0 + c1) / 2 - 12.5, f"current  {f.after['current']}", bold=True, size=12)
        text(xt, (c0 + c1) / 2 + 13.5, f"{f.after['current'] - f.new} kept, {f.new} new", color=theme.secondary,
             size=10)

        # the gap callout, between the retired and current stacks, beside the hatched segments' labels
        last = max(span[1] for span in ret.values())
        ax.text(xt, last + 16, note, ha="left", va="top", fontsize=10, color=theme.ink, linespacing=1.3, zorder=4,
                bbox={"fc": theme.surface, "ec": theme.ret, "lw": 1.2, "boxstyle": "round,pad=0.4"})

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

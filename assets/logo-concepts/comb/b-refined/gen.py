"""Generate the refined Honeyguide logo (comb variant B, "flower") and, with --install, write it into assets/.

Two drawings of one mark:
  large (>= 48px): seven outlined cells; an amber trail from a dot in the left cell steps centre to centre
                   through the middle cell to the upper-right cell, which is filled amber. A mask cuts the
                   walls around the trail, so amber never touches brown (they are only 1.8:1 apart).
  small (<= 32px, 18px sidebar, 16px favicon): the same layout as filled cells with 1px gaps at 16px.
                   The two cells the trail runs through are left out so the trail itself stays a clear
                   2px line (carving it through filled 4px cells left slivers; see alt/).
Static files use presentation attributes (no <style> classes) and per-file mask ids prefixed hg-, so two
inlined copies can't clash. favicon.svg keeps classes (hg-fav-*) because it switches with prefers-color-scheme.

Writes assets/logo-concepts/comb/b-refined/{icon,icon-dark,icon-small,icon-small-dark,favicon,logo,logo-dark,
page-logo}.svg and alt/*.svg (rejected small treatments). --install also copies the installed set to assets/.
"""
import math
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # importing ../gen.py must not leave a __pycache__ in assets/
sys.path.insert(0, str(HERE.parent))
from gen import DARK, LIGHT, S3, f, hexpath  # noqa: E402  (the comb sheet's geometry helpers)

ASSETS = HERE.parents[2]
FONT = "Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def svg(body, w=96, h=96, style=""):
    st = f"<style>{style}</style>\n  " if style else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">\n  '
            f"{st}{body}\n</svg>\n")


def flower(pitch, cx=48, cy=48):
    """Centres of the seven cells (pointy-top), plus the trail's start (left cell) and end (upper-right cell)."""
    r = pitch / S3
    cs = [(cx, cy)] + [(cx + pitch * math.cos(math.radians(a)), cy + pitch * math.sin(math.radians(a)))
                       for a in (0, 60, 120, 180, 240, 300)]
    return r, cs, (cx - pitch, cy), (cx + pitch / 2, cy - 1.5 * r)


def trail_d(start, mid, end):
    return f"M{f(start[0])} {f(start[1])} L{f(mid[0])} {f(mid[1])} L{f(end[0])} {f(end[1])}"


def paint(kind, colour):
    """Colour as an attribute, or a CSS var for the page's inline copy (attributes can't take var())."""
    if colour.startswith("var("):
        return f' style="{kind}:{colour}"'
    return f' {kind}="{colour}"'


# Large: original B was r 16.5, walls 3.5, trail 6, cut 3, dot r 5. Refined: walls 4 and trail 7 so the mark
# holds at 48px and in the 40px lockup; dot r 6.5 so the start reads as a dot, not a line end.
LARGE = dict(r=16.5, sw=4, tw=7, halo=3, dot=6.5, inset=2.5)


def large(brand, amber, mid, r, sw, tw, halo, dot, inset):
    _, cs, start, end = flower(S3 * r)
    t = trail_d(start, (48, 48), end)
    walls = " ".join(hexpath(*c, r) for c in cs if math.dist(c, end) > 1)
    m = (f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="96" height="96">'
         f'<rect width="96" height="96" fill="#fff"/>'
         f'<path d="{t}" fill="none" stroke="#000" stroke-width="{f(tw + 2 * halo)}" stroke-linecap="round" '
         f'stroke-linejoin="round"/><circle cx="{f(start[0])}" cy="{f(start[1])}" r="{f(dot + halo)}"/></mask>')
    return (f"<defs>{m}</defs>\n"
            f'  <path mask="url(#{mid})" d="{walls}" fill="none"{paint("stroke", brand)} stroke-width="{f(sw)}" '
            f'stroke-linejoin="round"/>\n'
            f'  <path d="{hexpath(*end, r - sw / 2 - inset)}"{paint("fill", amber)}/>\n'
            f'  <path d="{t}" fill="none"{paint("stroke", amber)} stroke-width="{f(tw)}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>\n'
            f'  <circle cx="{f(start[0])}" cy="{f(start[1])}" r="{f(dot)}"{paint("fill", amber)}/>')


# Small: pitch 30 = 5px at 16px; gap 6 = 1px. Shifted 3 left (half a pixel at 16px) so the four cells in the
# top and bottom rows have pixel-aligned vertical sides and gaps; the trail is 12 wide on y = 48 (exactly
# rows 7-8 at 16px). No mask, so the inline copy needs no ids.
SMALL = dict(pitch=30, gap=6, tw=12, dot=10, dx=-3)


def small(brand, amber, pitch, gap, tw, dot, dx, brand_attr=True):
    r, cs, start, end = flower(pitch, cx=48 + dx)
    rr = r - gap / S3
    centre = (48 + dx, 48)
    route = [start, centre, end]
    off = [c for c in cs if min(math.dist(c, p) for p in route) > 1]
    bf = paint("fill", brand) if brand_attr else ""
    return (f'<path{bf} d="{" ".join(hexpath(*c, rr) for c in off)}"/>\n'
            f'  <path{paint("fill", amber)} d="{hexpath(*end, rr)}"/>\n'
            f'  <path d="{trail_d(start, centre, end)}" fill="none"{paint("stroke", amber)} stroke-width="{f(tw)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'  <circle cx="{f(start[0])}" cy="{f(start[1])}" r="{f(dot)}"{paint("fill", amber)}/>')


def favicon():
    """The small drawing with classes, switching palette with prefers-color-scheme (not meant to be inlined)."""
    body = small("BRAND", "AMBER", **SMALL)
    body = body.replace(' fill="BRAND"', ' class="hg-fav-b"').replace(' fill="AMBER"', ' class="hg-fav-a"')
    body = body.replace(' stroke="AMBER"', ' class="hg-fav-t"')
    st = lambda p: f".hg-fav-b{{fill:{p['brand']}}}.hg-fav-a{{fill:{p['amber']}}}.hg-fav-t{{stroke:{p['amber']}}}"
    return svg(body, style=st(LIGHT) + "@media (prefers-color-scheme:dark){" + st(DARK) + "}")


def lockup(p, mid):
    word = (f'<g>{large(p["brand"], p["amber"], mid, **LARGE)}</g>\n'
            f'  <text x="112" y="66" fill="{p["ink"]}" font-family="{FONT}" font-size="54" font-weight="650" '
            f'letter-spacing="-1.08">honeyguide</text>')
    return svg(word, w=420)


# Rejected small treatments, kept for the comparison sheet.
def alt_lit(brand, amber, pitch=30, gap=6, dx=-3):
    """The original B favicon: filled cells, the route as three amber cells (no trail, no dot)."""
    r, cs, start, end = flower(pitch, cx=48 + dx)
    rr = r - gap / S3
    route = [start, (48 + dx, 48), end]
    off = [c for c in cs if min(math.dist(c, p) for p in route) > 1]
    return (f'<path fill="{brand}" d="{" ".join(hexpath(*c, rr) for c in off)}"/>\n'
            f'  <path fill="{amber}" d="{" ".join(hexpath(*c, rr) for c in route)}"/>')


def alt_carved(brand, amber, pitch=30, gap=6, tw=8, halo=3, dot=8, dx=-3, mid="hg-alt-m"):
    """All six other cells filled; the trail carved through them with a halo (leaves slivers at 16px)."""
    r, cs, start, end = flower(pitch, cx=48 + dx)
    rr = r - gap / S3
    t = trail_d(start, (48 + dx, 48), end)
    m = (f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="96" height="96">'
         f'<rect width="96" height="96" fill="#fff"/><path d="{t}" fill="none" stroke="#000" '
         f'stroke-width="{f(tw + 2 * halo)}" stroke-linecap="round" stroke-linejoin="round"/>'
         f'<circle cx="{f(start[0])}" cy="{f(start[1])}" r="{f(dot + halo)}"/></mask>')
    cells = " ".join(hexpath(*c, rr) for c in cs if math.dist(c, end) > 1)
    return (f'<defs>{m}</defs>\n  <path mask="url(#{mid})" fill="{brand}" d="{cells}"/>\n'
            f'  <path fill="{amber}" d="{hexpath(*end, rr)}"/>\n'
            f'  <path d="{t}" fill="none" stroke="{amber}" stroke-width="{f(tw)}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>\n  <circle cx="{f(start[0])}" cy="{f(start[1])}" r="{f(dot)}" fill="{amber}"/>')


def alt_outline(brand, amber):
    """The large drawing itself, shrunk (what original B did at 32px and below)."""
    return large(brand, amber, "hg-alt-o", **LARGE)


INSTALLED = ["icon.svg", "icon-dark.svg", "icon-small.svg", "icon-small-dark.svg", "favicon.svg",
             "logo.svg", "logo-dark.svg"]


def main(install=False):
    for sfx, p in (("", LIGHT), ("-dark", DARK)):
        tag = sfx or "-light"
        (HERE / f"icon{sfx}.svg").write_text(svg(large(p["brand"], p["amber"], f"hg-icon{tag}-m", **LARGE)))
        (HERE / f"icon-small{sfx}.svg").write_text(svg(small(p["brand"], p["amber"], **SMALL)))
        (HERE / f"logo{sfx}.svg").write_text(lockup(p, f"hg-logo{tag}-m"))
        alt = HERE / "alt"
        alt.mkdir(exist_ok=True)
        (alt / f"lit{sfx}.svg").write_text(svg(alt_lit(p["brand"], p["amber"])))
        (alt / f"carved{sfx}.svg").write_text(svg(alt_carved(p["brand"], p["amber"], mid=f"hg-alt-c{tag}-m")))
        (alt / f"outline{sfx}.svg").write_text(svg(alt_outline(p["brand"], p["amber"])))
    (HERE / "favicon.svg").write_text(favicon())
    # The page's 18px sidebar logo: brown inherits .logo{fill:var(--brand)}; amber from var(--amber).
    page = small("", "var(--amber)", **SMALL, brand_attr=False)
    (HERE / "page-logo.svg").write_text(
        f'<svg class="logo" viewBox="0 0 96 96" aria-hidden="true">\n  {page}\n</svg>\n')
    if install:
        for n in INSTALLED:
            shutil.copyfile(HERE / n, ASSETS / n)
    print("ok", HERE, "(installed to " + str(ASSETS) + ")" if install else "")


if __name__ == "__main__":
    main(install="--install" in sys.argv)

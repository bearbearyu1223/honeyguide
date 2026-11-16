"""Generate the 'path through the comb' logo drafts for Honeyguide.

Writes assets/logo-concepts/comb/<a|b|c|d>/{icon,icon-dark,favicon,logo,logo-dark}.svg.
Geometry is computed here so the hexagons are exact; the output SVG is plain, hand-readable markup.
"""
import math
import pathlib

OUT = pathlib.Path.home() / "Documents/GitHub/honeyguide/assets/logo-concepts/comb"
S3 = math.sqrt(3)
LIGHT = dict(brand="#8F5A24", amber="#B8862A", ink="#24272B", line="#DDD9D1", bg="#F8F7F4")
DARK = dict(brand="#C98348", amber="#E2C25C", ink="#F0F1F3", line="#3A3F49", bg="#171A20")


def f(x):
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def hexpts(cx, cy, r):
    """Pointy-top hexagon, vertices clockwise from the top."""
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in (-90, -30, 30, 90, 150, 210)]


def hexpath(cx, cy, r):
    p = hexpts(cx, cy, r)
    return "M" + " L".join(f"{f(x)} {f(y)}" for x, y in p) + " Z"


def svg(body, w=96, h=96, style=""):
    st = f"<style>{style}</style>\n  " if style else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">\n  '
            f"{st}{body}\n</svg>\n")


# Each variant returns the icon body given a colour dict (or CSS-class mode for the favicon).
# Classes: c = cells, t = trail, d = end dot / destination fill. The halo under the trail is a mask,
# so the cut works on any background (tab bars included).

def cells_g(paths, sw, fill=False):
    d = " ".join(paths)
    if fill:
        return f'<path class="f" d="{d}"/>'
    return f'<path class="c" d="{d}" fill="none" stroke-width="{f(sw)}" stroke-linejoin="round"/>'


def masked(cells, trail_d, trail_w, halo, dots=(), dot_halo=0, extra=""):
    """Cells cut by a halo around the trail, then the trail and dots on top."""
    m = (f'<mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="96" height="96">'
         f'<rect width="96" height="96" fill="#fff"/>'
         f'<path d="{trail_d}" fill="none" stroke="#000" stroke-width="{f(trail_w + 2 * halo)}" '
         f'stroke-linecap="round" stroke-linejoin="round"/>'
         + "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r + dot_halo)}"/>' for x, y, r in dots)
         + "</mask>")
    body = (f"<defs>{m}</defs>\n  <g mask=\"url(#m)\">{cells}</g>\n  {extra}"
            f'<path class="t" d="{trail_d}" fill="none" stroke-width="{f(trail_w)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
    for x, y, r in dots:
        body += f'\n  <circle class="d" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>'
    return body


# a) three cells in a triangle; one curved trail from the outer wall, through a shared wall, to a dot
#    in the far cell.
def variant_a(small=False):
    r = 23 if not small else 24.5
    dx = S3 * r / 2
    cx = 48
    top = (cx, (96 - 3.5 * r) / 2 + r)
    bl = (cx - dx, top[1] + 1.5 * r)
    br = (cx + dx, top[1] + 1.5 * r)
    sw = 6 if not small else 10
    tw = 7 if not small else 10.5
    cells = cells_g([hexpath(*c, r) for c in (top, bl, br)], sw)
    wall = bl[0] - S3 * r / 2
    y0 = bl[1] + 5
    trail = (f"M{f(wall)} {f(y0)} C{f(bl[0] + 2)} {f(y0)} {f(bl[0] + 14)} {f(y0 - 14)} "
             f"{f(top[0])} {f(top[1])}")
    dot = (top[0], top[1], 8 if not small else 11)
    h = 3 if not small else 3.5
    return masked(cells, trail, tw, h, [dot], dot_halo=h)


# b) seven-cell flower, outlines; trail steps centre to centre, ending in a filled cell.
#    favicon: the same flower as filled cells (outlines close up at 16px).
def variant_b(small=False):
    r = 16.5 if not small else 17.5
    d = S3 * r
    cs = [(48, 48)] + [(48 + d * math.cos(math.radians(a)), 48 + d * math.sin(math.radians(a)))
                       for a in (0, 60, 120, 180, 240, 300)]
    start = (48 - d, 48)                       # left cell
    end = (48 + d / 2, 48 - 1.5 * r)           # upper-right cell
    trail = f"M{f(start[0])} {f(start[1])} L48 48 L{f(end[0])} {f(end[1])}"
    others = [c for c in cs if math.dist(c, end) > 1]
    if not small:
        sw, tw, h = 3.5, 6, 3
        cells = cells_g([hexpath(*c, r) for c in others], sw)
        goal = f'<path class="d" d="{hexpath(*end, r - sw / 2 - 2.5)}"/>\n  '
        return masked(cells, trail, tw, h, [(start[0], start[1], 5)], dot_halo=h, extra=goal)
    # favicon: filled cells, the route lit as amber cells (a 1px line would vanish here)
    gap = 5
    rr = r - gap / S3
    route = [start, (48, 48), end]
    off = [c for c in cs if min(math.dist(c, p) for p in route) > 1]
    return (cells_g([hexpath(*c, rr) for c in off], 0, fill=True) + "\n  "
            + f'<path class="d" d="{" ".join(hexpath(*c, rr) for c in route)}"/>')


# c) one hexagon; the trail comes in through the middle of a wall and ends in a dot at the centre.
def variant_c(small=False):
    if not small:
        r, sw, tw, cx, cy = 35, 7, 7, 53, 43
        trail = "M14 92 C33 84 42 62 53 43"
        dot = (cx, cy, 10)
    else:
        # favicon: side walls land on whole pixels at 16px (x = 18 and 78, 2px wide)
        r, sw, tw, cx, cy = 60 / S3, 12, 11, 48, 42
        trail = "M7 92 C26 86 38 62 48 42"
        dot = (cx, cy, 13)
    cells = cells_g([hexpath(cx, cy, r)], sw)
    return masked(cells, trail, tw, 4.5 if not small else 5, [dot])


# d) two solid cells part; the trail rises between them (the gap is the path) into a lit cell above.
def variant_d(small=False):
    r = 22 if not small else 23
    gap = 4 if not small else 5
    dx = S3 * r / 2
    top = (48, (96 - 3.5 * r) / 2 + r)
    bl = (48 - dx, top[1] + 1.5 * r)
    br = (48 + dx, top[1] + 1.5 * r)
    rr = r - gap / S3
    cells = cells_g([hexpath(*c, rr) for c in (bl, br)], 0, fill=True)
    tw = 7 if not small else 12          # favicon: 2px stem centred on x = 48, pixel-aligned
    trail = f"M48 {f(bl[1] + rr - 1)} L48 {f(top[1])}"
    lit = f'<path class="d" d="{hexpath(*top, rr)}"/>\n  '
    return masked(cells, trail, tw, 4 if not small else 5, [], extra=lit)


VARIANTS = dict(a=variant_a, b=variant_b, c=variant_c, d=variant_d)


def colour_style(p):
    return f".c{{stroke:{p['brand']}}}.f{{fill:{p['brand']}}}" + f".t{{stroke:{p['amber']}}}.d{{fill:{p['amber']}}}"


def write(name, small_fav):
    fn = VARIANTS[name]
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    for sfx, p in (("", LIGHT), ("-dark", DARK)):
        st = colour_style(p)
        (folder / f"icon{sfx}.svg").write_text(svg(fn(), style=st))
        word = (f'<g>{fn()}</g>\n  <text x="112" y="66" fill="{p["ink"]}" '
                f'font-family="Inter,-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,\'Helvetica Neue\',Arial,sans-serif" '
                f'font-size="54" font-weight="650" letter-spacing="-1.08">honeyguide</text>')
        (folder / f"logo{sfx}.svg").write_text(svg(word, w=420, style=st))
    fav_st = colour_style(LIGHT) + "@media (prefers-color-scheme:dark){" + colour_style(DARK) + "}"
    (folder / "favicon.svg").write_text(svg(fn(small=small_fav), style=fav_st))


if __name__ == "__main__":
    for k in VARIANTS:
        write(k, small_fav=True)
    print("ok", OUT)

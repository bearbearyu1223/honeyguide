"""Build the five Honeyguide agent avatars (assets/avatars/*.svg) and hg-avatars.js from one shared body.

Run: python3 assets/avatars/tools/build_avatars.py
Every avatar shares the honey-drop body, face and state parts; each agent adds ONE prop and a soft body tint.
The Guide is Honey, the Honeyguide mascot: the same drop with its tip swept back into a tuft, plus a beak, one wing
and an amber honeycomb satchel (its prop). It also writes honey.svg (the mascot, idle, self-contained) and
honey-badge.svg (a static 44px crop for a round job avatar), and Honeyguide's logo set in assets/ (logo_files: the
lockup, icon, icon-small and favicon, light and dark), all drawn from the same parts so logo and avatar stay in sync.
Fill/stroke attributes are light-theme fallbacks (used when the SVG is shown as <img>); avatars.css overrides
them through CSS variables for dark mode and animates the named groups. No ids, so copies can sit inline together.
"""
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
LINE, INK, AMBER, GOLD = "#8F5A24", "#2A1E14", "#B8862A", "#E2A33C"
SKIN = {"guide": "#FFEDD2", "cartographer": "#F7F1DA", "investigator": "#FFF2CC", "tracer": "#FFEADF", "checker": "#F6EEE6"}
NAME = {"guide": "Guide", "cartographer": "Cartographer", "investigator": "Investigator", "tracer": "Tracer", "checker": "Checker"}

BODY = "M24 4.5C25.8 10.5 40 18 40 30.5 40 39.5 33 44.5 24 44.5S8 39.5 8 30.5C8 18 22.2 10.5 24 4.5Z"


# Honey (the Guide): sketch A in sketches/honey-compare.png. The drop's tip leans back into one curled tuft.
HONEY_BODY = ("M17.6 5.2C21.8 5.4 25 8.6 26.4 12.6C34 14.6 40 21.4 40 30.5 40 39.5 33 44.5 24 44.5S8 39.5 8 30.5"
              "C8 21.6 13.6 15.4 20.6 13.2C20.8 10.2 19.6 7.2 17.6 5.2Z")
WING = "#F4D3A2"


def hexagon(cx, cy, r):
    """A pointy-top hexagon, like the cells of the logo."""
    pts = [(cx + r * math.cos(math.radians(90 + 60 * k)), cy - r * math.sin(math.radians(90 + 60 * k))) for k in range(6)]
    return "M" + " ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"


def honey_parts():
    """Honey's extra parts: (ground, behind the body, in front of the face, prop)."""
    s = f'stroke="{LINE}" stroke-linejoin="round"'
    ground = ('<g class="hg-av-honeytrail" opacity="0">'  # the logo's trail: a start dot, then dots turning upward
              f'<circle class="hg-av-dot hg-av-tr1" cx="3" cy="45.2" r="2.1" fill="{AMBER}"/>'
              f'<circle class="hg-av-dot hg-av-tr2" cx="7.4" cy="45.2" r="1.2" fill="{AMBER}"/>'
              f'<circle class="hg-av-dot hg-av-tr3" cx="11.4" cy="45.2" r="1.2" fill="{AMBER}"/>'
              f'<circle class="hg-av-dot hg-av-tr4" cx="14.8" cy="43.2" r="1.2" fill="{AMBER}"/></g>')
    wing = ('<g class="hg-av-wing"><path d="M10.8 29.8C6.2 29.2 3.6 33 4.4 36.6 6.8 35.6 9.4 37.4 11.6 35.4Z" '
            f'fill="{WING}" {s} stroke-width="1.6"/></g>')
    beak = f'<g class="hg-av-beak"><path d="M39.2 25.6 44.6 28.6 39.4 31.2Z" fill="{GOLD}" {s} stroke-width="1.4"/></g>'
    drop = "M37.6 35C38.4 36.7 40 37.7 40 39.5 40 40.9 38.9 41.9 37.6 41.9S35.2 40.9 35.2 39.5C35.2 37.7 36.8 36.7 37.6 35Z"
    satchel = ('<g class="hg-av-prop hg-av-satchel">'
               f'<path d="{hexagon(37.6, 38.6, 5.4)}" fill="{GOLD}" {s} stroke-width="1.6"/>'
               f'<path class="hg-av-cell" d="{hexagon(37.6, 38.9, 2.45)}" fill="#F6CE72"/>'
               f'<g class="hg-av-honeydrop" opacity="0"><path d="{drop}" fill="#FFE59A" {s} stroke-width=".9"/>'
               '<ellipse class="hg-av-glint" cx="36.7" cy="39.2" rx=".55" ry=".9" fill="#fff"/>'
               f'<path class="hg-av-dropspark" d="{star(44.6, 33.6, 2.2)}" fill="{GOLD}"/></g></g>')
    return ground, wing, beak, satchel


def paw(*_a, **_k):
    """Paws were tried and dropped: at 28px they read as hollow rings, not hands."""
    return ""


def face():
    e = []
    e.append('<g class="hg-av-face">')
    e.append('<g class="hg-av-eyes">')
    e.append(f'<g class="hg-av-eyes-open"><ellipse cx="18.5" cy="29.5" rx="2.3" ry="2.8" fill="{INK}"/>'
             f'<ellipse cx="28.5" cy="29.5" rx="2.3" ry="2.8" fill="{INK}"/>'
             '<circle class="hg-av-glint" cx="19.2" cy="28.5" r=".8" fill="#fff"/>'
             '<circle class="hg-av-glint" cx="29.2" cy="28.5" r=".8" fill="#fff"/></g>')
    arc = 'fill="none" stroke="{}" stroke-width="1.7" stroke-linecap="round"'.format(INK)
    e.append(f'<g class="hg-av-eyes-happy" opacity="0"><path d="M16.2 30.4Q18.5 27.2 20.8 30.4" {arc}/>'
             f'<path d="M26.2 30.4Q28.5 27.2 30.8 30.4" {arc}/></g>')
    e.append(f'<g class="hg-av-eyes-sleepy" opacity="0"><path d="M16.2 29.6Q18.5 31.6 20.8 29.6" {arc}/>'
             f'<path d="M26.2 29.6Q28.5 31.6 30.8 29.6" {arc}/></g>')
    e.append('</g>')
    e.append('<g class="hg-av-blush"><ellipse cx="14.5" cy="33.6" rx="2.4" ry="1.4" fill="#EE9C8C" opacity=".6"/>'
             '<ellipse cx="32.5" cy="33.6" rx="2.4" ry="1.4" fill="#EE9C8C" opacity=".6"/></g>')
    m = 'fill="none" stroke="{}" stroke-width="1.5" stroke-linecap="round"'.format(INK)
    e.append(f'<path class="hg-av-mouth hg-av-mouth-smile" d="M21.2 33.3Q23.5 35.7 25.8 33.3" {m}/>')
    e.append(f'<path class="hg-av-mouth hg-av-mouth-grin" opacity="0" d="M21 33.2H26Q25.6 36.6 23.5 36.6 21.4 36.6 21 33.2Z" fill="{INK}"/>')
    e.append(f'<path class="hg-av-mouth hg-av-mouth-frown" opacity="0" d="M21.4 35.2Q23.5 33.4 25.6 35.2" {m}/>')
    e.append(f'<ellipse class="hg-av-mouth hg-av-mouth-tiny" opacity="0" cx="23.5" cy="34.4" rx="1.1" ry=".9" fill="{INK}"/>')
    e.append('</g>')
    return "".join(e)


def star(cx, cy, r):
    k = r * 0.32
    return (f'M{cx} {cy - r}Q{cx + k} {cy - k} {cx + r} {cy}Q{cx + k} {cy + k} {cx} {cy + r}'
            f'Q{cx - k} {cy + k} {cx - r} {cy}Q{cx - k} {cy - k} {cx} {cy - r}Z')


def extras(agent=""):
    if agent == "guide":  # Honey dozes under a little hexagon "z" instead of a dream bubble
        z = "M34.9 10.3H38.1L34.9 13.5H38.1"
        bubble = (f'<g class="hg-av-bubble hg-av-hexz" opacity="0"><path d="{hexagon(36.5, 11.9, 4)}" fill="none" stroke="{LINE}" '
                  f'stroke-width="1.3" stroke-linejoin="round"/><path class="hg-av-hexz-z" d="{z}" fill="none" stroke="{LINE}" '
                  f'stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/><path d="{hexagon(42.3, 5.4, 1.9)}" '
                  f'fill="none" stroke="{LINE}" stroke-width="1.1" stroke-linejoin="round"/></g>')
    else:
        bubble = (f'<g class="hg-av-bubble" opacity="0"><circle cx="35.5" cy="12" r="3.4" fill="none" stroke="{LINE}" '
                  f'stroke-width="1.3"/><circle cx="40.5" cy="6.5" r="1.8" fill="none" stroke="{LINE}" stroke-width="1.1"/></g>')
    return (f'<g class="hg-av-sparkle" opacity="0"><path class="hg-av-spark1" d="{star(7, 13, 3.6)}" fill="{GOLD}"/>'
            f'<path class="hg-av-spark2" d="{star(41, 9, 2.8)}" fill="{GOLD}"/>'
            f'<path class="hg-av-spark3" d="{star(44, 21, 2)}" fill="{GOLD}"/></g>' + bubble)


def prop(agent):
    s = f'stroke="{LINE}" stroke-linejoin="round"'
    if agent == "guide":  # Honey's amber honeycomb satchel; a honey drop sparkles in it when the job is done
        return honey_parts()[3]
    if agent == "cartographer":  # a three-panel folded map; outer panels fold in while it works
        return ('<g class="hg-av-prop hg-av-map">'
                f'<g class="hg-av-map-l"><path d="M24.5 32 31.8 34.6V46.2L24.5 43.6Z" fill="#D7E8DA" {s} stroke-width="1.5"/>'
                f'<circle cx="28.2" cy="40.6" r="1.1" fill="{AMBER}"/></g>'
                f'<g class="hg-av-map-r"><path d="M39.1 32 46.4 34.6V46.2L39.1 43.6Z" fill="#D7E8DA" {s} stroke-width="1.5"/>'
                f'<circle cx="42.8" cy="38.2" r="1.9" fill="{AMBER}"/></g>'
                f'<g class="hg-av-map-c"><path d="M31.8 34.6 39.1 32V43.6L31.8 46.2Z" fill="#B5D2BC" {s} stroke-width="1.5"/>'
                f'<path class="hg-av-route" d="M33.4 41.6 37.4 37.8" stroke="{AMBER}" stroke-width="1.4" stroke-linecap="round" stroke-dasharray="1.3 1.5"/></g>'
                '</g>')
    if agent == "investigator":  # a magnifying glass; the lens peers across the face while it works
        return ('<g class="hg-av-prop hg-av-lens">'
                f'<path d="M41.6 41.2 46.2 45.8" stroke="{LINE}" stroke-width="3.4" stroke-linecap="round"/>'
                f'<circle class="hg-av-glass" cx="37" cy="36.6" r="6.4" fill="#DCEAF0" fill-opacity=".55" stroke="{LINE}" stroke-width="2.4"/>'
                '<path class="hg-av-glare" d="M33.6 35.4Q34 33.4 35.8 32.8" fill="none" stroke="#fff" stroke-width="1.3" stroke-linecap="round"/>'
                + paw(43.6, 43.2, agent=agent) + '</g>')
    if agent == "tracer":  # the amber trail it leaves behind, as in the logo: a start dot and dashes
        return ('<g class="hg-av-prop hg-av-trail">'
                f'<circle class="hg-av-dot hg-av-dot1" cx="11.5" cy="45.4" r="1.6" fill="{AMBER}"/>'
                f'<circle class="hg-av-dot hg-av-dot2" cx="6.8" cy="45.4" r="1.6" fill="{AMBER}"/>'
                f'<circle class="hg-av-dot hg-av-dot3" cx="2.4" cy="45.4" r="2.2" fill="{AMBER}"/>'
                '</g>'
                '<g class="hg-av-prop2 hg-av-spool">'
                f'<rect x="34.4" y="34.6" width="8.4" height="9.4" rx="1.6" fill="#E9A3B4" {s} stroke-width="1.5"/>'
                f'<path d="M34.4 37.6H42.8M34.4 41H42.8" stroke="#C97C90" stroke-width="1.1"/>'
                f'<path d="M33 34.4H44.2M33 44.2H44.2" stroke="{LINE}" stroke-width="2.2" stroke-linecap="round"/>'
                + paw(33.6, 40, agent=agent) + '</g>')
    if agent == "checker":  # a round tick badge it stamps onto each claim
        return ('<g class="hg-av-prop hg-av-stamp">'
                f'<circle cx="38.4" cy="37.4" r="7.2" fill="#3E9A6E" {s} stroke-width="1.6"/>'
                '<path class="hg-av-tick" d="M34.8 37.6 37.4 40.2 42 34.8" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
                + paw(32, 41.6, agent=agent) + '</g>')
    raise ValueError(agent)


def svg(agent, standalone=True):
    ground, wing, beak, shape = "", "", "", BODY
    if agent == "guide":
        ground, wing, beak, _ = honey_parts()
        shape = HONEY_BODY
    behind = prop(agent) if agent == "tracer" else ""
    if agent == "tracer":  # trail sits behind the body, spool in front
        behind, front = behind.split('<g class="hg-av-prop2')[0], '<g class="hg-av-prop2' + behind.split('<g class="hg-av-prop2')[1]
    else:
        front = prop(agent)
    body = (f'<g class="hg-av-char">{wing}<g class="hg-av-body"><path class="hg-av-skin" d="{shape}" fill="{SKIN[agent]}" '
            f'stroke="{LINE}" stroke-width="2" stroke-linejoin="round"/>'
            '<ellipse class="hg-av-shine" cx="14.5" cy="23.6" rx="1.8" ry="3.2" transform="rotate(28 14.5 23.6)" fill="#fff" opacity=".9"/>'
            '</g>' + face() + beak + '</g>')
    inner = f'{ground}<g class="hg-av-all">{behind}{body}{front}{extras(agent)}</g>'
    head = '<?xml-stylesheet href="avatars.css" type="text/css"?>\n' if standalone else ""
    size = ' width="96" height="96"' if standalone else ""
    return (f'{head}<svg xmlns="http://www.w3.org/2000/svg" class="hg-av hg-av-{agent} hg-av-idle" viewBox="0 0 48 48"{size} '
            f'aria-hidden="true" focusable="false">{inner}</svg>\n')


HONEY_IDLE_CSS = (  # honey.svg carries its own idle motion, so it breathes, blinks and ruffles as a plain <img>
    "g,path,ellipse{transform-box:fill-box}"
    ".hg-av-char{transform-origin:50% 100%;animation:b 3.6s ease-in-out infinite}"
    ".hg-av-eyes-open{transform-origin:50% 50%;animation:k 5.2s infinite}"
    ".hg-av-wing{transform-origin:100% 20%;animation:r 7s ease-in-out infinite}"
    "@keyframes b{0%,100%{transform:scale(1,1)}50%{transform:scale(1.025,.965)}}"
    "@keyframes k{0%,91%,97%,100%{transform:scaleY(1)}94%{transform:scaleY(.1)}}"
    "@keyframes r{0%,86%,100%{transform:rotate(0)}89%{transform:rotate(-26deg)}92%{transform:rotate(6deg)}"
    "95%{transform:rotate(-14deg)}98%{transform:rotate(0)}}"
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}}")


def honey_files():
    """honey.svg: the mascot, idle, self-contained. honey-badge.svg: static, no classes, cropped to fit a circle."""
    g = svg("guide", standalone=False)
    mascot = g.replace('class="hg-av hg-av-guide hg-av-idle" ', "").replace(
        'aria-hidden="true" focusable="false">', f'width="96" height="96" role="img" aria-label="Honey, the Honeyguide mascot">'
        f'<style>{HONEY_IDLE_CSS}</style>', 1)
    (OUT / "honey.svg").write_text(mascot)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.fromstring(g)
    for parent in list(root.iter()):  # drop every hidden part (other states' faces, trail, sparkles), then the classes
        for child in list(parent):
            if child.get("opacity") == "0":
                parent.remove(child)
    for el in root.iter():
        el.attrib.pop("class", None)
    root.set("viewBox", "0.5 3.5 48 48")
    root.set("width", "44")
    root.set("height", "44")
    (OUT / "honey-badge.svg").write_text(ET.tostring(root, encoding="unicode") + "\n")


# ---------------------------------------------------------------------------------------------------------------
# The logo: Honey, static, idle pose. Written to assets/ (logo.svg, logo-dark.svg, icon*.svg, favicon.svg).
# Dark colours are avatars.css's dark values for the Guide; keep the two in step (tests/test_logo_assets.py checks).
DARK = {LINE: "#C98348", INK: "#1E1610", "#EE9C8C": "#D98A7C", SKIN["guide"]: "#DCC4A2", WING: "#C9A57C"}
DARK_SHINE_OPACITY = ".45"
WORD_INK = {"light": "#24272B", "dark": "#F0F1F3"}   # the lockup's wordmark, as before
FONT = "Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
CROP = "2.5 3 44 44"    # icons: Honey's drawing (x 3.6-45.4, y 4.2-45.5) with about a unit of margin
FAV_CROP = "2.8 3.6 43.6 43.6"
SVGNS = "http://www.w3.org/2000/svg"


def honey_static(small=False, dark=False):
    """Honey's idle pose as a static tree: hidden parts (other states, trail, sparkles) and every class removed.
    small: the 18-32px tuning the page uses below 28px (avatars.css hg-av-20/22/24): outline 2.6, no glints or shine."""
    ET.register_namespace("", SVGNS)
    root = ET.fromstring(svg("guide", standalone=False))
    for parent in list(root.iter()):
        for child in list(parent):
            cls = child.get("class", "")
            if child.get("opacity") == "0" or (small and ("hg-av-glint" in cls or "hg-av-shine" in cls)):
                parent.remove(child)
    for el in root.iter():
        cls = el.attrib.pop("class", "")
        if small and "hg-av-skin" in cls:
            el.set("stroke-width", "2.6")
        if dark:
            for k in ("fill", "stroke"):
                if el.get(k) in DARK:
                    el.set(k, DARK[el.get(k)])
            if "hg-av-shine" in cls:
                el.set("opacity", DARK_SHINE_OPACITY)
    for k in ("aria-hidden", "focusable"):
        root.attrib.pop(k, None)
    return root


def honey_inner(**kw):
    """Honey's drawing (the children of the svg), as markup."""
    return "".join(ET.tostring(c, encoding="unicode") for c in honey_static(**kw)).replace(f' xmlns="{SVGNS}"', "")


def icon_svg(small=False, dark=False):
    n = 96
    return (f'<svg xmlns="{SVGNS}" viewBox="{CROP}" width="{n}" height="{n}" role="img" aria-label="Honeyguide">'
            f'{honey_inner(small=small, dark=dark)}</svg>\n')


def lockup_svg(dark=False):
    """420x96: Honey in the 96px square, the wordmark where the comb logo's was (x 112, baseline 66, 54px, 650)."""
    ink = WORD_INK["dark" if dark else "light"]
    return (f'<svg xmlns="{SVGNS}" viewBox="0 0 420 96" width="420" height="96" role="img" aria-label="Honeyguide">\n'
            f'  <svg x="0" y="0" width="96" height="96" viewBox="{CROP}">{honey_inner(dark=dark)}</svg>\n'
            f'  <text x="112" y="66" fill="{ink}" font-family="{FONT}" font-size="54" font-weight="650" '
            'letter-spacing="-1.08">honeyguide</text>\n</svg>\n')


def favicon_svg():
    """Honey for 16px: the silhouette (tuft, wing, beak), the eyes and the satchel as a solid amber hexagon. No blush,
    mouth, glints or shine: at 16px they smear into a grey patch (compare.html's "full face at 16" row). The outline
    is thicker and the beak bigger than the avatar's so both survive at 16; the crop (2.725 units a pixel) puts each
    eye on a solid 2x3-pixel block at 16 and 32px. Classes, because it switches with prefers-color-scheme."""
    body = ('<path class="hg-fav-w" d="M10.8 29.8C6.2 29.2 3.6 33 4.4 36.6 6.8 35.6 9.4 37.4 11.6 35.4Z" '
            'stroke-width="2" stroke-linejoin="round"/>'
            f'<path class="hg-fav-s" d="{HONEY_BODY}" stroke-width="3.6" stroke-linejoin="round"/>'
            '<path class="hg-fav-b" d="M38.8 25 45.2 28.6 39 32Z" stroke-width="1.8" stroke-linejoin="round"/>'
            '<ellipse class="hg-fav-e" cx="19.15" cy="29.5" rx="2.7" ry="4.05"/>'
            '<ellipse class="hg-fav-e" cx="30.05" cy="29.5" rx="2.7" ry="4.05"/>'
            f'<path class="hg-fav-b" d="{hexagon(37.6, 38.6, 5.6)}" stroke-width="2" stroke-linejoin="round"/>')

    def pal(skin, wing, line, ink):
        return (f".hg-fav-s{{fill:{skin};stroke:{line}}}.hg-fav-w{{fill:{wing};stroke:{line}}}"
                f".hg-fav-b{{fill:{GOLD};stroke:{line}}}.hg-fav-e{{fill:{ink}}}")
    light = pal(SKIN["guide"], WING, LINE, INK)
    dark = pal(DARK[SKIN["guide"]], DARK[WING], DARK[LINE], DARK[INK])
    return (f'<svg xmlns="{SVGNS}" viewBox="{FAV_CROP}" width="96" height="96">'
            f'<style>{light}@media (prefers-color-scheme:dark){{{dark}}}</style>{body}</svg>\n')


def logo_files():
    """name -> text for Honeyguide's logo set in assets/."""
    return {"logo.svg": lockup_svg(), "logo-dark.svg": lockup_svg(dark=True),
            "icon.svg": icon_svg(), "icon-dark.svg": icon_svg(dark=True),
            "icon-small.svg": icon_svg(small=True), "icon-small-dark.svg": icon_svg(small=True, dark=True),
            "favicon.svg": favicon_svg()}


def main():
    js = {}
    for a in SKIN:
        (OUT / f"{a}.svg").write_text(svg(a))
        js[a] = svg(a, standalone=False).strip()
    (OUT / "hg-avatars.js").write_text(
        "/* Generated by assets/avatars/tools/build_avatars.py; do not edit by hand.\n"
        "   hgAv(agent, state, size): inline SVG markup for an agent avatar. state: idle|working|done|failed|waiting, plus \" static\" for prose (\"idle static\"). */\n"
        f"const HG_AV = {json.dumps(js, indent=1)};\n"
        "const hgAv = (agent, state = \"idle\", size = 28) => (HG_AV[agent] || HG_AV.guide)\n"
        "  .replace(\"hg-av-idle\", state.split(\" \").map(s => `hg-av-${s}`).join(\" \") + ` hg-av-${size}`)\n"
        "  .replace(\"<svg \", `<svg width=\"${size}\" height=\"${size}\" `);\n")
    honey_files()
    for name, text in logo_files().items():
        (OUT.parent / name).write_text(text)
    print("wrote", ", ".join(f"{a}.svg" for a in SKIN), "honey.svg, honey-badge.svg and hg-avatars.js;",
          "and the logo set in assets/:", ", ".join(logo_files()))


if __name__ == "__main__":
    main()

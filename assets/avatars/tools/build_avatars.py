"""Build the five Honeyguide agent avatars (assets/avatars/*.svg) and hg-avatars.js from one shared body.

Run: python3 assets/avatars/tools/build_avatars.py
Every avatar shares the honey-drop body, face and state parts; each agent adds ONE prop and a soft body tint.
Fill/stroke attributes are light-theme fallbacks (used when the SVG is shown as <img>); avatars.css overrides
them through CSS variables for dark mode and animates the named groups. No ids, so copies can sit inline together.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
LINE, INK, AMBER, GOLD = "#8F5A24", "#2A1E14", "#B8862A", "#E2A33C"
SKIN = {"guide": "#FFEDD2", "cartographer": "#F7F1DA", "investigator": "#FFF2CC", "tracer": "#FFEADF", "checker": "#F6EEE6"}
NAME = {"guide": "Guide", "cartographer": "Cartographer", "investigator": "Investigator", "tracer": "Tracer", "checker": "Checker"}

BODY = "M24 4.5C25.8 10.5 40 18 40 30.5 40 39.5 33 44.5 24 44.5S8 39.5 8 30.5C8 18 22.2 10.5 24 4.5Z"


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


def extras():
    return (f'<g class="hg-av-sparkle" opacity="0"><path class="hg-av-spark1" d="{star(7, 13, 3.6)}" fill="{GOLD}"/>'
            f'<path class="hg-av-spark2" d="{star(41, 9, 2.8)}" fill="{GOLD}"/>'
            f'<path class="hg-av-spark3" d="{star(44, 21, 2)}" fill="{GOLD}"/></g>'
            f'<g class="hg-av-bubble" opacity="0"><circle cx="35.5" cy="12" r="3.4" fill="none" stroke="{LINE}" '
            f'stroke-width="1.3"/><circle cx="40.5" cy="6.5" r="1.8" fill="none" stroke="{LINE}" stroke-width="1.1"/></g>')


def prop(agent):
    s = f'stroke="{LINE}" stroke-linejoin="round"'
    if agent == "guide":  # a little pennant held high: the one who leads
        return ('<g class="hg-av-prop hg-av-flag">'
                f'<path class="hg-av-pole" d="M35 40 41.5 13" stroke="{LINE}" stroke-width="2" stroke-linecap="round"/>'
                f'<path class="hg-av-pennant" d="M41.5 12.5 47 18.2 39.6 20.6Z" fill="{GOLD}" {s} stroke-width="1.5"/>'
                + paw(35.2, 38.4, agent=agent) + '</g>')
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
    behind = prop(agent) if agent == "tracer" else ""
    if agent == "tracer":  # trail sits behind the body, spool in front
        behind, front = behind.split('<g class="hg-av-prop2')[0], '<g class="hg-av-prop2' + behind.split('<g class="hg-av-prop2')[1]
    else:
        front = prop(agent)
    body = (f'<g class="hg-av-char"><g class="hg-av-body"><path class="hg-av-skin" d="{BODY}" fill="{SKIN[agent]}" '
            f'stroke="{LINE}" stroke-width="2" stroke-linejoin="round"/>'
            '<ellipse class="hg-av-shine" cx="14.5" cy="23.6" rx="1.8" ry="3.2" transform="rotate(28 14.5 23.6)" fill="#fff" opacity=".9"/>'
            '</g>' + face() + '</g>')
    inner = f'<g class="hg-av-all">{behind}{body}{front}{extras()}</g>'
    head = '<?xml-stylesheet href="avatars.css" type="text/css"?>\n' if standalone else ""
    size = ' width="96" height="96"' if standalone else ""
    return (f'{head}<svg xmlns="http://www.w3.org/2000/svg" class="hg-av hg-av-{agent} hg-av-idle" viewBox="0 0 48 48"{size} '
            f'aria-hidden="true" focusable="false">{inner}</svg>\n')


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
    print("wrote", ", ".join(f"{a}.svg" for a in SKIN), "and hg-avatars.js")


if __name__ == "__main__":
    main()

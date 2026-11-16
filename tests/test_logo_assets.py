"""Honeyguide's logo is Honey (assets/*.svg), generated from the avatar's parts by assets/avatars/tools/build_avatars.py."""

from __future__ import annotations

import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
_spec = importlib.util.spec_from_file_location("build_avatars", ASSETS / "avatars/tools/build_avatars.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
FILES = build.logo_files()


def test_the_logo_files_are_what_the_avatar_build_writes():
    assert set(FILES) == {"logo.svg", "logo-dark.svg", "icon.svg", "icon-dark.svg", "icon-small.svg",
                          "icon-small-dark.svg", "favicon.svg"}
    for name, text in FILES.items():
        assert (ASSETS / name).read_text() == text, f"assets/{name} is stale: run assets/avatars/tools/build_avatars.py"


def test_static_logo_files_have_no_ids_classes_or_styles_and_parse():
    for name, text in FILES.items():
        ET.fromstring(text)
        assert " id=" not in text and "url(#" not in text, name
        if name != "favicon.svg":
            assert "<style" not in text and " class=" not in text and "style=" not in text, name


def test_the_favicon_switches_with_the_colour_scheme_and_has_no_face_detail():
    fav = FILES["favicon.svg"]
    assert fav.count("<style>") == 1 and "@media (prefers-color-scheme:dark)" in fav
    assert "#EE9C8C" not in fav and "#fff" not in fav.lower().replace("#ffedd2", "")   # no blush, glint or shine


def test_dark_variants_use_the_avatars_dark_colours():
    css = (ASSETS / "avatars/avatars.css").read_text()
    for light, dark in build.DARK.items():
        assert dark in css, f"{dark} (dark for {light}) is not in avatars.css"
        assert light not in FILES["icon-dark.svg"] and dark in FILES["icon-dark.svg"]
    assert "#F0F1F3" in FILES["logo-dark.svg"] and "#24272B" in FILES["logo.svg"]


def test_the_lockup_keeps_the_wordmark_where_it_was():
    for name in ("logo.svg", "logo-dark.svg"):
        t = FILES[name]
        assert 'viewBox="0 0 420 96" width="420" height="96"' in t
        assert re.search(r'<text x="112" y="66" fill="#[0-9A-F]{6}" font-family="Inter,[^"]+" font-size="54" '
                         r'font-weight="650" letter-spacing="-1.08">honeyguide</text>', t)

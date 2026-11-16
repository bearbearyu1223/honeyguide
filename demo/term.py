"""The terminal picture-in-picture: the real Claude Code session's stream-json events (each with the time
answer.sh received it), turned into terminal lines and drawn as a small dark terminal window.

Only real events are shown. Long lines are cut with an explicit "…", tool results are cut to their first line,
and home paths are shortened (``/Users/<me>/...`` -> ``~/...``, the target checkout -> ``~/…/nanochat``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MONO = "/System/Library/Fonts/Menlo.ttc"
SANS = "/System/Library/Fonts/HelveticaNeue.ttc"

BG = (24, 26, 31)
BAR = (36, 39, 46)
FG = (214, 218, 224)
DIM = (128, 135, 146)
AMBER = (226, 194, 92)        # the page's dark-theme amber
GREEN = (102, 189, 145)
BLUE = (159, 174, 241)
RED = (236, 143, 132)

AGENT_OF = {}   # tool_use id -> subagent name


def shorten(s: str) -> str:
    s = re.sub(r"/Users/[^/\s\"']+/Documents/GitHub/honeyguide-targets/nanochat", "~/…/nanochat", s)
    s = re.sub(r"/Users/[^/\s\"']+/\.honeyguide/github\.com__karpathy__nanochat__[0-9a-f]+", "~/.honeyguide/…", s)
    s = re.sub(r"/Users/[^/\s\"']+/", "~/", s)
    s = re.sub(r"~/\.claude/projects/[^/\s\"']+/", "~/.claude/projects/…/", s)   # Claude Code's spill files
    s = s.replace("--repo ~/…/nanochat", "--repo ~/…/nanochat")
    return s


def first_line(x) -> str:
    """A tool result, abridged to one line: JSON compacted, a file read as its line count, else the first line."""
    if isinstance(x, list):
        x = " ".join(c.get("text", "") for c in x if isinstance(c, dict))
    x = str(x or "").strip()
    if not x:
        return ""
    if x.startswith("{"):
        try:
            return json.dumps(json.loads(x), separators=(", ", ": "), ensure_ascii=False)
        except ValueError:
            pass
    lines = x.splitlines()
    if re.match(r"^\s*\d+\t", lines[0]):
        return f"({len(lines)} lines)"
    if lines[0].startswith("<"):
        return ""
    if lines[0].startswith("[Subagent hand-back]"):
        return "(the subagent's report)"
    return lines[0]


def events(path: Path) -> list[dict]:
    """[{t, who, kind, text}] in order. who: 'guide' or a subagent name; kind: cmd | text | result | agent | done."""
    out = []
    for raw in Path(path).read_text().splitlines():
        rec = json.loads(raw)
        t, e = rec["t"], rec["e"]
        typ = e.get("type")
        parent = e.get("parent_tool_use_id")
        who = AGENT_OF.get(parent, "agent") if parent else "guide"
        if typ == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "text" and c["text"].strip():
                    out.append({"t": t, "who": who, "kind": "text", "text": shorten(c["text"].strip())})
                elif c.get("type") == "tool_use":
                    name, inp = c["name"], c.get("input", {})
                    if name == "Agent" or name == "Task":
                        sub = (inp.get("subagent_type") or "agent").split(":")[-1]
                        AGENT_OF[c["id"]] = sub
                        out.append({"t": t, "who": who, "kind": "agent", "text": f"{sub}: {inp.get('description', '')}"})
                    elif name == "Bash":
                        out.append({"t": t, "who": who, "kind": "cmd", "text": shorten(inp.get("command", ""))})
                    elif name in ("Read", "Grep", "Glob", "Write", "Edit"):
                        arg = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
                        out.append({"t": t, "who": who, "kind": "tool", "text": f"{name}({shorten(str(arg))})"})
                    elif name == "Skill":
                        out.append({"t": t, "who": who, "kind": "tool", "text": f"Skill({inp.get('skill', '')})"})
                    else:
                        out.append({"t": t, "who": who, "kind": "cmd", "text": name})
        elif typ == "user":
            content = e["message"].get("content")
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result":
                        line = shorten(first_line(c.get("content")))
                        if c.get("is_error"):
                            out.append({"t": t, "who": who, "kind": "error", "text": line})
                        elif line:
                            out.append({"t": t, "who": who, "kind": "result", "text": line})
        elif typ == "result":
            out.append({"t": t, "who": "guide", "kind": "done",
                        "text": f"done · {e.get('duration_ms', 0) / 60000:.1f} min · ${e.get('total_cost_usd', 0):.2f} at API list price",
                        "cost": e.get("total_cost_usd"), "duration_ms": e.get("duration_ms"), "num_turns": e.get("num_turns")})
    return out


class Term:
    def __init__(self, w: int = 860, h: int = 470, size: int = 17, title: str = "") -> None:
        self.w, self.h = w, h
        self.font = ImageFont.truetype(MONO, size)
        self.bold = ImageFont.truetype(MONO, size, index=1)
        self.title_font = ImageFont.truetype(SANS, 17)
        self.lh = int(size * 1.45)
        self.cw = self.font.getlength("M")
        self.title = title

    def wrap(self, prefix: str, text: str, maxlines: int = 2) -> list[str]:
        cols = int((self.w - 28) / self.cw) - len(prefix)
        text = " ".join(text.split())
        lines = []
        while text and len(lines) < maxlines:
            lines.append(text[:cols])
            text = text[cols:]
        if text:
            lines[-1] = lines[-1][:-1] + "…"
        return [prefix + lines[0]] + ["  " + " " * (len(prefix) - 2) + x for x in lines[1:]]

    def lines_for(self, ev: dict, t0: float) -> list[tuple[str, tuple]]:
        ind = "" if ev["who"] == "guide" else "  │ "
        k = ev["kind"]
        if k == "cmd":
            return [(x, FG if ev["who"] == "guide" else (170, 176, 186)) for x in self.wrap(ind + "$ ", ev["text"], 2)]
        if k == "tool":
            return [(x, FG if ev["who"] == "guide" else (170, 176, 186)) for x in self.wrap(ind + "· ", ev["text"], 1)]
        if k == "agent":
            return [(x, AMBER) for x in self.wrap(ind + "▸ dispatch ", ev["text"], 1)]
        if k == "text":
            return [(x, BLUE) for x in self.wrap(ind + "● ", ev["text"], 3)]
        if k == "result":
            return [(x, DIM) for x in self.wrap(ind + "  └ ", ev["text"], 1)]
        if k == "error":
            return [(x, RED) for x in self.wrap(ind + "  └ ", ev["text"], 1)]
        if k == "done":
            return [(x, GREEN) for x in self.wrap("✔ ", ev["text"], 1)]
        return []

    def render(self, evs: list[dict], now: float, t0: float, badge: str = "") -> Image.Image:
        img = Image.new("RGBA", (self.w, self.h), BG + (246,))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, self.w, 34], fill=BAR + (255,))
        for i, col in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
            d.ellipse([14 + i * 20, 11, 26 + i * 20, 23], fill=col)
        d.text((84, 8), self.title, font=self.title_font, fill=(190, 195, 204))
        el = max(0, now - t0)
        clock = f"{int(el // 60):d}:{int(el % 60):02d}"
        cl = self.bold.getlength(clock)
        d.text((self.w - 14 - cl, 8), clock, font=self.bold, fill=AMBER)
        if badge:
            bl = self.bold.getlength(badge) + 16
            x = self.w - 28 - cl - bl
            d.rounded_rectangle([x, 6, x + bl, 28], 6, fill=AMBER)
            d.text((x + 8, 8), badge, font=self.bold, fill=BG)
        shown = [e for e in evs if e["t"] <= now]
        rows: list[tuple[str, tuple]] = []
        for e in shown:
            rows += self.lines_for(e, t0)
        maxrows = (self.h - 46) // self.lh
        rows = rows[-maxrows:]
        y = 44
        for text, col in rows:
            d.text((14, y), text, font=self.font, fill=col)
            y += self.lh
        return img


def frame_shadowed(img: Image.Image, radius: int = 12) -> Image.Image:
    """Rounded corners and a 1 px border."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius, outline=(70, 75, 86, 255))
    return out

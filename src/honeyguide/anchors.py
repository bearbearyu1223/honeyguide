"""Code anchors: an agent quotes text, the script finds the lines. Pure functions over lists of lines.

Resolution never guesses: text found on several lines is ``ambiguous`` (with the candidates), text found on
none is ``not_found``. The hash covers the cited lines, so a later reader can tell whether they changed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import PurePosixPath

from .outline import Unit, enclosing_unit, line_hash, python_units

__all__ = ["CodeAnchor", "Relocation", "Resolution", "find_text", "line_hash", "relocate", "resolve"]


def check_path(path: str) -> str:
    """A normalized repo-relative POSIX path, or ValueError."""
    pure = PurePosixPath(path)
    if (not path or "\x00" in path or "\\" in path or pure.is_absolute() or ".." in pure.parts
            or str(pure) != path):
        raise ValueError(f"{path!r}: not a normalized repository-relative path")
    return path


@dataclass(frozen=True)
class CodeAnchor:
    path: str
    anchor: str
    start: int
    end: int
    commit: str
    hash: str
    symbol: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "CodeAnchor":
        return cls(path=data["path"], anchor=data["anchor"], start=int(data["start"]),
                   end=int(data["end"]), commit=data["commit"], hash=data["hash"],
                   symbol=data.get("symbol"))

    def moved_to(self, path: str, start: int, end: int, commit: str, symbol: str | None) -> "CodeAnchor":
        return replace(self, path=path, start=start, end=end, commit=commit, symbol=symbol)


@dataclass(frozen=True)
class Resolution:
    """``status`` is ``found``, ``ambiguous``, ``not_found`` or ``no_file``."""

    status: str
    anchor: CodeAnchor | None = None
    candidates: tuple[int, ...] = ()
    message: str = ""


def _anchor_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.strip("\n").split("\n")]
    return [line for line in lines if line] or [""]


def find_text(lines: list[str], text: str, lo: int = 1, hi: int | None = None) -> list[int]:
    """1-based start lines where ``text`` occurs, line by line, within ``lo..hi``.

    A one-line anchor matches any line containing it (whitespace-trimmed). A multi-line anchor matches
    consecutive lines, each containing its trimmed counterpart; blank anchor lines are ignored.
    """
    wanted = _anchor_lines(text)
    if wanted == [""]:
        return []
    hi = len(lines) if hi is None else min(hi, len(lines))
    hits = []
    for i in range(lo - 1, hi - len(wanted) + 1):
        if all(w in lines[i + k] for k, w in enumerate(wanted)):
            hits.append(i + 1)
    return hits


def block_end(lines: list[str], start: int) -> int:
    """Last line of the indented block that starts at ``start`` (a def, class, if, ...).

    Follows the header across a multi-line signature (until a line ending in ``:``), then takes every
    following line indented deeper, or blank; trailing blank lines are not included.
    """
    def indent(s: str) -> int:
        return len(s) - len(s.lstrip())

    base = indent(lines[start - 1])
    i = start - 1
    while i < len(lines) - 1 and not lines[i].split("#", 1)[0].rstrip().endswith(":"):
        i += 1
    if not lines[i].split("#", 1)[0].rstrip().endswith(":"):
        return start
    end = i + 1
    for j in range(i + 1, len(lines)):
        if not lines[j].strip():
            continue
        if indent(lines[j]) <= base:
            break
        end = j + 1
    return end


def resolve(lines: list[str] | None, path: str, anchor: str, commit: str, *,
            end_anchor: str | None = None, extent: str = "lines") -> Resolution:
    """Turn quoted text into a CodeAnchor at ``commit``.

    ``extent``: ``lines`` (just the quoted lines, or up to ``end_anchor``) or ``block`` (the whole indented
    block the anchor opens, e.g. a function).
    """
    check_path(path)
    if lines is None:
        return Resolution("no_file", message=f"{path}: not in commit {commit[:12]} (or binary)")
    hits = find_text(lines, anchor)
    if not hits:
        return Resolution("not_found", message=f"{path}: {anchor!r} is on no line")
    if len(hits) > 1:
        shown = ", ".join(map(str, hits[:8]))
        return Resolution("ambiguous", candidates=tuple(hits),
                          message=f"{path}: {anchor!r} matches {len(hits)} places (lines {shown}); "
                                  "quote more lines to make it unique")
    start = hits[0]
    end = start + len(_anchor_lines(anchor)) - 1
    if end_anchor:
        after = find_text(lines, end_anchor, lo=start)
        if not after:
            return Resolution("not_found", message=f"{path}: end {end_anchor!r} not at or after line {start}")
        end = max(end, after[0] + len(_anchor_lines(end_anchor)) - 1)
    elif extent == "block":
        end = max(end, block_end(lines, start))
    unit = enclosing_unit(python_units(lines), start, end) if path.endswith(".py") else None
    return Resolution("found", CodeAnchor(path, anchor, start, end, commit,
                                          line_hash(lines[start - 1:end]), unit.qualname if unit else None))


def span_hashes(lines: list[str], length: int, want: str, first: str | None = None) -> list[int]:
    """1-based starts of every ``length``-line window whose hash is ``want``.

    ``first``: text the window's first line must contain (an anchor always starts on its first cited
    line), which skips hashing almost every window.
    """
    starts = find_text(lines, first) if first else range(1, len(lines) + 1)
    return [s for s in starts
            if s + length - 1 <= len(lines) and line_hash(lines[s - 1:s - 1 + length]) == want]


@dataclass(frozen=True)
class Relocation:
    """Where an anchor's lines are in a newer version of the file.

    ``state``: ``unchanged``, ``moved``, ``stale`` or ``retired``; ``start``/``end`` the new location when
    known (for stale, a candidate for the Checker, not a fact).
    """

    state: str
    start: int | None = None
    end: int | None = None
    symbol: str | None = None
    reason: str = ""


def relocate(old: CodeAnchor, new_lines: list[str] | None, new_path: str,
             new_units: list[Unit] | None = None) -> Relocation:
    """Classify one anchor against the file's new content (the file is known to have changed or moved)."""
    if new_lines is None:
        return Relocation("retired", reason="file gone")
    if new_units is None:
        new_units = python_units(new_lines) if new_path.endswith(".py") else []
    by_name = {u.qualname: u for u in new_units}
    length = old.end - old.start + 1
    path_moved = new_path != old.path

    def symbol_at(start: int, end: int) -> str | None:
        unit = enclosing_unit(new_units, start, end)
        return unit.qualname if unit else None

    if old.end <= len(new_lines) and line_hash(new_lines[old.start - 1:old.end]) == old.hash:
        here = symbol_at(old.start, old.end)
        # Same text at the same place counts only inside the same definition: identical lines from another
        # function that slid into the old position are not this anchor.
        if not old.symbol or here == old.symbol or old.symbol not in by_name:
            return Relocation("moved" if path_moved else "unchanged", old.start, old.end, here,
                              "renamed" if path_moved else "")
    same = span_hashes(new_lines, length, old.hash, first=_anchor_lines(old.anchor)[0] or None)
    unit = by_name.get(old.symbol) if old.symbol else None
    if len(same) > 1 and unit is not None:
        same = [s for s in same if unit.start <= s and s + length - 1 <= unit.end]
    if len(same) == 1:
        s = same[0]
        return Relocation("moved", s, s + length - 1, symbol_at(s, s + length - 1), "same lines elsewhere")
    if len(same) > 1:
        return Relocation("stale", reason=f"ambiguous: the cited lines occur {len(same)} times")
    if unit is not None:
        inside = find_text(new_lines, old.anchor, unit.start, unit.end)
        if len(inside) == 1:
            s = inside[0]
            e = min(s + length - 1, unit.end)
            return Relocation("stale", s, e, unit.qualname, "lines changed")
        return Relocation("stale", unit.start, unit.end, unit.qualname, "lines changed; symbol still exists")
    hits = find_text(new_lines, old.anchor)
    if len(hits) == 1:
        s = hits[0]
        e = min(s + length - 1, len(new_lines))
        return Relocation("stale", s, e, symbol_at(s, e), "lines changed")
    if len(hits) > 1:
        return Relocation("stale", reason=f"lines changed; anchor text matches {len(hits)} places")
    return Relocation("retired", reason="code gone" + (f" ({old.symbol} removed)" if old.symbol else ""))

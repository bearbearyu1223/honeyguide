"""The outline of a Python file: module-level functions, classes, and methods of top-level classes.

These are the units refresh uses to keep an anchor inside its function and to find new code no claim covers.
A class's own unit hashes its lines minus its methods, so editing one method doesn't mark the class changed.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Unit:
    qualname: str
    kind: str      # function, class, method
    start: int     # first decorator line, or the def/class line
    end: int
    hash: str


def line_hash(lines: list[str]) -> str:
    """sha256 over the lines, trailing whitespace ignored, 16 hex characters."""
    joined = "\n".join(line.rstrip() for line in lines)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _span(node: ast.AST) -> tuple[int, int]:
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return first, node.end_lineno or node.lineno


def python_units(lines: list[str]) -> list[Unit]:
    """Units in source order; [] if the file doesn't parse."""
    try:
        tree = ast.parse("\n".join(lines) + "\n")
    except (SyntaxError, ValueError):
        return []
    units: list[Unit] = []
    for node in tree.body:
        if isinstance(node, _DEFS):
            start, end = _span(node)
            units.append(Unit(node.name, "function", start, end, line_hash(lines[start - 1:end])))
        elif isinstance(node, ast.ClassDef):
            start, end = _span(node)
            methods = []
            for child in node.body:
                if isinstance(child, _DEFS):
                    ms, me = _span(child)
                    methods.append(Unit(f"{node.name}.{child.name}", "method", ms, me,
                                        line_hash(lines[ms - 1:me])))
            in_methods = {n for m in methods for n in range(m.start, m.end + 1)}
            own = [lines[n - 1] for n in range(start, end + 1) if n not in in_methods]
            units.append(Unit(node.name, "class", start, end, line_hash(own)))
            units.extend(methods)
    return units


def enclosing_unit(units: list[Unit], start: int, end: int) -> Unit | None:
    """The smallest unit containing lines ``start..end``."""
    inside = [u for u in units if u.start <= start and end <= u.end]
    return min(inside, key=lambda u: u.end - u.start) if inside else None

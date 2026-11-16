"""Script-built outline of a repo (the eval's "outline" condition): files, classes, functions with signatures,
imports, from the pinned commit's source with stdlib ast. Size-matched to the map in tokens.

Tokens are estimated as characters / 4 (no local Claude tokenizer exists; the runs' real input-token counts
show the true sizes afterwards). The same estimate measures the map, so the match is like for like.

Detail levels, each adding to the one before:
  0  files, classes and functions (module level and class level), with line numbers
  1  + signatures (arguments, return annotation, base classes)
  2  + imports (one line per file)
  3  + the first line of each docstring
  4  + whole docstrings (instead of first lines)
  5  + module- and class-level assignments (names, values cut at 60 chars) and functions nested in functions
Size matching: the richest level whose whole outline fits the target; then files are upgraded one level, in path
order, while the total still fits. If even level 0 is over the target, files are left out from the end (and the
outline says how many). Deterministic: same source, same target, same text.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

LEVELS = 6
VALUE_CHARS = 60


def est_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"({ast.unparse(node.args)}){ret}"


def _doc1(node) -> str:
    doc = ast.get_docstring(node, clean=True)
    return doc.strip().splitlines()[0].strip() if doc and doc.strip() else ""


def _doc_lines(node, level: int, pad: str) -> list[str]:
    """Docstring lines at this level: none below 3, the first line at 3, all of it from 4."""
    if level < 3:
        return []
    doc = ast.get_docstring(node, clean=True)
    if not doc or not doc.strip():
        return []
    lines = [ln.rstrip() for ln in doc.strip().splitlines()] if level >= 4 else [_doc1(node)]
    return [f"{pad}# {ln}" if ln else f"{pad}#" for ln in lines]


def _assign(n, pad: str) -> list[str]:
    if isinstance(n, ast.Assign):
        names = ", ".join(ast.unparse(t) for t in n.targets)
    elif isinstance(n, ast.AnnAssign):
        names = f"{ast.unparse(n.target)}: {ast.unparse(n.annotation)}"
    else:
        return []
    value = "" if getattr(n, "value", None) is None else " ".join(ast.unparse(n.value).split())
    if len(value) > VALUE_CHARS:
        value = value[:VALUE_CHARS - 3] + "..."
    return [f"{pad}{names}" + (f" = {value}" if value else "") + f"  L{n.lineno}"]


def _imports(tree: ast.Module) -> list[str]:
    out = []
    for n in tree.body:
        if isinstance(n, ast.Import):
            out += [a.name + (f" as {a.asname}" if a.asname else "") for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mod = "." * n.level + (n.module or "")
            out.append(f"from {mod} import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "")
                                                          for a in n.names))
    return out


def _defs(body, indent: int, level: int, in_func: bool = False) -> list[str]:
    lines = []
    pad = "  " * indent
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kw = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
            sig = _sig(n) if level >= 1 else ""
            lines.append(f"{pad}{kw} {n.name}{sig}  L{n.lineno}")
            lines += _doc_lines(n, level, pad + "  ")
            if level >= 5:
                lines += _defs(_nested_defs(n.body), indent + 1, level, in_func=True)
        elif isinstance(n, ast.ClassDef):
            bases = ""
            if level >= 1 and (n.bases or n.keywords):
                bases = "(" + ", ".join([ast.unparse(b) for b in n.bases] +
                                        [ast.unparse(k) for k in n.keywords]) + ")"
            lines.append(f"{pad}class {n.name}{bases}  L{n.lineno}")
            lines += _doc_lines(n, level, pad + "  ")
            lines += _defs(n.body, indent + 1, level, in_func=in_func)
        elif level >= 5 and not in_func:
            lines += _assign(n, pad)
    return lines


def _nested_defs(body) -> list:
    """Functions and classes defined anywhere inside a function body (not inside their own bodies)."""
    out = []
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n)
        else:
            for child in ast.iter_child_nodes(n):
                if isinstance(child, ast.stmt):
                    out += _nested_defs([child])
    return out


def file_outline(path: str, source: str, level: int) -> str:
    n_lines = len(source.splitlines())
    head = f"## {path} ({n_lines} lines)"
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"{head}\n(not parsed: SyntaxError line {exc.lineno})\n"
    lines = [head]
    if level >= 2:
        imps = _imports(tree)
        if imps:
            lines.append("imports: " + "; ".join(imps))
    lines += _doc_lines(tree, level, "")
    lines += _defs(tree.body, 0, level)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Outline:
    text: str
    tokens: int
    target: int
    levels: dict[str, int]       # per file: the detail level used (-1 = left out)
    left_out: int

    def summary(self) -> str:
        used = sorted(v for v in self.levels.values() if v >= 0)
        counts = {lv: used.count(lv) for lv in range(LEVELS)}
        return (f"outline {self.tokens} tokens (est.) vs target {self.target}; files per level "
                + ", ".join(f"L{lv}={counts[lv]}" for lv in range(LEVELS)) + f"; left out {self.left_out}")


def header(repo: str, commit: str) -> str:
    return (f"# Outline of {repo} at {commit[:12]}\n"
            "Script-built from the source with Python's ast: files, classes and functions with line numbers"
            " (signatures, imports, docstrings and assignments where they fit).\n\n")


def build_outline(repo: str, commit: str, sources: dict[str, str], target_tokens: int) -> Outline:
    """sources: {repo path: text}; files are listed in path order."""
    paths = sorted(sources)
    per = {p: [file_outline(p, sources[p], lv) for lv in range(LEVELS)] for p in paths}
    head = header(repo, commit)
    note = len("(999 more files left out to fit the size)\n")

    def total(levels: dict[str, int]) -> int:   # the joined text's estimate, as assembled below
        chars = len(head) + sum(len(per[p][lv]) + 1 for p, lv in levels.items() if lv >= 0)
        if any(lv < 0 for lv in levels.values()):
            chars += note
        return (chars + 3) // 4

    level = -1
    for lv in range(LEVELS):
        if total({p: lv for p in paths}) <= target_tokens:
            level = lv
    if level >= 0:
        levels = {p: level for p in paths}
        if level < LEVELS - 1:
            for p in paths:
                trial = dict(levels, **{p: level + 1})
                if total(trial) <= target_tokens:
                    levels = trial
    else:
        levels = {p: -1 for p in paths}
        for p in paths:
            trial = dict(levels, **{p: 0})
            if total(trial) > target_tokens:
                break
            levels = trial
    left_out = sum(1 for v in levels.values() if v < 0)
    body = "".join(per[p][levels[p]] + "\n" for p in paths if levels[p] >= 0)
    if left_out:
        body += f"({left_out:3d} more files left out to fit the size)\n"
    text = head + body
    return Outline(text=text, tokens=est_tokens(text), target=target_tokens, levels=levels, left_out=left_out)

"""Runtime call tracer for Honeyguide's flow-question answer keys.

Standard library only, and runs on Python 3.10+ because it is imported by the
runner inside each target repo's own virtual environment.

It records the ordered Python function calls whose code lives in the target
repo's package source (tests, site-packages, the standard library and
synthetic frames such as lambdas and comprehensions are dropped), with:

- the qualified name, taken from the source file's syntax tree so it is the
  same on 3.10 (no ``co_qualname``) and 3.12;
- ``file:line`` of the ``def`` (the first decorator line when decorated, which
  is what Python reports as the code object's first line);
- the depth, counted in kept frames only, so library frames between two repo
  functions do not inflate it;
- the nearest kept caller and the line it was on, so the same trace can key
  "what calls X" questions.

Generators: Python reports every resume of a suspended generator as a new
"call" event. The tracer marks those as ``resume`` (detected by the frame
having last stopped on a YIELD_VALUE), so they are never mistaken for calls.

Threads: ``threading.setprofile`` covers threads started while tracing. A
worker thread's depth is offset by the kept depth of the main thread's stack
at the moment the worker first runs repo code (the main thread is blocked
waiting for it), and its top kept frame's caller is the nearest kept frame on
the main thread's stack, with no call line (which line the main thread is on
when the worker starts is a race). Threads are labelled main, worker-1, worker-2, ... in
order of first kept event, so labels compare across runs.
"""

from __future__ import annotations

import ast
import dis
import inspect
import os
import sys
import threading
from dataclasses import dataclass

GEN_FLAGS = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
YIELD_OP = dis.opmap["YIELD_VALUE"]
DEFAULT_EXCLUDE_PARTS = ("tests", "test", "site-packages", "dist-packages")


# --------------------------------------------------------------------------
# Filter rules (pure)

@dataclass(frozen=True)
class FilterRules:
    """Which code counts as repo-owned.

    roots: absolute package source directories (e.g. <clone>/nanochat).
    exclude_parts: a path component under the root that drops the file.
    """

    roots: tuple
    exclude_parts: tuple = DEFAULT_EXCLUDE_PARTS

    def describe(self, repo_root):
        rel = [os.path.relpath(r, repo_root) + "/" for r in self.roots]
        return [
            "keep: Python code whose file is under " + ", ".join(rel),
            "drop: files with a directory named "
            + ", ".join(self.exclude_parts[:2]) + ",",
            "      " + ", ".join(self.exclude_parts[2:])
            + " between the root and the file",
            "drop: stdlib, site-packages, <string> and <frozen> code",
            "drop: synthetic frames: lambdas, comprehensions, genexprs,",
            "      module and class bodies",
            "drop: C functions (only Python 'call' events are seen)",
        ]


def path_kept(filename, rules):
    """True if a code object's file is inside one of the roots and no path
    part below the root is an excluded name. Pure apart from realpath."""
    if not filename or filename.startswith("<"):
        return False
    path = os.path.realpath(filename)
    for root in rules.roots:
        root = os.path.realpath(root)
        if path == root or not path.startswith(root + os.sep):
            continue
        parts = os.path.relpath(path, root).split(os.sep)
        if any(p in rules.exclude_parts for p in parts[:-1]):
            return False
        return path.endswith(".py")
    return False


def is_synthetic(co_name, co_flags=inspect.CO_NEWLOCALS):
    """Lambdas, comprehensions, generator expressions, and module and class
    bodies (the only code objects without CO_NEWLOCALS)."""
    return co_name.startswith("<") or not co_flags & inspect.CO_NEWLOCALS


# --------------------------------------------------------------------------
# Qualified names from source (same answer on every Python version)

def qualnames_from_source(source):
    """Map first line of each def (decorator line if decorated) to its
    qualified name, in co_qualname style ("Outer.<locals>.inner")."""
    out = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = [d.lineno for d in child.decorator_list] + [child.lineno]
                qual = prefix + child.name
                out[min(lines)] = qual
                visit(child, qual + ".<locals>.")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(ast.parse(source), "")
    return out


class QualnameIndex:
    def __init__(self):
        self._files = {}

    def lookup(self, filename, firstlineno, fallback):
        table = self._files.get(filename)
        if table is None:
            try:
                with open(filename, encoding="utf-8") as fh:
                    table = qualnames_from_source(fh.read())
            except (OSError, SyntaxError, ValueError):
                table = {}
            self._files[filename] = table
        return table.get(firstlineno, fallback)


# --------------------------------------------------------------------------
# The tracer

class Tracer:
    def __init__(self, rules, repo_root):
        self.rules = rules
        self.repo_root = os.path.realpath(repo_root)
        self.index = QualnameIndex()
        self.events = []
        self.phase = None
        self.counts = {}
        self._code_info = {}
        self._suspended = {}
        self._thread_labels = {}
        self._thread_offsets = {}
        self._main_ident = threading.main_thread().ident
        self._lock = threading.Lock()

    # counts are per phase: raw Python call events, kept calls, resumes,
    # synthetic repo frames dropped
    def _bump(self, key):
        self.counts[self.phase][key] += 1

    def _info(self, code):
        info = self._code_info.get(code, False)
        if info is not False:
            return info
        info = None
        if path_kept(code.co_filename, self.rules):
            if is_synthetic(code.co_name, code.co_flags):
                info = "synthetic"
            else:
                path = os.path.realpath(code.co_filename)
                qual = self.index.lookup(path, code.co_firstlineno, None)
                fallback = qual is None
                native = getattr(code, "co_qualname", None)  # 3.11+
                if fallback:
                    qual = native or code.co_name
                # None: cannot check (3.10); True/False: agrees with Python
                agrees = None if native is None or fallback else native == qual
                info = (qual, os.path.relpath(path, self.repo_root),
                        code.co_firstlineno, fallback, agrees)
        self._code_info[code] = info
        return info

    def _kept_ancestors(self, frame):
        """(depth, nearest kept caller qualname, that caller's current line)."""
        depth, caller, line = 0, None, None
        f = frame
        while f is not None:
            info = self._info(f.f_code)
            if isinstance(info, tuple):
                if caller is None:
                    caller, line = info[0], f.f_lineno
                depth += 1
            f = f.f_back
        return depth, caller, line

    def _thread_context(self, ident):
        """Offset depth and caller for a thread's top kept frame."""
        if ident == self._main_ident:
            return 0, None, None
        ctx = self._thread_offsets.get(ident)
        if ctx is None:
            main = sys._current_frames().get(self._main_ident)
            ctx = self._kept_ancestors(main) if main is not None else (0, None, None)
            self._thread_offsets[ident] = ctx
        return ctx

    def _label(self, ident):
        label = self._thread_labels.get(ident)
        if label is None:
            if ident == self._main_ident:
                label = "main"
            else:
                n = sum(1 for v in self._thread_labels.values() if v != "main")
                label = "worker-%d" % (n + 1)
            self._thread_labels[ident] = label
        return label

    def _profile(self, frame, event, arg):
        if self.phase is None:
            # a thread started during a phase keeps this hook after it ends
            return
        if event == "call":
            with self._lock:
                self._on_call(frame)
        elif event == "return":
            code = frame.f_code
            if code.co_flags & GEN_FLAGS and isinstance(self._info(code), tuple):
                with self._lock:
                    lasti = frame.f_lasti
                    if lasti >= 0 and code.co_code[lasti] == YIELD_OP:
                        self._suspended[id(frame)] = frame
                    else:
                        self._suspended.pop(id(frame), None)

    def _on_call(self, frame):
        self._bump("raw_calls")
        info = self._info(frame.f_code)
        if info is None:
            return
        if info == "synthetic":
            self._bump("dropped_synthetic")
            return
        qual, rel, line, fallback, agrees = info
        kind = "call"
        if self._suspended.get(id(frame)) is frame:
            kind = "resume"
        ident = threading.get_ident()
        depth, caller, call_line = self._kept_ancestors(frame.f_back)
        if caller is None:
            # Crossing into a worker thread: the caller function is known,
            # but the line the main thread is on is a race (it may still be
            # in executor.submit or already waiting in future.result), so
            # no call line is recorded for this hop.
            offset, caller, _racy_line = self._thread_context(ident)
            call_line = None
            depth += offset
        else:
            depth += self._thread_context(ident)[0]
        self._bump("kept_calls" if kind == "call" else "kept_resumes")
        if fallback:
            self._bump("qualname_fallbacks")
        if agrees is not None:
            self._bump("qualname_checked")
            if not agrees:
                self._bump("qualname_mismatches")
        self.events.append({
            "phase": self.phase, "thread": self._label(ident), "kind": kind,
            "qual": qual, "file": rel, "line": line, "depth": depth,
            "caller": caller, "call_line": call_line,
        })

    def run_phase(self, name, fn):
        """Trace one call of fn() as phase `name`; returns fn's result."""
        self.phase = name
        self.counts[name] = {
            "raw_calls": 0, "kept_calls": 0, "kept_resumes": 0,
            "dropped_synthetic": 0, "qualname_fallbacks": 0,
            "qualname_checked": 0, "qualname_mismatches": 0,
        }
        threading.setprofile(self._profile)
        sys.setprofile(self._profile)
        try:
            return fn()
        finally:
            sys.setprofile(None)
            threading.setprofile(None)
            self.phase = None


# --------------------------------------------------------------------------
# Views of a kept path (pure)

def path_key(events):
    """What must match between two runs for the kept path to be identical."""
    return [(e["phase"], e["thread"], e["kind"], e["qual"], e["file"],
             e["line"], e["depth"], e["caller"], e["call_line"])
            for e in events]


def first_difference(a, b):
    """Index of the first differing element, or None if equal."""
    for i, (x, y) in enumerate(zip(a, b, strict=False)):  # lengths may differ
        if x != y:
            return i
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def build_tree(events):
    """Nest events by depth. Returns a list of root nodes; a node is
    {"e": event, "children": [...]}. Depths are made relative to the
    shallowest event; a jump of more than one level attaches to the
    nearest open node above it."""
    if not events:
        return []
    base = min(e["depth"] for e in events)
    roots, stack = [], []
    for e in events:
        d = e["depth"] - base
        node = {"e": e, "children": []}
        while stack and stack[-1][0] >= d:
            stack.pop()
        (stack[-1][1]["children"] if stack else roots).append(node)
        stack.append((d, node))
    return roots


def _label(e):
    tag = "" if e["kind"] == "call" else "(resume) "
    thread = "" if e["thread"] == "main" else "[%s] " % e["thread"]
    return thread + tag + e["qual"]


def signature(node):
    return (_label(node["e"]), node["e"]["file"], node["e"]["line"],
            tuple(signature(c) for c in node["children"]))


def fold(nodes):
    """Fold consecutive siblings whose whole subtrees are identical.
    Returns [(node, repeat_count, folded_children)]."""
    out = []
    for node in nodes:
        sig = signature(node)
        if out and out[-1][3] == sig:
            out[-1][1] += 1
        else:
            out.append([node, 1, fold(node["children"]), sig])
    return [(n, k, kids) for n, k, kids, _ in out]


def collapse(events, max_depth):
    """Collapsed view: [(depth, label, file:line, repeat, hidden)] where
    hidden counts kept calls below max_depth under that line (per copy)."""
    rows = []

    def count(node):
        return sum(1 + count(c) for c in node["children"])

    def walk(items, depth):
        for node, repeat, kids in items:
            e = node["e"]
            hidden = count(node) if depth == max_depth else 0
            rows.append((depth, _label(e), "%s:%d" % (e["file"], e["line"]),
                         repeat, hidden))
            if depth < max_depth:
                walk(kids, depth + 1)

    walk(fold(build_tree(events)), 0)
    return rows


def render_rows(rows, width=74, indent=2):
    """Lines of at most `width` columns: indented name on the left, anchor
    on the right. When they do not fit on one line, the anchor (with any
    xN / deeper tags) goes right-aligned on the next line; when the
    indented name alone is too wide, the indent is replaced by "<depth>> ".
    Names are never truncated unless one is wider than `width` itself."""
    lines = []
    for depth, label, anchor, repeat, hidden in rows:
        tags = ""
        if repeat > 1:
            tags += " x%d" % repeat
        if hidden:
            tags += " (+%d deeper)" % hidden
        left = " " * (indent * depth) + label
        if len(left) + len(tags) + 2 + len(anchor) <= width:
            left += tags
            lines.append(left + " " * (width - len(left) - len(anchor)) + anchor)
            continue
        if len(left) > width:
            left = ("%d> " % depth) + label
        right = (tags.strip() + "  " if tags else "") + anchor
        lines.append(left[:width])
        lines.append(right.rjust(width)[-width:])
    return lines

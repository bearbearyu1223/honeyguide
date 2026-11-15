"""Answer keys for Honeyguide's generated eval questions (pure helpers).

Standard library only. Everything here works on source text, git output or
trace events handed in as arguments, so each piece is testable on small
fixtures; generate.py does the I/O.

- function_index: every def in a file, with the co_qualname-style name the
  T3 tracer uses ("Outer.<locals>.inner", "Class.method"), its line range,
  and the facts the filters need (property, cached, dunder, trivial).
- call_graph: who calls whom, resolved from the syntax tree only, plus the
  calls the syntax tree cannot settle (dynamic dispatch, getattr, callbacks
  passed by reference), which become disputes for Han.
- trace_callers / flow_hops: the same questions answered from the runtime
  trace, and the rule-based pre-filter that turns a trace phase into a short
  list of candidate hops.
- parse_blame / tag_lines: which key lines were last changed after a cutoff.
- leaks: question text that names its own answer.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

CACHE_DECORATORS = {"lru_cache", "cache", "cached_property"}
PROPERTY_DECORATORS = {"property", "cached_property", "setter", "getter", "deleter"}
KEEP_DUNDERS = {"__init__", "__call__"}


# --------------------------------------------------------------------------
# Function index

@dataclass(frozen=True)
class Func:
    file: str            # repo-relative path
    qual: str            # co_qualname style
    name: str
    cls: str | None      # enclosing class qualname, if a method
    start: int           # first decorator line, else the def line
    def_line: int
    end: int
    decorators: tuple
    trivial: bool        # one-statement body with no call, or a get_/is_/has_ one-liner
    body_lines: int      # end - def_line

    @property
    def is_property(self):
        return any(d.split(".")[-1] in PROPERTY_DECORATORS for d in self.decorators)

    @property
    def is_cached(self):
        return any(d.split(".")[-1] in CACHE_DECORATORS for d in self.decorators)

    @property
    def is_dunder(self):
        return self.name.startswith("__") and self.name.endswith("__")

    @property
    def key(self):
        return (self.file, self.qual)


def _decorator_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _body_without_docstring(fn):
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body


def _has_call(node):
    return any(isinstance(n, ast.Call) for n in ast.walk(node))


def is_trivial(fn):
    """A one-statement body that is `return <expr without calls>` or `pass`/
    `...`, or a get_/is_/has_ function whose body is one return."""
    body = _body_without_docstring(fn)
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return True
    if not isinstance(stmt, ast.Return):
        return False
    if stmt.value is None or not _has_call(stmt.value):
        return True
    return fn.name.startswith(("get_", "is_", "has_"))


def function_index(source, path):
    """All defs in one file (nested ones included), in source order."""
    out = []

    def visit(node, prefix, cls):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decos = tuple(_decorator_name(d) for d in child.decorator_list)
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                qual = prefix + child.name
                out.append(Func(
                    file=path, qual=qual, name=child.name, cls=cls, start=start,
                    def_line=child.lineno, end=child.end_lineno, decorators=decos,
                    trivial=is_trivial(child), body_lines=child.end_lineno - child.lineno,
                ))
                visit(child, qual + ".<locals>.", None)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".", prefix + child.name)
            else:
                visit(child, prefix, cls)

    visit(ast.parse(source), "", None)
    return out


# --------------------------------------------------------------------------
# Module-level facts for the call graph

@dataclass
class ModuleInfo:
    path: str
    module: str                      # dotted name, e.g. "smolagents.agents"
    tree: ast.Module
    funcs: dict = field(default_factory=dict)      # top-level function name -> qual
    classes: dict = field(default_factory=dict)    # class qual -> ClassInfo
    imports: dict = field(default_factory=dict)    # local name -> (module, name or None)


@dataclass
class ClassInfo:
    path: str
    qual: str
    bases: tuple                     # base expressions as dotted strings
    methods: dict                    # method name -> qual


def module_name(path, package_roots):
    """'src/smolagents/agents.py' with root 'src' -> 'smolagents.agents'."""
    p = path[:-3] if path.endswith(".py") else path
    for root in sorted(package_roots, key=len, reverse=True):
        if root and p.startswith(root.rstrip("/") + "/"):
            p = p[len(root.rstrip("/")) + 1:]
            break
    parts = p.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module, level, target, is_package):
    if level == 0:
        return target or ""
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    if level > 1:
        parts = parts[:len(parts) - (level - 1)]
    base = ".".join(parts)
    if target:
        return base + "." + target if base else target
    return base


def module_info(source, path, package_roots=("",)):
    tree = ast.parse(source)
    mod = module_name(path, package_roots)
    info = ModuleInfo(path=path, module=mod, tree=tree)
    is_package = path.endswith("__init__.py")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.funcs[node.name] = node.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    info.imports[a.asname] = (a.name, None)
                else:
                    top = a.name.split(".")[0]
                    info.imports[top] = (top, None)
        elif isinstance(node, ast.ImportFrom):
            src = _resolve_relative(mod, node.level, node.module, is_package)
            for a in node.names:
                info.imports[a.asname or a.name] = (src, a.name)

    def visit_classes(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = prefix + child.name
                methods = {c.name: qual + "." + c.name for c in child.body
                           if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))}
                info.classes[qual] = ClassInfo(
                    path=path, qual=qual,
                    bases=tuple(_decorator_name(b) for b in child.bases), methods=methods)
                visit_classes(child, qual + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            else:
                visit_classes(child, prefix)

    visit_classes(tree, "")
    return info


# --------------------------------------------------------------------------
# Call graph

@dataclass(frozen=True)
class Edge:
    caller_file: str
    caller: str          # caller qual, or "<module>" for top-level code
    line: int            # line of the call (or reference)
    callee_file: str
    callee: str
    via: str             # how it was resolved, see RESOLUTION


@dataclass(frozen=True)
class Dispute:
    caller_file: str
    caller: str
    line: int
    name: str            # the attribute / string / reference name
    kind: str            # see DISPUTE_KINDS
    detail: str


RESOLUTION = {
    "name": "plain name: same-module function, nested function or import",
    "class": "class called by name -> its __init__ (found up the repo bases)",
    "self": "self.m() / cls.m() -> m on the class or its repo bases",
    "override": "self.m() -> an override of m in a repo subclass (class "
                "hierarchy analysis)",
    "super": "super().m() -> m on a repo base class",
    "module": "module.f() on an imported repo module",
    "classattr": "Class.m() on a repo class named in the code",
}
DISPUTE_KINDS = {
    "attr": "obj.m() on an object whose type the AST cannot see; m matches "
            "the target by name only",
    "getattr": "getattr(obj, 'm') with the target's name as a string",
    "reference": "the target passed or stored without being called (callback, "
                 "registry, decorator)",
}


class Project:
    """All modules of one repo, with name resolution across them."""

    def __init__(self, modules):
        self.modules = {m.path: m for m in modules}
        self.by_module = {m.module: m for m in modules}
        self.classes = {}            # (path, qual) -> ClassInfo
        for m in modules:
            for q, c in m.classes.items():
                self.classes[(m.path, q)] = c
        self.subclasses = {}         # (path, qual) -> direct repo subclasses
        for key, c in self.classes.items():
            for b in c.bases:
                base = self.resolve_class(self.modules[key[0]], b)
                if base:
                    self.subclasses.setdefault(base, []).append(key)

    # ---- symbol lookup
    def lookup(self, module, name, depth=0):
        """Resolve a module-level name to ('func'|'class', path, qual)."""
        if depth > 5 or module is None:
            return None
        if name in module.funcs:
            return ("func", module.path, name)
        if name in module.classes:
            return ("class", module.path, name)
        if name in module.imports:
            src, sym = module.imports[name]
            target = self.by_module.get(src)
            if sym is None:
                return ("module", target.path, "") if target else None
            if target is not None:
                hit = self.lookup(target, sym, depth + 1)
                if hit:
                    return hit
            sub = self.by_module.get(src + "." + sym)
            if sub is not None:
                return ("module", sub.path, "")
        return None

    def is_external(self, module, name):
        """True if name is bound by an import of a module outside the repo
        (json, torch, np): its attributes are never repo functions."""
        if name not in module.imports:
            return False
        src, sym = module.imports[name]
        if sym is not None:
            return False         # from x import y: y may be any object
        return not any(m == src or m.startswith(src + ".") for m in self.by_module)

    def resolve_class(self, module, dotted):
        parts = dotted.split(".")
        if len(parts) == 1:
            hit = self.lookup(module, parts[0])
        else:
            hit = self.lookup(module, parts[0])
            if hit and hit[0] == "module":
                hit = self.lookup(self.modules[hit[1]], parts[-1])
            else:
                hit = None
        if hit and hit[0] == "class":
            return (hit[1], hit[2])
        return None

    def mro(self, cls_key, seen=None):
        """The class and its repo bases, depth-first, left to right."""
        seen = seen if seen is not None else set()
        if cls_key in seen or cls_key not in self.classes:
            return []
        seen.add(cls_key)
        out = [cls_key]
        c = self.classes[cls_key]
        for b in c.bases:
            base = self.resolve_class(self.modules[cls_key[0]], b)
            if base:
                out.extend(self.mro(base, seen))
        return out

    def method(self, cls_key, name, skip_self=False):
        chain = self.mro(cls_key)
        if skip_self:
            chain = chain[1:]
        for k in chain:
            q = self.classes[k].methods.get(name)
            if q:
                return (k[0], q)
        return None

    def all_subclasses(self, cls_key):
        out, todo = [], list(self.subclasses.get(cls_key, []))
        while todo:
            k = todo.pop(0)
            if k not in out:
                out.append(k)
                todo.extend(self.subclasses.get(k, []))
        return out


def _scopes(tree):
    """(qual, self_class, node) for every function, and ("<module>", None,
    module) for top-level code. self_class is the class whose `self` the
    function sees: its own class for a method, the enclosing method's class
    for a function nested in a method (closures over self). A scope's calls
    are the Call nodes inside it but not inside a nested def or class."""
    out = [("<module>", None, tree)]

    def visit(node, prefix, cls):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + child.name
                out.append((qual, cls, child))
                visit(child, qual + ".<locals>.", cls)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".", prefix + child.name)
            else:
                visit(child, prefix, cls)

    visit(tree, "", None)
    return out


def _own_nodes(scope_node):
    """Nodes inside a scope, not descending into nested defs or classes
    (lambdas and comprehensions belong to the enclosing function, as the
    tracer's synthetic-frame rule does). Decorators and default values of a
    nested def run in the enclosing scope, so they are included."""
    todo = list(ast.iter_child_nodes(scope_node))
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        todo = list(scope_node.body)
    while todo:
        n = todo.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            todo.extend(n.decorator_list)
            if not isinstance(n, ast.ClassDef):
                todo.extend(n.args.defaults + [d for d in n.args.kw_defaults if d])
            else:
                todo.extend(n.bases)
            continue
        todo.extend(ast.iter_child_nodes(n))


def call_graph(project):
    """Resolved edges and unresolved attribute/getattr/reference sites.

    Returns (edges, attr_sites) where attr_sites lists every site the AST
    could not resolve as (caller_file, caller, line, name, kind); generate.py
    turns the ones whose name matches a question's target into disputes."""
    edges, sites = set(), set()
    for path in sorted(project.modules):
        mod = project.modules[path]
        for qual, cls, node in _scopes(mod.tree):
            cls_key = (path, cls) if cls and (path, cls) in project.classes else None
            nested = {}
            if qual != "<module>":
                for c in node.body:
                    if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        nested[c.name] = qual + ".<locals>." + c.name
            called_funcs = set()
            for n in _own_nodes(node):
                if not isinstance(n, ast.Call):
                    continue
                called_funcs.add(id(n.func))
                for e in _resolve_call(project, mod, path, qual, cls_key, nested, n):
                    if isinstance(e, Edge):
                        edges.add(e)
                    else:
                        sites.add(e)
            # references: a function name, or any obj.attr, that is loaded
            # without being the func of a Call (callbacks, registries)
            for n in _own_nodes(node):
                if id(n) in called_funcs:
                    continue
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    hit = project.lookup(mod, n.id)
                    if n.id in nested or (hit and hit[0] == "func"):
                        sites.add((path, qual, n.lineno, n.id, "reference"))
                elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
                    if isinstance(n.value, ast.Name) and project.is_external(mod, n.value.id):
                        continue
                    sites.add((path, qual, n.lineno, n.attr, "reference"))
    return sorted(edges, key=_edge_sort), sorted(sites)


def _edge_sort(e):
    return (e.callee_file, e.callee, e.caller_file, e.caller, e.line, e.via)


def _init_of(project, cls_key):
    return project.method(cls_key, "__init__")


def _resolve_call(project, mod, path, qual, cls_key, nested, call):
    f = call.func
    line = call.lineno
    out = []

    def edge(target, via):
        out.append(Edge(path, qual, line, target[0], target[1], via))

    if isinstance(f, ast.Name):
        if f.id == "getattr" and len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) \
                and isinstance(call.args[1].value, str):
            out.append((path, qual, line, call.args[1].value, "getattr"))
            return out
        if f.id in nested:
            edge((path, nested[f.id]), "name")
            return out
        hit = project.lookup(mod, f.id)
        if hit and hit[0] == "func":
            edge((hit[1], hit[2]), "name")
        elif hit and hit[0] == "class":
            init = _init_of(project, (hit[1], hit[2]))
            if init:
                edge(init, "class")
        return out
    if not isinstance(f, ast.Attribute):
        return out
    attr, base = f.attr, f.value
    if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls_key:
        hit = project.method(cls_key, attr)
        if hit:
            edge(hit, "self")
        for sub in project.all_subclasses(cls_key):
            q = project.classes[sub].methods.get(attr)
            if q and (sub[0], q) != hit:
                edge((sub[0], q), "override")
        if not hit and not any(project.classes[s].methods.get(attr)
                               for s in project.all_subclasses(cls_key)):
            out.append((path, qual, line, attr, "attr"))
        return out
    if (isinstance(base, ast.Call) and isinstance(base.func, ast.Name)
            and base.func.id == "super" and cls_key):
        hit = project.method(cls_key, attr, skip_self=True)
        if hit:
            edge(hit, "super")
        return out
    if isinstance(base, ast.Name):
        hit = project.lookup(mod, base.id)
        if hit and hit[0] == "module":
            target = project.modules[hit[1]]
            h2 = project.lookup(target, attr)
            if h2 and h2[0] == "func":
                edge((h2[1], h2[2]), "module")
            elif h2 and h2[0] == "class":
                init = _init_of(project, (h2[1], h2[2]))
                if init:
                    edge(init, "class")
            return out
        if hit and hit[0] == "class":
            m = project.method((hit[1], hit[2]), attr)
            if m:
                edge(m, "classattr")
                return out
        if project.is_external(mod, base.id):
            return out           # json.dumps, torch.cat: not repo code
    out.append((path, qual, line, attr, "attr"))
    return out


def callers_of(edges, target):
    """{(caller_file, caller): sorted call lines} for edges into target."""
    out = {}
    for e in edges:
        if (e.callee_file, e.callee) == target:
            out.setdefault((e.caller_file, e.caller), set()).add(e.line)
    return {k: sorted(v) for k, v in sorted(out.items())}


def disputes_for(sites, target_name, exclude_callers=()):
    """Unresolved sites whose name equals the target's simple name."""
    out = []
    for path, qual, line, name, kind in sites:
        if name != target_name or (path, qual) in exclude_callers:
            continue
        out.append(Dispute(path, qual, line, name, kind, DISPUTE_KINDS[kind]))
    return out


# --------------------------------------------------------------------------
# Runtime trace

def trace_callers(events, target_file, target_qual):
    """{(caller_file, caller_qual): sorted call lines} from T3 events.

    The trace records the caller's qualname and call line; its file is the
    file of the nearest open frame with that qualname (rebuilt from depths
    per phase and thread). Resume events are re-entries, not calls."""
    out = {}
    stacks = {}
    for e in events:
        key = (e["phase"], e["thread"])
        stack = stacks.setdefault(key, [])
        del stack[e["depth"]:]
        stack.append((e["file"], e["qual"]))
        if e["kind"] != "call":
            continue
        if (e["file"], e["qual"]) != (target_file, target_qual) or e["caller"] is None:
            continue
        caller_file = None
        for f, q in reversed(stack[:-1]):
            if q == e["caller"]:
                caller_file = f
                break
        if caller_file is None:
            # worker thread top frame: caller lives on the main thread's stack
            for (ph, th), st in stacks.items():
                if ph == e["phase"] and th == "main":
                    for f, q in reversed(st):
                        if q == e["caller"]:
                            caller_file = f
                            break
        lines = out.setdefault((caller_file, e["caller"]), set())
        if e["call_line"] is not None:
            lines.add(e["call_line"])
    return {k: sorted(v) for k, v in sorted(out.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))}


@dataclass(frozen=True)
class FlowRules:
    """The pre-filter that turns a trace phase into candidate hops.

    drop_classes: classes whose methods only log or collect metrics; a call
    to one is dropped with everything it calls.
    drop_funcs: plain functions (qualnames) that only log or print.
    """

    drop_classes: tuple = ()
    drop_funcs: tuple = ()

    def describe(self):
        logging = [c + ".*" for c in self.drop_classes] + list(self.drop_funcs)
        return [
            "keep: the subtree under the question's entry call(s), repo",
            "      calls only (the T3 filter: package source, no tests)",
            "drop with callees: logging and metrics:",
            "      " + (", ".join(logging) if logging else "none"),
            "drop with callees: folded calls (fold = one hop, callees",
            "      belong to another question)",
            "drop, keep callees: generator re-entries (resume events);",
            "      a generator counts once, where it was created",
            "drop, keep callees: properties, __post_init__, dunders",
            "      other than __init__ and __call__",
            "drop, keep callees: trivial functions (one statement: a",
            "      return with no call, or a get_/is_/has_ return)",
            "merge: a function called again counts once, at its first",
            "      call (layers, loop iterations, decode steps)",
        ]


SUBTREE_REASONS = {"logging", "fold", "depth"}


def drop_reason(func, rules):
    """Why a call is pre-filtered out, or None to keep it."""
    if func is None:
        return None
    if func.cls and func.cls.split(".")[-1] in rules.drop_classes:
        return "logging"
    if func.qual in rules.drop_funcs:
        return "logging"
    if func.is_property:
        return "property"
    if func.name == "__post_init__":
        return "dataclass"
    if func.is_dunder and func.name not in KEEP_DUNDERS:
        return "dunder"
    if func.trivial:
        return "trivial"
    return None


@dataclass(frozen=True)
class Hop:
    file: str
    qual: str
    line: int            # def line (first decorator line if decorated)
    calls: int           # times called in the kept subtree
    caller: str          # qual of the nearest kept caller at the first call
    thread: str
    cached: bool
    folded: bool


def entry_subtree(events, phase, entry_qual, entry_index=0):
    """Events of the entry_index-th call of entry_qual in the phase, with
    everything below it (same thread until depth returns; worker threads
    started inside it come along). If the entry is a generator, its later
    resumes by the consumer are part of the same call (the consumer's own
    resumes on the way back to it are skipped)."""
    ph = [e for e in events if e["phase"] == phase]
    starts = [i for i, e in enumerate(ph) if e["qual"] == entry_qual and e["kind"] == "call"]
    if len(starts) <= entry_index:
        raise ValueError(f"{entry_qual} call #{entry_index} not in phase {phase}")
    i0 = starts[entry_index]
    root = ph[i0]
    sub = [root]
    for e in ph[i0 + 1:]:
        if e["thread"] == root["thread"] and e["depth"] <= root["depth"]:
            if e["kind"] == "resume" and e["depth"] < root["depth"]:
                continue     # a consumer re-entered on the way back to the entry
            if (e["kind"] == "resume" and e["depth"] == root["depth"]
                    and (e["file"], e["qual"]) == (root["file"], root["qual"])):
                sub.append(e)
                continue
            break
        sub.append(e)
    return sub


def flow_hops(events, phase, entries, funcs, rules, fold=(), max_depth=None):
    """Candidate hops for one flow question.

    entries: [(qual, index)] calls the question starts at, in order (index =
    which call of that qual in the phase, 0 = first); funcs: {(file, qual):
    Func}; fold: quals kept as one hop with their callees dropped;
    max_depth: drop calls deeper than this below the entry (None = all).
    Returns (hops, dropped, raw) where dropped counts calls by reason and
    raw is the number of call events in the subtree(s).

    A resume re-enters a suspended generator: it is not a call, but the
    generator is back on the stack, so a folded or dropped generator's
    later work stays dropped and a kept one's later callees get it as
    their caller."""
    dropped, hops, order, raw = {}, {}, [], 0
    fold = set(fold)

    def count(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for entry_qual, entry_index in entries:
        sub = entry_subtree(events, phase, entry_qual, entry_index)
        root, base = sub[0], sub[0]["depth"]
        cut = {}                 # thread -> (depth, reason) of a dropped subtree
        kept_stack = {}          # thread -> [(depth, qual)] of kept frames
        for e in sub:
            th, d = e["thread"], e["depth"]
            is_call = e["kind"] == "call"
            raw += is_call
            if cut.get(th) and d <= cut[th][0]:
                cut[th] = None
            # a worker thread runs while the thread that started it waits:
            # if that thread is inside a dropped subtree, so is the worker
            if th != root["thread"] and cut.get(root["thread"]):
                if is_call:
                    count("under " + cut[root["thread"]][1])
                continue
            stack = kept_stack.setdefault(th, [])
            while stack and stack[-1][0] >= d:
                stack.pop()
            if cut.get(th):
                if is_call:
                    count("under " + cut[th][1])
                continue
            is_root = (e["file"], e["qual"]) == (root["file"], root["qual"]) and d == base
            f = funcs.get((e["file"], e["qual"]))
            reason = None if is_root else drop_reason(f, rules)
            if reason is None and max_depth is not None and d - base > max_depth:
                reason = "depth"
            folded = e["qual"] in fold and not is_root
            if not is_call:
                count("resume")
                if reason in SUBTREE_REASONS or folded:
                    cut[th] = (d, "fold" if folded else reason)
                elif reason is None:
                    stack.append((d, e["qual"]))
                continue
            if reason in SUBTREE_REASONS:
                count(reason)
                cut[th] = (d, reason)
                continue
            if reason:
                count(reason)
                continue
            caller = stack[-1][1] if stack else (
                _main_caller(kept_stack, th) if th != "main" else "")
            stack.append((d, e["qual"]))
            k = (e["file"], e["qual"])
            if k in hops:
                h = hops[k]
                hops[k] = Hop(h.file, h.qual, h.line, h.calls + 1, h.caller, h.thread,
                              h.cached, h.folded)
                count("repeat")
            else:
                hops[k] = Hop(e["file"], e["qual"], e["line"], 1, caller, th,
                              bool(f and f.is_cached), folded)
                order.append(k)
            if folded:
                cut[th] = (d, "fold")
    return [hops[k] for k in order], dict(sorted(dropped.items())), raw


def _main_caller(kept_stack, thread):
    main = kept_stack.get("main") or []
    return main[-1][1] if main else ""


# --------------------------------------------------------------------------
# Blame

def parse_blame(porcelain):
    """git blame --line-porcelain output -> {final line number: committer
    time (unix seconds)}."""
    out = {}
    cur_line = None
    for raw in porcelain.splitlines():
        if raw.startswith("\t"):
            continue
        parts = raw.split(" ")
        if len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]) \
                and len(parts) >= 3:
            cur_line = int(parts[2])
        elif parts[0] == "committer-time" and cur_line is not None:
            out[cur_line] = int(parts[1])
    return out


def tag_lines(times, lines, cutoff_ts, nonblank=None):
    """Share of key lines last changed after the cutoff.

    times: {line: unix time}; lines: the key's line numbers; nonblank: the
    set of lines that are not blank (blank lines carry no code). Returns
    (after_count, total, tag) with tag 'after' when at least half the
    counted lines are after the cutoff, else 'before'."""
    counted = [n for n in lines if nonblank is None or n in nonblank]
    after = sum(1 for n in counted if times.get(n, 0) > cutoff_ts)
    total = len(counted)
    tag = "after" if total and 2 * after >= total else "before"
    return after, total, tag


# --------------------------------------------------------------------------
# Leakage

def _word_re(word):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", re.I)


def leaks(text, symbols, files):
    """Key symbol names or file names that appear verbatim in the text
    (case-insensitive, whole identifier). symbols: simple names and class
    names; files: repo paths (checked as base name and as stem)."""
    found = []
    for s in sorted(set(symbols)):
        if s and _word_re(s).search(text):
            found.append(s)
    for p in sorted(set(files)):
        base = p.rsplit("/", 1)[-1]
        stem = base[:-3] if base.endswith(".py") else base
        for w in (base, stem):
            if w != "__init__" and _word_re(w).search(text):
                found.append(w)
                break
    return found


def loose_leaks(text, symbols):
    """Snake/Camel names whose every word (3+ letters) appears in the text,
    e.g. sample_next_token for 'sample the next token'. Informational."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    out = []
    for s in sorted(set(symbols)):
        parts = [p.lower() for p in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", s)]
        parts = [p for p in parts if len(p) >= 3]
        if len(parts) >= 2 and all(p in words for p in parts):
            out.append(s)
    return out

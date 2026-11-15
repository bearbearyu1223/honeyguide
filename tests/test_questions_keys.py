"""Answer-key helpers: AST function index, call graph, leak checks."""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "questions"))
from keys import (  # noqa: E402
    Project, call_graph, callers_of, disputes_for, function_index, leaks,
    loose_leaks, module_info, module_name,
)


def src(s):
    return textwrap.dedent(s).lstrip("\n")


# --------------------------------------------------------------------------
# Function index (locate keys)

INDEX_SRC = src('''
    import functools

    def plain(x):
        y = x + 1
        return y

    @functools.lru_cache(maxsize=None)
    def cached(x):
        return compute(x)

    class Box:
        """A box."""

        def __init__(self, v):
            self.v = v

        @property
        def value(self):
            return self.v

        def get_size(self):
            return len(self.v)

        def __repr__(self):
            return "Box"

        def outer(self):
            def inner():
                return 1
            return inner()
''')


def test_index_qualnames_and_ranges():
    fs = {f.qual: f for f in function_index(INDEX_SRC, "pkg/m.py")}
    assert list(fs) == ["plain", "cached", "Box.__init__", "Box.value", "Box.get_size",
                        "Box.__repr__", "Box.outer", "Box.outer.<locals>.inner"]
    assert (fs["plain"].start, fs["plain"].end) == (3, 5)
    # decorated: the range starts at the decorator, like co_firstlineno
    assert fs["cached"].start == 7 and fs["cached"].def_line == 8
    assert fs["Box.value"].cls == "Box" and fs["plain"].cls is None
    assert fs["Box.outer.<locals>.inner"].cls is None


def test_index_flags():
    fs = {f.qual: f for f in function_index(INDEX_SRC, "pkg/m.py")}
    assert fs["cached"].is_cached and not fs["plain"].is_cached
    assert fs["Box.value"].is_property
    assert fs["Box.__repr__"].is_dunder and fs["Box.__init__"].is_dunder
    # trivial: a return with no call, or a get_ one-liner even with a call
    assert fs["Box.value"].trivial
    assert fs["Box.get_size"].trivial
    assert fs["Box.outer.<locals>.inner"].trivial
    assert not fs["plain"].trivial          # two statements
    assert not fs["cached"].trivial         # returns a call, not get_/is_/has_
    assert not fs["Box.__init__"].trivial   # an assignment, not a return


def test_module_name():
    assert module_name("src/smolagents/agents.py", ("src",)) == "smolagents.agents"
    assert module_name("nanochat/gpt.py", ("",)) == "nanochat.gpt"
    assert module_name("pkg/__init__.py", ("",)) == "pkg"


# --------------------------------------------------------------------------
# Call graph (callers keys and disputes)

FILES = {
    "pkg/__init__.py": "",
    "pkg/util.py": src('''
        import json

        def helper(x):
            return x

        def uses_json(d):
            return json.dumps(d)

        def target(x):
            return helper(x)
    '''),
    "pkg/base.py": src('''
        from .util import target, helper
        from . import util

        class Base:
            def __init__(self):
                self.setup()

            def setup(self):
                pass

            def run(self):
                self.step()
                return target(1)

            def step(self):
                raise NotImplementedError

            @classmethod
            def make(cls):
                return cls.setup_cls()

            @staticmethod
            def setup_cls():
                return util.helper(2)

        class Child(Base):
            def __init__(self):
                super().__init__()

            def step(self):
                def nested():
                    return self.setup()
                return nested()
    '''),
    "pkg/main.py": src('''
        from pkg.base import Child, Base
        from pkg import util

        def main(obj):
            c = Child()
            Base.make()
            obj.target(3)
            fn = getattr(util, "target")
            callbacks = [util.target]
            return util.target(4)

        main(None)
    '''),
}


def graph():
    mods = [module_info(s, p, ("",)) for p, s in FILES.items()]
    project = Project(mods)
    return call_graph(project)


def callers(edges, path, qual):
    return {k: v for k, v in callers_of(edges, (path, qual)).items()}


def test_plain_names_and_imports():
    edges, _ = graph()
    assert callers(edges, "pkg/util.py", "helper") == {
        ("pkg/base.py", "Base.setup_cls"): [24],   # util.helper via module
        ("pkg/util.py", "target"): [10],           # same module
    }
    got = callers(edges, "pkg/util.py", "target")
    assert got[("pkg/base.py", "Base.run")] == [13]       # from .util import target
    assert got[("pkg/main.py", "main")] == [10]           # util.target(4)


def test_classes_self_super_override():
    edges, _ = graph()
    via = {(e.caller, e.callee): e.via for e in edges}
    assert via[("main", "Child.__init__")] == "class"
    assert via[("Child.__init__", "Base.__init__")] == "super"
    assert via[("Base.__init__", "Base.setup")] == "self"
    assert via[("main", "Base.make")] == "classattr"
    assert via[("Base.make", "Base.setup_cls")] == "self"           # cls.m()
    # self.step() in Base reaches Child.step at runtime: class hierarchy
    assert via[("Base.run", "Base.step")] == "self"
    assert via[("Base.run", "Child.step")] == "override"
    # a function nested in a method sees the method's self
    assert via[("Child.step.<locals>.nested", "Base.setup")] == "self"
    assert via[("Child.step", "Child.step.<locals>.nested")] == "name"
    # module-level code is a caller too
    assert via[("<module>", "main")] == "name"


def test_disputes_and_external_modules():
    edges, sites = graph()
    ds = disputes_for(sites, "target")
    kinds = sorted((d.caller, d.kind, d.line) for d in ds)
    assert ("main", "attr", 7) in kinds          # obj.target(3): type unknown
    assert ("main", "getattr", 8) in kinds       # getattr(util, "target")
    assert ("main", "reference", 9) in kinds     # [util.target], not called
    # json.dumps is an attribute of an external module: never a dispute
    assert not disputes_for(sites, "dumps")
    # resolved calls are edges, not disputes
    assert ("main", "attr", 10) not in kinds


# --------------------------------------------------------------------------
# Leakage

def test_leaks_whole_identifier_case_insensitive():
    text = "Where is the KV cache prefill done, in the engine?"
    assert leaks(text, ["prefill", "KVCache"], ["nanochat/engine.py"]) == ["prefill", "engine"]
    # substrings of longer words do not count
    assert leaks("normalization of rows", ["norm"], []) == []
    assert leaks("calls norm() twice", ["norm"], []) == ["norm"]
    assert leaks("text", [], ["pkg/__init__.py"]) == []


def test_loose_leaks():
    assert loose_leaks("sample the next token", ["sample_next_token"]) == ["sample_next_token"]
    assert loose_leaks("draw the next token", ["sample_next_token"]) == []
    assert loose_leaks("the safe serializer", ["SafeSerializer"]) == ["SafeSerializer"]
    # one-word names never loose-leak (that is the strict check's job)
    assert loose_leaks("norm", ["norm"]) == []

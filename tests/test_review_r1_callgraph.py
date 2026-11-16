"""Review round 1 (T8): call sites the AST call graph misses with no dispute, or resolves wrongly."""

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "questions"))
from keys import Project, call_graph, callers_of, disputes_for, module_info  # noqa: E402


def graph(files):
    mods = [module_info(textwrap.dedent(s).lstrip("\n"), p) for p, s in files.items()]
    return call_graph(Project(mods))


def test_sibling_closure_call_is_an_edge_or_a_dispute():
    """outer.<locals>.a calls its sibling outer.<locals>.b by name. `nested`
    only holds the calling scope's own children, so b() is looked up at
    module level, misses, and leaves neither an edge nor a site."""
    edges, sites = graph({"m.py": '''
        def outer():
            def a():
                return b()
            def b():
                return 1
            return a()
    '''})
    target = ("m.py", "outer.<locals>.b")
    found = callers_of(edges, target)
    assert ("m.py", "outer.<locals>.a") in found or disputes_for(sites, "b")


def test_def_inside_if_block_in_function():
    """A nested def under an `if` is not in `nested` (only direct body
    children are), so the call resolves to nothing, silently."""
    edges, sites = graph({"m.py": '''
        def f(flag):
            if flag:
                def g():
                    return 1
            else:
                def g():
                    return 2
            return g()
    '''})
    assert callers_of(edges, ("m.py", "f.<locals>.g")) or disputes_for(sites, "g")


def test_function_local_import_does_not_leak_or_lose():
    """f imports helper from b locally; a module-level helper also exists.
    module_info flattens all imports, and lookup checks module funcs first,
    so f's call is keyed to a.helper and b.helper loses the caller."""
    edges, _ = graph({
        "a.py": '''
            def helper():
                return 0

            def f():
                from b import helper
                return helper()
        ''',
        "b.py": '''
            def helper():
                return 1
        ''',
    })
    assert ("a.py", "f") in callers_of(edges, ("b.py", "helper"))
    assert ("a.py", "f") not in callers_of(edges, ("a.py", "helper"))


def test_module_level_def_inside_if_is_a_function():
    """A def under a module-level `if` (or try) binds a module name too."""
    edges, _ = graph({"m.py": '''
        import os
        if os.environ.get("X"):
            def helper():
                return 1
        else:
            def helper():
                return 2

        def f():
            return helper()
    '''})
    assert ("m.py", "f") in callers_of(edges, ("m.py", "helper"))


def test_local_import_of_an_external_module_is_still_external():
    """With local imports kept local, `import json` inside f must still make
    json.dumps an external call, not an unresolved attr site."""
    _, sites = graph({"m.py": '''
        def f(x):
            import json
            return json.dumps(x)
    '''})
    assert not disputes_for(sites, "dumps")


def test_method_of_a_class_in_a_function_is_not_a_local_name():
    """A method defined in a class inside f is not a name f's body can call."""
    edges, _ = graph({"m.py": '''
        def go():
            return 0

        def f():
            class C:
                def go(self):
                    return 1
            return go()
    '''})
    assert ("m.py", "f") in callers_of(edges, ("m.py", "go"))
    assert not callers_of(edges, ("m.py", "f.<locals>.C.go"))

"""The trace filter: which files count as repo-owned, and qualified names."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "trace"))
from tracer import FilterRules, is_synthetic, path_kept, qualnames_from_source  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "repo" / "pkg"
    for rel in ["mod.py", "sub/inner.py", "tests/test_x.py", "sub/test/t.py",
                ".venv/lib/site-packages/dep.py", "data.txt"]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n")
    sibling = tmp_path / "repo" / "pkg2" / "mod.py"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("x = 1\n")
    outside = tmp_path / "repo" / "scripts" / "run.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("x = 1\n")
    return tmp_path, FilterRules(roots=(str(root),))


def test_keeps_package_source(tree):
    tmp, rules = tree
    assert path_kept(str(tmp / "repo/pkg/mod.py"), rules)
    assert path_kept(str(tmp / "repo/pkg/sub/inner.py"), rules)


@pytest.mark.parametrize("rel", [
    "repo/pkg/tests/test_x.py",                      # tests directory
    "repo/pkg/sub/test/t.py",                        # nested test directory
    "repo/pkg/.venv/lib/site-packages/dep.py",       # venv inside the root
    "repo/pkg/data.txt",                             # not Python
    "repo/pkg2/mod.py",                              # sibling with the root as prefix
    "repo/scripts/run.py",                           # repo code outside the package
])
def test_drops(tree, rel):
    tmp, rules = tree
    assert not path_kept(str(tmp / rel), rules)


@pytest.mark.parametrize("name", ["<string>", "<frozen importlib._bootstrap>", ""])
def test_drops_synthetic_filenames(tree, name):
    _, rules = tree
    assert not path_kept(name, rules)


def test_symlinked_path_resolves_into_root(tree):
    tmp, rules = tree
    link = tmp / "link"
    os.symlink(tmp / "repo" / "pkg", link)
    assert path_kept(str(link / "mod.py"), rules)


def test_file_named_like_excluded_dir_is_kept(tree):
    # only directories between the root and the file are checked
    tmp, rules = tree
    p = tmp / "repo" / "pkg" / "tests.py"
    p.write_text("x = 1\n")
    assert path_kept(str(p), rules)


@pytest.mark.parametrize("name,expected", [
    ("<lambda>", True), ("<listcomp>", True), ("<genexpr>", True),
    ("<module>", True), ("forward", False), ("__init__", False),
])
def test_is_synthetic(name, expected):
    assert is_synthetic(name) is expected


def test_class_body_is_synthetic():
    code = compile("class K:\n    def f(self):\n        pass\n", "x.py", "exec")
    (body,) = [c for c in code.co_consts if hasattr(c, "co_code")]
    (method,) = [c for c in body.co_consts if hasattr(c, "co_code")]
    assert is_synthetic(body.co_name, body.co_flags)
    assert not is_synthetic(method.co_name, method.co_flags)


SOURCE = '''\
import functools

def top():
    def inner():
        return 1
    return inner

class A:
    def m(self):
        pass

    @staticmethod
    @functools.lru_cache(maxsize=2)
    def cached(x):
        return x

    class B:
        async def am(self):
            def deep():
                pass
            return deep

@functools.wraps(top)
def wrapped():
    pass
'''


def test_qualnames_from_source():
    q = qualnames_from_source(SOURCE)
    assert q == {
        3: "top", 4: "top.<locals>.inner", 9: "A.m",
        12: "A.cached",                 # first decorator line, not the def
        18: "A.B.am", 19: "A.B.am.<locals>.deep", 23: "wrapped",
    }


def _function_codes(code):
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield const
            yield from _function_codes(const)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="co_qualname is 3.11+")
def test_qualnames_match_co_qualname():
    table = qualnames_from_source(SOURCE)
    codes = [c for c in _function_codes(compile(SOURCE, "x.py", "exec"))
             if not is_synthetic(c.co_name, c.co_flags)]
    assert len(codes) == len(table)
    for c in codes:
        assert table[c.co_firstlineno] == c.co_qualname

"""Read a target repo at its pinned commit (git show / ls-tree / blame).

Never reads the working tree, so the key is the same whatever is checked
out. Standard library only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keys import function_index, module_info, parse_blame

TARGETS = Path.home() / "Documents" / "GitHub" / "honeyguide-targets"

REPOS = {
    "nanochat": {
        "url": "https://github.com/karpathy/nanochat",
        "commit": "92d63d4e8bb4df75c3b71618f31ddde2378b2bcd",
        "package_roots": ("",),          # modules are nanochat.*, scripts.*, tasks.*
        "trace_root": "nanochat/",       # what the T3 trace kept
    },
    "smolagents": {
        "url": "https://github.com/huggingface/smolagents",
        "commit": "e1249d373d58db6abc73882ee394f6bb3854c89f",
        "package_roots": ("src",),
        "trace_root": "src/smolagents/",
    },
}
# Code in scope for keys: every tracked .py outside these top-level dirs
EXCLUDE_TOP = ("tests", "test", "examples", "docs")


def git(clone, *args):
    return subprocess.run(["git", "-C", str(clone), *args], check=True,
                          capture_output=True, text=True).stdout


def blame_file(clone, commit, path, first_parent=True):
    """{line: committer time} at commit. -w ignores whitespace changes; -M
    and -C keep moved or copied lines' original dates; first_parent dates
    lines merged from a branch by the merge onto the default branch."""
    args = ["blame", "--line-porcelain", "-w", "-M", "-C"]
    if first_parent:
        args.append("--first-parent")
    return parse_blame(git(clone, *args, commit, "--", path))


class Repo:
    def __init__(self, name, clone=None):
        cfg = REPOS[name]
        self.name = name
        self.clone = Path(clone) if clone else TARGETS / name
        self.commit = cfg["commit"]
        self.url = cfg["url"]
        self.package_roots = cfg["package_roots"]
        self.trace_root = cfg["trace_root"]
        self._memo = {}
        got = git(self.clone, "rev-parse", self.commit + "^{commit}").strip()
        if got != self.commit:
            raise SystemExit(f"{name}: pinned commit not found ({got})")

    def _cached(self, key, make):
        if key not in self._memo:
            self._memo[key] = make()
        return self._memo[key]

    def commit_date(self):
        return git(self.clone, "show", "-s", "--format=%cI", self.commit).strip()

    def py_files(self):
        def make():
            out = git(self.clone, "ls-tree", "-r", "--name-only", self.commit).splitlines()
            return tuple(p for p in sorted(out)
                         if p.endswith(".py") and p.split("/")[0] not in EXCLUDE_TOP)
        return self._cached("files", make)

    def source(self, path):
        return self._cached(("src", path),
                            lambda: git(self.clone, "show", f"{self.commit}:{path}"))

    def functions(self):
        """{(file, qual): Func} for every in-scope def."""
        def make():
            out = {}
            for p in self.py_files():
                for f in function_index(self.source(p), p):
                    out[f.key] = f
            return out
        return self._cached("funcs", make)

    def modules(self):
        return self._cached("modules", lambda: tuple(
            module_info(self.source(p), p, self.package_roots) for p in self.py_files()))

    def blame(self, path, first_parent=True):
        return self._cached(("blame", path, first_parent),
                            lambda: blame_file(self.clone, self.commit, path, first_parent))

    def nonblank(self, path):
        return {i for i, line in enumerate(self.source(path).splitlines(), 1)
                if line.strip()}

"""Python lines at a commit: every .py file in the commit's tree, lines counted as ``wc -l`` counts them.

One method for every capture that prints a repo's size (eval/refresh/capture.py, eval/cutoff/june_check.py).
Reads the commit through git (ls-tree, cat-file), never the working tree, so what is checked out does not
matter. Standard library only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

METHOD = "every .py file in the commit's tree (git ls-tree -r), lines counted as wc -l counts them"
FILE_MODES = ("100644", "100755")   # regular files; symlinks (120000) and submodules (160000) are not code


def parse_ls_tree(text, keep=None):
    """[(blob sha, path)] for the regular .py files in ``git ls-tree -r -z`` output, optionally only paths for
    which ``keep(path)`` is true."""
    out = []
    for entry in text.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind == "blob" and mode in FILE_MODES and path.endswith(".py") and (keep is None or keep(path)):
            out.append((sha, path))
    return out


def count_lines(data):
    """Newlines in ``data`` (bytes), which is what wc -l prints: a last line with no newline is not counted."""
    return data.count(b"\n")


def parse_batch(data):
    """The contents (bytes) of each object in ``git cat-file --batch`` output, in order."""
    out, i = [], 0
    while i < len(data):
        nl = data.index(b"\n", i)
        header = data[i:nl].split()
        if len(header) < 3 or header[1] == b"missing":
            raise ValueError(f"git cat-file: {data[i:nl].decode(errors='replace')}")
        size = int(header[2])
        out.append(data[nl + 1:nl + 1 + size])
        i = nl + 1 + size + 1          # the content, then one newline
    return out


def py_lines(checkout, commit, keep=None):
    """(files, lines) of Python at ``commit`` in the git checkout, or None when git cannot read it."""
    checkout = Path(checkout)
    if not commit or not (checkout / ".git").exists():
        return None
    try:
        tree = subprocess.run(["git", "-C", str(checkout), "ls-tree", "-r", "-z", commit], capture_output=True,
                              timeout=120, check=True).stdout.decode()
        blobs = parse_ls_tree(tree, keep)
        if not blobs:
            return 0, 0
        batch = subprocess.run(["git", "-C", str(checkout), "cat-file", "--batch"], capture_output=True,
                               input="".join(f"{sha}\n" for sha, _ in blobs).encode(), timeout=120,
                               check=True).stdout
        contents = parse_batch(batch)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if len(contents) != len(blobs):
        return None
    return len(blobs), sum(count_lines(c) for c in contents)

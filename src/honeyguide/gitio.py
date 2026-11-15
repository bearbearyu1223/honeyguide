"""Read-only git access. Every read of repository content goes through here.

Files are read at a commit (``git show <sha>:<path>``), never from the working tree, so a resolved line
range always refers to a fixed snapshot.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: Path | str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def split_lines(text: str) -> list[str]:
    """Lines as GitHub and editors number them: split on newline only.

    ``str.splitlines`` also splits on form feeds and Unicode separators, which would shift line numbers.
    """
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def decode_text(data: bytes) -> list[str] | None:
    """The lines of a file's bytes, or None if it looks binary."""
    if b"\x00" in data[:8192]:
        return None
    return split_lines(data.decode("utf-8", errors="replace"))


@dataclass
class Repo:
    """One checkout, with a cache of file contents by (commit, path)."""

    root: Path
    _files: dict[tuple[str, str], list[str] | None] = field(default_factory=dict, repr=False)

    @classmethod
    def open(cls, path: Path | str) -> "Repo":
        top = run_git(path, "rev-parse", "--show-toplevel").strip()
        return cls(Path(top))

    def git(self, *args: str, check: bool = True) -> str:
        return run_git(self.root, *args, check=check)

    def rev(self, rev: str = "HEAD") -> str:
        """The full sha of ``rev`` as a commit."""
        return self.git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()

    def lines_at(self, commit: str, path: str) -> list[str] | None:
        """The file's lines at ``commit``; None if absent there or binary."""
        key = (commit, path)
        if key not in self._files:
            proc = subprocess.run(
                ["git", "-C", str(self.root), "show", f"{commit}:{path}"], capture_output=True,
            )
            self._files[key] = decode_text(proc.stdout) if proc.returncode == 0 else None
        return self._files[key]

    def ls_files(self, commit: str) -> list[str]:
        out = self.git("ls-tree", "-r", "-z", "--name-only", commit)
        return [p for p in out.split("\0") if p]

    def diff_name_status(self, a: str, b: str) -> list[tuple[str, str, str | None]]:
        """``(status letter, old path, new path or None)`` for each changed file, renames followed."""
        out = self.git("diff", "--name-status", "-z", "-M", a, b)
        parts = out.split("\0")
        changes: list[tuple[str, str, str | None]] = []
        i = 0
        while i < len(parts) and parts[i]:
            status = parts[i]
            letter = status[0]
            if letter in "RC":
                changes.append((letter, parts[i + 1], parts[i + 2]))
                i += 3
            else:
                changes.append((letter, parts[i + 1], None))
                i += 2
        return changes

    def dirty(self) -> dict[str, int]:
        """Counts of tracked changes and untracked files in the working tree."""
        entries = self.git("status", "--porcelain", "-z").split("\0")
        tracked = untracked = 0
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            if entry.startswith("??"):
                untracked += 1
            elif entry[:2].strip():
                tracked += 1
                if entry[0] in "RC" or entry[1] in "RC":
                    i += 1  # a rename's original path follows as its own entry
        return {"tracked": tracked, "untracked": untracked}

    def remotes(self) -> dict[str, str]:
        names = self.git("remote").split()
        return {n: self.git("remote", "get-url", n).strip() for n in names}

    def root_commits(self) -> list[str]:
        return self.git("rev-list", "--max-parents=0", "HEAD").split()

    def first_parent_root(self) -> str:
        roots = self.git("rev-list", "--first-parent", "--max-parents=0", "HEAD").split()
        if not roots:
            raise GitError("repository has no commits")
        return roots[0]

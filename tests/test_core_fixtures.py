"""Throwaway git repositories for the core tests (helpers, plus a check that they work)."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_CONFIG = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
              "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main"]


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *GIT_CONFIG, "-C", str(self.root), *args],
                              capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"git {args}: {proc.stderr}")
        return proc.stdout

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message: str = "change") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


def test_helper_makes_commits(tmp_path):
    repo = GitRepo(tmp_path / "r")
    repo.write("a.txt", "one\n")
    first = repo.commit()
    repo.write("a.txt", "two\n")
    second = repo.commit()
    assert len(first) == 40 and first != second

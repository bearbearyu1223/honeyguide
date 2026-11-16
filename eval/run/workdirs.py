"""Working directories for eval runs: a fresh copy of the pinned target, or an empty dir for no-access.

The copy comes from `git archive <pin>` (tracked files at the pinned commit, no .git, whatever is checked out),
then the repo's own agent files are removed (config `remove`). Afterwards no agent file may remain anywhere in
the copy; if one does, the copy is refused rather than used. Maps, outlines, questions and keys are never written
into a working dir: they live in the run archive, and the answering prompt carries the map or outline text.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

# Files Claude Code (or another agent tool) could pick up from a working dir. None may remain after removal.
AGENT_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude", ".mcp.json")


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"unsafe path in archive: {m.name}")
        if m.issym() or m.islnk():
            continue   # links are skipped: nothing in a working dir may point outside it
        yield m


def archive_tree(clone: Path, commit: str, dest: Path) -> int:
    """Extract the tracked files at commit into dest (created, must not exist). Returns the file count."""
    dest.mkdir(parents=True)
    data = subprocess.run(["git", "-C", str(clone), "archive", "--format=tar", commit],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = list(_safe_members(tar))
        tar.extractall(dest, members=members, filter="data")
    return sum(1 for m in members if m.isfile())


def remove_agent_files(dest: Path, remove: list[str]) -> list[str]:
    """Delete the configured agent files (repo-root paths). Returns what was removed."""
    gone = []
    for rel in remove:
        p = dest / rel
        if p.is_dir():
            shutil.rmtree(p)
            gone.append(rel)
        elif p.exists():
            p.unlink()
            gone.append(rel)
    return gone


def leftover_agent_files(dest: Path) -> list[str]:
    """Agent files anywhere in the tree (should be empty after removal)."""
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.name in AGENT_NAMES)


def make_repo_workdir(clone: Path, commit: str, remove: list[str], dest: Path) -> dict:
    files = archive_tree(clone, commit, dest)
    gone = remove_agent_files(dest, remove)
    left = leftover_agent_files(dest)
    if left:
        shutil.rmtree(dest)
        raise RuntimeError(f"agent files remain in the working dir copy: {', '.join(left)}; add them to remove")
    return {"files": files, "removed": gone}


def make_empty_workdir(dest: Path) -> dict:
    dest.mkdir(parents=True)
    return {"files": 0, "removed": []}

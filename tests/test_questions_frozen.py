"""The frozen set: generate.py is deterministic, and the committed files
still match MANIFEST.txt (fails if anything under eval/questions/ changed
after the freeze)."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QDIR = ROOT / "eval" / "questions"
GEN = QDIR / "generate.py"
TARGETS = Path.home() / "Documents" / "GitHub" / "honeyguide-targets"


def run(repo, out_dir, hashseed):
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    res = subprocess.run([sys.executable, str(GEN), repo, "--cutoff", "2026-06-30",
                          "--out-dir", str(out_dir)],
                         env=env, capture_output=True, text=True, check=True)
    files = {p.name: p.read_bytes() for p in sorted(out_dir.iterdir())}
    return res.stdout, files


@pytest.mark.parametrize("repo", ["nanochat", "waku-agent"])
def test_two_runs_byte_identical(repo, tmp_path):
    if not (TARGETS / repo).exists():
        pytest.skip(f"target clone {repo} not present")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    out_a, files_a = run(repo, a, "0")
    out_b, files_b = run(repo, b, "1")
    assert out_a == out_b
    assert files_a == files_b
    assert set(files_a) == {f"{repo}.json", f"{repo}_flow_hops_to_mark.md",
                            f"{repo}_callers_disputes.md", "MANIFEST.txt"}
    # the frozen copy in the repo is what this code produces
    for name in (f"{repo}.json", f"{repo}_flow_hops_to_mark.md",
                 f"{repo}_callers_disputes.md"):
        assert (QDIR / name).read_bytes() == files_a[name], name


def test_manifest_matches_files():
    lines = [ln for ln in (QDIR / "MANIFEST.txt").read_text().splitlines()
             if ln and not ln.startswith("#")]
    listed = {}
    for ln in lines:
        digest, name = ln.split("  ", 1)
        listed[name] = digest
    on_disk = {p.relative_to(QDIR).as_posix() for p in QDIR.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.name != "MANIFEST.txt"}
    assert set(listed) == on_disk
    for name, digest in listed.items():
        assert hashlib.sha256((QDIR / name).read_bytes()).hexdigest() == digest, name

"""Print how Honeyguide's own history was written: commits up to a frozen commit, and how many carry a Claude
co-author trailer.

    uv run python eval/runs/commits.py > outputs/commits.txt

Reads this repo's history through git (rev-list, log) from the pinned commit FROZEN, never HEAD, so later commits
do not change the output. A commit counts as Claude co-authored when the trailer block (the message's last
paragraph) has a ``Co-Authored-By:`` line (key matched case-insensitively) whose value starts with ``Claude``
(any model). Dates are author dates. Standard library only; no network.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN = "f1b52e9"
WIDTH = 74
TRAILER = re.compile(r"^co-authored-by:\s*claude\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Pure helpers (tested in tests/test_eval_commits.py)

def trailer_block(message):
    """The message's last paragraph (where git trailers live), as a list of lines; [] for a one-paragraph
    message, which has a subject and no trailer block."""
    paras = [p for p in re.split(r"\n\s*\n", message.strip()) if p.strip()]
    return paras[-1].splitlines() if len(paras) > 1 else []


def has_claude_trailer(message):
    """True when the trailer block has a Co-Authored-By line naming Claude (any model, key in any case)."""
    return any(TRAILER.match(line.strip()) for line in trailer_block(message))


def parse_log(text):
    """[(sha, author date, message)] from ``git log -z --format=%H%n%aI%n%B`` output."""
    out = []
    for entry in text.split("\0"):
        entry = entry.lstrip("\n")
        if not entry:
            continue
        sha, date, message = (entry.split("\n", 2) + [""])[:3]
        out.append((sha, date, message))
    return out


def summarize(commits):
    """(count, with trailer, first commit (sha, date)) for commits in git log order (newest first)."""
    tagged = sum(has_claude_trailer(m) for _, _, m in commits)
    first = commits[-1][:2] if commits else (None, None)
    return len(commits), tagged, first


# --------------------------------------------------------------------------

def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def log(commit, first_parent=False):
    args = ["log", "-z", "--format=%H%n%aI%n%B"] + (["--first-parent"] if first_parent else []) + [commit]
    return parse_log(git(*args))


def render(commit):
    full = git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
    every = log(full)
    first_parent = log(full, first_parent=True)
    n, tagged, (first_sha, first_date) = summarize(every)
    rows = [(f"commits reachable from {commit}", n)]
    if len(first_parent) != n:
        fp_n, fp_tagged, _ = summarize(first_parent)
        rows.append(("commits on the first-parent line", fp_n))
    rows.append(("with a Claude co-author trailer", f"{tagged} of {n}"))
    if len(first_parent) != n:
        rows.append(("first-parent with the trailer", f"{fp_tagged} of {fp_n}"))
    rows += [("first commit", f"{first_sha[:7]}, {first_date}"), (f"{commit} itself", every[0][1])]
    lines = ["Honeyguide commits: who wrote them", "=" * WIDTH,
             f"  frozen at   {commit} ({full})",
             "  rule        a 'Co-Authored-By: Claude' line in the trailer block",
             "              (key case-insensitive, any Claude model)",
             ""]
    lines += [f"  {label:<36} {value}" for label, value in rows]
    return "\n".join(line.rstrip() for line in lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", default=FROZEN, help="the commit to count back from (default: the frozen one)")
    args = ap.parse_args(argv)
    sys.stdout.write(render(args.commit))


if __name__ == "__main__":
    main()

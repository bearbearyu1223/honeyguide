"""Count the eval questions' key lines last changed in June 2026 (the cutoff month).

    uv run python eval/cutoff/june_check.py > outputs/june_check.txt 2> outputs/june_check.err

The models' training cutoff is given only as a month, June 2026, so a key line
changed during June could fall on either side of it. This prints, per repo,
how the key lines the cutoff tags count split into before June 2026, June 2026
and after 2026-06-30. It also prints each repo's Python at the pinned commit:
every .py file, and the .py files in the questions' key scope (eval/common/
pylines.py, the method the refresh capture uses too).

Read only. The questions come from the frozen eval/questions/<repo>.json, the
key lines from generate.py's key_ranges (the one builder the tags use), and the
dates from the same git blame of the pinned commit in
~/Documents/GitHub/honeyguide-targets/<repo>. It writes nothing there and
changes nothing in eval/questions/ (whose MANIFEST lists every file in it, which
is why this script lives here). Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import textwrap
from pathlib import Path

QUESTIONS = Path(__file__).resolve().parents[1] / "questions"
sys.path.insert(0, str(QUESTIONS))
sys.path.insert(0, str(QUESTIONS.parent / "common"))

from generate import key_ranges  # noqa: E402
from pylines import METHOD as PY_LINES_METHOD  # noqa: E402
from pylines import py_lines  # noqa: E402
from repo import Repo, in_scope  # noqa: E402

WIDTH = 74
REPOS = ("nanochat", "waku-agent")
MONTH = "2026-06"


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Pure helpers (tested in tests/test_june_check.py)

def month_bounds(month):
    """'YYYY-MM' -> (first second, last second) of that month in UTC, as unix times, inclusive. The last second
    is 23:59:59 of the last day, the same day boundary as generate.py's cutoff_ts."""
    y, m = (int(x) for x in month.split("-"))
    start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    nxt = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return start.timestamp(), nxt.timestamp() - 1


def split_lines(times, lines, nonblank, lo, hi):
    """Counted key lines (non-blank, as tag_lines counts them) by when they last changed:
    {'before': t < lo, 'in': lo <= t <= hi, 'after': t > hi}. A line blame has no time for counts as 0
    (before), as in tag_lines."""
    out = {"before": 0, "in": 0, "after": 0}
    for n in lines:
        if n not in nonblank:
            continue
        t = times.get(n, 0)
        out["before" if t < lo else "after" if t > hi else "in"] += 1
    return out


def add(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


# --------------------------------------------------------------------------

def check_repo(name, clone=None):
    data = json.loads((QUESTIONS / f"{name}.json").read_text())
    repo = Repo(name, clone)
    if data["commit"] != repo.commit:
        raise SystemExit(f"{name}: frozen JSON commit does not match the pinned commit")
    funcs = repo.functions()
    lo, hi = month_bounds(MONTH)
    total, authored = {}, {}
    with_june = 0
    for q in data["questions"]:
        per_q = {}
        for path, lines in sorted(key_ranges(q, funcs).items()):
            nb = repo.nonblank(path)
            per_q = add(per_q, split_lines(repo.blame(path, True), sorted(lines), nb, lo, hi))
            authored = add(authored, split_lines(repo.blame(path, False), sorted(lines), nb, lo, hi))
        with_june += per_q.get("in", 0) > 0
        total = add(total, per_q)
    frozen_counted = sum(q["cutoff"]["lines_counted"] for q in data["questions"])
    frozen_after = sum(q["cutoff"]["lines_after"] for q in data["questions"])
    result = {"questions": len(data["questions"]), "split": total, "authored_in": authored.get("in", 0),
              "with_june": with_june, "frozen_counted": frozen_counted, "frozen_after": frozen_after,
              "commit": repo.commit, "cutoff": data["cutoff"],
              "py_all": py_lines(repo.clone, repo.commit),
              "py_scope": py_lines(repo.clone, repo.commit, lambda path: in_scope(path, repo.code_dirs)),
              "scope_text": repo.scope_text}
    if result["py_scope"] is not None and result["py_scope"][0] != len(repo.py_files()):
        raise SystemExit(f"{name}: key-scope .py count differs from Repo.py_files()")
    return result


def python_lines(results):
    """The 'Python at the pinned commit' lines: every .py file, and the questions' key scope."""
    def cell(v, i):
        return "not recorded" if v is None else f"{v[i]:,}"
    out = textwrap.wrap(f"Python at the pinned commit: {PY_LINES_METHOD}; key scope = the .py files the "
                        "questions' keys may cite (below).", WIDTH, initial_indent="  ", subsequent_indent="  ")
    out.append(f"  {'':<20}{'every .py file':>22}{'in key scope':>23}")
    out.append(f"  {'repo':<12}{'commit':<8}{'files':>11}{'lines':>11}{'files':>12}{'lines':>11}")
    for name, r in results:
        a, k = r["py_all"], r["py_scope"]
        out.append(f"  {name:<12}{r['commit'][:7]:<8}{cell(a, 0):>11}{cell(a, 1):>11}{cell(k, 0):>12}"
                   f"{cell(k, 1):>11}")
    out.append("  key scope:")
    for name, r in results:
        out += textwrap.wrap(f"{name}: {r['scope_text']}", WIDTH, initial_indent="    ",
                             subsequent_indent="      ", break_on_hyphens=False)
    return out


def render(results):
    lo, hi = month_bounds(MONTH)
    first = dt.datetime.fromtimestamp(lo, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    last = dt.datetime.fromtimestamp(hi, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = ["Eval key lines last changed in June 2026", "=" * WIDTH]
    out.append(f"  June 2026     {first} to {last} UTC")
    out.append("  key lines     the lines each question's cutoff tag counts (generate.py")
    out.append("                key_ranges; non-blank), summed over the questions")
    out.append("  dated by      git blame -w -M -C --first-parent at the pinned commit")
    out.append("                (committer time), as the tags are")
    out.append("")
    out.append(f"  {'repo':<12}{'questions':>10}{'key lines':>11}{'before June':>13}{'in June':>9}"
               f"{'after June':>12}")
    for name, r in results:
        s = r["split"]
        out.append(f"  {name:<12}{r['questions']:>10}{sum(s.values()):>11}{s.get('before', 0):>13}"
                   f"{s.get('in', 0):>9}{s.get('after', 0):>12}")
    out.append("")
    out.append("  questions with any key line last changed in June 2026:")
    for name, r in results:
        out.append(f"    {name:<12}{r['with_june']} of {r['questions']}")
    out.append("  key lines in June 2026 if dated by authored commit (no --first-parent):")
    for name, r in results:
        out.append(f"    {name:<12}{r['authored_in']}")
    out.append("")
    out.append("  check against the frozen JSON (sums of lines_counted, lines_after):")
    for name, r in results:
        s = r["split"]
        ok = (sum(s.values()) == r["frozen_counted"] and s.get("after", 0) == r["frozen_after"]
              and r["cutoff"] == f"{MONTH}-30")
        out.append(f"    {name:<12}counted {r['frozen_counted']}, after {r['cutoff']} {r['frozen_after']}: "
                   + ("match" if ok else "MISMATCH"))
    out.append("")
    out += python_lines(results)
    return "\n".join(line.rstrip() for line in out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repos", nargs="*", help=f"default: {' '.join(REPOS)}")
    args = ap.parse_args(argv)
    bad = [r for r in args.repos if r not in REPOS]
    if bad:
        ap.error(f"unknown repo {', '.join(bad)} (choose from {', '.join(REPOS)})")
    args.repos = args.repos or list(REPOS)
    results = []
    for name in args.repos:
        status(f"{name}: blaming key lines at the pinned commit")
        results.append((name, check_repo(name)))
    sys.stdout.write(render(results))


if __name__ == "__main__":
    main()

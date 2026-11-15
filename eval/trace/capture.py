"""Trace a target repo's toy entry point twice and print the capture.

    uv run python eval/trace/capture.py nanochat \
        > outputs/trace_nanochat.txt 2> outputs/trace_nanochat.err

Runs eval/trace/runner.py with the target's own venv python, in a fresh
process each time, compares the two kept paths, writes run 1's events to
outputs/trace_<repo>.json (the machine-readable key) and prints the report
on stdout. Progress and the target's own console output go to stderr.
Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tracer import (  # noqa: E402
    collapse, first_difference, path_key, qualnames_from_source, render_rows,
)

WIDTH = 74
MAX_DEPTH = 6
RUNS = 2
# One extra run with a different hash seed checks whether pinning it matters
CONTROL_HASHSEED = "1"
TARGETS = Path.home() / "Documents" / "GitHub" / "honeyguide-targets"
OUTPUTS = HERE.parent.parent / "outputs"

REPOS = {
    "nanochat": {
        "package_dir": "nanochat",
        "sys_path": ["."],   # not installed into its venv; import from the clone
        "entry": "entries/nanochat_entry.py",
    },
    "waku-agent": {
        "package_dir": "waku",   # waku/ only: hosted/, lab/, evals/ never kept
        "sys_path": [],      # editable install
        "entry": "entries/waku_entry.py",
    },
}

# Fixed so set/dict-of-str ordering cannot vary between runs; offline so no
# library can reach the network.
CHILD_ENV = {"PYTHONHASHSEED": "0", "HF_HUB_OFFLINE": "1"}


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Pure helpers

def resolve_anchor(text, needle):
    """1-based line of the first line containing needle, and how many lines
    contain it. Raises if absent, so a stale skip note cannot print."""
    hits = [i for i, line in enumerate(text.splitlines(), 1) if needle in line]
    if not hits:
        raise ValueError("anchor text not found: %r" % needle)
    return hits[0], len(hits)


def coverage(events, sources):
    """Per file: (functions defined, distinct functions called).
    sources maps repo-relative file -> source text."""
    called = {}
    for e in events:
        if e["kind"] == "call":
            called.setdefault(e["file"], set()).add(e["line"])
    rows = []
    for f in sorted(called):
        defined = qualnames_from_source(sources[f])
        rows.append((f, len(defined), len(called[f] & set(defined))))
    return rows


def kv_lines(key, value, width=WIDTH, key_width=14):
    """'key   value' wrapped to width with a hanging indent."""
    first = ("  %-*s " % (key_width, key))
    return textwrap.wrap(str(value), width=width, initial_indent=first,
                         subsequent_indent=" " * len(first),
                         break_on_hyphens=False) or [first.rstrip()]


def rule(ch="-"):
    return ch * WIDTH


# --------------------------------------------------------------------------
# Running

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def run_once(name, cfg, repo, out_path, hashseed=None):
    python = repo / ".venv" / "bin" / "python"
    cmd = [str(python), str(HERE / "runner.py"),
           "--entry", str(HERE / cfg["entry"]),
           "--repo-root", str(repo),
           "--package-dir", cfg["package_dir"],
           "--out", str(out_path)]
    for p in cfg["sys_path"]:
        cmd += ["--sys-path", str((repo / p).resolve())]
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env.update(CHILD_ENV)
    if hashseed is not None:
        env["PYTHONHASHSEED"] = hashseed
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, cwd=out_path.parent,
                          capture_output=True, text=True)
    seconds = time.perf_counter() - t0
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit("%s runner failed (exit %d)" % (name, proc.returncode))
    with open(out_path, encoding="utf-8") as fh:
        return json.load(fh), seconds


# --------------------------------------------------------------------------
# Report

def report(name, cfg, repo, runs, control, seconds):
    d = runs[0]
    pkg = cfg["package_dir"].rstrip("/") + "/"
    lines = []
    out = lines.append

    out("Runtime trace: %s" % name)
    out(rule("="))
    for k, v in [
        ("repo", git(repo, "remote", "get-url", "origin")),
        ("commit", git(repo, "rev-parse", "HEAD")),
        ("commit date", git(repo, "log", "-1", "--format=%cI")),
        ("branch", git(repo, "rev-parse", "--abbrev-ref", "HEAD")),
        ("tracked edits", len([x for x in git(
            repo, "status", "--porcelain", "--untracked-files=no").splitlines()
            if x])),
        ("python", d["python"]),
        ("libraries", ", ".join("%s %s" % kv for kv in d["versions"].items())),
        ("platform", d["platform"]),
        ("child env", " ".join("%s=%s" % kv for kv in CHILD_ENV.items())),
    ]:
        lines += kv_lines(k, v)
    out("")
    out("Entry point and config")
    out(rule())
    kw = max(len(k) for k in d["config"])
    for k, v in d["config"].items():
        lines += kv_lines(k, v, key_width=kw)
    out("")
    out("Filter rules")
    out(rule())
    for r in d["filter"]:
        out("  " + r)
    out("")

    out("Phases (run 1)")
    out(rule())
    out("  %-17s %10s %6s %8s %10s" % ("phase", "raw calls", "kept",
                                       "resumes", "synthetic"))
    tot = [0, 0, 0, 0]
    for p in d["phases"]:
        c = d["counts"][p["name"]]
        row = [c["raw_calls"], c["kept_calls"], c["kept_resumes"],
               c["dropped_synthetic"]]
        tot = [a + b for a, b in zip(tot, row, strict=True)]
        out("  %-17s %10d %6d %8d %10d" % (p["name"], *row))
    out("  %-17s %10d %6d %8d %10d" % ("total", *tot))
    out("  raw calls = every Python call event in the phase, any file;")
    out("  kept = repo calls on the path; resumes = generator re-entries")
    out("  (kept in the path, marked, not counted as calls); synthetic =")
    out("  repo lambdas, comprehensions and class bodies dropped.")
    fallbacks = sum(c["qualname_fallbacks"] for c in d["counts"].values())
    out("  names not found in the source index (fallback): %d" % fallbacks)
    checked = sum(c["qualname_checked"] for c in d["counts"].values())
    bad = sum(c["qualname_mismatches"] for c in d["counts"].values())
    if checked:
        out("  source-index names vs Python's co_qualname: %d of %d"
            % (checked - bad, checked))
        out("  kept events agree")
    else:
        out("  source-index names vs co_qualname: not checkable on %s"
            % d["python"])
    out("")

    out("What the run returned (sanity, not a result)")
    out(rule())
    for k, v in d["results"].items():
        lines += kv_lines(k, v, key_width=28)
    out("")

    out("Reproducibility (fresh process per run)")
    out(rule())
    keys = [path_key(r["events"]) for r in runs]
    labels = ["run %d" % (i + 1) for i in range(len(runs))]
    labels.append("control, PYTHONHASHSEED=%s" % CONTROL_HASHSEED)
    keys.append(path_key(control["events"]))
    for i in range(1, len(keys)):
        diff = first_difference(keys[0], keys[i])
        verdict = ("identical (%d events)" % len(keys[0]) if diff is None
                   else "DIFFERS at event %d" % diff)
        out("  kept path, run 1 vs %s:" % labels[i])
        out("    " + verdict)
    raws = ["%d" % sum(c["raw_calls"] for c in r["counts"].values())
            for r in runs + [control]]
    out("  raw calls, runs then control: " + " / ".join(raws))
    out("  wall time, runs then control: "
        + " / ".join("%.1f s" % s for s in seconds))
    out("")

    out("Coverage of the files the trace touched")
    out(rule())
    out("  %-44s %8s %8s" % ("file (under %s)" % pkg, "defined", "called"))
    sources = {f: (repo / f).read_text(encoding="utf-8")
               for f in {e["file"] for e in d["events"]}}
    for f, n_def, n_called in coverage(d["events"], sources):
        out("  %-44s %8d %8d" % (f[len(pkg):] if f.startswith(pkg) else f,
                                 n_def, n_called))
    out("  defined = def statements in the file (methods and nested")
    out("  functions included); called = distinct ones seen in any phase.")
    out("")

    out("Collapsed paths")
    out(rule())
    out("  One block per phase. Indent = depth in repo frames. xN =")
    out("  N consecutive identical subtrees folded. (+N deeper) = kept")
    out("  calls below depth %d, hidden here, kept in the JSON." % MAX_DEPTH)
    out("  (resume) = a suspended generator re-entered. [worker-1] = a")
    out("  thread the run started. Anchors: file:line of the def (of")
    out("  its first decorator if decorated), relative to %s" % pkg)
    for p in d["phases"]:
        ev = [e for e in d["events"] if e["phase"] == p["name"]]
        n_calls = sum(1 for e in ev if e["kind"] == "call")
        out("")
        head = "## %s: %s" % (p["name"], p["description"])
        lines += textwrap.wrap(head, WIDTH, subsequent_indent="   ")
        rows = collapse(ev, MAX_DEPTH)
        out("   kept calls %d, resumes %d, max depth %d, rows shown %d"
            % (n_calls, len(ev) - n_calls,
               max((e["depth"] for e in ev), default=0) -
               min((e["depth"] for e in ev), default=0), len(rows)))
        rows = [(dep, lab, a[len(pkg):] if a.startswith(pkg) else a, rep, hid)
                for dep, lab, a, rep, hid in rows]
        if not rows:
            out("   (no repo-owned Python calls)")
        lines += render_rows(rows, WIDTH, indent=2)
    out("")

    out("What this toy run skips (read from the code at this commit)")
    out(rule())
    for text, rel, needle in d["skips"]:
        line, hits = resolve_anchor((repo / rel).read_text(encoding="utf-8"),
                                    needle)
        lines += textwrap.wrap("- " + text, WIDTH, subsequent_indent="  ")
        anchor = "%s:%d" % (rel, line) + ("" if hits == 1 else " (1st of %d)" % hits)
        out("    " + anchor)
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", choices=sorted(REPOS))
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--json-out", default=None,
                    help="default outputs/trace_<repo>.json")
    args = ap.parse_args()
    cfg = REPOS[args.repo]
    repo = TARGETS / args.repo
    runs, seconds = [], []
    with tempfile.TemporaryDirectory() as tmp:
        plan = [(None, "run %d/%d" % (i + 1, args.runs)) for i in range(args.runs)]
        plan.append((CONTROL_HASHSEED, "control (PYTHONHASHSEED=%s)" % CONTROL_HASHSEED))
        for i, (seed, label) in enumerate(plan):
            status("[%s] %s ..." % (args.repo, label))
            d, s = run_once(args.repo, cfg, repo, Path(tmp) / ("run%d.json" % i),
                            hashseed=seed)
            status("[%s] %s done in %.1f s" % (args.repo, label, s))
            runs.append(d)
            seconds.append(s)
    runs, control = runs[:-1], runs[-1]
    json_out = Path(args.json_out or OUTPUTS / ("trace_%s.json" % args.repo))
    keep = {k: v for k, v in runs[0].items()}
    keep["commit"] = git(repo, "rev-parse", "HEAD")
    json_out.write_text(json.dumps(keep, indent=1) + "\n", encoding="utf-8")
    lines = report(args.repo, cfg, repo, runs, control, seconds)
    too_wide = [ln for ln in lines if len(ln) > WIDTH]
    if too_wide:
        status("warning: %d lines wider than %d" % (len(too_wide), WIDTH))
    print("\n".join(ln.rstrip() for ln in lines))


if __name__ == "__main__":
    main()

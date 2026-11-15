"""Run one entry module under the tracer and write the events as JSON.

Executed by the TARGET repo's own venv python (see capture.py), so it must
stay standard library only and Python 3.10 compatible.

An entry module defines:
  CONFIG    dict printed in the capture
  SKIPS     [(what the toy setup skips, repo-relative file, text to find)]
  versions() -> dict of library versions
  setup()   -> ctx dict (untraced: imports, fixtures)
  PHASES    [(name, description, fn(ctx))], each traced separately
"""

import argparse
import importlib.util
import json
import os
import platform
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tracer import FilterRules, Tracer  # noqa: E402


def load_entry(path):
    spec = importlib.util.spec_from_file_location("honeyguide_entry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--package-dir", required=True,
                    help="package source, relative to the repo root")
    ap.add_argument("--sys-path", action="append", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    for p in args.sys_path:
        sys.path.insert(0, p)
    repo_root = os.path.realpath(args.repo_root)
    rules = FilterRules(roots=(os.path.join(repo_root, args.package_dir),))

    entry = load_entry(args.entry)
    t0 = time.perf_counter()
    ctx = entry.setup()
    setup_s = time.perf_counter() - t0

    tracer = Tracer(rules, repo_root)
    phases = []
    for name, description, fn in entry.PHASES:
        t0 = time.perf_counter()
        tracer.run_phase(name, lambda fn=fn: fn(ctx))
        phases.append({"name": name, "description": description,
                       "seconds": time.perf_counter() - t0})

    out = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": entry.versions(),
        "config": entry.CONFIG,
        "skips": entry.SKIPS,
        "results": ctx.get("results", {}),
        "filter": rules.describe(repo_root),
        "setup_seconds": setup_s,
        "phases": phases,
        "counts": tracer.counts,
        "events": tracer.events,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh)


if __name__ == "__main__":
    main()

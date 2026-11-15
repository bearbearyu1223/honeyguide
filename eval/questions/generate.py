"""Generate Honeyguide's frozen eval questions and answer keys for one repo.

    uv run python eval/questions/generate.py nanochat --cutoff 2026-06-30 \
        > outputs/questions_nanochat.txt

Reads the target at its pinned commit (git show / blame, never the working
tree) and the T3 trace (outputs/trace_<repo>.json). Writes, under
eval/questions/:

- <repo>.json: questions, keys, cutoff tags, filter rules, commit, version
- <repo>_flow_hops_to_mark.md: Han marks each candidate hop
- <repo>_callers_disputes.md: call sites the AST can't settle, for Han
- MANIFEST.txt: SHA-256 of every file here, so the frozen set (and the
  code that made it) can be proven unchanged later

and prints the capture (74 columns) on stdout. Deterministic: no clock,
no randomness except the seeded presentation order. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from keys import (  # noqa: E402
    DISPUTE_KINDS, RESOLUTION, Project, call_graph, callers_of, disputes_for,
    flow_hops, leaks, loose_leaks, tag_lines, trace_callers,
)
from repo import REPOS, Repo  # noqa: E402
from specs import SPECS  # noqa: E402

GENERATOR_VERSION = "1"
WIDTH = 74
DEFAULT_CUTOFF = "2026-06-30"
# Printed for comparison only; the JSON's tags use --cutoff
OTHER_CUTOFFS = ("2025-12-31", "2026-03-31")
OUTPUTS = HERE.parent.parent / "outputs"
SCOPE = {
    "locate": "file + function; a function nested inside the key function "
              "also counts",
    "callers": "the set of direct callers (file + function, or file + "
               "<module> for top-level code), outside tests/, examples/, docs/",
    "flow": "the required hops Han marks, recalled, in order (LCS); hops in "
            "neither the trace nor the AST count as invented",
}


def scoring_scope(repo):
    """SCOPE, with the callers line naming the repo's code dirs if it has
    them (nanochat's set predates code_dirs and keeps its text)."""
    if not repo.code_dirs:
        return SCOPE
    dirs = ", ".join(d + "/" for d in repo.code_dirs)
    return dict(SCOPE, callers="the set of direct callers (file + function, or "
                               f"file + <module> for top-level code), under {dirs}")


BLAME_RULE = [
    "git blame -w -M -C --first-parent at the pinned commit; committer",
    "time per line (a branch merged later is dated by its merge; moved",
    "or copied lines keep their original date)",
    "a question is 'after' when at least half of its key's non-blank",
    "lines changed after the cutoff day (23:59:59 UTC)",
    "key lines: locate = the function; callers = the call lines of",
    "key callers and open disputes; flow = every candidate hop's",
    "function",
]


def status(msg):
    print(msg, file=sys.stderr, flush=True)


def cutoff_ts(day):
    return dt.datetime.fromisoformat(day + "T23:59:59+00:00").timestamp()


def iso_day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Tagging

class Tagger:
    def __init__(self, repo, cutoff):
        self.repo, self.cutoff = repo, cutoff

    def tag(self, ranges, cutoff=None):
        """ranges: {file: set of line numbers}. Returns the tag record."""
        ts = cutoff_ts(cutoff or self.cutoff)
        after = total = after_c = 0
        newest = 0
        for path in sorted(ranges):
            lines = sorted(ranges[path])
            nb = self.repo.nonblank(path)
            fp = self.repo.blame(path, True)
            a, n, _ = tag_lines(fp, lines, ts, nb)
            ac, _, _ = tag_lines(self.repo.blame(path, False), lines, ts, nb)
            after, total, after_c = after + a, total + n, after_c + ac
            newest = max([newest] + [fp.get(i, 0) for i in lines if i in nb])
        return {
            "subset": "after" if total and 2 * after >= total else "before",
            "lines_after": after,
            "lines_counted": total,
            "newest_change": iso_day(newest) if newest else None,
            "subset_by_authored_commit": (
                "after" if total and 2 * after_c >= total else "before"),
        }


def func_lines(f):
    return set(range(f.start, f.end + 1))


# --------------------------------------------------------------------------
# Question builders

def build_locate(spec, repo, tagger):
    funcs = repo.functions()
    out = []
    for i, (path, qual, text) in enumerate(spec["locate"], 1):
        f = funcs.get((path, qual))
        if f is None:
            raise SystemExit(f"locate: {path}:{qual} not found at the commit")
        nested = sorted(q for (p, q) in funcs if p == path and q.startswith(qual + ".<locals>."))
        symbols = [f.name] + ([f.cls.split(".")[-1]] if f.cls else [])
        out.append({
            "id": f"{spec['prefix']}-loc-{i:02d}",
            "type": "locate",
            "text": text,
            "phrasing": "hand",
            "key": {"file": path, "qual": qual, "lines": [f.start, f.end],
                    "also_accept": nested},
            "cutoff": tagger.tag({path: func_lines(f)}),
            "leaks": leaks(text, symbols, [path]),
            "loose_leaks": loose_leaks(text, symbols),
        })
    return out


def qual_is_unique(funcs, qual):
    return sum(1 for (_, q) in funcs if q == qual) == 1


def build_callers(spec, repo, tagger, edges, sites, events):
    funcs = repo.functions()
    out, disputes = [], []
    for i, (path, qual) in enumerate(spec["callers"], 1):
        f = funcs.get((path, qual))
        if f is None:
            raise SystemExit(f"callers: {path}:{qual} not found at the commit")
        qid = f"{spec['prefix']}-cal-{i:02d}"
        ast_c = callers_of(edges, (path, qual))
        via = {}
        for e in edges:
            if (e.callee_file, e.callee) == (path, qual):
                via.setdefault((e.caller_file, e.caller), set()).add(e.via)
        tr_c = {}
        if path.startswith(repo.trace_root):
            for (cf, cq), lines in trace_callers(events, path, qual).items():
                if cf is None:
                    cands = [p for (p, q) in funcs if q == cq]
                    cf = cands[0] if len(cands) == 1 else "?"
                tr_c[(cf, cq)] = lines
        keyset = sorted(set(ast_c) | set(tr_c))
        callers = []
        ranges = {}
        for k in keyset:
            src = "both" if k in ast_c and k in tr_c else ("ast" if k in ast_c else "trace")
            lines = sorted(set(ast_c.get(k, [])) | set(tr_c.get(k, [])))
            callers.append({
                "file": k[0], "qual": k[1], "source": src,
                "ast_lines": ast_c.get(k, []), "trace_lines": tr_c.get(k, []),
                "ast_via": sorted(via.get(k, [])),
            })
            ranges.setdefault(k[0], set()).update(lines)
        site_list = disputes_for(sites, f.name)
        in_key = [d for d in site_list if (d.caller_file, d.caller) in set(keyset)]
        open_ = group_disputes(
            [d for d in site_list if (d.caller_file, d.caller) not in set(keyset)],
            unique=sum(1 for (_, q) in funcs if q.split(".")[-1] == f.name) == 1)
        for g in open_:
            disputes.append((qid, qual, g))
            ranges.setdefault(g["file"], set()).update(g["lines"])
        name = qual if qual_is_unique(funcs, qual) else f"{qual} in {path}"
        text = (f"What calls `{name}` directly? List every caller "
                f"{repo.callers_scope}.")
        named = set(qual.replace(".<locals>.", ".").split("."))
        symbols = sorted(({c["qual"].split(".")[-1] for c in callers}
                          | {c["qual"].split(".")[0] for c in callers if "." in c["qual"]})
                         - {"<module>"} - named)
        files = sorted({c["file"] for c in callers} - {path})
        out.append({
            "id": qid,
            "type": "callers",
            "text": text,
            "target": {"file": path, "qual": qual, "lines": [f.start, f.end],
                       "in_trace_scope": path.startswith(repo.trace_root)},
            "key": {"callers": callers},
            "disputes_for_han": open_,
            "unresolved_sites_already_in_key": [_dispute_json(d) for d in in_key],
            "cutoff": dict(tagger.tag(ranges), basis="key callers and open disputes"),
            "names_target": bool(leaks(text, [f.name], [])),
            "leaks": leaks(text, symbols, files),
        })
    return out, disputes


def group_disputes(sites, unique):
    """One entry per (file, caller): Han decides per caller, not per line."""
    groups = {}
    for d in sites:
        g = groups.setdefault((d.caller_file, d.caller), {
            "file": d.caller_file, "caller": d.caller, "lines": [], "kinds": [],
            "name": d.name, "only_repo_def_with_this_name": unique, "mark": None})
        g["lines"] = sorted(set(g["lines"]) | {d.line})
        g["kinds"] = sorted(set(g["kinds"]) | {d.kind})
    return [groups[k] for k in sorted(groups)]


def _dispute_json(d):
    return {"file": d.caller_file, "caller": d.caller, "line": d.line,
            "name": d.name, "kind": d.kind}


def build_flow(spec, repo, tagger, events, trace_config):
    funcs = repo.functions()
    out = []
    rules = spec["flow_rules"]
    for i, q in enumerate(spec["flow"], 1):
        if q["phase"] == "backward":
            raise SystemExit("flow: backward has no repo calls in the trace")
        hops, dropped, raw = flow_hops(events, q["phase"], q["entries"], funcs,
                                       rules, fold=q["fold"])
        ranges = {}
        hop_json = []
        for h in hops:
            f = funcs.get((h.file, h.qual))
            ranges.setdefault(h.file, set()).update(func_lines(f) if f else {h.line})
            hop_json.append({
                "file": h.file, "qual": h.qual,
                "lines": [f.start, f.end] if f else [h.line, h.line],
                "calls": h.calls, "first_caller": h.caller, "thread": h.thread,
                "folded": h.folded, "cached": h.cached, "mark": None,
            })
        entry_quals = {e[0] for e in q["entries"]}
        named = {part for e in entry_quals for part in e.replace(".<locals>.", ".").split(".")}
        others = [h for h in hops if h.qual not in entry_quals]
        # function names only: class names in the config are named by design
        symbols = sorted({h.qual.split(".")[-1] for h in others} - named)
        out.append({
            "id": f"{spec['prefix']}-flo-{i:02d}",
            "type": "flow",
            "text": q["text"],
            "trace_phase": q["phase"],
            "entries": [{"qual": e[0], "call_index": e[1]} for e in q["entries"]],
            "fold": list(q["fold"]),
            "trace_config": trace_config,
            "key": {"candidate_hops": hop_json, "raw_calls": raw,
                    "dropped": dropped,
                    "status": "candidates; Han marks each hop required or optional"},
            "cutoff": tagger.tag(ranges),
            "leaks": leaks(q["text"], symbols, []),
        })
    return out


# --------------------------------------------------------------------------
# Sheets for Han

def flow_sheet(name, repo, flows):
    lines = [f"# {name}: flow hops to mark", "",
             f"Commit {repo.commit[:7]}. For each question, tick one box per hop: "
             "**required** (an answer that misses it is incomplete) or **optional** "
             "(fine to mention, fine to skip). Hops are in first-call order; xN = "
             "times called; (fold) = counts as one step, inside is another question; "
             "(cached) = lru_cache, later calls may not show; [worker-1] = runs on a "
             "thread the code starts.", ""]
    for q in flows:
        lines += [f"## {q['id']} ({q['trace_phase']})", "", q["text"], ""]
        for h in q["key"]["candidate_hops"]:
            tags = []
            if h["calls"] > 1:
                tags.append(f"x{h['calls']}")
            if h["folded"]:
                tags.append("(fold)")
            if h["cached"]:
                tags.append("(cached)")
            if h["thread"] != "main":
                tags.append(f"[{h['thread']}]")
            extra = (" " + " ".join(tags)) if tags else ""
            lines.append(f"- [ ] required [ ] optional: `{h['qual']}` "
                         f"{h['file']}:{h['lines'][0]}{extra}")
        lines.append("")
    return "\n".join(lines)


def disputes_sheet(name, repo, callers, disputes):
    lines = [f"# {name}: callers disputes", "",
             f"Commit {repo.commit[:7]}. Each callers key is the AST call graph "
             "united with the T3 runtime trace. Below are the call sites the AST "
             "could not resolve and the trace did not confirm. For each, tick "
             "**caller** (add it to the key) or **not** (leave it out).", ""]
    lines += ["Kinds:"] + [f"- {k}: {v}" for k, v in DISPUTE_KINDS.items()] + [""]
    by_q = {}
    for qid, qual, d in disputes:
        by_q.setdefault((qid, qual), []).append(d)
    for q in callers:
        key = (q["id"], q["target"]["qual"])
        ds = by_q.get(key, [])
        n_key = len(q["key"]["callers"])
        lines.append(f"## {q['id']}: {q['target']['qual']} "
                     f"({n_key} callers in the key, {len(ds)} to decide)")
        lines.append("")
        for c in q["key"]["callers"]:
            lines.append(f"- in key ({c['source']}): `{c['qual']}` {c['file']}")
        for d in ds:
            at = ", ".join(str(n) for n in d["lines"])
            hint = "; only repo def named so" if d["only_repo_def_with_this_name"] else ""
            lines.append(f"- [ ] caller [ ] not: `{d['caller']}` {d['file']} line "
                         f"{at} ({'/'.join(d['kinds'])}: `{d['name']}`{hint})")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Report (stdout)

def wrap(text, indent=2, sub=4):
    return textwrap.wrap(text, WIDTH, initial_indent=" " * indent,
                         subsequent_indent=" " * sub)


def rule(title):
    return ["", title, "-" * WIDTH]


def report(name, repo, args, data, trace_sha, alt):
    qs = data["questions"]
    out = [f"Eval questions and keys: {name}", "=" * WIDTH]
    out.append(f"  repo           {repo.url}")
    out.append(f"  commit         {repo.commit}")
    out.append(f"  commit date    {repo.commit_date()}")
    out.append(f"  generator      v{GENERATOR_VERSION}, seed {args.seed}")
    out.append(f"  cutoff         {args.cutoff} (a parameter until verified)")
    out.append(f"  trace          outputs/trace_{name}.json")
    out.append(f"                 sha256 {trace_sha[:16]}...")

    out += rule("Questions by type and subset (cutoff " + args.cutoff + ")")
    out.append(f"  {'type':<10}{'total':>7}{'before':>8}{'after':>7}{'none':>6}")
    types = ["locate", "callers", "flow"]
    for t in types:
        sub = [q for q in qs if q["type"] == t]
        c = {s: sum(q["cutoff"]["subset"] == s for q in sub) for s in ("before", "after", "none")}
        out.append(f"  {t:<10}{len(sub):>7}{c['before']:>8}{c['after']:>7}{c['none']:>6}")
    c = {s: sum(q["cutoff"]["subset"] == s for q in qs) for s in ("before", "after", "none")}
    out.append(f"  {'all':<10}{len(qs):>7}{c['before']:>8}{c['after']:>7}{c['none']:>6}")
    out.append(f"  {'why/how':<10}{'slot':>7}  Han writes ~10 (T5); not generated")
    if c["none"]:
        out.append("  none = no key lines to blame")
    n_dis = sum(q["cutoff"].get("subset_by_authored_commit") != q["cutoff"]["subset"]
                for q in qs)
    out.append(f"  tag differs if dated by authored commit instead of merge: {n_dis}")

    out += rule("Blame rule")
    out += ["  " + s for s in BLAME_RULE]

    out += rule("After-cutoff counts at other cutoffs (same questions)")
    out.append(f"  {'cutoff':<12}" + "".join(f"{t:>9}" for t in types) + f"{'all':>7}")
    for day, counts in alt:
        out.append(f"  {day:<12}" + "".join(f"{counts[t]:>9}" for t in types)
                   + f"{counts['all']:>7}")

    out += rule("Leakage (key names or file names verbatim in the text)")
    loc = [q for q in qs if q["type"] == "locate"]
    cal = [q for q in qs if q["type"] == "callers"]
    flo = [q for q in qs if q["type"] == "flow"]
    out.append(f"  locate: key function, class or file named      "
               f"{sum(bool(q['leaks']) for q in loc):>3} of {len(loc)}")
    out.append(f"  locate: all words of a key name present (loose) "
               f"{sum(bool(q['loose_leaks']) for q in loc):>3} of {len(loc)}")
    out.append(f"  callers: target named (by design)               "
               f"{sum(q['names_target'] for q in cal):>3} of {len(cal)}")
    out.append(f"  callers: a key caller or its file named          "
               f"{sum(bool(q['leaks']) for q in cal):>3} of {len(cal)}")
    out.append(f"  flow: a hop's function named (not the entry's)  "
               f"{sum(bool(q['leaks']) for q in flo):>3} of {len(flo)}")
    for q in loc + cal + flo:
        if q["leaks"] or q.get("loose_leaks"):
            names = ", ".join(q["leaks"] + [n + " (loose)" for n in q.get("loose_leaks", [])])
            out += wrap(f"{q['id']}: {names}", 4, 6)

    out += rule("Callers keys: where each key caller came from")
    tot = {"ast": 0, "trace": 0, "both": 0}
    for q in cal:
        for c in q["key"]["callers"]:
            tot[c["source"]] += 1
    out.append(f"  key callers {sum(tot.values())}: ast only {tot['ast']}, trace only "
               f"{tot['trace']}, both {tot['both']}")
    out.append(f"  {'id':<10}{'target':<36}{'ast':>4}{'trace':>6}{'both':>5}{'han':>5}")
    for q in cal:
        cs = q["key"]["callers"]
        n = {s: sum(c["source"] == s for c in cs) for s in ("ast", "trace", "both")}
        tgt = q["target"]["qual"]
        tgt = tgt if len(tgt) <= 35 else tgt[:32] + "..."
        out.append(f"  {q['id']:<10}{tgt:<36}{n['ast']:>4}{n['trace']:>6}{n['both']:>5}"
                   f"{len(q['disputes_for_han']):>5}")
    out.append("  han = call sites the AST can't resolve and the trace didn't")
    out.append("  confirm (getattr, obj.m() on an unknown type, callbacks)")
    out.append("  AST resolution rules:")
    for k, v in RESOLUTION.items():
        out += wrap(f"{k}: {v}", 4, 6)

    out += rule("Flow keys: trace pre-filter")
    out += ["  " + s for s in data["flow_rules"]]
    out.append(f"  {'id':<10}{'phase':<18}{'raw':>5}{'hops':>6}  dropped")
    for q in flo:
        d = q["key"]["dropped"]
        short = ", ".join(f"{k} {v}" for k, v in d.items())
        rows = textwrap.wrap(short, WIDTH - 43) or [""]
        out.append(f"  {q['id']:<10}{q['trace_phase']:<18}{q['key']['raw_calls']:>5}"
                   f"{len(q['key']['candidate_hops']):>6}  {rows[0]}")
        for r in rows[1:]:
            out.append(" " * 43 + r)
    out.append("  raw = repo calls in the entry's subtree (T3 filter); hops =")
    out.append("  candidates Han marks")

    out += rule("Examples")
    for t in types:
        for q in [q for q in qs if q["type"] == t][:2]:
            out += wrap(f"{q['id']} [{q['cutoff']['subset']}] {q['text']}", 2, 4)
            if t == "locate":
                k = q["key"]
                out += wrap(f"key: {k['file']} {k['qual']} "
                            f"lines {k['lines'][0]}-{k['lines'][1]}", 4, 6)
            elif t == "callers":
                cs = q["key"]["callers"]
                names = "; ".join(f"{c['qual']} ({c['source']})" for c in cs) or "none"
                n = len(q["disputes_for_han"])
                more = f"; {n} disputed caller{'s' * (n != 1)} for Han" if n else ""
                out += wrap(f"key: {names}{more}", 4, 6)
            else:
                hops = " > ".join(h["qual"] for h in q["key"]["candidate_hops"])
                out += wrap(f"candidates: {hops}", 4, 6)
            out.append("")
    if out[-1] == "":
        out.pop()

    out += rule("What Han marks")
    n_hops = sum(len(q["key"]["candidate_hops"]) for q in flo)
    n_dis = sum(len(q["disputes_for_han"]) for q in cal)
    out.append(f"  flow hops (required / optional)   {n_hops:>4} in {len(flo)} questions")
    out.append(f"  callers disputes (caller / not)   {n_dis:>4} in "
               f"{sum(bool(q['disputes_for_han']) for q in cal)} questions")
    out.append(f"  sheets: eval/questions/{name}_flow_hops_to_mark.md,")
    out.append(f"          eval/questions/{name}_callers_disputes.md")
    for line in out:
        assert len(line) <= WIDTH, line
    return "\n".join(line.rstrip() for line in out) + "\n"


# --------------------------------------------------------------------------

def manifest(directory):
    rows = []
    for p in sorted(directory.rglob("*")):
        if p.is_dir() or "__pycache__" in p.parts or p.name == "MANIFEST.txt":
            continue
        rows.append(f"{sha256(p)}  {p.relative_to(directory).as_posix()}")
    head = ["# SHA-256 of every file in eval/questions/ (this file excluded).",
            "# Check: cd eval/questions && shasum -a 256 -c MANIFEST.txt"]
    return "\n".join(head + rows) + "\n"


def generate(name, args):
    spec = SPECS[name]
    repo = Repo(name, args.clone)
    trace_path = Path(args.trace) if args.trace else OUTPUTS / f"trace_{name}.json"
    trace = json.loads(trace_path.read_text())
    if trace["commit"] != repo.commit:
        raise SystemExit("trace commit does not match the pinned commit")
    events = trace["events"]
    tagger = Tagger(repo, args.cutoff)

    status(f"{name}: indexing {len(repo.py_files())} files at {repo.commit[:7]}")
    project = Project(list(repo.modules()))
    edges, sites = call_graph(project)
    status(f"{name}: {len(edges)} call edges, {len(sites)} unresolved sites")

    status(f"{name}: building questions and blaming key lines")
    locate = build_locate(spec, repo, tagger)
    callers, disputes = build_callers(spec, repo, tagger, edges, sites, events)
    flow = build_flow(spec, repo, tagger, events, trace["config"])
    questions = locate + callers + flow
    order = [q["id"] for q in questions]
    random.Random(args.seed).shuffle(order)

    alt = []
    for day in OTHER_CUTOFFS:
        counts = {"locate": 0, "callers": 0, "flow": 0}
        for q in questions:
            rng = _key_ranges(q, repo)
            if rng and tagger.tag(rng, day)["subset"] == "after":
                counts[q["type"]] += 1
        counts["all"] = sum(counts.values())
        alt.append((day, counts))

    data = {
        "repo": name,
        "url": repo.url,
        "commit": repo.commit,
        "commit_date": repo.commit_date(),
        "generator_version": GENERATOR_VERSION,
        "seed": args.seed,
        "cutoff": args.cutoff,
        "blame_rule": BLAME_RULE,
        "scope": {"code": repo.scope_text,
                  "trace": repo.trace_root, "scoring": scoring_scope(repo)},
        "trace": {"path": f"outputs/trace_{name}.json", "sha256": sha256(trace_path)},
        "flow_rules": spec["flow_rules"].describe(),
        "ast_resolution": RESOLUTION,
        "dispute_kinds": DISPUTE_KINDS,
        "presentation_order": order,
        "questions": questions,
        "why_how": {"status": "slot: Han writes ~10 questions and a rubric (T5) "
                              "before any map exists", "questions": []},
    }
    text = report(name, repo, args, data, sha256(trace_path), alt)
    out_dir = Path(args.out_dir)
    (out_dir / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n")
    (out_dir / f"{name}_flow_hops_to_mark.md").write_text(flow_sheet(name, repo, flow) + "\n")
    (out_dir / f"{name}_callers_disputes.md").write_text(
        disputes_sheet(name, repo, callers, disputes) + "\n")
    (out_dir / "MANIFEST.txt").write_text(manifest(out_dir))
    status(f"{name}: wrote {name}.json, sheets, MANIFEST.txt")
    return text


def _key_ranges(q, repo):
    funcs = repo.functions()
    if q["type"] == "locate":
        k = q["key"]
        return {k["file"]: set(range(k["lines"][0], k["lines"][1] + 1))}
    if q["type"] == "callers":
        r = {}
        for c in q["key"]["callers"]:
            r.setdefault(c["file"], set()).update(c["ast_lines"] + c["trace_lines"])
        return r
    r = {}
    for h in q["key"]["candidate_hops"]:
        f = funcs.get((h["file"], h["qual"]))
        r.setdefault(h["file"], set()).update(
            range(f.start, f.end + 1) if f else [h["lines"][0]])
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", choices=sorted(REPOS))
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF,
                    help="model training cutoff day, YYYY-MM-DD (default %(default)s)")
    ap.add_argument("--seed", type=int, default=0, help="presentation-order seed")
    ap.add_argument("--clone", help="target clone (default ~/Documents/GitHub/"
                                    "honeyguide-targets/<repo>)")
    ap.add_argument("--trace", help="T3 trace JSON (default outputs/trace_<repo>.json)")
    ap.add_argument("--out-dir", default=str(HERE))
    args = ap.parse_args(argv)
    dt.date.fromisoformat(args.cutoff)
    sys.stdout.write(generate(args.repo, args))


if __name__ == "__main__":
    main()

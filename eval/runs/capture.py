"""Print the receipts of the real Honeyguide runs (run 1, run 2, repair, live demo).

    uv run python eval/runs/capture.py > outputs/runs.txt 2> outputs/runs.err

Reads the run archive (default ~/Documents/GitHub/honeyguide-targets/_runs,
or --archive DIR) and never writes to it. Prints six labelled blocks: runs,
maps, checker, readability, demo, examples. Every number is read from the
archive; a value the archive does not hold prints as "not recorded".
Repos are printed by name, never by path. Standard library only (plus
honeyguide.readability for the readability block).
"""

import argparse
import json
import sys
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    from honeyguide.mapdoc import block_text, module_blocks, module_files
    from honeyguide.readability import check_readability, prose_pieces, words
except ImportError:   # run outside the uv environment
    sys.path.insert(0, str(HERE.parents[1] / "src"))
    from honeyguide.mapdoc import block_text, module_blocks, module_files
    from honeyguide.readability import check_readability, prose_pieces, words

WIDTH = 74
DEFAULT_ARCHIVE = Path.home() / "Documents" / "GitHub" / "honeyguide-targets" / "_runs"
NOT_RECORDED = "not recorded"
TOPICS = ("purpose", "users", "capabilities", "commands", "entry-points", "components", "start-here")
STATES = ("supported", "not_supported", "unchecked", "retired")
NARROWED_RULE = "the first claim in id order (both repos) with a 'rewrite' repair"
WRONGLY_PASSED = "c_20b0bb0d778f"


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Pure helpers (tested in tests/test_eval_runs.py)

def repo_of_store(dirname):
    """'github.com__karpathy__nanochat__3a5e0bc50b12' -> 'nanochat'."""
    parts = dirname.split("__")
    return parts[2] if len(parts) >= 4 else dirname


def parse_time(text):
    return datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%SZ")


def minutes_between(start, end):
    """Minutes from start to end (ISO-Z strings), or None when either is missing."""
    if not start or not end:
        return None
    return (parse_time(end) - parse_time(start)).total_seconds() / 60


def claim_state(claim, stage):
    """A map claim's Checker state after repair round ``stage`` (0 = before repair).

    A repair recorded at round r means the claim was not supported after round r-1, so any repair at a round later
    than ``stage`` makes it ``not_supported`` then; otherwise its saved state holds.
    """
    if any(r.get("round", 0) > stage for r in claim.get("repairs") or []):
        return "not_supported"
    if claim.get("freshness") == "retired":
        return "retired"
    check = claim.get("check") or "unchecked"
    return check if check in STATES else "unchecked"


def stage_counts(claims, stage):
    c = Counter(claim_state(x, stage) for x in claims)
    return {s: c.get(s, 0) for s in STATES}


def anchor_lines(anchors):
    """Cited (path, line) pairs from saved anchors (dicts) or repair-history anchors ('path:start-end')."""
    out = set()
    for a in anchors or []:
        if isinstance(a, dict):
            path, start, end = a.get("path"), a.get("start"), a.get("end")
        else:
            path, _, span = str(a).rpartition(":")
            start, _, end = span.partition("-")
        try:
            start, end = int(start), int(end or start)
        except (TypeError, ValueError):
            continue
        out.update((path, n) for n in range(start, end + 1))
    return out


def repair_steps(claim):
    """(round, action, before_text, after_text, before_lines, after_lines) for each repair of a claim."""
    reps = sorted(claim.get("repairs") or [], key=lambda r: r.get("round", 0))
    steps = []
    for i, r in enumerate(reps):
        nxt = reps[i + 1] if i + 1 < len(reps) else None
        after_text = nxt["text"] if nxt else claim.get("text", "")
        after_anchors = nxt["anchors"] if nxt else claim.get("anchors")
        steps.append((r.get("round", 0), r.get("action"), r.get("text", ""), after_text,
                      len(anchor_lines(r.get("anchors"))), len(anchor_lines(after_anchors))))
    return steps


def repair_summary(claims):
    """Per round: action counts, and for 'anchor' repairs how many cite more lines afterwards."""
    out = {}
    for claim in claims:
        for rnd, action, _, _, before, after in repair_steps(claim):
            row = out.setdefault(rnd, {"anchor": 0, "rewrite": 0, "retire": 0, "wider": 0})
            row[action] = row.get(action, 0) + 1
            if action == "anchor" and after > before:
                row["wider"] += 1
    return out


def map_stats(layer):
    doc = layer.get("document") or {}
    sections = [s for s in doc.get("sections") or [] if isinstance(s, dict)]
    overview = next((s for s in sections if s.get("kind") == "overview"), {"blocks": []})
    topics = []
    for b in overview.get("blocks") or []:
        t = b.get("topic")
        if t and t not in topics:
            topics.append(t)
    mods = module_blocks(doc)
    flows = doc.get("flows") or []
    claims = layer.get("claims") or []
    prose = " ".join(t for k, _, _, t in prose_pieces(doc) if k == "overview")
    return {
        "sections": [s.get("kind") for s in sections],
        "topics": topics,
        "modules": len(mods),
        "components": sum(1 for b in mods if len(module_files(b)) > 1),
        "flows": len(flows),
        "hops": sum(len(f.get("hops") or []) for f in flows),
        "claims": len(claims),
        "evidence": sorted(Counter(c.get("evidence") or "none" for c in claims).items(), key=lambda kv: (-kv[1], kv[0])),
        "overview_words": len(words(prose)),
    }


def overview_only(layer):
    doc = layer.get("document") or {}
    return {"sections": [s for s in doc.get("sections") or [] if isinstance(s, dict) and s.get("kind") == "overview"]}


def readability_counts(layer):
    errors, warnings = check_readability(overview_only(layer), strict=True)
    kinds = Counter()
    for w in warnings:
        parts = w.split(": ")
        kinds[parts[2] if len(parts) > 2 else "other"] += 1
    return len(errors), len(warnings), sorted(kinds.items())


# --------------------------------------------------------------------------
# Archive

def read_text(path):
    return path.read_text().strip() if path.is_file() else None


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def stores(root):
    """{repo: store dir} under root (the saved maps)."""
    if not root.is_dir():
        return {}
    return {repo_of_store(p.name): p for p in sorted(root.iterdir()) if (p / "map.json").is_file()}


def load(archive):
    a = {"run1": stores(archive / "run1"), "final": stores(archive / "after-repair")}
    a["repos"] = sorted(set(a["run1"]) | set(a["final"]))
    a["passes"] = {}
    run1_start = read_text(archive / "run1" / "start")
    for repo in a["repos"]:
        a["passes"][(repo, "run 1")] = {"start": run1_start, "end": None, "exit": None,
                                        "result": read_json(archive / "run1" / f"{repo}-result.json")}
        for name, sub in (("run 2", "run2"), ("repair", "repair")):
            d = archive / sub / repo
            a["passes"][(repo, name)] = {"start": read_text(d / "start"), "end": read_text(d / "end"),
                                         "exit": read_text(d / "exit"), "result": read_json(d / "result.json")}
    a["demo"] = []
    live = archive / "demo" / "live"
    for q in sorted(live.iterdir()) if live.is_dir() else []:
        events = []
        for f in sorted(q.glob("answer-*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    events.append(e.get("e", e))
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        a["demo"].append({"name": q.name, "qid": read_text(q / "qid"), "result": result})
    a["answers"] = {repo: read_json(p / "answers.json") or {} for repo, p in a["final"].items()}
    return a


def layer(stores_, repo):
    p = stores_.get(repo)
    return read_json(p / "map.json") if p else None


# --------------------------------------------------------------------------
# Output

def rule(ch="-"):
    return ch * WIDTH


def header(name, what):
    return ["", name, rule(), *textwrap.wrap(what, WIDTH)]


def wrap(text, indent="  "):
    """Text verbatim, wrapped at WIDTH on spaces only; its own line breaks are kept."""
    out = []
    for line in text.split("\n"):
        out += textwrap.wrap(line, WIDTH, initial_indent=indent, subsequent_indent=indent,
                             break_long_words=False, break_on_hyphens=False) or [""]
    return out


def fmt_min(m):
    return NOT_RECORDED if m is None else f"{m:.1f}"


def block_runs(a):
    lines = header("runs", "Wall clock from the launcher's start/end files; turns and cost from claude -p's "
                           "JSON result (total_cost_usd: cost at API list price; these were subscription runs).")
    lines.append(f"  {'repo':<12}{'pass':<9}{'wall min':>14}{'turns':>8}{'cost (list)':>13}{'exit':>14}")
    partial = False
    for repo in a["repos"]:
        total = 0.0
        for name in ("run 1", "run 2", "repair"):
            p = a["passes"][(repo, name)]
            r = p["result"] or {}
            turns = r.get("num_turns")
            mark = ""
            if r.get("result_index"):
                mark, partial = "*", True
            t = NOT_RECORDED if turns is None else f"{turns}{mark}"
            cost = r.get("total_cost_usd")
            total += cost or 0.0
            c = NOT_RECORDED if cost is None else f"${cost:.2f}"
            lines.append(f"  {repo:<12}{name:<9}{fmt_min(minutes_between(p['start'], p['end'])):>14}{t:>8}{c:>13}"
                         f"{p['exit'] if p['exit'] is not None else NOT_RECORDED:>14}")
        lines.append(f"  {repo:<12}{'total':<9}{'':>14}{'':>8}{f'${total:.2f}':>13}")
    lines.append("")
    lines.append("  claude -p's own session duration (duration_ms), minutes:")
    for repo in a["repos"]:
        for name in ("run 1", "run 2", "repair"):
            r = a["passes"][(repo, name)]["result"] or {}
            d = r.get("duration_ms")
            v = NOT_RECORDED if d is None else f"{d / 60000:.1f}" + ("*" if r.get("result_index") else "")
            lines.append(f"    {repo:<12}{name:<9}{v:>10}")
    if partial:
        lines += wrap("* result_index > 0: the session ended after background tasks, and the saved JSON is its "
                      "last result event only, so turns and duration_ms cover that last segment; cost "
                      "(total_cost_usd) is the whole session's.", "  ")
    return lines


def block_maps(a):
    lines = header("maps", "Run 1 (old Cartographer brief) against run 2 (Cartographer v2, start over), as saved "
                           "after the repair pass.")
    for repo in a["repos"]:
        for name, store in (("run 1", a["run1"]), ("run 2 after repair", a["final"])):
            m = layer(store, repo)
            lines.append(f"  {repo}, {name}")
            if m is None:
                lines.append(f"    {NOT_RECORDED}")
                continue
            s = map_stats(m)
            lines.append(f"    sections            {len(s['sections'])} ({', '.join(s['sections'])})")
            lines += textwrap.wrap(f"{len(s['topics'])} of {len(TOPICS)}"
                                   + (f" ({', '.join(s['topics'])})" if s["topics"] else ""), WIDTH,
                                   initial_indent="    Overview topics     ", subsequent_indent=" " * 24)
            lines.append(f"    module blocks       {s['modules']} ({s['components']} with more than one file)")
            lines.append(f"    flows               {s['flows']} ({s['hops']} hops)")
            lines.append(f"    claims              {s['claims']}")
            ev = ", ".join(f"{k} {v}" for k, v in s["evidence"])
            lines += textwrap.wrap(ev, WIDTH, initial_indent="    evidence labels     ",
                                   subsequent_indent=" " * 24)
            lines.append(f"    Overview words      {s['overview_words']}")
    return lines


def block_checker(a):
    lines = header("checker", "Map claims by Checker verdict. Run 2's state before repair and after each round is "
                              "derived from each claim's repairs history (a repair at round r means it was not "
                              "supported after round r-1) and its current check.")
    lines.append(f"  {'repo':<12}{'stage':<22}{'supported':>10}{'not supp.':>10}{'unchecked':>10}{'retired':>8}")
    for repo in a["repos"]:
        rows = []
        r1 = layer(a["run1"], repo)
        if r1:
            rows.append(("run 1 (no repair)", {s: Counter(claim_state(c, 99) for c in r1["claims"]).get(s, 0)
                                               for s in STATES}))
        fin = layer(a["final"], repo)
        if fin:
            for stage, label in ((0, "run 2 before repair"), (1, "after repair round 1"),
                                 (2, "after repair round 2")):
                rows.append((label, stage_counts(fin["claims"], stage)))
        for label, c in rows:
            lines.append(f"  {repo:<12}{label:<22}{c['supported']:>10}{c['not_supported']:>10}{c['unchecked']:>10}"
                         f"{c['retired']:>8}")
    lines.append("")
    lines.append("  What repair did, per round (one row per repair action taken):")
    lines.append(f"  {'repo':<12}{'round':>5}{'anchors replaced':>18}{'cite more lines':>17}{'rewritten':>11}"
                 f"{'retired':>9}")
    for repo in a["repos"]:
        fin = layer(a["final"], repo)
        summary = repair_summary(fin["claims"]) if fin else {}
        for rnd in sorted(summary):
            s = summary[rnd]
            lines.append(f"  {repo:<12}{rnd:>5}{s['anchor']:>18}{s['wider']:>17}{s['rewrite']:>11}{s['retire']:>9}")
    lines += wrap("anchors replaced = the claim's text kept, its anchors replaced; cite more lines = of those, "
                  "the new anchors cover more source lines than the old; rewritten = the claim's text "
                  "changed to say only what the cited lines show.", "  ")
    return lines


def block_readability(a):
    lines = header("readability", "honeyguide.readability.check_readability(strict=True), the check behind "
                                  "`map validate --strict`, on the Overview section alone.")
    lines.append(f"  {'repo':<12}{'map':<20}{'errors':>8}{'warnings':>10}  warnings by kind")
    for repo in a["repos"]:
        for name, store in (("run 1", a["run1"]), ("run 2 after repair", a["final"])):
            m = layer(store, repo)
            if m is None:
                lines.append(f"  {repo:<12}{name:<20}{NOT_RECORDED:>18}")
                continue
            e, w, kinds = readability_counts(m)
            k = ", ".join(f"{n} {c}" for n, c in kinds) or "none"
            lines += textwrap.wrap(k, WIDTH, initial_indent=f"  {repo:<12}{name:<20}{e:>8}{w:>10}  ",
                                   subsequent_indent=" " * 52)
    return lines


def find_question(a, qid):
    for repo in a["repos"]:
        ans = a["answers"].get(repo) or {}
        q = next((x for x in ans.get("questions") or [] if x.get("id") == qid), None)
        if q:
            r = next((x for x in ans.get("responses") or [] if x.get("id") == q.get("response")), None)
            return repo, q, r
    return None, None, None


def block_demo(a):
    lines = header("demo", "The two live questions, each answered by one claude -p session (stream-json "
                           "transcript; turns, duration_ms and cost from its final result event).")
    for d in a["demo"]:
        repo, q, resp = find_question(a, d["qid"])
        r = d["result"] or {}
        lines.append(f"  {d['name']}")
        lines.append(f"    question id       {d['qid'] or NOT_RECORDED}")
        lines.append(f"    repo              {repo or NOT_RECORDED}")
        if q:
            lines += textwrap.wrap(q.get("text", ""), WIDTH, initial_indent="    question          ",
                                   subsequent_indent=" " * 22)
        lines.append(f"    route (agent)     {(q or {}).get('agent') or NOT_RECORDED}")
        by_type = (r.get("subagent_stats") or {}).get("by_type") or {}
        subs = ", ".join(f"{k.split(':')[-1]} {v}" for k, v in sorted(by_type.items()))
        lines.append(f"    subagents run     {subs or NOT_RECORDED}")
        lines.append(f"    turns             {r.get('num_turns', NOT_RECORDED)}")
        dur = r.get("duration_ms")
        lines.append(f"    wall clock        {NOT_RECORDED if dur is None else f'{dur / 1000:.0f} s'} (claude -p)")
        if q and q.get("created_at") and q.get("answered_at"):
            secs = (parse_time(q["answered_at"]) - parse_time(q["created_at"])).total_seconds()
            lines.append(f"    posted->answered  {secs:.0f} s (answers.json timestamps)")
        cost = r.get("total_cost_usd")
        lines.append(f"    cost (list)       {NOT_RECORDED if cost is None else f'${cost:.2f}'}")
        claims = (resp or {}).get("claims") or []
        c = Counter(x.get("check") or "unchecked" for x in claims)
        lines.append(f"    answer claims     {len(claims)}")
        lines.append(f"    Checker           supported {c.get('supported', 0)}, "
                     f"not supported {c.get('not_supported', 0)}"
                     + "".join(f", {k} {v}" for k, v in sorted(c.items()) if k not in ("supported", "not_supported")))
    return lines


def first_narrowed(a):
    best = None
    for repo in a["repos"]:
        fin = layer(a["final"], repo)
        for claim in (fin or {}).get("claims") or []:
            for rnd, action, before, after, _, _ in repair_steps(claim):
                if action == "rewrite":
                    key = (claim["id"], rnd)
                    if best is None or key < best[0]:
                        best = (key, repo, rnd, before, after)
                    break
    return best


def block_examples(a):
    lines = header("examples", "Text printed verbatim from the saved maps (wrapped at 74 columns on spaces).")
    repo = "nanochat" if "nanochat" in a["repos"] else (a["repos"][0] if a["repos"] else None)
    r1 = layer(a["run1"], repo) if repo else None
    fin = layer(a["final"], repo) if repo else None
    lines.append(f"  (a) {repo}, run 1: the Overview's first block")
    ov = next((s for s in (r1 or {}).get("document", {}).get("sections", []) if s.get("kind") == "overview"), None)
    lines += wrap(block_text(ov["blocks"][0]), "      ") if ov and ov.get("blocks") else [f"      {NOT_RECORDED}"]
    lines.append("")
    lines.append(f"  (b) {repo}, run 2 after repair: the Purpose block(s)")
    ov = next((s for s in (fin or {}).get("document", {}).get("sections", []) if s.get("kind") == "overview"), None)
    purpose = [b for b in (ov or {}).get("blocks", []) if b.get("topic") == "purpose"]
    for i, b in enumerate(purpose):
        if i:
            lines.append("")
        lines += wrap(block_text(b), "      ")
    if not purpose:
        lines.append(f"      {NOT_RECORDED}")
    lines.append("")
    best = first_narrowed(a)
    lines += wrap(f"(c) a rewritten (narrowed) claim, picked as {NARROWED_RULE}", "  ")
    if best:
        (cid, _), crepo, rnd, before, after = best
        lines.append(f"      {cid} ({crepo}, repair round {rnd})")
        lines.append("      before:")
        lines += wrap(before, "        ")
        lines.append("      after:")
        lines += wrap(after, "        ")
    else:
        lines.append(f"      {NOT_RECORDED}")
    lines.append("")
    lines.append(f"  (d) {WRONGLY_PASSED}, the claim the Checker passed")
    claim = None
    for rp in a["repos"]:
        m = layer(a["final"], rp)
        claim = next((c for c in (m or {}).get("claims") or [] if c.get("id") == WRONGLY_PASSED), None)
        if claim:
            lines.append(f"      repo      {rp}")
            break
    if claim:
        lines.append("      text")
        lines += wrap(claim.get("text", ""), "        ")
        lines.append(f"      evidence  {claim.get('evidence')}")
        lines.append(f"      check     {claim.get('check')}"
                     + (f" (note: {claim['check_note']})" if claim.get("check_note") else " (no note)"))
        lines.append(f"      repairs   {len(claim.get('repairs') or [])}")
        for an in claim.get("anchors") or []:
            lines.append(f"      anchor    {an.get('path')}:{an.get('start')}-{an.get('end')}")
            lines += wrap(an.get("anchor", ""), "        ")
    else:
        lines.append(f"      {NOT_RECORDED}")
    return lines


def render(archive):
    a = load(archive)
    status(f"repos: {', '.join(a['repos'])}; demo questions: {len(a['demo'])}")
    lines = ["Honeyguide runs: receipts", rule("="),
             f"  archive   {archive.parent.name}/{archive.name} (read only)",
             f"  repos     {', '.join(a['repos'])}"]
    for block in (block_runs, block_maps, block_checker, block_readability, block_demo, block_examples):
        status(f"block {block.__name__[6:]}")
        lines += block(a)
    return "\n".join(line.rstrip() for line in lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = ap.parse_args(argv)
    sys.stdout.write(render(args.archive))


if __name__ == "__main__":
    main()
